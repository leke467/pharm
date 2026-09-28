"""Phase 9 Acceptance Tests — Stock Counts & Approval (Server)."""
import uuid
from datetime import date, timedelta
from decimal import Decimal
import pytest
from django.utils import timezone
from apps.audit.models import AuditEvent
from apps.inventory.models import Batch, BranchInventory, InventoryMovement, StockCount, StockCountItem
from apps.inventory.views import apply_inventory_movement
from apps.products.models import Category, Product
from apps.users.services import seed_permissions_and_roles
from shared.enums import (
    AuditAction,
    BatchStatus,
    MovementType,
    SYNC_DEPENDENCY_LEVELS,
)


@pytest.mark.django_db
class TestPhase9ServerStockCountAcceptance:
    """Server acceptance tests for Phase 9 Stock Counts & Approval."""

    def _setup_inventory(self, org, branch, user):
        seed_permissions_and_roles(org)
        user.is_org_admin = True
        user.save()

        cat, _ = Category.objects.get_or_create(organization=org, name="Antacids")
        prod = Product.objects.create(
            organization=org,
            sku="GAV-LIQ-200",
            name="Gaviscon Liquid 200ml",
            category=cat,
        )
        batch1 = Batch.objects.create(
            organization=org,
            product=prod,
            batch_number="GAV-001",
            expiry_date=date.today() + timedelta(days=200),
            purchase_price=Decimal("1200.00"),
            received_date=date.today(),
        )
        batch2 = Batch.objects.create(
            organization=org,
            product=prod,
            batch_number="GAV-002",
            expiry_date=date.today() + timedelta(days=300),
            purchase_price=Decimal("1250.00"),
            received_date=date.today(),
        )

        apply_inventory_movement(
            organization_id=org.id,
            branch_id=branch.id,
            batch_id=batch1.id,
            storage_location_id=None,
            movement_type=MovementType.OPENING_BALANCE.value,
            quantity_change=20,
            reference_type="init",
            reference_id=branch.id,
            user=user,
        )
        apply_inventory_movement(
            organization_id=org.id,
            branch_id=branch.id,
            batch_id=batch2.id,
            storage_location_id=None,
            movement_type=MovementType.OPENING_BALANCE.value,
            quantity_change=15,
            reference_type="init",
            reference_id=branch.id,
            user=user,
        )
        return prod, batch1, batch2

    def test_stock_count_full_lifecycle_variance_application_and_negative_guard(
        self, authenticated_client, test_user, test_organization, test_branch, test_device
    ):
        """
        1. Start stock count -> IN_PROGRESS. Starting another in same scope is blocked (400).
        2. Submit counts: batch1 counted 25 (system 20, variance +5), batch2 counted 10 (system 15, variance -5).
        3. Negative Quantity Guard: if an external sale reduces batch2 to 3 units, approving variance -5 (3 + (-5) = -2 < 0) is blocked with 400!
        4. When stock is sufficient, approving variances creates COUNT_VARIANCE movements and updates BranchInventory.
        """
        prod, batch1, batch2 = self._setup_inventory(
            test_organization, test_branch, test_user
        )

        # 1. Start stock count
        res_start = authenticated_client.post(
            "/api/v1/stock-counts/",
            {
                "branch_id": str(test_branch.id),
                "device_id": str(test_device.id),
                "count_type": "FULL_BRANCH",
                "notes": "Monthly full inventory count",
            },
            format="json",
        )
        assert res_start.status_code == 201, res_start.json()
        sc_data = res_start.json()
        sc_id = sc_data["id"]
        assert sc_data["status"] == "IN_PROGRESS"

        # Concurrency guard: starting second count in same scope blocked
        dup_start = authenticated_client.post(
            "/api/v1/stock-counts/",
            {"branch_id": str(test_branch.id), "count_type": "FULL_BRANCH"},
            format="json",
        )
        assert dup_start.status_code == 400

        # 2. Submit counts: batch1 counted 25 (+5), batch2 counted 10 (-5)
        res_submit = authenticated_client.post(
            f"/api/v1/stock-counts/{sc_id}/submit/",
            {
                "items": [
                    {"batch_id": str(batch1.id), "counted_quantity": 25},
                    {"batch_id": str(batch2.id), "counted_quantity": 10},
                ],
                "notes": "Physical count done by storekeeper",
            },
            format="json",
        )
        assert res_submit.status_code == 200, res_submit.json()
        sc_sub = res_submit.json()
        assert sc_sub["status"] == "SUBMITTED"
        assert len(sc_sub["items"]) == 2

        it1 = next(i for i in sc_sub["items"] if i["batch"] == str(batch1.id))
        it2 = next(i for i in sc_sub["items"] if i["batch"] == str(batch2.id))
        assert it1["variance"] == 5
        assert it2["variance"] == -5

        # 3. Simulate external sale reducing batch2 live inventory from 15 to 3
        inv2 = BranchInventory.objects.get(branch=test_branch, batch=batch2)
        apply_inventory_movement(
            organization_id=test_organization.id,
            branch_id=test_branch.id,
            batch_id=batch2.id,
            storage_location_id=None,
            movement_type=MovementType.SALE.value,
            quantity_change=-12,
            reference_type="sale",
            reference_id=uuid.uuid4(),
            user=test_user,
        )
        inv2.refresh_from_db()
        assert inv2.quantity == 3

        # Negative Quantity Guard: approving -5 variance when live qty is 3 -> 3 + (-5) = -2 < 0 -> BLOCKED (400)
        res_blocked = authenticated_client.post(
            f"/api/v1/stock-counts/{sc_id}/approve/",
            {
                "items": [
                    {"stock_count_item_id": it2["id"], "action": "APPROVE"}
                ]
            },
            format="json",
        )
        assert res_blocked.status_code == 400
        assert "negative_stock_guard" in str(res_blocked.json())

        # 4. Approve batch1 (+5 variance) and reject batch2 (for re-counting)
        res_appr = authenticated_client.post(
            f"/api/v1/stock-counts/{sc_id}/approve/",
            {
                "items": [
                    {"stock_count_item_id": it1["id"], "action": "APPROVE"},
                    {
                        "stock_count_item_id": it2["id"],
                        "action": "REJECT",
                        "rejection_reason": "Variance exceeds live stock after mid-count sales; recount required.",
                    },
                ]
            },
            format="json",
        )
        assert res_appr.status_code == 200, res_appr.json()
        assert res_appr.json()["status"] == "PARTIALLY_APPROVED"

        # Verify batch1 inventory was updated by variance: 20 + 5 = 25
        inv1 = BranchInventory.objects.get(branch=test_branch, batch=batch1)
        assert inv1.quantity == 25
        assert InventoryMovement.objects.filter(
            batch=batch1,
            movement_type=MovementType.COUNT_VARIANCE.value,
            quantity_change=5,
        ).exists()

        assert AuditEvent.objects.filter(
            entity_id=sc_id,
            action=AuditAction.STOCK_COUNT_APPROVED.value,
        ).exists()

    def test_sync_upload_multi_device_conflict_detection(
        self, authenticated_client, test_user, test_organization, test_branch, test_device
    ):
        """
        Offline multi-device conflict detection (Architecture Plan §9.3):
        When a stock count from device B arrives that overlaps with an already-submitted count
        from device A, server processes it with status = CONFLICT.
        """
        prod, batch1, batch2 = self._setup_inventory(
            test_organization, test_branch, test_user
        )
        # Device A already submitted a count
        sc_a = StockCount.objects.create(
            organization=test_organization,
            branch=test_branch,
            device=test_device,
            count_type="FULL_BRANCH",
            status="SUBMITTED",
            started_by=test_user,
            started_at=timezone.now(),
        )

        from apps.branches.models import Device
        device_b = Device.objects.create(
            organization=test_organization,
            branch=test_branch,
            name="Counter 2",
            code="D02",
            device_identifier="HW-DEV-B02",
        )
        device_b_id = str(device_b.id)
        corr_id = str(uuid.uuid4())
        sc_b_id = str(uuid.uuid4())
        now_iso = timezone.now().isoformat()

        events = [
            {
                "id": str(uuid.uuid4()),
                "entity_type": "stock_count",
                "entity_id": sc_b_id,
                "operation": "CREATE",
                "correlation_id": corr_id,
                "dependency_level": SYNC_DEPENDENCY_LEVELS["stock_count"],
                "local_created_at": now_iso,
                "payload": {
                    "id": sc_b_id,
                    "organization_id": str(test_organization.id),
                    "branch_id": str(test_branch.id),
                    "device_id": device_b_id,
                    "count_type": "FULL_BRANCH",
                    "status": "IN_PROGRESS",
                    "started_by_id": str(test_user.id),
                    "started_at": now_iso,
                    "notes": "Concurrent count from device B",
                },
            }
        ]

        res = authenticated_client.post(
            "/api/v1/sync/upload/",
            {
                "device_id": device_b_id,
                "branch_id": str(test_branch.id),
                "events": events,
            },
            format="json",
        )
        assert res.status_code == 200
        assert [r["status"] for r in res.data["results"]] == ["PROCESSED"]

        # Server flagged multi-device overlap as CONFLICT
        sc_b = StockCount.objects.get(id=sc_b_id)
        assert sc_b.status == "CONFLICT"
        assert "CONFLICT" in sc_b.notes
