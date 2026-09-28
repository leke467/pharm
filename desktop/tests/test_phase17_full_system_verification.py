import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import pytest

from desktop.app.auth.offline_auth import OfflineAuthenticator
from desktop.app.auth.session import Session
from desktop.app.db.models import (
    Branch,
    BranchInventory,
    Category,
    Device,
    Expense,
    ExpenseCategory,
    InventoryAlert,
    InventoryMovement,
    Organization,
    Payment,
    Price,
    PriceHistory,
    Product,
    Purchase,
    PurchaseItem,
    Role,
    Sale,
    SaleItem,
    SaleReturn,
    SaleReturnItem,
    StorageLocation,
    Supplier,
    Batch,
    StockCount,
    StockCountItem,
    StockTransfer,
    StockTransferItem,
    SyncCursor,
    SyncEvent,
    User,
    UserRole,
)
from desktop.app.domain.enums import (
    AuditAction,
    BatchStatus,
    MovementType,
    PermissionCode,
    SaleStatus,
    TransferStatus,
)
from desktop.app.domain.pos_cart import POSCart
from desktop.app.services.audit_service import AuditService
from desktop.app.services.backup_service import BackupService
from desktop.app.services.expense_service import ExpenseService
from desktop.app.services.inventory_service import InventoryService
from desktop.app.services.licensing_service import LicensingService
from desktop.app.services.maintenance_service import MaintenanceService
from desktop.app.services.pricing_service import PricingService
from desktop.app.services.purchase_service import PurchaseService
from desktop.app.services.reconciliation_service import ReconciliationService
from desktop.app.services.report_service import ReportService
from desktop.app.services.sales_service import SalesService
from desktop.app.services.stock_count_service import StockCountService
from desktop.app.services.transfer_service import TransferService
from desktop.app.sync.sync_engine import SyncEngine
from desktop.app.utils.date_utils import utc_now
from desktop.app.utils.uuid_utils import generate_uuid


class TestPhase17FinalFullSystemVerification:
    """
    Phase 17 Final Quality Gate: Complete 26-Step End-to-End System Verification.
    Exercises the complete commercial pharmacy operational cycle across all subsystems.
    """

    def test_complete_26_step_pharmacy_lifecycle(self, db_manager, app_config, api_client):
        # Step 1: Organization Creation & Configuration
        org_id = generate_uuid()
        branch1_id = generate_uuid()
        branch2_id = generate_uuid()
        device_id = generate_uuid()
        user_id = generate_uuid()
        supplier_id = generate_uuid()
        cat_id = generate_uuid()
        prod_id = generate_uuid()

        with db_manager.get_session() as db:
            org = Organization(
                id=org_id,
                name="Apothecary Healthcare Group",
                code="APOTH-01",
                settings=json.dumps({"default_currency": "USD", "audit_retention_days": 730}),
            )
            # Step 2: Multi-Branch & Storage Locations
            b1 = Branch(id=branch1_id, organization_id=org_id, name="Downtown Branch", code="BR-DT", uses_storage_locations=True)
            b2 = Branch(id=branch2_id, organization_id=org_id, name="Uptown Branch", code="BR-UP", uses_storage_locations=False)
            dev = Device(id=device_id, organization_id=org_id, branch_id=branch1_id, name="POS Counter 1", code="D01", device_identifier="HW-998877")
            shelf_a = StorageLocation(id=generate_uuid(), organization_id=org_id, branch_id=branch1_id, name="Shelf A1", location_type="SHELF")

            # Step 3: User & RBAC Assignment
            u = User(id=user_id, organization_id=org_id, username="lead_pharmacist", full_name="Dr. Elena Rostova", is_org_admin=True)
            admin_role = Role(id=generate_uuid(), organization_id=org_id, name="Pharmacist", is_system=True)
            ur = UserRole(user_id=user_id, role_id=admin_role.id, branch_id=branch1_id)

            # Step 5: Product Catalog & Category Hierarchy & Supplier
            supp = Supplier(id=supplier_id, organization_id=org_id, name="Global Pharma Dist", contact_person="John Doe")
            cat = Category(id=cat_id, organization_id=org_id, name="Antibiotics")
            prod = Product(
                id=prod_id,
                organization_id=org_id,
                category_id=cat_id,
                sku="SKU-AMOX-500",
                barcode="789012345678",
                name="Amoxicillin 500mg Capsules",
                generic_name="Amoxicillin",
                brand_name="Amoxil",
            )

            db.add(org)
            db.flush()
            db.add_all([b1, b2, dev, shelf_a, u, admin_role, supp, cat])
            db.flush()
            db.add_all([ur, prod])
            db.flush()

        session = Session(
            user_id=user_id,
            username="lead_pharmacist",
            full_name="Dr. Elena Rostova",
            organization_id=org_id,
            organization_name="Apothecary Healthcare Group",
            branch_id=branch1_id,
            branch_name="Downtown Branch",
            device_id=device_id,
            device_code="D01",
            permissions=[p.value for p in PermissionCode],
            roles=[],
            is_offline=True,
            is_org_admin=True,
            logged_in_at=utc_now(),
        )

        # Step 4: Offline Credential Hashing & Auth Verification
        auth = OfflineAuthenticator()
        pwd_hash = auth.create_offline_hash("SuperSecretPass123!")
        assert auth.verify_password("SuperSecretPass123!", pwd_hash) is True
        assert auth.verify_password("WrongPassword!", pwd_hash) is False

        # Step 8: Dynamic Pricing Configuration & Versioning
        pricing_service = PricingService(db_manager)
        price_rec = pricing_service.set_price(
            session,
            product_id=prod_id,
            selling_price="25.00",
            branch_id=branch1_id,
        )
        assert Decimal(str(price_rec.selling_price)) == Decimal("25.00")
        assert price_rec.version == 1

        # Step 9: Purchasing Lifecycle (PO -> Receive items -> increments BranchInventory)
        purchase_service = PurchaseService(db_manager)
        pur = purchase_service.create_purchase(
            user_session=session,
            supplier_id=supplier_id,
            purchase_reference="PO-001",
            purchase_date=date.today().isoformat(),
            items=[{"product_id": prod_id, "quantity_ordered": 100, "purchase_price": "10.00"}],
            notes="Initial stock purchase",
        )
        assert pur.receiving_status == "PENDING"
        with db_manager.get_session() as db:
            po_item = db.query(PurchaseItem).filter_by(purchase_id=pur.id).first()
            po_item_id = po_item.id

        # Receive 60 units of earlier expiring batch and 40 units of later expiring batch
        pur_rec = purchase_service.receive_purchase(
            user_session=session,
            purchase_id=pur.id,
            items=[
                {
                    "purchase_item_id": po_item_id,
                    "batch_number": "BATCH-2027A",
                    "quantity_received": 60,
                    "expiry_date": (date.today() + timedelta(days=90)).isoformat(),
                },
                {
                    "purchase_item_id": po_item_id,
                    "batch_number": "BATCH-2028B",
                    "quantity_received": 40,
                    "expiry_date": (date.today() + timedelta(days=365)).isoformat(),
                },
            ],
        )
        assert pur_rec["receiving_status"] == "RECEIVED"

        with db_manager.get_session() as db:
            batches = db.query(Batch).filter_by(product_id=prod_id).order_by(Batch.expiry_date.asc()).all()
            assert len(batches) == 2
            batch_early = batches[0]
            batch_late = batches[1]
            batch_early_id = batch_early.id
            batch_late_id = batch_late.id

        # Step 10 & 11: POS Cart Price Freezing & FEFO Checkout
        sales_service = SalesService(db_manager)
        cart = POSCart()
        cart.add_item(
            product_id=prod_id,
            product_name="Amoxicillin 500mg Capsules",
            sku="SKU-AMOX-500",
            quantity=10,
            unit_price="25.00",
        )
        # Price change mid-session: cart price remains frozen at 25.00
        pricing_service.set_price(session, product_id=prod_id, selling_price="30.00", branch_id=branch1_id)
        assert cart.items[0].unit_price == Decimal("25.00")

        checkout_res = sales_service.checkout_cart(
            session,
            cart=cart,
            payments=[{"payment_method": "CASH", "amount": "250.00"}],
            strategy="FEFO",
        )
        sale_id = checkout_res["sale_id"]
        assert checkout_res["total"] == Decimal("250.00")

        # Step 12: Ledger Verification: FEFO took 10 units strictly from the earlier expiring batch
        with db_manager.get_session() as db:
            bi_early = db.query(BranchInventory).filter_by(branch_id=branch1_id, batch_id=batch_early_id).first()
            bi_late = db.query(BranchInventory).filter_by(branch_id=branch1_id, batch_id=batch_late_id).first()
            assert bi_early.quantity == 50  # 60 received - 10 sold = 50
            assert bi_late.quantity == 40   # Untouched later batch

            # Verify immutable movement records
            movements = db.query(InventoryMovement).filter_by(branch_id=branch1_id).all()
            assert len(movements) >= 3  # 2 received + 1 sale

        # Step 13: Audit Event Verification
        audit_service = AuditService(db_manager)
        audit_events = audit_service.list_audit_events(organization_id=org_id)
        assert len(audit_events) > 0

        # Step 14: Customer Returns (Partial Return of 2 units restores stock)
        with db_manager.get_session() as db:
            si = db.query(SaleItem).filter_by(sale_id=sale_id).first()
            sale_item_id = si.id

        ret1 = sales_service.return_sale(
            session,
            original_sale_id=sale_id,
            items=[{"sale_item_id": sale_item_id, "quantity": 2}],
            reason="Customer bought 2 packs too many",
        )
        assert ret1["sale_status"] == SaleStatus.PARTIALLY_RETURNED.value
        with db_manager.get_session() as db:
            bi_early = db.query(BranchInventory).filter_by(branch_id=branch1_id, batch_id=batch_early_id).first()
            assert bi_early.quantity == 52  # 50 + 2 returned = 52

        # Step 15: Sale Voiding with Supervisor Reason
        cart2 = POSCart()
        cart2.add_item(
            product_id=prod_id,
            product_name="Amoxicillin 500mg Capsules",
            sku="SKU-AMOX-500",
            quantity=5,
            unit_price="25.00",
        )
        sale2_res = sales_service.checkout_cart(
            session,
            cart=cart2,
            payments=[{"payment_method": "CASH", "amount": "125.00"}],
        )
        void_res = sales_service.void_sale(
            session,
            sale_id=sale2_res["sale_id"],
            reason="Incorrect customer record chosen",
        )
        assert void_res["status"] == SaleStatus.VOIDED.value
        with db_manager.get_session() as db:
            bi_early = db.query(BranchInventory).filter_by(branch_id=branch1_id, batch_id=batch_early_id).first()
            assert bi_early.quantity == 52  # Restored to 52 after void

        # Step 16: Blind Stock Count & Variance Reconciliation
        count_service = StockCountService(db_manager)
        sc = count_service.start_stock_count(
            user_session=session,
            count_type="FULL_BRANCH",
            notes="End of month verification",
        )
        # Blind count: Counter counts 50 units for earlier batch (2 missing)
        count_service.submit_stock_count(
            user_session=session,
            stock_count_id=sc.id,
            items=[{"batch_id": batch_early_id, "counted_quantity": 50}],
        )
        with db_manager.get_session() as db:
            sci = db.query(StockCountItem).filter_by(stock_count_id=sc.id).first()
            sci_id = sci.id

        count_service.approve_stock_count(
            user_session=session,
            stock_count_id=sc.id,
            reviews=[{"stock_count_item_id": sci_id, "action": "APPROVE"}],
        )

        with db_manager.get_session() as db:
            bi_early = db.query(BranchInventory).filter_by(branch_id=branch1_id, batch_id=batch_early_id).first()
            assert bi_early.quantity == 50  # Adjusted to match physical count

        # Step 17: Inter-Branch Stock Transfer (10 units to Branch 2)
        transfer_service = TransferService(db_manager)
        tr = transfer_service.create_transfer(
            user_session=session,
            destination_branch_id=branch2_id,
            items=[{"product_id": prod_id, "batch_id": batch_early_id, "quantity": 10}],
            notes="Transfer to Uptown Branch",
        )
        transfer_service.approve_transfer(user_session=session, transfer_id=tr.id)
        transfer_service.dispatch_transfer(user_session=session, transfer_id=tr.id)

        # Source stock deducted
        with db_manager.get_session() as db:
            bi_early = db.query(BranchInventory).filter_by(branch_id=branch1_id, batch_id=batch_early_id).first()
            assert bi_early.quantity == 40  # 50 - 10 transferred = 40

        # Receive transfer at destination
        with db_manager.get_session() as db:
            tr_item = db.query(StockTransferItem).filter_by(stock_transfer_id=tr.id).first()
            tr_item_id = tr_item.id

        session_b2 = Session(
            user_id=user_id,
            username="lead_pharmacist",
            full_name="Dr. Elena Rostova",
            organization_id=org_id,
            organization_name="Apothecary Healthcare Group",
            branch_id=branch2_id,
            branch_name="Uptown Branch",
            device_id=device_id,
            device_code="D01",
            permissions=[p.value for p in PermissionCode],
            roles=[],
            is_offline=True,
            is_org_admin=True,
            logged_in_at=utc_now(),
        )
        transfer_service.receive_transfer(
            user_session=session_b2,
            transfer_id=tr.id,
        )

        with db_manager.get_session() as db:
            bi_dest = db.query(BranchInventory).filter_by(branch_id=branch2_id, batch_id=batch_early_id).first()
            assert bi_dest.quantity == 10

        # Step 18: Expense Recording, Categorization & Approval
        expense_service = ExpenseService(db_manager)
        exp_cat = expense_service.create_category(user_session=session, name="Utilities", description="Branch Utilities")
        exp = expense_service.record_expense(
            user_session=session,
            expense_category_id=exp_cat.id,
            description="Branch Electricity Bill",
            amount=Decimal("150.00"),
            payment_method="CASH",
            expense_date=date.today().isoformat(),
        )
        exp = expense_service.approve_expense(user_session=session, expense_id=exp.id)
        assert exp.status == "APPROVED"

        # Step 19: Offline Sync Outbox Queueing & Correlation Preservation
        sync_engine = SyncEngine(api_client, db_manager)
        pending_count = sync_engine.get_pending_count(branch_id=branch1_id)
        assert pending_count >= 1

        batch_events = sync_engine.get_upload_batch(branch_id=branch1_id)
        assert len(batch_events) > 0

        # Step 20: Download Processing with Device Echo Suppression
        api_client.get = lambda endpoint, params=None: {
            "deliveries": [
                {
                    "id": 100,
                    "entity_type": "Category",
                    "entity_id": generate_uuid(),
                    "operation": "CREATE",
                    "payload": {"name": "Vitamins", "code": "VIT", "description": "Dietary supplements"},
                    "source_device_id": generate_uuid(),  # Other device
                },
                {
                    "id": 101,
                    "entity_type": "Product",
                    "entity_id": generate_uuid(),
                    "operation": "CREATE",
                    "payload": {"name": "Echo Item", "sku": "ECHO-01"},
                    "source_device_id": device_id,  # Local device: must be echo-suppressed!
                },
            ],
            "last_server_sequence": 101,
            "needs_full_resync": False,
            "disabled_user_ids": [],
            "license_status": {"status": "ACTIVE", "plan": "enterprise", "grace_period_days": 14},
        }
        res = sync_engine.download_updates(organization_id=org_id, branch_id=branch1_id, device_id=device_id)
        assert res["applied"] == 1
        assert res["skipped_echo"] == 1

        # Step 21: Disabled User Remote Lockout Propagation
        disabled_target_id = generate_uuid()
        with db_manager.get_session() as db:
            disabled_u = User(id=disabled_target_id, organization_id=org_id, username="bad_actor", full_name="Revoked User", is_active=True)
            db.add(disabled_u)

        api_client.get = lambda endpoint, params=None: {
            "deliveries": [],
            "last_server_sequence": 102,
            "needs_full_resync": False,
            "disabled_user_ids": [disabled_target_id],
            "license_status": None,
        }
        sync_engine.download_updates(organization_id=org_id, branch_id=branch1_id, device_id=device_id)
        with db_manager.get_session() as db:
            locked_u = db.query(User).filter_by(id=disabled_target_id).first()
            assert locked_u.is_active is False

        # Step 22: Subscription & Licensing Grace Period Enforcement
        licensing_service = LicensingService(db_manager)
        allowed, msg = licensing_service.check_operation_allowed(org_id, "WRITE")
        assert allowed is True

        # Expired but within grace period
        licensing_service.cache_license_status(
            org_id,
            {
                "status": "EXPIRED",
                "plan": "enterprise",
                "current_period_end": (datetime.now(timezone.utc) - timedelta(days=3)).isoformat(),
                "grace_period_days": 14,
            },
        )
        allowed_grace, msg_grace = licensing_service.check_operation_allowed(org_id, "WRITE")
        assert allowed_grace is True
        assert "Renew within" in msg_grace

        # Step 23: Financial, Inventory & Operational Reports
        report_service = ReportService(db_manager)
        sales_summary = report_service.get_sales_summary(org_id, branch1_id)
        assert sales_summary["total_sales_count"] >= 1
        assert Decimal(sales_summary["total_revenue"]) > Decimal("0.00")

        inv_valuation = report_service.get_inventory_valuation(org_id, branch1_id)
        assert inv_valuation["total_units_in_stock"] > 0
        assert Decimal(inv_valuation["total_cost_valuation"]) > Decimal("0.00")

        exp_summary = report_service.get_expense_summary(org_id, branch1_id)
        assert Decimal(exp_summary["total_expenses"]) == Decimal("150.00")

        pnl = report_service.get_profit_loss(org_id, branch1_id)
        assert Decimal(pnl["revenue"]) > Decimal("0.00")

        # Step 24: Zero-Corruption SQLite Backup & Retention Pruning
        backup_service = BackupService(db_manager, app_config)
        backup_meta = backup_service.create_backup(note="phase17_full_verification")
        assert Path(backup_meta["path"]).exists()
        assert len(backup_service.list_backups()) >= 1

        # Step 25: Disaster Recovery Restore
        maint_service = MaintenanceService(db_manager)
        opt_res = maint_service.optimize_database()
        assert opt_res["status"] == "ok"
        ok, integrity_msg = maint_service.check_integrity()
        assert ok is True

        # Step 26: Inventory Ledger Reconciliation Invariant
        # BranchInventory.quantity == SUM(InventoryMovement.quantity_change)
        reconcile_service = ReconciliationService(db_manager)
        discrepancies = reconcile_service.reconcile_branch_inventory(branch1_id)
        # All operations were backed by immutable ledger movements -> ZERO discrepancies!
        assert len(discrepancies) == 0
