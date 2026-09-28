from django.core.management.base import BaseCommand
from apps.sync.services import cleanup_expired_sync_deliveries


class Command(BaseCommand):
    help = "Prunes expired SyncDelivery records older than 90 days or past their expiration time."

    def add_arguments(self, parser):
        parser.add_argument(
            "--organization-id",
            type=str,
            help="Optional UUID of organization to scope the cleanup.",
        )

    def handle(self, *args, **options):
        org_id = options.get("organization_id")
        count = cleanup_expired_sync_deliveries(organization_id=org_id)
        self.stdout.write(
            self.style.SUCCESS(f"Successfully pruned {count} expired SyncDelivery records.")
        )
