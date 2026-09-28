from rest_framework import serializers
from .models import Price, PriceHistory


class PriceHistorySerializer(serializers.ModelSerializer):
    changed_by_name = serializers.CharField(source='changed_by.full_name', read_only=True, default=None)
    branch_name = serializers.CharField(source='branch.name', read_only=True, default=None)

    class Meta:
        model = PriceHistory
        fields = [
            'id',
            'organization',
            'price',
            'product',
            'branch',
            'branch_name',
            'old_price',
            'new_price',
            'changed_by',
            'changed_by_name',
            'change_reason',
            'version',
            'local_timestamp',
            'server_timestamp',
            'sync_status',
            'created_at',
        ]
        read_only_fields = fields


class PriceSerializer(serializers.ModelSerializer):
    organization = serializers.CharField(source='organization_id', read_only=True)
    product_name = serializers.CharField(source='product.name', read_only=True)
    branch_name = serializers.CharField(
        source='branch.name', read_only=True, default=None
    )
    change_reason = serializers.CharField(write_only=True, required=False, allow_blank=True, default='')
    force_all_branches = serializers.BooleanField(write_only=True, required=False, default=False)

    class Meta:
        model = Price
        fields = [
            'id',
            'organization',
            'product',
            'product_name',
            'branch',
            'branch_name',
            'selling_price',
            'currency',
            'is_current',
            'version',
            'effective_from',
            'effective_to',
            'created_by',
            'sync_status',
            'change_reason',
            'force_all_branches',
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'id',
            'organization',
            'is_current',
            'version',
            'effective_to',
            'created_by',
            'sync_status',
            'created_at',
            'updated_at',
        ]

    def create(self, validated_data):
        validated_data.pop('change_reason', None)
        validated_data.pop('force_all_branches', None)
        return super().create(validated_data)
