from datetime import date
from decimal import Decimal
from django.db import transaction
from django.db.models import Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.audit.models import AuditEvent
from apps.branches.models import Branch, Device
from apps.core.mixins import OrganizationQuerysetMixin
from apps.core.permissions import IsOrganizationMember, require_permission, user_has_permission
from apps.inventory.models import Batch, BranchInventory
from apps.inventory.views import apply_inventory_movement
from apps.products.models import Product
from shared.enums import (
    PermissionCode,
    BatchStatus,
    MovementType,
    SaleStatus,
    SaleReturnStatus,
    AuditAction,
    AuditSource,
)
from .models import Sale, SaleItem, Payment, Receipt, SaleReturn, SaleReturnItem
from .serializers import (
    SaleSerializer,
    ReceiptSerializer,
    CreateSaleRequestSerializer,
    SaleReturnSerializer,
    CreateSaleReturnRequestSerializer,
)


def allocate_batches_fefo_server(organization_id, branch_id, product_id, qty_needed: int) -> list[tuple[Batch, int]]:
    """
    Server-side FEFO batch allocation for a product in a branch.
    Selects ACTIVE, non-expired batches ordered by expiry_date ASC, received_date ASC.
    """
    today = date.today()
    inventories = (
        BranchInventory.objects.select_related('batch')
        .filter(
            organization_id=organization_id,
            branch_id=branch_id,
            batch__product_id=product_id,
            batch__status=BatchStatus.ACTIVE.value,
            batch__expiry_date__gte=today,
        )
        .order_by('batch__expiry_date', 'batch__received_date')
    )
    allocations = []
    remaining = qty_needed
    for inv in inventories:
        if remaining <= 0:
            break
        avail = inv.available_quantity
        if avail <= 0:
            continue
        take = min(remaining, avail)
        allocations.append((inv.batch, take))
        remaining -= take

    if remaining > 0:
        raise DRFValidationError(
            f"Insufficient active stock for product {product_id} (short by {remaining} units)."
        )
    return allocations


class SaleViewSet(OrganizationQuerysetMixin, viewsets.ModelViewSet):
    queryset = Sale.objects.prefetch_related('items', 'payments', 'receipt').all()
    serializer_class = SaleSerializer
    http_method_names = ['get', 'post', 'head', 'options']
    permission_classes = [
        IsAuthenticated,
        IsOrganizationMember,
        require_permission(
            read_perm=PermissionCode.SALES_SELL.value,
            write_perm=PermissionCode.SALES_SELL.value,
        ),
    ]

    def get_queryset(self):
        qs = super().get_queryset()
        branch_id = self.request.query_params.get('branch_id')
        receipt_number = self.request.query_params.get('receipt_number')
        status_filter = self.request.query_params.get('status')
        if branch_id:
            qs = qs.filter(branch_id=branch_id)
        if receipt_number:
            qs = qs.filter(receipt_number=receipt_number)
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs

    def create(self, request, *args, **kwargs):
        serializer = CreateSaleRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        org_id = self.get_organization_id()

        branch = get_object_or_404(Branch, id=data['branch_id'], organization_id=org_id)
        device = get_object_or_404(
            Device, id=data['device_id'], branch=branch, organization_id=org_id
        )
        items_data = data['items']
        payments_data = data['payments']
        if not items_data:
            raise DRFValidationError("A sale must contain at least one item.")
        if not payments_data:
            raise DRFValidationError("A sale must contain at least one payment.")

        today = date.today()
        now = timezone.now()

        with transaction.atomic():
            expanded_items = []
            subtotal = Decimal('0.00')

            for item in items_data:
                product = get_object_or_404(
                    Product, id=item['product_id'], organization_id=org_id
                )
                qty = int(item['quantity'])
                unit_price = Decimal(str(item['unit_price']))
                line_discount = Decimal(str(item.get('discount_amount', '0.00')))

                if item.get('batch_id'):
                    batch = get_object_or_404(
                        Batch,
                        id=item['batch_id'],
                        product=product,
                        organization_id=org_id,
                    )
                    if batch.expiry_date < today:
                        batch.status = BatchStatus.EXPIRED.value
                        batch.save(update_fields=['status', 'updated_at'])
                    if batch.status in (
                        BatchStatus.EXPIRED.value,
                        BatchStatus.RECALLED.value,
                        BatchStatus.DEPLETED.value,
                    ):
                        raise DRFValidationError(
                            f"Cannot sell from batch '{batch.batch_number}' with status '{batch.status}'."
                        )
                    allocations = [(batch, qty)]
                else:
                    allocations = allocate_batches_fefo_server(
                        org_id, branch.id, product.id, qty
                    )

                for alloc_batch, alloc_qty in allocations:
                    alloc_discount = (
                        line_discount
                        if len(allocations) == 1
                        else (line_discount * Decimal(alloc_qty) / Decimal(qty)).quantize(Decimal('0.01'))
                    )
                    line_sub = unit_price * Decimal(alloc_qty)
                    line_tot = line_sub - alloc_discount
                    subtotal += line_sub
                    expanded_items.append({
                        'product': product,
                        'batch': alloc_batch,
                        'quantity': alloc_qty,
                        'unit_price': unit_price,
                        'discount_amount': alloc_discount,
                        'line_total': line_tot,
                    })

            total_item_discounts = sum(i['discount_amount'] for i in expanded_items)
            header_discount = Decimal(str(data.get('discount_amount', '0.00')))
            total_discount = total_item_discounts + header_discount
            tax_amount = Decimal(str(data.get('tax_amount', '0.00')))
            total = subtotal - total_discount + tax_amount

            payment_sum = sum(Decimal(str(p['amount'])) for p in payments_data)
            if payment_sum < total:
                raise DRFValidationError(
                    f"Total payments ({payment_sum}) cannot be less than sale total ({total})."
                )

            sale = Sale.objects.create(
                organization_id=org_id,
                branch=branch,
                user=request.user,
                device=device,
                receipt_number=data['receipt_number'],
                customer_name=data.get('customer_name'),
                customer_phone=data.get('customer_phone'),
                subtotal=subtotal,
                discount_amount=total_discount,
                tax_amount=tax_amount,
                total=total,
                status=SaleStatus.COMPLETED.value,
                sale_date=now,
                server_received_at=now,
                is_offline=False,
                sync_status='SYNCED',
                notes=data.get('notes', ''),
            )

            for exp in expanded_items:
                SaleItem.objects.create(
                    sale=sale,
                    product=exp['product'],
                    batch=exp['batch'],
                    quantity=exp['quantity'],
                    unit_price=exp['unit_price'],
                    discount_amount=exp['discount_amount'],
                    line_total=exp['line_total'],
                )
                apply_inventory_movement(
                    organization_id=org_id,
                    branch_id=branch.id,
                    batch_id=exp['batch'].id,
                    storage_location_id=None,
                    movement_type=MovementType.SALE.value,
                    quantity_change=-exp['quantity'],
                    reference_type='sale',
                    reference_id=sale.id,
                    user=request.user,
                    device_id=device.id,
                    notes=f"POS Sale {sale.receipt_number}",
                    local_timestamp=now,
                    is_offline=False,
                    allow_negative=False,
                )

            for p_data in payments_data:
                Payment.objects.create(
                    sale=sale,
                    payment_method=p_data['payment_method'],
                    amount=Decimal(str(p_data['amount'])),
                    reference=p_data.get('reference'),
                )

            Receipt.objects.create(
                sale=sale,
                receipt_number=sale.receipt_number,
                printed_at=now,
                printer_name='SERVER',
                reprint_count=0,
            )

            AuditEvent.objects.create(
                organization_id=org_id,
                branch_id=branch.id,
                user_id=request.user.id,
                device_id=device.id,
                action=AuditAction.SALE_CREATED.value,
                entity_type='sale',
                entity_id=sale.id,
                data_after={
                    'receipt_number': sale.receipt_number,
                    'total': str(sale.total),
                    'items_count': len(expanded_items),
                },
                local_timestamp=now,
                server_timestamp=now,
                is_offline=False,
                source=AuditSource.SERVER.value,
            )

        return Response(SaleSerializer(sale).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def void(self, request, pk=None):
        """
        POST /api/v1/sales/{id}/void/
        Voids a COMPLETED sale (with no prior returns), restores inventory via
        SALE_RETURN movements, and logs AuditEvent(SALE_VOIDED).
        """
        sale = self.get_object()
        if not user_has_permission(
            request.user, PermissionCode.SALES_VOID.value, branch_id=sale.branch_id
        ):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("You do not have permission to void sales.")

        reason = (request.data.get('reason') or '').strip()
        if not reason:
            raise DRFValidationError({"reason": "A reason is required to void a sale."})

        if sale.status != SaleStatus.COMPLETED.value:
            raise DRFValidationError(
                f"Only COMPLETED sales with no prior returns can be voided (current status: {sale.status})."
            )

        now = timezone.now()
        with transaction.atomic():
            before_status = sale.status
            sale.status = SaleStatus.VOIDED.value
            sale.notes = f"{sale.notes}\n[VOIDED: {reason}]".strip()
            sale.save(update_fields=['status', 'notes', 'updated_at'])

            for item in sale.items.all():
                apply_inventory_movement(
                    organization_id=sale.organization_id,
                    branch_id=sale.branch_id,
                    batch_id=item.batch_id,
                    storage_location_id=None,
                    movement_type=MovementType.SALE_RETURN.value,
                    quantity_change=item.quantity,
                    reference_type='sale_void',
                    reference_id=sale.id,
                    user=request.user,
                    device_id=sale.device_id,
                    notes=f"Voided Sale {sale.receipt_number}: {reason}",
                    local_timestamp=now,
                    is_offline=False,
                    allow_negative=False,
                )

            AuditEvent.objects.create(
                organization_id=sale.organization_id,
                branch_id=sale.branch_id,
                user_id=request.user.id,
                device_id=sale.device_id,
                action=AuditAction.SALE_VOIDED.value,
                entity_type='sale',
                entity_id=sale.id,
                data_before={'status': before_status},
                data_after={'status': sale.status},
                reason=reason,
                local_timestamp=now,
                server_timestamp=now,
                is_offline=False,
                source=AuditSource.SERVER.value,
            )

        return Response(SaleSerializer(sale).data, status=status.HTTP_200_OK)


class SaleReturnViewSet(OrganizationQuerysetMixin, viewsets.ModelViewSet):
    queryset = SaleReturn.objects.prefetch_related('items').all()
    serializer_class = SaleReturnSerializer
    http_method_names = ['get', 'post', 'head', 'options']
    permission_classes = [
        IsAuthenticated,
        IsOrganizationMember,
        require_permission(
            read_perm=PermissionCode.SALES_RETURN.value,
            write_perm=PermissionCode.SALES_RETURN.value,
        ),
    ]

    def get_queryset(self):
        qs = super().get_queryset()
        branch_id = self.request.query_params.get('branch_id')
        original_sale_id = self.request.query_params.get('original_sale_id')
        if branch_id:
            qs = qs.filter(branch_id=branch_id)
        if original_sale_id:
            qs = qs.filter(original_sale_id=original_sale_id)
        return qs

    def create(self, request, *args, **kwargs):
        serializer = CreateSaleReturnRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        org_id = self.get_organization_id()

        sale = get_object_or_404(
            Sale.objects.prefetch_related('items'),
            id=data['original_sale_id'],
            organization_id=org_id,
        )
        if sale.status in (
            SaleStatus.VOIDED.value,
            SaleStatus.CANCELLED.value,
            SaleStatus.RETURNED.value,
        ):
            raise DRFValidationError(
                f"Cannot process a return on a sale with status '{sale.status}'."
            )

        device = get_object_or_404(
            Device, id=data['device_id'], branch_id=sale.branch_id, organization_id=org_id
        )
        items_in = data['items']
        if not items_in:
            raise DRFValidationError("At least one return item is required.")

        now = timezone.now()
        with transaction.atomic():
            sale_items_by_id = {str(si.id): si for si in sale.items.all()}
            validated_return_lines = []
            total_refund = Decimal('0.00')

            for req_line in items_in:
                si_id_str = str(req_line['sale_item_id'])
                if si_id_str not in sale_items_by_id:
                    raise DRFValidationError(
                        f"SaleItem {si_id_str} does not belong to Sale {sale.receipt_number}."
                    )
                si = sale_items_by_id[si_id_str]
                already_returned = (
                    SaleReturnItem.objects.filter(
                        sale_item=si,
                        sale_return__status=SaleReturnStatus.COMPLETED.value,
                    ).aggregate(total=Sum('quantity'))['total']
                    or 0
                )
                remaining_returnable = si.quantity - already_returned
                req_qty = int(req_line['quantity'])
                if req_qty > remaining_returnable:
                    raise DRFValidationError(
                        f"Cannot return {req_qty} units for SaleItem {si.id} (only {remaining_returnable} remaining)."
                    )

                # Net unit refund based on original SaleItem.line_total / quantity
                eff_unit_price = (si.line_total / Decimal(si.quantity)).quantize(Decimal('0.01'))
                line_refund = (eff_unit_price * Decimal(req_qty)).quantize(Decimal('0.01'))
                total_refund += line_refund
                validated_return_lines.append((si, req_qty, eff_unit_price, line_refund))

            sale_return = SaleReturn.objects.create(
                organization_id=org_id,
                original_sale=sale,
                branch=sale.branch,
                user=request.user,
                device=device,
                return_date=now,
                reason=data['reason'],
                refund_amount=total_refund,
                status=SaleReturnStatus.COMPLETED.value,
                approved_by=request.user,
            )

            for si, req_qty, eff_unit_price, line_refund in validated_return_lines:
                SaleReturnItem.objects.create(
                    sale_return=sale_return,
                    sale_item=si,
                    product=si.product,
                    batch=si.batch,
                    quantity=req_qty,
                    unit_price=eff_unit_price,
                    line_total=line_refund,
                )
                apply_inventory_movement(
                    organization_id=org_id,
                    branch_id=sale.branch_id,
                    batch_id=si.batch_id,
                    storage_location_id=None,
                    movement_type=MovementType.SALE_RETURN.value,
                    quantity_change=req_qty,
                    reference_type='sale_return',
                    reference_id=sale_return.id,
                    user=request.user,
                    device_id=device.id,
                    notes=f"Return on {sale.receipt_number}: {data['reason']}",
                    local_timestamp=now,
                    is_offline=False,
                    allow_negative=False,
                )

            # Determine if original sale is now fully RETURNED or PARTIALLY_RETURNED
            total_sold_qty = sum(si.quantity for si in sale.items.all())
            total_returned_qty = (
                SaleReturnItem.objects.filter(
                    sale_return__original_sale=sale,
                    sale_return__status=SaleReturnStatus.COMPLETED.value,
                ).aggregate(total=Sum('quantity'))['total']
                or 0
            )
            before_sale_status = sale.status
            sale.status = (
                SaleStatus.RETURNED.value
                if total_returned_qty >= total_sold_qty
                else SaleStatus.PARTIALLY_RETURNED.value
            )
            sale.save(update_fields=['status', 'updated_at'])

            AuditEvent.objects.create(
                organization_id=org_id,
                branch_id=sale.branch_id,
                user_id=request.user.id,
                device_id=device.id,
                action=AuditAction.SALE_RETURNED.value,
                entity_type='sale_return',
                entity_id=sale_return.id,
                data_before={'sale_status': before_sale_status},
                data_after={
                    'sale_status': sale.status,
                    'refund_amount': str(total_refund),
                },
                reason=data['reason'],
                local_timestamp=now,
                server_timestamp=now,
                is_offline=False,
                source=AuditSource.SERVER.value,
            )

        return Response(
            SaleReturnSerializer(sale_return).data, status=status.HTTP_201_CREATED
        )


class ReceiptViewSet(OrganizationQuerysetMixin, viewsets.ReadOnlyModelViewSet):
    queryset = Receipt.objects.select_related('sale').all()
    serializer_class = ReceiptSerializer
    permission_classes = [
        IsAuthenticated,
        IsOrganizationMember,
        require_permission(read_perm=PermissionCode.SALES_SELL.value),
    ]

    def get_queryset(self):
        return Receipt.objects.filter(sale__organization_id=self.get_organization_id())

    @action(detail=True, methods=['post'])
    def reprint(self, request, pk=None):
        receipt = self.get_object()
        receipt.reprint_count += 1
        receipt.save(update_fields=['reprint_count'])
        return Response(ReceiptSerializer(receipt).data)
