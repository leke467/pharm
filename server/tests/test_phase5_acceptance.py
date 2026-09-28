"""Phase 5 Acceptance Tests — Core Synchronization (Server)."""
import uuid
from datetime import date, timedelta
import pytest
from django.utils import timezone
from apps.audit.models import AuditEvent
from apps.branches.models import Branch, Device
from apps.inventory.models import Batch, BranchInventory, InventoryMovement
from apps.products.models import Category, Product
from apps.sync.models import ProcessedEvent, SyncDelivery
from apps.users.models import User
from shared.enums import AuditAction, AuditSource, MovementType


@pytest.mark.django_db
class TestPhase5ServerSyncAcceptance:
    """Server acceptance tests for Phase 5 Core Synchronization."""

    def test_correlated_atomic_upload_and_idempotency(
        self, authenticated_client, test_user, test_organization, test_branch, test_device
    ):
        """
        1. Correlated events sharing a correlation_id are sorted by dependency_level and processed atomically.
        2. Re-uploading the same event_id returns DUPLICATE_IGNORED and never duplicates inventory movements.
        """
        corr_id = str(uuid.uuid4())
        cat_id = str(uuid.uuid4())
        prod_id = str(uuid.uuid4())
        batch_id = str(uuid.uuid4())
        mov_id = str(uuid.uuid4())
        audit_id = str(uuid.uuid4())
        now_str = timezone.now().isoformat()

        # Deliberately send in reverse dependency order to prove server sorts by dependency_level
        events = [
            {
                "id": str(uuid.uuid4()),
                "entity_type": "audit_event",
                "entity_id": audit_id,
                "operation": "CREATE",
                "payload": {
                    "id": audit_id,
                    "branch_id": str(test_branch.id),
                    "user_id": str(test_user.id),
                    "action": AuditAction.STOCK_RECEIVED.value,
                    "entity_type": "inventory_movement",
                    "entity_id": mov_id,
                    "local_timestamp": now_str,
                },
                "correlation_id": corr_id,
                "dependency_level": 8,
                "schema_version": 1,
                "local_created_at": now_str,
            },
            {
                "id": str(uuid.uuid4()),
                "entity_type": "inventory_movement",
                "entity_id": mov_id,
                "operation": "CREATE",
                "payload": {
                    "id": mov_id,
                    "branch_id": str(test_branch.id),
                    "batch_id": batch_id,
                    "movement_type": MovementType.STOCK_RECEIVED.value,
                    "quantity_change": 50,
                    "reference_type": "opening_balance",
                    "reference_id": str(test_branch.id),
                    "user_id": str(test_user.id),
                    "local_timestamp": now_str,
                },
                "correlation_id": corr_id,
                "dependency_level": 7,
                "schema_version": 1,
                "local_created_at": now_str,
            },
            {
                "id": str(uuid.uuid4()),
                "entity_type": "batch",
                "entity_id": batch_id,
                "operation": "CREATE",
                "payload": {
                    "id": batch_id,
                    "product_id": prod_id,
                    "batch_number": "SYNC-B01",
                    "expiry_date": (date.today() + timedelta(days=365)).isoformat(),
                    "purchase_price": "300.00",
                    "received_date": date.today().isoformat(),
                },
                "correlation_id": corr_id,
                "dependency_level": 3,
                "schema_version": 1,
                "local_created_at": now_str,
            },
            {
                "id": str(uuid.uuid4()),
                "entity_type": "product",
                "entity_id": prod_id,
                "operation": "CREATE",
                "payload": {
                    "id": prod_id,
                    "sku": "SYNC-PROD-1",
                    "name": "Synced Artemether",
                    "category_id": cat_id,
                },
                "correlation_id": corr_id,
                "dependency_level": 2,
                "schema_version": 1,
                "local_created_at": "2026-01-01T10:00:02Z",
            },
            {
                "id": str(uuid.uuid4()),
                "entity_type": "category",
                "entity_id": cat_id,
                "operation": "CREATE",
                "payload": {
                    "id": cat_id,
                    "name": "Antimalarials",
                },
                "correlation_id": corr_id,
                "dependency_level": 2,
                "schema_version": 1,
                "local_created_at": "2026-01-01T10:00:01Z",
            },
        ]

        res = authenticated_client.post(
            "/api/v1/sync/upload/",
            {
                "device_id": str(test_device.id),
                "branch_id": str(test_branch.id),
                "events": events,
            },
            format="json",
        )
        assert res.status_code == 200, res.data
        statuses = [r["status"] for r in res.data["results"]]
        assert statuses == ["PROCESSED"] * 5

        assert Category.objects.filter(id=cat_id).exists()
        assert Product.objects.filter(id=prod_id).exists()
        assert Batch.objects.filter(id=batch_id).exists()
        inv = BranchInventory.objects.get(branch=test_branch, batch_id=batch_id)
        assert inv.quantity == 50

        # Re-upload the exact same batch -> idempotency returns DUPLICATE_IGNORED and stock stays 50!
        res_dup = authenticated_client.post(
            "/api/v1/sync/upload/",
            {
                "device_id": str(test_device.id),
                "branch_id": str(test_branch.id),
                "events": events,
            },
            format="json",
        )
        assert res_dup.status_code == 200
        dup_statuses = [r["status"] for r in res_dup.data["results"]]
        assert dup_statuses == ["DUPLICATE_IGNORED"] * 5

        inv.refresh_from_db()
        assert inv.quantity == 50
        assert InventoryMovement.objects.filter(id=mov_id).count() == 1

    def test_correlated_group_atomic_rollback_on_failure(
        self, authenticated_client, test_organization, test_branch, test_device
    ):
        """
        If one event in a correlation_id group fails, the entire correlation_id group rolls back,
        while an independent correlation_id group in the same upload succeeds.
        """
        good_corr = str(uuid.uuid4())
        bad_corr = str(uuid.uuid4())
        good_cat_id = str(uuid.uuid4())
        bad_cat_id = str(uuid.uuid4())
        now_str = timezone.now().isoformat()

        events = [
            {
                "id": str(uuid.uuid4()),
                "entity_type": "category",
                "entity_id": good_cat_id,
                "operation": "CREATE",
                "payload": {"id": good_cat_id, "name": "Valid Category"},
                "correlation_id": good_corr,
                "dependency_level": 2,
                "schema_version": 1,
                "local_created_at": now_str,
            },
            {
                "id": str(uuid.uuid4()),
                "entity_type": "category",
                "entity_id": bad_cat_id,
                "operation": "CREATE",
                "payload": {"id": bad_cat_id, "name": "Should Rollback Category"},
                "correlation_id": bad_corr,
                "dependency_level": 2,
                "schema_version": 1,
                "local_created_at": now_str,
            },
            {
                "id": str(uuid.uuid4()),
                "entity_type": "unsupported_bogus_type",
                "entity_id": str(uuid.uuid4()),
                "operation": "CREATE",
                "payload": {},
                "correlation_id": bad_corr,
                "dependency_level": 5,
                "schema_version": 1,
                "local_created_at": now_str,
            },
        ]

        res = authenticated_client.post(
            "/api/v1/sync/upload/",
            {
                "device_id": str(test_device.id),
                "branch_id": str(test_branch.id),
                "events": events,
            },
            format="json",
        )
        assert res.status_code == 200
        results = res.data["results"]
        assert results[0]["status"] == "PROCESSED"
        assert results[1]["status"] == "FAILED"
        assert results[2]["status"] == "FAILED"

        # Good group committed; bad group rolled back completely
        assert Category.objects.filter(id=good_cat_id).exists()
        assert not Category.objects.filter(id=bad_cat_id).exists()

    def test_device_echo_suppression_and_branch_scoping_on_download(
        self, authenticated_client, test_user, test_organization, test_branch, test_device
    ):
        """
        Verify:
        - Uploading device (test_device in test_branch) does NOT receive its own events on download.
        - Peer device B in the SAME branch (test_branch) DOES receive both ALL_BRANCHES and SPECIFIC_BRANCH events.
        - Device C in a DIFFERENT branch (branch_2) receives ALL_BRANCHES events (e.g. category)
          but NOT test_branch's SPECIFIC_BRANCH events (e.g. storage_location).
        """
        device_b = Device.objects.create(
            organization=test_organization,
            branch=test_branch,
            name="Branch 1 POS 2",
            code="D02",
            device_identifier="HW-B1-D02",
        )
        branch_2 = Branch.objects.create(
            organization=test_organization,
            name="Second Branch",
            code="BR02",
            uses_storage_locations=True,
        )
        device_c = Device.objects.create(
            organization=test_organization,
            branch=branch_2,
            name="Branch 2 POS 1",
            code="D01",
            device_identifier="HW-B2-D01",
        )

        cat_id = str(uuid.uuid4())
        loc_id = str(uuid.uuid4())
        now_str = timezone.now().isoformat()

        upload_res = authenticated_client.post(
            "/api/v1/sync/upload/",
            {
                "device_id": str(test_device.id),
                "branch_id": str(test_branch.id),
                "events": [
                    {
                        "id": str(uuid.uuid4()),
                        "entity_type": "category",
                        "entity_id": cat_id,
                        "operation": "CREATE",
                        "payload": {"id": cat_id, "name": "Vitamins"},
                        "dependency_level": 2,
                        "schema_version": 1,
                        "local_created_at": now_str,
                    },
                    {
                        "id": str(uuid.uuid4()),
                        "entity_type": "storage_location",
                        "entity_id": loc_id,
                        "operation": "CREATE",
                        "payload": {
                            "id": loc_id,
                            "branch_id": str(test_branch.id),
                            "name": "Cold Room 1",
                        },
                        "dependency_level": 4,
                        "schema_version": 1,
                        "local_created_at": now_str,
                    },
                ],
            },
            format="json",
        )
        assert upload_res.status_code == 200

        # 1. Source device (test_device) downloads -> 0 deliveries (echo suppressed!)
        dl_source = authenticated_client.get(
            f"/api/v1/sync/download/?branch_id={test_branch.id}&device_id={test_device.id}&last_sequence=0"
        )
        assert dl_source.status_code == 200
        assert len(dl_source.data["deliveries"]) == 0

        # 2. Peer device B in SAME branch downloads -> receives both category AND storage_location (2 deliveries)
        dl_peer_same_branch = authenticated_client.get(
            f"/api/v1/sync/download/?branch_id={test_branch.id}&device_id={device_b.id}&last_sequence=0"
        )
        assert dl_peer_same_branch.status_code == 200
        peer_types = [d["entity_type"] for d in dl_peer_same_branch.data["deliveries"]]
        assert "category" in peer_types
        assert "storage_location" in peer_types

        # 3. Device C in Branch 2 downloads -> receives category (ALL_BRANCHES) but NOT Branch 1's storage_location
        dl_other_branch = authenticated_client.get(
            f"/api/v1/sync/download/?branch_id={branch_2.id}&device_id={device_c.id}&last_sequence=0"
        )
        assert dl_other_branch.status_code == 200
        other_types = [d["entity_type"] for d in dl_other_branch.data["deliveries"]]
        assert "category" in other_types
        assert "storage_location" not in other_types
        assert "license_status" in dl_other_branch.data

    def test_disabled_user_offline_action_flagged_on_sync(
        self, authenticated_client, test_organization, test_branch, test_device
    ):
        """
        When an offline event is uploaded whose acting user has since been disabled on the server,
        the server honors the valid offline record AND generates a DISABLED_USER_ACTION security audit event.
        """
        disabled_user = User.objects.create_user(
            username="ex_cashier",
            organization_id=test_organization.id,
            password="Password123!",
            full_name="Ex Cashier",
            is_active=False,
        )
        cat_id = str(uuid.uuid4())
        now_str = timezone.now().isoformat()

        res = authenticated_client.post(
            "/api/v1/sync/upload/",
            {
                "device_id": str(test_device.id),
                "branch_id": str(test_branch.id),
                "events": [
                    {
                        "id": str(uuid.uuid4()),
                        "entity_type": "category",
                        "entity_id": cat_id,
                        "operation": "CREATE",
                        "payload": {
                            "id": cat_id,
                            "name": "Offline Created By Disabled User",
                            "user_id": str(disabled_user.id),
                        },
                        "dependency_level": 2,
                        "schema_version": 1,
                        "local_created_at": now_str,
                    }
                ],
            },
            format="json",
        )
        assert res.status_code == 200
        assert res.data["results"][0]["status"] == "PROCESSED"
        assert AuditEvent.objects.filter(
            organization=test_organization,
            user_id=disabled_user.id,
            action=AuditAction.DISABLED_USER_ACTION.value,
            source=AuditSource.SERVER_SYNC.value,
        ).exists()
