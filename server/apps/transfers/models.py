import uuid
from django.db import models
from django.utils import timezone

from apps.core.models import TimestampedModel
from apps.organizations.models import Organization
from apps.branches.models import Branch
from apps.products.models import Product
from apps.inventory.models import Batch
from apps.users.models import User
from shared.enums import TransferStatus


class StockTransfer(TimestampedModel):
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name='stock_transfers'
    )
    source_branch = models.ForeignKey(
        Branch, on_delete=models.CASCADE, related_name='transfers_out'
    )
    destination_branch = models.ForeignKey(
        Branch, on_delete=models.CASCADE, related_name='transfers_in'
    )
    status = models.CharField(
        max_length=20, default=TransferStatus.REQUESTED.value
    )
    requested_by = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name='requested_transfers'
    )
    approved_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_transfers'
    )
    dispatched_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='dispatched_transfers'
    )
    received_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='received_transfers'
    )
    requested_at = models.DateTimeField(default=timezone.now)
    approved_at = models.DateTimeField(null=True, blank=True)
    dispatched_at = models.DateTimeField(null=True, blank=True)
    received_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True, default='')

    class Meta:
        ordering = ['-requested_at', '-created_at']

    def __str__(self):
        return f"Transfer {self.id} ({self.source_branch.code} -> {self.destination_branch.code}: {self.status})"


class StockTransferItem(TimestampedModel):
    stock_transfer = models.ForeignKey(
        StockTransfer, on_delete=models.CASCADE, related_name='items'
    )
    product = models.ForeignKey(
        Product, on_delete=models.PROTECT, related_name='transfer_items'
    )
    batch = models.ForeignKey(
        Batch, on_delete=models.PROTECT, related_name='transfer_items'
    )
    quantity = models.IntegerField()

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"{self.product.name} (Batch {self.batch.batch_number}): {self.quantity}"
