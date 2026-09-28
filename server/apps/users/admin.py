from django.contrib import admin
from .models import User, Role, Permission, UserRole


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ('username', 'full_name', 'organization', 'default_branch', 'is_org_admin', 'is_staff', 'is_active')
    list_filter = ('organization', 'is_org_admin', 'is_staff', 'is_active')
    search_fields = ('username', 'full_name', 'email')


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
