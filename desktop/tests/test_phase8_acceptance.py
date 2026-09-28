"""Phase 8 Acceptance Tests — Purchasing & Inventory Receiving (Desktop)."""
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
    Supplier,
    Batch,
    BranchInventory,
    Price,
    Purchase,
    PurchaseItem,
    PurchasePayment,
    SyncEvent,
    User,
)
from desktop.app.domain.enums import (
    MovementType,
    PaymentStatus,
    PermissionCode,
    ReceivingStatus,
)
from desktop.app.domain.exceptions import ValidationError
from desktop.app.services.purchase_service import PurchaseService
from desktop.app.utils.date_utils import utc_now
from desktop.app.utils.uuid_utils import generate_uuid


class TestPhase8DesktopPurchasingAcceptance:
    """Desktop acceptance tests for Phase 8 Purchasing & Inventory Receiving."""

    def _seed(self, db_manager):
        org_id = generate_uuid()
        branch_id = generate_uuid()
        device_id = generate_uuid()
        cat_id = generate_uuid()
        product_id = generate_uuid()
        supplier_id = generate_uuid()
        user_id = generate_uuid()

        with db_manager.get_session() as db:
            db.add(Organization(id=org_id, name="MedCare Pharmacy", code="MEDC"))
            db.flush()
            db.add(Branch(id=branch_id, organization_id=org_id, name="Ikeja Branch", code="IK01"))
            db.flush()
            db.add(Device(
                id=device_id,
                organization_id=org_id,
                branch_id=branch_id,
                name="Store Terminal",
                code="ST01",
                device_identifier="HW-IK-ST01",
            ))
            db.flush()
            db.add(User(
                id=user_id,
                organization_id=org_id,
                username="inventory_manager",
                full_name="Emeka Eze",
                email="emeka@medcare.ng",
            ))
            db.flush()
            db.add(Supplier(
                id=supplier_id,
                organization_id=org_id,
                name="Emzor Pharmaceuticals",
                contact_person="Mrs. Okonkwo",
                phone="08022223333",
            ))
            db.flush()
            db.add(Category(id=cat_id, organization_id=org_id, name="Cold & Flu"))
            db.flush()
            db.add(Product(
                id=product_id,
                organization_id=org_id,
                category_id=cat_id,
                sku="PANADOL-EXTRA",
                name="Panadol Extra Tablets",
            ))
            db.flush()

        session = Session(
            user_id=user_id,
            username="inventory_manager",
            full_name="Emeka Eze",
            organization_id=org_id,
            organization_name="MedCare Pharmacy",
            branch_id=branch_id,
            branch_name="Ikeja Branch",
            device_id=device_id,
            device_code="ST01",
            permissions=[p.value for p in PermissionCode],
            roles=[],
            is_offline=True,
            is_org_admin=True,
            logged_in_at=utc_now(),
        )
        return org_id, branch_id, device_id, product_id, supplier_id, session

    def test_purchase_lifecycle_stock_receiving_and_price_update(self, db_manager):
        """
        1. Create purchase order with 30 units @ 200.00 each -> total 6,000.00 (PENDING, UNPAID).
        2. Partial receiving of 10 units creates Batch, increments BranchInventory, records STOCK_RECEIVED movement.
        3. Over-receive attempt (25 units when 20 remain) raises ValidationError.
        4. Receiving expired batch raises ValidationError.
        5. Receive remaining 20 units with update_selling_price=True updates Price and sets receiving_status = RECEIVED.
        6. Record payments transitions UNPAID -> PARTIALLY_PAID -> PAID.
        """
        org_id, branch_id, device_id, product_id, supplier_id, session = self._seed(db_manager)
        pur_svc = PurchaseService(db_manager)
        today = date.today()

        # 1. Create Purchase
        purchase = pur_svc.create_purchase(
            user_session=session,
            supplier_id=supplier_id,
            purchase_reference="PO-EMZOR-001",
            purchase_date=today.isoformat(),
            invoice_number="INV-EMZ-101",
            items=[
                {
                    "product_id": product_id,
                    "quantity_ordered": 30,
                    "purchase_price": "200.00",
                    "selling_price": "350.00",
                }
            ],
            notes="First stock purchase order",
        )
        assert purchase.total == Decimal("6000.00")
        assert purchase.receiving_status == ReceivingStatus.PENDING.value
        assert purchase.payment_status == PaymentStatus.UNPAID.value

        with db_manager.get_session() as db:
            pi = db.query(PurchaseItem).filter_by(purchase_id=purchase.id).first()
            pi_id = pi.id

        # 2. Partial receive 10 units
        rec1 = pur_svc.receive_purchase(
            user_session=session,
            purchase_id=purchase.id,
            items=[
                {
                    "purchase_item_id": pi_id,
                    "quantity_received": 10,
                    "batch_number": "PAN-B01",
                    "expiry_date": (today + timedelta(days=400)).isoformat(),
                }
            ],
        )
        assert rec1["receiving_status"] == ReceivingStatus.PARTIALLY_RECEIVED.value

        with db_manager.get_session() as db:
            batch = db.query(Batch).filter_by(batch_number="PAN-B01").first()
            assert batch is not None
            inv = db.query(BranchInventory).filter_by(batch_id=batch.id).first()
            assert inv.quantity == 10

        # 3. Over-receive attempt (25 units when only 20 remain)
        with pytest.raises(ValidationError, match="only 20 units remain"):
            pur_svc.receive_purchase(
                user_session=session,
                purchase_id=purchase.id,
                items=[
                    {
                        "purchase_item_id": pi_id,
                        "quantity_received": 25,
                        "batch_number": "PAN-B01",
                        "expiry_date": (today + timedelta(days=400)).isoformat(),
                    }
                ],
            )

        # 4. Receiving expired batch
        with pytest.raises(ValidationError, match="already-expired"):
            pur_svc.receive_purchase(
                user_session=session,
                purchase_id=purchase.id,
                items=[
                    {
                        "purchase_item_id": pi_id,
                        "quantity_received": 5,
                        "batch_number": "PAN-B02",
                        "expiry_date": (today - timedelta(days=1)).isoformat(),
                    }
                ],
            )

        # 5. Receive remaining 20 units and update selling price to 380.00
        rec2 = pur_svc.receive_purchase(
            user_session=session,
            purchase_id=purchase.id,
            items=[
                {
                    "purchase_item_id": pi_id,
                    "quantity_received": 20,
                    "batch_number": "PAN-B01",
                    "expiry_date": (today + timedelta(days=400)).isoformat(),
                    "selling_price": "380.00",
                    "update_selling_price": True,
                }
            ],
        )
        assert rec2["receiving_status"] == ReceivingStatus.RECEIVED.value

        with db_manager.get_session() as db:
            inv = db.query(BranchInventory).filter_by(batch_id=batch.id).first()
            assert inv.quantity == 30
            p = db.query(Price).filter_by(product_id=product_id, is_current=True).first()
            assert p is not None
            assert p.selling_price == Decimal("380.00")

        # 6. Record Payments
        pay1 = pur_svc.record_payment(
            user_session=session,
            purchase_id=purchase.id,
            payment_method="BANK_TRANSFER",
            amount="2500.00",
            payment_date=today.isoformat(),
        )
        assert pay1["payment_status"] == PaymentStatus.PARTIALLY_PAID.value

        pay2 = pur_svc.record_payment(
            user_session=session,
            purchase_id=purchase.id,
            payment_method="CASH",
            amount="3500.00",
            payment_date=today.isoformat(),
        )
        assert pay2["payment_status"] == PaymentStatus.PAID.value
