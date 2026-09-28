"""Phase 14 Acceptance Tests — Dashboards & Reporting (Server)."""
import uuid
from datetime import date, timedelta
from decimal import Decimal
import pytest
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.organizations.models import Organization
from apps.branches.models import Branch, Device
from apps.users.models import User, Role, Permission, RolePermission, UserRole
from apps.products.models import Product, Category
from apps.inventory.models import Batch, BranchInventory
from apps.sales.models import Sale, SaleItem, Payment
from apps.expenses.models import ExpenseCategory, Expense
from shared.enums import PermissionCode, SaleStatus, ExpenseStatus


@pytest.mark.django_db
class TestPhase14ServerReportsAcceptance:
    """Server acceptance tests for Phase 14 Reports & Analytics."""

    @pytest.fixture
    def setup_data(self):
        org = Organization.objects.create(name="Report Medix", code="RPT")
        branch = Branch.objects.create(organization=org, name="Central Branch", code="CEN")
        device = Device.objects.create(
            organization=org,
            branch=branch,
            name="POS 1",
            code="P1",
            device_identifier="DEV-RPT-01",
        )
        user = User.objects.create_user(
            username="analyst",
            organization_id=org.id,
            password="password123",
            full_name="Financial Analyst",
            is_org_admin=False,
        )

        perm, _ = Permission.objects.get_or_create(
            code=PermissionCode.REPORTS_VIEW.value,
            defaults={"name": "View Reports", "category": "Reports"},
        )
        role = Role.objects.create(organization=org, name="Report Viewer")
        RolePermission.objects.create(role=role, permission=perm)
        UserRole.objects.create(user=user, role=role, branch=None)

        client = APIClient()
        client.force_authenticate(user=user)

        # Products & Batches
        cat = Category.objects.create(organization=org, name="Antibiotics")
        prod = Product.objects.create(
            organization=org,
            category=cat,
            sku="AMX-500",
            name="Amoxicillin 500mg",
        )

        # Active Batch (expires in 180 days, cost = 100.00)
        b_active = Batch.objects.create(
            organization=org,
            product=prod,
            batch_number="BAT-ACT-01",
            expiry_date=date.today() + timedelta(days=180),
            purchase_price=Decimal("100.00"),
            received_date=date.today(),
            status="ACTIVE",
        )
        # Expiring soon Batch (expires in 30 days, cost = 80.00)
        b_expiring = Batch.objects.create(
            organization=org,
            product=prod,
            batch_number="BAT-EXP-02",
            expiry_date=date.today() + timedelta(days=30),
            purchase_price=Decimal("80.00"),
            received_date=date.today(),
            status="ACTIVE",
        )
        # Expired Batch (cost = 50.00)
        b_expired = Batch.objects.create(
            organization=org,
            product=prod,
            batch_number="BAT-EXPIRED-03",
            expiry_date=date.today() - timedelta(days=10),
            purchase_price=Decimal("50.00"),
            received_date=date.today() - timedelta(days=400),
            status="EXPIRED",
        )

        # Inventories
        BranchInventory.objects.create(
            organization=org,
            branch=branch,
            batch=b_active,
            quantity=50,
            reorder_level=20,
        )
        BranchInventory.objects.create(
            organization=org,
            branch=branch,
            batch=b_expiring,
            quantity=5,  # Low stock (<= 10)
            reorder_level=10,
        )
        BranchInventory.objects.create(
            organization=org,
            branch=branch,
            batch=b_expired,
            quantity=15,
            reorder_level=5,
        )

        # Completed Sale: 10 units of b_active @ 250.00 = 2500.00
        # Cost = 10 * 100.00 = 1000.00; Profit = 1500.00
        sale = Sale.objects.create(
            organization=org,
            branch=branch,
            user=user,
            device=device,
            receipt_number="CEN-P1-20260925-0001",
            subtotal=Decimal("2500.00"),
            discount_amount=Decimal("0.00"),
            tax_amount=Decimal("0.00"),
            total=Decimal("2500.00"),
            status=SaleStatus.COMPLETED.value,
            sale_date=timezone.now(),
        )
        SaleItem.objects.create(
            sale=sale,
            product=prod,
            batch=b_active,
            quantity=10,
            unit_price=Decimal("250.00"),
            discount_amount=Decimal("0.00"),
            line_total=Decimal("2500.00"),
        )
        Payment.objects.create(
            sale=sale,
            payment_method="CASH",
            amount=Decimal("2500.00"),
        )

        # Expense: 500.00 generator fuel
        exp_cat = ExpenseCategory.objects.create(organization=org, name="Utilities")
        Expense.objects.create(
            organization=org,
            branch=branch,
            expense_category=exp_cat,
            description="Diesel fuel",
            amount=Decimal("500.00"),
            payment_method="CASH",
            expense_date=date.today(),
            created_by=user,
            status=ExpenseStatus.APPROVED.value,
        )

        return {
            'org': org,
            'branch': branch,
            'user': user,
            'client': client,
        }

    def test_sales_report(self, setup_data):
        client = setup_data['client']
        res = client.get('/api/v1/reports/sales/')
        assert res.status_code == status.HTTP_200_OK

        data = res.data
        assert data['total_sales_count'] == 1
        assert Decimal(data['total_revenue']) == Decimal("2500.00")
        assert data['total_items_sold'] == 10
        assert Decimal(data['cost_of_goods_sold']) == Decimal("1000.00")
        assert Decimal(data['gross_profit']) == Decimal("1500.00")

        payments = data['payment_breakdown']
        assert len(payments) == 1
        assert payments[0]['method'] == "CASH"
        assert Decimal(payments[0]['total']) == Decimal("2500.00")

    def test_inventory_report(self, setup_data):
        client = setup_data['client']
        res = client.get('/api/v1/reports/inventory/')
        assert res.status_code == status.HTTP_200_OK

        data = res.data
        # Total units: 50 + 5 + 15 = 70
        assert data['total_units_in_stock'] == 70
        assert data['total_batches_in_stock'] == 3

        # Cost valuation: (50 * 100) + (5 * 80) + (15 * 50) = 5000 + 400 + 750 = 6150.00
        assert Decimal(data['total_cost_valuation']) == Decimal("6150.00")

        # Low stock: b_expiring has quantity=5, reorder_level=10
        assert data['low_stock_count'] >= 1

        # Expiry counts
        assert data['expired_batches_count'] == 1
        assert data['expiring_soon_batches_count'] == 1

    def test_expense_report(self, setup_data):
        client = setup_data['client']
        res = client.get('/api/v1/reports/expenses/')
        assert res.status_code == status.HTTP_200_OK

        data = res.data
        assert Decimal(data['total_expenses']) == Decimal("500.00")
        assert data['total_count'] == 1
        assert len(data['category_breakdown']) == 1
        assert data['category_breakdown'][0]['category'] == "Utilities"

    def test_profit_loss_report(self, setup_data):
        client = setup_data['client']
        res = client.get('/api/v1/reports/profit-loss/')
        assert res.status_code == status.HTTP_200_OK

        data = res.data
        # Revenue: 2500.00
        assert Decimal(data['revenue']) == Decimal("2500.00")
        # COGS: 1000.00
        assert Decimal(data['cost_of_goods_sold']) == Decimal("1000.00")
        # Gross Profit: 1500.00
        assert Decimal(data['gross_profit']) == Decimal("1500.00")
        # Operating Expenses: 500.00
        assert Decimal(data['operating_expenses']) == Decimal("500.00")
        # Net Profit: 1500.00 - 500.00 = 1000.00
        assert Decimal(data['net_profit']) == Decimal("1000.00")

    def test_cashier_shift_report(self, setup_data):
        client = setup_data['client']
        today_str = date.today().isoformat()
        res = client.get(f'/api/v1/reports/shifts/?date={today_str}')
        assert res.status_code == status.HTTP_200_OK

        data = res.data
        shifts = data['shifts']
        assert len(shifts) == 1
        shift = shifts[0]
        assert shift['username'] == "analyst"
        assert shift['sales_count'] == 1
        assert Decimal(shift['total_collected']) == Decimal("2500.00")
        assert shift['payments']['CASH'] == "2500.00"

    def test_reports_tenant_isolation(self, setup_data):
        # Create other organization
        other_org = Organization.objects.create(name="Other Org", code="OTH")
        other_user = User.objects.create_user(
            username="other_analyst",
            organization_id=other_org.id,
            password="password123",
        )
        perm, _ = Permission.objects.get_or_create(
            code=PermissionCode.REPORTS_VIEW.value,
            defaults={"name": "View Reports", "category": "Reports"},
        )
        role = Role.objects.create(organization=other_org, name="Other Viewer")
        RolePermission.objects.create(role=role, permission=perm)
        UserRole.objects.create(user=other_user, role=role, branch=None)

        other_client = APIClient()
        other_client.force_authenticate(user=other_user)

        # Other org has zero sales, inventory, or expenses
        res = other_client.get('/api/v1/reports/sales/')
        assert res.status_code == status.HTTP_200_OK
        assert res.data['total_sales_count'] == 0
        assert Decimal(res.data['total_revenue']) == Decimal("0.00")
