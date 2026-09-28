import json
from sqlalchemy import func
from desktop.app.db.models import BranchInventory, InventoryAlert, InventoryMovement
from desktop.app.services.base_service import BaseService
from shared.enums import InventoryAlertType


class ReconciliationService(BaseService):
    """
    Local Inventory Ledger Reconciliation Service (Architecture Plan §3.3).
    Verifies that BranchInventory.quantity == SUM(InventoryMovement.quantity_change)
    for each local (branch, batch, storage_location).
    Discrepancies generate an InventoryAlert(type=RECONCILIATION_MISMATCH) for manual review.
    Discrepancies are NEVER auto-fixed.
    """

    def reconcile_branch_inventory(self, branch_id: str) -> list[dict]:
        discrepancies = []

        with self.transaction() as db:
            inventories = (
                db.query(BranchInventory)
                .filter(BranchInventory.branch_id == branch_id)
                .all()
            )

            for bi in inventories:
                query = db.query(
                    func.coalesce(func.sum(InventoryMovement.quantity_change), 0)
                ).filter(
                    InventoryMovement.branch_id == bi.branch_id,
                    InventoryMovement.batch_id == bi.batch_id,
                )

                if bi.storage_location_id:
                    query = query.filter(
                        InventoryMovement.storage_location_id == bi.storage_location_id
                    )
                else:
                    query = query.filter(
                        InventoryMovement.storage_location_id.is_(None)
                    )

                movement_sum = query.scalar() or 0

                if bi.quantity != movement_sum:
                    details = {
                        "branch_inventory_id": bi.id,
                        "recorded_quantity": bi.quantity,
                        "movement_sum": movement_sum,
                        "discrepancy": bi.quantity - movement_sum,
                        "storage_location_id": bi.storage_location_id,
                    }
                    alert = InventoryAlert(
                        organization_id=bi.organization_id,
                        branch_id=bi.branch_id,
                        batch_id=bi.batch_id,
                        alert_type=InventoryAlertType.RECONCILIATION_MISMATCH.value,
                        details=json.dumps(details),
                    )
                    db.add(alert)
                    discrepancies.append(details)

            db.flush()

        return discrepancies
