from django.contrib import admin
from .models import User, Role, Permission, UserRole
from .services import seed_permissions_and_roles


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ('username', 'full_name', 'organization', 'default_branch', 'is_org_admin', 'is_staff', 'is_active')
    list_filter = ('organization', 'is_org_admin', 'is_staff', 'is_active')
    search_fields = ('username', 'full_name', 'email')

    def save_model(self, request, obj, form, change):
        raw_pw = obj.password or ''
        if raw_pw and not raw_pw.startswith(('pbkdf2_', 'bcrypt', 'argon2', 'scrypt')):
            obj.set_password(raw_pw)
        super().save_model(request, obj, form, change)
        if obj.organization:
            try:
                seed_permissions_and_roles(obj.organization)
                if obj.is_org_admin:
                    admin_role = Role.objects.filter(organization=obj.organization, name="Organization Admin").first()
                    if admin_role:
                        UserRole.objects.get_or_create(user=obj, role=admin_role, branch=None)
            except Exception:
                pass


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ('name', 'organization', 'is_system', 'is_active')
    list_filter = ('organization', 'is_system', 'is_active')


@admin.register(Permission)
class PermissionAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'category')
    list_filter = ('category',)
    search_fields = ('code', 'name')


@admin.register(UserRole)
class UserRoleAdmin(admin.ModelAdmin):
    list_display = ('user', 'role', 'branch', 'is_active')
    list_filter = ('role', 'branch', 'is_active')
