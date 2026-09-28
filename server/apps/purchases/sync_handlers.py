import uuid
from decimal import Decimal
from django.utils import timezone
from apps.sync.services import register_sync_handler, _parse_d
from apps.users.models import User
from shared.enums import PaymentStatus, ReceivingStatus
from .models import Purchase, PurchaseItem, PurchasePayment


def handle_purchase_sync(
    *, organization, branch_id, device_id, request_user, entity_id, operation, payload, event
) -> dict:
    user_obj = request_user
    if payload.get('user_id'):
        u = User.objects.filter(id=payload['user_id'], organization=organization).first()
        if u:
            user_obj = u

    p_branch_id = uuid.UUID(str(payload.get('branch_id') or branch_id))
    p_supplier_id = uuid.UUID(str(payload['supplier_id']))
    p_date = _parse_d(payload.get('purchase_date')) or timezone.now().date()

    Purchase.objects.update_or_create(
        id=entity_id,
        organization=organization,
        defaults={
            'branch_id': p_branch_id,
            'supplier_id': p_supplier_id,
            'user': user_obj,
            'purchase_reference': payload['purchase_reference'],
            'invoice_number': payload.get('invoice_number'),
            'purchase_date': p_date,
            'subtotal': Decimal(str(payload.get('subtotal', '0.00'))),
            'discount_amount': Decimal(str(payload.get('discount_amount', '0.00'))),
            'total': Decimal(str(payload.get('total', '0.00'))),
            'payment_status': payload.get('payment_status', PaymentStatus.UNPAID.value),
            'receiving_status': payload.get('receiving_status', ReceivingStatus.PENDING.value),
            'notes': payload.get('notes', ''),
        },
    )
    return payload


def handle_purchase_item_sync(
    *, organization, branch_id, device_id, request_user, entity_id, operation, payload, event
) -> dict:
    batch_id = uuid.UUID(str(payload['batch_id'])) if payload.get('batch_id') else None
    PurchaseItem.objects.update_or_create(
        id=entity_id,
        defaults={
            'purchase_id': uuid.UUID(str(payload['purchase_id'])),
            'product_id': uuid.UUID(str(payload['product_id'])),
            'batch_id': batch_id,
            'quantity_ordered': int(payload.get('quantity_ordered', 0)),
            'quantity_received': int(payload.get('quantity_received', 0)),
            'purchase_price': Decimal(str(payload.get('purchase_price', '0.00'))),
            'selling_price': Decimal(str(payload.get('selling_price', '0.00'))),
            'discount': Decimal(str(payload.get('discount', '0.00'))),
            'line_total': Decimal(str(payload.get('line_total', '0.00'))),
        },
    )
    return payload


def handle_purchase_payment_sync(
    *, organization, branch_id, device_id, request_user, entity_id, operation, payload, event
) -> dict:
    if not PurchasePayment.objects.filter(id=entity_id).exists():
        PurchasePayment.objects.create(
            id=entity_id,
            purchase_id=uuid.UUID(str(payload['purchase_id'])),
            payment_method=payload['payment_method'],
            amount=Decimal(str(payload['amount'])),
            reference=payload.get('reference'),
            payment_date=_parse_d(payload.get('payment_date')) or timezone.now().date(),
        )
    return payload


register_sync_handler('purchase', handle_purchase_sync)
register_sync_handler('purchase_item', handle_purchase_item_sync)
register_sync_handler('purchase_payment', handle_purchase_payment_sync)
