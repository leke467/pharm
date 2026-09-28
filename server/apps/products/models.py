import uuid
from django.db import models
from apps.core.models import BaseModel
from apps.organizations.models import Organization
from apps.branches.models import Branch
from apps.users.models import User


class Category(BaseModel):
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name='categories'
    )
    name = models.CharField(max_length=255)
    parent = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='children',
    )

    class Meta:
        unique_together = [('organization', 'name', 'parent')]
        ordering = ['name']

    def __str__(self):
        return self.name


class ProductType(BaseModel):
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name='product_types'
    )
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, default='')

    class Meta:
        unique_together = [('organization', 'name')]
        ordering = ['name']

    def __str__(self):
        return self.name


class Manufacturer(BaseModel):
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name='manufacturers'
    )
    name = models.CharField(max_length=255)
    country = models.CharField(max_length=100, blank=True, default='')
    contact_info = models.TextField(blank=True, default='')

    class Meta:
        unique_together = [('organization', 'name')]
        ordering = ['name']

    def __str__(self):
        return self.name


class Supplier(BaseModel):
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name='suppliers'
    )
    name = models.CharField(max_length=255)
    contact_person = models.CharField(max_length=255, blank=True, default='')
    phone = models.CharField(max_length=50, blank=True, default='')
    email = models.EmailField(blank=True, default='')
    address = models.TextField(blank=True, default='')
    notes = models.TextField(blank=True, default='')

    class Meta:
        unique_together = [('organization', 'name')]
        ordering = ['name']

    def __str__(self):
        return self.name


class Product(BaseModel):
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name='products'
    )
    sku = models.CharField(max_length=50)
    barcode = models.CharField(max_length=100, blank=True, null=True)
    name = models.CharField(max_length=255)
    generic_name = models.CharField(max_length=255, blank=True, null=True)
    brand_name = models.CharField(max_length=255, blank=True, null=True)
    category = models.ForeignKey(
        Category, on_delete=models.PROTECT, related_name='products'
    )
    product_type = models.ForeignKey(
        ProductType,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='products',
    )
    manufacturer = models.ForeignKey(
        Manufacturer,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='products',
    )
    description = models.TextField(blank=True, default='')

    # Optional pharmaceutical attributes (nullable so non-drug items work seamlessly)
    active_ingredients = models.TextField(blank=True, null=True)
    strength = models.CharField(max_length=100, blank=True, null=True)
    dosage_form = models.CharField(max_length=100, blank=True, null=True)
    route = models.CharField(max_length=100, blank=True, null=True)
    formulation = models.CharField(max_length=255, blank=True, null=True)
    indication = models.TextField(blank=True, null=True)
    contraindications = models.TextField(blank=True, null=True)
    precautions = models.TextField(blank=True, null=True)
    drug_interactions = models.TextField(blank=True, null=True)
    side_effects = models.TextField(blank=True, null=True)
    storage_conditions = models.CharField(max_length=255, blank=True, null=True)
    age_suitability = models.CharField(max_length=100, blank=True, null=True)
    pregnancy_caution = models.BooleanField(default=False)
    prescription_required = models.BooleanField(default=False)
    controlled_status = models.CharField(max_length=50, blank=True, null=True)
    importer = models.CharField(max_length=255, blank=True, null=True)
    regulatory_info = models.TextField(blank=True, null=True)
    image_url = models.URLField(max_length=500, blank=True, null=True)
    notes = models.TextField(blank=True, null=True)

    class Meta:
        unique_together = [('organization', 'sku')]
        indexes = [
            models.Index(fields=['organization', 'sku']),
            models.Index(fields=['organization', 'barcode']),
            models.Index(fields=['organization', 'name']),
        ]
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.sku})"


class ProductBranch(BaseModel):
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name='product_branches'
    )
    branch = models.ForeignKey(
        Branch, on_delete=models.CASCADE, related_name='branch_products'
    )
    reorder_level = models.IntegerField(null=True, blank=True)
    settings = models.JSONField(default=dict, blank=True)

    class Meta:
        unique_together = [('product', 'branch')]
        ordering = ['-created_at']


class ProductDocument(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name='documents'
    )
    name = models.CharField(max_length=255)
    file_path = models.CharField(max_length=500)
    document_type = models.CharField(max_length=50, blank=True, null=True)
    uploaded_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
