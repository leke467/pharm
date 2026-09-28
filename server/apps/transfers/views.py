import uuid
from datetime import timedelta
from django.db import models, transaction
from django.utils import timezone
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError

from apps.core.mixins import OrganizationQuerysetMixin
from apps.branches.models import Branch
from apps.products.models import Product
from apps.inventory.models import Batch, BranchInventory, InventoryMovement
from apps.transfers.models import StockTransfer, StockTransferItem
from apps.transfers.serializers import (
    StockTransferSerializer,
    StockTransferCreateSerializer,
)
from apps.audit.models import AuditEvent
from apps.sync.models import SyncDelivery
from shared.enums import (
    TransferStatus,
    MovementType,
    AuditAction,
    AuditSource,
    SyncTargetScope,
    SyncOperation,
)


def queue_transfer_sync_delivery(transfer: StockTransfer, operation: str = SyncOperation.CREATE.value):
    """Deliver transfer updates to both source and destination branches."""
    payload = {
        'id': str(transfer.id),
        'organization_id': str(transfer.organization_id),
        'source_branch_id': str(transfer.source_branch_id),
        'destination_branch_id': str(transfer.destination_branch_id),
        'status': transfer.status,
        'requested_by_id': str(transfer.requested_by_id) if transfer.requested_by_id else None,
        'approved_by_id': str(transfer.approved_by_id) if transfer.approved_by_id else None,
        'dispatched_by_id': str(transfer.dispatched_by_id) if transfer.dispatched_by_id else None,
        'received_by_id': str(transfer.received_by_id) if transfer.received_by_id else None,
        'requested_at': transfer.requested_at.isoformat() if transfer.requested_at else None,
        'approved_at': transfer.approved_at.isoformat() if transfer.approved_at else None,
        'dispatched_at': transfer.dispatched_at.isoformat() if transfer.dispatched_at else None,
        'received_at': transfer.received_at.isoformat() if transfer.received_at else None,
        'notes': transfer.notes,
        'created_at': transfer.created_at.isoformat(),
        'updated_at': transfer.updated_at.isoformat(),
        'items': [
            {
                'id': str(item.id),
                'stock_transfer_id': str(transfer.id),
                'product_id': str(item.product_id),
                'batch_id': str(item.batch_id),
                'quantity': item.quantity,
                'created_at': item.created_at.isoformat(),
            }
            for item in transfer.items.all()
        ]
    }
    expires_at = timezone.now() + timedelta(days=90)

    # Deliver to both source and destination branch
    for b_id in [transfer.source_branch_id, transfer.destination_branch_id]:
        SyncDelivery.objects.create(
            organization=transfer.organization,
            entity_type='stock_transfer',
            entity_id=transfer.id,
            operation=operation,
            payload=payload,
            target_scope=SyncTargetScope.SPECIFIC_BRANCH.value,
            target_branch_id=b_id,
            source_branch_id=transfer.source_branch_id,
            expires_at=expires_at,
        )


class StockTransferViewSet(OrganizationQuerysetMixin, viewsets.ModelViewSet):
    queryset = StockTransfer.objects.all().select_related(
        'source_branch', 'destination_branch', 'requested_by', 'approved_by', 'dispatched_by', 'received_by'
    ).prefetch_related('items__product', 'items__batch')
    serializer_class = StockTransferSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = super().get_queryset()
        branch_id = self.request.query_params.get('branch_id')
        if branch_id:
            qs = qs.filter(
                models.Q(source_branch_id=branch_id) | models.Q(destination_branch_id=branch_id)
            )
        status_param = self.request.query_params.get('status')
        if status_param:
            qs = qs.filter(status=status_param)
        return qs

    def create(self, request, *args, **kwargs):
        serializer = StockTransferCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        source_branch = Branch.objects.filter(
            id=data['source_branch_id'], organization_id=request.organization_id
        ).first()
        destination_branch = Branch.objects.filter(
            id=data['destination_branch_id'], organization_id=request.organization_id
        ).first()

        if not source_branch or not destination_branch:
            raise ValidationError("Invalid source or destination branch.")

        items_data = data['items']

        with transaction.atomic():
            transfer = StockTransfer.objects.create(
                organization_id=request.organization_id,
                source_branch=source_branch,
                destination_branch=destination_branch,
                status=TransferStatus.REQUESTED.value,
                requested_by=request.user,
                requested_at=timezone.now(),
                notes=data.get('notes', ''),
            )

            for item_data in items_data:
                product = Product.objects.filter(
                    id=item_data['product_id'], organization_id=request.organization_id
                ).first()
                batch = Batch.objects.filter(
                    id=item_data['batch_id'], organization_id=request.organization_id
                ).first()
                if not product or not batch:
                    raise ValidationError(f"Invalid product or batch for item: {item_data}")
                StockTransferItem.objects.create(
                    stock_transfer=transfer,
                    product=product,
                    batch=batch,
                    quantity=item_data['quantity'],
                )

            AuditEvent.objects.create(
                organization=transfer.organization,
                branch_id=source_branch.id,
                user_id=request.user.id,
                action=AuditAction.TRANSFER_REQUESTED.value,
                entity_type='stock_transfer',
                entity_id=transfer.id,
                data_after={'status': transfer.status, 'source': source_branch.code, 'dest': destination_branch.code},
                local_timestamp=timezone.now(),
                source=AuditSource.SERVER.value,
            )

            queue_transfer_sync_delivery(transfer, SyncOperation.CREATE.value)

        read_serializer = self.get_serializer(transfer)
        return Response(read_serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        transfer = self.get_object()
        if transfer.status not in [TransferStatus.REQUESTED.value, TransferStatus.DRAFT.value]:
            raise ValidationError(f"Transfer cannot be approved from status {transfer.status}.")

        with transaction.atomic():
            # Check availability and reserve
            for item in transfer.items.all():
                inv = BranchInventory.objects.select_for_update().filter(
                    branch=transfer.source_branch,
                    batch=item.batch,
                    storage_location=None,
                ).first()
                current_qty = inv.quantity if inv else 0
                current_reserved = inv.reserved_quantity if inv else 0
                available = current_qty - current_reserved

                if available < item.quantity:
                    raise ValidationError(
                        f"Insufficient available stock for batch {item.batch.batch_number} at branch {transfer.source_branch.name}. "
                        f"Available: {available}, Requested: {item.quantity}"
                    )

                if inv is None:
                    raise ValidationError(f"Inventory record missing for batch {item.batch.batch_number}.")

                inv.reserved_quantity += item.quantity
                inv.save(update_fields=['reserved_quantity', 'updated_at'])

            transfer.status = TransferStatus.APPROVED.value
            transfer.approved_by = request.user
            transfer.approved_at = timezone.now()
            transfer.save(update_fields=['status', 'approved_by', 'approved_at', 'updated_at'])

            AuditEvent.objects.create(
                organization=transfer.organization,
                branch_id=transfer.source_branch_id,
                user_id=request.user.id,
                action=AuditAction.TRANSFER_APPROVED.value,
                entity_type='stock_transfer',
                entity_id=transfer.id,
                data_after={'status': transfer.status, 'approved_by': str(request.user.id)},
                local_timestamp=timezone.now(),
                source=AuditSource.SERVER.value,
            )

            queue_transfer_sync_delivery(transfer, SyncOperation.UPDATE.value)

        return Response(self.get_serializer(transfer).data)

    @action(detail=True, methods=['post'], url_path='dispatch')
    def dispatch_transfer(self, request, pk=None):
        transfer = self.get_object()
        if transfer.status != TransferStatus.APPROVED.value:
            raise ValidationError(f"Transfer cannot be dispatched from status {transfer.status}. Must be APPROVED.")

        with transaction.atomic():
            now = timezone.now()
            for item in transfer.items.all():
                inv = BranchInventory.objects.select_for_update().filter(
                    branch=transfer.source_branch,
                    batch=item.batch,
                    storage_location=None,
                ).first()
                if not inv:
                    raise ValidationError(f"Inventory record missing for batch {item.batch.batch_number}.")

                qty_before = inv.quantity
                inv.reserved_quantity = max(0, inv.reserved_quantity - item.quantity)
                inv.quantity -= item.quantity
                if inv.quantity <= 0:
                    inv.status = 'DEPLETED'
                inv.save(update_fields=['quantity', 'reserved_quantity', 'status', 'updated_at'])

                qty_after = inv.quantity

                InventoryMovement.objects.create(
                    organization=transfer.organization,
                    branch=transfer.source_branch,
                    batch=item.batch,
                    storage_location=None,
                    movement_type=MovementType.STOCK_TRANSFER_OUT.value,
                    quantity_change=-item.quantity,
                    quantity_before=qty_before,
                    quantity_after=qty_after,
                    reference_type='transfer',
                    reference_id=transfer.id,
                    user=request.user,
                    local_timestamp=now,
                    server_timestamp=now,
                    is_offline=False,
                )

            transfer.status = TransferStatus.DISPATCHED.value
            transfer.dispatched_by = request.user
            transfer.dispatched_at = now
            transfer.save(update_fields=['status', 'dispatched_by', 'dispatched_at', 'updated_at'])

            AuditEvent.objects.create(
                organization=transfer.organization,
                branch_id=transfer.source_branch_id,
                user_id=request.user.id,
                action=AuditAction.TRANSFER_DISPATCHED.value,
                entity_type='stock_transfer',
                entity_id=transfer.id,
                data_after={'status': transfer.status, 'dispatched_by': str(request.user.id)},
                local_timestamp=now,
                source=AuditSource.SERVER.value,
            )

            queue_transfer_sync_delivery(transfer, SyncOperation.UPDATE.value)

        return Response(self.get_serializer(transfer).data)

    @action(detail=True, methods=['post'])
    def receive(self, request, pk=None):
        transfer = self.get_object()
        if transfer.status not in [TransferStatus.DISPATCHED.value, TransferStatus.IN_TRANSIT.value]:
            raise ValidationError(f"Transfer cannot be received from status {transfer.status}. Must be DISPATCHED.")

        with transaction.atomic():
            now = timezone.now()
            for item in transfer.items.all():
                inv, _ = BranchInventory.objects.select_for_update().get_or_create(
                    organization=transfer.organization,
                    branch=transfer.destination_branch,
                    batch=item.batch,
                    storage_location=None,
                    defaults={'quantity': 0, 'reserved_quantity': 0, 'status': 'AVAILABLE'},
                )

                qty_before = inv.quantity
                inv.quantity += item.quantity
                if inv.quantity > 0:
                    inv.status = 'AVAILABLE'
                inv.save(update_fields=['quantity', 'status', 'updated_at'])

                qty_after = inv.quantity

                InventoryMovement.objects.create(
                    organization=transfer.organization,
                    branch=transfer.destination_branch,
                    batch=item.batch,
                    storage_location=None,
                    movement_type=MovementType.STOCK_TRANSFER_IN.value,
                    quantity_change=item.quantity,
                    quantity_before=qty_before,
                    quantity_after=qty_after,
                    reference_type='transfer',
                    reference_id=transfer.id,
                    user=request.user,
                    local_timestamp=now,
                    server_timestamp=now,
                    is_offline=False,
                )

            transfer.status = TransferStatus.RECEIVED.value
            transfer.received_by = request.user
            transfer.received_at = now
            transfer.save(update_fields=['status', 'received_by', 'received_at', 'updated_at'])

            AuditEvent.objects.create(
                organization=transfer.organization,
                branch_id=transfer.destination_branch_id,
                user_id=request.user.id,
                action=AuditAction.TRANSFER_RECEIVED.value,
                entity_type='stock_transfer',
                entity_id=transfer.id,
                data_after={'status': transfer.status, 'received_by': str(request.user.id)},
                local_timestamp=now,
                source=AuditSource.SERVER.value,
            )

            queue_transfer_sync_delivery(transfer, SyncOperation.UPDATE.value)

        return Response(self.get_serializer(transfer).data)

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        transfer = self.get_object()
        if transfer.status not in [TransferStatus.DRAFT.value, TransferStatus.REQUESTED.value, TransferStatus.APPROVED.value]:
            raise ValidationError(f"Transfer cannot be cancelled from status {transfer.status}.")

        with transaction.atomic():
            if transfer.status == TransferStatus.APPROVED.value:
                # Release reserved quantity
                for item in transfer.items.all():
                    inv = BranchInventory.objects.select_for_update().filter(
                        branch=transfer.source_branch,
                        batch=item.batch,
                        storage_location=None,
                    ).first()
                    if inv:
                        inv.reserved_quantity = max(0, inv.reserved_quantity - item.quantity)
                        inv.save(update_fields=['reserved_quantity', 'updated_at'])

            transfer.status = TransferStatus.CANCELLED.value
            transfer.save(update_fields=['status', 'updated_at'])

            AuditEvent.objects.create(
                organization=transfer.organization,
                branch_id=transfer.source_branch_id,
                user_id=request.user.id,
                action=AuditAction.TRANSFER_CANCELLED.value,
                entity_type='stock_transfer',
                entity_id=transfer.id,
                data_after={'status': transfer.status},
                local_timestamp=timezone.now(),
                source=AuditSource.SERVER.value,
            )

            queue_transfer_sync_delivery(transfer, SyncOperation.UPDATE.value)

        return Response(self.get_serializer(transfer).data)
