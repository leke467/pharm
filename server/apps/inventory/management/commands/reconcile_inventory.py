from django.core.management.base import BaseCommand
from apps.inventory.services import reconcile_branch_inventory


class Command(BaseCommand):
    help = "Verifies inventory ledger invariant (BranchInventory.quantity == SUM(InventoryMovement)) and generates alerts for mismatches."

    def add_arguments(self, parser):
        parser.add_argument(
            "--organization-id",
            type=str,
            help="Optional UUID of organization to scope the reconciliation.",
        )
        parser.add_argument(
            "--branch-id",
            type=str,
            help="Optional UUID of branch to scope the reconciliation.",
        )

    def handle(self, *args, **options):
        org_id = options.get("organization_id")
        br_id = options.get("branch_id")
        alerts = reconcile_branch_inventory(organization_id=org_id, branch_id=br_id)
        if alerts:
            self.stdout.write(
                self.style.WARNING(
                    f"Reconciliation completed with {len(alerts)} discrepancy alerts generated."
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS("Reconciliation completed successfully. All ledger movements match balances.")
            )
