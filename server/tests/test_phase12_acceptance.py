import uuid
from datetime import date
from decimal import Decimal
import pytest
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.branches.models import Branch, Device
from apps.organizations.models import Organization
from apps.expenses.models import ExpenseCategory, Expense
from apps.users.models import User
from shared.enums import ExpenseStatus, SyncOperation


@pytest.mark.django_db
class TestPhase12ServerExpensesAcceptance:
    @pytest.fixture
    def setup_data(self):
        org = Organization.objects.create(name="Expense Org", code="EORG")
        branch = Branch.objects.create(organization=org, name="Central Branch", code="CBR")

        user = User.objects.create_user(
            username="expenseadmin",
            organization_id=org.id,
            password="adminpassword123",
            full_name="Expense Admin",
            is_org_admin=True,
        )

        client = APIClient()
        client.force_authenticate(user=user)

        return {
            'org': org,
            'branch': branch,
            'user': user,
            'client': client,
        }

    def test_expense_category_crud_and_expense_lifecycle(self, setup_data):
        client = setup_data['client']
        branch = setup_data['branch']
        user = setup_data['user']

        # 1. Create Expense Category
        cat_resp = client.post("/api/v1/expense-categories/", {
            "name": "Generator Fuel & Maintenance",
            "description": "Diesel purchases and generator servicing",
        }, format="json")
        assert cat_resp.status_code == status.HTTP_201_CREATED, cat_resp.data
        cat_id = cat_resp.data['id']
        assert cat_resp.data['name'] == "Generator Fuel & Maintenance"

        # 2. Create Expense
        exp_resp = client.post("/api/v1/expenses/", {
            "branch": str(branch.id),
            "expense_category": str(cat_id),
            "description": "50L Diesel purchase for generator",
            "amount": "45000.00",
            "payment_method": "CASH",
            "expense_date": date.today().isoformat(),
        }, format="json")
        assert exp_resp.status_code == status.HTTP_201_CREATED, exp_resp.data
        exp_id = exp_resp.data['id']
        assert exp_resp.data['status'] == ExpenseStatus.PENDING_APPROVAL.value
        assert exp_resp.data['amount'] == "45000.00"
        assert str(exp_resp.data['created_by']) == str(user.id)

        # 3. Approve Expense
        appr_resp = client.post(f"/api/v1/expenses/{exp_id}/approve/")
        assert appr_resp.status_code == status.HTTP_200_OK, appr_resp.data
        assert appr_resp.data['status'] == ExpenseStatus.APPROVED.value
        assert str(appr_resp.data['approved_by']) == str(user.id)

        # Verify in database
        exp = Expense.objects.get(id=exp_id)
        assert exp.status == ExpenseStatus.APPROVED.value
        assert exp.approved_by == user

        # 4. Reject workflow on another expense
        exp2_resp = client.post("/api/v1/expenses/", {
            "branch": str(branch.id),
            "expense_category": str(cat_id),
            "description": "Unapproved luxury stationery",
            "amount": "12000.00",
            "payment_method": "TRANSFER",
            "expense_date": date.today().isoformat(),
        }, format="json")
        assert exp2_resp.status_code == status.HTTP_201_CREATED
        exp2_id = exp2_resp.data['id']

        rej_resp = client.post(f"/api/v1/expenses/{exp2_id}/reject/")
        assert rej_resp.status_code == status.HTTP_200_OK
        assert rej_resp.data['status'] == ExpenseStatus.REJECTED.value

        exp2 = Expense.objects.get(id=exp2_id)
        assert exp2.status == ExpenseStatus.REJECTED.value

    def test_sync_upload_expense_and_category(self, setup_data):
        client = setup_data['client']
        org = setup_data['org']
        branch = setup_data['branch']
        user = setup_data['user']

        device = Device.objects.create(
            organization=org,
            branch=branch,
            name="Office PC",
            code="OP01",
            device_identifier="DEV-EXP-01",
        )

        cat_id = uuid.uuid4()
        exp_id = uuid.uuid4()
        now_str = timezone.now().isoformat()

        events = [
            {
                "id": str(uuid.uuid4()),
                "entity_type": "expense_category",
                "entity_id": str(cat_id),
                "operation": SyncOperation.CREATE.value,
                "dependency_level": 2,
                "schema_version": 1,
                "local_created_at": now_str,
                "payload": {
                    "id": str(cat_id),
                    "name": "Cleaning Supplies",
                    "description": "Detergents and disinfectant",
                    "is_active": True,
                },
            },
            {
                "id": str(uuid.uuid4()),
                "entity_type": "expense",
                "entity_id": str(exp_id),
                "operation": SyncOperation.CREATE.value,
                "dependency_level": 4,
                "schema_version": 1,
                "local_created_at": now_str,
                "payload": {
                    "id": str(exp_id),
                    "branch_id": str(branch.id),
                    "expense_category_id": str(cat_id),
                    "description": "Floor bleach and mops",
                    "amount": "8500.00",
                    "payment_method": "CASH",
                    "expense_date": date.today().isoformat(),
                    "created_by_id": str(user.id),
                    "status": ExpenseStatus.APPROVED.value,
                },
            },
        ]

        resp = client.post(
            "/api/v1/sync/upload/",
            {
                "device_id": str(device.id),
                "branch_id": str(branch.id),
                "events": events,
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK, resp.data
        statuses = [r["status"] for r in resp.data["results"]]
        assert statuses == ["PROCESSED", "PROCESSED"]

        # Verify in database
        cat = ExpenseCategory.objects.filter(id=cat_id).first()
        assert cat is not None
        assert cat.name == "Cleaning Supplies"

        exp = Expense.objects.filter(id=exp_id).first()
        assert exp is not None
        assert exp.amount == Decimal("8500.00")
        assert exp.status == ExpenseStatus.APPROVED.value
