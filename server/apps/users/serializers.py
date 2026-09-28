from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenRefreshSerializer as BaseTokenRefreshSerializer
from .models import User, Role, Permission, UserRole, RolePermission


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True)
    org_code = serializers.CharField()
    branch_id = serializers.UUIDField(required=False, allow_null=True)
    device_id = serializers.UUIDField(required=False, allow_null=True)


class PermissionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Permission
        fields = ['id', 'code', 'name', 'category']


class RoleSerializer(serializers.ModelSerializer):
    organization = serializers.CharField(source='organization_id', read_only=True)
    permission_codes = serializers.ListField(
        child=serializers.CharField(),
        write_only=True,
        required=False,
    )
    permissions = serializers.SerializerMethodField()

    class Meta:
        model = Role
        fields = [
            'id',
            'organization',
            'name',
            'description',
            'is_system',
            'is_active',
            'permission_codes',
            'permissions',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'organization', 'is_system', 'created_at', 'updated_at']

    def get_permissions(self, obj):
        return list(obj.permissions.values_list('permission__code', flat=True))

    def create(self, validated_data):
        perm_codes = validated_data.pop('permission_codes', [])
        role = super().create(validated_data)
        if perm_codes:
            perms = Permission.objects.filter(code__in=perm_codes)
            for perm in perms:
                RolePermission.objects.get_or_create(role=role, permission=perm)
        return role

    def update(self, instance, validated_data):
        perm_codes = validated_data.pop('permission_codes', None)
        role = super().update(instance, validated_data)
        if perm_codes is not None:
            RolePermission.objects.filter(role=role).delete()
            perms = Permission.objects.filter(code__in=perm_codes)
            for perm in perms:
                RolePermission.objects.get_or_create(role=role, permission=perm)
        return role


class UserRoleSerializer(serializers.ModelSerializer):
    role_name = serializers.CharField(source='role.name', read_only=True)
    branch_name = serializers.CharField(source='branch.name', read_only=True, default=None)

    class Meta:
        model = UserRole
        fields = [
            'id',
            'user',
            'role',
            'role_name',
            'branch',
            'branch_name',
            'assigned_by',
            'is_active',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'assigned_by', 'created_at', 'updated_at']


class UserSerializer(serializers.ModelSerializer):
    organization = serializers.CharField(source='organization_id', read_only=True)
    roles = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id',
            'organization',
            'username',
            'email',
            'full_name',
            'phone',
            'is_active',
            'is_org_admin',
            'default_branch',
            'roles',
            'date_joined',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'organization', 'date_joined', 'created_at', 'updated_at']

    def get_roles(self, obj):
        return UserRoleSerializer(obj.userrole_set.filter(is_active=True), many=True).data


class UserCreateSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(read_only=True)
    organization = serializers.CharField(source='organization_id', read_only=True)
    password = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = [
            'id',
            'organization',
            'username',
            'email',
            'full_name',
            'phone',
            'password',
            'is_org_admin',
            'default_branch',
            'is_active',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'organization', 'created_at', 'updated_at']


class TokenRefreshSerializer(BaseTokenRefreshSerializer):
    pass
