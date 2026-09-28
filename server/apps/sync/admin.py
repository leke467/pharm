from django.contrib import admin
from django.utils.html import format_html
from .models import BranchBackup, SyncDelivery, ProcessedEvent


@admin.register(BranchBackup)
class BranchBackupAdmin(admin.ModelAdmin):
    list_display = (
        'organization',
        'branch_name',
        'branch_code',
        'device_code',
        'size_kb_display',
        'note',
        'created_at',
        'download_link',
    )
    list_filter = ('organization', 'branch_code', 'created_at')
    search_fields = ('organization__name', 'organization__code', 'branch_name', 'branch_code', 'filename')
    readonly_fields = (
        'id',
        'organization',
        'branch',
        'branch_code',
        'branch_name',
        'device_code',
        'filename',
        'size_bytes',
        'checksum_sha256',
        'note',
        'created_at',
        'updated_at',
        'download_link',
    )

    @admin.display(description='Size (KB)')
    def size_kb_display(self, obj: BranchBackup):
        return f"{obj.size_bytes / 1024.0:,.1f} KB"

    @admin.display(description='Download .db File')
    def download_link(self, obj: BranchBackup):
        if not obj.pk:
            return "-"
        return format_html(
            '<a class="button" href="/api/v1/sync/backups/{}/download/?raw=1" '
            'style="background:#2563EB;color:white;padding:4px 10px;border-radius:4px;text-decoration:none;font-weight:700;">'
            '⬇ Download SQLite .db</a>',
            obj.pk,
        )


@admin.register(SyncDelivery)
class SyncDeliveryAdmin(admin.ModelAdmin):
    list_display = ('id', 'organization', 'entity_type', 'operation', 'target_scope', 'created_at')
    list_filter = ('organization', 'entity_type', 'operation')


@admin.register(ProcessedEvent)
class ProcessedEventAdmin(admin.ModelAdmin):
    list_display = ('event_id', 'organization', 'processed_at')
    list_filter = ('organization',)
