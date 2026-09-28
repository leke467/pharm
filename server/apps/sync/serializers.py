from rest_framework import serializers
from .models import SyncDelivery, BranchBackup


class SyncEventInputSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    entity_type = serializers.CharField(max_length=50)
    entity_id = serializers.UUIDField()
    operation = serializers.ChoiceField(choices=['CREATE', 'UPDATE'])
    payload = serializers.DictField()
    correlation_id = serializers.UUIDField(required=False, allow_null=True)
    dependency_level = serializers.IntegerField(default=5)
    schema_version = serializers.IntegerField(default=1)
    local_created_at = serializers.CharField()


class SyncUploadRequestSerializer(serializers.Serializer):
    device_id = serializers.UUIDField()
    branch_id = serializers.UUIDField()
    events = SyncEventInputSerializer(many=True)


class SyncDeliverySerializer(serializers.ModelSerializer):
    sequence = serializers.IntegerField(source='id', read_only=True)
    target_branch_id = serializers.UUIDField(read_only=True)
    source_branch_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = SyncDelivery
        fields = [
            'sequence',
            'id',
            'entity_type',
            'entity_id',
            'operation',
            'payload',
            'target_scope',
            'target_branch_id',
            'source_branch_id',
            'source_device_id',
            'source_event_id',
            'created_at',
        ]


class BranchBackupSerializer(serializers.ModelSerializer):
    organization_code = serializers.CharField(source='organization.code', read_only=True)
    organization_name = serializers.CharField(source='organization.name', read_only=True)

    class Meta:
        model = BranchBackup
        fields = [
            'id',
            'organization',
            'organization_code',
            'organization_name',
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
        ]

