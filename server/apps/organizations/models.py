from django.db import models
from apps.core.models import BaseModel


def default_settings():
    return {
        "default_currency": "NGN",
        "offline_session_max_hours": 72,
        "offline_login_max_days": 7,
        "audit_retention_days": 90,
    }


class Organization(BaseModel):
    name = models.CharField(max_length=255)
    code = models.CharField(max_length=50, unique=True)
    address = models.TextField(blank=True)
    phone = models.CharField(max_length=50, blank=True)
    email = models.EmailField(blank=True)
    logo_url = models.URLField(blank=True)
    settings = models.JSONField(default=default_settings)

    def __str__(self):
        return self.name
