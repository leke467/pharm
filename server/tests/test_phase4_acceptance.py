"""Phase 4 Acceptance Tests — Batches, Inventory & Basic Pricing (Server)."""
import uuid
from datetime import date, timedelta
from decimal import Decimal
import pytest
from django.core.exceptions import ValidationError as DjangoValidationError
from apps.inventory.models import (
    Batch,
    StorageLocation,
    StorageLocationAssignment,
    BranchInventory,
    InventoryMovement,
    InventoryAlert,
)
from apps.inventory.views import apply_inventory_movement
from apps.pricing.models import Price
from apps.pricing.views import resolve_product_price
from apps.products.models import Product, ProductType, Category
from apps.users.services import seed_permissions_and_roles
from shared.enums import BatchStatus, MovementType, InventoryAlertType


@pytest.mark.django_db
class TestPhase4Acceptance:
    """Acceptance tests for Phase 4 Batches, Inventory & Basic Pricing."""

    def _setup_org(self, org, user):
        seed_permissions_and_roles(org)
        if not user.is_org_admin:
            user.is_org_admin = True
            user.save()

    def _create_product(self, org, sku="PARA-500"):
        cat, _ = Category.objects.get_or_create(organization=org, name="Analgesics")
        pt, _ = ProductType.objects.get_or_create(organization=org, name="Medication")
        return Product.objects.create(
            organization=org,
            sku=sku,
            name="Paracetamol 500mg",
            category=cat,
            product_type=pt,
        )

    def test_batch_creation_and_expiry_status(self, authenticated_client, test_user, test_organization, test_branch):
        """1. Batch creation, automatic EXPIRED detection, and manual recall."""
        self._setup_org(test_organization, test_user)
        product = self._create_product(test_organization)
        today_str = date.today().isoformat()

        # Create active batch with future expiry
        future_date = (date.today() + timedelta(days=180)).isoformat()
        res = authenticated_client.post(
            "/api/v1/batches/",
            {
                "product": str(product.id),
                "batch_number": "BATCH-001",
                "expiry_date": future_date,
                "purchase_price": "250.00",
                "received_date": today_str,
            },
            format="json",
        )
        assert res.status_code == 201, res.data
        assert res.data["status"] == BatchStatus.ACTIVE.value

        # Create batch with past expiry -> automatically marked EXPIRED
        past_date = (date.today() - timedelta(days=5)).isoformat()
        res_exp = authenticated_client.post(
            "/api/v1/batches/",
            {
                "product": str(product.id),
                "batch_number": "BATCH-EXP",
                "expiry_date": past_date,
                "purchase_price": "200.00",
                "received_date": today_str,
            },
            format="json",
        )
        assert res_exp.status_code == 201
        assert res_exp.data["status"] == BatchStatus.EXPIRED.value

        # Recall active batch -> status transitions to RECALLED
        batch_id = res.data["id"]
        recall_res = authenticated_client.post(
            f"/api/v1/batches/{batch_id}/recall/",
            {"reason": "Manufacturer contamination notice"},
            format="json",
        )
        assert recall_res.status_code == 200
        assert recall_res.data["status"] == BatchStatus.RECALLED.value

    def test_storage_location_opt_in_per_branch(self, authenticated_client, test_user, test_organization, test_branch):
        """2. Optional storage locations blocked when branch.uses_storage_locations=False, allowed when True."""
        self._setup_org(test_organization, test_user)
        test_branch.uses_storage_locations = False
        test_branch.save()

        # Blocked when False
        res = authenticated_client.post(
            "/api/v1/storage-locations/",
            {"branch": str(test_branch.id), "name": "Shelf A1", "location_type": "SHELF"},
            format="json",
        )
        assert res.status_code == 400

        # Enable uses_storage_locations on branch
        test_branch.uses_storage_locations = True
        test_branch.save()

        res_ok = authenticated_client.post(
            "/api/v1/storage-locations/",
            {"branch": str(test_branch.id), "name": "Shelf A1", "location_type": "SHELF"},
            format="json",
        )
        assert res_ok.status_code == 201
        assert res_ok.data["name"] == "Shelf A1"

    def test_opening_balance_one_time_only(self, authenticated_client, test_user, test_organization, test_branch):
        """3. Opening balance creates OPENING_BALANCE movements, sets initial_stock_loaded=True, blocks repeat."""
        self._setup_org(test_organization, test_user)
        product = self._create_product(test_organization)
        batch = Batch.objects.create(
            organization=test_organization,
            product=product,
            batch_number="OB-2026-01",
            expiry_date=date.today() + timedelta(days=365),
            purchase_price=Decimal("150.00"),
            received_date=date.today(),
        )
        assert test_branch.initial_stock_loaded is False

        res = authenticated_client.post(
            "/api/v1/inventory/opening-balance/",
            {
                "branch_id": str(test_branch.id),
                "entries": [
                    {
                        "batch_id": str(batch.id),
                        "quantity": 100,
                        "reorder_level": 15,
                    }
                ],
            },
            format="json",
        )
        assert res.status_code == 201, res.data

        test_branch.refresh_from_db()
        assert test_branch.initial_stock_loaded is True

        inv = BranchInventory.objects.get(branch=test_branch, batch=batch)
        assert inv.quantity == 100
        assert inv.reorder_level == 15

        mv = InventoryMovement.objects.get(branch=test_branch, batch=batch)
        assert mv.movement_type == MovementType.OPENING_BALANCE.value
        assert mv.quantity_change == 100
        assert mv.quantity_before == 0
        assert mv.quantity_after == 100

        # Repeat opening balance must be rejected with 400
        res_repeat = authenticated_client.post(
            "/api/v1/inventory/opening-balance/",
            {
                "branch_id": str(test_branch.id),
                "entries": [
                    {
                        "batch_id": str(batch.id),
                        "quantity": 50,
                    }
                ],
            },
            format="json",
        )
        assert res_repeat.status_code == 400

    def test_stock_adjustment_and_movement_immutability(self, authenticated_client, test_user, test_organization, test_branch):
        """4. Stock adjustments update BranchInventory via immutable InventoryMovement records; depletion sets DEPLETED."""
        self._setup_org(test_organization, test_user)
        product = self._create_product(test_organization)
        batch = Batch.objects.create(
            organization=test_organization,
            product=product,
            batch_number="ADJ-001",
            expiry_date=date.today() + timedelta(days=180),
            purchase_price=Decimal("100.00"),
            received_date=date.today(),
        )

        # Positive adjustment (+20)
        res = authenticated_client.post(
            "/api/v1/inventory/adjust/",
            {
                "branch_id": str(test_branch.id),
                "batch_id": str(batch.id),
                "quantity_change": 20,
                "movement_type": MovementType.STOCK_ADJUSTMENT.value,
                "notes": "Found extra pack during audit",
            },
            format="json",
        )
        assert res.status_code == 200, res.data
        assert res.data["quantity"] == 20

        # Negative adjustment beyond available stock blocked by default
        res_neg_fail = authenticated_client.post(
            "/api/v1/inventory/adjust/",
            {
                "branch_id": str(test_branch.id),
                "batch_id": str(batch.id),
                "quantity_change": -25,
                "movement_type": MovementType.STOCK_ADJUSTMENT.value,
                "notes": "Damaged units",
            },
            format="json",
        )
        assert res_neg_fail.status_code == 400

        # Deplete exactly to 0 -> batch status transitions to DEPLETED
        res_deplete = authenticated_client.post(
            "/api/v1/inventory/adjust/",
            {
                "branch_id": str(test_branch.id),
                "batch_id": str(batch.id),
                "quantity_change": -20,
                "movement_type": MovementType.DAMAGE.value,
                "notes": "Water damage",
            },
            format="json",
        )
        assert res_deplete.status_code == 200
        batch.refresh_from_db()
        assert batch.status == BatchStatus.DEPLETED.value

        # Verify InventoryMovement is strictly immutable (cannot update or delete)
        mv = InventoryMovement.objects.filter(batch=batch).first()
        mv.notes = "Tampered notes"
        with pytest.raises(DjangoValidationError):
            mv.save()
        with pytest.raises(DjangoValidationError):
            mv.delete()

        # Server sync allow_negative=True creates OVERSOLD alert
        inv, _ = apply_inventory_movement(
            organization_id=test_organization.id,
            branch_id=test_branch.id,
            batch_id=batch.id,
            storage_location_id=None,
            movement_type=MovementType.SALE.value,
            quantity_change=-5,
            reference_type="sale",
            reference_id=uuid.uuid4(),
            user=test_user,
            notes="Offline sale synced concurrently",
            allow_negative=True,
        )
        assert inv.quantity == -5
        assert InventoryAlert.objects.filter(
            organization=test_organization,
            branch=test_branch,
            batch=batch,
            alert_type=InventoryAlertType.OVERSOLD.value,
        ).exists()

    def test_pricing_hierarchy_and_versioning(self, authenticated_client, test_user, test_organization, test_branch):
        """5. Price creation, atomic is_current switching, and branch-override vs org-default resolution."""
        self._setup_org(test_organization, test_user)
        product = self._create_product(test_organization, sku="AMOX-500")

        # Create Org-wide price v1 (branch=None)
        res_org1 = authenticated_client.post(
            "/api/v1/prices/",
            {
                "product": str(product.id),
                "selling_price": "1200.00",
                "effective_from": "2026-01-01T00:00:00Z",
            },
            format="json",
        )
        assert res_org1.status_code == 201, res_org1.data
        assert res_org1.data["version"] == 1
        assert res_org1.data["is_current"] is True

        # Create Org-wide price v2 -> v1 must become is_current=False
        res_org2 = authenticated_client.post(
            "/api/v1/prices/",
            {
                "product": str(product.id),
                "selling_price": "1350.00",
                "effective_from": "2026-02-01T00:00:00Z",
            },
            format="json",
        )
        assert res_org2.status_code == 201
        assert res_org2.data["version"] == 2
        p1 = Price.objects.get(id=res_org1.data["id"])
        assert p1.is_current is False

        # Resolve price for branch (no branch override yet -> returns org v2 price 1350)
        res_resolve1 = authenticated_client.get(
            f"/api/v1/prices/resolve/?product_id={product.id}&branch_id={test_branch.id}"
        )
        assert res_resolve1.status_code == 200
        assert Decimal(res_resolve1.data["selling_price"]) == Decimal("1350.00")

        # Create Branch-specific override price -> resolution returns branch override (1500)
        res_branch = authenticated_client.post(
            "/api/v1/prices/",
            {
                "product": str(product.id),
                "branch": str(test_branch.id),
                "selling_price": "1500.00",
                "effective_from": "2026-02-15T00:00:00Z",
            },
            format="json",
        )
        assert res_branch.status_code == 201
        assert res_branch.data["version"] == 1

        res_resolve2 = authenticated_client.get(
            f"/api/v1/prices/resolve/?product_id={product.id}&branch_id={test_branch.id}"
        )
        assert res_resolve2.status_code == 200
        assert Decimal(res_resolve2.data["selling_price"]) == Decimal("1500.00")
        assert str(res_resolve2.data["branch"]) == str(test_branch.id)
