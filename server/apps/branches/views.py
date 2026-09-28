from django.shortcuts import get_object_or_404
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from apps.core.mixins import OrganizationQuerysetMixin
from apps.core.permissions import IsOrganizationMember, require_permission
from shared.enums import PermissionCode
from .models import Branch, Device
from .serializers import (
    BranchSerializer,
    BranchCreateSerializer,
    DeviceSerializer,
    DeviceRegisterSerializer,
)


class BranchViewSet(OrganizationQuerysetMixin, viewsets.ModelViewSet):
    queryset = Branch.objects.all()
    permission_classes = [
        IsAuthenticated,
        IsOrganizationMember,
        require_permission(write_perm=PermissionCode.BRANCHES_MANAGE.value),
    ]

    def get_serializer_class(self):
        if self.action == 'create':
            return BranchCreateSerializer
        return BranchSerializer


class DeviceViewSet(OrganizationQuerysetMixin, viewsets.ModelViewSet):
    queryset = Device.objects.all()
    permission_classes = [
        IsAuthenticated,
        IsOrganizationMember,
        require_permission(write_perm=PermissionCode.BRANCHES_MANAGE.value),
    ]

    def get_serializer_class(self):
        if self.action == 'create':
            return DeviceRegisterSerializer
        return DeviceSerializer

    def perform_create(self, serializer):
        org_id = self.get_organization_id()
        branch = get_object_or_404(
            Branch,
            id=serializer.validated_data['branch_id'],
            organization_id=org_id,
        )
        serializer.save(organization_id=org_id, branch=branch)
