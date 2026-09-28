import uuid
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db import models
from apps.core.models import TimestampedModel
from apps.organizations.models import Organization
from apps.branches.models import Branch, Device
from apps.products.models import Product
from apps.inventory.models import Batch
from apps.users.models import User
from shared.enums import SaleStatus, SaleReturnStatus


class Sale(TimestampedModel):
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name='sales'
    )
    branch = models.ForeignKey(
        Branch, on_delete=models.CASCADE, related_name='sales'
    )
    user = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name='sales'
    )
    device = models.ForeignKey(
        Device, on_delete=models.PROTECT, related_name='sales'
    )
    receipt_number = models.CharField(max_length=50)
    customer_name = models.CharField(max_length=255, null=True, blank=True)
    customer_phone = models.CharField(max_length=50, null=True, blank=True)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2)
    discount_amount = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal('0.00')
    )
    tax_amount = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal('0.00')
    )
    total = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(
        max_length=20, default=SaleStatus.COMPLETED.value
    )
    sale_date = models.DateTimeField()
    server_received_at = models.DateTimeField(null=True, blank=True)
    is_offline = models.BooleanField(default=False)
    sync_status = models.CharField(max_length=20, default='SYNCED')
    notes = models.TextField(blank=True, default='')

    class Meta:
        unique_together = [('branch', 'receipt_number')]
        indexes = [
            models.Index(fields=['branch', 'sale_date']),
            models.Index(fields=['branch', 'receipt_number']),
        ]
        ordering = ['-sale_date']

    def __str__(self):
        return f"{self.receipt_number} ({self.total})"

    def delete(self, *args, **kwargs):
        raise ValidationError(
            "Sale records cannot be deleted. Use VOID or RETURN workflows."
        )


class SaleItem(models.Model):
    """
    Immutable POS line item (Architecture Plan §2.3 & §7.3).
    `unit_price` is frozen at add-to-cart time and can never be modified.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    sale = models.ForeignKey(
        Sale, on_delete=models.CASCADE, related_name='items'
    )
    product = models.ForeignKey(
        Product, on_delete=models.PROTECT, related_name='sale_items'
    )
    batch = models.ForeignKey(
        Batch, on_delete=models.PROTECT, related_name='sale_items'
    )
    quantity = models.IntegerField()
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    discount_amount = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal('0.00')
    )
    line_total = models.DecimalField(max_digits=12, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def save(self, *args, **kwargs):
        if not self._state.adding and SaleItem.objects.filter(pk=self.pk).exists():
            raise ValidationError(
                "SaleItem records are immutable after creation."
            )
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError(
            "SaleItem records are immutable and cannot be deleted."
        )


class Payment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    sale = models.ForeignKey(
        Sale, on_delete=models.CASCADE, related_name='payments'
    )
    payment_method = models.CharField(max_length=50)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    reference = models.CharField(max_length=100, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']


class Receipt(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    sale = models.OneToOneField(
        Sale, on_delete=models.CASCADE, related_name='receipt'
    )
    receipt_number = models.CharField(max_length=50)
    printed_at = models.DateTimeField()
    printer_name = models.CharField(max_length=100, null=True, blank=True)
    reprint_count = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-printed_at']


class SaleReturn(TimestampedModel):
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name='sale_returns'
    )
    original_sale = models.ForeignKey(
        Sale, on_delete=models.PROTECT, related_name='returns'
    )
    branch = models.ForeignKey(
        Branch, on_delete=models.CASCADE, related_name='sale_returns'
    )
    user = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name='sale_returns'
    )
    device = models.ForeignKey(
        Device, on_delete=models.PROTECT, related_name='sale_returns'
    )
    return_date = models.DateTimeField()
    reason = models.TextField()
    refund_amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(
        max_length=20, default=SaleReturnStatus.COMPLETED.value
    )
    approved_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )

    class Meta:
        ordering = ['-return_date']

    def delete(self, *args, **kwargs):
        raise ValidationError("SaleReturn records cannot be deleted.")


class SaleReturnItem(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    sale_return = models.ForeignKey(
        SaleReturn, on_delete=models.CASCADE, related_name='items'
    )
    sale_item = models.ForeignKey(
        SaleItem, on_delete=models.PROTECT, related_name='return_items'
    )
    product = models.ForeignKey(
        Product, on_delete=models.PROTECT, related_name='sale_return_items'
    )
    batch = models.ForeignKey(
        Batch, on_delete=models.PROTECT, related_name='sale_return_items'
    )
    quantity = models.IntegerField()
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    line_total = models.DecimalField(max_digits=12, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def delete(self, *args, **kwargs):
        raise ValidationError("SaleReturnItem records cannot be deleted.")

