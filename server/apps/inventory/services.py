from django.db import models
from apps.inventory.models import BranchInventory, InventoryMovement, InventoryAlert
from shared.enums import InventoryAlertType


def reconcile_branch_inventory(organization_id=None, branch_id=None) -> list[InventoryAlert]:
    """
    Weekly automated inventory ledger reconciliation job (Architecture Plan §3.3).
    Verifies the invariant:
        BranchInventory.quantity == SUM(InventoryMovement.quantity_change)
    For each (branch, batch, storage_location).
    Discrepancies generate an InventoryAlert(type='RECONCILIATION_MISMATCH') for manual review.
    They do NOT auto-fix the recorded quantity.
    """
    qs = BranchInventory.objects.select_related('organization', 'branch', 'batch', 'storage_location').all()
    if organization_id:
        qs = qs.filter(organization_id=organization_id)
    if branch_id:
        qs = qs.filter(branch_id=branch_id)

    discrepancies = []

    for bi in qs:
        movement_filter = {
            'branch': bi.branch,
            'batch': bi.batch,
        }
        if bi.storage_location:
            movement_filter['storage_location'] = bi.storage_location
        else:
            movement_filter['storage_location__isnull'] = True

        movements_sum = InventoryMovement.objects.filter(**movement_filter).aggregate(
            total=models.Sum('quantity_change')
        )['total'] or 0

        if bi.quantity != movements_sum:
            alert = InventoryAlert.objects.create(
                organization=bi.organization,
                branch=bi.branch,
                batch=bi.batch,
                alert_type=InventoryAlertType.RECONCILIATION_MISMATCH.value,
                details={
                    "branch_inventory_id": str(bi.id),
                    "recorded_quantity": bi.quantity,
                    "movement_sum": movements_sum,
                    "discrepancy": bi.quantity - movements_sum,
                    "storage_location_id": str(bi.storage_location_id) if bi.storage_location_id else None,
                },
            )
            discrepancies.append(alert)

    return discrepancies
