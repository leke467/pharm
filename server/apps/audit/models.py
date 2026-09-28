import uuid
from django.core.exceptions import ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from apps.organizations.models import Organization


class AuditEvent(models.Model):
    """
    Immutable append-only audit trail record (Architecture Decision #24).
    No UPDATE or DELETE is ever permitted on this table.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='audit_events')
    branch_id = models.UUIDField()
    user_id = models.UUIDField()
    device_id = models.UUIDField(null=True, blank=True)
    action = models.CharField(max_length=50)
    entity_type = models.CharField(max_length=50)
    entity_id = models.UUIDField()
    data_before = models.JSONField(null=True, blank=True, encoder=DjangoJSONEncoder)
    data_after = models.JSONField(null=True, blank=True, encoder=DjangoJSONEncoder)
    reason = models.TextField(blank=True)
    correlation_id = models.UUIDField(null=True, blank=True)
    transaction_id = models.UUIDField(null=True, blank=True)
    local_timestamp = models.DateTimeField()
    server_timestamp = models.DateTimeField(null=True, blank=True)
    is_offline = models.BooleanField(default=False)
    source = models.CharField(max_length=20)
    sync_id = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['organization', 'branch_id', 'created_at']),
            models.Index(fields=['entity_type', 'entity_id']),
        ]
        ordering = ['-created_at']

    def save(self, *args, **kwargs):
        if not self._state.adding and AuditEvent.objects.filter(pk=self.pk).exists():
            raise ValidationError("AuditEvent records are immutable and cannot be updated.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("AuditEvent records are immutable and cannot be deleted.")
