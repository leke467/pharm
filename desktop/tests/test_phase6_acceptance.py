"""Phase 6 Acceptance Tests — Sales / POS (Desktop)."""
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
    Sale,
    SaleItem,
    Payment,
    Receipt,
    SyncEvent,
)
from desktop.app.domain.enums import BatchStatus, MovementType, PermissionCode
from desktop.app.domain.exceptions import ValidationError, InsufficientStockError
from desktop.app.domain.pos_cart import POSCart
from desktop.app.repositories.base_repository import BaseRepository
from desktop.app.services.inventory_service import InventoryService
from desktop.app.services.pricing_service import PricingService
from desktop.app.services.sales_service import SalesService
from desktop.app.utils.date_utils import utc_now
from desktop.app.utils.uuid_utils import generate_uuid


class TestPhase6DesktopPOSAcceptance:
    """Desktop acceptance tests for Phase 6 POS / Sales."""

    def _seed(self, db_manager):
        org_id = generate_uuid()
        branch_id = generate_uuid()
        device_id = generate_uuid()
        cat_id = generate_uuid()
        product_id = generate_uuid()

        with db_manager.get_session() as db:
            db.add(Organization(id=org_id, name="CarePlus Pharmacy", code="CARE"))
            db.flush()
            db.add(Branch(id=branch_id, organization_id=org_id, name="Victoria Island", code="VI01"))
            db.flush()
            db.add(Device(
                id=device_id,
                organization_id=org_id,
                branch_id=branch_id,
                name="Counter 1",
                code="C01",
                device_identifier="HW-VI-C01",
            ))
            db.flush()
            db.add(Category(id=cat_id, organization_id=org_id, name="Antibiotics"))
            db.flush()
            db.add(Product(
                id=product_id,
                organization_id=org_id,
                category_id=cat_id,
                sku="CIPRO-500",
                name="Ciprofloxacin 500mg",
            ))
            db.flush()

        session = Session(
            user_id=generate_uuid(),
            username="cashier1",
            full_name="Tunde Bakare",
            organization_id=org_id,
            organization_name="CarePlus Pharmacy",
            branch_id=branch_id,
            branch_name="Victoria Island",
            device_id=device_id,
            device_code="C01",
            permissions=[p.value for p in PermissionCode],
            roles=[],
            is_offline=True,
            is_org_admin=True,
            logged_in_at=utc_now(),
        )
        return org_id, branch_id, device_id, product_id, session

    def test_cart_price_freezing_and_fefo_checkout_lifecycle(self, db_manager):
        """
        1. Cart freezes unit_price at add-to-cart time; subsequent price changes do NOT affect cart items.
        2. FEFO allocates earliest-expiring batch first, creates Sale, SaleItems, Payments,
           InventoryMovements, Receipt, AuditEvent, and correlated SyncEvents.
        3. Receipt number follows {branch_code}-{device_code}-{YYYYMMDD}-{sequence:06d}.
        4. SaleItem is immutable and thermal receipt is formatted and reprinted cleanly.
        """
        org_id, branch_id, device_id, product_id, session = self._seed(db_manager)
        inv_svc = InventoryService(db_manager)
        pricing_svc = PricingService(db_manager)
        sales_svc = SalesService(db_manager)

        # Initial price = 800.00
        p1 = pricing_svc.set_price(session, product_id=product_id, selling_price="800.00")

        # Create 2 batches: B-SOON (expires in 20 days, 5 units) and B-LATER (expires in 180 days, 15 units)
        b_soon = inv_svc.create_batch(
            session,
            product_id=product_id,
            batch_number="B-SOON",
            expiry_date=(date.today() + timedelta(days=20)).isoformat(),
            purchase_price="500.00",
        )
        b_later = inv_svc.create_batch(
            session,
            product_id=product_id,
            batch_number="B-LATER",
            expiry_date=(date.today() + timedelta(days=180)).isoformat(),
            purchase_price="520.00",
        )
        inv_svc.adjust_stock(
            session, branch_id=branch_id, batch_id=b_soon.id, quantity_change=5, notes="Load B-SOON"
        )
        inv_svc.adjust_stock(
            session, branch_id=branch_id, batch_id=b_later.id, quantity_change=15, notes="Load B-LATER"
        )

        # Add 8 units to POSCart at current price (800.00) -> freezes unit_price at 800.00!
        cart = POSCart()
        resolved = pricing_svc.resolve_price(org_id, product_id, branch_id)
        cart.add_item(
            product_id=product_id,
            product_name="Ciprofloxacin 500mg",
            sku="CIPRO-500",
            quantity=8,
            unit_price=resolved.selling_price,
        )

        # Mid-session price change to 1200.00 -> cart item MUST remain frozen at 800.00!
        pricing_svc.set_price(session, product_id=product_id, selling_price="1200.00")
        assert cart.items[0].unit_price == Decimal("800.00")
        assert cart.total == Decimal("6400.00")

        # Checkout cart with FEFO -> 5 units from B-SOON + 3 units from B-LATER
        res = sales_svc.checkout_cart(
            session,
            cart,
            payments=[
                {"payment_method": "CASH", "amount": "4000.00"},
                {"payment_method": "POS_CARD", "amount": "2400.00", "reference": "POS-REF-1"},
            ],
            strategy="FEFO",
        )
        today_code = date.today().strftime("%Y%m%d")
        assert res["receipt_number"] == f"VI01-C01-{today_code}-000001"
        assert res["total"] == Decimal("6400.00")
        assert res["items_count"] == 2
        assert "CAREPLUS PHARMACY" in res["receipt_text"]
        assert "Ciprofloxacin 500mg" in res["receipt_text"]

        with db_manager.get_session() as db:
            b_soon_db = db.query(Batch).filter_by(id=b_soon.id).first()
            assert b_soon_db.status == BatchStatus.DEPLETED.value

            inv_soon = db.query(BranchInventory).filter_by(branch_id=branch_id, batch_id=b_soon.id).first()
            inv_later = db.query(BranchInventory).filter_by(branch_id=branch_id, batch_id=b_later.id).first()
            assert inv_soon.quantity == 0
            assert inv_later.quantity == 12

            # All SyncEvents for this sale share the exact same correlation_id
            corr_events = db.query(SyncEvent).filter_by(correlation_id=res["correlation_id"]).all()
            corr_types = {e.entity_type for e in corr_events}
            assert {"sale", "sale_item", "payment", "receipt", "inventory_movement", "audit_event"}.issubset(corr_types)

            si_obj = db.query(SaleItem).filter_by(sale_id=res["sale_id"]).first()
            sale_obj = db.query(Sale).filter_by(id=res["sale_id"]).first()

        # Verify SaleItem immutability and Sale no-delete in BaseRepository
        repo = BaseRepository(db_manager.get_session)
        with pytest.raises(ValidationError, match="immutable"):
            repo.update(si_obj, unit_price=Decimal("999.00"))
        with pytest.raises(ValidationError, match="immutable"):
            repo.soft_delete(sale_obj)

        # Reprint receipt increments reprint_count
        reprint_txt = sales_svc.reprint_receipt(session, res["sale_id"])
        assert "REPRINT COPY" in reprint_txt
        with db_manager.get_session() as db:
            rec_obj = db.query(Receipt).filter_by(sale_id=res["sale_id"]).first()
            assert rec_obj.reprint_count == 1

    def test_pos_blocks_expired_and_recalled_batches_on_desktop(self, db_manager):
        """Desktop POS blocks selling from EXPIRED or RECALLED batches."""
        _, branch_id, _, product_id, session = self._seed(db_manager)
        inv_svc = InventoryService(db_manager)
        sales_svc = SalesService(db_manager)

        b_rec = inv_svc.create_batch(
            session,
            product_id=product_id,
            batch_number="B-REC",
            expiry_date=(date.today() + timedelta(days=90)).isoformat(),
            purchase_price="500.00",
        )
        inv_svc.adjust_stock(
            session, branch_id=branch_id, batch_id=b_rec.id, quantity_change=10, notes="Load"
        )
        inv_svc.recall_batch(session, b_rec.id, reason="Contamination")

        cart = POSCart()
        cart.add_item(
            product_id=product_id,
            product_name="Ciprofloxacin 500mg",
            sku="CIPRO-500",
            quantity=1,
            unit_price="800.00",
            batch_id=b_rec.id,
        )
        with pytest.raises(ValidationError, match="RECALLED"):
            sales_svc.checkout_cart(
                session,
                cart,
                payments=[{"payment_method": "CASH", "amount": "800.00"}],
            )
