from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from apps.core.mixins import OrganizationQuerysetMixin
from apps.core.permissions import IsOrganizationMember, require_permission
from shared.enums import PermissionCode
from .models import AuditEvent
from .serializers import AuditEventSerializer


class AuditEventViewSet(OrganizationQuerysetMixin, viewsets.ReadOnlyModelViewSet):
    """
    Read-only, paginated, and filterable endpoint for audit events (Architecture Plan §6, §13).
    Strictly forbids modifications and deletions.
    """

    queryset = AuditEvent.objects.all()
    serializer_class = AuditEventSerializer
    permission_classes = [
        IsAuthenticated,
        IsOrganizationMember,
        require_permission(read_perm=PermissionCode.AUDIT_VIEW.value),
    ]

    def get_queryset(self):
        qs = super().get_queryset()
        params = self.request.query_params

        branch_id = params.get('branch_id')
        if branch_id:
            qs = qs.filter(branch_id=branch_id)

        user_id = params.get('user_id')
        if user_id:
            qs = qs.filter(user_id=user_id)

        device_id = params.get('device_id')
        if device_id:
            qs = qs.filter(device_id=device_id)

        action = params.get('action')
        if action:
            qs = qs.filter(action=action)

        entity_type = params.get('entity_type')
        if entity_type:
            qs = qs.filter(entity_type=entity_type)

        entity_id = params.get('entity_id')
        if entity_id:
            qs = qs.filter(entity_id=entity_id)

        source = params.get('source')
        if source:
            qs = qs.filter(source=source)

        transaction_id = params.get('transaction_id')
        if transaction_id:
            qs = qs.filter(transaction_id=transaction_id)

        correlation_id = params.get('correlation_id')
        if correlation_id:
            qs = qs.filter(correlation_id=correlation_id)

        start_date = params.get('start_date')
        if start_date:
            qs = qs.filter(created_at__gte=start_date)

        end_date = params.get('end_date')
        if end_date:
            qs = qs.filter(created_at__lte=end_date)

        return qs.order_by('-created_at')
