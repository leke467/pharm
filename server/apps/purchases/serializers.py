from decimal import Decimal
from rest_framework import serializers
from .models import Purchase, PurchaseItem, PurchasePayment


class PurchaseItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    product_sku = serializers.CharField(source='product.sku', read_only=True)
    batch_number = serializers.CharField(source='batch.batch_number', read_only=True)

    class Meta:
        model = PurchaseItem
        fields = [
            'id',
            'purchase',
            'product',
            'product_name',
            'product_sku',
            'batch',
            'batch_number',
            'quantity_ordered',
            'quantity_received',
            'purchase_price',
            'selling_price',
            'discount',
            'line_total',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'purchase', 'quantity_received', 'line_total', 'created_at', 'updated_at']


class PurchasePaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = PurchasePayment
        fields = [
            'id',
            'purchase',
            'payment_method',
            'amount',
            'reference',
            'payment_date',
            'created_at',
        ]
        read_only_fields = ['id', 'purchase', 'created_at']


class PurchaseSerializer(serializers.ModelSerializer):
    items = PurchaseItemSerializer(many=True, read_only=True)
    payments = PurchasePaymentSerializer(many=True, read_only=True)
    supplier_name = serializers.CharField(source='supplier.name', read_only=True)

    class Meta:
        model = Purchase
        fields = [
            'id',
            'organization',
            'branch',
            'supplier',
            'supplier_name',
            'user',
            'purchase_reference',
            'invoice_number',
            'purchase_date',
            'subtotal',
            'discount_amount',
            'total',
            'payment_status',
            'receiving_status',
            'notes',
            'items',
            'payments',
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'id',
            'organization',
            'user',
            'subtotal',
            'total',
            'payment_status',
            'receiving_status',
            'created_at',
            'updated_at',
        ]


class CreatePurchaseItemInputSerializer(serializers.Serializer):
    product_id = serializers.UUIDField()
    quantity_ordered = serializers.IntegerField(min_value=1)
    purchase_price = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal('0.00'))
    selling_price = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False, default=Decimal('0.00')
    )
    discount = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False, default=Decimal('0.00')
    )


class CreatePurchaseRequestSerializer(serializers.Serializer):
    branch_id = serializers.UUIDField()
    supplier_id = serializers.UUIDField()
    purchase_reference = serializers.CharField(max_length=100)
    invoice_number = serializers.CharField(max_length=100, required=False, allow_blank=True, allow_null=True)
    purchase_date = serializers.DateField()
    discount_amount = serializers.DecimalField(
        max_digits=14, decimal_places=2, required=False, default=Decimal('0.00')
    )
    notes = serializers.CharField(required=False, allow_blank=True, default='')
    items = CreatePurchaseItemInputSerializer(many=True, min_length=1)


class ReceivePurchaseItemInputSerializer(serializers.Serializer):
    purchase_item_id = serializers.UUIDField()
    quantity_received = serializers.IntegerField(min_value=1)
    batch_number = serializers.CharField(max_length=100)
    expiry_date = serializers.DateField()
    manufacturing_date = serializers.DateField(required=False, allow_null=True)
    storage_location_id = serializers.UUIDField(required=False, allow_null=True)
    selling_price = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False, allow_null=True
    )
    update_selling_price = serializers.BooleanField(required=False, default=False)


class ReceivePurchaseRequestSerializer(serializers.Serializer):
    items = ReceivePurchaseItemInputSerializer(many=True, min_length=1)
    invoice_number = serializers.CharField(max_length=100, required=False, allow_blank=True, allow_null=True)


class CreatePurchasePaymentInputSerializer(serializers.Serializer):
    payment_method = serializers.CharField(max_length=50)
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal('0.01'))
    reference = serializers.CharField(max_length=100, required=False, allow_blank=True, allow_null=True)
    payment_date = serializers.DateField()
