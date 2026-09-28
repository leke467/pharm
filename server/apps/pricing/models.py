import uuid
from django.db import models
from django.utils import timezone
from apps.core.models import TimestampedModel
from apps.organizations.models import Organization
from apps.branches.models import Branch
from apps.products.models import Product
from apps.users.models import User


class Price(TimestampedModel):
    """
    Product selling price record (Architecture Plan §2.3 & §10).
    - branch=None: organization-wide default price
    - branch=X: branch-specific override price
    Resolution order: Branch override (is_current=True) -> Org default (is_current=True).
    """

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name='prices'
    )
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name='prices'
    )
    branch = models.ForeignKey(
        Branch,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='prices',
    )
    selling_price = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=10, default='NGN')
    is_current = models.BooleanField(default=True)
    version = models.IntegerField(default=1)
    effective_from = models.DateTimeField(default=timezone.now)
    effective_to = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )
    sync_status = models.CharField(max_length=20, default='SYNCED')

    class Meta:
        indexes = [
            models.Index(fields=['product', 'branch', 'is_current']),
        ]
        ordering = ['-version', '-created_at']

    def __str__(self):
        scope = self.branch.code if self.branch else "ORG"
        return f"{self.product.sku} @ {scope}: {self.currency} {self.selling_price} (v{self.version})"


class PriceHistory(models.Model):
    """
    Immutable audit ledger of price changes (Architecture Plan §2.3 & §11).
    No UPDATE or DELETE is allowed on this model.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name='price_histories'
    )
    price = models.ForeignKey(
        Price, on_delete=models.CASCADE, related_name='history'
    )
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name='price_histories'
    )
    branch = models.ForeignKey(
        Branch,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='price_histories',
    )
    old_price = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    new_price = models.DecimalField(max_digits=12, decimal_places=2)
    changed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )
    change_reason = models.TextField(blank=True, default='')
    version = models.IntegerField()
    local_timestamp = models.DateTimeField(default=timezone.now)
    server_timestamp = models.DateTimeField(auto_now_add=True)
    sync_status = models.CharField(max_length=20, default='SYNCED')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-version', '-created_at']

    def __str__(self):
        return f"{self.product.name} v{self.version}: {self.old_price} -> {self.new_price}"

