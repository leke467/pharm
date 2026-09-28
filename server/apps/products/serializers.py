from rest_framework import serializers
from apps.branches.models import Branch
from .models import (
    Category,
    ProductType,
    Manufacturer,
    Supplier,
    Product,
    ProductBranch,
    ProductDocument,
)


class CategorySerializer(serializers.ModelSerializer):
    organization = serializers.CharField(source='organization_id', read_only=True)

    class Meta:
        model = Category
        fields = [
            'id',
            'organization',
            'name',
            'parent',
            'is_active',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'organization', 'created_at', 'updated_at']
        validators = []


class ProductTypeSerializer(serializers.ModelSerializer):
    organization = serializers.CharField(source='organization_id', read_only=True)

    class Meta:
        model = ProductType
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
        validators = []


class ManufacturerSerializer(serializers.ModelSerializer):
    organization = serializers.CharField(source='organization_id', read_only=True)

    class Meta:
        model = Manufacturer
        fields = [
            'id',
            'organization',
            'name',
            'country',
            'contact_info',
            'is_active',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'organization', 'created_at', 'updated_at']
        validators = []


class SupplierSerializer(serializers.ModelSerializer):
    organization = serializers.CharField(source='organization_id', read_only=True)

    class Meta:
        model = Supplier
        fields = [
            'id',
            'organization',
            'name',
            'contact_person',
            'phone',
            'email',
            'address',
            'notes',
            'is_active',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'organization', 'created_at', 'updated_at']
        validators = []


class ProductBranchSerializer(serializers.ModelSerializer):
    branch_name = serializers.CharField(source='branch.name', read_only=True)
    branch_code = serializers.CharField(source='branch.code', read_only=True)

    class Meta:
        model = ProductBranch
        fields = [
            'id',
            'product',
            'branch',
            'branch_name',
            'branch_code',
            'is_active',
            'reorder_level',
            'settings',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class ProductDocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductDocument
        fields = [
            'id',
            'product',
            'name',
            'file_path',
            'document_type',
            'uploaded_by',
            'created_at',
        ]
        read_only_fields = ['id', 'uploaded_by', 'created_at']


class ProductSerializer(serializers.ModelSerializer):
    organization = serializers.CharField(source='organization_id', read_only=True)
    category_name = serializers.CharField(source='category.name', read_only=True)
    branch_ids = serializers.ListField(
        child=serializers.UUIDField(),
        write_only=True,
        required=False,
    )
    select_all_branches = serializers.BooleanField(
        write_only=True,
        required=False,
        default=False,
    )
    active_branch_ids = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            'id',
            'organization',
            'sku',
            'barcode',
            'name',
            'generic_name',
            'brand_name',
            'category',
            'category_name',
            'product_type',
            'manufacturer',
            'description',
            'active_ingredients',
            'strength',
            'dosage_form',
            'route',
            'formulation',
            'indication',
            'contraindications',
            'precautions',
            'drug_interactions',
            'side_effects',
            'storage_conditions',
            'age_suitability',
            'pregnancy_caution',
            'prescription_required',
            'controlled_status',
            'importer',
            'regulatory_info',
            'image_url',
            'notes',
            'is_active',
            'branch_ids',
            'select_all_branches',
            'active_branch_ids',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'organization', 'created_at', 'updated_at']

    def get_active_branch_ids(self, obj):
        return [
            str(bid)
            for bid in obj.product_branches.filter(is_active=True).values_list(
                'branch_id', flat=True
            )
        ]

    def create(self, validated_data):
        branch_ids = validated_data.pop('branch_ids', None)
        select_all = validated_data.pop('select_all_branches', False)
        product = super().create(validated_data)

        if select_all:
            branches = Branch.objects.filter(
                organization_id=product.organization_id, is_active=True
            )
            for b in branches:
                ProductBranch.objects.update_or_create(
                    product=product, branch=b, defaults={'is_active': True}
                )
        elif branch_ids:
            branches = Branch.objects.filter(
                organization_id=product.organization_id, id__in=branch_ids
            )
            for b in branches:
                ProductBranch.objects.update_or_create(
                    product=product, branch=b, defaults={'is_active': True}
                )
        return product

    def update(self, instance, validated_data):
        branch_ids = validated_data.pop('branch_ids', None)
        select_all = validated_data.pop('select_all_branches', False)
        product = super().update(instance, validated_data)

        if select_all:
            branches = Branch.objects.filter(
                organization_id=product.organization_id, is_active=True
            )
            for b in branches:
                ProductBranch.objects.update_or_create(
                    product=product, branch=b, defaults={'is_active': True}
                )
        elif branch_ids is not None:
            ProductBranch.objects.filter(product=product).exclude(
                branch_id__in=branch_ids
            ).update(is_active=False)
            branches = Branch.objects.filter(
                organization_id=product.organization_id, id__in=branch_ids
            )
            for b in branches:
                ProductBranch.objects.update_or_create(
                    product=product, branch=b, defaults={'is_active': True}
                )
        return product
