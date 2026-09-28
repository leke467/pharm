import uuid
from decimal import Decimal
from django.utils import timezone
from apps.sync.services import register_sync_handler, _parse_dt
from apps.pricing.models import Price, PriceHistory
from apps.products.models import Product
from apps.branches.models import Branch
from apps.users.models import User


def handle_price_history_sync(
    *, organization, branch_id, device_id, request_user, entity_id, operation, payload, event
) -> dict:
    hist_id = uuid.UUID(str(entity_id))
    price_id = uuid.UUID(str(payload['price_id']))
    prod_id = uuid.UUID(str(payload['product_id']))
    b_id = uuid.UUID(str(payload['branch_id'])) if payload.get('branch_id') else None

    price = Price.objects.filter(id=price_id).first()
    product = Product.objects.filter(id=prod_id, organization=organization).first()
    if not price or not product:
        raise ValueError(f"Price {price_id} or Product {prod_id} not found")

    branch = Branch.objects.filter(id=b_id, organization=organization).first() if b_id else None

    old_price_val = Decimal(str(payload['old_price'])) if payload.get('old_price') is not None else None
    new_price_val = Decimal(str(payload['new_price']))

    PriceHistory.objects.update_or_create(
        id=hist_id,
        defaults={
            'organization': organization,
            'price': price,
            'product': product,
            'branch': branch,
            'old_price': old_price_val,
            'new_price': new_price_val,
            'changed_by': request_user,
            'change_reason': payload.get('change_reason', ''),
            'version': int(payload.get('version', 1)),
            'local_timestamp': _parse_dt(payload.get('local_timestamp')),
            'sync_status': 'SYNCED',
        },
    )
    return payload


register_sync_handler('price_history', handle_price_history_sync)
