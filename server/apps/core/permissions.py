from rest_framework import permissions
from apps.users.models import RolePermission


def user_has_permission(user, permission_code: str, branch_id=None) -> bool:
    """
    Check if an authenticated user has a specific permission code,
    optionally scoped to a branch_id (org-wide roles with branch=None apply to all branches).
    """
    if not user or not user.is_authenticated or not user.is_active:
        return False
    if getattr(user, 'is_org_admin', False):
        return True

    user_roles = user.userrole_set.filter(is_active=True, role__is_active=True)
    if branch_id:
        user_roles = user_roles.filter(branch_id=branch_id) | user_roles.filter(branch__isnull=True)

    role_ids = user_roles.values_list('role_id', flat=True)
    return RolePermission.objects.filter(
        role_id__in=role_ids,
        permission__code=permission_code,
    ).exists()


class IsOrganizationMember(permissions.BasePermission):
    """
    Layer 2 of the Three-Layer Tenant Security Model.
    Ensures the user belongs to an active organization and any accessed object
    belongs to the exact same organization.
    """

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.is_active
            and getattr(request.user, 'organization_id', None)
        )

    def has_object_permission(self, request, view, obj):
        user_org_id = getattr(request.user, 'organization_id', None)
        if not user_org_id:
            return False
        if hasattr(obj, 'organization_id'):
            return obj.organization_id == user_org_id
        if hasattr(obj, 'organization'):
            return obj.organization_id == user_org_id
        if hasattr(obj, 'user') and hasattr(obj.user, 'organization_id'):
            return obj.user.organization_id == user_org_id
        if obj.__class__.__name__ == 'Organization':
            return obj.id == user_org_id
        return False


class IsBranchMember(permissions.BasePermission):
    """Verifies the user has an active role in the target branch (or an org-wide role)."""

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if getattr(request.user, 'is_org_admin', False):
            return True
        branch_id = (
            view.kwargs.get('branch_id')
            or request.headers.get('X-Branch-ID')
            or request.query_params.get('branch_id')
        )
        if not branch_id:
            return True
        return (
            request.user.userrole_set.filter(branch_id=branch_id, is_active=True).exists()
            or request.user.userrole_set.filter(branch__isnull=True, is_active=True).exists()
        )

    def has_object_permission(self, request, view, obj):
        if getattr(request.user, 'is_org_admin', False):
            return True
        if hasattr(obj, 'branch_id') and obj.branch_id:
            return (
                request.user.userrole_set.filter(branch_id=obj.branch_id, is_active=True).exists()
                or request.user.userrole_set.filter(branch__isnull=True, is_active=True).exists()
            )
        return True


def require_permission(read_perm: str | None = None, write_perm: str | None = None):
    """
    Factory returning a DRF BasePermission class that checks `read_perm` on SAFE_METHODS
    and `write_perm` on mutating methods (POST, PUT, PATCH, DELETE).
    """

    class _PermissionClass(permissions.BasePermission):
        def has_permission(self, request, view):
            if not request.user or not request.user.is_authenticated:
                return False
            branch_id = (
                request.headers.get('X-Branch-ID')
                or request.query_params.get('branch_id')
                or (request.data.get('branch_id') if isinstance(request.data, dict) else None)
            )
            if request.method in permissions.SAFE_METHODS:
                if not read_perm:
                    return True
                return user_has_permission(request.user, read_perm, branch_id=branch_id)
            else:
                required = write_perm or read_perm
                if not required:
                    return True
                return user_has_permission(request.user, required, branch_id=branch_id)

    return _PermissionClass
