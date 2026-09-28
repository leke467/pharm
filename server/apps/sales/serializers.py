from decimal import Decimal
from rest_framework import serializers
from .models import Sale, SaleItem, Payment, Receipt, SaleReturn, SaleReturnItem


class SaleItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    batch_number = serializers.CharField(source='batch.batch_number', read_only=True)

    class Meta:
        model = SaleItem
        fields = [
            'id',
            'sale',
            'product',
            'product_name',
            'batch',
            'batch_number',
            'quantity',
            'unit_price',
            'discount_amount',
            'line_total',
            'created_at',
        ]
        read_only_fields = fields


class PaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = ['id', 'sale', 'payment_method', 'amount', 'reference', 'created_at']
        read_only_fields = fields


class ReceiptSerializer(serializers.ModelSerializer):
    class Meta:
        model = Receipt
        fields = [
            'id',
            'sale',
            'receipt_number',
            'printed_at',
            'printer_name',
            'reprint_count',
            'created_at',
        ]
        read_only_fields = fields


class SaleSerializer(serializers.ModelSerializer):
    organization = serializers.CharField(source='organization_id', read_only=True)
    items = SaleItemSerializer(many=True, read_only=True)
    payments = PaymentSerializer(many=True, read_only=True)
    receipt = ReceiptSerializer(read_only=True)

    class Meta:
        model = Sale
        fields = [
            'id',
            'organization',
            'branch',
            'user',
            'device',
            'receipt_number',
            'customer_name',
            'customer_phone',
            'subtotal',
            'discount_amount',
            'tax_amount',
            'total',
            'status',
            'sale_date',
            'server_received_at',
            'is_offline',
            'sync_status',
            'notes',
            'items',
            'payments',
            'receipt',
            'created_at',
            'updated_at',
        ]
        read_only_fields = fields


class CheckoutItemInputSerializer(serializers.Serializer):
    product_id = serializers.UUIDField()
    batch_id = serializers.UUIDField(required=False, allow_null=True)
    quantity = serializers.IntegerField(min_value=1)
    unit_price = serializers.DecimalField(max_digits=12, decimal_places=2)
    discount_amount = serializers.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal('0.00')
    )


class CheckoutPaymentInputSerializer(serializers.Serializer):
    payment_method = serializers.CharField(max_length=50)
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    reference = serializers.CharField(max_length=100, required=False, allow_blank=True, allow_null=True)


class CreateSaleRequestSerializer(serializers.Serializer):
    branch_id = serializers.UUIDField()
    device_id = serializers.UUIDField()
    receipt_number = serializers.CharField(max_length=50)
    customer_name = serializers.CharField(max_length=255, required=False, allow_blank=True, allow_null=True)
    customer_phone = serializers.CharField(max_length=50, required=False, allow_blank=True, allow_null=True)
    discount_amount = serializers.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal('0.00')
    )
    tax_amount = serializers.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal('0.00')
    )
    notes = serializers.CharField(required=False, allow_blank=True, default='')
    items = CheckoutItemInputSerializer(many=True)
    payments = CheckoutPaymentInputSerializer(many=True)


class SaleReturnItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)

    class Meta:
        model = SaleReturnItem
        fields = [
            'id',
            'sale_return',
            'sale_item',
            'product',
            'product_name',
            'batch',
            'quantity',
            'unit_price',
            'line_total',
            'created_at',
        ]
        read_only_fields = fields


class SaleReturnSerializer(serializers.ModelSerializer):
    organization = serializers.CharField(source='organization_id', read_only=True)
    items = SaleReturnItemSerializer(many=True, read_only=True)

    class Meta:
        model = SaleReturn
        fields = [
            'id',
            'organization',
            'original_sale',
            'branch',
            'user',
            'device',
            'return_date',
            'reason',
            'refund_amount',
            'status',
            'approved_by',
            'items',
            'created_at',
            'updated_at',
        ]
        read_only_fields = fields


class ReturnItemInputSerializer(serializers.Serializer):
    sale_item_id = serializers.UUIDField()
    quantity = serializers.IntegerField(min_value=1)


class CreateSaleReturnRequestSerializer(serializers.Serializer):
    original_sale_id = serializers.UUIDField()
    device_id = serializers.UUIDField()
    reason = serializers.CharField()
    items = ReturnItemInputSerializer(many=True)
