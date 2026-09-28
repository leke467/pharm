"""Phase 5 Acceptance Tests — Core Synchronization (Desktop)."""
from datetime import date, timedelta
from decimal import Decimal
import pytest
from desktop.app.auth.session import Session
from desktop.app.db.models import (
    Organization,
    Branch,
    Device,
    User,
    OfflineCredential,
    Category,
    Product,
    Batch,
    BranchInventory,
    InventoryMovement,
    SyncEvent,
    SyncCursor,
)
from desktop.app.domain.enums import MovementType, PermissionCode
from desktop.app.domain.exceptions import NetworkError
from desktop.app.services.inventory_service import InventoryService
from desktop.app.services.product_service import ProductService
from desktop.app.sync.sync_engine import SyncEngine
from desktop.app.utils.date_utils import utc_now
from desktop.app.utils.uuid_utils import generate_uuid


class FakeSyncApiClient:
    """In-memory mock API client simulating `/api/v1/sync/upload/` and `/api/v1/sync/download/`."""

    def __init__(self):
        self.uploaded_batches = []
        self.deliveries = []
        self.disabled_user_ids = []
        self.fail_with_network_error = False
        self._seq = 0

    def post(self, endpoint: str, data: dict = None) -> dict:
        if self.fail_with_network_error:
            raise NetworkError("Simulated 30s HTTP timeout")
        assert endpoint == "/api/v1/sync/upload/"
        self.uploaded_batches.append(data)
        results = []
        for ev in data["events"]:
            results.append({
                "event_id": ev["id"],
                "status": "PROCESSED",
                "server_received_at": utc_now(),
            })
            if ev["entity_type"] != "audit_event":
                self._seq += 1
                self.deliveries.append({
                    "sequence": self._seq,
                    "id": self._seq,
                    "entity_type": ev["entity_type"],
                    "entity_id": ev["entity_id"],
                    "operation": ev["operation"],
                    "payload": ev["payload"],
                    "target_scope": "ALL_BRANCHES",
                    "target_branch_id": data["branch_id"],
                    "source_branch_id": data["branch_id"],
                    "source_device_id": data["device_id"],
                    "source_event_id": ev["id"],
                })
        return {
            "device_id": data["device_id"],
            "branch_id": data["branch_id"],
            "results": results,
        }

    def get(self, endpoint: str, params: dict = None) -> dict:
        if self.fail_with_network_error:
            raise NetworkError("Simulated network error on download")
        assert endpoint == "/api/v1/sync/download/"
        last_seq = int(params.get("last_sequence", 0))
        req_device_id = str(params["device_id"])

        filtered = [
            d for d in self.deliveries
            if d["id"] > last_seq and str(d["source_device_id"]) != req_device_id
        ]
        new_seq = filtered[-1]["id"] if filtered else last_seq
        return {
            "deliveries": filtered,
            "last_sequence": new_seq,
            "has_more": False,
            "needs_full_resync": False,
            "disabled_user_ids": self.disabled_user_ids,
            "license_status": {"status": "ACTIVE", "plan": "ENTERPRISE"},
        }


class TestPhase5DesktopSyncAcceptance:
    """Desktop acceptance tests for Phase 5 Core Synchronization."""

    def _seed_org_and_branch(self, db_manager):
        org_id = generate_uuid()
        branch_id = generate_uuid()
        device_a_id = generate_uuid()
        device_b_id = generate_uuid()
        user_id = generate_uuid()

        with db_manager.get_session() as db:
            db.add(Organization(id=org_id, name="Sync Pharm", code="SPHARM"))
            db.flush()
            db.add(Branch(id=branch_id, organization_id=org_id, name="Main", code="MN01"))
            db.flush()
            db.add(Device(
                id=device_a_id,
                organization_id=org_id,
                branch_id=branch_id,
                name="POS A",
                code="DA",
                device_identifier="HW-DA",
            ))
            db.add(Device(
                id=device_b_id,
                organization_id=org_id,
                branch_id=branch_id,
                name="POS B",
                code="DB",
                device_identifier="HW-DB",
            ))
            db.add(User(
                id=user_id,
                organization_id=org_id,
                username="pharmacist1",
                full_name="Pharmacist One",
                is_active=True,
            ))
            db.add(OfflineCredential(
                user_id=user_id,
                offline_password_hash="hash",
                is_active=True,
                last_online_login_at=utc_now(),
            ))
            db.flush()

        session_a = Session(
            user_id=user_id,
            username="pharmacist1",
            full_name="Pharmacist One",
            organization_id=org_id,
            organization_name="Sync Pharm",
            branch_id=branch_id,
            branch_name="Main",
            device_id=device_a_id,
            device_code="DA",
            permissions=[p.value for p in PermissionCode],
            roles=[],
            is_offline=True,
            is_org_admin=True,
            logged_in_at=utc_now(),
        )
        return org_id, branch_id, device_a_id, device_b_id, user_id, session_a

    def test_upload_batch_ordering_and_correlation_group_preservation(self, db_manager):
        """
        1. Outbox events are ordered by dependency_level ASC, local_created_at ASC.
        2. Correlated events sharing correlation_id are never split across batch boundaries.
        3. Audit events default to max_retries=50 while standard events use max_retries=10.
        """
        org_id, branch_id, device_a_id, _, _, session_a = self._seed_org_and_branch(db_manager)
        prod_svc = ProductService(db_manager)
        inv_svc = InventoryService(db_manager)

        cat = prod_svc.create_category(session_a, name="Antibiotics")
        prod = prod_svc.create_product(
            session_a,
            sku="AMOX-250",
            name="Amoxicillin 250mg",
            category_id=cat.id,
        )
        batch = inv_svc.create_batch(
            session_a,
            product_id=prod.id,
            batch_number="B-AMOX-1",
            expiry_date=(date.today() + timedelta(days=365)).isoformat(),
            purchase_price="120.00",
        )
        inv_svc.adjust_stock(
            session_a,
            branch_id=branch_id,
            batch_id=batch.id,
            quantity_change=40,
            movement_type=MovementType.STOCK_ADJUSTMENT.value,
            notes="Initial stock",
        )

        # Verify max_retries=50 on audit_event and 10 on entity events
        with db_manager.get_session() as db:
            audit_sync = db.query(SyncEvent).filter_by(entity_type="audit_event").first()
            cat_sync = db.query(SyncEvent).filter_by(entity_type="category").first()
            assert audit_sync.max_retries == 50
            assert cat_sync.max_retries == 10

        fake_api = FakeSyncApiClient()
        engine = SyncEngine(fake_api, db_manager)

        # Request a batch with max_batch_size=3: each operation created 2 correlated events (entity + audit_event).
        # Because correlated groups of size 2 must never be split, max_batch_size=3 must return exactly 1 group (2 events)!
        small_batch = engine.get_upload_batch(branch_id=branch_id, max_batch_size=3)
        assert len(small_batch) == 2
        assert small_batch[0]["correlation_id"] == small_batch[1]["correlation_id"]
        assert small_batch[0]["dependency_level"] <= small_batch[1]["dependency_level"]

    def test_timeout_reverts_sending_to_pending_and_retries(self, db_manager):
        """
        On HTTP timeout / NetworkError during upload, SENDING events revert to PENDING,
        retry_count increments, and subsequent retry succeeds cleanly.
        """
        org_id, branch_id, device_a_id, _, _, session_a = self._seed_org_and_branch(db_manager)
        prod_svc = ProductService(db_manager)
        prod_svc.create_category(session_a, name="Pain Relief")

        fake_api = FakeSyncApiClient()
        fake_api.fail_with_network_error = True
        engine = SyncEngine(fake_api, db_manager)

        with pytest.raises(NetworkError):
            engine.upload_pending_events(branch_id=branch_id, device_id=device_a_id)

        with db_manager.get_session() as db:
            events = db.query(SyncEvent).filter_by(branch_id=branch_id).all()
            assert len(events) == 2
            for ev in events:
                assert ev.status == "PENDING"
                assert ev.retry_count == 1
                assert "timeout" in (ev.error_message or "").lower()

        assert engine.calculate_backoff_seconds(1) == 10
        assert engine.calculate_backoff_seconds(2) == 20
        assert engine.calculate_backoff_seconds(10) == 300

        # Restore connectivity and retry -> events transition to SENT
        fake_api.fail_with_network_error = False
        stats = engine.upload_pending_events(branch_id=branch_id, device_id=device_a_id)
        assert stats["processed"] == 2
        assert engine.get_pending_count(branch_id) == 0

    def test_end_to_end_upload_and_incremental_download_with_echo_suppression(self, db_manager):
        """
        Device A uploads Category, Product, Batch, and InventoryMovement.
        When Device A downloads -> 0 applied (echo suppressed).
        When Device B downloads onto a second database -> Category, Product, Batch, and
        InventoryMovement delta (+60 units) are applied, SyncCursor advances, and disabled user is locked out.
        """
        org_id, branch_id, device_a_id, device_b_id, user_id, session_a = self._seed_org_and_branch(db_manager)
        prod_svc = ProductService(db_manager)
        inv_svc = InventoryService(db_manager)

        cat = prod_svc.create_category(session_a, name="Cardiovascular")
        prod = prod_svc.create_product(
            session_a,
            sku="AMLOD-5",
            name="Amlodipine 5mg",
            category_id=cat.id,
        )
        batch = inv_svc.create_batch(
            session_a,
            product_id=prod.id,
            batch_number="B-AML-01",
            expiry_date=(date.today() + timedelta(days=365)).isoformat(),
            purchase_price="90.00",
        )
        inv_svc.adjust_stock(
            session_a,
            branch_id=branch_id,
            batch_id=batch.id,
            quantity_change=60,
            movement_type=MovementType.STOCK_ADJUSTMENT.value,
            notes="Received 60 packs",
        )

        fake_api = FakeSyncApiClient()
        engine = SyncEngine(fake_api, db_manager)

        # Upload all pending events from Device A
        up_stats = engine.upload_pending_events(branch_id=branch_id, device_id=device_a_id)
        assert up_stats["processed"] == 8  # 4 entities + 4 audit events

        # Device A downloads -> echo suppressed!
        dl_a = engine.download_updates(organization_id=org_id, branch_id=branch_id, device_id=device_a_id)
        assert dl_a["applied"] == 0

        # Simulate Device B deleting local product/batch/inventory state (or fresh branch DB) and downloading
        with db_manager.get_session() as db:
            db.query(InventoryMovement).delete()
            db.query(BranchInventory).delete()
            db.query(Batch).delete()
            db.query(Product).delete()
            db.query(Category).delete()
            db.flush()

        fake_api.disabled_user_ids = [user_id]
        dl_b = engine.download_updates(organization_id=org_id, branch_id=branch_id, device_id=device_b_id)
        assert dl_b["applied"] == 4
        assert dl_b["last_sequence"] == 4

        with db_manager.get_session() as db:
            assert db.query(Category).filter_by(id=cat.id).first() is not None
            assert db.query(Product).filter_by(id=prod.id).first() is not None
            assert db.query(Batch).filter_by(id=batch.id).first() is not None
            inv_b = db.query(BranchInventory).filter_by(branch_id=branch_id, batch_id=batch.id).first()
            assert inv_b is not None
            assert inv_b.quantity == 60

            cursor_b = db.query(SyncCursor).filter_by(device_id=device_b_id).first()
            assert cursor_b.last_server_sequence == 4

            # Disabled user locked out locally
            u = db.query(User).filter_by(id=user_id).first()
            cred = db.query(OfflineCredential).filter_by(user_id=user_id).first()
            assert u.is_active is False
            assert cred.is_active is False
