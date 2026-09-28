"""Phase 14 Acceptance Tests — Dashboards & Reporting (Desktop)."""
import json
import uuid
from datetime import date, timedelta, datetime, timezone
from decimal import Decimal
import pytest
from desktop.app.auth.session import Session
from desktop.app.db.models import (
    Organization,
    Branch,
    Device,
    User,
    Category,
    Product,
    Batch,
    BranchInventory,
    Sale,
    SaleItem,
    Payment,
    ExpenseCategory,
    Expense,
)
from desktop.app.domain.enums import PermissionCode, SaleStatus, ExpenseStatus
from desktop.app.services.report_service import ReportService
from desktop.app.utils.date_utils import utc_now
from desktop.app.utils.uuid_utils import generate_uuid


class TestPhase14DesktopReportsAcceptance:
    """Desktop acceptance tests for Phase 14 Reports & Analytics."""

    def _seed(self, db_manager):
        org_id = generate_uuid()
        branch_id = generate_uuid()
        device_id = generate_uuid()
        user_id = generate_uuid()
        cat_id = generate_uuid()
        prod_id = generate_uuid()
        b_act_id = generate_uuid()
        b_exp_soon_id = generate_uuid()
        b_expired_id = generate_uuid()
        exp_cat_id = generate_uuid()

        today = date.today()
        today_iso = today.isoformat()
        now_utc = datetime.now(timezone.utc).isoformat()

        with db_manager.get_session() as db:
            db.add(Organization(id=org_id, name="Medix Reports", code="RPT"))
            db.flush()
            db.add(Branch(id=branch_id, organization_id=org_id, name="Central Branch", code="CEN"))
            db.flush()
            db.add(Device(
                id=device_id,
                organization_id=org_id,
                branch_id=branch_id,
                name="POS 1",
                code="P01",
                device_identifier="DEV-RPT-01",
            ))
            db.flush()
            db.add(User(
                id=user_id,
                organization_id=org_id,
                username="cashier_jane",
                full_name="Jane Doe",
                is_org_admin=False,
            ))
            db.flush()
            db.add(Category(id=cat_id, organization_id=org_id, name="Analgesics"))
            db.flush()
            db.add(Product(
                id=prod_id,
                organization_id=org_id,
                category_id=cat_id,
                sku="PAR-500",
                name="Paracetamol 500mg",
            ))
            db.flush()

            # Active Batch: 100 units @ 50.00 cost
            db.add(Batch(
                id=b_act_id,
                organization_id=org_id,
                product_id=prod_id,
                batch_number="B-ACT-001",
                expiry_date=(today + timedelta(days=200)).isoformat(),
                purchase_price=Decimal("50.00"),
                received_date=today_iso,
                status="ACTIVE",
            ))
            # Expiring Soon Batch: 5 units @ 40.00 cost (Low Stock <= 10)
            db.add(Batch(
                id=b_exp_soon_id,
                organization_id=org_id,
                product_id=prod_id,
                batch_number="B-EXP-002",
                expiry_date=(today + timedelta(days=25)).isoformat(),
                purchase_price=Decimal("40.00"),
                received_date=today_iso,
                status="ACTIVE",
            ))
            # Expired Batch: 10 units @ 30.00 cost
            db.add(Batch(
                id=b_expired_id,
                organization_id=org_id,
                product_id=prod_id,
                batch_number="B-EXP-003",
                expiry_date=(today - timedelta(days=15)).isoformat(),
                purchase_price=Decimal("30.00"),
                received_date=(today - timedelta(days=365)).isoformat(),
                status="EXPIRED",
            ))
            db.flush()

            # Inventories
            db.add(BranchInventory(
                id=generate_uuid(),
                organization_id=org_id,
                branch_id=branch_id,
                batch_id=b_act_id,
                quantity=100,
                reorder_level=20,
            ))
            db.add(BranchInventory(
                id=generate_uuid(),
                organization_id=org_id,
                branch_id=branch_id,
                batch_id=b_exp_soon_id,
                quantity=5,  # Low stock
                reorder_level=10,
            ))
            db.add(BranchInventory(
                id=generate_uuid(),
                organization_id=org_id,
                branch_id=branch_id,
                batch_id=b_expired_id,
                quantity=10,
                reorder_level=5,
            ))
            db.flush()

            # Completed Sale: 20 units of active batch @ 150.00 = 3000.00
            # COGS = 20 * 50.00 = 1000.00; Profit = 2000.00
            sale_id = generate_uuid()
            db.add(Sale(
                id=sale_id,
                organization_id=org_id,
                branch_id=branch_id,
                user_id=user_id,
                device_id=device_id,
                receipt_number="CEN-P01-20260925-0001",
                subtotal=Decimal("3000.00"),
                discount_amount=Decimal("0.00"),
                tax_amount=Decimal("0.00"),
                total=Decimal("3000.00"),
                status=SaleStatus.COMPLETED.value,
                sale_date=now_utc,
            ))
            db.flush()
            db.add(SaleItem(
                id=generate_uuid(),
                sale_id=sale_id,
                product_id=prod_id,
                batch_id=b_act_id,
                quantity=20,
                unit_price=Decimal("150.00"),
                discount_amount=Decimal("0.00"),
                line_total=Decimal("3000.00"),
            ))
            db.add(Payment(
                id=generate_uuid(),
                sale_id=sale_id,
                payment_method="CASH",
                amount=Decimal("2000.00"),
            ))
            db.add(Payment(
                id=generate_uuid(),
                sale_id=sale_id,
                payment_method="CARD",
                amount=Decimal("1000.00"),
            ))
            db.flush()

            # Expense: 400.00 Transport
            db.add(ExpenseCategory(
                id=exp_cat_id,
                organization_id=org_id,
                name="Logistics",
                is_active=True,
            ))
            db.flush()
            db.add(Expense(
                id=generate_uuid(),
                organization_id=org_id,
                branch_id=branch_id,
                expense_category_id=exp_cat_id,
                description="Delivery transport fee",
                amount=Decimal("400.00"),
                payment_method="CASH",
                expense_date=today_iso,
                created_by_id=user_id,
                status=ExpenseStatus.APPROVED.value,
            ))
            db.commit()

        session = Session(
            user_id=user_id,
            username="cashier_jane",
            full_name="Jane Doe",
            organization_id=org_id,
            organization_name="Medix Reports",
            branch_id=branch_id,
            branch_name="Central Branch",
            device_id=device_id,
            device_code="P01",
            permissions=[PermissionCode.REPORTS_VIEW.value],
            roles=["Cashier"],
            is_offline=True,
            is_org_admin=False,
            access_token=None,
            refresh_token=None,
            logged_in_at=utc_now(),
        )

        return {
            'org_id': org_id,
            'branch_id': branch_id,
            'user_id': user_id,
            'session': session,
        }

    def test_desktop_sales_summary(self, db_manager):
        data = self._seed(db_manager)
        service = ReportService(db_manager)

        res = service.get_sales_summary(data['org_id'], branch_id=data['branch_id'])
        assert res['total_sales_count'] == 1
        assert Decimal(res['total_revenue']) == Decimal("3000.00")
        assert res['total_items_sold'] == 20
        assert Decimal(res['cost_of_goods_sold']) == Decimal("1000.00")
        assert Decimal(res['gross_profit']) == Decimal("2000.00")

        payments = {p['method']: Decimal(p['total']) for p in res['payment_breakdown']}
        assert payments['CASH'] == Decimal("2000.00")
        assert payments['CARD'] == Decimal("1000.00")

    def test_desktop_inventory_valuation(self, db_manager):
        data = self._seed(db_manager)
        service = ReportService(db_manager)

        res = service.get_inventory_valuation(data['org_id'], branch_id=data['branch_id'])
        # Total units = 100 + 5 + 10 = 115
        assert res['total_units_in_stock'] == 115
        assert res['total_batches_in_stock'] == 3

        # Cost valuation = (100 * 50) + (5 * 40) + (10 * 30) = 5000 + 200 + 300 = 5500.00
        assert Decimal(res['total_cost_valuation']) == Decimal("5500.00")

        # Low stock: 1 batch
        assert res['low_stock_count'] == 1
        assert res['low_stock_items'][0]['batch_number'] == "B-EXP-002"

        # Expiry counts
        assert res['expired_batches_count'] == 1
        assert res['expiring_soon_batches_count'] == 1

    def test_desktop_expense_summary(self, db_manager):
        data = self._seed(db_manager)
        service = ReportService(db_manager)

        res = service.get_expense_summary(data['org_id'], branch_id=data['branch_id'])
        assert Decimal(res['total_expenses']) == Decimal("400.00")
        assert res['total_count'] == 1
        assert res['category_breakdown'][0]['category'] == "Logistics"
        assert res['payment_breakdown'][0]['method'] == "CASH"

    def test_desktop_profit_loss(self, db_manager):
        data = self._seed(db_manager)
        service = ReportService(db_manager)

        res = service.get_profit_loss(data['org_id'], branch_id=data['branch_id'])
        assert Decimal(res['revenue']) == Decimal("3000.00")
        assert Decimal(res['cost_of_goods_sold']) == Decimal("1000.00")
        assert Decimal(res['gross_profit']) == Decimal("2000.00")
        assert Decimal(res['operating_expenses']) == Decimal("400.00")
        # Net Profit = 2000.00 - 400.00 = 1600.00
        assert Decimal(res['net_profit']) == Decimal("1600.00")

    def test_desktop_cashier_shift(self, db_manager):
        data = self._seed(db_manager)
        service = ReportService(db_manager)

        today_str = date.today().isoformat()
        res = service.get_cashier_shift_summary(data['org_id'], branch_id=data['branch_id'], date_str=today_str)
        shifts = res['shifts']
        assert len(shifts) == 1
        shift = shifts[0]
        assert shift['username'] == "cashier_jane"
        assert shift['sales_count'] == 1
        assert Decimal(shift['total_collected']) == Decimal("3000.00")
        assert Decimal(shift['payments']['CASH']) == Decimal("2000.00")
        assert Decimal(shift['payments']['CARD']) == Decimal("1000.00")
