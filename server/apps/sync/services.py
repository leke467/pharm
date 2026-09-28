import uuid
from collections import OrderedDict
from datetime import date, datetime, timedelta
from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime, parse_date

from apps.audit.models import AuditEvent
from apps.branches.models import Branch, Device
from apps.inventory.models import (
    Batch,
    StorageLocation,
    BranchInventory,
    InventoryMovement,
)
from apps.inventory.views import apply_inventory_movement
from apps.organizations.models import Organization
from apps.pricing.models import Price, PriceHistory
from apps.products.models import (
    Category,
    ProductType,
    Manufacturer,
    Supplier,
    Product,
    ProductBranch,
)
from apps.users.models import User, Role, Permission, RolePermission, UserRole
from shared.enums import (
    AuditAction,
    AuditSource,
    BatchStatus,
    SyncTargetScope,
    SYNC_DEPENDENCY_LEVELS,
)
from .models import SyncDelivery, ProcessedEvent


# Registry allowing later phases (Sales, Returns, Purchases, Stock Counts, Transfers, Expenses)
# to register custom entity sync handlers without modifying the core sync loop.
CUSTOM_SYNC_HANDLERS = {}


def register_sync_handler(entity_type: str, handler_fn):
    CUSTOM_SYNC_HANDLERS[entity_type] = handler_fn


def _parse_dt(val):
    if not val:
        return timezone.now()
    if isinstance(val, datetime):
        return val
    dt = parse_datetime(str(val))
    if dt is None:
        try:
            dt = datetime.fromisoformat(str(val).replace('Z', '+00:00'))
        except Exception:
            dt = timezone.now()
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone.utc)
    return dt


def _parse_d(val):
    if not val:
        return None
    if isinstance(val, date) and not isinstance(val, datetime):
        return val
    d = parse_date(str(val)[:10])
    return d


def determine_target_scope(entity_type: str, payload: dict) -> tuple[str, uuid.UUID | None]:
    """
    Determines whether a SyncDelivery is broadcast to ALL_BRANCHES or SPECIFIC_BRANCH.
    """
    org_wide_types = {
        'organization',
        'branch',
        'device',
        'user',
        'role',
        'permission',
        'role_permission',
        'user_role',
        'category',
        'product_type',
        'manufacturer',
        'supplier',
        'product',
        'product_branch',
        'batch',
        'price',
        'price_history',
        'stock_transfer',
        'stock_transfer_item',
    }
    if entity_type in org_wide_types:
        return SyncTargetScope.ALL_BRANCHES.value, None

    b_id = payload.get('branch_id') or payload.get('branch')
    if b_id:
        return SyncTargetScope.SPECIFIC_BRANCH.value, uuid.UUID(str(b_id))
    return SyncTargetScope.ALL_BRANCHES.value, None


def apply_single_sync_event(
    *,
    organization: Organization,
    branch_id: uuid.UUID,
    device_id: uuid.UUID,
    request_user: User,
    event: dict,
) -> dict:
    """
    Applies a single sync event to the authoritative PostgreSQL/Django database.
    Returns the canonical payload dict to store in SyncDelivery.
    """
    entity_type = event['entity_type']
    entity_id = uuid.UUID(str(event['entity_id']))
    operation = event['operation']
    payload = dict(event.get('payload') or {})
    org_id = organization.id

    # Check if a later phase registered a custom handler
    if entity_type in CUSTOM_SYNC_HANDLERS:
        return CUSTOM_SYNC_HANDLERS[entity_type](
            organization=organization,
            branch_id=branch_id,
            device_id=device_id,
            request_user=request_user,
            entity_id=entity_id,
            operation=operation,
            payload=payload,
            event=event,
        )

    if entity_type == 'organization':
        if payload.get('name'):
            organization.name = payload['name']
        if payload.get('address') is not None:
            organization.address = payload['address']
        if payload.get('phone') is not None:
            organization.phone = payload['phone']
        if payload.get('email') is not None:
            organization.email = payload['email']
        if isinstance(payload.get('settings'), dict):
            merged = dict(organization.settings or {})
            merged.update(payload['settings'])
            organization.settings = merged
        organization.save()
        return payload

    elif entity_type == 'branch':
        defaults = {
            'organization_id': org_id,
            'name': payload.get('name', 'Branch'),
            'code': payload.get('code', f'B-{str(entity_id)[:4]}'),
        }
        for field in ('address', 'phone', 'email', 'uses_storage_locations', 'initial_stock_loaded', 'is_active'):
            if field in payload and payload[field] is not None:
                defaults[field] = payload[field]
        if isinstance(payload.get('settings'), dict):
            defaults['settings'] = payload['settings']

        branch_obj = Branch.objects.filter(id=entity_id, organization_id=org_id).first()
        if branch_obj:
            for k, v in defaults.items():
                if k != 'organization_id':
                    setattr(branch_obj, k, v)
            branch_obj.save()
        else:
            Branch.objects.create(id=entity_id, **defaults)
        return payload

    elif entity_type == 'device':
        br_id = payload.get('branch_id') or payload.get('branch') or branch_id
        Device.objects.update_or_create(
            id=entity_id,
            organization_id=org_id,
            defaults={
                'branch_id': br_id,
                'name': payload.get('name', 'Terminal'),
                'code': payload.get('code', str(entity_id)[:5].upper()),
                'device_identifier': payload.get('device_identifier') or f"DEV-{str(entity_id)[:8]}",
                'is_active': payload.get('is_active', True),
            },
        )
        return payload

    elif entity_type == 'user':
        user_obj = User.objects.filter(id=entity_id, organization_id=org_id).first()
        if not user_obj and payload.get('username'):
            user_obj = User.objects.filter(organization_id=org_id, username=payload['username']).first()
        if user_obj:
            for field in ('full_name', 'email', 'phone', 'is_org_admin', 'is_active'):
                if field in payload and payload[field] is not None:
                    setattr(user_obj, field, payload[field])
            if 'default_branch_id' in payload:
                user_obj.default_branch_id = payload['default_branch_id']
            user_obj.save()
        elif payload.get('username'):
            User.objects.create(
                id=entity_id,
                organization_id=org_id,
                username=payload['username'],
                full_name=payload.get('full_name', payload['username']),
                email=payload.get('email', ''),
                phone=payload.get('phone', ''),
                is_org_admin=bool(payload.get('is_org_admin', False)),
                default_branch_id=payload.get('default_branch_id'),
                is_active=bool(payload.get('is_active', True)),
            )
        return payload

    elif entity_type == 'role':
        role_obj, _ = Role.objects.update_or_create(
            id=entity_id,
            organization_id=org_id,
            defaults={
                'name': payload.get('name', 'Role'),
                'description': payload.get('description', ''),
                'is_system': bool(payload.get('is_system', False)),
                'is_active': bool(payload.get('is_active', True)),
            },
        )
        perm_codes = payload.get('permission_codes')
        if isinstance(perm_codes, list):
            RolePermission.objects.filter(role=role_obj).delete()
            for code in dict.fromkeys(perm_codes):
                perm, _ = Permission.objects.get_or_create(
                    code=code,
                    defaults={
                        'name': code.replace('.', ' - ').title(),
                        'category': code.split('.')[0].title(),
                    },
                )
                RolePermission.objects.get_or_create(role=role_obj, permission=perm)
        return payload

    elif entity_type == 'user_role':
        u_id = payload.get('user_id') or payload.get('user')
        r_id = payload.get('role_id') or payload.get('role')
        b_id = payload.get('branch_id') or payload.get('branch')
        if u_id and r_id:
            UserRole.objects.update_or_create(
                id=entity_id,
                defaults={
                    'user_id': u_id,
                    'role_id': r_id,
                    'branch_id': b_id,
                    'is_active': bool(payload.get('is_active', True)),
                },
            )
        return payload

    elif entity_type == 'category':
        parent_id = payload.get('parent_id') or payload.get('parent')
        Category.objects.update_or_create(
            id=entity_id,
            organization_id=org_id,
            defaults={
                'name': payload['name'],
                'parent_id': parent_id,
                'is_active': payload.get('is_active', True),
            },
        )
        return payload

    elif entity_type == 'product_type':
        ProductType.objects.update_or_create(
            id=entity_id,
            organization_id=org_id,
            defaults={
                'name': payload['name'],
                'description': payload.get('description', ''),
                'is_active': payload.get('is_active', True),
            },
        )
        return payload

    elif entity_type == 'manufacturer':
        Manufacturer.objects.update_or_create(
            id=entity_id,
            organization_id=org_id,
            defaults={
                'name': payload['name'],
                'country': payload.get('country', ''),
                'contact_info': payload.get('contact_info', ''),
                'is_active': payload.get('is_active', True),
            },
        )
        return payload

    elif entity_type == 'supplier':
        Supplier.objects.update_or_create(
            id=entity_id,
            organization_id=org_id,
            defaults={
                'name': payload['name'],
                'contact_person': payload.get('contact_person', ''),
                'phone': payload.get('phone', ''),
                'email': payload.get('email', ''),
                'address': payload.get('address', ''),
                'notes': payload.get('notes', ''),
                'is_active': payload.get('is_active', True),
            },
        )
        return payload

    elif entity_type == 'product':
        cat_id = payload.get('category_id') or payload.get('category')
        pt_id = payload.get('product_type_id') or payload.get('product_type')
        mfg_id = payload.get('manufacturer_id') or payload.get('manufacturer')
        defaults = {
            'sku': payload['sku'],
            'barcode': payload.get('barcode'),
            'name': payload['name'],
            'generic_name': payload.get('generic_name'),
            'brand_name': payload.get('brand_name'),
            'category_id': cat_id,
            'product_type_id': pt_id,
            'manufacturer_id': mfg_id,
            'description': payload.get('description', ''),
            'active_ingredients': payload.get('active_ingredients'),
            'strength': payload.get('strength'),
            'dosage_form': payload.get('dosage_form'),
            'route': payload.get('route'),
            'formulation': payload.get('formulation'),
            'indication': payload.get('indication'),
            'contraindications': payload.get('contraindications'),
            'precautions': payload.get('precautions'),
            'drug_interactions': payload.get('drug_interactions'),
            'side_effects': payload.get('side_effects'),
            'storage_conditions': payload.get('storage_conditions'),
            'age_suitability': payload.get('age_suitability'),
            'pregnancy_caution': bool(payload.get('pregnancy_caution', False)),
            'prescription_required': bool(payload.get('prescription_required', False)),
            'controlled_status': payload.get('controlled_status'),
            'importer': payload.get('importer'),
            'regulatory_info': payload.get('regulatory_info'),
            'image_url': payload.get('image_url'),
            'notes': payload.get('notes'),
            'is_active': payload.get('is_active', True),
        }
        Product.objects.update_or_create(
            id=entity_id,
            organization_id=org_id,
            defaults=defaults,
        )
        return payload

    elif entity_type == 'product_branch':
        prod_id = payload.get('product_id') or payload.get('product')
        br_id = payload.get('branch_id') or payload.get('branch')
        ProductBranch.objects.update_or_create(
            id=entity_id,
            defaults={
                'product_id': prod_id,
                'branch_id': br_id,
                'is_active': payload.get('is_active', True),
                'reorder_level': payload.get('reorder_level'),
                'settings': payload.get('settings') if isinstance(payload.get('settings'), dict) else {},
            },
        )
        return payload

    elif entity_type == 'batch':
        prod_id = payload.get('product_id') or payload.get('product')
        sup_id = payload.get('supplier_id') or payload.get('supplier')
        existing_batch = Batch.objects.filter(id=entity_id, organization_id=org_id).first()
        if existing_batch and operation == 'UPDATE':
            if 'status' in payload:
                existing_batch.status = payload['status']
            if 'notes' in payload:
                existing_batch.notes = payload['notes']
            existing_batch.save()
        else:
            exp_date = _parse_d(payload.get('expiry_date')) or date.today()
            rec_date = _parse_d(payload.get('received_date')) or date.today()
            mfg_date = _parse_d(payload.get('manufacturing_date'))
            status_val = payload.get('status') or (
                BatchStatus.EXPIRED.value if exp_date < date.today() else BatchStatus.ACTIVE.value
            )
            Batch.objects.update_or_create(
                id=entity_id,
                organization_id=org_id,
                defaults={
                    'product_id': prod_id,
                    'batch_number': payload['batch_number'],
                    'manufacturing_date': mfg_date,
                    'expiry_date': exp_date,
                    'purchase_price': Decimal(str(payload.get('purchase_price', '0.00'))),
                    'supplier_id': sup_id,
                    'invoice_reference': payload.get('invoice_reference', ''),
                    'received_date': rec_date,
                    'status': status_val,
                    'notes': payload.get('notes', ''),
                },
            )
        return payload

    elif entity_type == 'storage_location':
        br_id = payload.get('branch_id') or payload.get('branch') or branch_id
        StorageLocation.objects.update_or_create(
            id=entity_id,
            organization_id=org_id,
            defaults={
                'branch_id': br_id,
                'name': payload['name'],
                'description': payload.get('description', ''),
                'location_type': payload.get('location_type', ''),
                'is_active': payload.get('is_active', True),
            },
        )
        return payload

    elif entity_type == 'price':
        prod_id = payload.get('product_id') or payload.get('product')
        br_id = payload.get('branch_id') or payload.get('branch')
        is_curr = bool(payload.get('is_current', True))
        force_all = bool(payload.get('force_all_branches', br_id is None))

        if is_curr:
            if force_all or br_id is None:
                Price.objects.select_for_update().filter(
                    organization_id=org_id,
                    product_id=prod_id,
                    is_current=True,
                ).exclude(id=entity_id).update(is_current=False, effective_to=timezone.now())
            else:
                Price.objects.select_for_update().filter(
                    organization_id=org_id,
                    product_id=prod_id,
                    branch_id=br_id,
                    is_current=True,
                ).exclude(id=entity_id).update(is_current=False, effective_to=timezone.now())

        Price.objects.update_or_create(
            id=entity_id,
            organization_id=org_id,
            defaults={
                'product_id': prod_id,
                'branch_id': br_id,
                'selling_price': Decimal(str(payload['selling_price'])),
                'currency': payload.get('currency', 'NGN'),
                'is_current': is_curr,
                'version': int(payload.get('version', 1)),
                'effective_from': _parse_dt(payload.get('effective_from')),
                'created_by': request_user,
                'sync_status': 'SYNCED',
            },
        )
        if request_user:
            payload.setdefault('created_by_id', str(request_user.id))
            payload.setdefault('changed_by_id', str(request_user.id))
            u_label = (
                f"{request_user.full_name} (@{request_user.username})"
                if getattr(request_user, 'full_name', '')
                else f"@{request_user.username}"
            )
            payload.setdefault('changed_by_name', u_label)
        if branch_id:
            payload.setdefault('source_branch_id', str(branch_id))
            if not payload.get('source_branch_name'):
                src_b = Branch.objects.filter(id=branch_id).first()
                if src_b:
                    payload['source_branch_name'] = src_b.name
        return payload

    elif entity_type == 'price_history':
        prod_id = payload.get('product_id') or payload.get('product')
        price_id = payload.get('price_id') or payload.get('price')
        br_id = payload.get('branch_id') or payload.get('branch')
        changed_by_id = payload.get('changed_by_id') or (str(request_user.id) if request_user else None)
        old_p = payload.get('old_price')
        new_p = payload.get('new_price')
        if not PriceHistory.objects.filter(id=entity_id).exists() and price_id and prod_id:
            PriceHistory.objects.create(
                id=entity_id,
                organization_id=org_id,
                price_id=price_id,
                product_id=prod_id,
                branch_id=br_id,
                old_price=Decimal(str(old_p)) if old_p is not None else None,
                new_price=Decimal(str(new_p or '0.00')),
                changed_by_id=changed_by_id,
                change_reason=payload.get('change_reason', ''),
                version=int(payload.get('version', 1)),
                local_timestamp=_parse_dt(payload.get('local_timestamp')),
                sync_status='SYNCED',
            )
        if request_user:
            payload.setdefault('changed_by_id', str(request_user.id))
            u_label = (
                f"{request_user.full_name} (@{request_user.username})"
                if getattr(request_user, 'full_name', '')
                else f"@{request_user.username}"
            )
            payload.setdefault('changed_by_name', u_label)
        if branch_id:
            payload.setdefault('source_branch_id', str(branch_id))
            if not payload.get('source_branch_name'):
                src_b = Branch.objects.filter(id=branch_id).first()
                if src_b:
                    payload['source_branch_name'] = src_b.name
        return payload

    elif entity_type == 'inventory_movement':
        # Check if movement with this exact ID already exists
        if InventoryMovement.objects.filter(id=entity_id).exists():
            return payload

        mov_branch_id = uuid.UUID(str(payload.get('branch_id') or branch_id))
        mov_batch_id = uuid.UUID(str(payload['batch_id']))
        loc_id = payload.get('storage_location_id')
        qty_change = int(payload['quantity_change'])
        mov_type = payload['movement_type']
        ref_type = payload.get('reference_type', 'sync')
        ref_id = uuid.UUID(str(payload.get('reference_id') or entity_id))

        acting_user = request_user
        if payload.get('user_id'):
            u = User.objects.filter(id=payload['user_id'], organization_id=org_id).first()
            if u:
                acting_user = u

        dev_obj = Device.objects.filter(id=device_id, organization_id=org_id).first()

        # Apply delta with allow_negative=True so offline sales/movements never fail
        # and automatically generate InventoryAlert(OVERSOLD) if server stock < 0.
        with transaction.atomic():
            inv = (
                BranchInventory.objects.select_for_update()
                .filter(
                    organization_id=org_id,
                    branch_id=mov_branch_id,
                    batch_id=mov_batch_id,
                    storage_location_id=loc_id,
                )
                .first()
            )
            if not inv:
                inv = BranchInventory.objects.create(
                    organization_id=org_id,
                    branch_id=mov_branch_id,
                    batch_id=mov_batch_id,
                    storage_location_id=loc_id,
                    quantity=0,
                    reserved_quantity=0,
                )

            qty_before = inv.quantity
            qty_after = qty_before + qty_change
            inv.quantity = qty_after
            if qty_after <= 0:
                inv.status = 'DEPLETED'
            elif inv.status == 'DEPLETED' and qty_after > 0:
                inv.status = 'AVAILABLE'
            inv.save()

            now = timezone.now()
            movement = InventoryMovement.objects.create(
                id=entity_id,
                organization_id=org_id,
                branch_id=mov_branch_id,
                batch_id=mov_batch_id,
                storage_location_id=loc_id,
                movement_type=mov_type,
                quantity_change=qty_change,
                quantity_before=qty_before,
                quantity_after=qty_after,
                reference_type=ref_type,
                reference_id=ref_id,
                user=acting_user,
                device=dev_obj,
                notes=payload.get('notes', ''),
                local_timestamp=_parse_dt(payload.get('local_timestamp')),
                server_timestamp=now,
                is_offline=bool(payload.get('is_offline', True)),
            )

            if qty_after < 0:
                from apps.inventory.models import InventoryAlert
                from shared.enums import InventoryAlertType

                InventoryAlert.objects.create(
                    organization_id=org_id,
                    branch_id=mov_branch_id,
                    batch_id=mov_batch_id,
                    alert_type=InventoryAlertType.OVERSOLD.value,
                    details={
                        "quantity_before": qty_before,
                        "quantity_change": qty_change,
                        "quantity_after": qty_after,
                        "movement_id": str(movement.id),
                        "source_device_id": str(device_id),
                    },
                )

            # Update Batch status
            from django.db.models import Sum

            batch = Batch.objects.select_for_update().get(id=mov_batch_id)
            if batch.status != BatchStatus.RECALLED.value:
                total_qty = (
                    BranchInventory.objects.filter(batch_id=mov_batch_id).aggregate(
                        total=Sum('quantity')
                    )['total']
                    or 0
                )
                if batch.expiry_date < date.today():
                    batch.status = BatchStatus.EXPIRED.value
                elif total_qty <= 0:
                    batch.status = BatchStatus.DEPLETED.value
                else:
                    batch.status = BatchStatus.ACTIVE.value
                batch.save(update_fields=['status', 'updated_at'])

            return {
                "id": str(movement.id),
                "organization_id": str(org_id),
                "branch_id": str(mov_branch_id),
                "batch_id": str(mov_batch_id),
                "storage_location_id": str(loc_id) if loc_id else None,
                "movement_type": movement.movement_type,
                "quantity_change": movement.quantity_change,
                "quantity_before": movement.quantity_before,
                "quantity_after": movement.quantity_after,
                "reference_type": movement.reference_type,
                "reference_id": str(movement.reference_id),
                "user_id": str(acting_user.id),
                "device_id": str(device_id) if device_id else None,
                "notes": movement.notes,
                "local_timestamp": movement.local_timestamp.isoformat(),
                "server_timestamp": now.isoformat(),
                "is_offline": movement.is_offline,
            }

    elif entity_type == 'audit_event':
        if not AuditEvent.objects.filter(id=entity_id).exists():
            AuditEvent.objects.create(
                id=entity_id,
                organization_id=org_id,
                branch_id=uuid.UUID(str(payload.get('branch_id') or branch_id)),
                user_id=uuid.UUID(str(payload.get('user_id') or request_user.id)),
                device_id=uuid.UUID(str(payload.get('device_id') or device_id)) if (payload.get('device_id') or device_id) else None,
                action=payload.get('action', AuditAction.SETTINGS_CHANGED.value),
                entity_type=payload.get('entity_type', 'unknown'),
                entity_id=uuid.UUID(str(payload.get('entity_id') or entity_id)),
                data_before=payload.get('data_before'),
                data_after=payload.get('data_after'),
                reason=payload.get('reason', ''),
                correlation_id=uuid.UUID(str(payload['correlation_id'])) if payload.get('correlation_id') else None,
                transaction_id=uuid.UUID(str(payload['transaction_id'])) if payload.get('transaction_id') else None,
                local_timestamp=_parse_dt(payload.get('local_timestamp') or event.get('local_created_at')),
                server_timestamp=timezone.now(),
                is_offline=bool(payload.get('is_offline', True)),
                source=payload.get('source', AuditSource.DESKTOP.value),
                sync_id=uuid.UUID(str(event['id'])),
            )
        return payload

    else:
        raise ValueError(f"Unsupported sync entity_type: '{entity_type}'")


def process_sync_upload_batch(
    *,
    organization: Organization,
    branch_id: uuid.UUID,
    device_id: uuid.UUID,
    request_user: User,
    events: list[dict],
) -> list[dict]:
    """
    Processes a batch of uploaded SyncEvents.
    1. Groups events by `correlation_id` (events without correlation_id form singleton groups).
    2. Orders groups by minimum (dependency_level, local_created_at), and events within each group
       by (dependency_level, local_created_at).
    3. Executes each correlation group inside an atomic DB transaction.
    4. Enforces idempotency via ProcessedEvent.
    5. Creates SyncDelivery records for downstream devices/branches.
    """
    groups: OrderedDict[str, list[dict]] = OrderedDict()
    for ev in events:
        corr = ev.get('correlation_id')
        group_key = f"corr_{corr}" if corr else f"single_{ev['id']}"
        groups.setdefault(group_key, []).append(ev)

    # Sort events inside each group by dependency_level ASC, local_created_at ASC
    for g_key, g_events in groups.items():
        g_events.sort(
            key=lambda e: (
                int(e.get('dependency_level') or SYNC_DEPENDENCY_LEVELS.get(e['entity_type'], 5)),
                str(e.get('local_created_at') or ''),
            )
        )

    # Sort groups by minimum (dependency_level, local_created_at)
    sorted_group_items = sorted(
        groups.items(),
        key=lambda item: (
            min(
                int(e.get('dependency_level') or SYNC_DEPENDENCY_LEVELS.get(e['entity_type'], 5))
                for e in item[1]
            ),
            min(str(e.get('local_created_at') or '') for e in item[1]),
        ),
    )

    results_by_id: dict[str, dict] = {}
    now = timezone.now()
    expires_at = now + timedelta(days=90)

    # Update device last_seen_at if registered
    Device.objects.filter(id=device_id, organization_id=organization.id).update(last_seen_at=now)

    for _, group_events in sorted_group_items:
        try:
            with transaction.atomic():
                group_results = []
                for ev in group_events:
                    ev_id = uuid.UUID(str(ev['id']))
                    ev_id_str = str(ev_id)

                    # 1. Idempotency check
                    if ProcessedEvent.objects.filter(event_id=ev_id).exists():
                        group_results.append({
                            "event_id": ev_id_str,
                            "status": "DUPLICATE_IGNORED",
                            "server_received_at": now.isoformat(),
                        })
                        continue

                    # 2. Check if acting user was disabled when performing offline action
                    payload = ev.get('payload') or {}
                    acting_user_id = payload.get('user_id')
                    if acting_user_id:
                        acting_user = User.objects.filter(
                            id=acting_user_id, organization_id=organization.id
                        ).first()
                        if acting_user and not acting_user.is_active:
                            AuditEvent.objects.create(
                                organization=organization,
                                branch_id=branch_id,
                                user_id=acting_user.id,
                                device_id=device_id,
                                action=AuditAction.DISABLED_USER_ACTION.value,
                                entity_type=ev['entity_type'],
                                entity_id=uuid.UUID(str(ev['entity_id'])),
                                data_after=payload,
                                reason="Offline action uploaded for a user who is currently disabled.",
                                local_timestamp=_parse_dt(ev.get('local_created_at')),
                                server_timestamp=now,
                                is_offline=True,
                                source=AuditSource.SERVER_SYNC.value,
                                sync_id=ev_id,
                            )

                    # 3. Apply the event to server models
                    delivery_payload = apply_single_sync_event(
                        organization=organization,
                        branch_id=branch_id,
                        device_id=device_id,
                        request_user=request_user,
                        event=ev,
                    )

                    # 4. Record ProcessedEvent for idempotency
                    ProcessedEvent.objects.create(
                        event_id=ev_id,
                        organization=organization,
                    )

                    # 5. Create SyncDelivery for other devices/branches (skip audit_event echoes)
                    if ev['entity_type'] != 'audit_event':
                        target_scope, target_branch_id = determine_target_scope(
                            ev['entity_type'], delivery_payload
                        )
                        SyncDelivery.objects.create(
                            organization=organization,
                            entity_type=ev['entity_type'],
                            entity_id=uuid.UUID(str(ev['entity_id'])),
                            operation=ev['operation'],
                            payload=delivery_payload,
                            target_scope=target_scope,
                            target_branch_id=target_branch_id,
                            source_branch_id=branch_id,
                            source_device_id=device_id,
                            source_event_id=ev_id,
                            expires_at=expires_at,
                        )

                    group_results.append({
                        "event_id": ev_id_str,
                        "status": "PROCESSED",
                        "server_received_at": now.isoformat(),
                    })

                for r in group_results:
                    results_by_id[r['event_id']] = r

        except Exception as exc:
            # Entire correlation_id group rolled back atomically!
            for ev in group_events:
                ev_id_str = str(ev['id'])
                results_by_id[ev_id_str] = {
                    "event_id": ev_id_str,
                    "status": "FAILED",
                    "error_message": str(exc),
                    "server_received_at": now.isoformat(),
                }

    # Return results in original request order
    return [results_by_id[str(ev['id'])] for ev in events]


def cleanup_expired_sync_deliveries(organization_id=None, before_timestamp=None) -> int:
    """
    Prunes SyncDelivery records that have exceeded their retention period (Architecture Plan §4, §15, §16).
    Deletes records where expires_at <= cutoff (or older than 90 days if before_timestamp specified).
    """
    cutoff = before_timestamp or timezone.now()
    qs = SyncDelivery.objects.filter(expires_at__lte=cutoff)
    if organization_id:
        qs = qs.filter(organization_id=organization_id)
    deleted_count, _ = qs.delete()
    return deleted_count

