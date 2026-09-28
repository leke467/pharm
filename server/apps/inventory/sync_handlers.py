import uuid
from django.utils import timezone
from apps.sync.services import register_sync_handler, _parse_dt
from apps.users.models import User
from .models import StockCount, StockCountItem


def handle_stock_count_sync(
    *, organization, branch_id, device_id, request_user, entity_id, operation, payload, event
) -> dict:
    user_obj = request_user
    if payload.get('started_by_id') or payload.get('user_id'):
        u_id = payload.get('started_by_id') or payload.get('user_id')
        u = User.objects.filter(id=u_id, organization=organization).first()
        if u:
            user_obj = u

    sc_branch_id = uuid.UUID(str(payload.get('branch_id') or branch_id))
    raw_device_id = payload.get('device_id') or device_id
    sc_device_id = None
    if raw_device_id:
        from apps.branches.models import Device
        d_uuid = uuid.UUID(str(raw_device_id))
        if Device.objects.filter(id=d_uuid).exists():
            sc_device_id = d_uuid
    loc_id = uuid.UUID(str(payload['storage_location_id'])) if payload.get('storage_location_id') else None
    started_at = _parse_dt(payload.get('started_at') or event.get('local_created_at'))

    # Multi-device conflict detection (Architecture Plan §9.3):
    # Detect if another count from a different device overlapped in scope
    existing_other_device = StockCount.objects.filter(
        organization=organization,
        branch_id=sc_branch_id,
        storage_location_id=loc_id,
        status__in=['IN_PROGRESS', 'SUBMITTED', 'APPROVED', 'PARTIALLY_APPROVED'],
    ).exclude(id=entity_id)

    status_val = payload.get('status', 'IN_PROGRESS')
    notes_val = payload.get('notes', '')

    if sc_device_id and existing_other_device.exclude(device_id=sc_device_id).exists():
        status_val = 'CONFLICT'
        notes_val = f"CONFLICT: Overlapping multi-device stock count detected with existing count. {notes_val}".strip()

    StockCount.objects.update_or_create(
        id=entity_id,
        organization=organization,
        defaults={
            'branch_id': sc_branch_id,
            'device_id': sc_device_id,
            'storage_location_id': loc_id,
            'count_type': payload.get('count_type', 'FULL_BRANCH'),
            'status': status_val,
            'started_by': user_obj,
            'started_at': started_at,
            'submitted_at': _parse_dt(payload['submitted_at']) if payload.get('submitted_at') else None,
            'approved_at': _parse_dt(payload['approved_at']) if payload.get('approved_at') else None,
            'notes': notes_val,
        },
    )
    payload['status'] = status_val
    payload['notes'] = notes_val
    return payload


def handle_stock_count_item_sync(
    *, organization, branch_id, device_id, request_user, entity_id, operation, payload, event
) -> dict:
    loc_id = uuid.UUID(str(payload['storage_location_id'])) if payload.get('storage_location_id') else None
    StockCountItem.objects.update_or_create(
        id=entity_id,
        defaults={
            'stock_count_id': uuid.UUID(str(payload['stock_count_id'])),
            'product_id': uuid.UUID(str(payload['product_id'])),
            'batch_id': uuid.UUID(str(payload['batch_id'])),
            'storage_location_id': loc_id,
            'system_quantity': int(payload.get('system_quantity', 0)),
            'counted_quantity': int(payload.get('counted_quantity', 0)),
            'variance': int(payload.get('variance', 0)),
            'current_quantity_at_approval': int(payload['current_quantity_at_approval']) if payload.get('current_quantity_at_approval') is not None else None,
            'approval_status': payload.get('approval_status', 'PENDING'),
            'rejection_reason': payload.get('rejection_reason', ''),
        },
    )
    return payload


register_sync_handler('stock_count', handle_stock_count_sync)
register_sync_handler('stock_count_item', handle_stock_count_item_sync)
