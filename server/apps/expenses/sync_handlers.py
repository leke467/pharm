import uuid
from decimal import Decimal
from django.utils import timezone
from apps.sync.services import register_sync_handler, _parse_dt, _parse_d
from apps.expenses.models import ExpenseCategory, Expense
from apps.branches.models import Branch
from apps.users.models import User
from shared.enums import ExpenseStatus


def handle_expense_category_sync(
    *, organization, branch_id, device_id, request_user, entity_id, operation, payload, event
) -> dict:
    cat_id = uuid.UUID(str(entity_id))
    ExpenseCategory.objects.update_or_create(
        id=cat_id,
        organization=organization,
        defaults={
            'name': payload['name'],
            'description': payload.get('description', ''),
            'is_active': payload.get('is_active', True),
        },
    )
    return payload


def handle_expense_sync(
    *, organization, branch_id, device_id, request_user, entity_id, operation, payload, event
) -> dict:
    exp_id = uuid.UUID(str(entity_id))
    b_id = uuid.UUID(str(payload['branch_id']))
    cat_id = uuid.UUID(str(payload['expense_category_id']))

    branch = Branch.objects.filter(id=b_id, organization=organization).first()
    category = ExpenseCategory.objects.filter(id=cat_id, organization=organization).first()
    if not branch or not category:
        raise ValueError(f"Branch {b_id} or ExpenseCategory {cat_id} not found in org {organization.id}")

    c_user_id = payload.get('created_by_id') or str(request_user.id)
    c_user = User.objects.filter(id=uuid.UUID(str(c_user_id))).first() or request_user

    a_user_id = payload.get('approved_by_id')
    a_user = User.objects.filter(id=uuid.UUID(str(a_user_id))).first() if a_user_id else None

    e_date = _parse_d(payload.get('expense_date')) or timezone.now().date()

    Expense.objects.update_or_create(
        id=exp_id,
        organization=organization,
        defaults={
            'branch': branch,
            'expense_category': category,
            'description': payload.get('description', ''),
            'amount': Decimal(str(payload['amount'])),
            'payment_method': payload.get('payment_method', 'CASH'),
            'expense_date': e_date,
            'created_by': c_user,
            'approved_by': a_user,
            'status': payload.get('status', ExpenseStatus.PENDING_APPROVAL.value),
            'attachment_path': payload.get('attachment_path'),
            'notes': payload.get('notes', ''),
        },
    )
    return payload


register_sync_handler('expense_category', handle_expense_category_sync)
register_sync_handler('expense', handle_expense_sync)
