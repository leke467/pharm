import uuid
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from apps.organizations.models import Organization
from apps.branches.models import Branch


class SyncDelivery(models.Model):
    id = models.BigAutoField(primary_key=True)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='+')
    entity_type = models.CharField(max_length=50)
    entity_id = models.UUIDField()
    operation = models.CharField(max_length=20)
    payload = models.JSONField(encoder=DjangoJSONEncoder)
    target_scope = models.CharField(max_length=20)
    target_branch = models.ForeignKey(Branch, on_delete=models.CASCADE, null=True, related_name='+')
    source_branch = models.ForeignKey(Branch, on_delete=models.CASCADE, null=True, related_name='+')
    source_device_id = models.UUIDField(null=True)
    source_event_id = models.UUIDField(null=True)
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)


class ProcessedEvent(models.Model):
    event_id = models.UUIDField(primary_key=True)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='+')
    processed_at = models.DateTimeField(auto_now_add=True)


class BranchBackup(models.Model):
    """
    Cloud SQLite backup snapshot per branch.
    Maintains up to 4 backups per branch in FILO/LIFO order (newest first, max 4 retained per branch).
    Allows any branch whose laptop spoils to restore from the latest cloud backup on a new PC and continue.
    """
    MAX_BACKUPS_PER_BRANCH = 4

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name='branch_backups'
    )
    branch = models.ForeignKey(
        Branch, on_delete=models.SET_NULL, null=True, blank=True, related_name='cloud_backups'
    )
    branch_code = models.CharField(max_length=50, db_index=True)
    branch_name = models.CharField(max_length=255, default='Main Branch')
    device_code = models.CharField(max_length=50, blank=True, default='POS01')
    filename = models.CharField(max_length=255)
    size_bytes = models.BigIntegerField(default=0)
    checksum_sha256 = models.CharField(max_length=64, blank=True, default='')
    compressed_payload = models.BinaryField()
    note = models.CharField(max_length=255, blank=True, default='Auto-Sync Cloud Backup')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Branch Cloud Backup'
        verbose_name_plural = 'Branch Cloud Backups (Max 4 / Branch)'

    def __str__(self):
        return f"{self.organization.code} / {self.branch_name} ({self.branch_code}) — {self.created_at:%Y-%m-%d %H:%M:%S}"

    @classmethod
    def enforce_branch_retention(cls, organization: Organization, branch_code: str, max_retain: int = 4):
        """
        Keeps only the `max_retain` (4) most recent backups for the given branch (FILO/LIFO stack)
        and deletes any older backups beyond the 4 slots.
        """
        qs = cls.objects.filter(
            organization=organization,
            branch_code__iexact=branch_code,
        ).order_by('-created_at', '-updated_at')
        all_ids = list(qs.values_list('id', flat=True))
        if len(all_ids) > max_retain:
            stale_ids = all_ids[max_retain:]
            cls.objects.filter(id__in=stale_ids).delete()

