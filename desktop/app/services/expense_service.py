import json
import uuid
from datetime import datetime, date, timezone
from decimal import Decimal
from desktop.app.db.models import (
    Branch,
    ExpenseCategory,
    Expense,
    AuditEvent,
    SyncEvent,
)
from desktop.app.domain.exceptions import ValidationError
from desktop.app.services.base_service import BaseService
from desktop.app.sync.sync_engine import register_download_handler
from shared.enums import (
    PermissionCode,
    ExpenseStatus,
    AuditAction,
    AuditSource,
    SyncOperation,
    SYNC_DEPENDENCY_LEVELS,
    SYNC_SCHEMA_VERSION,
)


class ExpenseService(BaseService):
    """
    Offline-first Expense & Category Service (Architecture Plan §12).
    """

    def create_category(
        self,
        user_session,
        name: str,
        description: str = "",
    ) -> ExpenseCategory:
        self.require_permission(user_session, PermissionCode.EXPENSES_CREATE.value)
        if not name or not name.strip():
            raise ValidationError("Category name is required.")

        now_utc = datetime.now(timezone.utc).isoformat()
        now_local = datetime.now().astimezone().isoformat()
        cat_id = str(uuid.uuid4())

        with self.transaction() as db:
            existing = db.query(ExpenseCategory).filter_by(
                organization_id=user_session.organization_id,
                name=name.strip(),
            ).first()
            if existing:
                raise ValidationError(f"Expense category '{name}' already exists.")

            cat = ExpenseCategory(
                id=cat_id,
                organization_id=user_session.organization_id,
                name=name.strip(),
                description=description or "",
                is_active=True,
                created_at=now_utc,
                updated_at=now_utc,
            )
            db.add(cat)

            payload = {
                "id": cat_id,
                "organization_id": user_session.organization_id,
                "name": cat.name,
                "description": cat.description,
                "is_active": True,
            }
            db.add(
                SyncEvent(
                    id=str(uuid.uuid4()),
                    branch_id=user_session.branch_id,
                    device_id=user_session.device_id,
                    entity_type="expense_category",
                    entity_id=cat_id,
                    operation=SyncOperation.CREATE.value,
                    payload=json.dumps(payload),
                    correlation_id=cat_id,
                    dependency_level=SYNC_DEPENDENCY_LEVELS.get("category", 2),
                    schema_version=SYNC_SCHEMA_VERSION,
                    local_created_at=now_local,
                )
            )

            db.flush()
            return cat

    def list_categories(self, organization_id: str, active_only: bool = True) -> list[ExpenseCategory]:
        with self.transaction() as db:
            q = db.query(ExpenseCategory).filter_by(organization_id=organization_id)
            if active_only:
                q = q.filter_by(is_active=True)
            return q.order_by(ExpenseCategory.name.asc()).all()

    def record_expense(
        self,
        user_session,
        expense_category_id: str,
        description: str,
        amount: Decimal | float | str,
        payment_method: str = "CASH",
        expense_date: str | None = None,
        notes: str = "",
        attachment_path: str | None = None,
        branch_id: str | None = None,
    ) -> Expense:
        self.require_permission(user_session, PermissionCode.EXPENSES_CREATE.value)
        amt = Decimal(str(amount))
        if amt <= 0:
            raise ValidationError("Expense amount must be greater than zero.")

        b_id = branch_id or user_session.branch_id
        e_date = expense_date or date.today().isoformat()
        now_utc = datetime.now(timezone.utc).isoformat()
        now_local = datetime.now().astimezone().isoformat()
        exp_id = str(uuid.uuid4())

        with self.transaction() as db:
            cat = db.query(ExpenseCategory).filter_by(id=expense_category_id).first()
            if not cat:
                raise ValidationError(f"ExpenseCategory {expense_category_id} not found.")

            expense = Expense(
                id=exp_id,
                organization_id=user_session.organization_id,
                branch_id=b_id,
                expense_category_id=expense_category_id,
                description=description or "",
                amount=amt,
                payment_method=payment_method,
                expense_date=e_date,
                created_by_id=user_session.user_id,
                status=ExpenseStatus.PENDING_APPROVAL.value,
                attachment_path=attachment_path,
                notes=notes or "",
                created_at=now_utc,
                updated_at=now_utc,
            )
            db.add(expense)

            # Audit event
            db.add(
                AuditEvent(
                    id=str(uuid.uuid4()),
                    organization_id=user_session.organization_id,
                    branch_id=b_id,
                    user_id=user_session.user_id,
                    device_id=user_session.device_id,
                    action=AuditAction.EXPENSE_CREATED.value,
                    entity_type="expense",
                    entity_id=exp_id,
                    data_after=json.dumps({
                        "amount": str(amt),
                        "category": cat.name,
                        "description": description,
                    }),
                    local_timestamp=now_local,
                    source=AuditSource.DESKTOP.value,
                    is_offline=user_session.is_offline,
                    created_at=now_utc,
                )
            )

            # Sync event
            payload = {
                "id": exp_id,
                "branch_id": b_id,
                "expense_category_id": expense_category_id,
                "description": description,
                "amount": str(amt),
                "payment_method": payment_method,
                "expense_date": e_date,
                "created_by_id": user_session.user_id,
                "status": expense.status,
                "attachment_path": attachment_path,
                "notes": notes or "",
            }
            db.add(
                SyncEvent(
                    id=str(uuid.uuid4()),
                    branch_id=b_id,
                    device_id=user_session.device_id,
                    entity_type="expense",
                    entity_id=exp_id,
                    operation=SyncOperation.CREATE.value,
                    payload=json.dumps(payload),
                    correlation_id=exp_id,
                    dependency_level=SYNC_DEPENDENCY_LEVELS.get("expense", 4),
                    schema_version=SYNC_SCHEMA_VERSION,
                    local_created_at=now_local,
                )
            )

            db.flush()
            return expense

    def approve_expense(self, user_session, expense_id: str) -> Expense:
        self.require_permission(user_session, PermissionCode.EXPENSES_APPROVE.value)
        now_utc = datetime.now(timezone.utc).isoformat()
        now_local = datetime.now().astimezone().isoformat()

        with self.transaction() as db:
            exp = db.query(Expense).filter_by(id=expense_id).first()
            if not exp:
                raise ValidationError(f"Expense {expense_id} not found.")

            if exp.status not in [ExpenseStatus.DRAFT.value, ExpenseStatus.PENDING_APPROVAL.value]:
                raise ValidationError(f"Expense cannot be approved from status {exp.status}.")

            exp.status = ExpenseStatus.APPROVED.value
            exp.approved_by_id = user_session.user_id
            exp.updated_at = now_utc

            # Audit event
            db.add(
                AuditEvent(
                    id=str(uuid.uuid4()),
                    organization_id=user_session.organization_id,
                    branch_id=exp.branch_id,
                    user_id=user_session.user_id,
                    device_id=user_session.device_id,
                    action=AuditAction.EXPENSE_APPROVED.value,
                    entity_type="expense",
                    entity_id=expense_id,
                    data_after=json.dumps({"status": exp.status, "approved_by_id": user_session.user_id}),
                    local_timestamp=now_local,
                    source=AuditSource.DESKTOP.value,
                    is_offline=user_session.is_offline,
                    created_at=now_utc,
                )
            )

            # Sync event
            db.add(
                SyncEvent(
                    id=str(uuid.uuid4()),
                    branch_id=exp.branch_id,
                    device_id=user_session.device_id,
                    entity_type="expense",
                    entity_id=expense_id,
                    operation=SyncOperation.UPDATE.value,
                    payload=json.dumps({
                        "id": expense_id,
                        "branch_id": exp.branch_id,
                        "status": exp.status,
                        "approved_by_id": user_session.user_id,
                    }),
                    correlation_id=expense_id,
                    dependency_level=SYNC_DEPENDENCY_LEVELS.get("expense", 4),
                    schema_version=SYNC_SCHEMA_VERSION,
                    local_created_at=now_local,
                )
            )

            db.flush()
            return exp

    def reject_expense(self, user_session, expense_id: str) -> Expense:
        self.require_permission(user_session, PermissionCode.EXPENSES_APPROVE.value)
        now_utc = datetime.now(timezone.utc).isoformat()
        now_local = datetime.now().astimezone().isoformat()

        with self.transaction() as db:
            exp = db.query(Expense).filter_by(id=expense_id).first()
            if not exp:
                raise ValidationError(f"Expense {expense_id} not found.")

            if exp.status not in [ExpenseStatus.DRAFT.value, ExpenseStatus.PENDING_APPROVAL.value]:
                raise ValidationError(f"Expense cannot be rejected from status {exp.status}.")

            exp.status = ExpenseStatus.REJECTED.value
            exp.updated_at = now_utc

            # Audit event
            db.add(
                AuditEvent(
                    id=str(uuid.uuid4()),
                    organization_id=user_session.organization_id,
                    branch_id=exp.branch_id,
                    user_id=user_session.user_id,
                    device_id=user_session.device_id,
                    action=AuditAction.EXPENSE_REJECTED.value,
                    entity_type="expense",
                    entity_id=expense_id,
                    data_after=json.dumps({"status": exp.status}),
                    local_timestamp=now_local,
                    source=AuditSource.DESKTOP.value,
                    is_offline=user_session.is_offline,
                    created_at=now_utc,
                )
            )

            # Sync event
            db.add(
                SyncEvent(
                    id=str(uuid.uuid4()),
                    branch_id=exp.branch_id,
                    device_id=user_session.device_id,
                    entity_type="expense",
                    entity_id=expense_id,
                    operation=SyncOperation.UPDATE.value,
                    payload=json.dumps({
                        "id": expense_id,
                        "branch_id": exp.branch_id,
                        "status": exp.status,
                    }),
                    correlation_id=expense_id,
                    dependency_level=SYNC_DEPENDENCY_LEVELS.get("expense", 4),
                    schema_version=SYNC_SCHEMA_VERSION,
                    local_created_at=now_local,
                )
            )

            db.flush()
            return exp

    def list_expenses(self, branch_id: str | None = None, status: str | None = None) -> list[dict]:
        with self.transaction() as db:
            q = db.query(Expense)
            if branch_id:
                q = q.filter_by(branch_id=branch_id)
            if status:
                q = q.filter_by(status=status)
            expenses = q.order_by(Expense.expense_date.desc(), Expense.created_at.desc()).all()
            res = []
            for e in expenses:
                cat = db.query(ExpenseCategory).filter_by(id=e.expense_category_id).first()
                res.append({
                    "id": e.id,
                    "branch_id": e.branch_id,
                    "expense_category_id": e.expense_category_id,
                    "category_name": cat.name if cat else "",
                    "description": e.description,
                    "amount": e.amount,
                    "payment_method": e.payment_method,
                    "expense_date": e.expense_date,
                    "created_by_id": e.created_by_id,
                    "approved_by_id": e.approved_by_id,
                    "status": e.status,
                    "attachment_path": e.attachment_path,
                    "notes": e.notes,
                    "created_at": e.created_at,
                })
            return res

    def get_expense(self, expense_id: str) -> dict | None:
        expenses = self.list_expenses()
        for e in expenses:
            if e["id"] == expense_id:
                return e
        return None


# =============================================================================
# Download Handlers
# =============================================================================

def _download_expense_category(db, organization_id, entity_id, operation, payload, delivery):
    cat = db.query(ExpenseCategory).filter_by(id=entity_id).first()
    if not cat:
        cat = ExpenseCategory(
            id=entity_id,
            organization_id=organization_id,
            name=payload["name"],
            description=payload.get("description", ""),
            is_active=payload.get("is_active", True),
        )
        db.add(cat)
    else:
        cat.name = payload.get("name", cat.name)
        cat.description = payload.get("description", cat.description)
        cat.is_active = payload.get("is_active", cat.is_active)
    db.flush()


def _download_expense(db, organization_id, entity_id, operation, payload, delivery):
    exp = db.query(Expense).filter_by(id=entity_id).first()
    if not exp:
        exp = Expense(
            id=entity_id,
            organization_id=organization_id,
            branch_id=str(payload["branch_id"]),
            expense_category_id=str(payload["expense_category_id"]),
            description=payload.get("description", ""),
            amount=Decimal(str(payload["amount"])),
            payment_method=payload.get("payment_method", "CASH"),
            expense_date=str(payload["expense_date"]),
            created_by_id=str(payload["created_by_id"]),
            approved_by_id=str(payload["approved_by_id"]) if payload.get("approved_by_id") else None,
            status=payload.get("status", ExpenseStatus.PENDING_APPROVAL.value),
            attachment_path=payload.get("attachment_path"),
            notes=payload.get("notes", ""),
        )
        db.add(exp)
    else:
        exp.status = payload.get("status", exp.status)
        if payload.get("approved_by_id"):
            exp.approved_by_id = str(payload["approved_by_id"])
        if payload.get("notes"):
            exp.notes = payload["notes"]
    db.flush()


register_download_handler("expense_category", _download_expense_category)
register_download_handler("expense", _download_expense)
