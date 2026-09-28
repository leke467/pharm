from django.contrib import admin
from .models import Branch, Device


@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'organization', 'uses_storage_locations', 'is_active', 'created_at')
    list_filter = ('organization', 'is_active', 'uses_storage_locations')
    search_fields = ('name', 'code', 'organization__name', 'organization__code')


@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'device_identifier', 'branch', 'organization', 'last_seen_at', 'is_active')
    list_filter = ('organization', 'branch', 'is_active')
    search_fields = ('name', 'code', 'device_identifier')
