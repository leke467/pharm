"""Phase 4 Acceptance Tests — Batches, Inventory & Basic Pricing (Desktop)."""
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
    Price,
    SyncEvent,
    AuditEvent,
)
from desktop.app.domain.enums import (
    BatchStatus,
    MovementType,
    PermissionCode,
)
from desktop.app.domain.exceptions import ValidationError, InsufficientStockError
from desktop.app.repositories.base_repository import BaseRepository
from desktop.app.services.inventory_service import InventoryService
from desktop.app.services.pricing_service import PricingService
from desktop.app.utils.date_utils import utc_now
from desktop.app.utils.uuid_utils import generate_uuid


class TestPhase4DesktopAcceptance:
    """Desktop acceptance tests for Phase 4 Batches, Inventory & Basic Pricing."""

    def _seed_context(self, db_manager, uses_storage_locations=False):
        org_id = generate_uuid()
        branch_id = generate_uuid()
        device_id = generate_uuid()
        cat_id = generate_uuid()
        product_id = generate_uuid()

        with db_manager.get_session() as db:
            org = Organization(id=org_id, name="Test Pharm", code="TPHARM")
            db.add(org)
            db.flush()

            branch = Branch(
                id=branch_id,
                organization_id=org_id,
                name="Main Branch",
                code="MB01",
                uses_storage_locations=uses_storage_locations,
                initial_stock_loaded=False,
            )
            db.add(branch)
            db.flush()

            device = Device(
                id=device_id,
                organization_id=org_id,
                branch_id=branch_id,
                name="POS-1",
                code="D01",
                device_identifier="HW-001",
            )
            db.add(device)
            db.flush()

            cat = Category(id=cat_id, organization_id=org_id, name="Analgesics")
            db.add(cat)
            db.flush()

            product = Product(
                id=product_id,
                organization_id=org_id,
                category_id=cat_id,
                sku="PARA-500",
                name="Paracetamol 500mg",
            )
            db.add(product)
            db.flush()

        session = Session(
            user_id=generate_uuid(),
            username="admin",
            full_name="Admin User",
            organization_id=org_id,
            organization_name="Test Pharm",
            branch_id=branch_id,
            branch_name="Main Branch",
            device_id=device_id,
            device_code="D01",
            permissions=[
                PermissionCode.INVENTORY_VIEW.value,
                PermissionCode.INVENTORY_ADJUST.value,
                PermissionCode.BATCHES_MANAGE.value,
                PermissionCode.BRANCHES_MANAGE.value,
                PermissionCode.PRICES_VIEW.value,
                PermissionCode.PRICES_MANAGE.value,
            ],
            roles=[],
            is_offline=False,
            is_org_admin=True,
            logged_in_at=utc_now(),
        )
        return org_id, branch_id, device_id, product_id, session

    def test_batch_lifecycle_and_recall(self, db_manager):
        """1. Batch creation, automatic EXPIRED status, and manual recall."""
        _, _, _, product_id, session = self._seed_context(db_manager)
        inv_service = InventoryService(db_manager)

        future_exp = (date.today() + timedelta(days=90)).isoformat()
        batch = inv_service.create_batch(
            session,
            product_id=product_id,
            batch_number="B-ACTIVE",
            expiry_date=future_exp,
            purchase_price="200.00",
        )
        assert batch.status == BatchStatus.ACTIVE.value

        past_exp = (date.today() - timedelta(days=2)).isoformat()
        exp_batch = inv_service.create_batch(
            session,
            product_id=product_id,
            batch_number="B-EXP",
            expiry_date=past_exp,
            purchase_price="180.00",
        )
        assert exp_batch.status == BatchStatus.EXPIRED.value

        recalled = inv_service.recall_batch(session, batch.id, reason="Safety recall")
        assert recalled.status == BatchStatus.RECALLED.value

    def test_storage_location_opt_in(self, db_manager):
        """2. Optional storage locations require branch.uses_storage_locations=True."""
        _, branch_id, _, _, session = self._seed_context(db_manager, uses_storage_locations=False)
        inv_service = InventoryService(db_manager)

        with pytest.raises(ValidationError):
            inv_service.create_storage_location(session, branch_id=branch_id, name="Shelf 1")

        with db_manager.get_session() as db:
            branch = db.query(Branch).filter_by(id=branch_id).first()
            branch.uses_storage_locations = True
            db.flush()

        loc = inv_service.create_storage_location(session, branch_id=branch_id, name="Shelf 1", location_type="SHELF")
        assert loc.name == "Shelf 1"

    def test_opening_balance_one_time_execution(self, db_manager):
        """3. Opening balance loads initial stock once, creates OPENING_BALANCE movements, blocks second run."""
        _, branch_id, _, product_id, session = self._seed_context(db_manager)
        inv_service = InventoryService(db_manager)

        batch = inv_service.create_batch(
            session,
            product_id=product_id,
            batch_number="OB-001",
            expiry_date=(date.today() + timedelta(days=365)).isoformat(),
            purchase_price="150.00",
        )

        res = inv_service.load_opening_balance(
            session,
            branch_id=branch_id,
            entries=[
                {
                    "batch_id": batch.id,
                    "quantity": 75,
                    "reorder_level": 10,
                }
            ],
        )
        assert len(res) == 1
        assert res[0].quantity_after == 75
        inv_list = inv_service.list_branch_inventory(branch_id, product_id)
        assert len(inv_list) == 1
        assert inv_list[0].quantity == 75

        # Second opening balance on same branch must fail
        with pytest.raises(ValidationError):
            inv_service.load_opening_balance(
                session,
                branch_id=branch_id,
                entries=[
                    {
                        "batch_id": batch.id,
                        "quantity": 10,
                    }
                ],
            )

    def test_stock_adjustments_and_immutability(self, db_manager):
        """4. Stock adjustments update BranchInventory via immutable movements; local negative stock is blocked."""
        _, branch_id, _, product_id, session = self._seed_context(db_manager)
        inv_service = InventoryService(db_manager)

        batch = inv_service.create_batch(
            session,
            product_id=product_id,
            batch_number="LOT-100",
            expiry_date=(date.today() + timedelta(days=180)).isoformat(),
            purchase_price="100.00",
        )

        # Add 30 units
        inv1, m1 = inv_service.adjust_stock(
            session,
            branch_id=branch_id,
            batch_id=batch.id,
            quantity_change=30,
            movement_type=MovementType.STOCK_ADJUSTMENT.value,
            notes="Initial count addition",
        )
        assert m1.quantity_after == 30
        assert inv1.quantity == 30

        # Attempt to deduct 40 units -> InsufficientStockError
        with pytest.raises(InsufficientStockError):
            inv_service.adjust_stock(
                session,
                branch_id=branch_id,
                batch_id=batch.id,
                quantity_change=-40,
                movement_type=MovementType.STOCK_ADJUSTMENT.value,
                notes="Too much deduction",
            )

        # Deduct 30 units -> hits 0 -> batch status becomes DEPLETED
        inv2, m2 = inv_service.adjust_stock(
            session,
            branch_id=branch_id,
            batch_id=batch.id,
            quantity_change=-30,
            movement_type=MovementType.DAMAGE.value,
            notes="Broken bottles",
        )
        assert m2.quantity_after == 0
        assert inv2.quantity == 0

        with db_manager.get_session() as db:
            b_obj = db.query(Batch).filter_by(id=batch.id).first()
            assert b_obj.status == BatchStatus.DEPLETED.value

            mv_obj = db.query(InventoryMovement).filter_by(id=m1.id).first()

        # BaseRepository blocks update and soft_delete on InventoryMovement
        repo = BaseRepository(db_manager.get_session)
        with pytest.raises(ValidationError, match="immutable"):
            repo.update(mv_obj, notes="Altered")
        with pytest.raises(ValidationError, match="immutable"):
            repo.soft_delete(mv_obj)

        # Check SyncEvent and AuditEvent were emitted
        with db_manager.get_session() as db:
            assert db.query(SyncEvent).filter_by(entity_type="inventory_movement").count() >= 2
            assert db.query(AuditEvent).filter_by(entity_type="inventory_movement").count() == 2

    def test_price_resolution_and_versioning(self, db_manager):
        """5. Price creation, atomic version switching, and branch-override vs org-default resolution."""
        org_id, branch_id, _, product_id, session = self._seed_context(db_manager)
        pricing_service = PricingService(db_manager)

        # Create org-wide price v1 (branch_id=None)
        p_org1 = pricing_service.set_price(
            session,
            product_id=product_id,
            selling_price="500.00",
            branch_id=None,
        )
        assert p_org1.version == 1
        assert p_org1.is_current is True

        # Create org-wide price v2 -> v1 becomes is_current=False
        p_org2 = pricing_service.set_price(
            session,
            product_id=product_id,
            selling_price="550.00",
            branch_id=None,
        )
        assert p_org2.version == 2

        with db_manager.get_session() as db:
            old_p = db.query(Price).filter_by(id=p_org1.id).first()
            assert old_p.is_current is False

        # Resolve price for branch (no branch override -> returns org v2 550.00)
        resolved_org = pricing_service.resolve_price(org_id, product_id, branch_id)
        assert Decimal(str(resolved_org.selling_price)) == Decimal("550.00")
        assert resolved_org.branch_id is None

        # Set branch-specific override price -> resolution returns branch override 600.00
        p_branch = pricing_service.set_price(
            session,
            product_id=product_id,
            selling_price="600.00",
            branch_id=branch_id,
        )
        assert p_branch.version == 1

        resolved_branch = pricing_service.resolve_price(org_id, product_id, branch_id)
        assert Decimal(str(resolved_branch.selling_price)) == Decimal("600.00")
        assert resolved_branch.branch_id == branch_id
