from rest_framework import serializers
from .models import Subscription, SubscriptionPayment, Entitlement, License


class EntitlementSerializer(serializers.ModelSerializer):
    class Meta:
        model = Entitlement
        fields = [
            'id',
            'organization',
            'subscription',
            'feature_code',
            'feature_value',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'organization', 'created_at', 'updated_at']


class SubscriptionSerializer(serializers.ModelSerializer):
    entitlements = EntitlementSerializer(many=True, read_only=True)
    is_expired = serializers.BooleanField(read_only=True)
    is_in_grace_period = serializers.BooleanField(read_only=True)
    days_remaining = serializers.IntegerField(read_only=True)
    effective_status = serializers.CharField(read_only=True)

    class Meta:
        model = Subscription
        fields = [
            'id',
            'organization',
            'plan',
            'status',
            'effective_status',
            'monthly_price',
            'yearly_price',
            'currency',
            'current_period_start',
            'current_period_end',
            'days_remaining',
            'grace_period_days',
            'auto_renew',
            'monnify_account_reference',
            'monnify_account_number',
            'monnify_account_name',
            'monnify_bank_name',
            'monnify_bank_code',
            'entitlements',
            'is_expired',
            'is_in_grace_period',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'organization', 'created_at', 'updated_at']


class SubscriptionPaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = SubscriptionPayment
        fields = [
            'id',
            'organization',
            'subscription',
            'payment_reference',
            'monnify_transaction_reference',
            'billing_cycle',
            'amount',
            'currency',
            'days_credited',
            'status',
            'checkout_url',
            'payment_method',
            'paid_at',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'organization', 'subscription', 'created_at', 'updated_at']


class LicenseSerializer(serializers.ModelSerializer):
    class Meta:
        model = License
        fields = [
            'id',
            'organization',
            'license_key',
            'status',
            'issued_at',
            'expires_at',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'organization', 'created_at', 'updated_at']
