import uuid
from django.core.exceptions import ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from apps.core.models import BaseModel, TimestampedModel
from apps.organizations.models import Organization
from apps.branches.models import Branch, Device
from apps.products.models import Product, Supplier
from apps.users.models import User
from shared.enums import BatchStatus, InventoryStatus


class Batch(TimestampedModel):
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name='batches'
    )
    product = models.ForeignKey(
        Product, on_delete=models.PROTECT, related_name='batches'
    )
    batch_number = models.CharField(max_length=100)
    manufacturing_date = models.DateField(null=True, blank=True)
    expiry_date = models.DateField()
    purchase_price = models.DecimalField(max_digits=12, decimal_places=2)
    supplier = models.ForeignKey(
        Supplier,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='batches',
    )
    invoice_reference = models.CharField(max_length=100, blank=True, default='')
    received_date = models.DateField()
    status = models.CharField(
        max_length=20,
        default=BatchStatus.ACTIVE.value,
    )
    regulatory_metadata = models.JSONField(
        null=True, blank=True, encoder=DjangoJSONEncoder
    )
    notes = models.TextField(blank=True, default='')

    class Meta:
        unique_together = [('product', 'batch_number')]
        indexes = [
            models.Index(fields=['product', 'expiry_date']),
            models.Index(fields=['product', 'batch_number']),
        ]
        ordering = ['expiry_date', 'received_date']

    def __str__(self):
        return f"{self.product.name} - {self.batch_number}"


class StorageLocation(BaseModel):
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name='storage_locations'
    )
    branch = models.ForeignKey(
        Branch, on_delete=models.CASCADE, related_name='storage_locations'
    )
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default='')
    location_type = models.CharField(max_length=50, blank=True, default='')

    class Meta:
        unique_together = [('branch', 'name')]
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.branch.code})"


class StorageLocationAssignment(BaseModel):
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name='storage_location_assignments',
    )
    storage_location = models.ForeignKey(
        StorageLocation, on_delete=models.CASCADE, related_name='assignments'
    )
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='storage_assignments'
    )
    branch = models.ForeignKey(
        Branch, on_delete=models.CASCADE, related_name='storage_assignments'
    )
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    assigned_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )

    class Meta:
        ordering = ['-start_date']


class BranchInventory(TimestampedModel):
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name='branch_inventories'
    )
    branch = models.ForeignKey(
        Branch, on_delete=models.CASCADE, related_name='inventories'
    )
    batch = models.ForeignKey(
        Batch, on_delete=models.PROTECT, related_name='branch_inventories'
    )
    storage_location = models.ForeignKey(
        StorageLocation,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='inventories',
    )
    quantity = models.IntegerField(default=0)
    reserved_quantity = models.IntegerField(default=0)
    reorder_level = models.IntegerField(null=True, blank=True)
    status = models.CharField(
        max_length=20,
        default=InventoryStatus.AVAILABLE.value,
    )
    last_counted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = [('branch', 'batch', 'storage_location')]
        indexes = [
            models.Index(fields=['branch', 'status']),
            models.Index(fields=['branch', 'batch']),
        ]
        ordering = ['-updated_at']

    @property
    def available_quantity(self) -> int:
        return self.quantity - self.reserved_quantity


class InventoryMovement(models.Model):
    """
    Immutable append-only inventory movement ledger (Architecture Decision #15).
    No UPDATE or DELETE is ever permitted on this table.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name='inventory_movements'
    )
    branch = models.ForeignKey(
        Branch, on_delete=models.CASCADE, related_name='inventory_movements'
    )
    batch = models.ForeignKey(
        Batch, on_delete=models.PROTECT, related_name='movements'
    )
    storage_location = models.ForeignKey(
        StorageLocation,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='movements',
    )
    movement_type = models.CharField(max_length=30)
    quantity_change = models.IntegerField()
    quantity_before = models.IntegerField()
    quantity_after = models.IntegerField()
    reference_type = models.CharField(max_length=50)
    reference_id = models.UUIDField()
    user = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name='inventory_movements'
    )
    device = models.ForeignKey(
        Device,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='inventory_movements',
    )
    notes = models.TextField(blank=True, default='')
    local_timestamp = models.DateTimeField()
    server_timestamp = models.DateTimeField(null=True, blank=True)
    is_offline = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['branch', 'batch', 'created_at']),
            models.Index(fields=['reference_type', 'reference_id']),
        ]
        ordering = ['-created_at']

    def save(self, *args, **kwargs):
        if not self._state.adding and InventoryMovement.objects.filter(pk=self.pk).exists():
            raise ValidationError(
                "InventoryMovement records are immutable and cannot be updated."
            )
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError(
            "InventoryMovement records are immutable and cannot be deleted."
        )


class InventoryAlert(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name='inventory_alerts'
    )
    branch = models.ForeignKey(
        Branch, on_delete=models.CASCADE, related_name='inventory_alerts'
    )
    batch = models.ForeignKey(
        Batch, on_delete=models.CASCADE, related_name='alerts'
    )
    alert_type = models.CharField(max_length=30)
    details = models.JSONField(default=dict, encoder=DjangoJSONEncoder)
    is_resolved = models.BooleanField(default=False)
    resolved_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']


class StockCount(TimestampedModel):
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name='stock_counts'
    )
    branch = models.ForeignKey(
        Branch, on_delete=models.CASCADE, related_name='stock_counts'
    )
    device = models.ForeignKey(
        Device, on_delete=models.SET_NULL, null=True, blank=True, related_name='stock_counts'
    )
    storage_location = models.ForeignKey(
        StorageLocation, on_delete=models.SET_NULL, null=True, blank=True, related_name='stock_counts'
    )
    count_type = models.CharField(max_length=30, default='FULL_BRANCH')
    status = models.CharField(max_length=20, default='DRAFT')
    started_by = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name='started_stock_counts'
    )
    started_at = models.DateTimeField()
    submitted_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='submitted_stock_counts'
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_stock_counts'
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True, default='')

    class Meta:
        ordering = ['-started_at']


class StockCountItem(TimestampedModel):
    stock_count = models.ForeignKey(
        StockCount, on_delete=models.CASCADE, related_name='items'
    )
    product = models.ForeignKey(
        Product, on_delete=models.PROTECT, related_name='stock_count_items'
    )
    batch = models.ForeignKey(
        Batch, on_delete=models.PROTECT, related_name='stock_count_items'
    )
    storage_location = models.ForeignKey(
        StorageLocation, on_delete=models.SET_NULL, null=True, blank=True, related_name='stock_count_items'
    )
    system_quantity = models.IntegerField()
    counted_quantity = models.IntegerField()
    variance = models.IntegerField()
    current_quantity_at_approval = models.IntegerField(null=True, blank=True)
    approval_status = models.CharField(max_length=20, default='PENDING')
    rejection_reason = models.TextField(blank=True, default='')

    class Meta:
        ordering = ['created_at']

