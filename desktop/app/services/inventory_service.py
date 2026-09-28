import json
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from sqlalchemy import func
from desktop.app.db.models import (
    Batch,
    Branch,
    Category,
    Manufacturer,
    Price,
    PriceHistory,
    Product,
    ProductType,
    StorageLocation,
    StorageLocationAssignment,
    Supplier,
    BranchInventory,
    InventoryMovement,
    SyncEvent,
    User,
)
from desktop.app.domain.exceptions import ValidationError, InsufficientStockError
from desktop.app.services.base_service import BaseService
from shared.enums import (
    PermissionCode,
    BatchStatus,
    InventoryStatus,
    MovementType,
    AuditAction,
    SyncOperation,
    SYNC_DEPENDENCY_LEVELS,
    SYNC_SCHEMA_VERSION,
)


class InventoryService(BaseService):
    """
    Service managing Batches, BranchInventory, optional StorageLocations,
    Opening Balance loading, and immutable InventoryMovements on the desktop.
    """

    def create_batch(
        self,
        user_session,
        product_id: str,
        batch_number: str,
        expiry_date: str,
        purchase_price: Decimal | float | str,
        received_date: str | None = None,
        manufacturing_date: str | None = None,
        supplier_id: str | None = None,
        invoice_reference: str = "",
        notes: str = "",
    ) -> Batch:
        self.require_permission(user_session, PermissionCode.BATCHES_MANAGE.value)
        if not product_id or not batch_number or not expiry_date:
            raise ValidationError("Product, batch number, and expiry date are required.")

        with self.transaction() as db:
            product = (
                db.query(Product)
                .filter_by(id=product_id, organization_id=user_session.organization_id)
                .first()
            )
            if not product:
                raise ValidationError("Product not found in your organization.")

            existing = (
                db.query(Batch)
                .filter_by(product_id=product_id, batch_number=batch_number)
                .first()
            )
            if existing:
                raise ValidationError(
                    f"Batch '{batch_number}' already exists for this product."
                )

            today_iso = date.today().isoformat()
            status_val = (
                BatchStatus.EXPIRED.value
                if expiry_date < today_iso
                else BatchStatus.ACTIVE.value
            )
            rec_date = received_date or today_iso
            cost = Decimal(str(purchase_price))

            batch = Batch(
                id=str(uuid.uuid4()),
                organization_id=user_session.organization_id,
                product_id=product_id,
                batch_number=batch_number,
                manufacturing_date=manufacturing_date,
                expiry_date=expiry_date,
                purchase_price=cost,
                supplier_id=supplier_id,
                invoice_reference=invoice_reference,
                received_date=rec_date,
                status=status_val,
                notes=notes,
            )
            db.add(batch)
            db.flush()

            payload = {
                "id": batch.id,
                "organization_id": batch.organization_id,
                "product_id": batch.product_id,
                "batch_number": batch.batch_number,
                "manufacturing_date": batch.manufacturing_date,
                "expiry_date": batch.expiry_date,
                "purchase_price": str(batch.purchase_price),
                "supplier_id": batch.supplier_id,
                "invoice_reference": batch.invoice_reference,
                "received_date": batch.received_date,
                "status": batch.status,
                "notes": batch.notes,
            }
            self.record_audit_and_sync(
                db_session=db,
                user_session=user_session,
                action=AuditAction.BATCH_CREATED.value,
                entity_type="batch",
                entity_id=batch.id,
                operation=SyncOperation.CREATE.value,
                payload=payload,
            )
            return batch

    def recall_batch(self, user_session, batch_id: str, reason: str = "Recalled") -> Batch:
        self.require_permission(user_session, PermissionCode.BATCHES_MANAGE.value)
        with self.transaction() as db:
            batch = (
                db.query(Batch)
                .filter_by(id=batch_id, organization_id=user_session.organization_id)
                .first()
            )
            if not batch:
                raise ValidationError("Batch not found.")

            before_status = batch.status
            batch.status = BatchStatus.RECALLED.value
            db.flush()

            payload = {
                "id": batch.id,
                "organization_id": batch.organization_id,
                "product_id": batch.product_id,
                "batch_number": batch.batch_number,
                "status": batch.status,
            }
            self.record_audit_and_sync(
                db_session=db,
                user_session=user_session,
                action=AuditAction.BATCH_RECALLED.value,
                entity_type="batch",
                entity_id=batch.id,
                operation=SyncOperation.UPDATE.value,
                payload=payload,
                data_before={"status": before_status},
                data_after={"status": batch.status},
                reason=reason,
            )
            return batch

    def update_batch(
        self,
        user_session,
        batch_id: str,
        expiry_date: str | None = None,
        manufacturing_date: str | None = None,
        purchase_price: Decimal | float | str | None = None,
        status: str | None = None,
        notes: str | None = None,
    ) -> Batch:
        """Updates batch metadata such as manufacturing date, expiry date, purchase price, status, or notes."""
        self.require_permission(user_session, PermissionCode.BATCHES_MANAGE.value)
        with self.transaction() as db:
            batch = db.query(Batch).filter_by(id=batch_id, organization_id=user_session.organization_id).first()
            if not batch:
                raise ValidationError("Batch not found.")
            data_before = {
                "manufacturing_date": batch.manufacturing_date,
                "expiry_date": batch.expiry_date,
                "purchase_price": str(batch.purchase_price),
                "status": batch.status,
                "notes": batch.notes,
            }
            if manufacturing_date is not None:
                batch.manufacturing_date = manufacturing_date or None
            if expiry_date:
                batch.expiry_date = expiry_date
            if purchase_price is not None:
                batch.purchase_price = Decimal(str(purchase_price))
            if status:
                batch.status = status
            if notes is not None:
                batch.notes = notes
            db.flush()

            data_after = {
                "manufacturing_date": batch.manufacturing_date,
                "expiry_date": batch.expiry_date,
                "purchase_price": str(batch.purchase_price),
                "status": batch.status,
                "notes": batch.notes,
            }
            self.record_audit_and_sync(
                db_session=db,
                user_session=user_session,
                action=AuditAction.SETTINGS_CHANGED.value,
                entity_type="batch",
                entity_id=batch.id,
                operation=SyncOperation.UPDATE.value,
                payload={"id": batch.id, **data_after},
                data_before=data_before,
                data_after=data_after,
            )
            return batch

    def refresh_expired_batches(self, organization_id: str) -> int:
        """Auto-transition ACTIVE batches whose expiry_date < today to EXPIRED."""
        today_iso = date.today().isoformat()
        with self.transaction() as db:
            expired_batches = (
                db.query(Batch)
                .filter(
                    Batch.organization_id == organization_id,
                    Batch.status == BatchStatus.ACTIVE.value,
                    Batch.expiry_date < today_iso,
                )
                .all()
            )
            for b in expired_batches:
                b.status = BatchStatus.EXPIRED.value
            db.flush()
            return len(expired_batches)

    def _require_shelf_permission(self, user_session) -> None:
        if user_session.has_permission(PermissionCode.BRANCHES_MANAGE.value) or user_session.has_permission(
            PermissionCode.BATCHES_MANAGE.value
        ):
            return
        self.require_permission(user_session, PermissionCode.BRANCHES_MANAGE.value)

    def create_storage_location(
        self,
        user_session,
        branch_id: str,
        name: str,
        description: str = "",
        location_type: str = "",
        auto_enable: bool = False,
    ) -> StorageLocation:
        self._require_shelf_permission(user_session)
        if not name:
            raise ValidationError("Storage location name is required.")

        with self.transaction() as db:
            branch = (
                db.query(Branch)
                .filter_by(id=branch_id, organization_id=user_session.organization_id)
                .first()
            )
            if not branch:
                raise ValidationError("Branch not found.")
            if not branch.uses_storage_locations:
                if auto_enable:
                    branch.uses_storage_locations = True
                    db.flush()
                else:
                    raise ValidationError(
                        "Storage locations are not enabled for this branch."
                    )

            loc = StorageLocation(
                id=str(uuid.uuid4()),
                organization_id=user_session.organization_id,
                branch_id=branch_id,
                name=name.strip(),
                description=description.strip(),
                location_type=location_type.strip(),
                is_active=True,
            )
            db.add(loc)
            db.flush()

            payload = {
                "id": loc.id,
                "organization_id": loc.organization_id,
                "branch_id": loc.branch_id,
                "name": loc.name,
                "description": loc.description,
                "location_type": loc.location_type,
                "is_active": True,
            }
            self.record_audit_and_sync(
                db_session=db,
                user_session=user_session,
                action=AuditAction.SETTINGS_CHANGED.value,
                entity_type="storage_location",
                entity_id=loc.id,
                operation=SyncOperation.CREATE.value,
                payload=payload,
            )
            return loc

    def update_storage_location(
        self,
        user_session,
        location_id: str,
        name: str,
        description: str = "",
        location_type: str = "",
        is_active: bool = True,
    ) -> StorageLocation:
        self._require_shelf_permission(user_session)
        if not name or not name.strip():
            raise ValidationError("Storage location name is required.")

        with self.transaction() as db:
            loc = (
                db.query(StorageLocation)
                .filter_by(id=location_id, organization_id=user_session.organization_id)
                .first()
            )
            if not loc:
                raise ValidationError("Storage location not found.")

            loc.name = name.strip()
            loc.description = description.strip()
            loc.location_type = location_type.strip()
            loc.is_active = bool(is_active)
            db.flush()

            payload = {
                "id": loc.id,
                "organization_id": loc.organization_id,
                "branch_id": loc.branch_id,
                "name": loc.name,
                "description": loc.description,
                "location_type": loc.location_type,
                "is_active": loc.is_active,
            }
            self.record_audit_and_sync(
                db_session=db,
                user_session=user_session,
                action=AuditAction.SETTINGS_CHANGED.value,
                entity_type="storage_location",
                entity_id=loc.id,
                operation=SyncOperation.UPDATE.value,
                payload=payload,
            )
            return loc

    def list_storage_locations(
        self,
        organization_id: str,
        branch_id: str,
        active_only: bool = True,
    ) -> list[StorageLocation]:
        with self.transaction() as db:
            q = db.query(StorageLocation).filter_by(
                organization_id=organization_id,
                branch_id=branch_id,
            )
            if active_only:
                q = q.filter_by(is_active=True)
            return q.order_by(StorageLocation.name.asc()).all()

    def list_storage_location_assignments(
        self,
        organization_id: str,
        branch_id: str,
    ) -> dict[str, dict]:
        """Returns mapping of storage_location_id -> active staff assignment details."""
        with self.transaction() as db:
            rows = (
                db.query(StorageLocationAssignment, User)
                .join(User, StorageLocationAssignment.user_id == User.id)
                .filter(
                    StorageLocationAssignment.organization_id == organization_id,
                    StorageLocationAssignment.branch_id == branch_id,
                    StorageLocationAssignment.is_active.is_(True),
                )
                .order_by(StorageLocationAssignment.created_at.desc())
                .all()
            )
            result: dict[str, dict] = {}
            for assign, usr in rows:
                if assign.storage_location_id not in result:
                    result[assign.storage_location_id] = {
                        "assignment_id": assign.id,
                        "user_id": usr.id,
                        "username": usr.username,
                        "full_name": usr.full_name,
                        "label": f"{usr.full_name} (@{usr.username})" if usr.full_name else f"@{usr.username}",
                        "start_date": assign.start_date,
                        "end_date": assign.end_date,
                    }
            return result

    def list_organization_users(self, organization_id: str) -> list[User]:
        """Returns active staff users in the organization for shelf assignment."""
        with self.transaction() as db:
            return (
                db.query(User)
                .filter_by(organization_id=organization_id, is_active=True)
                .order_by(User.full_name.asc(), User.username.asc())
                .all()
            )

    def set_batch_storage_location(
        self,
        user_session,
        branch_id: str,
        batch_id: str,
        storage_location_id: str | None,
        current_location_id: str | None = None,
    ) -> None:
        """Assigns or moves a batch's BranchInventory row in a branch to a specific shelf/storage location."""
        with self.transaction() as db:
            if storage_location_id:
                branch = db.query(Branch).filter_by(id=branch_id, organization_id=user_session.organization_id).first()
                if branch and not branch.uses_storage_locations:
                    branch.uses_storage_locations = True
                    db.flush()

            q = db.query(BranchInventory).filter_by(
                organization_id=user_session.organization_id,
                branch_id=branch_id,
                batch_id=batch_id,
            )
            if current_location_id is not None:
                inv = q.filter_by(storage_location_id=current_location_id).first() or q.first()
            else:
                inv = q.first()

            if not inv:
                inv = BranchInventory(
                    id=str(uuid.uuid4()),
                    organization_id=user_session.organization_id,
                    branch_id=branch_id,
                    batch_id=batch_id,
                    storage_location_id=storage_location_id,
                    quantity=0,
                    reserved_quantity=0,
                    status=InventoryStatus.DEPLETED.value,
                )
                db.add(inv)
                db.flush()
                return

            if inv.storage_location_id == storage_location_id:
                return

            target_inv = (
                db.query(BranchInventory)
                .filter_by(
                    organization_id=user_session.organization_id,
                    branch_id=branch_id,
                    batch_id=batch_id,
                    storage_location_id=storage_location_id,
                )
                .first()
            )
            if target_inv and target_inv.id != inv.id:
                target_inv.quantity = (target_inv.quantity or 0) + (inv.quantity or 0)
                target_inv.reserved_quantity = (target_inv.reserved_quantity or 0) + (inv.reserved_quantity or 0)
                if target_inv.quantity > 0:
                    target_inv.status = InventoryStatus.AVAILABLE.value
                db.delete(inv)
            else:
                inv.storage_location_id = storage_location_id
            db.flush()

    def assign_storage_location(
        self,
        user_session,
        storage_location_id: str,
        target_user_id: str,
        start_date: str,
        end_date: str | None = None,
    ) -> StorageLocationAssignment:
        self._require_shelf_permission(user_session)
        with self.transaction() as db:
            loc = (
                db.query(StorageLocation)
                .filter_by(id=storage_location_id, organization_id=user_session.organization_id)
                .first()
            )
            if not loc:
                raise ValidationError("Storage location not found.")

            # Retire previous active assignments for this shelf
            db.query(StorageLocationAssignment).filter_by(
                storage_location_id=storage_location_id,
                is_active=True,
            ).update({"is_active": False})

            assigner_exists = (
                db.query(User).filter_by(id=user_session.user_id).first() is not None
            )
            assignment = StorageLocationAssignment(
                id=str(uuid.uuid4()),
                organization_id=user_session.organization_id,
                storage_location_id=storage_location_id,
                user_id=target_user_id,
                branch_id=loc.branch_id,
                start_date=start_date,
                end_date=end_date,
                assigned_by_id=user_session.user_id if assigner_exists else None,
                is_active=True,
            )
            db.add(assignment)
            db.flush()
            return assignment

    def _apply_movement_in_tx(
        self,
        db,
        user_session,
        branch_id: str,
        batch_id: str,
        storage_location_id: str | None,
        movement_type: str,
        quantity_change: int,
        reference_type: str,
        reference_id: str,
        notes: str = "",
        correlation_id: str | None = None,
        allow_negative: bool = False,
        emit_movement_sync: bool = True,
    ) -> tuple[BranchInventory, InventoryMovement]:
        inv = (
            db.query(BranchInventory)
            .filter_by(
                organization_id=user_session.organization_id,
                branch_id=branch_id,
                batch_id=batch_id,
                storage_location_id=storage_location_id,
            )
            .first()
        )
        if not inv:
            inv = BranchInventory(
                id=str(uuid.uuid4()),
                organization_id=user_session.organization_id,
                branch_id=branch_id,
                batch_id=batch_id,
                storage_location_id=storage_location_id,
                quantity=0,
                reserved_quantity=0,
                status=InventoryStatus.AVAILABLE.value,
            )
            db.add(inv)
            db.flush()

        qty_before = inv.quantity
        qty_after = qty_before + quantity_change
        if not allow_negative and qty_after < 0:
            raise InsufficientStockError(
                f"Insufficient stock for batch {batch_id} (available: {inv.available_quantity}, needed: {-quantity_change})."
            )

        inv.quantity = qty_after
        if qty_after <= 0:
            inv.status = InventoryStatus.DEPLETED.value
        elif inv.status == InventoryStatus.DEPLETED.value and qty_after > 0:
            inv.status = InventoryStatus.AVAILABLE.value
        db.flush()

        now_local = datetime.now().astimezone().isoformat()
        movement = InventoryMovement(
            id=str(uuid.uuid4()),
            organization_id=user_session.organization_id,
            branch_id=branch_id,
            batch_id=batch_id,
            storage_location_id=storage_location_id,
            movement_type=movement_type,
            quantity_change=quantity_change,
            quantity_before=qty_before,
            quantity_after=qty_after,
            reference_type=reference_type,
            reference_id=reference_id,
            user_id=user_session.user_id,
            device_id=user_session.device_id or None,
            notes=notes,
            local_timestamp=now_local,
            is_offline=user_session.is_offline,
        )
        db.add(movement)
        db.flush()

        # Sync event for movement (inventory sync is ALWAYS movement-based deltas, never absolute values!)
        if correlation_id and emit_movement_sync:
            mov_sync = SyncEvent(
                id=str(uuid.uuid4()),
                branch_id=branch_id,
                device_id=user_session.device_id or "00000000-0000-0000-0000-000000000000",
                entity_type="inventory_movement",
                entity_id=movement.id,
                operation=SyncOperation.CREATE.value,
                payload=json.dumps({
                    "id": movement.id,
                    "organization_id": movement.organization_id,
                    "branch_id": movement.branch_id,
                    "batch_id": movement.batch_id,
                    "storage_location_id": movement.storage_location_id,
                    "movement_type": movement.movement_type,
                    "quantity_change": movement.quantity_change,
                    "quantity_before": movement.quantity_before,
                    "quantity_after": movement.quantity_after,
                    "reference_type": movement.reference_type,
                    "reference_id": movement.reference_id,
                    "user_id": movement.user_id,
                    "device_id": movement.device_id,
                    "notes": movement.notes,
                    "local_timestamp": movement.local_timestamp,
                    "is_offline": movement.is_offline,
                }),
                correlation_id=correlation_id,
                dependency_level=SYNC_DEPENDENCY_LEVELS["inventory_movement"],
                schema_version=SYNC_SCHEMA_VERSION,
                local_created_at=now_local,
                status="PENDING",
            )
            db.add(mov_sync)

        # Update Batch status (ACTIVE -> DEPLETED or EXPIRED)
        batch = db.query(Batch).filter_by(id=batch_id).first()
        if batch and batch.status != BatchStatus.RECALLED.value:
            total_qty = (
                db.query(func.sum(BranchInventory.quantity))
                .filter(BranchInventory.batch_id == batch_id)
                .scalar()
                or 0
            )
            if batch.expiry_date < date.today().isoformat():
                batch.status = BatchStatus.EXPIRED.value
            elif total_qty <= 0:
                batch.status = BatchStatus.DEPLETED.value
            else:
                batch.status = BatchStatus.ACTIVE.value
            db.flush()

        return inv, movement

    def load_opening_balance(
        self,
        user_session,
        branch_id: str,
        entries: list[dict],
    ) -> list[InventoryMovement]:
        """
        One-time Opening Balance workflow per branch (Architecture Plan §3.6).
        Each entry dict: {'batch_id': str, 'quantity': int, 'storage_location_id': str | None, 'reorder_level': int | None}.
        """
        self.require_permission(user_session, PermissionCode.INVENTORY_ADJUST.value)
        if not entries:
            raise ValidationError("At least one opening balance entry is required.")

        with self.transaction() as db:
            branch = (
                db.query(Branch)
                .filter_by(id=branch_id, organization_id=user_session.organization_id)
                .first()
            )
            if not branch:
                raise ValidationError("Branch not found.")
            if branch.initial_stock_loaded:
                raise ValidationError(
                    "Opening balance has already been loaded for this branch."
                )

            corr_id = str(uuid.uuid4())
            movements = []
            for entry in entries:
                qty = int(entry['quantity'])
                if qty <= 0:
                    raise ValidationError("Opening balance quantity must be positive.")
                loc_id = entry.get('storage_location_id')
                if loc_id and not branch.uses_storage_locations:
                    raise ValidationError(
                        "Storage locations are not enabled for this branch."
                    )

                inv, mov = self._apply_movement_in_tx(
                    db=db,
                    user_session=user_session,
                    branch_id=branch_id,
                    batch_id=entry['batch_id'],
                    storage_location_id=loc_id,
                    movement_type=MovementType.OPENING_BALANCE.value,
                    quantity_change=qty,
                    reference_type="opening_balance",
                    reference_id=branch.id,
                    notes="Initial opening balance load",
                    correlation_id=corr_id,
                    emit_movement_sync=True,
                )
                if entry.get('reorder_level') is not None:
                    inv.reorder_level = int(entry['reorder_level'])
                movements.append(mov)

            branch.initial_stock_loaded = True
            db.flush()

            self.record_audit_and_sync(
                db_session=db,
                user_session=user_session,
                action=AuditAction.INVENTORY_ADJUSTED.value,
                entity_type="branch",
                entity_id=branch.id,
                operation=SyncOperation.UPDATE.value,
                payload={
                    "id": branch.id,
                    "organization_id": branch.organization_id,
                    "name": branch.name,
                    "code": branch.code,
                    "initial_stock_loaded": True,
                },
                data_before={"initial_stock_loaded": False},
                data_after={"initial_stock_loaded": True, "entries": len(entries)},
                reason="Opening balance loaded",
                correlation_id=corr_id,
            )
            return movements

    def adjust_stock(
        self,
        user_session,
        branch_id: str | None = None,
        batch_id: str = None,
        quantity_change: int = 0,
        movement_type: str = MovementType.STOCK_ADJUSTMENT.value,
        notes: str = "",
        storage_location_id: str | None = None,
        reason: str | None = None,
    ) -> tuple[BranchInventory, InventoryMovement]:
        self.require_permission(user_session, PermissionCode.INVENTORY_ADJUST.value)
        if not branch_id and user_session:
            branch_id = getattr(user_session, "branch_id", None)
        if not branch_id:
            raise ValidationError("Branch ID is required for stock adjustment.")
        if reason and not notes:
            notes = reason
        if quantity_change == 0:
            raise ValidationError("Quantity change cannot be zero.")

        with self.transaction() as db:
            corr_id = str(uuid.uuid4())
            ref_id = str(uuid.uuid4())
            inv, mov = self._apply_movement_in_tx(
                db=db,
                user_session=user_session,
                branch_id=branch_id,
                batch_id=batch_id,
                storage_location_id=storage_location_id,
                movement_type=movement_type,
                quantity_change=quantity_change,
                reference_type="stock_adjustment",
                reference_id=ref_id,
                notes=notes,
                correlation_id=corr_id,
                allow_negative=False,
                emit_movement_sync=False,
            )
            self.record_audit_and_sync(
                db_session=db,
                user_session=user_session,
                action=AuditAction.INVENTORY_ADJUSTED.value,
                entity_type="inventory_movement",
                entity_id=mov.id,
                operation=SyncOperation.CREATE.value,
                payload={
                    "id": mov.id,
                    "organization_id": mov.organization_id,
                    "branch_id": mov.branch_id,
                    "batch_id": mov.batch_id,
                    "storage_location_id": mov.storage_location_id,
                    "movement_type": mov.movement_type,
                    "quantity_change": mov.quantity_change,
                    "quantity_before": mov.quantity_before,
                    "quantity_after": mov.quantity_after,
                    "reference_type": mov.reference_type,
                    "reference_id": mov.reference_id,
                    "user_id": mov.user_id,
                    "device_id": mov.device_id,
                    "notes": mov.notes,
                    "local_timestamp": mov.local_timestamp,
                    "is_offline": mov.is_offline,
                },
                data_before={"quantity": mov.quantity_before},
                data_after={"quantity": mov.quantity_after},
                reason=notes,
                correlation_id=corr_id,
            )
            return inv, mov

    def list_batches(self, organization_id: str, product_id: str | None = None) -> list[Batch]:
        with self.transaction() as db:
            q = db.query(Batch).filter_by(organization_id=organization_id)
            if product_id:
                q = q.filter_by(product_id=product_id)
            return q.order_by(Batch.expiry_date.asc(), Batch.received_date.asc()).all()

    def list_branch_inventory(
        self, branch_id: str, product_id: str | None = None
    ) -> list[BranchInventory]:
        with self.transaction() as db:
            q = db.query(BranchInventory).filter_by(branch_id=branch_id)
            if product_id:
                q = q.join(Batch, Batch.id == BranchInventory.batch_id).filter(
                    Batch.product_id == product_id
                )
            return q.all()

    def list_movements(
        self, branch_id: str, batch_id: str | None = None
    ) -> list[InventoryMovement]:
        with self.transaction() as db:
            q = db.query(InventoryMovement).filter_by(branch_id=branch_id)
            if batch_id:
                q = q.filter_by(batch_id=batch_id)
            return q.order_by(InventoryMovement.created_at.desc()).all()

    def get_product_stock(
        self, organization_id: str, branch_id: str, product_id: str
    ) -> int:
        """Returns total active, non-expired, available stock for a product in a branch."""
        with self.transaction() as db:
            today_iso = date.today().isoformat()
            batches = (
                db.query(Batch.id)
                .filter(
                    Batch.organization_id == organization_id,
                    Batch.product_id == product_id,
                    Batch.status == BatchStatus.ACTIVE.value,
                    Batch.expiry_date >= today_iso,
                )
                .all()
            )
            batch_ids = [b[0] for b in batches]
            if not batch_ids:
                return 0
            invs = (
                db.query(BranchInventory)
                .filter(
                    BranchInventory.organization_id == organization_id,
                    BranchInventory.branch_id == branch_id,
                    BranchInventory.batch_id.in_(batch_ids),
                )
                .all()
            )
            return sum(i.available_quantity for i in invs)

    def get_inventory_summary_data(
        self,
        organization_id: str,
        branch_id: str,
        search_query: str | None = None,
        category_id: str | None = None,
        status_filter: str | None = None,
    ) -> dict:
        """
        Ultra-fast single-pass SQL query joining BranchInventory, Batch, Product, and Category.
        Computes KPI metric aggregates directly in SQLite (sub-millisecond) and returns clean tabular data.
        """
        with self.transaction() as db:
            today_iso = date.today().isoformat()
            ninety_days_iso = (date.today() + timedelta(days=90)).isoformat()

            q = (
                db.query(
                    Product.id.label("product_id"),
                    Product.name.label("product_name"),
                    Product.sku.label("product_sku"),
                    Product.category_id.label("category_id"),
                    Category.name.label("category_name"),
                    Batch.id.label("batch_id"),
                    Batch.batch_number.label("batch_number"),
                    Batch.manufacturing_date.label("manufacturing_date"),
                    Batch.expiry_date.label("expiry_date"),
                    Batch.purchase_price.label("purchase_price"),
                    Batch.status.label("batch_status"),
                    BranchInventory.quantity.label("quantity"),
                    BranchInventory.reserved_quantity.label("reserved_quantity"),
                    BranchInventory.storage_location_id.label("storage_location_id"),
                    StorageLocation.name.label("storage_location_name"),
                    StorageLocation.location_type.label("storage_location_type"),
                )
                .join(Batch, BranchInventory.batch_id == Batch.id)
                .join(Product, Batch.product_id == Product.id)
                .outerjoin(Category, Product.category_id == Category.id)
                .outerjoin(StorageLocation, BranchInventory.storage_location_id == StorageLocation.id)
                .filter(
                    BranchInventory.organization_id == organization_id,
                    BranchInventory.branch_id == branch_id,
                )
            )

            if category_id:
                q = q.filter(Product.category_id == category_id)

            if search_query and search_query.strip():
                term = f"%{search_query.strip()}%"
                q = q.filter(
                    (Product.name.ilike(term))
                    | (Product.sku.ilike(term))
                    | (Batch.batch_number.ilike(term))
                    | (StorageLocation.name.ilike(term))
                )

            rows = q.order_by(Product.name.asc(), Batch.expiry_date.asc()).all()

            product_ids = list({r.product_id for r in rows if r.product_id})
            price_map: dict[str, Decimal] = {}
            recent_price_map: dict[str, dict] = {}
            if product_ids:
                active_prices = (
                    db.query(Price)
                    .filter(
                        Price.organization_id == organization_id,
                        Price.product_id.in_(product_ids),
                        Price.is_current.is_(True),
                    )
                    .all()
                )
                for p in active_prices:
                    if p.product_id not in price_map:
                        price_map[p.product_id] = Decimal(str(p.selling_price or "0.00"))
                    elif branch_id and p.branch_id == branch_id:
                        price_map[p.product_id] = Decimal(str(p.selling_price or "0.00"))

                from desktop.app.services.pricing_service import (
                    build_attribution_maps,
                    resolve_price_attribution,
                )

                attr_maps = build_attribution_maps(db, organization_id)
                cutoff_24h_iso = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
                recent_ph = (
                    db.query(PriceHistory)
                    .filter(
                        PriceHistory.organization_id == organization_id,
                        PriceHistory.product_id.in_(product_ids),
                        PriceHistory.created_at >= cutoff_24h_iso,
                        ~PriceHistory.change_reason.like("Synced from organization price:%"),
                        ~PriceHistory.change_reason.like("Forced update from org default price:%"),
                    )
                    .order_by(PriceHistory.created_at.desc(), PriceHistory.version.desc())
                    .all()
                )
                for ph in recent_ph:
                    if ph.product_id not in recent_price_map:
                        resolved_branch, resolved_account = resolve_price_attribution(
                            attr_maps,
                            price_id=ph.price_id,
                            branch_id=ph.branch_id,
                            changed_by_id=ph.changed_by_id,
                            change_reason=ph.change_reason,
                        )
                        recent_price_map[ph.product_id] = {
                            "old_price": Decimal(str(ph.old_price)) if ph.old_price is not None else None,
                            "new_price": Decimal(str(ph.new_price)),
                            "change_reason": ph.change_reason or "Price updated",
                            "received_at": ph.created_at,
                            "branch_name": resolved_branch,
                            "account_name": resolved_account,
                        }

                for p in active_prices:
                    if p.product_id not in recent_price_map and (p.version or 1) > 1 and (p.updated_at or "") >= cutoff_24h_iso:
                        resolved_branch, resolved_account = resolve_price_attribution(
                            attr_maps,
                            price_id=p.id,
                            branch_id=p.branch_id,
                            changed_by_id=p.created_by_id,
                            change_reason="Recent price update",
                        )
                        recent_price_map[p.product_id] = {
                            "old_price": None,
                            "new_price": Decimal(str(p.selling_price)),
                            "change_reason": "Recent price update",
                            "received_at": p.updated_at,
                            "branch_name": resolved_branch,
                            "account_name": resolved_account,
                        }

                missing_old = [pid for pid, info in recent_price_map.items() if info.get("old_price") is None]
                if missing_old:
                    retired = (
                        db.query(Price)
                        .filter(
                            Price.organization_id == organization_id,
                            Price.product_id.in_(missing_old),
                            Price.is_current.is_(False),
                        )
                        .order_by(Price.version.desc(), Price.updated_at.desc())
                        .all()
                    )
                    for rp in retired:
                        if recent_price_map[rp.product_id].get("old_price") is None:
                            recent_price_map[rp.product_id]["old_price"] = Decimal(str(rp.selling_price))

            total_items = 0
            low_stock_count = 0
            expiring_count = 0
            total_valuation = Decimal("0.00")
            items = []

            for r in rows:
                qty = r.quantity or 0
                reserved = r.reserved_quantity or 0
                cost = Decimal(str(r.purchase_price or "0.00"))
                selling_price = price_map.get(r.product_id, Decimal("0.00"))
                line_val = cost * Decimal(qty)

                total_items += 1
                total_valuation += line_val

                is_exp = bool(
                    (r.expiry_date and r.expiry_date < today_iso)
                    or (r.batch_status == BatchStatus.EXPIRED.value)
                )
                is_low = bool(0 < qty <= 10)
                is_expiring_soon = bool(
                    r.expiry_date and today_iso <= r.expiry_date <= ninety_days_iso
                )

                if is_low:
                    low_stock_count += 1
                if is_expiring_soon:
                    expiring_count += 1

                if is_exp:
                    status_text = "EXPIRED"
                elif is_low:
                    status_text = "LOW STOCK"
                elif qty <= 0:
                    status_text = "DEPLETED"
                else:
                    status_text = "ACTIVE"

                if status_filter and status_filter != "ALL":
                    if status_filter == "ACTIVE" and status_text not in ("ACTIVE", "LOW STOCK"):
                        continue
                    elif status_filter == "LOW" and status_text != "LOW STOCK":
                        continue
                    elif status_filter == "EXPIRED" and status_text != "EXPIRED":
                        continue

                items.append({
                    "product_id": r.product_id,
                    "item_name": f"{r.product_name} ({r.product_sku})" if r.product_sku else r.product_name,
                    "category": r.category_name or "General",
                    "category_id": r.category_id,
                    "batch_id": r.batch_id,
                    "batch_no": r.batch_number,
                    "storage_location_id": r.storage_location_id,
                    "shelf_name": r.storage_location_name or "—",
                    "storage_location_type": r.storage_location_type or "",
                    "mfg_date": r.manufacturing_date or "—",
                    "expiry": r.expiry_date or "N/A",
                    "quantity": qty,
                    "reserved": reserved,
                    "cost": cost,
                    "selling_price": selling_price,
                    "price_update_info": recent_price_map.get(r.product_id),
                    "total_value": line_val,
                    "status": status_text,
                })

            return {
                "total_items": total_items,
                "low_stock_count": low_stock_count,
                "expiring_count": expiring_count,
                "total_valuation": total_valuation,
                "items": items,
            }

    def get_stocks_bulk(
        self, organization_id: str, branch_id: str, product_ids: list[str]
    ) -> dict[str, int]:
        """
        Batch-calculates active, non-expired, available stock for multiple products in a single SQL query.
        Returns dict mapping product_id -> available_quantity sum.
        """
        if not product_ids:
            return {}
        with self.transaction() as db:
            today_iso = date.today().isoformat()
            rows = (
                db.query(
                    Batch.product_id,
                    func.coalesce(func.sum(BranchInventory.quantity - BranchInventory.reserved_quantity), 0).label("stock")
                )
                .join(BranchInventory, BranchInventory.batch_id == Batch.id)
                .filter(
                    BranchInventory.organization_id == organization_id,
                    BranchInventory.branch_id == branch_id,
                    Batch.product_id.in_(product_ids),
                    Batch.status == BatchStatus.ACTIVE.value,
                    Batch.expiry_date >= today_iso,
                )
                .group_by(Batch.product_id)
                .all()
            )
            stock_map = {r[0]: max(0, int(r[1])) for r in rows}
            return {pid: stock_map.get(pid, 0) for pid in product_ids}

    def get_product_shelves_bulk(
        self, organization_id: str, branch_id: str, product_ids: list[str]
    ) -> dict[str, str]:
        """
        Returns a mapping of product_id -> comma-separated shelf names (e.g. 'Shelf A1, Fridge 1')
        for products in the branch.
        """
        if not product_ids:
            return {}
        with self.transaction() as db:
            rows = (
                db.query(Batch.product_id, StorageLocation.name)
                .join(BranchInventory, BranchInventory.batch_id == Batch.id)
                .join(StorageLocation, BranchInventory.storage_location_id == StorageLocation.id)
                .filter(
                    BranchInventory.organization_id == organization_id,
                    BranchInventory.branch_id == branch_id,
                    Batch.product_id.in_(product_ids),
                    StorageLocation.is_active.is_(True),
                )
                .order_by(StorageLocation.name.asc())
                .all()
            )
            shelf_map: dict[str, list[str]] = {}
            for pid, sname in rows:
                if sname and sname not in shelf_map.setdefault(pid, []):
                    shelf_map[pid].append(sname)
            return {pid: ", ".join(names) for pid, names in shelf_map.items()}

    def get_batch_full_details(
        self,
        organization_id: str,
        branch_id: str,
        batch_id: str,
        storage_location_id: str | None = None,
    ) -> dict:
        """Returns comprehensive drug, batch, shelf, supervisor, and valuation details for the View Details dialog."""
        with self.transaction() as db:
            batch = db.query(Batch).filter_by(id=batch_id, organization_id=organization_id).first()
            if not batch:
                return {}
            product = db.query(Product).filter_by(id=batch.product_id, organization_id=organization_id).first()
            category = (
                db.query(Category).filter_by(id=product.category_id).first()
                if product and product.category_id
                else None
            )
            prod_type = (
                db.query(ProductType).filter_by(id=product.product_type_id).first()
                if product and product.product_type_id
                else None
            )
            manufacturer = (
                db.query(Manufacturer).filter_by(id=product.manufacturer_id).first()
                if product and product.manufacturer_id
                else None
            )
            supplier = (
                db.query(Supplier).filter_by(id=batch.supplier_id).first()
                if batch.supplier_id
                else None
            )

            inv_q = db.query(BranchInventory).filter_by(
                organization_id=organization_id,
                branch_id=branch_id,
                batch_id=batch_id,
            )
            if storage_location_id is not None:
                inv_q = inv_q.filter_by(storage_location_id=storage_location_id)
            inv = inv_q.first()

            eff_loc_id = inv.storage_location_id if inv else storage_location_id
            loc = db.query(StorageLocation).filter_by(id=eff_loc_id).first() if eff_loc_id else None
            supervisor_label = "—"
            if loc:
                assign_row = (
                    db.query(StorageLocationAssignment, User)
                    .join(User, StorageLocationAssignment.user_id == User.id)
                    .filter(
                        StorageLocationAssignment.storage_location_id == loc.id,
                        StorageLocationAssignment.is_active.is_(True),
                    )
                    .order_by(StorageLocationAssignment.created_at.desc())
                    .first()
                )
                if assign_row:
                    _, sup_usr = assign_row
                    supervisor_label = (
                        f"{sup_usr.full_name} (@{sup_usr.username})"
                        if sup_usr.full_name
                        else f"@{sup_usr.username}"
                    )

            return {
                # Product fields
                "product_name": product.name if product else "—",
                "sku": product.sku if product else "—",
                "barcode": (product.barcode if product and product.barcode else "—"),
                "generic_name": (product.generic_name if product and product.generic_name else "—"),
                "brand_name": (product.brand_name if product and product.brand_name else "—"),
                "category_name": category.name if category else "General",
                "product_type": prod_type.name if prod_type else "—",
                "manufacturer_name": manufacturer.name if manufacturer else "—",
                "strength": (product.strength if product and product.strength else "—"),
                "dosage_form": (product.dosage_form if product and product.dosage_form else "—"),
                "route": (product.route if product and product.route else "—"),
                "formulation": (product.formulation if product and product.formulation else "—"),
                "active_ingredients": (product.active_ingredients if product and product.active_ingredients else "—"),
                "indication": (product.indication if product and product.indication else "—"),
                "storage_conditions": (product.storage_conditions if product and product.storage_conditions else "—"),
                "prescription_required": "Yes (Rx Only)" if (product and product.prescription_required) else "No (OTC)",
                "controlled_status": (product.controlled_status if product and product.controlled_status else "Standard"),
                "description": (product.description if product and product.description else "—"),
                # Batch & Supplier fields
                "batch_number": batch.batch_number or "—",
                "manufacturing_date": batch.manufacturing_date or "—",
                "expiry_date": batch.expiry_date or "—",
                "received_date": batch.received_date or "—",
                "supplier_name": supplier.name if supplier else "—",
                "invoice_reference": batch.invoice_reference or "—",
                "batch_status": batch.status or "ACTIVE",
                "batch_notes": batch.notes or "—",
                # Shelf & Supervisor fields
                "shelf_name": loc.name if loc else "Unassigned / General Floor",
                "shelf_type": loc.location_type if (loc and loc.location_type) else "—",
                "shelf_description": loc.description if (loc and loc.description) else "—",
                "shelf_supervisor": supervisor_label,
            }
