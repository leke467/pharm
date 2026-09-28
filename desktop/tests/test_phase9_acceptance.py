"""Phase 9 Acceptance Tests — Stock Counts & Approval (Desktop)."""
from datetime import date, timedelta
from decimal import Decimal
import pytest
from desktop.app.auth.session import Session
from desktop.app.db.models import (
    Organization,
    Branch,
    Device,
    Category,
    Product,
    Batch,
    BranchInventory,
    InventoryMovement,
    StockCount,
    StockCountItem,
    SyncEvent,
    User,
)
from desktop.app.domain.enums import (
    ApprovalStatus,
    MovementType,
    PermissionCode,
    StockCountStatus,
)
from desktop.app.domain.exceptions import ValidationError
from desktop.app.services.inventory_service import InventoryService
from desktop.app.services.stock_count_service import StockCountService
from desktop.app.utils.date_utils import utc_now
from desktop.app.utils.uuid_utils import generate_uuid


class TestPhase9DesktopStockCountAcceptance:
    """Desktop acceptance tests for Phase 9 Stock Counts & Approval."""

    def _seed(self, db_manager):
        org_id = generate_uuid()
        branch_id = generate_uuid()
        device_id = generate_uuid()
        user_id = generate_uuid()
        cat_id = generate_uuid()
        product_id = generate_uuid()

        with db_manager.get_session() as db:
            db.add(Organization(id=org_id, name="PrimeCare Pharmacy", code="PRIM"))
            db.flush()
            db.add(Branch(id=branch_id, organization_id=org_id, name="Surulere Branch", code="SR01"))
            db.flush()
            db.add(Device(
                id=device_id,
                organization_id=org_id,
                branch_id=branch_id,
                name="Stock Terminal 1",
                code="ST01",
                device_identifier="HW-SR-ST01",
            ))
            db.flush()
            db.add(User(
                id=user_id,
                organization_id=org_id,
                username="auditor1",
                full_name="Fatima Bello",
                email="fatima@primecare.ng",
            ))
            db.flush()
            db.add(Category(id=cat_id, organization_id=org_id, name="Antibiotics"))
            db.flush()
            db.add(Product(
                id=product_id,
                organization_id=org_id,
                category_id=cat_id,
                sku="AMOX-500",
                name="Amoxicillin 500mg Caps",
            ))
            db.flush()

        session = Session(
            user_id=user_id,
            username="auditor1",
            full_name="Fatima Bello",
            organization_id=org_id,
            organization_name="PrimeCare Pharmacy",
            branch_id=branch_id,
            branch_name="Surulere Branch",
            device_id=device_id,
            device_code="ST01",
            permissions=[p.value for p in PermissionCode],
            roles=[],
            is_offline=True,
            is_org_admin=True,
            logged_in_at=utc_now(),
        )

        inv_svc = InventoryService(db_manager)
        batch = inv_svc.create_batch(
            session,
            product_id=product_id,
            batch_number="AMX-001",
            expiry_date=(date.today() + timedelta(days=250)).isoformat(),
            purchase_price="700.00",
        )
        inv_svc.adjust_stock(
            session,
            branch_id=branch_id,
            batch_id=batch.id,
            quantity_change=30,
            notes="Initial stock load",
        )
        return org_id, branch_id, device_id, batch, session

    def test_stock_count_lifecycle_and_negative_guard(self, db_manager):
        """
        1. Start stock count -> IN_PROGRESS. Starting another in same scope raises ValidationError.
        2. Submit count: 34 counted (system 30, variance +4).
        3. Negative Quantity Guard: if variance is negative and exceeds live stock, approval is blocked.
        4. Approve variance (+4): BranchInventory updated to 34, COUNT_VARIANCE movement recorded.
        5. Correlated SyncEvents are emitted with correlation_id.
        """
        org_id, branch_id, device_id, batch, session = self._seed(db_manager)
        sc_svc = StockCountService(db_manager)

        # 1. Start Stock Count
        sc = sc_svc.start_stock_count(
            session, count_type="FULL_BRANCH", notes="Quarterly inventory audit"
        )
        assert sc.status == StockCountStatus.IN_PROGRESS.value

        # Local concurrency guard: another count in same scope is blocked
        with pytest.raises(ValidationError, match="already in progress"):
            sc_svc.start_stock_count(session, count_type="FULL_BRANCH")

        # 2. Submit count: counted 34 (+4 variance)
        sub_res = sc_svc.submit_stock_count(
            session,
            stock_count_id=sc.id,
            items=[{"batch_id": batch.id, "counted_quantity": 34}],
            notes="Count completed by auditor",
        )
        assert sub_res["status"] == StockCountStatus.SUBMITTED.value

        with db_manager.get_session() as db:
            sci = db.query(StockCountItem).filter_by(stock_count_id=sc.id).first()
            sci_id = sci.id
            assert sci.system_quantity == 30
            assert sci.counted_quantity == 34
            assert sci.variance == 4

        # 3. Test Negative Quantity Guard with artificial negative variance
        with db_manager.get_session() as db:
            sci_row = db.query(StockCountItem).filter_by(id=sci_id).first()
            sci_row.variance = -35  # live is 30 -> 30 + (-35) = -5 < 0
            db.flush()

        with pytest.raises(ValidationError, match="Approval blocked: live quantity"):
            sc_svc.approve_stock_count(
                session,
                stock_count_id=sc.id,
                reviews=[{"stock_count_item_id": sci_id, "action": "APPROVE"}],
            )

        # Reset variance to +4 and approve cleanly
        with db_manager.get_session() as db:
            sci_row = db.query(StockCountItem).filter_by(id=sci_id).first()
            sci_row.variance = 4
            db.flush()

        # 4. Approve Stock Count
        appr_res = sc_svc.approve_stock_count(
            session,
            stock_count_id=sc.id,
            reviews=[{"stock_count_item_id": sci_id, "action": "APPROVE"}],
            notes="Approved by manager after verification",
        )
        assert appr_res["status"] == StockCountStatus.APPROVED.value

        with db_manager.get_session() as db:
            inv = db.query(BranchInventory).filter_by(batch_id=batch.id).first()
            assert inv.quantity == 34  # 30 + 4 variance
            mov = (
                db.query(InventoryMovement)
                .filter_by(
                    batch_id=batch.id,
                    movement_type=MovementType.COUNT_VARIANCE.value,
                )
                .first()
            )
            assert mov is not None
            assert mov.quantity_change == 4

            # 5. Check sync events
            corr_events = (
                db.query(SyncEvent)
                .filter_by(correlation_id=appr_res["correlation_id"])
                .all()
            )
            entity_types = {e.entity_type for e in corr_events}
            assert {"stock_count", "stock_count_item", "inventory_movement", "audit_event"}.issubset(
                entity_types
            )
