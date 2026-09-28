import uuid
from decimal import Decimal
from django.db import models
from apps.core.models import TimestampedModel
from apps.organizations.models import Organization
from apps.branches.models import Branch
from apps.products.models import Supplier, Product
from apps.inventory.models import Batch
from apps.users.models import User
from shared.enums import PaymentStatus, ReceivingStatus


class Purchase(TimestampedModel):
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name='purchases'
    )
    branch = models.ForeignKey(
        Branch, on_delete=models.CASCADE, related_name='purchases'
    )
    supplier = models.ForeignKey(
        Supplier, on_delete=models.PROTECT, related_name='purchases'
    )
    user = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name='purchases'
    )
    purchase_reference = models.CharField(max_length=100)
    invoice_number = models.CharField(max_length=100, null=True, blank=True)
    purchase_date = models.DateField()
    subtotal = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'))
    discount_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'))
    total = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'))
    payment_status = models.CharField(
        max_length=20, default=PaymentStatus.UNPAID.value
    )
    receiving_status = models.CharField(
        max_length=20, default=ReceivingStatus.PENDING.value
    )
    notes = models.TextField(blank=True, default='')

    class Meta:
        ordering = ['-purchase_date', '-created_at']
        unique_together = [('organization', 'purchase_reference')]


class PurchaseItem(TimestampedModel):
    purchase = models.ForeignKey(
        Purchase, on_delete=models.CASCADE, related_name='items'
    )
    product = models.ForeignKey(
        Product, on_delete=models.PROTECT, related_name='purchase_items'
    )
    batch = models.ForeignKey(
        Batch, on_delete=models.SET_NULL, null=True, blank=True, related_name='purchase_items'
    )
    quantity_ordered = models.IntegerField()
    quantity_received = models.IntegerField(default=0)
    purchase_price = models.DecimalField(max_digits=12, decimal_places=2)
    selling_price = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal('0.00')
    )
    discount = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal('0.00')
    )
    line_total = models.DecimalField(max_digits=14, decimal_places=2)

    class Meta:
        ordering = ['created_at']


class PurchasePayment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    purchase = models.ForeignKey(
        Purchase, on_delete=models.CASCADE, related_name='payments'
    )
    payment_method = models.CharField(max_length=50)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    reference = models.CharField(max_length=100, null=True, blank=True)
    payment_date = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['payment_date', 'created_at']
