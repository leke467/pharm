from rest_framework import serializers
from .models import ExpenseCategory, Expense


class ExpenseCategorySerializer(serializers.ModelSerializer):
    organization = serializers.CharField(source='organization_id', read_only=True)

    class Meta:
        model = ExpenseCategory
        fields = [
            'id',
            'organization',
            'name',
            'description',
            'is_active',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'organization', 'created_at', 'updated_at']


class ExpenseSerializer(serializers.ModelSerializer):
    organization = serializers.CharField(source='organization_id', read_only=True)
    category_name = serializers.CharField(source='expense_category.name', read_only=True)
    branch_name = serializers.CharField(source='branch.name', read_only=True)
    created_by_name = serializers.CharField(source='created_by.full_name', read_only=True)
    approved_by_name = serializers.CharField(source='approved_by.full_name', read_only=True, default=None)

    class Meta:
        model = Expense
        fields = [
            'id',
            'organization',
            'branch',
            'branch_name',
            'expense_category',
            'category_name',
            'description',
            'amount',
            'payment_method',
            'expense_date',
            'created_by',
            'created_by_name',
            'approved_by',
            'approved_by_name',
            'status',
            'attachment_path',
            'notes',
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'id',
            'organization',
            'created_by',
            'approved_by',
            'created_at',
            'updated_at',
        ]
