import json
import uuid
from datetime import datetime, timezone
from sqlalchemy import func
from desktop.app.db.models import (
    Branch,
    Product,
    Batch,
    StorageLocation,
    BranchInventory,
    StockCount,
    StockCountItem,
    SyncEvent,
)
from desktop.app.domain.exceptions import ValidationError
from desktop.app.services.base_service import BaseService
from desktop.app.services.inventory_service import InventoryService
from desktop.app.sync.sync_engine import register_download_handler
from shared.enums import (
    AuditAction,
    ApprovalStatus,
    MovementType,
    PermissionCode,
    StockCountStatus,
    StockCountType,
    SyncOperation,
    SYNC_DEPENDENCY_LEVELS,
    SYNC_SCHEMA_VERSION,
)


class StockCountService(BaseService):
    """
    Offline-first Stock Count & Approval Service (Architecture Plan §9).
    """

    def __init__(self, db_manager):
        super().__init__(db_manager)
        self.inventory_service = InventoryService(db_manager)

    def start_stock_count(
        self,
        user_session,
        count_type: str = "FULL_BRANCH",
        storage_location_id: str | None = None,
        notes: str = "",
    ) -> StockCount:
        """
        Starts a stock count session.
        Enforces local multi-device conflict guard: only one IN_PROGRESS or DRAFT count
        per (branch, storage_location) scope is allowed at a time.
        """
        self.require_permission(user_session, PermissionCode.STOCK_COUNTS_PERFORM.value)
        corr_id = str(uuid.uuid4())
        now_local = datetime.now().astimezone().isoformat()
        now_utc = datetime.now(timezone.utc).isoformat()

        with self.transaction() as db:
            dev = self.resolve_device(db, user_session.branch_id, getattr(user_session, "device_id", None))
            eff_device_id = dev.id if dev else None
            if not getattr(user_session, "device_id", None) and eff_device_id:
                user_session.device_id = eff_device_id

            scope_q = db.query(StockCount).filter(
                StockCount.organization_id == user_session.organization_id,
                StockCount.branch_id == user_session.branch_id,
                StockCount.status.in_([StockCountStatus.DRAFT.value, StockCountStatus.IN_PROGRESS.value]),
            )
            if storage_location_id:
                scope_q = scope_q.filter(StockCount.storage_location_id == storage_location_id)
            if scope_q.first():
                raise ValidationError("A stock count is already in progress for this scope.")

            sc = StockCount(
                id=str(uuid.uuid4()),
                organization_id=user_session.organization_id,
                branch_id=user_session.branch_id,
                device_id=eff_device_id,
                storage_location_id=storage_location_id,
                count_type=count_type,
                status=StockCountStatus.IN_PROGRESS.value,
                started_by_id=user_session.user_id,
                started_at=now_local,
                notes=notes or "",
                created_at=now_utc,
                updated_at=now_utc,
            )
            db.add(sc)
            db.flush()

            sc_sync = SyncEvent(
                id=str(uuid.uuid4()),
                branch_id=user_session.branch_id,
                device_id=eff_device_id or user_session.device_id,
                entity_type="stock_count",
                entity_id=sc.id,
                operation=SyncOperation.CREATE.value,
                payload=json.dumps({
                    "id": sc.id,
                    "organization_id": sc.organization_id,
                    "branch_id": sc.branch_id,
                    "device_id": sc.device_id,
                    "storage_location_id": sc.storage_location_id,
                    "count_type": sc.count_type,
                    "status": sc.status,
                    "started_by_id": sc.started_by_id,
                    "started_at": sc.started_at,
                    "notes": sc.notes,
                }),
                correlation_id=corr_id,
                dependency_level=SYNC_DEPENDENCY_LEVELS["stock_count"],
                schema_version=SYNC_SCHEMA_VERSION,
                local_created_at=now_local,
                status="PENDING",
            )
            db.add(sc_sync)

            self.record_audit_and_sync(
                db_session=db,
                user_session=user_session,
                action=AuditAction.STOCK_COUNT_STARTED.value,
                entity_type="stock_count",
                entity_id=sc.id,
                operation=SyncOperation.CREATE.value,
                payload={"id": sc.id, "count_type": sc.count_type, "status": sc.status},
                correlation_id=corr_id,
                transaction_id=sc.id,
            )
            db.expunge(sc)
            return sc

    def submit_stock_count(
        self,
        user_session,
        stock_count_id: str,
        items: list[dict],
        notes: str | None = None,
    ) -> dict:
        """
        Submits physical counts against batches in the count session.
        Items: `[{'batch_id': '...', 'counted_quantity': 15, 'storage_location_id': None}]`.
        Calculates variance = counted_quantity - system_quantity.
        """
        self.require_permission(user_session, PermissionCode.STOCK_COUNTS_PERFORM.value)
        if not items:
            raise ValidationError("At least one count item is required to submit.")

        corr_id = str(uuid.uuid4())
        now_local = datetime.now().astimezone().isoformat()
        now_utc = datetime.now(timezone.utc).isoformat()

        with self.transaction() as db:
            sc = (
                db.query(StockCount)
                .filter_by(id=stock_count_id, organization_id=user_session.organization_id)
                .first()
            )
            if not sc:
                raise ValidationError("Stock count not found.")
            if sc.status != StockCountStatus.IN_PROGRESS.value:
                raise ValidationError(
                    f"Cannot submit a stock count with status '{sc.status}'."
                )

            # Clear previous draft items if any
            db.query(StockCountItem).filter_by(stock_count_id=sc.id).delete()

            for it in items:
                batch = (
                    db.query(Batch)
                    .filter_by(id=it["batch_id"], organization_id=user_session.organization_id)
                    .first()
                )
                if not batch:
                    raise ValidationError(f"Batch {it['batch_id']} not found.")

                loc_id = it.get("storage_location_id") or sc.storage_location_id
                inv = (
                    db.query(BranchInventory)
                    .filter_by(
                        organization_id=user_session.organization_id,
                        branch_id=sc.branch_id,
                        batch_id=batch.id,
                        storage_location_id=loc_id,
                    )
                    .first()
                )
                if not inv and loc_id is None:
                    inv = (
                        db.query(BranchInventory)
                        .filter_by(
                            organization_id=user_session.organization_id,
                            branch_id=sc.branch_id,
                            batch_id=batch.id,
                        )
                        .order_by(BranchInventory.quantity.desc())
                        .first()
                    )
                    if inv and inv.storage_location_id:
                        loc_id = inv.storage_location_id
                sys_qty = inv.quantity if inv else 0
                cnt_qty = int(it["counted_quantity"])
                variance = cnt_qty - sys_qty

                sci = StockCountItem(
                    id=str(uuid.uuid4()),
                    stock_count_id=sc.id,
                    product_id=batch.product_id,
                    batch_id=batch.id,
                    storage_location_id=loc_id,
                    system_quantity=sys_qty,
                    counted_quantity=cnt_qty,
                    variance=variance,
                    approval_status=ApprovalStatus.PENDING.value,
                    created_at=now_utc,
                    updated_at=now_utc,
                )
                db.add(sci)
                db.flush()

                sci_sync = SyncEvent(
                    id=str(uuid.uuid4()),
                    branch_id=sc.branch_id,
                    device_id=user_session.device_id,
                    entity_type="stock_count_item",
                    entity_id=sci.id,
                    operation=SyncOperation.CREATE.value,
                    payload=json.dumps({
                        "id": sci.id,
                        "stock_count_id": sci.stock_count_id,
                        "product_id": sci.product_id,
                        "batch_id": sci.batch_id,
                        "storage_location_id": sci.storage_location_id,
                        "system_quantity": sci.system_quantity,
                        "counted_quantity": sci.counted_quantity,
                        "variance": sci.variance,
                        "approval_status": sci.approval_status,
                    }),
                    correlation_id=corr_id,
                    dependency_level=SYNC_DEPENDENCY_LEVELS["stock_count_item"],
                    schema_version=SYNC_SCHEMA_VERSION,
                    local_created_at=now_local,
                    status="PENDING",
                )
                db.add(sci_sync)

            sc.status = StockCountStatus.SUBMITTED.value
            sc.submitted_by_id = user_session.user_id
            sc.submitted_at = now_local
            if notes:
                sc.notes = notes
            sc.updated_at = now_utc
            db.flush()

            sc_update_sync = SyncEvent(
                id=str(uuid.uuid4()),
                branch_id=sc.branch_id,
                device_id=user_session.device_id,
                entity_type="stock_count",
                entity_id=sc.id,
                operation=SyncOperation.UPDATE.value,
                payload=json.dumps({
                    "id": sc.id,
                    "organization_id": sc.organization_id,
                    "branch_id": sc.branch_id,
                    "device_id": sc.device_id,
                    "storage_location_id": sc.storage_location_id,
                    "count_type": sc.count_type,
                    "status": sc.status,
                    "started_by_id": sc.started_by_id,
                    "started_at": sc.started_at,
                    "submitted_by_id": sc.submitted_by_id,
                    "submitted_at": sc.submitted_at,
                    "notes": sc.notes,
                }),
                correlation_id=corr_id,
                dependency_level=SYNC_DEPENDENCY_LEVELS["stock_count"],
                schema_version=SYNC_SCHEMA_VERSION,
                local_created_at=now_local,
                status="PENDING",
            )
            db.add(sc_update_sync)

            self.record_audit_and_sync(
                db_session=db,
                user_session=user_session,
                action=AuditAction.STOCK_COUNT_SUBMITTED.value,
                entity_type="stock_count",
                entity_id=sc.id,
                operation=SyncOperation.UPDATE.value,
                payload={"id": sc.id, "status": sc.status, "submitted_at": sc.submitted_at},
                correlation_id=corr_id,
                transaction_id=sc.id,
            )

            return {
                "stock_count_id": sc.id,
                "status": sc.status,
                "items_count": len(items),
                "correlation_id": corr_id,
            }

    def approve_stock_count(
        self,
        user_session,
        stock_count_id: str,
        reviews: list[dict],
        notes: str | None = None,
    ) -> dict:
        """
        Reviews and approves/rejects items in a SUBMITTED stock count.
        Reviews: `[{'stock_count_item_id': '...', 'action': 'APPROVE' / 'REJECT', 'rejection_reason': '...'}]`.
        Enforces:
        - `STOCK_COUNTS_APPROVE` permission.
        - Negative Quantity Guard (Plan §9.2): `current_quantity_at_approval + item.variance < 0` blocks approval!
        - Creates `InventoryMovement(COUNT_VARIANCE)` for approved non-zero variances.
        - Sets final status (`APPROVED`, `PARTIALLY_APPROVED`, or `REJECTED`).
        """
        self.require_permission(user_session, PermissionCode.STOCK_COUNTS_APPROVE.value)
        if not reviews:
            raise ValidationError("At least one item review is required.")

        corr_id = str(uuid.uuid4())
        now_local = datetime.now().astimezone().isoformat()
        now_utc = datetime.now(timezone.utc).isoformat()

        with self.transaction() as db:
            sc = (
                db.query(StockCount)
                .filter_by(id=stock_count_id, organization_id=user_session.organization_id)
                .first()
            )
            if not sc:
                raise ValidationError("Stock count not found.")
            if sc.status != StockCountStatus.SUBMITTED.value:
                raise ValidationError(
                    f"Cannot approve stock count in status '{sc.status}'."
                )

            items_map = {
                it.id: it
                for it in db.query(StockCountItem).filter_by(stock_count_id=sc.id).all()
            }

            for rev in reviews:
                it_id = str(rev["stock_count_item_id"])
                if it_id not in items_map:
                    raise ValidationError(
                        f"StockCountItem {it_id} does not belong to this count."
                    )
                item = items_map[it_id]
                action = rev["action"].upper()

                if action == "APPROVE":
                    inv = (
                        db.query(BranchInventory)
                        .filter_by(
                            organization_id=user_session.organization_id,
                            branch_id=sc.branch_id,
                            batch_id=item.batch_id,
                            storage_location_id=item.storage_location_id,
                        )
                        .first()
                    )
                    if not inv and item.storage_location_id is None:
                        inv = (
                            db.query(BranchInventory)
                            .filter_by(
                                organization_id=user_session.organization_id,
                                branch_id=sc.branch_id,
                                batch_id=item.batch_id,
                            )
                            .order_by(BranchInventory.quantity.desc())
                            .first()
                        )
                        if inv and inv.storage_location_id:
                            item.storage_location_id = inv.storage_location_id
                    curr_qty = inv.quantity if inv else 0
                    # Negative Quantity Guard (Architecture Plan §9.2)
                    if curr_qty + item.variance < 0:
                        raise ValidationError(
                            f"Approval blocked: live quantity ({curr_qty}) + variance ({item.variance}) < 0 for batch {item.batch_id}."
                        )

                    item.current_quantity_at_approval = curr_qty
                    item.approval_status = ApprovalStatus.APPROVED.value
                    item.updated_at = now_utc
                    db.flush()

                    if item.variance != 0:
                        self.inventory_service._apply_movement_in_tx(
                            db=db,
                            user_session=user_session,
                            branch_id=sc.branch_id,
                            batch_id=item.batch_id,
                            storage_location_id=item.storage_location_id,
                            movement_type=MovementType.COUNT_VARIANCE.value,
                            quantity_change=item.variance,
                            reference_type="stock_count",
                            reference_id=sc.id,
                            notes=f"Stock count variance adjustment: {item.variance}",
                            correlation_id=corr_id,
                            allow_negative=False,
                            emit_movement_sync=True,
                        )
                else:
                    item.approval_status = ApprovalStatus.REJECTED.value
                    item.rejection_reason = rev.get("rejection_reason", "Rejected by manager")
                    item.updated_at = now_utc
                    db.flush()

                sci_sync = SyncEvent(
                    id=str(uuid.uuid4()),
                    branch_id=sc.branch_id,
                    device_id=user_session.device_id,
                    entity_type="stock_count_item",
                    entity_id=item.id,
                    operation=SyncOperation.UPDATE.value,
                    payload=json.dumps({
                        "id": item.id,
                        "stock_count_id": sc.id,
                        "current_quantity_at_approval": item.current_quantity_at_approval,
                        "approval_status": item.approval_status,
                        "rejection_reason": item.rejection_reason,
                    }),
                    correlation_id=corr_id,
                    dependency_level=SYNC_DEPENDENCY_LEVELS["stock_count_item"],
                    schema_version=SYNC_SCHEMA_VERSION,
                    local_created_at=now_local,
                    status="PENDING",
                )
                db.add(sci_sync)

            all_items = list(items_map.values())
            appr_count = sum(1 for i in all_items if i.approval_status == ApprovalStatus.APPROVED.value)
            rej_count = sum(1 for i in all_items if i.approval_status == ApprovalStatus.REJECTED.value)

            if appr_count == len(all_items):
                sc.status = StockCountStatus.APPROVED.value
            elif rej_count == len(all_items):
                sc.status = StockCountStatus.REJECTED.value
            else:
                sc.status = StockCountStatus.PARTIALLY_APPROVED.value

            sc.approved_by_id = user_session.user_id
            sc.approved_at = now_local
            if notes:
                sc.notes = (sc.notes + "\n" + notes).strip()
            sc.updated_at = now_utc
            db.flush()

            sc_update_sync = SyncEvent(
                id=str(uuid.uuid4()),
                branch_id=sc.branch_id,
                device_id=user_session.device_id,
                entity_type="stock_count",
                entity_id=sc.id,
                operation=SyncOperation.UPDATE.value,
                payload=json.dumps({
                    "id": sc.id,
                    "organization_id": sc.organization_id,
                    "branch_id": sc.branch_id,
                    "device_id": sc.device_id,
                    "storage_location_id": sc.storage_location_id,
                    "count_type": sc.count_type,
                    "status": sc.status,
                    "approved_by_id": sc.approved_by_id,
                    "approved_at": sc.approved_at,
                    "notes": sc.notes,
                }),
                correlation_id=corr_id,
                dependency_level=SYNC_DEPENDENCY_LEVELS["stock_count"],
                schema_version=SYNC_SCHEMA_VERSION,
                local_created_at=now_local,
                status="PENDING",
            )
            db.add(sc_update_sync)

            action_name = (
                AuditAction.STOCK_COUNT_APPROVED.value
                if sc.status in (StockCountStatus.APPROVED.value, StockCountStatus.PARTIALLY_APPROVED.value)
                else AuditAction.STOCK_COUNT_REJECTED.value
            )
            self.record_audit_and_sync(
                db_session=db,
                user_session=user_session,
                action=action_name,
                entity_type="stock_count",
                entity_id=sc.id,
                operation=SyncOperation.UPDATE.value,
                payload={"id": sc.id, "status": sc.status, "approved_at": sc.approved_at},
                correlation_id=corr_id,
                transaction_id=sc.id,
            )

            return {
                "stock_count_id": sc.id,
                "status": sc.status,
                "approved_count": appr_count,
                "rejected_count": rej_count,
                "correlation_id": corr_id,
            }

    def get_stock_count_details(self, stock_count_id: str) -> dict | None:
        with self.transaction() as db:
            sc = db.query(StockCount).filter_by(id=stock_count_id).first()
            if not sc:
                return None

            shelves_map = {
                loc.id: loc.name
                for loc in db.query(StorageLocation).filter_by(branch_id=sc.branch_id).all()
            }

            items = db.query(StockCountItem).filter_by(stock_count_id=sc.id).all()
            item_list = []
            for it in items:
                prod = db.query(Product).filter_by(id=it.product_id).first()
                batch = db.query(Batch).filter_by(id=it.batch_id).first()
                item_list.append({
                    "id": it.id,
                    "product_id": it.product_id,
                    "product_name": prod.name if prod else "Unknown Product",
                    "batch_id": it.batch_id,
                    "batch_number": batch.batch_number if batch else "Unknown Batch",
                    "storage_location_id": it.storage_location_id,
                    "shelf_name": shelves_map.get(it.storage_location_id, "—") if it.storage_location_id else "—",
                    "expiry_date": batch.expiry_date if batch else "",
                    "system_quantity": it.system_quantity,
                    "counted_quantity": it.counted_quantity,
                    "variance": it.variance,
                    "approval_status": it.approval_status,
                    "rejection_reason": it.rejection_reason,
                })

            branch_batches = []
            if not items:
                inv_q = (
                    db.query(BranchInventory, Batch, Product)
                    .join(Batch, BranchInventory.batch_id == Batch.id)
                    .join(Product, Batch.product_id == Product.id)
                    .filter(
                        BranchInventory.branch_id == sc.branch_id,
                        BranchInventory.quantity > 0,
                    )
                )
                if sc.storage_location_id:
                    inv_q = inv_q.filter(BranchInventory.storage_location_id == sc.storage_location_id)
                inv_rows = inv_q.all()
                for inv, b, p in inv_rows:
                    branch_batches.append({
                        "product_id": p.id,
                        "product_name": p.name,
                        "product_sku": p.sku,
                        "batch_id": b.id,
                        "batch_number": b.batch_number,
                        "storage_location_id": inv.storage_location_id,
                        "shelf_name": shelves_map.get(inv.storage_location_id, "—") if inv.storage_location_id else "—",
                        "expiry_date": b.expiry_date,
                        "system_quantity": inv.quantity,
                        "counted_quantity": inv.quantity,
                    })

            return {
                "id": sc.id,
                "count_type": sc.count_type,
                "storage_location_id": sc.storage_location_id,
                "shelf_name": shelves_map.get(sc.storage_location_id, "All Shelves") if sc.storage_location_id else "All Shelves",
                "status": sc.status,
                "started_at": sc.started_at,
                "submitted_at": sc.submitted_at,
                "approved_at": sc.approved_at,
                "notes": sc.notes,
                "items": item_list,
                "branch_batches": branch_batches,
            }

    def list_stock_counts(self, branch_id: str, limit: int = 100) -> list[StockCount]:
        with self.transaction() as db:
            rows = (
                db.query(StockCount)
                .filter_by(branch_id=branch_id)
                .order_by(StockCount.started_at.desc())
                .limit(limit)
                .all()
            )
            for r in rows:
                db.expunge(r)
            return rows


def _download_stock_count(db, organization_id, entity_id, operation, payload, delivery):
    sc = db.query(StockCount).filter_by(id=entity_id).first()
    if not sc:
        db.add(
            StockCount(
                id=entity_id,
                organization_id=organization_id,
                branch_id=str(payload["branch_id"]),
                device_id=str(payload["device_id"]) if payload.get("device_id") else None,
                storage_location_id=str(payload["storage_location_id"]) if payload.get("storage_location_id") else None,
                count_type=payload.get("count_type", "FULL_BRANCH"),
                status=payload.get("status", "IN_PROGRESS"),
                started_by_id=str(payload["started_by_id"]) if payload.get("started_by_id") else str(payload.get("user_id")),
                started_at=payload.get("started_at") or datetime.now(timezone.utc).isoformat(),
                submitted_by_id=str(payload["submitted_by_id"]) if payload.get("submitted_by_id") else None,
                submitted_at=payload.get("submitted_at"),
                approved_by_id=str(payload["approved_by_id"]) if payload.get("approved_by_id") else None,
                approved_at=payload.get("approved_at"),
                notes=payload.get("notes", ""),
            )
        )
    else:
        sc.status = payload.get("status", sc.status)
        sc.submitted_at = payload.get("submitted_at", sc.submitted_at)
        sc.approved_at = payload.get("approved_at", sc.approved_at)
        if payload.get("notes"):
            sc.notes = payload["notes"]
    db.flush()


def _download_stock_count_item(db, organization_id, entity_id, operation, payload, delivery):
    sci = db.query(StockCountItem).filter_by(id=entity_id).first()
    if not sci:
        db.add(
            StockCountItem(
                id=entity_id,
                stock_count_id=str(payload["stock_count_id"]),
                product_id=str(payload["product_id"]),
                batch_id=str(payload["batch_id"]),
                storage_location_id=str(payload["storage_location_id"]) if payload.get("storage_location_id") else None,
                system_quantity=int(payload.get("system_quantity", 0)),
                counted_quantity=int(payload.get("counted_quantity", 0)),
                variance=int(payload.get("variance", 0)),
                current_quantity_at_approval=int(payload["current_quantity_at_approval"]) if payload.get("current_quantity_at_approval") is not None else None,
                approval_status=payload.get("approval_status", "PENDING"),
                rejection_reason=payload.get("rejection_reason", ""),
            )
        )
    else:
        sci.current_quantity_at_approval = (
            int(payload["current_quantity_at_approval"])
            if payload.get("current_quantity_at_approval") is not None
            else sci.current_quantity_at_approval
        )
        sci.approval_status = payload.get("approval_status", sci.approval_status)
        sci.rejection_reason = payload.get("rejection_reason", sci.rejection_reason)
    db.flush()


register_download_handler("stock_count", _download_stock_count)
register_download_handler("stock_count_item", _download_stock_count_item)
