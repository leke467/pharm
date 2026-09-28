from rest_framework import serializers
from .models import Branch, Device


class BranchSerializer(serializers.ModelSerializer):
    organization = serializers.CharField(source='organization_id', read_only=True)

    class Meta:
        model = Branch
        fields = [
            'id',
            'organization',
            'name',
            'code',
            'address',
            'phone',
            'email',
            'uses_storage_locations',
            'initial_stock_loaded',
            'settings',
            'is_active',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'organization', 'created_at', 'updated_at']


class BranchCreateSerializer(BranchSerializer):
    pass


class DeviceSerializer(serializers.ModelSerializer):
    organization = serializers.CharField(source='organization_id', read_only=True)
    branch = serializers.CharField(source='branch_id', read_only=True)

    class Meta:
        model = Device
        fields = [
            'id',
            'organization',
            'branch',
            'name',
            'code',
            'device_identifier',
            'last_seen_at',
            'is_active',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'organization', 'branch', 'created_at', 'updated_at']


class DeviceRegisterSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(read_only=True)
    organization = serializers.CharField(source='organization_id', read_only=True)
    branch_id = serializers.UUIDField()

    class Meta:
        model = Device
        fields = [
            'id',
            'organization',
            'branch_id',
            'name',
            'code',
            'device_identifier',
            'last_seen_at',
            'is_active',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'organization', 'last_seen_at', 'is_active', 'created_at', 'updated_at']
