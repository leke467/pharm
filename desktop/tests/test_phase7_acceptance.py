"""Phase 7 Acceptance Tests — Returns & Voids (Desktop)."""
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
    BranchInventory,
    InventoryMovement,
    Sale,
    SaleItem,
    SaleReturn,
    SaleReturnItem,
    SyncEvent,
)
from desktop.app.domain.enums import MovementType, PermissionCode, SaleStatus
from desktop.app.domain.exceptions import ValidationError, PermissionDeniedError
from desktop.app.domain.pos_cart import POSCart
from desktop.app.repositories.base_repository import BaseRepository
from desktop.app.services.inventory_service import InventoryService
from desktop.app.services.pricing_service import PricingService
from desktop.app.services.sales_service import SalesService
from desktop.app.utils.date_utils import utc_now
from desktop.app.utils.uuid_utils import generate_uuid


class TestPhase7DesktopReturnsAndVoidsAcceptance:
    """Desktop acceptance tests for Phase 7 Returns & Voids."""

    def _seed_and_create_sale(self, db_manager):
        org_id = generate_uuid()
        branch_id = generate_uuid()
        device_id = generate_uuid()
        cat_id = generate_uuid()
        product_id = generate_uuid()

        with db_manager.get_session() as db:
            db.add(Organization(id=org_id, name="CarePlus Pharmacy", code="CARE"))
            db.flush()
            db.add(Branch(id=branch_id, organization_id=org_id, name="Lekki Branch", code="LK01"))
            db.flush()
            db.add(Device(
                id=device_id,
                organization_id=org_id,
                branch_id=branch_id,
                name="Counter 1",
                code="C01",
                device_identifier="HW-LK-C01",
            ))
            db.flush()
            db.add(Category(id=cat_id, organization_id=org_id, name="Antimalarials"))
            db.flush()
            db.add(Product(
                id=product_id,
                organization_id=org_id,
                category_id=cat_id,
                sku="COARTEM-80",
                name="Coartem 80/480mg",
            ))
            db.flush()

        session = Session(
            user_id=generate_uuid(),
            username="pharmacist1",
            full_name="Chidi Nwosu",
            organization_id=org_id,
            organization_name="CarePlus Pharmacy",
            branch_id=branch_id,
            branch_name="Lekki Branch",
            device_id=device_id,
            device_code="C01",
            permissions=[p.value for p in PermissionCode],
            roles=[],
            is_offline=True,
            is_org_admin=True,
            logged_in_at=utc_now(),
        )

        inv_svc = InventoryService(db_manager)
        pricing_svc = PricingService(db_manager)
        sales_svc = SalesService(db_manager)

        pricing_svc.set_price(session, product_id=product_id, selling_price="2500.00")
        batch = inv_svc.create_batch(
            session,
            product_id=product_id,
            batch_number="COA-001",
            expiry_date=(date.today() + timedelta(days=200)).isoformat(),
            purchase_price="1800.00",
        )
        inv_svc.adjust_stock(
            session,
            branch_id=branch_id,
            batch_id=batch.id,
            quantity_change=20,
            notes="Initial stock load",
        )

        cart = POSCart()
        cart.add_item(
            product_id=product_id,
            product_name="Coartem 80/480mg",
            sku="COARTEM-80",
            quantity=10,
            unit_price="2500.00",
        )
        checkout_res = sales_svc.checkout_cart(
            session,
            cart=cart,
            payments=[{"payment_method": "CASH", "amount": "25000.00"}],
        )
        return session, batch, sales_svc, checkout_res["sale_id"]

    def test_partial_and_full_return_lifecycle_and_immutability(self, db_manager):
        """
        1. Partial return (3 of 10) creates SaleReturn + SaleReturnItem, restores +3 to batch,
           sets Sale.status = PARTIALLY_RETURNED, and emits correlated SyncEvents.
        2. Over-return attempt (8 units when 7 remain) raises ValidationError.
        3. Returning remaining 7 units sets Sale.status = RETURNED and restores +7 to batch.
        4. BaseRepository blocks deletion of SaleReturn and SaleReturnItem and updates to SaleReturnItem.
        """
        session, batch, sales_svc, sale_id = self._seed_and_create_sale(db_manager)

        with db_manager.get_session() as db:
            si = db.query(SaleItem).filter_by(sale_id=sale_id).first()
            sale_item_id = si.id

        # 1. Partial return of 3 units
        ret1 = sales_svc.return_sale(
            session,
            original_sale_id=sale_id,
            items=[{"sale_item_id": sale_item_id, "quantity": 3}],
            reason="Customer bought 3 packs too many",
        )
        assert ret1["sale_status"] == SaleStatus.PARTIALLY_RETURNED.value
        assert ret1["refund_amount"] == Decimal("7500.00")

        with db_manager.get_session() as db:
            inv = db.query(BranchInventory).filter_by(batch_id=batch.id).first()
            assert inv.quantity == 13  # 20 - 10 + 3

            corr_events = (
                db.query(SyncEvent)
                .filter_by(correlation_id=ret1["correlation_id"])
                .all()
            )
            entity_types = {e.entity_type for e in corr_events}
            assert {
                "sale_return",
                "sale_return_item",
                "sale",
                "inventory_movement",
                "audit_event",
            }.issubset(entity_types)

        # 2. Cannot void a partially returned sale
        with pytest.raises(ValidationError, match="partial returns"):
            sales_svc.void_sale(session, sale_id=sale_id, reason="Try void after partial return")

        # 3. Over-return attempt (8 units when only 7 remain)
        with pytest.raises(ValidationError, match="only 7 units remain returnable"):
            sales_svc.return_sale(
                session,
                original_sale_id=sale_id,
                items=[{"sale_item_id": sale_item_id, "quantity": 8}],
                reason="Over return",
            )

        # 4. Return remaining 7 units -> Sale.status = RETURNED
        ret2 = sales_svc.return_sale(
            session,
            original_sale_id=sale_id,
            items=[{"sale_item_id": sale_item_id, "quantity": 7}],
            reason="Returned remaining packs",
        )
        assert ret2["sale_status"] == SaleStatus.RETURNED.value
        assert ret2["refund_amount"] == Decimal("17500.00")

        with db_manager.get_session() as db:
            inv = db.query(BranchInventory).filter_by(batch_id=batch.id).first()
            assert inv.quantity == 20

            repo = BaseRepository(db_manager.session_factory)
            sr = db.query(SaleReturn).filter_by(id=ret1["sale_return_id"]).first()
            sri = db.query(SaleReturnItem).filter_by(sale_return_id=sr.id).first()
            with pytest.raises(ValidationError):
                repo.soft_delete(sr, session=db)
            with pytest.raises(ValidationError):
                repo.soft_delete(sri, session=db)
            with pytest.raises(ValidationError):
                repo.update(sri, session=db, quantity=1)

    def test_void_sale_restores_stock_and_enforces_reason_and_permissions(self, db_manager):
        """
        1. Voiding requires SALES_VOID permission and a non-empty reason.
        2. Voiding a completed sale sets Sale.status = VOIDED and restores full batch stock.
        """
        session, batch, sales_svc, sale_id = self._seed_and_create_sale(db_manager)

        # Empty reason rejected
        with pytest.raises(ValidationError, match="reason is required"):
            sales_svc.void_sale(session, sale_id=sale_id, reason="  ")

        # Missing SALES_VOID permission rejected
        no_perm_session = Session(
            user_id=session.user_id,
            username="cashier_no_void",
            full_name="No Void Cashier",
            organization_id=session.organization_id,
            organization_name=session.organization_name,
            branch_id=session.branch_id,
            branch_name=session.branch_name,
            device_id=session.device_id,
            device_code=session.device_code,
            permissions=[PermissionCode.SALES_SELL.value],
            roles=[],
            is_offline=True,
            is_org_admin=False,
            logged_in_at=utc_now(),
        )
        with pytest.raises(PermissionDeniedError):
            sales_svc.void_sale(no_perm_session, sale_id=sale_id, reason="Void attempt")

        # Valid void
        void_res = sales_svc.void_sale(
            session, sale_id=sale_id, reason="Customer cancelled before leaving counter"
        )
        assert void_res["status"] == SaleStatus.VOIDED.value
        assert void_res["refund_amount"] == Decimal("25000.00")

        with db_manager.get_session() as db:
            inv = db.query(BranchInventory).filter_by(batch_id=batch.id).first()
            assert inv.quantity == 20
            mov = (
                db.query(InventoryMovement)
                .filter_by(
                    batch_id=batch.id,
                    movement_type=MovementType.SALE_RETURN.value,
                )
                .first()
            )
            assert mov is not None
            assert mov.quantity_change == 10
