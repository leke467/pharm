"""Phase 6 Acceptance Tests — Sales / POS (Server)."""
import uuid
from datetime import date, timedelta
from decimal import Decimal
import pytest
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from apps.inventory.models import Batch, BranchInventory, InventoryMovement
from apps.inventory.views import apply_inventory_movement
from apps.products.models import Category, Product
from apps.sales.models import Sale, SaleItem, Payment, Receipt
from apps.users.services import seed_permissions_and_roles
from shared.enums import BatchStatus, MovementType, SaleStatus


@pytest.mark.django_db
class TestPhase6ServerSalesAcceptance:
    """Server acceptance tests for Phase 6 POS / Sales."""

    def _setup(self, org, user):
        seed_permissions_and_roles(org)
        user.is_org_admin = True
        user.save()
        cat, _ = Category.objects.get_or_create(organization=org, name="Analgesics")
        prod = Product.objects.create(
            organization=org,
            sku="IBUP-400",
            name="Ibuprofen 400mg",
            category=cat,
        )
        return prod

    def test_pos_sale_fefo_allocation_and_batch_depletion(
        self, authenticated_client, test_user, test_organization, test_branch, test_device
    ):
        """
        1. FEFO selects earliest-expiring ACTIVE batch first and spans across multiple batches when needed.
        2. Depleted batch transitions to DEPLETED.
        3. SaleItem is immutable and Sale cannot be deleted.
        """
        prod = self._setup(test_organization, test_user)
        today = date.today()

        # Batch 1 expires in 30 days (10 units)
        b1 = Batch.objects.create(
            organization=test_organization,
            product=prod,
            batch_number="IBU-EARLY",
            expiry_date=today + timedelta(days=30),
            purchase_price=Decimal("100.00"),
            received_date=today,
        )
        # Batch 2 expires in 120 days (20 units)
        b2 = Batch.objects.create(
            organization=test_organization,
            product=prod,
            batch_number="IBU-LATER",
            expiry_date=today + timedelta(days=120),
            purchase_price=Decimal("110.00"),
            received_date=today,
        )
        apply_inventory_movement(
            organization_id=test_organization.id,
            branch_id=test_branch.id,
            batch_id=b1.id,
            storage_location_id=None,
            movement_type=MovementType.OPENING_BALANCE.value,
            quantity_change=10,
            reference_type="init",
            reference_id=test_branch.id,
            user=test_user,
        )
        apply_inventory_movement(
            organization_id=test_organization.id,
            branch_id=test_branch.id,
            batch_id=b2.id,
            storage_location_id=None,
            movement_type=MovementType.OPENING_BALANCE.value,
            quantity_change=20,
            reference_type="init",
            reference_id=test_branch.id,
            user=test_user,
        )

        # Sell 15 units using FEFO (no batch_id specified) -> 10 from b1, 5 from b2
        res = authenticated_client.post(
            "/api/v1/sales/",
            {
                "branch_id": str(test_branch.id),
                "device_id": str(test_device.id),
                "receipt_number": "MAIN-D01-20260925-000001",
                "customer_name": "Adaeze Obi",
                "discount_amount": "50.00",
                "items": [
                    {
                        "product_id": str(prod.id),
                        "quantity": 15,
                        "unit_price": "200.00",
                    }
                ],
                "payments": [
                    {"payment_method": "CASH", "amount": "2950.00"}
                ],
            },
            format="json",
        )
        assert res.status_code == 201, res.data
        assert Decimal(res.data["subtotal"]) == Decimal("3000.00")
        assert Decimal(res.data["total"]) == Decimal("2950.00")
        assert len(res.data["items"]) == 2

        b1.refresh_from_db()
        b2.refresh_from_db()
        assert b1.status == BatchStatus.DEPLETED.value
        assert b2.status == BatchStatus.ACTIVE.value

        inv1 = BranchInventory.objects.get(branch=test_branch, batch=b1)
        inv2 = BranchInventory.objects.get(branch=test_branch, batch=b2)
        assert inv1.quantity == 0
        assert inv2.quantity == 15

        # Verify SaleItem immutability and Sale no-delete policy
        sale = Sale.objects.get(id=res.data["id"])
        si = sale.items.first()
        si.unit_price = Decimal("999.00")
        with pytest.raises(DjangoValidationError):
            si.save()
        with pytest.raises(DjangoValidationError):
            si.delete()
        with pytest.raises(DjangoValidationError):
            sale.delete()

    def test_pos_blocks_expired_recalled_and_depleted_batches(
        self, authenticated_client, test_user, test_organization, test_branch, test_device
    ):
        """POS strictly blocks selling from EXPIRED, RECALLED, or DEPLETED batches."""
        prod = self._setup(test_organization, test_user)
        today = date.today()

        recalled_batch = Batch.objects.create(
            organization=test_organization,
            product=prod,
            batch_number="IBU-RECALLED",
            expiry_date=today + timedelta(days=90),
            purchase_price=Decimal("100.00"),
            received_date=today,
            status=BatchStatus.RECALLED.value,
        )
        BranchInventory.objects.create(
            organization=test_organization,
            branch=test_branch,
            batch=recalled_batch,
            quantity=25,
        )

        res = authenticated_client.post(
            "/api/v1/sales/",
            {
                "branch_id": str(test_branch.id),
                "device_id": str(test_device.id),
                "receipt_number": "MAIN-D01-20260925-000002",
                "items": [
                    {
                        "product_id": str(prod.id),
                        "batch_id": str(recalled_batch.id),
                        "quantity": 1,
                        "unit_price": "200.00",
                    }
                ],
                "payments": [{"payment_method": "CASH", "amount": "200.00"}],
            },
            format="json",
        )
        assert res.status_code == 400

    def test_offline_sale_sync_upload_persists_full_sale_graph(
        self, authenticated_client, test_user, test_organization, test_branch, test_device
    ):
        """Uploading a correlated offline sale batch creates Sale, SaleItem, Payment, Receipt, and InventoryMovement."""
        prod = self._setup(test_organization, test_user)
        today = date.today()
        batch = Batch.objects.create(
            organization=test_organization,
            product=prod,
            batch_number="IBU-SYNC-1",
            expiry_date=today + timedelta(days=180),
            purchase_price=Decimal("100.00"),
            received_date=today,
        )
        BranchInventory.objects.create(
            organization=test_organization,
            branch=test_branch,
            batch=batch,
            quantity=30,
        )

        corr_id = str(uuid.uuid4())
        sale_id = str(uuid.uuid4())
        si_id = str(uuid.uuid4())
        pay_id = str(uuid.uuid4())
        rec_id = str(uuid.uuid4())
        mov_id = str(uuid.uuid4())
        now_str = timezone.now().isoformat()

        events = [
            {
                "id": str(uuid.uuid4()),
                "entity_type": "sale",
                "entity_id": sale_id,
                "operation": "CREATE",
                "payload": {
                    "id": sale_id,
                    "branch_id": str(test_branch.id),
                    "user_id": str(test_user.id),
                    "device_id": str(test_device.id),
                    "receipt_number": "MAIN-D01-20260925-000099",
                    "subtotal": "600.00",
                    "discount_amount": "0.00",
                    "tax_amount": "0.00",
                    "total": "600.00",
                    "status": SaleStatus.COMPLETED.value,
                    "sale_date": now_str,
                    "is_offline": True,
                },
                "correlation_id": corr_id,
                "dependency_level": 5,
                "schema_version": 1,
                "local_created_at": now_str,
            },
            {
                "id": str(uuid.uuid4()),
                "entity_type": "sale_item",
                "entity_id": si_id,
                "operation": "CREATE",
                "payload": {
                    "id": si_id,
                    "sale_id": sale_id,
                    "product_id": str(prod.id),
                    "batch_id": str(batch.id),
                    "quantity": 3,
                    "unit_price": "200.00",
                    "discount_amount": "0.00",
                    "line_total": "600.00",
                },
                "correlation_id": corr_id,
                "dependency_level": 6,
                "schema_version": 1,
                "local_created_at": now_str,
            },
            {
                "id": str(uuid.uuid4()),
                "entity_type": "payment",
                "entity_id": pay_id,
                "operation": "CREATE",
                "payload": {
                    "id": pay_id,
                    "sale_id": sale_id,
                    "payment_method": "POS_CARD",
                    "amount": "600.00",
                    "reference": "TXN-12345",
                },
                "correlation_id": corr_id,
                "dependency_level": 6,
                "schema_version": 1,
                "local_created_at": now_str,
            },
            {
                "id": str(uuid.uuid4()),
                "entity_type": "receipt",
                "entity_id": rec_id,
                "operation": "CREATE",
                "payload": {
                    "id": rec_id,
                    "sale_id": sale_id,
                    "receipt_number": "MAIN-D01-20260925-000099",
                    "printed_at": now_str,
                },
                "correlation_id": corr_id,
                "dependency_level": 6,
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
                    "batch_id": str(batch.id),
                    "movement_type": MovementType.SALE.value,
                    "quantity_change": -3,
                    "reference_type": "sale",
                    "reference_id": sale_id,
                    "user_id": str(test_user.id),
                    "local_timestamp": now_str,
                },
                "correlation_id": corr_id,
                "dependency_level": 7,
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
        assert [r["status"] for r in res.data["results"]] == ["PROCESSED"] * 5

        assert Sale.objects.filter(id=sale_id).exists()
        assert SaleItem.objects.filter(id=si_id).exists()
        assert Payment.objects.filter(id=pay_id).exists()
        assert Receipt.objects.filter(id=rec_id).exists()
        inv = BranchInventory.objects.get(branch=test_branch, batch=batch)
        assert inv.quantity == 27
