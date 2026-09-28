import uuid
from django.db import models
from apps.core.models import BaseModel, TimestampedModel
from apps.organizations.models import Organization
from apps.branches.models import Branch
from apps.users.models import User
from shared.enums import ExpenseStatus


class ExpenseCategory(BaseModel):
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name='expense_categories'
    )
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, default='')

    class Meta:
        ordering = ['name']
        unique_together = [('organization', 'name')]

    def __str__(self):
        return self.name


class Expense(TimestampedModel):
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name='expenses'
    )
    branch = models.ForeignKey(
        Branch, on_delete=models.CASCADE, related_name='expenses'
    )
    expense_category = models.ForeignKey(
        ExpenseCategory, on_delete=models.PROTECT, related_name='expenses'
    )
    description = models.TextField()
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    payment_method = models.CharField(max_length=50, default='CASH')
    expense_date = models.DateField()
    created_by = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name='expenses_created'
    )
    approved_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='expenses_approved'
    )
    status = models.CharField(
        max_length=20, default=ExpenseStatus.PENDING_APPROVAL.value
    )
    attachment_path = models.CharField(max_length=500, null=True, blank=True)
    notes = models.TextField(blank=True, default='')

    class Meta:
        ordering = ['-expense_date', '-created_at']

    def __str__(self):
        return f"{self.expense_category.name}: {self.amount} ({self.status})"
