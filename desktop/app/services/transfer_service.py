import json
import uuid
from datetime import datetime, timezone
from desktop.app.db.models import (
    Branch,
    Product,
    Batch,
    BranchInventory,
    InventoryMovement,
    AuditEvent,
    StockTransfer,
    StockTransferItem,
    SyncEvent,
)
from desktop.app.domain.exceptions import ValidationError
from desktop.app.services.base_service import BaseService
from desktop.app.sync.sync_engine import register_download_handler
from shared.enums import (
    AuditAction,
    AuditSource,
    MovementType,
    TransferStatus,
    SyncOperation,
    SYNC_DEPENDENCY_LEVELS,
    SYNC_SCHEMA_VERSION,
)


class TransferService(BaseService):
    """
    Offline-first Stock Transfer Service (Architecture Plan §10).
    Manages stock transfers between branches with reserved quantity lifecycle:
    - REQUESTED: items specified, not yet reserved.
    - APPROVED: validates available quantity, reserves stock at source branch.
    - DISPATCHED: unreserves and removes stock at source branch, creates STOCK_TRANSFER_OUT movement.
    - RECEIVED: adds stock at destination branch, creates STOCK_TRANSFER_IN movement.
    - CANCELLED: releases reserved stock at source branch if it was approved.
    """

    def create_transfer(
        self,
        user_session,
        destination_branch_id: str,
        items: list[dict],
        notes: str = "",
        source_branch_id: str | None = None,
    ) -> StockTransfer:
        source_id = source_branch_id or user_session.branch_id
        if source_id == destination_branch_id:
            raise ValidationError("Source and destination branches cannot be the same.")

        if not items:
            raise ValidationError("At least one transfer item must be provided.")

        corr_id = str(uuid.uuid4())
        now_local = datetime.now().astimezone().isoformat()
        now_utc = datetime.now(timezone.utc).isoformat()
        transfer_id = str(uuid.uuid4())

        with self.transaction() as db:
            dest_branch = db.query(Branch).filter_by(id=destination_branch_id).first()
            if not dest_branch:
                raise ValidationError(f"Destination branch {destination_branch_id} not found.")

            transfer = StockTransfer(
                id=transfer_id,
                organization_id=user_session.organization_id,
                source_branch_id=source_id,
                destination_branch_id=destination_branch_id,
                status=TransferStatus.REQUESTED.value,
                requested_by_id=user_session.user_id,
                requested_at=now_local,
                notes=notes or "",
                created_at=now_utc,
                updated_at=now_utc,
            )
            db.add(transfer)

            # Add items
            for it in items:
                prod_id = str(it['product_id'])
                batch_id = str(it['batch_id'])
                qty = int(it['quantity'])
                if qty <= 0:
                    raise ValidationError("Transfer item quantity must be greater than zero.")

                item_id = str(uuid.uuid4())
                transfer_item = StockTransferItem(
                    id=item_id,
                    stock_transfer_id=transfer_id,
                    product_id=prod_id,
                    batch_id=batch_id,
                    quantity=qty,
                    created_at=now_utc,
                    updated_at=now_utc,
                )
                db.add(transfer_item)

                # Queue SyncEvent for item
                item_payload = {
                    "id": item_id,
                    "stock_transfer_id": transfer_id,
                    "product_id": prod_id,
                    "batch_id": batch_id,
                    "quantity": qty,
                }
                db.add(
                    SyncEvent(
                        id=str(uuid.uuid4()),
                        branch_id=source_id,
                        device_id=user_session.device_id,
                        entity_type="stock_transfer_item",
                        entity_id=item_id,
                        operation=SyncOperation.CREATE.value,
                        payload=json.dumps(item_payload),
                        correlation_id=corr_id,
                        dependency_level=SYNC_DEPENDENCY_LEVELS.get("stock_transfer_item", 5),
                        schema_version=SYNC_SCHEMA_VERSION,
                        local_created_at=now_local,
                    )
                )

            # Audit event
            audit_id = str(uuid.uuid4())
            db.add(
                AuditEvent(
                    id=audit_id,
                    organization_id=user_session.organization_id,
                    branch_id=source_id,
                    user_id=user_session.user_id,
                    device_id=user_session.device_id,
                    action=AuditAction.TRANSFER_REQUESTED.value,
                    entity_type="stock_transfer",
                    entity_id=transfer_id,
                    data_after=json.dumps({"status": transfer.status, "source": source_id, "dest": destination_branch_id}),
                    local_timestamp=now_local,
                    source=AuditSource.DESKTOP.value,
                    is_offline=user_session.is_offline,
                    created_at=now_utc,
                )
            )

            # Queue SyncEvent for transfer
            transfer_payload = {
                "id": transfer_id,
                "source_branch_id": source_id,
                "destination_branch_id": destination_branch_id,
                "status": transfer.status,
                "requested_by_id": user_session.user_id,
                "requested_at": now_local,
                "notes": notes or "",
            }
            db.add(
                SyncEvent(
                    id=str(uuid.uuid4()),
                    branch_id=source_id,
                    device_id=user_session.device_id,
                    entity_type="stock_transfer",
                    entity_id=transfer_id,
                    operation=SyncOperation.CREATE.value,
                    payload=json.dumps(transfer_payload),
                    correlation_id=corr_id,
                    dependency_level=SYNC_DEPENDENCY_LEVELS.get("stock_transfer", 4),
                    schema_version=SYNC_SCHEMA_VERSION,
                    local_created_at=now_local,
                )
            )

            db.flush()
            return transfer

    def approve_transfer(
        self,
        user_session,
        transfer_id: str,
        batch_overrides: dict[str, str] | None = None,
    ) -> StockTransfer:
        corr_id = str(uuid.uuid4())
        now_local = datetime.now().astimezone().isoformat()
        now_utc = datetime.now(timezone.utc).isoformat()

        with self.transaction() as db:
            transfer = db.query(StockTransfer).filter_by(id=transfer_id).first()
            if not transfer:
                raise ValidationError(f"StockTransfer {transfer_id} not found.")

            if transfer.status not in [TransferStatus.REQUESTED.value, TransferStatus.DRAFT.value]:
                raise ValidationError(f"Transfer cannot be approved from status {transfer.status}.")

            items = db.query(StockTransferItem).filter_by(stock_transfer_id=transfer_id).all()
            for it in list(items):
                if batch_overrides and it.id in batch_overrides and batch_overrides[it.id]:
                    it.batch_id = str(batch_overrides[it.id])

                # 1. Find all inventory rows for this product at source_branch_id (across any shelf/storage_location_id)
                def _get_product_inv_rows(target_branch_id: str):
                    exact_rows = (
                        db.query(BranchInventory, Batch)
                        .join(Batch, BranchInventory.batch_id == Batch.id)
                        .filter(
                            BranchInventory.branch_id == target_branch_id,
                            BranchInventory.batch_id == it.batch_id,
                            BranchInventory.quantity > BranchInventory.reserved_quantity,
                        )
                        .order_by((BranchInventory.quantity - BranchInventory.reserved_quantity).desc())
                        .all()
                    )
                    other_rows = (
                        db.query(BranchInventory, Batch)
                        .join(Batch, BranchInventory.batch_id == Batch.id)
                        .filter(
                            BranchInventory.branch_id == target_branch_id,
                            Batch.product_id == it.product_id,
                            BranchInventory.batch_id != it.batch_id,
                            BranchInventory.quantity > BranchInventory.reserved_quantity,
                        )
                        .order_by(Batch.expiry_date.asc(), (BranchInventory.quantity - BranchInventory.reserved_quantity).desc())
                        .all()
                    )
                    return exact_rows + other_rows

                candidate_rows = _get_product_inv_rows(transfer.source_branch_id)
                total_avail = sum(max(0, inv.quantity - inv.reserved_quantity) for inv, _ in candidate_rows)

                # Fallback: if source_branch_id had insufficient stock (e.g. duplicate branch entry or request created from receiving branch)
                # and current session branch has the requested stock
                if (
                    total_avail < it.quantity
                    and getattr(user_session, "branch_id", None)
                    and user_session.branch_id != transfer.source_branch_id
                ):
                    alt_rows = _get_product_inv_rows(user_session.branch_id)
                    alt_avail = sum(max(0, inv.quantity - inv.reserved_quantity) for inv, _ in alt_rows)
                    if alt_avail >= it.quantity:
                        if transfer.destination_branch_id == user_session.branch_id:
                            transfer.destination_branch_id = transfer.source_branch_id
                        transfer.source_branch_id = user_session.branch_id
                        candidate_rows = alt_rows
                        total_avail = alt_avail

                if total_avail < it.quantity:
                    prod = db.query(Product).filter_by(id=it.product_id).first()
                    batch = db.query(Batch).filter_by(id=it.batch_id).first()
                    prod_label = prod.name if prod else it.product_id[:8]
                    batch_label = batch.batch_number if batch else it.batch_id[:8]
                    raise ValidationError(
                        f"Insufficient available stock for {prod_label} (Batch: {batch_label}). "
                        f"Available across all batches: {total_avail}, Requested: {it.quantity}"
                    )

                # Allocate requested quantity across candidate inventory rows (supporting single or multiple batches)
                remaining_to_reserve = it.quantity
                batch_allocations: dict[str, int] = {}
                for inv, b_obj in candidate_rows:
                    if remaining_to_reserve <= 0:
                        break
                    row_avail = max(0, inv.quantity - inv.reserved_quantity)
                    if row_avail <= 0:
                        continue
                    take = min(row_avail, remaining_to_reserve)
                    inv.reserved_quantity += take
                    inv.updated_at = now_utc
                    remaining_to_reserve -= take
                    batch_allocations[b_obj.id] = batch_allocations.get(b_obj.id, 0) + take

                alloc_entries = list(batch_allocations.items())
                if alloc_entries:
                    first_batch_id, first_qty = alloc_entries[0]
                    it.batch_id = first_batch_id
                    it.quantity = first_qty
                    it.updated_at = now_utc

                    # If fulfilled across multiple batches, create additional StockTransferItem lines for the extra batches
                    for extra_batch_id, extra_qty in alloc_entries[1:]:
                        extra_item_id = str(uuid.uuid4())
                        extra_item = StockTransferItem(
                            id=extra_item_id,
                            stock_transfer_id=transfer_id,
                            product_id=it.product_id,
                            batch_id=extra_batch_id,
                            quantity=extra_qty,
                            created_at=now_utc,
                            updated_at=now_utc,
                        )
                        db.add(extra_item)
                        db.add(
                            SyncEvent(
                                id=str(uuid.uuid4()),
                                branch_id=transfer.source_branch_id,
                                device_id=user_session.device_id,
                                entity_type="stock_transfer_item",
                                entity_id=extra_item_id,
                                operation=SyncOperation.CREATE.value,
                                payload=json.dumps({
                                    "id": extra_item_id,
                                    "stock_transfer_id": transfer_id,
                                    "product_id": it.product_id,
                                    "batch_id": extra_batch_id,
                                    "quantity": extra_qty,
                                }),
                                correlation_id=corr_id,
                                dependency_level=SYNC_DEPENDENCY_LEVELS.get("stock_transfer_item", 5),
                                schema_version=SYNC_SCHEMA_VERSION,
                                local_created_at=now_local,
                            )
                        )

            transfer.status = TransferStatus.APPROVED.value
            transfer.approved_by_id = user_session.user_id
            transfer.approved_at = now_local
            transfer.updated_at = now_utc

            # Audit event
            db.add(
                AuditEvent(
                    id=str(uuid.uuid4()),
                    organization_id=user_session.organization_id,
                    branch_id=transfer.source_branch_id,
                    user_id=user_session.user_id,
                    device_id=user_session.device_id,
                    action=AuditAction.TRANSFER_APPROVED.value,
                    entity_type="stock_transfer",
                    entity_id=transfer_id,
                    data_after=json.dumps({"status": transfer.status, "approved_by_id": user_session.user_id}),
                    local_timestamp=now_local,
                    source=AuditSource.DESKTOP.value,
                    is_offline=user_session.is_offline,
                    created_at=now_utc,
                )
            )

            # Sync event
            db.add(
                SyncEvent(
                    id=str(uuid.uuid4()),
                    branch_id=transfer.source_branch_id,
                    device_id=user_session.device_id,
                    entity_type="stock_transfer",
                    entity_id=transfer_id,
                    operation=SyncOperation.UPDATE.value,
                    payload=json.dumps({
                        "id": transfer_id,
                        "source_branch_id": transfer.source_branch_id,
                        "destination_branch_id": transfer.destination_branch_id,
                        "status": transfer.status,
                        "approved_by_id": user_session.user_id,
                        "approved_at": now_local,
                    }),
                    correlation_id=corr_id,
                    dependency_level=SYNC_DEPENDENCY_LEVELS.get("stock_transfer", 4),
                    schema_version=SYNC_SCHEMA_VERSION,
                    local_created_at=now_local,
                )
            )

            db.flush()
            return transfer

    def dispatch_transfer(self, user_session, transfer_id: str) -> StockTransfer:
        corr_id = str(uuid.uuid4())
        now_local = datetime.now().astimezone().isoformat()
        now_utc = datetime.now(timezone.utc).isoformat()

        with self.transaction() as db:
            transfer = db.query(StockTransfer).filter_by(id=transfer_id).first()
            if not transfer:
                raise ValidationError(f"StockTransfer {transfer_id} not found.")

            if transfer.status != TransferStatus.APPROVED.value:
                raise ValidationError(f"Transfer cannot be dispatched from status {transfer.status}. Must be APPROVED.")

            items = db.query(StockTransferItem).filter_by(stock_transfer_id=transfer_id).all()
            for it in items:
                inv_rows = (
                    db.query(BranchInventory)
                    .filter(
                        BranchInventory.branch_id == transfer.source_branch_id,
                        BranchInventory.batch_id == it.batch_id,
                        BranchInventory.quantity > 0,
                    )
                    .order_by(BranchInventory.reserved_quantity.desc(), BranchInventory.quantity.desc())
                    .all()
                )
                if not inv_rows:
                    raise ValidationError(f"No inventory record found for batch {it.batch_id}.")

                remaining_to_deduct = it.quantity
                for inv in inv_rows:
                    if remaining_to_deduct <= 0:
                        break
                    deduct = min(inv.quantity, remaining_to_deduct)
                    if deduct <= 0:
                        continue
                    qty_before = inv.quantity
                    inv.reserved_quantity = max(0, inv.reserved_quantity - deduct)
                    inv.quantity -= deduct
                    if inv.quantity <= 0:
                        inv.status = 'DEPLETED'
                    inv.updated_at = now_utc
                    qty_after = inv.quantity
                    remaining_to_deduct -= deduct

                    # Create immutable InventoryMovement
                    mov_id = str(uuid.uuid4())
                    db.add(
                        InventoryMovement(
                            id=mov_id,
                            organization_id=user_session.organization_id,
                            branch_id=transfer.source_branch_id,
                            batch_id=it.batch_id,
                            storage_location_id=inv.storage_location_id,
                            movement_type=MovementType.STOCK_TRANSFER_OUT.value,
                            quantity_change=-deduct,
                            quantity_before=qty_before,
                            quantity_after=qty_after,
                            reference_type="transfer",
                            reference_id=transfer_id,
                            user_id=user_session.user_id,
                            device_id=user_session.device_id,
                            local_timestamp=now_local,
                            is_offline=user_session.is_offline,
                            created_at=now_utc,
                        )
                    )

                    db.add(
                        SyncEvent(
                            id=str(uuid.uuid4()),
                            branch_id=transfer.source_branch_id,
                            device_id=user_session.device_id,
                            entity_type="inventory_movement",
                            entity_id=mov_id,
                            operation=SyncOperation.CREATE.value,
                            payload=json.dumps({
                                "id": mov_id,
                                "branch_id": transfer.source_branch_id,
                                "batch_id": it.batch_id,
                                "movement_type": MovementType.STOCK_TRANSFER_OUT.value,
                                "quantity_change": -deduct,
                                "quantity_before": qty_before,
                                "quantity_after": qty_after,
                                "reference_type": "transfer",
                                "reference_id": transfer_id,
                                "user_id": user_session.user_id,
                                "local_timestamp": now_local,
                            }),
                            correlation_id=corr_id,
                            dependency_level=SYNC_DEPENDENCY_LEVELS.get("inventory_movement", 6),
                            schema_version=SYNC_SCHEMA_VERSION,
                            local_created_at=now_local,
                        )
                    )

            transfer.status = TransferStatus.DISPATCHED.value
            transfer.dispatched_by_id = user_session.user_id
            transfer.dispatched_at = now_local
            transfer.updated_at = now_utc

            # Audit event
            db.add(
                AuditEvent(
                    id=str(uuid.uuid4()),
                    organization_id=user_session.organization_id,
                    branch_id=transfer.source_branch_id,
                    user_id=user_session.user_id,
                    device_id=user_session.device_id,
                    action=AuditAction.TRANSFER_DISPATCHED.value,
                    entity_type="stock_transfer",
                    entity_id=transfer_id,
                    data_after=json.dumps({"status": transfer.status, "dispatched_by_id": user_session.user_id}),
                    local_timestamp=now_local,
                    source=AuditSource.DESKTOP.value,
                    is_offline=user_session.is_offline,
                    created_at=now_utc,
                )
            )

            # Sync event
            db.add(
                SyncEvent(
                    id=str(uuid.uuid4()),
                    branch_id=transfer.source_branch_id,
                    device_id=user_session.device_id,
                    entity_type="stock_transfer",
                    entity_id=transfer_id,
                    operation=SyncOperation.UPDATE.value,
                    payload=json.dumps({
                        "id": transfer_id,
                        "source_branch_id": transfer.source_branch_id,
                        "destination_branch_id": transfer.destination_branch_id,
                        "status": transfer.status,
                        "dispatched_by_id": user_session.user_id,
                        "dispatched_at": now_local,
                    }),
                    correlation_id=corr_id,
                    dependency_level=SYNC_DEPENDENCY_LEVELS.get("stock_transfer", 4),
                    schema_version=SYNC_SCHEMA_VERSION,
                    local_created_at=now_local,
                )
            )

            db.flush()
            return transfer

    def receive_transfer(self, user_session, transfer_id: str) -> StockTransfer:
        corr_id = str(uuid.uuid4())
        now_local = datetime.now().astimezone().isoformat()
        now_utc = datetime.now(timezone.utc).isoformat()

        with self.transaction() as db:
            transfer = db.query(StockTransfer).filter_by(id=transfer_id).first()
            if not transfer:
                raise ValidationError(f"StockTransfer {transfer_id} not found.")

            if transfer.status not in [TransferStatus.DISPATCHED.value, TransferStatus.IN_TRANSIT.value]:
                raise ValidationError(f"Transfer cannot be received from status {transfer.status}. Must be DISPATCHED.")

            items = db.query(StockTransferItem).filter_by(stock_transfer_id=transfer_id).all()
            for it in items:
                inv = (
                    db.query(BranchInventory)
                    .filter_by(
                        branch_id=transfer.destination_branch_id,
                        batch_id=it.batch_id,
                    )
                    .first()
                )

                if not inv:
                    inv = BranchInventory(
                        id=str(uuid.uuid4()),
                        organization_id=user_session.organization_id,
                        branch_id=transfer.destination_branch_id,
                        batch_id=it.batch_id,
                        storage_location_id=None,
                        quantity=0,
                        reserved_quantity=0,
                        status="AVAILABLE",
                        created_at=now_utc,
                        updated_at=now_utc,
                    )
                    db.add(inv)
                    db.flush()

                qty_before = inv.quantity
                inv.quantity += it.quantity
                if inv.quantity > 0:
                    inv.status = 'AVAILABLE'
                inv.updated_at = now_utc

                qty_after = inv.quantity

                # Create immutable InventoryMovement
                mov_id = str(uuid.uuid4())
                db.add(
                    InventoryMovement(
                        id=mov_id,
                        organization_id=user_session.organization_id,
                        branch_id=transfer.destination_branch_id,
                        batch_id=it.batch_id,
                        storage_location_id=inv.storage_location_id,
                        movement_type=MovementType.STOCK_TRANSFER_IN.value,
                        quantity_change=it.quantity,
                        quantity_before=qty_before,
                        quantity_after=qty_after,
                        reference_type="transfer",
                        reference_id=transfer_id,
                        user_id=user_session.user_id,
                        device_id=user_session.device_id,
                        local_timestamp=now_local,
                        is_offline=user_session.is_offline,
                        created_at=now_utc,
                    )
                )

                db.add(
                    SyncEvent(
                        id=str(uuid.uuid4()),
                        branch_id=transfer.destination_branch_id,
                        device_id=user_session.device_id,
                        entity_type="inventory_movement",
                        entity_id=mov_id,
                        operation=SyncOperation.CREATE.value,
                        payload=json.dumps({
                            "id": mov_id,
                            "branch_id": transfer.destination_branch_id,
                            "batch_id": it.batch_id,
                            "movement_type": MovementType.STOCK_TRANSFER_IN.value,
                            "quantity_change": it.quantity,
                            "quantity_before": qty_before,
                            "quantity_after": qty_after,
                            "reference_type": "transfer",
                            "reference_id": transfer_id,
                            "user_id": user_session.user_id,
                            "local_timestamp": now_local,
                        }),
                        correlation_id=corr_id,
                        dependency_level=SYNC_DEPENDENCY_LEVELS.get("inventory_movement", 6),
                        schema_version=SYNC_SCHEMA_VERSION,
                        local_created_at=now_local,
                    )
                )

            transfer.status = TransferStatus.RECEIVED.value
            transfer.received_by_id = user_session.user_id
            transfer.received_at = now_local
            transfer.updated_at = now_utc

            # Audit event
            db.add(
                AuditEvent(
                    id=str(uuid.uuid4()),
                    organization_id=user_session.organization_id,
                    branch_id=transfer.destination_branch_id,
                    user_id=user_session.user_id,
                    device_id=user_session.device_id,
                    action=AuditAction.TRANSFER_RECEIVED.value,
                    entity_type="stock_transfer",
                    entity_id=transfer_id,
                    data_after=json.dumps({"status": transfer.status, "received_by_id": user_session.user_id}),
                    local_timestamp=now_local,
                    source=AuditSource.DESKTOP.value,
                    is_offline=user_session.is_offline,
                    created_at=now_utc,
                )
            )

            # Sync event
            db.add(
                SyncEvent(
                    id=str(uuid.uuid4()),
                    branch_id=transfer.destination_branch_id,
                    device_id=user_session.device_id,
                    entity_type="stock_transfer",
                    entity_id=transfer_id,
                    operation=SyncOperation.UPDATE.value,
                    payload=json.dumps({
                        "id": transfer_id,
                        "source_branch_id": transfer.source_branch_id,
                        "destination_branch_id": transfer.destination_branch_id,
                        "status": transfer.status,
                        "received_by_id": user_session.user_id,
                        "received_at": now_local,
                    }),
                    correlation_id=corr_id,
                    dependency_level=SYNC_DEPENDENCY_LEVELS.get("stock_transfer", 4),
                    schema_version=SYNC_SCHEMA_VERSION,
                    local_created_at=now_local,
                )
            )

            db.flush()
            return transfer

    def cancel_transfer(self, user_session, transfer_id: str) -> StockTransfer:
        corr_id = str(uuid.uuid4())
        now_local = datetime.now().astimezone().isoformat()
        now_utc = datetime.now(timezone.utc).isoformat()

        with self.transaction() as db:
            transfer = db.query(StockTransfer).filter_by(id=transfer_id).first()
            if not transfer:
                raise ValidationError(f"StockTransfer {transfer_id} not found.")

            if transfer.status not in [TransferStatus.DRAFT.value, TransferStatus.REQUESTED.value, TransferStatus.APPROVED.value]:
                raise ValidationError(f"Transfer cannot be cancelled from status {transfer.status}.")

            if transfer.status == TransferStatus.APPROVED.value:
                # Release reserved quantity across any storage location rows
                items = db.query(StockTransferItem).filter_by(stock_transfer_id=transfer_id).all()
                for it in items:
                    inv_rows = (
                        db.query(BranchInventory)
                        .filter(
                            BranchInventory.branch_id == transfer.source_branch_id,
                            BranchInventory.batch_id == it.batch_id,
                            BranchInventory.reserved_quantity > 0,
                        )
                        .all()
                    )
                    rem = it.quantity
                    for inv in inv_rows:
                        if rem <= 0:
                            break
                        rel = min(inv.reserved_quantity, rem)
                        inv.reserved_quantity = max(0, inv.reserved_quantity - rel)
                        inv.updated_at = now_utc
                        rem -= rel

            transfer.status = TransferStatus.CANCELLED.value
            transfer.updated_at = now_utc

            # Audit event
            db.add(
                AuditEvent(
                    id=str(uuid.uuid4()),
                    organization_id=user_session.organization_id,
                    branch_id=transfer.source_branch_id,
                    user_id=user_session.user_id,
                    device_id=user_session.device_id,
                    action=AuditAction.TRANSFER_CANCELLED.value,
                    entity_type="stock_transfer",
                    entity_id=transfer_id,
                    data_after=json.dumps({"status": transfer.status}),
                    local_timestamp=now_local,
                    source=AuditSource.DESKTOP.value,
                    is_offline=user_session.is_offline,
                    created_at=now_utc,
                )
            )

            # Sync event
            db.add(
                SyncEvent(
                    id=str(uuid.uuid4()),
                    branch_id=transfer.source_branch_id,
                    device_id=user_session.device_id,
                    entity_type="stock_transfer",
                    entity_id=transfer_id,
                    operation=SyncOperation.UPDATE.value,
                    payload=json.dumps({
                        "id": transfer_id,
                        "source_branch_id": transfer.source_branch_id,
                        "destination_branch_id": transfer.destination_branch_id,
                        "status": transfer.status,
                    }),
                    correlation_id=corr_id,
                    dependency_level=SYNC_DEPENDENCY_LEVELS.get("stock_transfer", 4),
                    schema_version=SYNC_SCHEMA_VERSION,
                    local_created_at=now_local,
                )
            )

            db.flush()
            return transfer

    def list_transfers(self, branch_id: str | None = None, status: str | None = None) -> list[dict]:
        with self.transaction() as db:
            q = db.query(StockTransfer)
            if branch_id:
                q = q.filter(
                    (StockTransfer.source_branch_id == branch_id) | (StockTransfer.destination_branch_id == branch_id)
                )
            if status:
                q = q.filter(StockTransfer.status == status)

            transfers = q.order_by(StockTransfer.requested_at.desc()).all()
            res = []
            for t in transfers:
                src_b = db.query(Branch).filter_by(id=t.source_branch_id).first()
                dst_b = db.query(Branch).filter_by(id=t.destination_branch_id).first()
                items = db.query(StockTransferItem).filter_by(stock_transfer_id=t.id).all()
                item_list = []
                for it in items:
                    prod = db.query(Product).filter_by(id=it.product_id).first()
                    batch = db.query(Batch).filter_by(id=it.batch_id).first()
                    item_list.append({
                        "id": it.id,
                        "product_id": it.product_id,
                        "product_name": prod.name if prod else "",
                        "batch_id": it.batch_id,
                        "batch_number": batch.batch_number if batch else "",
                        "quantity": it.quantity,
                    })
                res.append({
                    "id": t.id,
                    "source_branch_id": t.source_branch_id,
                    "source_branch_name": f"{src_b.name} ({src_b.code})" if src_b else "",
                    "destination_branch_id": t.destination_branch_id,
                    "destination_branch_name": f"{dst_b.name} ({dst_b.code})" if dst_b else "",
                    "status": t.status,
                    "requested_by_id": t.requested_by_id,
                    "approved_by_id": t.approved_by_id,
                    "dispatched_by_id": t.dispatched_by_id,
                    "received_by_id": t.received_by_id,
                    "requested_at": t.requested_at,
                    "approved_at": t.approved_at,
                    "dispatched_at": t.dispatched_at,
                    "received_at": t.received_at,
                    "notes": t.notes,
                    "items": item_list,
                })
            return res

    def list_branches(self, organization_id: str, exclude_branch_id: str | None = None) -> list[Branch]:
        with self.transaction() as db:
            q = db.query(Branch).filter_by(organization_id=organization_id, is_active=True)
            if exclude_branch_id:
                q = q.filter(Branch.id != exclude_branch_id)
            rows = q.order_by(Branch.name.asc()).all()
            for r in rows:
                db.expunge(r)
            return rows

    def list_transferable_batches(self, branch_id: str) -> list[dict]:
        with self.transaction() as db:
            inv_rows = (
                db.query(BranchInventory, Batch, Product)
                .join(Batch, BranchInventory.batch_id == Batch.id)
                .join(Product, Batch.product_id == Product.id)
                .filter(
                    BranchInventory.branch_id == branch_id,
                    BranchInventory.quantity > 0,
                )
                .order_by(Product.name.asc(), Batch.expiry_date.asc())
                .all()
            )
            by_batch: dict[str, dict] = {}
            for inv, b, p in inv_rows:
                avail = max(0, inv.quantity - inv.reserved_quantity)
                if avail > 0:
                    if b.id not in by_batch:
                        by_batch[b.id] = {
                            "product_id": p.id,
                            "product_name": p.name,
                            "product_sku": p.sku,
                            "batch_id": b.id,
                            "batch_number": b.batch_number,
                            "expiry_date": b.expiry_date,
                            "quantity": inv.quantity,
                            "reserved_quantity": inv.reserved_quantity,
                            "available_quantity": avail,
                        }
                    else:
                        by_batch[b.id]["quantity"] += inv.quantity
                        by_batch[b.id]["reserved_quantity"] += inv.reserved_quantity
                        by_batch[b.id]["available_quantity"] += avail
            return list(by_batch.values())

    def get_transfer(self, transfer_id: str) -> dict | None:
        transfers = self.list_transfers()
        for t in transfers:
            if t['id'] == transfer_id:
                return t
        return None


# =============================================================================
# Sync Download Handlers
# =============================================================================

def _download_stock_transfer(db, organization_id, entity_id, operation, payload, delivery):
    st = db.query(StockTransfer).filter_by(id=entity_id).first()
    if not st:
        st = StockTransfer(
            id=entity_id,
            organization_id=organization_id,
            source_branch_id=str(payload["source_branch_id"]),
            destination_branch_id=str(payload["destination_branch_id"]),
            status=payload.get("status", TransferStatus.REQUESTED.value),
            requested_by_id=str(payload["requested_by_id"]),
            approved_by_id=str(payload["approved_by_id"]) if payload.get("approved_by_id") else None,
            dispatched_by_id=str(payload["dispatched_by_id"]) if payload.get("dispatched_by_id") else None,
            received_by_id=str(payload["received_by_id"]) if payload.get("received_by_id") else None,
            requested_at=payload.get("requested_at") or datetime.now(timezone.utc).isoformat(),
            approved_at=payload.get("approved_at"),
            dispatched_at=payload.get("dispatched_at"),
            received_at=payload.get("received_at"),
            notes=payload.get("notes", ""),
        )
        db.add(st)
    else:
        st.status = payload.get("status", st.status)
        if payload.get("approved_by_id"):
            st.approved_by_id = str(payload["approved_by_id"])
        if payload.get("approved_at"):
            st.approved_at = payload["approved_at"]
        if payload.get("dispatched_by_id"):
            st.dispatched_by_id = str(payload["dispatched_by_id"])
        if payload.get("dispatched_at"):
            st.dispatched_at = payload["dispatched_at"]
        if payload.get("received_by_id"):
            st.received_by_id = str(payload["received_by_id"])
        if payload.get("received_at"):
            st.received_at = payload["received_at"]
        if payload.get("notes"):
            st.notes = payload["notes"]
    db.flush()


def _download_stock_transfer_item(db, organization_id, entity_id, operation, payload, delivery):
    sti = db.query(StockTransferItem).filter_by(id=entity_id).first()
    if not sti:
        db.add(
            StockTransferItem(
                id=entity_id,
                stock_transfer_id=str(payload["stock_transfer_id"]),
                product_id=str(payload["product_id"]),
                batch_id=str(payload["batch_id"]),
                quantity=int(payload.get("quantity", 0)),
            )
        )
    else:
        sti.quantity = int(payload.get("quantity", sti.quantity))
    db.flush()


register_download_handler("stock_transfer", _download_stock_transfer)
register_download_handler("stock_transfer_item", _download_stock_transfer_item)
