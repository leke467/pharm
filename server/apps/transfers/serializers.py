from rest_framework import serializers
from apps.transfers.models import StockTransfer, StockTransferItem
from apps.branches.models import Branch
from apps.products.models import Product
from apps.inventory.models import Batch


class StockTransferItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    batch_number = serializers.CharField(source='batch.batch_number', read_only=True)

    class Meta:
        model = StockTransferItem
        fields = [
            'id',
            'product',
            'product_name',
            'batch',
            'batch_number',
            'quantity',
            'created_at',
        ]


class StockTransferItemCreateSerializer(serializers.Serializer):
    product_id = serializers.UUIDField()
    batch_id = serializers.UUIDField()
    quantity = serializers.IntegerField(min_value=1)


class StockTransferSerializer(serializers.ModelSerializer):
    items = StockTransferItemSerializer(many=True, read_only=True)
    source_branch_name = serializers.CharField(source='source_branch.name', read_only=True)
    source_branch_code = serializers.CharField(source='source_branch.code', read_only=True)
    destination_branch_name = serializers.CharField(source='destination_branch.name', read_only=True)
    destination_branch_code = serializers.CharField(source='destination_branch.code', read_only=True)
    requested_by_name = serializers.CharField(source='requested_by.full_name', read_only=True)
    approved_by_name = serializers.CharField(source='approved_by.full_name', read_only=True, default=None)
    dispatched_by_name = serializers.CharField(source='dispatched_by.full_name', read_only=True, default=None)
    received_by_name = serializers.CharField(source='received_by.full_name', read_only=True, default=None)

    class Meta:
        model = StockTransfer
        fields = [
            'id',
            'organization',
            'source_branch',
            'source_branch_name',
            'source_branch_code',
            'destination_branch',
            'destination_branch_name',
            'destination_branch_code',
            'status',
            'requested_by',
            'requested_by_name',
            'approved_by',
            'approved_by_name',
            'dispatched_by',
            'dispatched_by_name',
            'received_by',
            'received_by_name',
            'requested_at',
            'approved_at',
            'dispatched_at',
            'received_at',
            'notes',
            'items',
            'created_at',
            'updated_at',
        ]


class StockTransferCreateSerializer(serializers.Serializer):
    source_branch_id = serializers.UUIDField()
    destination_branch_id = serializers.UUIDField()
    notes = serializers.CharField(required=False, allow_blank=True, default='')
    items = StockTransferItemCreateSerializer(many=True)

    def validate(self, attrs):
        source_id = attrs['source_branch_id']
        dest_id = attrs['destination_branch_id']
        if source_id == dest_id:
            raise serializers.ValidationError("Source and destination branches cannot be the same.")
        if not attrs.get('items'):
            raise serializers.ValidationError("At least one transfer item must be provided.")
        return attrs
