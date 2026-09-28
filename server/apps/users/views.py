import uuid
from django.contrib.auth import authenticate
from django.utils import timezone
from rest_framework import viewsets, views, status
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenRefreshView as BaseTokenRefreshView

from apps.audit.models import AuditEvent
from apps.branches.models import Branch, Device
from apps.branches.serializers import BranchSerializer
from apps.core.mixins import OrganizationQuerysetMixin
from apps.core.permissions import IsOrganizationMember, require_permission
from apps.organizations.models import Organization
from apps.organizations.serializers import OrganizationSerializer
from shared.enums import PermissionCode, AuditAction, AuditSource
from .models import User, Role, Permission, UserRole, RolePermission
from .serializers import (
    LoginSerializer,
    UserSerializer,
    UserCreateSerializer,
    RoleSerializer,
    PermissionSerializer,
    UserRoleSerializer,
    TokenRefreshSerializer,
)


class LoginView(views.APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        org_code = serializer.validated_data['org_code']
        try:
            org = Organization.objects.get(code=org_code, is_active=True)
        except Organization.DoesNotExist:
            return Response(
                {"detail": "Invalid organization code."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        username = serializer.validated_data['username']
        password = serializer.validated_data['password']

        user = authenticate(
            request,
            username=username,
            password=password,
            organization_id=org.id,
        )
        if not user or user.organization_id != org.id or not user.is_active:
            return Response(
                {"detail": "Invalid credentials."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        branch_id = serializer.validated_data.get('branch_id')
        device_id = serializer.validated_data.get('device_id')
        active_branch = None
        if branch_id:
            active_branch = Branch.objects.filter(
                id=branch_id,
                organization_id=org.id,
                is_active=True,
            ).first()
        elif user.default_branch_id:
            active_branch = user.default_branch
        else:
            active_branch = Branch.objects.filter(
                organization_id=org.id,
                is_active=True,
            ).first()

        if device_id:
            Device.objects.filter(id=device_id, organization_id=org.id).update(
                last_seen_at=timezone.now()
            )

        # Resolve user roles and permission codes
        active_user_roles = user.userrole_set.filter(is_active=True, role__is_active=True)
        if active_branch:
            scoped_user_roles = (
                active_user_roles.filter(branch_id=active_branch.id)
                | active_user_roles.filter(branch__isnull=True)
            )
        else:
            scoped_user_roles = active_user_roles

        role_ids = list(scoped_user_roles.values_list('role_id', flat=True))
        if user.is_org_admin:
            permission_codes = list(
                Permission.objects.values_list('code', flat=True)
            )
            if not permission_codes:
                permission_codes = [p.value for p in PermissionCode]
        else:
            permission_codes = list(
                RolePermission.objects.filter(role_id__in=role_ids)
                .values_list('permission__code', flat=True)
                .distinct()
            )

        now = timezone.now()
        AuditEvent.objects.create(
            organization=org,
            branch_id=active_branch.id if active_branch else uuid.UUID(int=0),
            user_id=user.id,
            device_id=device_id,
            action=AuditAction.USER_LOGIN.value,
            entity_type='user',
            entity_id=user.id,
            data_after={"username": user.username, "branch_id": str(active_branch.id) if active_branch else None},
            local_timestamp=now,
            server_timestamp=now,
            is_offline=False,
            source=AuditSource.SERVER.value,
        )

        refresh = RefreshToken.for_user(user)
        user_data = UserSerializer(user).data

        return Response({
            "access_token": str(refresh.access_token),
            "refresh_token": str(refresh),
            "user": user_data,
            "roles": UserRoleSerializer(scoped_user_roles, many=True).data,
            "permissions": permission_codes,
            "branch": BranchSerializer(active_branch).data if active_branch else None,
            "org": OrganizationSerializer(org).data,
        })


class TokenRefreshView(BaseTokenRefreshView):
    serializer_class = TokenRefreshSerializer


class CurrentUserView(views.APIView):
    permission_classes = [IsAuthenticated, IsOrganizationMember]

    def get(self, request):
        return Response(UserSerializer(request.user).data)


class LogoutView(views.APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            refresh_token = request.data["refresh_token"]
            token = RefreshToken(refresh_token)
            token.blacklist()
            now = timezone.now()
            if getattr(request.user, 'organization_id', None):
                AuditEvent.objects.create(
                    organization_id=request.user.organization_id,
                    branch_id=request.user.default_branch_id or uuid.UUID(int=0),
                    user_id=request.user.id,
                    action=AuditAction.USER_LOGOUT.value,
                    entity_type='user',
                    entity_id=request.user.id,
                    local_timestamp=now,
                    server_timestamp=now,
                    is_offline=False,
                    source=AuditSource.SERVER.value,
                )
            return Response(status=status.HTTP_205_RESET_CONTENT)
        except Exception:
            return Response(status=status.HTTP_400_BAD_REQUEST)


class UserViewSet(OrganizationQuerysetMixin, viewsets.ModelViewSet):
    queryset = User.objects.all()
    permission_classes = [
        IsAuthenticated,
        IsOrganizationMember,
        require_permission(write_perm=PermissionCode.USERS_MANAGE.value),
    ]

    def get_serializer_class(self):
        if self.action == 'create':
            return UserCreateSerializer
        return UserSerializer

    def perform_create(self, serializer):
        org_id = self.get_organization_id()
        password = serializer.validated_data.pop('password')
        user = serializer.save(organization_id=org_id)
        user.set_password(password)
        user.save()


class RoleViewSet(OrganizationQuerysetMixin, viewsets.ModelViewSet):
    queryset = Role.objects.all()
    serializer_class = RoleSerializer
    permission_classes = [
        IsAuthenticated,
        IsOrganizationMember,
        require_permission(write_perm=PermissionCode.USERS_MANAGE.value),
    ]

    def perform_destroy(self, instance):
        if instance.is_system:
            raise DRFValidationError("Built-in system roles cannot be deleted.")
        super().perform_destroy(instance)


class PermissionViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Permission.objects.all()
    serializer_class = PermissionSerializer
    pagination_class = None


class UserRoleViewSet(viewsets.ModelViewSet):
    queryset = UserRole.objects.all()
    serializer_class = UserRoleSerializer
    permission_classes = [
        IsAuthenticated,
        IsOrganizationMember,
        require_permission(write_perm=PermissionCode.USERS_MANAGE.value),
    ]

    def get_organization_id(self):
        return getattr(self.request, 'organization_id', None) or getattr(
            self.request.user, 'organization_id', None
        )

    def get_queryset(self):
        org_id = self.get_organization_id()
        if org_id:
            return UserRole.objects.filter(user__organization_id=org_id)
        return UserRole.objects.none()

    def perform_create(self, serializer):
        org_id = self.get_organization_id()
        target_user = serializer.validated_data['user']
        role = serializer.validated_data['role']
        branch = serializer.validated_data.get('branch')

        if target_user.organization_id != org_id or role.organization_id != org_id:
            raise DRFValidationError("User and role must belong to your organization.")
        if branch and branch.organization_id != org_id:
            raise DRFValidationError("Branch must belong to your organization.")

        instance = serializer.save(assigned_by=self.request.user)
        now = timezone.now()
        AuditEvent.objects.create(
            organization_id=org_id,
            branch_id=branch.id if branch else uuid.UUID(int=0),
            user_id=self.request.user.id,
            action=AuditAction.PERMISSION_CHANGED.value,
            entity_type='user_role',
            entity_id=instance.id,
            data_after={
                "user_id": str(target_user.id),
                "role_id": str(role.id),
                "branch_id": str(branch.id) if branch else None,
            },
            local_timestamp=now,
            server_timestamp=now,
            is_offline=False,
            source=AuditSource.SERVER.value,
        )

    def perform_destroy(self, instance):
        instance.is_active = False
        instance.save(update_fields=['is_active', 'updated_at'])
        now = timezone.now()
        AuditEvent.objects.create(
            organization_id=instance.user.organization_id,
            branch_id=instance.branch_id or uuid.UUID(int=0),
            user_id=self.request.user.id,
            action=AuditAction.PERMISSION_CHANGED.value,
            entity_type='user_role',
            entity_id=instance.id,
            data_before={"is_active": True},
            data_after={"is_active": False},
            local_timestamp=now,
            server_timestamp=now,
            is_offline=False,
            source=AuditSource.SERVER.value,
        )
