import uuid
from django.db import models


class TimestampedModel(models.Model):
    """Abstract base model with UUID v4 primary key and UTC timestamps."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class BaseModel(TimestampedModel):
    """
    Abstract base model for all standard business entities.
    Enforces UUID v4 primary key, UTC timestamps, and soft-delete via is_active.
    """
    is_active = models.BooleanField(default=True)

    class Meta:
        abstract = True
        ordering = ['-created_at']

    def soft_delete(self):
        """Soft-delete record by marking is_active=False (nothing is hard-deleted)."""
        self.is_active = False
        self.save(update_fields=['is_active', 'updated_at'])
