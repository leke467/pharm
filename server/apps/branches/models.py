from django.db import models
from apps.core.models import BaseModel
from apps.organizations.models import Organization

class Branch(BaseModel):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='branches')
    name = models.CharField(max_length=255)
    code = models.CharField(max_length=20)
    address = models.TextField(blank=True, null=True)
    phone = models.CharField(max_length=50, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    uses_storage_locations = models.BooleanField(default=False)
    initial_stock_loaded = models.BooleanField(default=False)
    settings = models.JSONField(default=dict)

    class Meta:
        unique_together = [('organization', 'code')]
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} ({self.code})"

class Device(BaseModel):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='devices')
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name='devices')
    name = models.CharField(max_length=255)
    code = models.CharField(max_length=5)
    device_identifier = models.CharField(max_length=255, unique=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = [('branch', 'code')]
        ordering = ['-created_at']

    def __str__(self):
        return self.name
