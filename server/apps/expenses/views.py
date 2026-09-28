import uuid
from datetime import timedelta
from django.db import transaction
from django.utils import timezone
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError, PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.mixins import OrganizationQuerysetMixin
from apps.core.permissions import IsOrganizationMember, require_permission
from apps.audit.models import AuditEvent
from apps.sync.models import SyncDelivery
from shared.enums import (
    ExpenseStatus,
    PermissionCode,
    AuditAction,
    AuditSource,
    SyncTargetScope,
    SyncOperation,
)
from .models import ExpenseCategory, Expense
from .serializers import ExpenseCategorySerializer, ExpenseSerializer


def queue_expense_sync_delivery(expense: Expense, operation: str = SyncOperation.CREATE.value):
    payload = {
        'id': str(expense.id),
        'organization_id': str(expense.organization_id),
        'branch_id': str(expense.branch_id),
        'expense_category_id': str(expense.expense_category_id),
        'description': expense.description,
        'amount': str(expense.amount),
        'payment_method': expense.payment_method,
        'expense_date': expense.expense_date.isoformat(),
        'created_by_id': str(expense.created_by_id),
        'approved_by_id': str(expense.approved_by_id) if expense.approved_by_id else None,
        'status': expense.status,
        'attachment_path': expense.attachment_path,
        'notes': expense.notes,
        'created_at': expense.created_at.isoformat(),
        'updated_at': expense.updated_at.isoformat(),
    }
    expires_at = timezone.now() + timedelta(days=90)
    SyncDelivery.objects.create(
        organization=expense.organization,
        entity_type='expense',
        entity_id=expense.id,
        operation=operation,
        payload=payload,
        target_scope=SyncTargetScope.SPECIFIC_BRANCH.value,
        target_branch_id=expense.branch_id,
        source_branch_id=expense.branch_id,
        expires_at=expires_at,
    )


class ExpenseCategoryViewSet(OrganizationQuerysetMixin, viewsets.ModelViewSet):
    queryset = ExpenseCategory.objects.all()
    serializer_class = ExpenseCategorySerializer
    permission_classes = [IsAuthenticated, IsOrganizationMember]

    def get_queryset(self):
        qs = super().get_queryset()
        active_only = self.request.query_params.get('active_only', 'false').lower() == 'true'
        if active_only:
            qs = qs.filter(is_active=True)
        return qs

    def perform_create(self, serializer):
        cat = serializer.save(organization_id=self.get_organization_id())
        expires_at = timezone.now() + timedelta(days=90)
        SyncDelivery.objects.create(
            organization=cat.organization,
            entity_type='expense_category',
            entity_id=cat.id,
            operation=SyncOperation.CREATE.value,
            payload={
                'id': str(cat.id),
                'organization_id': str(cat.organization_id),
                'name': cat.name,
                'description': cat.description,
                'is_active': cat.is_active,
            },
            target_scope=SyncTargetScope.ALL_BRANCHES.value,
            expires_at=expires_at,
        )


class ExpenseViewSet(OrganizationQuerysetMixin, viewsets.ModelViewSet):
    queryset = Expense.objects.select_related(
        'branch', 'expense_category', 'created_by', 'approved_by'
    ).all()
    serializer_class = ExpenseSerializer
    permission_classes = [IsAuthenticated, IsOrganizationMember]

    def get_queryset(self):
        qs = super().get_queryset()
        branch_id = self.request.query_params.get('branch_id')
        status_param = self.request.query_params.get('status')
        if branch_id:
            qs = qs.filter(branch_id=branch_id)
        if status_param:
            qs = qs.filter(status=status_param)
        return qs

    def perform_create(self, serializer):
        org_id = self.get_organization_id()
        branch = serializer.validated_data['branch']
        if branch.organization_id != org_id:
            raise ValidationError("Branch must belong to your organization.")

        category = serializer.validated_data['expense_category']
        if category.organization_id != org_id:
            raise ValidationError("Expense category must belong to your organization.")

        with transaction.atomic():
            expense = serializer.save(
                organization_id=org_id,
                created_by=self.request.user,
                status=ExpenseStatus.PENDING_APPROVAL.value,
            )

            AuditEvent.objects.create(
                organization_id=org_id,
                branch_id=branch.id,
                user_id=self.request.user.id,
                action=AuditAction.EXPENSE_CREATED.value,
                entity_type='expense',
                entity_id=expense.id,
                data_after=ExpenseSerializer(expense).data,
                local_timestamp=timezone.now(),
                server_timestamp=timezone.now(),
                source=AuditSource.SERVER.value,
            )

            queue_expense_sync_delivery(expense, SyncOperation.CREATE.value)

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        expense = self.get_object()
        if expense.status not in [ExpenseStatus.DRAFT.value, ExpenseStatus.PENDING_APPROVAL.value]:
            raise ValidationError(f"Expense cannot be approved from status {expense.status}.")

        with transaction.atomic():
            expense.status = ExpenseStatus.APPROVED.value
            expense.approved_by = request.user
            expense.save(update_fields=['status', 'approved_by', 'updated_at'])

            AuditEvent.objects.create(
                organization_id=expense.organization_id,
                branch_id=expense.branch_id,
                user_id=request.user.id,
                action=AuditAction.EXPENSE_APPROVED.value,
                entity_type='expense',
                entity_id=expense.id,
                data_after={'status': expense.status, 'approved_by': str(request.user.id)},
                local_timestamp=timezone.now(),
                server_timestamp=timezone.now(),
                source=AuditSource.SERVER.value,
            )

            queue_expense_sync_delivery(expense, SyncOperation.UPDATE.value)

        return Response(self.get_serializer(expense).data)

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        expense = self.get_object()
        if expense.status not in [ExpenseStatus.DRAFT.value, ExpenseStatus.PENDING_APPROVAL.value]:
            raise ValidationError(f"Expense cannot be rejected from status {expense.status}.")

        with transaction.atomic():
            expense.status = ExpenseStatus.REJECTED.value
            expense.save(update_fields=['status', 'updated_at'])

            AuditEvent.objects.create(
                organization_id=expense.organization_id,
                branch_id=expense.branch_id,
                user_id=request.user.id,
                action=AuditAction.EXPENSE_REJECTED.value,
                entity_type='expense',
                entity_id=expense.id,
                data_after={'status': expense.status},
                local_timestamp=timezone.now(),
                server_timestamp=timezone.now(),
                source=AuditSource.SERVER.value,
            )

            queue_expense_sync_delivery(expense, SyncOperation.UPDATE.value)

        return Response(self.get_serializer(expense).data)
