from django.core.management.base import BaseCommand
from apps.audit.services import archive_old_audit_events


class Command(BaseCommand):
    help = "Archives or prunes AuditEvent records exceeding the organization retention policy."

    def add_arguments(self, parser):
        parser.add_argument(
            "--organization-id",
            type=str,
            help="Optional UUID of organization to scope the audit archival.",
        )
        parser.add_argument(
            "--retention-days",
            type=int,
            help="Override retention period in days.",
        )

    def handle(self, *args, **options):
        org_id = options.get("organization_id")
        days = options.get("retention_days")
        count = archive_old_audit_events(organization_id=org_id, retention_days=days)
        self.stdout.write(
            self.style.SUCCESS(f"Successfully pruned/archived {count} audit events.")
        )
