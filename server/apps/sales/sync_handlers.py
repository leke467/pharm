import uuid
from decimal import Decimal
from django.utils import timezone
from apps.sync.services import register_sync_handler, _parse_dt
from apps.users.models import User
from .models import Sale, SaleItem, Payment, Receipt, SaleReturn, SaleReturnItem


def handle_sale_sync(
    *, organization, branch_id, device_id, request_user, entity_id, operation, payload, event
) -> dict:
    user_obj = request_user
    if payload.get('user_id'):
        u = User.objects.filter(id=payload['user_id'], organization=organization).first()
        if u:
            user_obj = u

    existing_sale = Sale.objects.filter(id=entity_id, organization=organization).first()
    if existing_sale and operation == 'UPDATE':
        if 'status' in payload:
            existing_sale.status = payload['status']
        if 'notes' in payload and payload['notes']:
            existing_sale.notes = payload['notes']
        existing_sale.sync_status = 'SYNCED'
        existing_sale.save()
        return payload

    sale_branch_id = uuid.UUID(str(payload.get('branch_id') or branch_id))
    sale_device_id = uuid.UUID(str(payload.get('device_id') or device_id))
    now = timezone.now()

    Sale.objects.update_or_create(
        id=entity_id,
        organization=organization,
        defaults={
            'branch_id': sale_branch_id,
            'user': user_obj,
            'device_id': sale_device_id,
            'receipt_number': payload['receipt_number'],
            'customer_name': payload.get('customer_name'),
            'customer_phone': payload.get('customer_phone'),
            'subtotal': Decimal(str(payload.get('subtotal', '0.00'))),
            'discount_amount': Decimal(str(payload.get('discount_amount', '0.00'))),
            'tax_amount': Decimal(str(payload.get('tax_amount', '0.00'))),
            'total': Decimal(str(payload.get('total', '0.00'))),
            'status': payload.get('status', 'COMPLETED'),
            'sale_date': _parse_dt(payload.get('sale_date') or event.get('local_created_at')),
            'server_received_at': now,
            'is_offline': bool(payload.get('is_offline', True)),
            'sync_status': 'SYNCED',
            'notes': payload.get('notes', ''),
        },
    )
    payload['server_received_at'] = now.isoformat()
    payload['sync_status'] = 'SYNCED'
    return payload


def handle_sale_item_sync(
    *, organization, branch_id, device_id, request_user, entity_id, operation, payload, event
) -> dict:
    if not SaleItem.objects.filter(id=entity_id).exists():
        SaleItem.objects.create(
            id=entity_id,
            sale_id=uuid.UUID(str(payload['sale_id'])),
            product_id=uuid.UUID(str(payload['product_id'])),
            batch_id=uuid.UUID(str(payload['batch_id'])),
            quantity=int(payload['quantity']),
            unit_price=Decimal(str(payload['unit_price'])),
            discount_amount=Decimal(str(payload.get('discount_amount', '0.00'))),
            line_total=Decimal(str(payload['line_total'])),
        )
    return payload


def handle_payment_sync(
    *, organization, branch_id, device_id, request_user, entity_id, operation, payload, event
) -> dict:
    if not Payment.objects.filter(id=entity_id).exists():
        Payment.objects.create(
            id=entity_id,
            sale_id=uuid.UUID(str(payload['sale_id'])),
            payment_method=payload['payment_method'],
            amount=Decimal(str(payload['amount'])),
            reference=payload.get('reference'),
        )
    return payload


def handle_receipt_sync(
    *, organization, branch_id, device_id, request_user, entity_id, operation, payload, event
) -> dict:
    Receipt.objects.update_or_create(
        id=entity_id,
        defaults={
            'sale_id': uuid.UUID(str(payload['sale_id'])),
            'receipt_number': payload['receipt_number'],
            'printed_at': _parse_dt(payload.get('printed_at') or event.get('local_created_at')),
            'printer_name': payload.get('printer_name'),
            'reprint_count': int(payload.get('reprint_count', 0)),
        },
    )
    return payload


def handle_sale_return_sync(
    *, organization, branch_id, device_id, request_user, entity_id, operation, payload, event
) -> dict:
    user_obj = request_user
    if payload.get('user_id'):
        u = User.objects.filter(id=payload['user_id'], organization=organization).first()
        if u:
            user_obj = u

    SaleReturn.objects.update_or_create(
        id=entity_id,
        organization=organization,
        defaults={
            'original_sale_id': uuid.UUID(str(payload['original_sale_id'])),
            'branch_id': uuid.UUID(str(payload.get('branch_id') or branch_id)),
            'user': user_obj,
            'device_id': uuid.UUID(str(payload.get('device_id') or device_id)),
            'return_date': _parse_dt(payload.get('return_date') or event.get('local_created_at')),
            'reason': payload.get('reason', 'Customer return'),
            'refund_amount': Decimal(str(payload.get('refund_amount', '0.00'))),
            'status': payload.get('status', 'COMPLETED'),
        },
    )
    return payload


def handle_sale_return_item_sync(
    *, organization, branch_id, device_id, request_user, entity_id, operation, payload, event
) -> dict:
    if not SaleReturnItem.objects.filter(id=entity_id).exists():
        sale_item_id = uuid.UUID(str(payload['sale_item_id']))
        sale_item = SaleItem.objects.filter(id=sale_item_id).first()
        prod_id = (
            uuid.UUID(str(payload['product_id']))
            if payload.get('product_id')
            else (sale_item.product_id if sale_item else None)
        )
        qty = int(payload['quantity'])
        line_tot = Decimal(
            str(payload.get('line_total') or payload.get('refund_amount') or '0.00')
        )
        u_price = (
            Decimal(str(payload['unit_price']))
            if payload.get('unit_price')
            else (
                sale_item.unit_price
                if sale_item
                else (line_tot / Decimal(qty) if qty else Decimal('0.00'))
            )
        )
        SaleReturnItem.objects.create(
            id=entity_id,
            sale_return_id=uuid.UUID(str(payload['sale_return_id'])),
            sale_item_id=sale_item_id,
            product_id=prod_id,
            batch_id=uuid.UUID(str(payload['batch_id'])),
            quantity=qty,
            unit_price=u_price,
            line_total=line_tot,
        )
    return payload


register_sync_handler('sale', handle_sale_sync)
register_sync_handler('sale_item', handle_sale_item_sync)
register_sync_handler('payment', handle_payment_sync)
register_sync_handler('receipt', handle_receipt_sync)
register_sync_handler('sale_return', handle_sale_return_sync)
register_sync_handler('sale_return_item', handle_sale_return_item_sync)
