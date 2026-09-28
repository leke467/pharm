import uuid
from django.utils import timezone
from rest_framework import viewsets, mixins
from rest_framework.permissions import IsAuthenticated
from apps.audit.models import AuditEvent
from apps.core.permissions import IsOrganizationMember, require_permission
from shared.enums import PermissionCode, AuditAction, AuditSource
from .serializers import OrganizationSerializer, OrganizationUpdateSerializer


class OrganizationViewSet(
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = [
        IsAuthenticated,
        IsOrganizationMember,
        require_permission(write_perm=PermissionCode.SETTINGS_MANAGE.value),
    ]

    def get_serializer_class(self):
        if self.action in ['update', 'partial_update']:
            return OrganizationUpdateSerializer
        return OrganizationSerializer

    def get_object(self):
        return self.request.user.organization

    def perform_update(self, serializer):
        org = self.get_object()
        before_data = OrganizationSerializer(org).data
        instance = serializer.save()
        after_data = OrganizationSerializer(instance).data
        now = timezone.now()
        AuditEvent.objects.create(
            organization=instance,
            branch_id=self.request.user.default_branch_id or uuid.UUID(int=0),
            user_id=self.request.user.id,
            action=AuditAction.SETTINGS_CHANGED.value,
            entity_type='organization',
            entity_id=instance.id,
            data_before=before_data,
            data_after=after_data,
            local_timestamp=now,
            server_timestamp=now,
            is_offline=False,
            source=AuditSource.SERVER.value,
        )
