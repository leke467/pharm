import uuid
from apps.sync.services import register_sync_handler, _parse_dt
from apps.transfers.models import StockTransfer, StockTransferItem
from apps.branches.models import Branch
from apps.products.models import Product
from apps.inventory.models import Batch
from apps.users.models import User
from shared.enums import TransferStatus


def handle_stock_transfer_sync(
    *, organization, branch_id, device_id, request_user, entity_id, operation, payload, event
) -> dict:
    t_id = uuid.UUID(str(entity_id))
    src_b_id = uuid.UUID(str(payload['source_branch_id']))
    dst_b_id = uuid.UUID(str(payload['destination_branch_id']))

    source_b = Branch.objects.filter(id=src_b_id, organization=organization).first()
    dest_b = Branch.objects.filter(id=dst_b_id, organization=organization).first()
    if not source_b or not dest_b:
        raise ValueError(f"Branches {src_b_id} or {dst_b_id} not found in org {organization.id}")

    req_user_id = payload.get('requested_by_id') or str(request_user.id)
    req_user = User.objects.filter(id=uuid.UUID(str(req_user_id))).first() or request_user

    app_user_id = payload.get('approved_by_id')
    app_user = User.objects.filter(id=uuid.UUID(str(app_user_id))).first() if app_user_id else None

    disp_user_id = payload.get('dispatched_by_id')
    disp_user = User.objects.filter(id=uuid.UUID(str(disp_user_id))).first() if disp_user_id else None

    rec_user_id = payload.get('received_by_id')
    rec_user = User.objects.filter(id=uuid.UUID(str(rec_user_id))).first() if rec_user_id else None

    status_val = payload.get('status', TransferStatus.REQUESTED.value)

    transfer = StockTransfer.objects.filter(id=t_id, organization=organization).first()
    if not transfer:
        transfer = StockTransfer.objects.create(
            id=t_id,
            organization=organization,
            source_branch=source_b,
            destination_branch=dest_b,
            status=status_val,
            requested_by=req_user,
            approved_by=app_user,
            dispatched_by=disp_user,
            received_by=rec_user,
            requested_at=_parse_dt(payload.get('requested_at')),
            approved_at=_parse_dt(payload.get('approved_at')) if payload.get('approved_at') else None,
            dispatched_at=_parse_dt(payload.get('dispatched_at')) if payload.get('dispatched_at') else None,
            received_at=_parse_dt(payload.get('received_at')) if payload.get('received_at') else None,
            notes=payload.get('notes', ''),
        )
    else:
        transfer.status = status_val
        if app_user:
            transfer.approved_by = app_user
            transfer.approved_at = _parse_dt(payload.get('approved_at'))
        if disp_user:
            transfer.dispatched_by = disp_user
            transfer.dispatched_at = _parse_dt(payload.get('dispatched_at'))
        if rec_user:
            transfer.received_by = rec_user
            transfer.received_at = _parse_dt(payload.get('received_at'))
        transfer.notes = payload.get('notes', transfer.notes)
        transfer.save()

    return payload


def handle_stock_transfer_item_sync(
    *, organization, branch_id, device_id, request_user, entity_id, operation, payload, event
) -> dict:
    item_id = uuid.UUID(str(entity_id))
    t_id = uuid.UUID(str(payload['stock_transfer_id']))
    prod_id = uuid.UUID(str(payload['product_id']))
    batch_id = uuid.UUID(str(payload['batch_id']))

    transfer = StockTransfer.objects.filter(id=t_id, organization=organization).first()
    if not transfer:
        raise ValueError(f"StockTransfer {t_id} not found for item {item_id}")

    product = Product.objects.filter(id=prod_id, organization=organization).first()
    batch = Batch.objects.filter(id=batch_id, organization=organization).first()
    if not product or not batch:
        raise ValueError(f"Product {prod_id} or Batch {batch_id} not found")

    qty = int(payload.get('quantity', 0))

    item = StockTransferItem.objects.filter(id=item_id).first()
    if not item:
        StockTransferItem.objects.create(
            id=item_id,
            stock_transfer=transfer,
            product=product,
            batch=batch,
            quantity=qty,
        )
    else:
        item.quantity = qty
        item.save()

    return payload


register_sync_handler('stock_transfer', handle_stock_transfer_sync)
register_sync_handler('stock_transfer_item', handle_stock_transfer_item_sync)
