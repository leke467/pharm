"""Phase 8 Acceptance Tests — Purchasing & Inventory Receiving (Server)."""
import uuid
from datetime import date, timedelta
from decimal import Decimal
import pytest
from django.utils import timezone
from apps.audit.models import AuditEvent
from apps.inventory.models import Batch, BranchInventory, InventoryMovement
from apps.pricing.models import Price
from apps.products.models import Category, Product, Supplier
from apps.purchases.models import Purchase, PurchaseItem, PurchasePayment
from apps.users.services import seed_permissions_and_roles
from shared.enums import (
    AuditAction,
    BatchStatus,
    MovementType,
    PaymentStatus,
    ReceivingStatus,
    SYNC_DEPENDENCY_LEVELS,
)


@pytest.mark.django_db
class TestPhase8ServerPurchasingAcceptance:
    """Server acceptance tests for Phase 8 Purchasing & Inventory Receiving."""

    def _setup_master_data(self, org, user):
        seed_permissions_and_roles(org)
        user.is_org_admin = True
        user.save()
        cat, _ = Category.objects.get_or_create(organization=org, name="Vitamins")
        prod = Product.objects.create(
            organization=org,
            sku="VIT-C-1000",
            name="Vitamin C 1000mg",
            category=cat,
        )
        sup = Supplier.objects.create(
            organization=org,
            name="MegaHealth Pharma Ltd",
            contact_person="Alhaji Danladi",
            phone="08031234567",
        )
        return prod, sup

    def test_purchase_order_lifecycle_receiving_and_pricing_update(
        self, authenticated_client, test_user, test_organization, test_branch, test_device
    ):
        """
        1. Create purchase order with 20 units @ 500.00 each -> total 10,000.00 (PENDING, UNPAID).
        2. Partial receiving of 8 units creates Batch, increments BranchInventory, records STOCK_RECEIVED movement.
        3. Over-receiving attempt (15 units when 12 remain) is rejected with 400.
        4. Receiving remaining 12 units transitions receiving_status -> RECEIVED and updates Price.
        5. Recording partial and full payments transitions UNPAID -> PARTIALLY_PAID -> PAID.
        """
        prod, sup = self._setup_master_data(test_organization, test_user)
        today = date.today()

        # 1. Create Purchase
        res_create = authenticated_client.post(
            "/api/v1/purchases/",
            {
                "branch_id": str(test_branch.id),
                "supplier_id": str(sup.id),
                "purchase_reference": "PO-MEGA-2026-001",
                "invoice_number": "INV-MEGA-9988",
                "purchase_date": today.isoformat(),
                "discount_amount": "0.00",
                "notes": "Urgent stock replenishment",
                "items": [
                    {
                        "product_id": str(prod.id),
                        "quantity_ordered": 20,
                        "purchase_price": "500.00",
                        "selling_price": "750.00",
                    }
                ],
            },
            format="json",
        )
        assert res_create.status_code == 201, res_create.json()
        po_data = res_create.json()
        po_id = po_data["id"]
        pi_id = po_data["items"][0]["id"]
        assert po_data["receiving_status"] == ReceivingStatus.PENDING.value
        assert po_data["payment_status"] == PaymentStatus.UNPAID.value
        assert Decimal(po_data["total"]) == Decimal("10000.00")

        # 2. Partial receive: 8 units of batch 'VC-B01'
        res_rec1 = authenticated_client.post(
            f"/api/v1/purchases/{po_id}/receive/",
            {
                "items": [
                    {
                        "purchase_item_id": pi_id,
                        "quantity_received": 8,
                        "batch_number": "VC-B01",
                        "expiry_date": (today + timedelta(days=365)).isoformat(),
                    }
                ]
            },
            format="json",
        )
        assert res_rec1.status_code == 200, res_rec1.json()
        assert res_rec1.json()["receiving_status"] == ReceivingStatus.PARTIALLY_RECEIVED.value

        batch1 = Batch.objects.get(product=prod, batch_number="VC-B01")
        assert batch1.status == BatchStatus.ACTIVE.value
        inv1 = BranchInventory.objects.get(branch=test_branch, batch=batch1)
        assert inv1.quantity == 8
        assert InventoryMovement.objects.filter(
            batch=batch1,
            movement_type=MovementType.STOCK_RECEIVED.value,
            quantity_change=8,
        ).exists()

        # 3. Over-receiving attempt: 15 units when only 12 remain -> 400
        res_over = authenticated_client.post(
            f"/api/v1/purchases/{po_id}/receive/",
            {
                "items": [
                    {
                        "purchase_item_id": pi_id,
                        "quantity_received": 15,
                        "batch_number": "VC-B01",
                        "expiry_date": (today + timedelta(days=365)).isoformat(),
                    }
                ]
            },
            format="json",
        )
        assert res_over.status_code == 400

        # 4. Receive remaining 12 units and update selling price to 800.00
        res_rec2 = authenticated_client.post(
            f"/api/v1/purchases/{po_id}/receive/",
            {
                "items": [
                    {
                        "purchase_item_id": pi_id,
                        "quantity_received": 12,
                        "batch_number": "VC-B01",
                        "expiry_date": (today + timedelta(days=365)).isoformat(),
                        "selling_price": "800.00",
                        "update_selling_price": True,
                    }
                ]
            },
            format="json",
        )
        assert res_rec2.status_code == 200
        assert res_rec2.json()["receiving_status"] == ReceivingStatus.RECEIVED.value
        inv1.refresh_from_db()
        assert inv1.quantity == 20

        # Verify Price was updated
        curr_price = Price.objects.get(product=prod, branch=test_branch, is_current=True)
        assert curr_price.selling_price == Decimal("800.00")
        assert AuditEvent.objects.filter(
            entity_id=po_id, action=AuditAction.STOCK_RECEIVED.value
        ).exists()

        # 5. Record Payments
        # Partial payment of 4,000.00 -> PARTIALLY_PAID
        pay1 = authenticated_client.post(
            f"/api/v1/purchases/{po_id}/pay/",
            {
                "payment_method": "BANK_TRANSFER",
                "amount": "4000.00",
                "payment_date": today.isoformat(),
                "reference": "TXN-BANK-001",
            },
            format="json",
        )
        assert pay1.status_code == 200
        assert pay1.json()["payment_status"] == PaymentStatus.PARTIALLY_PAID.value

        # Remaining payment of 6,000.00 -> PAID
        pay2 = authenticated_client.post(
            f"/api/v1/purchases/{po_id}/pay/",
            {
                "payment_method": "CASH",
                "amount": "6000.00",
                "payment_date": today.isoformat(),
            },
            format="json",
        )
        assert pay2.status_code == 200
        assert pay2.json()["payment_status"] == PaymentStatus.PAID.value

    def test_sync_upload_of_correlated_purchase_bundle(
        self, authenticated_client, test_user, test_organization, test_branch, test_device
    ):
        """
        Offline purchase receiving bundle (purchase, purchase_item, batch,
        inventory_movement STOCK_RECEIVED, audit_event) processes atomically on upload.
        """
        prod, sup = self._setup_master_data(test_organization, test_user)
        corr_id = str(uuid.uuid4())
        po_id = str(uuid.uuid4())
        pi_id = str(uuid.uuid4())
        batch_id = str(uuid.uuid4())
        mov_id = str(uuid.uuid4())
        aud_id = str(uuid.uuid4())
        today = date.today()
        now_iso = timezone.now().isoformat()

        events = [
            {
                "id": str(uuid.uuid4()),
                "entity_type": "batch",
                "entity_id": batch_id,
                "operation": "CREATE",
                "correlation_id": corr_id,
                "dependency_level": SYNC_DEPENDENCY_LEVELS["batch"],
                "local_created_at": now_iso,
                "payload": {
                    "id": batch_id,
                    "organization_id": str(test_organization.id),
                    "product_id": str(prod.id),
                    "batch_number": "VC-OFFLINE-99",
                    "expiry_date": (today + timedelta(days=300)).isoformat(),
                    "purchase_price": "450.00",
                    "supplier_id": str(sup.id),
                    "received_date": today.isoformat(),
                    "status": BatchStatus.ACTIVE.value,
                },
            },
            {
                "id": str(uuid.uuid4()),
                "entity_type": "purchase",
                "entity_id": po_id,
                "operation": "CREATE",
                "correlation_id": corr_id,
                "dependency_level": SYNC_DEPENDENCY_LEVELS["purchase"],
                "local_created_at": now_iso,
                "payload": {
                    "id": po_id,
                    "organization_id": str(test_organization.id),
                    "branch_id": str(test_branch.id),
                    "supplier_id": str(sup.id),
                    "user_id": str(test_user.id),
                    "purchase_reference": "PO-OFFLINE-888",
                    "purchase_date": today.isoformat(),
                    "subtotal": "4500.00",
                    "discount_amount": "0.00",
                    "total": "4500.00",
                    "payment_status": PaymentStatus.UNPAID.value,
                    "receiving_status": ReceivingStatus.RECEIVED.value,
                },
            },
            {
                "id": str(uuid.uuid4()),
                "entity_type": "purchase_item",
                "entity_id": pi_id,
                "operation": "CREATE",
                "correlation_id": corr_id,
                "dependency_level": SYNC_DEPENDENCY_LEVELS["purchase_item"],
                "local_created_at": now_iso,
                "payload": {
                    "id": pi_id,
                    "purchase_id": po_id,
                    "product_id": str(prod.id),
                    "batch_id": batch_id,
                    "quantity_ordered": 10,
                    "quantity_received": 10,
                    "purchase_price": "450.00",
                    "selling_price": "700.00",
                    "discount": "0.00",
                    "line_total": "4500.00",
                },
            },
            {
                "id": str(uuid.uuid4()),
                "entity_type": "inventory_movement",
                "entity_id": mov_id,
                "operation": "CREATE",
                "correlation_id": corr_id,
                "dependency_level": SYNC_DEPENDENCY_LEVELS["inventory_movement"],
                "local_created_at": now_iso,
                "payload": {
                    "id": mov_id,
                    "branch_id": str(test_branch.id),
                    "batch_id": batch_id,
                    "movement_type": MovementType.STOCK_RECEIVED.value,
                    "quantity_change": 10,
                    "quantity_before": 0,
                    "quantity_after": 10,
                    "reference_type": "purchase",
                    "reference_id": po_id,
                    "user_id": str(test_user.id),
                    "device_id": str(test_device.id),
                    "local_timestamp": now_iso,
                },
            },
            {
                "id": str(uuid.uuid4()),
                "entity_type": "audit_event",
                "entity_id": aud_id,
                "operation": "CREATE",
                "correlation_id": corr_id,
                "dependency_level": SYNC_DEPENDENCY_LEVELS["audit_event"],
                "local_created_at": now_iso,
                "payload": {
                    "id": aud_id,
                    "branch_id": str(test_branch.id),
                    "user_id": str(test_user.id),
                    "device_id": str(test_device.id),
                    "action": AuditAction.STOCK_RECEIVED.value,
                    "entity_type": "purchase",
                    "entity_id": po_id,
                    "correlation_id": corr_id,
                    "local_timestamp": now_iso,
                },
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
        assert [r["status"] for r in res.data["results"]] == ["PROCESSED"] * 5

        assert Purchase.objects.filter(id=po_id).exists()
        assert PurchaseItem.objects.filter(id=pi_id).exists()
        assert Batch.objects.filter(id=batch_id).exists()
        inv = BranchInventory.objects.get(branch=test_branch, batch_id=batch_id)
        assert inv.quantity == 10
