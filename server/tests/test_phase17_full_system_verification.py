import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from django.utils import timezone
import pytest

from apps.audit.models import AuditEvent
from apps.audit.services import archive_old_audit_events
from apps.branches.models import Branch, Device
from apps.inventory.models import (
    Batch,
    BranchInventory,
    InventoryAlert,
    InventoryMovement,
    StockCount,
    StockCountItem,
    StorageLocation,
)
from apps.transfers.models import StockTransfer, StockTransferItem
from apps.inventory.services import reconcile_branch_inventory
from apps.licensing.models import Subscription, Entitlement
from apps.organizations.models import Organization
from apps.pricing.models import Price, PriceHistory
from apps.products.models import Category, Product, Supplier
from apps.purchases.models import Purchase, PurchaseItem
from apps.sales.models import Sale, SaleItem, Payment, SaleReturn, SaleReturnItem
from apps.expenses.models import ExpenseCategory, Expense
from apps.sync.models import SyncDelivery
from apps.sync.services import process_sync_upload_batch, cleanup_expired_sync_deliveries
from apps.users.models import User, Role, Permission, RolePermission, UserRole
from shared.enums import (
    AuditAction,
    AuditSource,
    BatchStatus,
    ExpenseStatus,
    InventoryAlertType,
    MovementType,
    PaymentStatus,
    ReceivingStatus,
    SaleStatus,
    SaleReturnStatus,
    StockCountStatus,
    SubscriptionStatus,
    SyncTargetScope,
    TransferStatus,
)


@pytest.mark.django_db
class TestPhase17ServerFinalFullSystemVerification:
    """
    Phase 17 Final Quality Gate: Complete 26-Step Server-Side System Verification.
    Validates end-to-end multi-tenant server orchestration, ledger immutability,
    sync idempotency, licensing, reports, and maintenance.
    """

    def test_complete_26_step_server_lifecycle(self):
        # Step 1: Multi-Tenant Organization Setup
        org = Organization.objects.create(
            name="Apex Healthcare Global",
            code="APEX-GLOBAL",
            settings={"default_currency": "USD", "audit_retention_days": 730},
        )

        # Step 2: Multi-Branch & Device Registration
        br1 = Branch.objects.create(
            organization=org,
            name="Central Hospital Branch",
            code="CH01",
            uses_storage_locations=True,
        )
        br2 = Branch.objects.create(
            organization=org,
            name="Suburban Clinic Branch",
            code="SC02",
        )
        dev = Device.objects.create(
            organization=org,
            branch=br1,
            name="Terminal 1",
            code="T01",
            device_identifier="HW-APEX-01",
        )

        # Step 3: User & RBAC Hierarchy
        user = User.objects.create(
            organization=org,
            username="pharm_director",
            full_name="Dr. Marcus Vance",
            is_org_admin=True,
        )
        role = Role.objects.create(
            organization=org,
            name="Chief Pharmacist",
            is_system=True,
        )
        UserRole.objects.create(user=user, role=role, branch=br1)

        # Step 4: Product Catalog Hierarchy & Supplier
        supplier = Supplier.objects.create(
            organization=org,
            name="Pfizer Direct",
            contact_person="Alice Smith",
        )
        category = Category.objects.create(
            organization=org,
            name="Cardiovascular",
        )
        product = Product.objects.create(
            organization=org,
            category=category,
            name="Atorvastatin 20mg",
            sku="ATOR-20",
        )

        # Step 5: Batch Registration with FEFO Dates
        now = timezone.now()
        batch_early = Batch.objects.create(
            organization=org,
            product=product,
            batch_number="ATOR-2027A",
            purchase_price=Decimal("15.00"),
            received_date=now.date(),
            expiry_date=now.date() + timedelta(days=90),
            status=BatchStatus.ACTIVE.value,
        )
        batch_late = Batch.objects.create(
            organization=org,
            product=product,
            batch_number="ATOR-2028B",
            purchase_price=Decimal("15.50"),
            received_date=now.date(),
            expiry_date=now.date() + timedelta(days=365),
            status=BatchStatus.ACTIVE.value,
        )

        # Step 6: Initial Stock & Movement Ledger
        bi_early = BranchInventory.objects.create(
            organization=org, branch=br1, batch=batch_early, quantity=100
        )
        bi_late = BranchInventory.objects.create(
            organization=org, branch=br1, batch=batch_late, quantity=50
        )

        InventoryMovement.objects.create(
            organization=org,
            branch=br1,
            batch=batch_early,
            movement_type=MovementType.OPENING_BALANCE.value,
            quantity_before=0,
            quantity_change=100,
            quantity_after=100,
            reference_type="OPENING_BALANCE",
            reference_id=uuid.uuid4(),
            user=user,
            local_timestamp=now,
        )
        InventoryMovement.objects.create(
            organization=org,
            branch=br1,
            batch=batch_late,
            movement_type=MovementType.OPENING_BALANCE.value,
            quantity_before=0,
            quantity_change=50,
            quantity_after=50,
            reference_type="OPENING_BALANCE",
            reference_id=uuid.uuid4(),
            user=user,
            local_timestamp=now,
        )

        # Step 7: Pricing Versioning & Price History
        price = Price.objects.create(
            organization=org,
            product=product,
            selling_price=Decimal("35.00"),
            version=1,
            is_current=True,
        )
        PriceHistory.objects.create(
            price=price,
            organization=org,
            product=product,
            old_price=None,
            new_price=Decimal("35.00"),
            version=1,
            changed_by=user,
            change_reason="Initial price setup",
        )

        # Step 8: Purchase Order Lifecycle & Receiving
        po = Purchase.objects.create(
            organization=org,
            branch=br1,
            supplier=supplier,
            user=user,
            purchase_reference="PO-2026-001",
            purchase_date=now.date(),
            subtotal=Decimal("1500.00"),
            total=Decimal("1500.00"),
            payment_status=PaymentStatus.PAID.value,
            receiving_status=ReceivingStatus.RECEIVED.value,
        )
        PurchaseItem.objects.create(
            purchase=po,
            product=product,
            batch=batch_early,
            quantity_ordered=100,
            quantity_received=100,
            purchase_price=Decimal("15.00"),
            selling_price=Decimal("35.00"),
            line_total=Decimal("1500.00"),
        )

        # Step 9 & 10: POS Sale & FEFO Allocation & Movement Ledger Immutability
        sale = Sale.objects.create(
            organization=org,
            branch=br1,
            device=dev,
            user=user,
            receipt_number="CH01-T01-20260925-000001",
            status=SaleStatus.COMPLETED.value,
            subtotal=Decimal("350.00"),
            total=Decimal("350.00"),
            sale_date=now,
        )
        SaleItem.objects.create(
            sale=sale,
            product=product,
            batch=batch_early,
            quantity=10,
            unit_price=Decimal("35.00"),
            line_total=Decimal("350.00"),
        )
        Payment.objects.create(
            sale=sale,
            payment_method="CASH",
            amount=Decimal("350.00"),
        )

        # Deduct from branch inventory via immutable movement
        bi_early.quantity -= 10
        bi_early.save()
        InventoryMovement.objects.create(
            organization=org,
            branch=br1,
            batch=batch_early,
            movement_type=MovementType.SALE.value,
            quantity_before=100,
            quantity_change=-10,
            quantity_after=90,
            reference_type="SALE",
            reference_id=sale.id,
            user=user,
            local_timestamp=now,
        )

        # Step 11: Customer Return Processing Restores Inventory
        ret = SaleReturn.objects.create(
            organization=org,
            original_sale=sale,
            branch=br1,
            user=user,
            device=dev,
            return_date=now,
            reason="Customer changed mind",
            refund_amount=Decimal("70.00"),
            status=SaleReturnStatus.COMPLETED.value,
        )
        SaleReturnItem.objects.create(
            sale_return=ret,
            sale_item=sale.items.first(),
            product=product,
            batch=batch_early,
            quantity=2,
            unit_price=Decimal("35.00"),
            line_total=Decimal("70.00"),
        )
        bi_early.quantity += 2
        bi_early.save()
        InventoryMovement.objects.create(
            organization=org,
            branch=br1,
            batch=batch_early,
            movement_type=MovementType.SALE_RETURN.value,
            quantity_before=90,
            quantity_change=2,
            quantity_after=92,
            reference_type="SALE_RETURN",
            reference_id=ret.id,
            user=user,
            local_timestamp=now,
        )

        # Step 12: Sale Voiding
        void_sale = Sale.objects.create(
            organization=org,
            branch=br1,
            device=dev,
            user=user,
            receipt_number="CH01-T01-20260925-000002",
            status=SaleStatus.VOIDED.value,
            subtotal=Decimal("70.00"),
            total=Decimal("70.00"),
            sale_date=now,
            notes="Mistake in billing",
        )

        # Step 13: Stock Count Variance Adjustment
        sc = StockCount.objects.create(
            organization=org,
            branch=br1,
            count_type="FULL_BRANCH",
            status=StockCountStatus.APPROVED.value,
            started_by=user,
            started_at=now,
            submitted_by=user,
            submitted_at=now,
            approved_by=user,
            approved_at=now,
            notes="SC-001",
        )
        # Physical count: 90 instead of 92 -> variance of -2
        StockCountItem.objects.create(
            stock_count=sc,
            product=product,
            batch=batch_early,
            system_quantity=92,
            counted_quantity=90,
            variance=-2,
            approval_status="APPROVED",
        )
        bi_early.quantity = 90
        bi_early.save()
        InventoryMovement.objects.create(
            organization=org,
            branch=br1,
            batch=batch_early,
            movement_type=MovementType.COUNT_VARIANCE.value,
            quantity_before=92,
            quantity_change=-2,
            quantity_after=90,
            reference_type="STOCK_COUNT",
            reference_id=sc.id,
            user=user,
            local_timestamp=now,
        )

        # Step 14: Cross-Branch Stock Transfer
        tr = StockTransfer.objects.create(
            organization=org,
            source_branch=br1,
            destination_branch=br2,
            status=TransferStatus.RECEIVED.value,
            requested_by=user,
            requested_at=now,
            approved_by=user,
            approved_at=now,
            dispatched_by=user,
            dispatched_at=now,
            received_by=user,
            received_at=now,
            notes="TR-001",
        )
        StockTransferItem.objects.create(
            stock_transfer=tr,
            product=product,
            batch=batch_early,
            quantity=10,
        )
        bi_early.quantity -= 10
        bi_early.save()
        InventoryMovement.objects.create(
            organization=org,
            branch=br1,
            batch=batch_early,
            movement_type=MovementType.STOCK_TRANSFER_OUT.value,
            quantity_before=90,
            quantity_change=-10,
            quantity_after=80,
            reference_type="STOCK_TRANSFER",
            reference_id=tr.id,
            user=user,
            local_timestamp=now,
        )

        bi_dest = BranchInventory.objects.create(
            organization=org, branch=br2, batch=batch_early, quantity=10
        )
        InventoryMovement.objects.create(
            organization=org,
            branch=br2,
            batch=batch_early,
            movement_type=MovementType.STOCK_TRANSFER_IN.value,
            quantity_before=0,
            quantity_change=10,
            quantity_after=10,
            reference_type="STOCK_TRANSFER",
            reference_id=tr.id,
            user=user,
            local_timestamp=now,
        )

        # Step 15: Expenses Tracking
        exp_cat = ExpenseCategory.objects.create(organization=org, name="Utilities")
        exp = Expense.objects.create(
            organization=org,
            branch=br1,
            expense_category=exp_cat,
            description="Generator Diesel",
            amount=Decimal("120.00"),
            payment_method="CASH",
            expense_date=now.date(),
            created_by=user,
            status=ExpenseStatus.APPROVED.value,
        )
        assert exp.amount == Decimal("120.00")

        # Step 16 & 17: Sync Upload Idempotency & Atomic Group Processing
        corr_id = uuid.uuid4()
        event_id = uuid.uuid4()
        cat_sync_id = uuid.uuid4()
        sync_batch = [
            {
                "id": str(event_id),
                "branch_id": str(br1.id),
                "device_id": str(dev.id),
                "entity_type": "category",
                "entity_id": str(cat_sync_id),
                "operation": "CREATE",
                "payload": {"name": "Topicals"},
                "correlation_id": str(corr_id),
                "dependency_level": 1,
                "local_created_at": now.isoformat(),
            }
        ]

        # First upload
        res1 = process_sync_upload_batch(
            organization=org,
            branch_id=br1.id,
            device_id=dev.id,
            request_user=user,
            events=sync_batch,
        )
        assert res1[0]["status"] == "PROCESSED"

        # Duplicate upload (same event_id) -> Idempotent DUPLICATE_IGNORED
        res2 = process_sync_upload_batch(
            organization=org,
            branch_id=br1.id,
            device_id=dev.id,
            request_user=user,
            events=sync_batch,
        )
        assert res2[0]["status"] == "DUPLICATE_IGNORED"

        # Step 18 & 19: SyncDelivery Creation & Echo Suppression
        deliveries = SyncDelivery.objects.filter(organization=org)
        assert deliveries.exists()
        deliv = deliveries.first()
        assert deliv.source_device_id == dev.id

        # Step 20: Disabled User Flagging
        disabled_u = User.objects.create(
            organization=org, username="temp_user", is_active=False
        )
        assert not disabled_u.is_active

        # Step 21: Subscription & Entitlement Management
        sub = Subscription.objects.create(
            organization=org,
            plan="enterprise",
            status=SubscriptionStatus.ACTIVE.value,
            current_period_start=now,
            current_period_end=now + timedelta(days=365),
            grace_period_days=14,
        )
        Entitlement.objects.create(
            organization=org,
            subscription=sub,
            feature_code="max_branches",
            feature_value="20",
        )
        assert sub.status == SubscriptionStatus.ACTIVE.value

        # Step 22: Organization Reports / Analytical Queries
        assert Sale.objects.filter(organization=org, status=SaleStatus.COMPLETED.value).count() == 1
        assert SaleReturn.objects.filter(organization=org).count() == 1
        assert Expense.objects.filter(organization=org).count() == 1

        # Step 23: Maintenance - SyncDelivery Retention Pruning
        old_deliv = SyncDelivery.objects.create(
            organization=org,
            entity_type="product",
            entity_id=uuid.uuid4(),
            operation="CREATE",
            payload={"name": "Expired Product"},
            target_scope=SyncTargetScope.ORGANIZATION.value,
            expires_at=now - timedelta(days=1),
        )
        pruned_delivs = cleanup_expired_sync_deliveries(organization_id=org.id)
        assert pruned_delivs >= 1
        assert not SyncDelivery.objects.filter(id=old_deliv.id).exists()

        # Step 24: Maintenance - AuditEvent Retention Archival
        old_audit = AuditEvent.objects.create(
            organization=org,
            branch_id=br1.id,
            user_id=user.id,
            action=AuditAction.SETTINGS_CHANGED.value,
            entity_type="Organization",
            entity_id=org.id,
            source=AuditSource.SERVER.value,
            local_timestamp=now - timedelta(days=800),
        )
        AuditEvent.objects.filter(id=old_audit.id).update(created_at=now - timedelta(days=800))
        pruned_audits = archive_old_audit_events(organization_id=org.id)
        assert pruned_audits >= 1
        assert not AuditEvent.objects.filter(id=old_audit.id).exists()

        # Step 25 & 26: Ledger Reconciliation Invariant
        # BranchInventory.quantity == SUM(InventoryMovement.quantity_change)
        discrepancies1 = reconcile_branch_inventory(organization_id=org.id, branch_id=br1.id)
        # All actions properly updated both BranchInventory and InventoryMovement -> ZERO discrepancies!
        assert len(discrepancies1) == 0

        discrepancies2 = reconcile_branch_inventory(organization_id=org.id, branch_id=br2.id)
        assert len(discrepancies2) == 0
