"""Phase 12 Acceptance Tests — Expenses (Desktop)."""
import json
import uuid
from decimal import Decimal
import pytest
from desktop.app.auth.session import Session
from desktop.app.db.models import (
    Organization,
    Branch,
    Device,
    ExpenseCategory,
    Expense,
    SyncEvent,
    AuditEvent,
    User,
)
from desktop.app.domain.enums import PermissionCode, AuditAction, ExpenseStatus
from desktop.app.domain.exceptions import ValidationError
from desktop.app.services.expense_service import (
    ExpenseService,
    _download_expense_category,
    _download_expense,
)
from desktop.app.utils.date_utils import utc_now
from desktop.app.utils.uuid_utils import generate_uuid


class TestPhase12DesktopExpensesAcceptance:
    """Desktop acceptance tests for Phase 12 Expenses & Categories."""

    def _seed(self, db_manager):
        org_id = generate_uuid()
        branch_id = generate_uuid()
        device_id = generate_uuid()
        user_id = generate_uuid()

        with db_manager.get_session() as db:
            db.add(Organization(id=org_id, name="Medix Pharmacy", code="MDX"))
            db.flush()
            db.add(Branch(id=branch_id, organization_id=org_id, name="Central Branch", code="CEN"))
            db.flush()
            db.add(Device(
                id=device_id,
                organization_id=org_id,
                branch_id=branch_id,
                name="POS 1",
                code="P01",
                device_identifier="DEV-MDX-EXP-01",
            ))
            db.flush()
            db.add(User(
                id=user_id,
                organization_id=org_id,
                username="admin_user",
                full_name="Admin User",
                is_org_admin=True,
            ))
            db.commit()

        session = Session(
            user_id=user_id,
            username="admin_user",
            full_name="Admin User",
            organization_id=org_id,
            organization_name="Medix Pharmacy",
            branch_id=branch_id,
            branch_name="Central Branch",
            device_id=device_id,
            device_code="P01",
            permissions=[
                PermissionCode.EXPENSES_CREATE.value,
                PermissionCode.EXPENSES_APPROVE.value,
            ],
            roles=["Admin"],
            is_offline=True,
            is_org_admin=True,
            access_token=None,
            refresh_token=None,
            logged_in_at=utc_now(),
        )

        return {
            'org_id': org_id,
            'branch_id': branch_id,
            'device_id': device_id,
            'user_id': user_id,
            'session': session,
        }

    def test_expense_category_creation_and_listing(self, db_manager):
        data = self._seed(db_manager)
        service = ExpenseService(db_manager)
        session = data['session']

        cat = service.create_category(
            session,
            name="Utilities",
            description="Electricity, generator fuel, and water",
        )
        assert cat.name == "Utilities"
        assert cat.is_active is True

        # Duplicate name in same org should fail
        with pytest.raises(ValidationError):
            service.create_category(session, name="Utilities")

        # Blank name should fail
        with pytest.raises(ValidationError):
            service.create_category(session, name="   ")

        # Verify listing
        cats = service.list_categories(data['org_id'])
        assert len(cats) == 1
        assert cats[0].name == "Utilities"

        # Verify SyncEvent was queued
        with db_manager.get_session() as db:
            sync = db.query(SyncEvent).filter_by(entity_id=cat.id).first()
            assert sync is not None
            assert sync.entity_type == "expense_category"
            payload = json.loads(sync.payload)
            assert payload["name"] == "Utilities"

    def test_record_expense_lifecycle(self, db_manager):
        data = self._seed(db_manager)
        service = ExpenseService(db_manager)
        session = data['session']

        cat = service.create_category(session, name="Office Supplies")

        # Invalid amount
        with pytest.raises(ValidationError):
            service.record_expense(
                session,
                expense_category_id=cat.id,
                description="Paper reams",
                amount=Decimal("-10.00"),
            )

        # Invalid category
        with pytest.raises(ValidationError):
            service.record_expense(
                session,
                expense_category_id=generate_uuid(),
                description="Test",
                amount=Decimal("100.00"),
            )

        # Record valid expense
        exp = service.record_expense(
            session,
            expense_category_id=cat.id,
            description="Paper reams and printer toner",
            amount=Decimal("15000.00"),
            payment_method="CASH",
            notes="Purchased from local market",
        )
        assert exp.id is not None
        assert exp.status == ExpenseStatus.PENDING_APPROVAL.value
        assert exp.amount == Decimal("15000.00")

        # Check AuditEvent and SyncEvent
        with db_manager.get_session() as db:
            audit = db.query(AuditEvent).filter_by(entity_id=exp.id).first()
            assert audit is not None
            assert audit.action == AuditAction.EXPENSE_CREATED.value

            sync = db.query(SyncEvent).filter_by(entity_id=exp.id).first()
            assert sync is not None
            assert sync.entity_type == "expense"
            payload = json.loads(sync.payload)
            assert payload["amount"] == "15000.00"

        # List expenses
        expenses = service.list_expenses(branch_id=data['branch_id'])
        assert len(expenses) == 1
        assert expenses[0]["category_name"] == "Office Supplies"
        assert expenses[0]["amount"] == Decimal("15000.00")

        # Approve expense
        app_exp = service.approve_expense(session, exp.id)
        assert app_exp.status == ExpenseStatus.APPROVED.value
        assert app_exp.approved_by_id == session.user_id

        # Cannot approve already approved expense
        with pytest.raises(ValidationError):
            service.approve_expense(session, exp.id)

        # Verify audit for approval
        with db_manager.get_session() as db:
            audits = db.query(AuditEvent).filter_by(entity_id=exp.id).all()
            actions = [a.action for a in audits]
            assert AuditAction.EXPENSE_APPROVED.value in actions

    def test_reject_expense(self, db_manager):
        data = self._seed(db_manager)
        service = ExpenseService(db_manager)
        session = data['session']

        cat = service.create_category(session, name="Maintenance")
        exp = service.record_expense(
            session,
            expense_category_id=cat.id,
            description="AC Repair",
            amount=Decimal("50000.00"),
        )
        assert exp.status == ExpenseStatus.PENDING_APPROVAL.value

        rej_exp = service.reject_expense(session, exp.id)
        assert rej_exp.status == ExpenseStatus.REJECTED.value

        # Cannot reject again
        with pytest.raises(ValidationError):
            service.reject_expense(session, exp.id)

    def test_download_handlers_for_expenses(self, db_manager):
        data = self._seed(db_manager)
        org_id = data['org_id']
        branch_id = data['branch_id']
        user_id = data['user_id']

        cat_id = generate_uuid()
        exp_id = generate_uuid()

        cat_payload = {
            "id": cat_id,
            "name": "Security Services",
            "description": "Monthly security bill",
            "is_active": True,
        }
        with db_manager.get_session() as db:
            _download_expense_category(db, org_id, cat_id, "CREATE", cat_payload, None)
            db.commit()

        with db_manager.get_session() as db:
            cat = db.query(ExpenseCategory).filter_by(id=cat_id).first()
            assert cat is not None
            assert cat.name == "Security Services"

        exp_payload = {
            "id": exp_id,
            "branch_id": branch_id,
            "expense_category_id": cat_id,
            "description": "Night guard fee",
            "amount": "25000.00",
            "payment_method": "BANK_TRANSFER",
            "expense_date": "2026-09-25",
            "created_by_id": user_id,
            "status": "APPROVED",
            "notes": "Approved by manager",
        }
        with db_manager.get_session() as db:
            _download_expense(db, org_id, exp_id, "CREATE", exp_payload, None)
            db.commit()

        with db_manager.get_session() as db:
            exp = db.query(Expense).filter_by(id=exp_id).first()
            assert exp is not None
            assert exp.description == "Night guard fee"
            assert exp.amount == Decimal("25000.00")
            assert exp.status == "APPROVED"
