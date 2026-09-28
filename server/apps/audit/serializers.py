from rest_framework import serializers
from .models import AuditEvent


class AuditEventSerializer(serializers.ModelSerializer):
    """
    Read-only serializer for AuditEvent records (Architecture Plan §6, §13).
    """

    class Meta:
        model = AuditEvent
        fields = [
            'id',
            'organization',
            'branch_id',
            'user_id',
            'device_id',
            'action',
            'entity_type',
            'entity_id',
            'data_before',
            'data_after',
            'reason',
            'correlation_id',
            'transaction_id',
            'local_timestamp',
            'server_timestamp',
            'is_offline',
            'source',
            'sync_id',
            'created_at',
        ]
        read_only_fields = fields
