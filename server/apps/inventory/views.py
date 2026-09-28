import uuid
from datetime import date
from django.db import transaction
from django.db.models import Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import viewsets, views, status
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.audit.models import AuditEvent
from apps.branches.models import Branch
from apps.core.mixins import OrganizationQuerysetMixin
from apps.core.permissions import IsOrganizationMember, require_permission
from shared.enums import (
    PermissionCode,
    BatchStatus,
    InventoryStatus,
    MovementType,
    InventoryAlertType,
    AuditAction,
    AuditSource,
)
from .models import (
    Batch,
    StorageLocation,
    StorageLocationAssignment,
    BranchInventory,
    InventoryMovement,
    InventoryAlert,
    StockCount,
    StockCountItem,
)
from .serializers import (
    BatchSerializer,
    StorageLocationSerializer,
    StorageLocationAssignmentSerializer,
    BranchInventorySerializer,
    InventoryMovementSerializer,
    InventoryAlertSerializer,
    OpeningBalanceRequestSerializer,
    StockAdjustmentRequestSerializer,
    StockCountSerializer,
    StockCountItemSerializer,
    StartStockCountRequestSerializer,
    SubmitStockCountRequestSerializer,
    ApproveStockCountRequestSerializer,
)


def apply_inventory_movement(
    *,
    organization_id,
    branch_id,
    batch_id,
    storage_location_id,
    movement_type: str,
    quantity_change: int,
    reference_type: str,
    reference_id,
    user,
    device_id=None,
    notes: str = "",
    local_timestamp=None,
    is_offline: bool = False,
    allow_negative: bool = False,
) -> tuple[BranchInventory, InventoryMovement]:
    """
    Atomically applies a delta movement to BranchInventory and creates an immutable
    InventoryMovement record. Updates Batch status (`DEPLETED` / `EXPIRED`) and creates
    `InventoryAlert(OVERSOLD)` if server-side multi-device sync results in quantity < 0.
    """
    with transaction.atomic():
        inv = (
            BranchInventory.objects.select_for_update()
            .filter(
                organization_id=organization_id,
                branch_id=branch_id,
                batch_id=batch_id,
                storage_location_id=storage_location_id,
            )
            .first()
        )
        if not inv:
            inv = BranchInventory.objects.create(
                organization_id=organization_id,
                branch_id=branch_id,
                batch_id=batch_id,
                storage_location_id=storage_location_id,
                quantity=0,
                reserved_quantity=0,
                status=InventoryStatus.AVAILABLE.value,
            )

        qty_before = inv.quantity
        qty_after = qty_before + quantity_change

        if not allow_negative and qty_after < 0:
            raise DRFValidationError("Insufficient stock for this operation.")

        inv.quantity = qty_after
        if qty_after <= 0:
            inv.status = InventoryStatus.DEPLETED.value
        elif inv.status == InventoryStatus.DEPLETED.value and qty_after > 0:
            inv.status = InventoryStatus.AVAILABLE.value
        inv.save()

        now = timezone.now()
        movement = InventoryMovement.objects.create(
            organization_id=organization_id,
            branch_id=branch_id,
            batch_id=batch_id,
            storage_location_id=storage_location_id,
            movement_type=movement_type,
            quantity_change=quantity_change,
            quantity_before=qty_before,
            quantity_after=qty_after,
            reference_type=reference_type,
            reference_id=reference_id,
            user=user,
            device_id=device_id,
            notes=notes,
            local_timestamp=local_timestamp or now,
            server_timestamp=now,
            is_offline=is_offline,
        )

        if qty_after < 0:
            InventoryAlert.objects.create(
                organization_id=organization_id,
                branch_id=branch_id,
                batch_id=batch_id,
                alert_type=InventoryAlertType.OVERSOLD.value,
                details={
                    "quantity_before": qty_before,
                    "quantity_change": quantity_change,
                    "quantity_after": qty_after,
                    "movement_id": str(movement.id),
                },
            )

        # Check batch status transitions (ACTIVE -> DEPLETED or EXPIRED)
        batch = Batch.objects.select_for_update().get(id=batch_id)
        if batch.status != BatchStatus.RECALLED.value:
            total_qty = (
                BranchInventory.objects.filter(batch_id=batch_id).aggregate(
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

        return inv, movement


class BatchViewSet(OrganizationQuerysetMixin, viewsets.ModelViewSet):
    queryset = Batch.objects.all()
    serializer_class = BatchSerializer
    permission_classes = [
        IsAuthenticated,
        IsOrganizationMember,
        require_permission(
            read_perm=PermissionCode.INVENTORY_VIEW.value,
            write_perm=PermissionCode.BATCHES_MANAGE.value,
        ),
    ]

    def get_queryset(self):
        qs = super().get_queryset()
        product_id = self.request.query_params.get('product_id')
        status_filter = self.request.query_params.get('status')
        if product_id:
            qs = qs.filter(product_id=product_id)
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs

    def perform_create(self, serializer):
        org_id = self.get_organization_id()
        product = serializer.validated_data['product']
        if product.organization_id != org_id:
            raise DRFValidationError("Product must belong to your organization.")
        expiry = serializer.validated_data['expiry_date']
        initial_status = (
            BatchStatus.EXPIRED.value
            if expiry < date.today()
            else BatchStatus.ACTIVE.value
        )
        batch = serializer.save(organization_id=org_id, status=initial_status)
        now = timezone.now()
        AuditEvent.objects.create(
            organization_id=org_id,
            branch_id=self.request.user.default_branch_id or uuid.UUID(int=0),
            user_id=self.request.user.id,
            action=AuditAction.BATCH_CREATED.value,
            entity_type='batch',
            entity_id=batch.id,
            data_after=BatchSerializer(batch).data,
            local_timestamp=now,
            server_timestamp=now,
            is_offline=False,
            source=AuditSource.SERVER.value,
        )

    @action(detail=True, methods=['post'])
    def recall(self, request, pk=None):
        batch = self.get_object()
        reason = request.data.get('reason', 'Batch recalled by administrator')
        before_status = batch.status
        batch.status = BatchStatus.RECALLED.value
        batch.save(update_fields=['status', 'updated_at'])

        now = timezone.now()
        AuditEvent.objects.create(
            organization_id=batch.organization_id,
            branch_id=request.user.default_branch_id or uuid.UUID(int=0),
            user_id=request.user.id,
            action=AuditAction.BATCH_RECALLED.value,
            entity_type='batch',
            entity_id=batch.id,
            data_before={"status": before_status},
            data_after={"status": batch.status},
            reason=reason,
            local_timestamp=now,
            server_timestamp=now,
            is_offline=False,
            source=AuditSource.SERVER.value,
        )
        return Response(BatchSerializer(batch).data)


class StorageLocationViewSet(OrganizationQuerysetMixin, viewsets.ModelViewSet):
    queryset = StorageLocation.objects.all()
    serializer_class = StorageLocationSerializer
    permission_classes = [
        IsAuthenticated,
        IsOrganizationMember,
        require_permission(
            read_perm=PermissionCode.INVENTORY_VIEW.value,
            write_perm=PermissionCode.BRANCHES_MANAGE.value,
        ),
    ]

    def get_queryset(self):
        qs = super().get_queryset()
        branch_id = self.request.query_params.get('branch_id')
        if branch_id:
            qs = qs.filter(branch_id=branch_id)
        return qs

    def perform_create(self, serializer):
        org_id = self.get_organization_id()
        branch = serializer.validated_data['branch']
        if branch.organization_id != org_id:
            raise DRFValidationError("Branch must belong to your organization.")
        if not branch.uses_storage_locations:
            raise DRFValidationError("Storage locations are not enabled for this branch.")
        serializer.save(organization_id=org_id)


class StorageLocationAssignmentViewSet(OrganizationQuerysetMixin, viewsets.ModelViewSet):
    queryset = StorageLocationAssignment.objects.all()
    serializer_class = StorageLocationAssignmentSerializer
    permission_classes = [
        IsAuthenticated,
        IsOrganizationMember,
        require_permission(
            read_perm=PermissionCode.INVENTORY_VIEW.value,
            write_perm=PermissionCode.BRANCHES_MANAGE.value,
        ),
    ]

    def perform_create(self, serializer):
        org_id = self.get_organization_id()
        serializer.save(organization_id=org_id, assigned_by=self.request.user)


class BranchInventoryViewSet(OrganizationQuerysetMixin, viewsets.ReadOnlyModelViewSet):
    queryset = BranchInventory.objects.select_related('batch', 'batch__product').all()
    serializer_class = BranchInventorySerializer
    permission_classes = [
        IsAuthenticated,
        IsOrganizationMember,
        require_permission(read_perm=PermissionCode.INVENTORY_VIEW.value),
    ]

    def get_queryset(self):
        qs = super().get_queryset()
        branch_id = self.request.query_params.get('branch_id')
        product_id = self.request.query_params.get('product_id')
        batch_id = self.request.query_params.get('batch_id')
        if branch_id:
            qs = qs.filter(branch_id=branch_id)
        if product_id:
            qs = qs.filter(batch__product_id=product_id)
        if batch_id:
            qs = qs.filter(batch_id=batch_id)
        return qs


class InventoryMovementViewSet(OrganizationQuerysetMixin, viewsets.ReadOnlyModelViewSet):
    """Read-only endpoint for immutable InventoryMovement records."""

    queryset = InventoryMovement.objects.all()
    serializer_class = InventoryMovementSerializer
    permission_classes = [
        IsAuthenticated,
        IsOrganizationMember,
        require_permission(read_perm=PermissionCode.INVENTORY_VIEW.value),
    ]

    def get_queryset(self):
        qs = super().get_queryset()
        branch_id = self.request.query_params.get('branch_id')
        batch_id = self.request.query_params.get('batch_id')
        if branch_id:
            qs = qs.filter(branch_id=branch_id)
        if batch_id:
            qs = qs.filter(batch_id=batch_id)
        return qs


class InventoryAlertViewSet(OrganizationQuerysetMixin, viewsets.ModelViewSet):
    queryset = InventoryAlert.objects.all()
    serializer_class = InventoryAlertSerializer
    permission_classes = [
        IsAuthenticated,
        IsOrganizationMember,
        require_permission(
            read_perm=PermissionCode.INVENTORY_VIEW.value,
            write_perm=PermissionCode.INVENTORY_ADJUST.value,
        ),
    ]

    @action(detail=True, methods=['post'])
    def resolve(self, request, pk=None):
        alert = self.get_object()
        alert.is_resolved = True
        alert.resolved_by = request.user
        alert.resolved_at = timezone.now()
        alert.save(update_fields=['is_resolved', 'resolved_by', 'resolved_at'])
        return Response(InventoryAlertSerializer(alert).data)


class OpeningBalanceView(views.APIView):
    """
    One-time Opening Balance loader per branch (Architecture Plan §3.6).
    Creates OPENING_BALANCE movements and sets Branch.initial_stock_loaded = True.
    """

    permission_classes = [
        IsAuthenticated,
        IsOrganizationMember,
        require_permission(write_perm=PermissionCode.INVENTORY_ADJUST.value),
    ]

    def post(self, request):
        serializer = OpeningBalanceRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        org_id = request.user.organization_id
        branch = get_object_or_404(
            Branch,
            id=serializer.validated_data['branch_id'],
            organization_id=org_id,
        )
        if branch.initial_stock_loaded:
            raise DRFValidationError(
                "Opening balance has already been loaded for this branch."
            )

        entries = serializer.validated_data['entries']
        created_movements = []
        with transaction.atomic():
            for entry in entries:
                batch = get_object_or_404(
                    Batch, id=entry['batch_id'], organization_id=org_id
                )
                storage_loc_id = entry.get('storage_location_id')
                if storage_loc_id and not branch.uses_storage_locations:
                    raise DRFValidationError(
                        "This branch does not have storage locations enabled."
                    )
                inv, mov = apply_inventory_movement(
                    organization_id=org_id,
                    branch_id=branch.id,
                    batch_id=batch.id,
                    storage_location_id=storage_loc_id,
                    movement_type=MovementType.OPENING_BALANCE.value,
                    quantity_change=entry['quantity'],
                    reference_type='opening_balance',
                    reference_id=branch.id,
                    user=request.user,
                    notes="Initial opening balance load",
                )
                if entry.get('reorder_level') is not None:
                    inv.reorder_level = entry['reorder_level']
                    inv.save(update_fields=['reorder_level'])
                created_movements.append(mov)

            branch.initial_stock_loaded = True
            branch.save(update_fields=['initial_stock_loaded', 'updated_at'])

            now = timezone.now()
            AuditEvent.objects.create(
                organization_id=org_id,
                branch_id=branch.id,
                user_id=request.user.id,
                action=AuditAction.INVENTORY_ADJUSTED.value,
                entity_type='branch',
                entity_id=branch.id,
                data_after={"initial_stock_loaded": True, "entries_count": len(entries)},
                reason="Opening balance loaded",
                local_timestamp=now,
                server_timestamp=now,
                is_offline=False,
                source=AuditSource.SERVER.value,
            )

        return Response(
            {
                "branch_id": str(branch.id),
                "initial_stock_loaded": True,
                "movements_created": len(created_movements),
            },
            status=status.HTTP_201_CREATED,
        )


class StockAdjustmentView(views.APIView):
    permission_classes = [
        IsAuthenticated,
        IsOrganizationMember,
        require_permission(write_perm=PermissionCode.INVENTORY_ADJUST.value),
    ]

    def post(self, request):
        serializer = StockAdjustmentRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        org_id = request.user.organization_id

        branch = get_object_or_404(Branch, id=data['branch_id'], organization_id=org_id)
        batch = get_object_or_404(Batch, id=data['batch_id'], organization_id=org_id)

        inv, mov = apply_inventory_movement(
            organization_id=org_id,
            branch_id=branch.id,
            batch_id=batch.id,
            storage_location_id=data.get('storage_location_id'),
            movement_type=data['movement_type'],
            quantity_change=data['quantity_change'],
            reference_type='stock_adjustment',
            reference_id=uuid.uuid4(),
            user=request.user,
            notes=data['notes'],
            allow_negative=False,
        )
        now = timezone.now()
        AuditEvent.objects.create(
            organization_id=org_id,
            branch_id=branch.id,
            user_id=request.user.id,
            action=AuditAction.INVENTORY_ADJUSTED.value,
            entity_type='branch_inventory',
            entity_id=inv.id,
            data_before={"quantity": mov.quantity_before},
            data_after={"quantity": mov.quantity_after, "movement_type": mov.movement_type},
            reason=data['notes'],
            local_timestamp=now,
            server_timestamp=now,
            is_offline=False,
            source=AuditSource.SERVER.value,
        )
        return Response(BranchInventorySerializer(inv).data, status=status.HTTP_200_OK)


class StockCountViewSet(OrganizationQuerysetMixin, viewsets.ModelViewSet):
    """
    Stock Count and Approval ViewSet (Architecture Plan §9).
    """
    queryset = StockCount.objects.select_related(
        'branch', 'device', 'storage_location', 'started_by'
    ).prefetch_related('items__product', 'items__batch')
    serializer_class = StockCountSerializer
    permission_classes = [IsAuthenticated, IsOrganizationMember]

    def create(self, request, *args, **kwargs):
        ser = StartStockCountRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        org_id = request.user.organization_id

        branch = get_object_or_404(Branch, id=data['branch_id'], organization_id=org_id)
        storage_loc = None
        if data.get('storage_location_id'):
            storage_loc = get_object_or_404(
                StorageLocation, id=data['storage_location_id'], organization_id=org_id
            )

        # Multi-device local conflict check: only one IN_PROGRESS or DRAFT count per scope
        scope_q = StockCount.objects.filter(
            organization_id=org_id,
            branch=branch,
            status__in=['DRAFT', 'IN_PROGRESS'],
        )
        if storage_loc:
            scope_q = scope_q.filter(storage_location=storage_loc)
        if scope_q.exists():
            return Response(
                {
                    "error": {
                        "code": "count_already_in_progress",
                        "message": "A stock count is already in progress for this scope.",
                    }
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        now = timezone.now()
        corr_id = uuid.uuid4()
        with transaction.atomic():
            stock_count = StockCount.objects.create(
                organization_id=org_id,
                branch=branch,
                device_id=data.get('device_id'),
                storage_location=storage_loc,
                count_type=data.get('count_type', 'FULL_BRANCH'),
                status='IN_PROGRESS',
                started_by=request.user,
                started_at=now,
                notes=data.get('notes', ''),
            )
            AuditEvent.objects.create(
                organization_id=org_id,
                branch_id=branch.id,
                user_id=request.user.id,
                action=AuditAction.STOCK_COUNT_STARTED.value,
                entity_type='stock_count',
                entity_id=stock_count.id,
                correlation_id=corr_id,
                transaction_id=stock_count.id,
                local_timestamp=now,
                server_timestamp=now,
                is_offline=False,
                source=AuditSource.SERVER.value,
            )

        return Response(StockCountSerializer(stock_count).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'], url_path='submit')
    def submit(self, request, pk=None):
        stock_count = self.get_object()
        if stock_count.status != 'IN_PROGRESS':
            return Response(
                {
                    "error": {
                        "code": "invalid_status",
                        "message": f"Cannot submit a count in status {stock_count.status}.",
                    }
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        ser = SubmitStockCountRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        org_id = request.user.organization_id
        now = timezone.now()
        corr_id = uuid.uuid4()

        with transaction.atomic():
            stock_count = StockCount.objects.select_for_update().get(pk=stock_count.pk)
            stock_count.items.all().delete()

            for item_in in data['items']:
                batch = get_object_or_404(Batch, id=item_in['batch_id'], organization_id=org_id)
                loc_id = item_in.get('storage_location_id') or (
                    stock_count.storage_location_id if stock_count.storage_location else None
                )
                inv = BranchInventory.objects.filter(
                    organization_id=org_id,
                    branch=stock_count.branch,
                    batch=batch,
                    storage_location_id=loc_id,
                ).first()
                sys_qty = inv.quantity if inv else 0
                cnt_qty = int(item_in['counted_quantity'])
                variance = cnt_qty - sys_qty

                StockCountItem.objects.create(
                    stock_count=stock_count,
                    product=batch.product,
                    batch=batch,
                    storage_location_id=loc_id,
                    system_quantity=sys_qty,
                    counted_quantity=cnt_qty,
                    variance=variance,
                    approval_status='PENDING',
                )

            stock_count.status = 'SUBMITTED'
            stock_count.submitted_by = request.user
            stock_count.submitted_at = now
            if data.get('notes'):
                stock_count.notes = data['notes']
            stock_count.save()

            AuditEvent.objects.create(
                organization_id=org_id,
                branch_id=stock_count.branch_id,
                user_id=request.user.id,
                action=AuditAction.STOCK_COUNT_SUBMITTED.value,
                entity_type='stock_count',
                entity_id=stock_count.id,
                correlation_id=corr_id,
                transaction_id=stock_count.id,
                local_timestamp=now,
                server_timestamp=now,
                is_offline=False,
                source=AuditSource.SERVER.value,
            )

        return Response(StockCountSerializer(stock_count).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], url_path='approve')
    def approve(self, request, pk=None):
        stock_count = self.get_object()
        if stock_count.status != 'SUBMITTED':
            return Response(
                {
                    "error": {
                        "code": "invalid_status",
                        "message": f"Cannot approve a count in status {stock_count.status}.",
                    }
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        ser = ApproveStockCountRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        org_id = request.user.organization_id
        now = timezone.now()
        corr_id = uuid.uuid4()

        with transaction.atomic():
            stock_count = StockCount.objects.select_for_update().get(pk=stock_count.pk)
            items_map = {
                item.id: item
                for item in StockCountItem.objects.select_for_update().filter(stock_count=stock_count)
            }

            for rev in data['items']:
                item_id = rev['stock_count_item_id']
                if item_id not in items_map:
                    return Response(
                        {
                            "error": {
                                "code": "invalid_item",
                                "message": f"Item {item_id} does not belong to this count.",
                            }
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                item = items_map[item_id]
                action_type = rev['action']

                if action_type == 'APPROVE':
                    inv = BranchInventory.objects.select_for_update().filter(
                        organization_id=org_id,
                        branch=stock_count.branch,
                        batch=item.batch,
                        storage_location=item.storage_location,
                    ).first()
                    curr_qty = inv.quantity if inv else 0
                    # Negative Quantity Guard (Architecture Plan §9.2)
                    if curr_qty + item.variance < 0:
                        return Response(
                            {
                                "error": {
                                    "code": "negative_stock_guard",
                                    "message": f"Approval blocked: live quantity ({curr_qty}) + variance ({item.variance}) < 0 for batch {item.batch.batch_number}.",
                                }
                            },
                            status=status.HTTP_400_BAD_REQUEST,
                        )

                    item.current_quantity_at_approval = curr_qty
                    item.approval_status = 'APPROVED'
                    item.save()

                    if item.variance != 0:
                        apply_inventory_movement(
                            organization_id=org_id,
                            branch_id=stock_count.branch_id,
                            batch_id=item.batch_id,
                            storage_location_id=item.storage_location_id,
                            movement_type=MovementType.COUNT_VARIANCE.value,
                            quantity_change=item.variance,
                            reference_type='stock_count',
                            reference_id=stock_count.id,
                            user=request.user,
                            notes=f"Stock count variance: {item.variance}",
                            allow_negative=False,
                        )
                else:
                    item.approval_status = 'REJECTED'
                    item.rejection_reason = rev.get('rejection_reason', 'Rejected by reviewer')
                    item.save()

            all_items = list(items_map.values())
            approved_count = sum(1 for i in all_items if i.approval_status == 'APPROVED')
            rejected_count = sum(1 for i in all_items if i.approval_status == 'REJECTED')

            if approved_count == len(all_items):
                stock_count.status = 'APPROVED'
            elif rejected_count == len(all_items):
                stock_count.status = 'REJECTED'
            else:
                stock_count.status = 'PARTIALLY_APPROVED'

            stock_count.approved_by = request.user
            stock_count.approved_at = now
            if data.get('notes'):
                stock_count.notes = (stock_count.notes + "\n" + data['notes']).strip()
            stock_count.save()

            action_name = (
                AuditAction.STOCK_COUNT_APPROVED.value
                if stock_count.status in ('APPROVED', 'PARTIALLY_APPROVED')
                else AuditAction.STOCK_COUNT_REJECTED.value
            )
            AuditEvent.objects.create(
                organization_id=org_id,
                branch_id=stock_count.branch_id,
                user_id=request.user.id,
                action=action_name,
                entity_type='stock_count',
                entity_id=stock_count.id,
                data_after={
                    "status": stock_count.status,
                    "approved_count": approved_count,
                    "rejected_count": rejected_count,
                },
                correlation_id=corr_id,
                transaction_id=stock_count.id,
                local_timestamp=now,
                server_timestamp=now,
                is_offline=False,
                source=AuditSource.SERVER.value,
            )

        return Response(StockCountSerializer(stock_count).data, status=status.HTTP_200_OK)

