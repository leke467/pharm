from rest_framework import serializers
from .models import (
    Batch,
    StorageLocation,
    StorageLocationAssignment,
    BranchInventory,
    InventoryMovement,
    InventoryAlert,
    StockCount,
    StockCountItem,
)


class BatchSerializer(serializers.ModelSerializer):
    organization = serializers.CharField(source='organization_id', read_only=True)
    product_name = serializers.CharField(source='product.name', read_only=True)

    class Meta:
        model = Batch
        fields = [
            'id',
            'organization',
            'product',
            'product_name',
            'batch_number',
            'manufacturing_date',
            'expiry_date',
            'purchase_price',
            'supplier',
            'invoice_reference',
            'received_date',
            'status',
            'regulatory_metadata',
            'notes',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'organization', 'created_at', 'updated_at']
        validators = []


class StorageLocationSerializer(serializers.ModelSerializer):
    organization = serializers.CharField(source='organization_id', read_only=True)

    class Meta:
        model = StorageLocation
        fields = [
            'id',
            'organization',
            'branch',
            'name',
            'description',
            'location_type',
            'is_active',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'organization', 'created_at', 'updated_at']
        validators = []


class StorageLocationAssignmentSerializer(serializers.ModelSerializer):
    organization = serializers.CharField(source='organization_id', read_only=True)

    class Meta:
        model = StorageLocationAssignment
        fields = [
            'id',
            'organization',
            'storage_location',
            'user',
            'branch',
            'start_date',
            'end_date',
            'assigned_by',
            'is_active',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'organization', 'assigned_by', 'created_at', 'updated_at']


class BranchInventorySerializer(serializers.ModelSerializer):
    organization = serializers.CharField(source='organization_id', read_only=True)
    available_quantity = serializers.IntegerField(read_only=True)
    batch_number = serializers.CharField(source='batch.batch_number', read_only=True)
    expiry_date = serializers.DateField(source='batch.expiry_date', read_only=True)
    product_id = serializers.UUIDField(source='batch.product_id', read_only=True)
    product_name = serializers.CharField(source='batch.product.name', read_only=True)

    class Meta:
        model = BranchInventory
        fields = [
            'id',
            'organization',
            'branch',
            'batch',
            'batch_number',
            'expiry_date',
            'product_id',
            'product_name',
            'storage_location',
            'quantity',
            'reserved_quantity',
            'available_quantity',
            'reorder_level',
            'status',
            'last_counted_at',
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'id',
            'organization',
            'quantity',
            'reserved_quantity',
            'available_quantity',
            'created_at',
            'updated_at',
        ]


class InventoryMovementSerializer(serializers.ModelSerializer):
    organization = serializers.CharField(source='organization_id', read_only=True)

    class Meta:
        model = InventoryMovement
        fields = [
            'id',
            'organization',
            'branch',
            'batch',
            'storage_location',
            'movement_type',
            'quantity_change',
            'quantity_before',
            'quantity_after',
            'reference_type',
            'reference_id',
            'user',
            'device',
            'notes',
            'local_timestamp',
            'server_timestamp',
            'is_offline',
            'created_at',
        ]
        read_only_fields = fields


class InventoryAlertSerializer(serializers.ModelSerializer):
    organization = serializers.CharField(source='organization_id', read_only=True)

    class Meta:
        model = InventoryAlert
        fields = [
            'id',
            'organization',
            'branch',
            'batch',
            'alert_type',
            'details',
            'is_resolved',
            'resolved_by',
            'resolved_at',
            'created_at',
        ]
        read_only_fields = [
            'id',
            'organization',
            'branch',
            'batch',
            'alert_type',
            'details',
            'resolved_by',
            'resolved_at',
            'created_at',
        ]


class OpeningBalanceEntrySerializer(serializers.Serializer):
    batch_id = serializers.UUIDField()
    storage_location_id = serializers.UUIDField(required=False, allow_null=True)
    quantity = serializers.IntegerField(min_value=1)
    reorder_level = serializers.IntegerField(required=False, allow_null=True)


class OpeningBalanceRequestSerializer(serializers.Serializer):
    branch_id = serializers.UUIDField()
    entries = OpeningBalanceEntrySerializer(many=True)


class StockAdjustmentRequestSerializer(serializers.Serializer):
    branch_id = serializers.UUIDField()
    batch_id = serializers.UUIDField()
    storage_location_id = serializers.UUIDField(required=False, allow_null=True)
    movement_type = serializers.ChoiceField(
        choices=['STOCK_ADJUSTMENT', 'DAMAGE', 'EXPIRY']
    )
    quantity_change = serializers.IntegerField()
    notes = serializers.CharField(required=True)


class StockCountItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    batch_number = serializers.CharField(source='batch.batch_number', read_only=True)

    class Meta:
        model = StockCountItem
        fields = [
            'id',
            'stock_count',
            'product',
            'product_name',
            'batch',
            'batch_number',
            'storage_location',
            'system_quantity',
            'counted_quantity',
            'variance',
            'current_quantity_at_approval',
            'approval_status',
            'rejection_reason',
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'id',
            'stock_count',
            'variance',
            'current_quantity_at_approval',
            'approval_status',
            'rejection_reason',
            'created_at',
            'updated_at',
        ]


class StockCountSerializer(serializers.ModelSerializer):
    items = StockCountItemSerializer(many=True, read_only=True)
    started_by_name = serializers.CharField(source='started_by.username', read_only=True)

    class Meta:
        model = StockCount
        fields = [
            'id',
            'organization',
            'branch',
            'device',
            'storage_location',
            'count_type',
            'status',
            'started_by',
            'started_by_name',
            'started_at',
            'submitted_by',
            'submitted_at',
            'approved_by',
            'approved_at',
            'notes',
            'items',
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'id',
            'organization',
            'status',
            'started_by',
            'started_at',
            'submitted_by',
            'submitted_at',
            'approved_by',
            'approved_at',
            'created_at',
            'updated_at',
        ]


class StartStockCountRequestSerializer(serializers.Serializer):
    branch_id = serializers.UUIDField()
    device_id = serializers.UUIDField(required=False, allow_null=True)
    storage_location_id = serializers.UUIDField(required=False, allow_null=True)
    count_type = serializers.ChoiceField(
        choices=['FULL_BRANCH', 'STORAGE_LOCATION', 'CATEGORY', 'SELECTED_PRODUCTS'],
        default='FULL_BRANCH',
    )
    notes = serializers.CharField(required=False, allow_blank=True, default='')


class CountItemEntrySerializer(serializers.Serializer):
    batch_id = serializers.UUIDField()
    counted_quantity = serializers.IntegerField(min_value=0)
    storage_location_id = serializers.UUIDField(required=False, allow_null=True)


class SubmitStockCountRequestSerializer(serializers.Serializer):
    items = CountItemEntrySerializer(many=True, min_length=1)
    notes = serializers.CharField(required=False, allow_blank=True, default='')


class ApproveItemEntrySerializer(serializers.Serializer):
    stock_count_item_id = serializers.UUIDField()
    action = serializers.ChoiceField(choices=['APPROVE', 'REJECT'])
    rejection_reason = serializers.CharField(required=False, allow_blank=True, default='')


class ApproveStockCountRequestSerializer(serializers.Serializer):
    items = ApproveItemEntrySerializer(many=True, min_length=1)
    notes = serializers.CharField(required=False, allow_blank=True, default='')

