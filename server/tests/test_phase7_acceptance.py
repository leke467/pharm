"""Phase 7 Acceptance Tests — Returns & Voids (Server)."""
import uuid
from datetime import date, timedelta
from decimal import Decimal
import pytest
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from apps.audit.models import AuditEvent
from apps.inventory.models import Batch, BranchInventory, InventoryMovement
from apps.inventory.views import apply_inventory_movement
from apps.products.models import Category, Product
from apps.sales.models import Sale, SaleItem, SaleReturn, SaleReturnItem
from apps.users.services import seed_permissions_and_roles
from shared.enums import (
    AuditAction,
    BatchStatus,
    MovementType,
    SaleStatus,
    SYNC_DEPENDENCY_LEVELS,
)


@pytest.mark.django_db
class TestPhase7ServerReturnsAndVoidsAcceptance:
    """Server acceptance tests for Phase 7 Returns & Voids."""

    def _create_completed_sale(
        self, authenticated_client, test_user, test_organization, test_branch, test_device
    ):
        seed_permissions_and_roles(test_organization)
        test_user.is_org_admin = True
        test_user.save()

        cat, _ = Category.objects.get_or_create(organization=test_organization, name="Analgesics")
        prod = Product.objects.create(
            organization=test_organization,
            sku="PARA-500",
            name="Paracetamol 500mg",
            category=cat,
        )
        batch = Batch.objects.create(
            organization=test_organization,
            product=prod,
            batch_number="B-PARA-01",
            expiry_date=date.today() + timedelta(days=180),
            purchase_price=Decimal("50.00"),
            received_date=date.today(),
        )
        apply_inventory_movement(
            organization_id=test_organization.id,
            branch_id=test_branch.id,
            batch_id=batch.id,
            storage_location_id=None,
            movement_type=MovementType.OPENING_BALANCE.value,
            quantity_change=20,
            reference_type="init",
            reference_id=test_branch.id,
            user=test_user,
        )

        res = authenticated_client.post(
            "/api/v1/sales/",
            {
                "branch_id": str(test_branch.id),
                "device_id": str(test_device.id),
                "receipt_number": f"MAIN-D01-20260925-{uuid.uuid4().hex[:6].upper()}",
                "items": [
                    {
                        "product_id": str(prod.id),
                        "batch_id": str(batch.id),
                        "quantity": 10,
                        "unit_price": "100.00",
                    }
                ],
                "payments": [{"payment_method": "CASH", "amount": "1000.00"}],
            },
            format="json",
        )
        assert res.status_code == 201
        sale_data = res.json()
        return prod, batch, sale_data

    def test_partial_and_full_sale_return_restores_inventory_and_prevents_over_return(
        self, authenticated_client, test_user, test_organization, test_branch, test_device
    ):
        """
        1. Partial return (4 of 10 units) transitions Sale.status -> PARTIALLY_RETURNED,
           creates SaleReturn + SaleReturnItem, and restores +4 units to the original batch via SALE_RETURN movement.
        2. Over-return attempt (returning 7 units when only 6 remain) is rejected with 400.
        3. Returning the remaining 6 units transitions Sale.status -> RETURNED and restores +6 units.
        4. SaleReturn and SaleReturnItem cannot be deleted.
        """
        prod, batch, sale_data = self._create_completed_sale(
            authenticated_client, test_user, test_organization, test_branch, test_device
        )
        sale_id = sale_data["id"]
        sale_item_id = sale_data["items"][0]["id"]

        inv = BranchInventory.objects.get(branch=test_branch, batch=batch)
        assert inv.quantity == 10  # 20 initial - 10 sold

        # 1. Partial return of 4 units
        res1 = authenticated_client.post(
            "/api/v1/sale-returns/",
            {
                "original_sale_id": sale_id,
                "device_id": str(test_device.id),
                "reason": "Customer returned extra packs",
                "items": [{"sale_item_id": sale_item_id, "quantity": 4}],
            },
            format="json",
        )
        assert res1.status_code == 201, res1.json()
        ret1_data = res1.json()
        assert Decimal(ret1_data["refund_amount"]) == Decimal("400.00")

        sale = Sale.objects.get(id=sale_id)
        assert sale.status == SaleStatus.PARTIALLY_RETURNED.value

        inv.refresh_from_db()
        assert inv.quantity == 14
        assert InventoryMovement.objects.filter(
            batch=batch,
            movement_type=MovementType.SALE_RETURN.value,
            quantity_change=4,
        ).exists()
        assert AuditEvent.objects.filter(
            entity_id=ret1_data["id"],
            action=AuditAction.SALE_RETURNED.value,
        ).exists()

        # 2. Over-return attempt: 7 units when only 6 remain returnable -> 400
        res_over = authenticated_client.post(
            "/api/v1/sale-returns/",
            {
                "original_sale_id": sale_id,
                "device_id": str(test_device.id),
                "reason": "Attempting over-return",
                "items": [{"sale_item_id": sale_item_id, "quantity": 7}],
            },
            format="json",
        )
        assert res_over.status_code == 400

        # 3. Return remaining 6 units -> Sale.status becomes RETURNED
        res2 = authenticated_client.post(
            "/api/v1/sale-returns/",
            {
                "original_sale_id": sale_id,
                "device_id": str(test_device.id),
                "reason": "Customer returned remaining packs",
                "items": [{"sale_item_id": sale_item_id, "quantity": 6}],
            },
            format="json",
        )
        assert res2.status_code == 201
        sale.refresh_from_db()
        assert sale.status == SaleStatus.RETURNED.value
        inv.refresh_from_db()
        assert inv.quantity == 20

        # 4. Verify no-delete protection on SaleReturn and SaleReturnItem
        sr = SaleReturn.objects.get(id=ret1_data["id"])
        sri = SaleReturnItem.objects.filter(sale_return=sr).first()
        with pytest.raises(DjangoValidationError):
            sr.delete()
        with pytest.raises(DjangoValidationError):
            sri.delete()

    def test_void_sale_restores_inventory_and_blocks_invalid_voids(
        self, authenticated_client, test_user, test_organization, test_branch, test_device
    ):
        """
        1. Voiding a completed sale without a reason fails with 400.
        2. Voiding a completed sale with a reason sets Sale.status = VOIDED, creates a SaleReturn,
           restores full batch inventory via SALE_RETURN movement, and records SALE_VOIDED audit event.
        3. Voiding an already-voided sale fails with 400.
        """
        prod, batch, sale_data = self._create_completed_sale(
            authenticated_client, test_user, test_organization, test_branch, test_device
        )
        sale_id = sale_data["id"]

        # Missing reason -> 400
        bad_void = authenticated_client.post(
            f"/api/v1/sales/{sale_id}/void/",
            {"device_id": str(test_device.id), "reason": "   "},
            format="json",
        )
        assert bad_void.status_code == 400

        # Valid void -> 200
        ok_void = authenticated_client.post(
            f"/api/v1/sales/{sale_id}/void/",
            {"device_id": str(test_device.id), "reason": "Cashier rang wrong medication"},
            format="json",
        )
        assert ok_void.status_code == 200
        assert ok_void.json()["status"] == SaleStatus.VOIDED.value

        inv = BranchInventory.objects.get(branch=test_branch, batch=batch)
        assert inv.quantity == 20  # Full 10 units restored
        assert AuditEvent.objects.filter(
            entity_id=sale_id,
            action=AuditAction.SALE_VOIDED.value,
        ).exists()

        # Voiding again -> 400
        dup_void = authenticated_client.post(
            f"/api/v1/sales/{sale_id}/void/",
            {"device_id": str(test_device.id), "reason": "Second void"},
            format="json",
        )
        assert dup_void.status_code == 400

    def test_sync_upload_of_correlated_sale_return_bundle(
        self, authenticated_client, test_user, test_organization, test_branch, test_device
    ):
        """
        Offline sale return uploaded as a correlated bundle (sale_return, sale_return_item,
        sale UPDATE, inventory_movement SALE_RETURN, audit_event) processes atomically.
        """
        prod, batch, sale_data = self._create_completed_sale(
            authenticated_client, test_user, test_organization, test_branch, test_device
        )
        sale_id = sale_data["id"]
        sale_item_id = sale_data["items"][0]["id"]

        corr_id = str(uuid.uuid4())
        ret_id = str(uuid.uuid4())
        ret_item_id = str(uuid.uuid4())
        mov_id = str(uuid.uuid4())
        aud_id = str(uuid.uuid4())
        now_iso = timezone.now().isoformat()

        events = [
            {
                "id": str(uuid.uuid4()),
                "entity_type": "sale_return",
                "entity_id": ret_id,
                "operation": "CREATE",
                "correlation_id": corr_id,
                "dependency_level": SYNC_DEPENDENCY_LEVELS["sale_return"],
                "local_created_at": now_iso,
                "payload": {
                    "id": ret_id,
                    "organization_id": str(test_organization.id),
                    "branch_id": str(test_branch.id),
                    "original_sale_id": sale_id,
                    "user_id": str(test_user.id),
                    "device_id": str(test_device.id),
                    "return_receipt_number": "RET-OFFLINE-001",
                    "reason": "Offline customer return",
                    "refund_amount": "300.00",
                    "return_date": now_iso,
                    "is_offline": True,
                },
            },
            {
                "id": str(uuid.uuid4()),
                "entity_type": "sale_return_item",
                "entity_id": ret_item_id,
                "operation": "CREATE",
                "correlation_id": corr_id,
                "dependency_level": SYNC_DEPENDENCY_LEVELS["sale_return_item"],
                "local_created_at": now_iso,
                "payload": {
                    "id": ret_item_id,
                    "sale_return_id": ret_id,
                    "sale_item_id": sale_item_id,
                    "batch_id": str(batch.id),
                    "quantity": 3,
                    "refund_amount": "300.00",
                },
            },
            {
                "id": str(uuid.uuid4()),
                "entity_type": "sale",
                "entity_id": sale_id,
                "operation": "UPDATE",
                "correlation_id": corr_id,
                "dependency_level": SYNC_DEPENDENCY_LEVELS["sale"],
                "local_created_at": now_iso,
                "payload": {
                    "id": sale_id,
                    "branch_id": str(test_branch.id),
                    "user_id": str(test_user.id),
                    "device_id": str(test_device.id),
                    "receipt_number": sale_data["receipt_number"],
                    "subtotal": "1000.00",
                    "discount_amount": "0.00",
                    "tax_amount": "0.00",
                    "total": "1000.00",
                    "status": SaleStatus.PARTIALLY_RETURNED.value,
                    "sale_date": now_iso,
                    "is_offline": True,
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
                    "batch_id": str(batch.id),
                    "movement_type": MovementType.SALE_RETURN.value,
                    "quantity_change": 3,
                    "quantity_before": 10,
                    "quantity_after": 13,
                    "reference_type": "sale_return",
                    "reference_id": ret_id,
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
                    "action": AuditAction.SALE_RETURNED.value,
                    "entity_type": "sale_return",
                    "entity_id": ret_id,
                    "reason": "Offline customer return",
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

        assert SaleReturn.objects.filter(id=ret_id).exists()
        assert SaleReturnItem.objects.filter(id=ret_item_id).exists()
        assert Sale.objects.get(id=sale_id).status == SaleStatus.PARTIALLY_RETURNED.value
        assert BranchInventory.objects.get(branch=test_branch, batch=batch).quantity == 13
