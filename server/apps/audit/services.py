from datetime import timedelta
from django.utils import timezone
from apps.audit.models import AuditEvent
from apps.organizations.models import Organization


def archive_old_audit_events(organization_id=None, retention_days=None) -> int:
    """
    Archives or prunes AuditEvent records exceeding the organization's retention policy (Architecture Plan §15.2, §16).
    Default retention is 730 days (2 years) unless specified in Organization settings.
    """
    total_pruned = 0
    now = timezone.now()

    if organization_id:
        orgs = Organization.objects.filter(id=organization_id)
    else:
        orgs = Organization.objects.all()

    for org in orgs:
        days = retention_days
        if days is None:
            settings = org.settings or {}
            days = int(settings.get("audit_retention_days", 730))

        cutoff = now - timedelta(days=days)
        deleted, _ = AuditEvent.objects.filter(
            organization=org,
            created_at__lte=cutoff,
        ).delete()
        total_pruned += deleted

    return total_pruned
