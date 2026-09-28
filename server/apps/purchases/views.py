import uuid
from decimal import Decimal
from django.db import models, transaction
from django.utils import timezone
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.audit.models import AuditEvent
from apps.branches.models import Branch
from apps.core.mixins import OrganizationQuerysetMixin
from apps.core.permissions import IsOrganizationMember, require_permission
from apps.inventory.models import Batch
from apps.inventory.views import apply_inventory_movement
from apps.pricing.models import Price
from apps.products.models import Supplier, Product
from shared.enums import (
    AuditAction,
    AuditSource,
    BatchStatus,
    MovementType,
    PaymentStatus,
    PermissionCode,
    ReceivingStatus,
)
from .models import Purchase, PurchaseItem, PurchasePayment
from .serializers import (
    PurchaseSerializer,
    CreatePurchaseRequestSerializer,
    ReceivePurchaseRequestSerializer,
    CreatePurchasePaymentInputSerializer,
)


class PurchaseViewSet(OrganizationQuerysetMixin, viewsets.ModelViewSet):
    """
    Purchasing & Inventory Receiving API (Architecture Plan §8).
    """
    queryset = Purchase.objects.select_related('branch', 'supplier', 'user').prefetch_related(
        'items__product', 'items__batch', 'payments'
    )
    serializer_class = PurchaseSerializer
    permission_classes = [IsAuthenticated, IsOrganizationMember]

    def get_queryset(self):
        qs = super().get_queryset()
        branch_id = self.request.query_params.get('branch_id')
        if branch_id:
            qs = qs.filter(branch_id=branch_id)
        supplier_id = self.request.query_params.get('supplier_id')
        if supplier_id:
            qs = qs.filter(supplier_id=supplier_id)
        receiving_status = self.request.query_params.get('receiving_status')
        if receiving_status:
            qs = qs.filter(receiving_status=receiving_status)
        return qs

    def create(self, request, *args, **kwargs):
        req_ser = CreatePurchaseRequestSerializer(data=request.data)
        req_ser.is_valid(raise_exception=True)
        data = req_ser.validated_data
        org = request.user.organization

        try:
            branch = Branch.objects.get(id=data['branch_id'], organization=org)
        except Branch.DoesNotExist:
            return Response(
                {"error": {"code": "invalid_branch", "message": "Branch not found."}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            supplier = Supplier.objects.get(id=data['supplier_id'], organization=org, is_active=True)
        except Supplier.DoesNotExist:
            return Response(
                {"error": {"code": "invalid_supplier", "message": "Active supplier not found."}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if Purchase.objects.filter(organization=org, purchase_reference=data['purchase_reference']).exists():
            return Response(
                {"error": {"code": "duplicate_reference", "message": "Purchase reference already exists."}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            subtotal = Decimal('0.00')
            prepared_items = []
            for item_in in data['items']:
                try:
                    product = Product.objects.get(
                        id=item_in['product_id'], organization=org, is_active=True
                    )
                except Product.DoesNotExist:
                    return Response(
                        {"error": {"code": "invalid_product", "message": f"Product {item_in['product_id']} not found."}},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                qty = int(item_in['quantity_ordered'])
                p_price = Decimal(str(item_in['purchase_price']))
                s_price = Decimal(str(item_in.get('selling_price', '0.00')))
                disc = Decimal(str(item_in.get('discount', '0.00')))
                line_total = max(Decimal('0.00'), (p_price * Decimal(qty)) - disc).quantize(Decimal('0.01'))
                subtotal += line_total
                prepared_items.append((product, qty, p_price, s_price, disc, line_total))

            order_discount = Decimal(str(data.get('discount_amount', '0.00')))
            total = max(Decimal('0.00'), subtotal - order_discount).quantize(Decimal('0.01'))

            purchase = Purchase.objects.create(
                organization=org,
                branch=branch,
                supplier=supplier,
                user=request.user,
                purchase_reference=data['purchase_reference'],
                invoice_number=data.get('invoice_number'),
                purchase_date=data['purchase_date'],
                subtotal=subtotal,
                discount_amount=order_discount,
                total=total,
                payment_status=PaymentStatus.UNPAID.value,
                receiving_status=ReceivingStatus.PENDING.value,
                notes=data.get('notes', ''),
            )

            for product, qty, p_price, s_price, disc, line_total in prepared_items:
                PurchaseItem.objects.create(
                    purchase=purchase,
                    product=product,
                    quantity_ordered=qty,
                    quantity_received=0,
                    purchase_price=p_price,
                    selling_price=s_price,
                    discount=disc,
                    line_total=line_total,
                )

        return Response(PurchaseSerializer(purchase).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'], url_path='receive')
    def receive(self, request, pk=None):
        """
        Receives stock for one or more PurchaseItems on a Purchase:
        - Creates or updates Batch (`ACTIVE` status)
        - Applies `STOCK_RECEIVED` InventoryMovement
        - Updates `PurchaseItem.quantity_received` and `PurchaseItem.batch`
        - Optionally updates current `Price` (`update_selling_price=True`)
        - Updates `Purchase.receiving_status` (`PARTIALLY_RECEIVED` or `RECEIVED`)
        - Records `AuditEvent(STOCK_RECEIVED)`
        """
        purchase = self.get_object()
        if purchase.receiving_status == ReceivingStatus.RECEIVED.value:
            return Response(
                {"error": {"code": "already_received", "message": "Purchase is already fully received."}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        req_ser = ReceivePurchaseRequestSerializer(data=request.data)
        req_ser.is_valid(raise_exception=True)
        data = req_ser.validated_data
        org = request.user.organization
        corr_id = uuid.uuid4()
        today = timezone.now().date()

        with transaction.atomic():
            purchase = Purchase.objects.select_for_update().get(pk=purchase.pk)
            if data.get('invoice_number'):
                purchase.invoice_number = data['invoice_number']

            p_items_map = {
                pi.id: pi
                for pi in PurchaseItem.objects.select_for_update().filter(purchase=purchase)
            }

            for rec_in in data['items']:
                pi_id = rec_in['purchase_item_id']
                if pi_id not in p_items_map:
                    return Response(
                        {"error": {"code": "invalid_purchase_item", "message": f"PurchaseItem {pi_id} does not belong to this purchase."}},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                pi = p_items_map[pi_id]
                qty_rec = int(rec_in['quantity_received'])
                remaining = pi.quantity_ordered - pi.quantity_received
                if qty_rec > remaining:
                    return Response(
                        {
                            "error": {
                                "code": "over_receive_blocked",
                                "message": f"Cannot receive {qty_rec} units for {pi.product.name}; only {remaining} units remain.",
                            }
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                exp_date = rec_in['expiry_date']
                if exp_date <= today:
                    return Response(
                        {"error": {"code": "expired_batch_rejected", "message": "Cannot receive an already-expired batch."}},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                batch, created = Batch.objects.get_or_create(
                    organization=org,
                    product=pi.product,
                    batch_number=rec_in['batch_number'],
                    defaults={
                        'expiry_date': exp_date,
                        'manufacturing_date': rec_in.get('manufacturing_date'),
                        'purchase_price': pi.purchase_price,
                        'supplier': purchase.supplier,
                        'received_date': today,
                        'status': BatchStatus.ACTIVE.value,
                    },
                )
                if not created:
                    batch.expiry_date = exp_date
                    batch.purchase_price = pi.purchase_price
                    batch.supplier = purchase.supplier
                    if batch.status == BatchStatus.DEPLETED.value:
                        batch.status = BatchStatus.ACTIVE.value
                    batch.save()

                apply_inventory_movement(
                    organization_id=org.id,
                    branch_id=purchase.branch_id,
                    batch_id=batch.id,
                    storage_location_id=rec_in.get('storage_location_id'),
                    movement_type=MovementType.STOCK_RECEIVED.value,
                    quantity_change=qty_rec,
                    reference_type='purchase',
                    reference_id=purchase.id,
                    user=request.user,
                    notes=f"Purchase {purchase.purchase_reference} received",
                )

                pi.batch = batch
                pi.quantity_received += qty_rec
                new_sell = rec_in.get('selling_price')
                if new_sell is not None:
                    pi.selling_price = Decimal(str(new_sell))
                pi.save()

                # Optionally update current Price when receiving stock
                if rec_in.get('update_selling_price') and pi.selling_price and pi.selling_price > Decimal('0.00'):
                    now_ts = timezone.now()
                    prev_prices = Price.objects.filter(
                        organization=org,
                        product=pi.product,
                        branch=purchase.branch,
                        is_current=True,
                    )
                    max_ver = prev_prices.aggregate(models.Max('version'))['version__max'] or 0
                    prev_prices.update(is_current=False, effective_to=now_ts)
                    Price.objects.create(
                        organization=org,
                        product=pi.product,
                        branch=purchase.branch,
                        selling_price=pi.selling_price,
                        is_current=True,
                        version=max_ver + 1,
                        effective_from=now_ts,
                        created_by=request.user,
                    )

            all_received = all(
                item.quantity_received >= item.quantity_ordered
                for item in p_items_map.values()
            )
            purchase.receiving_status = (
                ReceivingStatus.RECEIVED.value
                if all_received
                else ReceivingStatus.PARTIALLY_RECEIVED.value
            )
            purchase.save()

            AuditEvent.objects.create(
                organization_id=org.id,
                branch_id=purchase.branch_id,
                user_id=request.user.id,
                action=AuditAction.STOCK_RECEIVED.value,
                entity_type='purchase',
                entity_id=purchase.id,
                data_after={
                    'purchase_reference': purchase.purchase_reference,
                    'receiving_status': purchase.receiving_status,
                },
                correlation_id=corr_id,
                transaction_id=purchase.id,
                local_timestamp=timezone.now(),
                source=AuditSource.SERVER.value,
            )

        return Response(PurchaseSerializer(purchase).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], url_path='pay')
    def pay(self, request, pk=None):
        purchase = self.get_object()
        req_ser = CreatePurchasePaymentInputSerializer(data=request.data)
        req_ser.is_valid(raise_exception=True)
        data = req_ser.validated_data

        with transaction.atomic():
            purchase = Purchase.objects.select_for_update().get(pk=purchase.pk)
            PurchasePayment.objects.create(
                purchase=purchase,
                payment_method=data['payment_method'],
                amount=data['amount'],
                reference=data.get('reference'),
                payment_date=data['payment_date'],
            )
            total_paid = (
                PurchasePayment.objects.filter(purchase=purchase).aggregate(
                    s=models.Sum('amount')
                )['s']
                or Decimal('0.00')
            )
            if total_paid >= purchase.total:
                purchase.payment_status = PaymentStatus.PAID.value
            elif total_paid > Decimal('0.00'):
                purchase.payment_status = PaymentStatus.PARTIALLY_PAID.value
            else:
                purchase.payment_status = PaymentStatus.UNPAID.value
            purchase.save()

        return Response(PurchaseSerializer(purchase).data, status=status.HTTP_200_OK)
