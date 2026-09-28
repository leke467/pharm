import uuid
from datetime import timedelta
from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.audit.models import AuditEvent
from apps.sync.models import SyncDelivery
from apps.core.mixins import OrganizationQuerysetMixin
from apps.core.permissions import IsOrganizationMember, require_permission
from shared.enums import (
    PermissionCode,
    AuditAction,
    AuditSource,
    SyncTargetScope,
    SyncOperation,
)
from .models import Price, PriceHistory
from .serializers import PriceSerializer, PriceHistorySerializer


def queue_price_sync_delivery(price: Price, operation: str = SyncOperation.CREATE.value):
    """Queues a SyncDelivery for price updates across branches."""
    payload = {
        'id': str(price.id),
        'organization_id': str(price.organization_id),
        'product_id': str(price.product_id),
        'branch_id': str(price.branch_id) if price.branch_id else None,
        'selling_price': str(price.selling_price),
        'currency': price.currency,
        'is_current': price.is_current,
        'version': price.version,
        'effective_from': price.effective_from.isoformat() if price.effective_from else None,
        'effective_to': price.effective_to.isoformat() if price.effective_to else None,
        'sync_status': price.sync_status,
        'created_at': price.created_at.isoformat(),
        'updated_at': price.updated_at.isoformat(),
    }
    expires_at = timezone.now() + timedelta(days=90)
    target_scope = SyncTargetScope.ALL_BRANCHES.value

    SyncDelivery.objects.create(
        organization=price.organization,
        entity_type='price',
        entity_id=price.id,
        operation=operation,
        payload=payload,
        target_scope=target_scope,
        target_branch_id=None,
        expires_at=expires_at,
    )


def resolve_product_price(organization_id, product_id, branch_id=None) -> Price | None:
    """
    Resolves the active selling price for a product in a branch:
    1. Branch-specific override (`branch_id = branch_id AND is_current = True`)
    2. Organization-wide default (`branch__isnull = True AND is_current = True`)
    """
    if branch_id:
        branch_price = Price.objects.filter(
            organization_id=organization_id,
            product_id=product_id,
            branch_id=branch_id,
            is_current=True,
        ).first()
        if branch_price:
            return branch_price

    return Price.objects.filter(
        organization_id=organization_id,
        product_id=product_id,
        branch__isnull=True,
        is_current=True,
    ).first()


class PriceViewSet(OrganizationQuerysetMixin, viewsets.ModelViewSet):
    queryset = Price.objects.select_related('product', 'branch').all()
    serializer_class = PriceSerializer
    permission_classes = [
        IsAuthenticated,
        IsOrganizationMember,
        require_permission(
            read_perm=PermissionCode.PRICES_VIEW.value,
            write_perm=PermissionCode.PRICES_MANAGE.value,
        ),
    ]

    def get_queryset(self):
        qs = super().get_queryset()
        product_id = self.request.query_params.get('product_id')
        branch_id = self.request.query_params.get('branch_id')
        current_only = self.request.query_params.get('current_only', 'true').lower() == 'true'
        if product_id:
            qs = qs.filter(product_id=product_id)
        if branch_id:
            qs = qs.filter(branch_id=branch_id)
        if current_only and self.action == 'list':
            qs = qs.filter(is_current=True)
        return qs

    def perform_create(self, serializer):
        org_id = self.get_organization_id()
        product = serializer.validated_data['product']
        branch = serializer.validated_data.get('branch')
        force_all_branches = serializer.validated_data.get('force_all_branches', False)
        change_reason = serializer.validated_data.get('change_reason', '')

        if product.organization_id != org_id:
            raise DRFValidationError("Product must belong to your organization.")
        if branch and branch.organization_id != org_id:
            raise DRFValidationError("Branch must belong to your organization.")

        now = timezone.now()
        with transaction.atomic():
            previous = (
                Price.objects.select_for_update()
                .filter(
                    organization_id=org_id,
                    product=product,
                    branch=branch,
                    is_current=True,
                )
                .first()
            )
            next_version = 1
            before_price_val = None
            if previous:
                next_version = previous.version + 1
                before_price_val = str(previous.selling_price)
                previous.is_current = False
                previous.effective_to = now
                previous.save(update_fields=['is_current', 'effective_to', 'updated_at'])

            org_settings = self.request.user.organization.settings or {}
            currency = serializer.validated_data.get('currency') or org_settings.get(
                'default_currency', 'NGN'
            )

            new_price = serializer.save(
                organization_id=org_id,
                currency=currency,
                is_current=True,
                version=next_version,
                created_by=self.request.user,
            )

            # Create immutable PriceHistory
            PriceHistory.objects.create(
                organization=new_price.organization,
                price=new_price,
                product=product,
                branch=branch,
                old_price=Decimal(before_price_val) if before_price_val else None,
                new_price=new_price.selling_price,
                changed_by=self.request.user,
                change_reason=change_reason,
                version=next_version,
                local_timestamp=now,
                server_timestamp=now,
                sync_status='SYNCED',
            )

            # Force all branches: retire branch overrides if this is an org default price
            if force_all_branches and branch is None:
                branch_overrides = Price.objects.select_for_update().filter(
                    organization_id=org_id,
                    product=product,
                    branch__isnull=False,
                    is_current=True,
                )
                for bo in branch_overrides:
                    bo_old_price = bo.selling_price
                    bo.is_current = False
                    bo.effective_to = now
                    bo.save(update_fields=['is_current', 'effective_to', 'updated_at'])

                    PriceHistory.objects.create(
                        organization=new_price.organization,
                        price=bo,
                        product=product,
                        branch=bo.branch,
                        old_price=bo_old_price,
                        new_price=new_price.selling_price,
                        changed_by=self.request.user,
                        change_reason=f"Forced update from org default price: {change_reason}".strip(),
                        version=bo.version + 1,
                        local_timestamp=now,
                        server_timestamp=now,
                        sync_status='SYNCED',
                    )

            AuditEvent.objects.create(
                organization_id=org_id,
                branch_id=branch.id if branch else (self.request.user.default_branch_id or uuid.UUID(int=0)),
                user_id=self.request.user.id,
                action=AuditAction.PRICE_CHANGED.value,
                entity_type='price',
                entity_id=new_price.id,
                data_before={"selling_price": before_price_val} if before_price_val else None,
                data_after=PriceSerializer(new_price).data,
                local_timestamp=now,
                server_timestamp=now,
                is_offline=False,
                source=AuditSource.SERVER.value,
            )

            queue_price_sync_delivery(new_price, SyncOperation.CREATE.value)

    @action(detail=False, methods=['get'])
    def resolve(self, request):
        product_id = request.query_params.get('product_id')
        branch_id = request.query_params.get('branch_id')
        if not product_id:
            raise DRFValidationError({"product_id": "This query parameter is required."})

        org_id = self.get_organization_id()
        price = resolve_product_price(org_id, product_id, branch_id=branch_id)
        if not price:
            return Response(
                {"detail": "No active price found for this product."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(PriceSerializer(price).data)

    @action(detail=True, methods=['get'])
    def history(self, request, pk=None):
        price = self.get_object()
        histories = PriceHistory.objects.filter(
            organization_id=self.get_organization_id(),
            product_id=price.product_id,
        ).order_by('-version', '-created_at')
        return Response(PriceHistorySerializer(histories, many=True).data)

    @action(detail=True, methods=['post'], url_path='force-all-branches')
    def force_all_branches(self, request, pk=None):
        price = self.get_object()
        if price.branch is not None:
            raise DRFValidationError("Cannot force branch-specific price across all branches. Must be organization default.")

        now = timezone.now()
        org_id = self.get_organization_id()
        change_reason = request.data.get('change_reason', 'Forced all branches sync')

        with transaction.atomic():
            branch_overrides = Price.objects.select_for_update().filter(
                organization_id=org_id,
                product=price.product,
                branch__isnull=False,
                is_current=True,
            )
            retired_count = 0
            for bo in branch_overrides:
                bo_old_price = bo.selling_price
                bo.is_current = False
                bo.effective_to = now
                bo.save(update_fields=['is_current', 'effective_to', 'updated_at'])

                PriceHistory.objects.create(
                    organization=price.organization,
                    price=bo,
                    product=price.product,
                    branch=bo.branch,
                    old_price=bo_old_price,
                    new_price=price.selling_price,
                    changed_by=request.user,
                    change_reason=change_reason,
                    version=bo.version + 1,
                    local_timestamp=now,
                    server_timestamp=now,
                    sync_status='SYNCED',
                )
                retired_count += 1

            queue_price_sync_delivery(price, SyncOperation.UPDATE.value)

            AuditEvent.objects.create(
                organization_id=org_id,
                branch_id=self.request.user.default_branch_id or uuid.UUID(int=0),
                user_id=request.user.id,
                action=AuditAction.PRICE_CHANGED.value,
                entity_type='price',
                entity_id=price.id,
                data_after={"action": "force_all_branches", "overrides_retired": retired_count},
                local_timestamp=now,
                server_timestamp=now,
                is_offline=False,
                source=AuditSource.SERVER.value,
            )

        return Response({
            "status": "success",
            "message": f"Forced price across all branches. {retired_count} branch override(s) retired.",
            "price": PriceSerializer(price).data,
        })


class PriceHistoryViewSet(OrganizationQuerysetMixin, viewsets.ReadOnlyModelViewSet):
    """
    Read-only audit view for immutable price histories.
    """
    queryset = PriceHistory.objects.select_related('product', 'branch', 'changed_by').all()
    serializer_class = PriceHistorySerializer
    permission_classes = [
        IsAuthenticated,
        IsOrganizationMember,
        require_permission(read_perm=PermissionCode.PRICES_VIEW.value),
    ]

    def get_queryset(self):
        qs = super().get_queryset()
        product_id = self.request.query_params.get('product_id')
        branch_id = self.request.query_params.get('branch_id')
        if product_id:
            qs = qs.filter(product_id=product_id)
        if branch_id:
            qs = qs.filter(branch_id=branch_id)
        return qs
