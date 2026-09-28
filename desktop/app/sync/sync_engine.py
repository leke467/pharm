import json
import uuid
from collections import OrderedDict
from datetime import date, datetime, timezone
from decimal import Decimal
from sqlalchemy import func
from desktop.app.config.constants import MAX_SYNC_BATCH_SIZE
from desktop.app.db.models import (
    Organization,
    Branch,
    Device,
    User,
    Role,
    Permission,
    RolePermission,
    UserRole,
    OfflineCredential,
    Category,
    ProductType,
    Manufacturer,
    Supplier,
    Product,
    ProductBranch,
    Batch,
    StorageLocation,
    BranchInventory,
    InventoryMovement,
    Price,
    SyncEvent,
    SyncCursor,
    LicenseState,
)
from desktop.app.domain.exceptions import NetworkError
from shared.enums import BatchStatus, InventoryStatus


CUSTOM_DOWNLOAD_HANDLERS = {}


def register_download_handler(entity_type: str, handler_fn):
    CUSTOM_DOWNLOAD_HANDLERS[entity_type] = handler_fn


class SyncEngine:
    """
    Core Desktop Synchronization Engine (Architecture Plan §4).
    Handles:
    - Dependency-ordered, correlation_id-preserving outbox upload batches.
    - Timeout-resilient retry & exponential backoff (reverting SENDING -> PENDING on timeout).
    - Monotonic cursor-based incremental download (`SyncCursor.last_server_sequence`).
    - Device-level echo suppression (`source_device_id != device_id`).
    - Movement-based inventory delta application on download.
    - Disabled-user immediate local lockout and piggybacked license status updates.
    """

    def __init__(self, api_client, db_manager):
        self.api_client = api_client
        self.db_manager = db_manager

    @staticmethod
    def calculate_backoff_seconds(retry_count: int) -> int:
        """Exponential backoff capped at 300 seconds: min(300, 5 * 2^retry_count)."""
        return min(300, 5 * (2 ** max(0, retry_count)))

    def get_pending_count(self, branch_id: str | None = None) -> int:
        with self.db_manager.get_session() as db:
            q = db.query(SyncEvent).filter(
                SyncEvent.status.in_(["PENDING", "FAILED"]),
                SyncEvent.retry_count < SyncEvent.max_retries,
            )
            if branch_id:
                q = q.filter(SyncEvent.branch_id == branch_id)
            return q.count()

    def get_upload_batch(
        self,
        branch_id: str | None = None,
        max_batch_size: int = MAX_SYNC_BATCH_SIZE,
    ) -> list[dict]:
        """
        Selects pending/retriable SyncEvents ordered by (dependency_level ASC, local_created_at ASC),
        keeping all events sharing the same `correlation_id` in the same batch (never splitting
        a correlated transaction across batch boundaries).
        """
        with self.db_manager.get_session() as db:
            q = db.query(SyncEvent).filter(
                SyncEvent.status.in_(["PENDING", "FAILED"]),
                SyncEvent.retry_count < SyncEvent.max_retries,
            )
            if branch_id:
                q = q.filter(SyncEvent.branch_id == branch_id)

            candidates = q.order_by(
                SyncEvent.dependency_level.asc(),
                SyncEvent.local_created_at.asc(),
            ).all()

            if not candidates:
                return []

            groups: OrderedDict[str, list[SyncEvent]] = OrderedDict()
            for ev in candidates:
                key = f"corr_{ev.correlation_id}" if ev.correlation_id else f"single_{ev.id}"
                groups.setdefault(key, []).append(ev)

            # Sort groups by minimum (dependency_level, local_created_at)
            sorted_groups = sorted(
                groups.values(),
                key=lambda g: (
                    min(e.dependency_level for e in g),
                    min(e.local_created_at or "" for e in g),
                ),
            )

            selected: list[SyncEvent] = []
            for group in sorted_groups:
                group.sort(key=lambda e: (e.dependency_level, e.local_created_at or ""))
                if len(selected) + len(group) <= max_batch_size or len(selected) == 0:
                    selected.extend(group)
                else:
                    # Do not split this correlation_id group; defer it to the next upload batch
                    break

            now_iso = datetime.now(timezone.utc).isoformat()
            batch_dicts = []
            for ev in selected:
                ev.status = "SENDING"
                ev.last_attempt_at = now_iso
                payload_obj = json.loads(ev.payload) if isinstance(ev.payload, str) else (ev.payload or {})
                batch_dicts.append({
                    "id": ev.id,
                    "entity_type": ev.entity_type,
                    "entity_id": ev.entity_id,
                    "operation": ev.operation,
                    "payload": payload_obj,
                    "correlation_id": ev.correlation_id,
                    "dependency_level": ev.dependency_level,
                    "schema_version": ev.schema_version,
                    "local_created_at": ev.local_created_at,
                })
            db.flush()
            return batch_dicts

    def upload_pending_events(self, branch_id: str, device_id: str) -> dict:
        """
        Uploads batches of pending outbox events to `/api/v1/sync/upload/`.
        On HTTP timeout / NetworkError, returns SENDING events to PENDING and increments
        retry_count, relying on server ProcessedEvent idempotency on retry.
        """
        batch = self.get_upload_batch(branch_id=branch_id)
        if not batch:
            return {"uploaded": 0, "processed": 0, "failed": 0, "conflicts": 0}

        batch_ids = [item["id"] for item in batch]
        try:
            response = self.api_client.post(
                "/api/v1/sync/upload/",
                data={
                    "device_id": device_id,
                    "branch_id": branch_id,
                    "events": batch,
                },
            )
        except NetworkError as exc:
            # Architecture Decision §4.3 & §4.7: On timeout/network failure, return events to PENDING
            # (unless max_retries reached) and rely on server ProcessedEvent idempotency.
            with self.db_manager.get_session() as db:
                events = db.query(SyncEvent).filter(SyncEvent.id.in_(batch_ids)).all()
                for ev in events:
                    ev.retry_count = (ev.retry_count or 0) + 1
                    ev.error_message = str(exc)
                    if ev.retry_count >= ev.max_retries:
                        ev.status = "FAILED"
                    else:
                        ev.status = "PENDING"
                db.flush()
            raise

        results = response.get("results", [])
        processed_count = 0
        failed_count = 0
        conflict_count = 0

        with self.db_manager.get_session() as db:
            results_map = {r["event_id"]: r for r in results}
            events = db.query(SyncEvent).filter(SyncEvent.id.in_(batch_ids)).all()
            for ev in events:
                res = results_map.get(ev.id)
                if not res:
                    ev.status = "PENDING"
                    continue

                st = res.get("status")
                if st in ("PROCESSED", "DUPLICATE_IGNORED"):
                    ev.status = "SENT"
                    ev.server_received_at = res.get("server_received_at") or datetime.now(timezone.utc).isoformat()
                    ev.error_message = None
                    processed_count += 1
                elif st == "CONFLICT":
                    ev.status = "CONFLICT"
                    ev.error_message = res.get("error_message", "Conflict reported by server")
                    conflict_count += 1
                else:
                    ev.retry_count = (ev.retry_count or 0) + 1
                    ev.status = "FAILED"
                    ev.error_message = res.get("error_message", "Processing failed on server")
                    failed_count += 1
            db.flush()

        return {
            "uploaded": len(batch),
            "processed": processed_count,
            "failed": failed_count,
            "conflicts": conflict_count,
        }

    def _apply_downloaded_delivery(self, db, organization_id: str, delivery: dict):
        entity_type = delivery["entity_type"]
        entity_id = str(delivery["entity_id"])
        operation = delivery["operation"]
        payload = delivery.get("payload") or {}

        if entity_type in CUSTOM_DOWNLOAD_HANDLERS:
            CUSTOM_DOWNLOAD_HANDLERS[entity_type](db, organization_id, entity_id, operation, payload, delivery)
            return

        if entity_type == "organization":
            org = db.query(Organization).filter_by(id=entity_id).first()
            if org:
                if payload.get("name"):
                    org.name = payload["name"]
                if "address" in payload:
                    org.address = payload["address"] or ""
                if "phone" in payload:
                    org.phone = payload["phone"] or ""
                if "email" in payload:
                    org.email = payload["email"] or ""
                if "settings" in payload and payload["settings"] is not None:
                    org.settings = (
                        json.dumps(payload["settings"])
                        if isinstance(payload["settings"], dict)
                        else str(payload["settings"])
                    )
                db.flush()

        elif entity_type == "branch":
            branch = db.query(Branch).filter_by(id=entity_id).first()
            if not branch:
                branch = Branch(
                    id=entity_id,
                    organization_id=organization_id,
                    name=payload.get("name", "Branch"),
                    code=payload.get("code", entity_id[:6]),
                )
                db.add(branch)
            else:
                if payload.get("name"):
                    branch.name = payload["name"]
                if payload.get("code"):
                    branch.code = payload["code"]
            for f in ("address", "phone", "email", "uses_storage_locations", "initial_stock_loaded", "is_active"):
                if f in payload and payload[f] is not None:
                    setattr(branch, f, payload[f])
            db.flush()

        elif entity_type == "device":
            dev = db.query(Device).filter_by(id=entity_id).first()
            br_id = str(payload.get("branch_id") or payload.get("branch") or "")
            if not dev and br_id:
                dev = Device(
                    id=entity_id,
                    organization_id=organization_id,
                    branch_id=br_id,
                    name=payload.get("name", "Terminal"),
                    code=payload.get("code", entity_id[:5].upper()),
                    device_identifier=payload.get("device_identifier") or f"DEV-{entity_id[:8]}",
                    is_active=payload.get("is_active", True),
                )
                db.add(dev)
            elif dev:
                for f in ("name", "code", "is_active"):
                    if f in payload and payload[f] is not None:
                        setattr(dev, f, payload[f])
            db.flush()

        elif entity_type == "user":
            u = db.query(User).filter_by(id=entity_id).first()
            if not u and payload.get("username"):
                u = db.query(User).filter_by(organization_id=organization_id, username=payload["username"]).first()
            if not u and payload.get("username"):
                u = User(
                    id=entity_id,
                    organization_id=organization_id,
                    username=payload["username"],
                    full_name=payload.get("full_name", payload["username"]),
                    email=payload.get("email", ""),
                    phone=payload.get("phone", ""),
                    is_org_admin=bool(payload.get("is_org_admin", False)),
                    default_branch_id=str(payload["default_branch_id"]) if payload.get("default_branch_id") else None,
                    is_active=bool(payload.get("is_active", True)),
                )
                db.add(u)
            elif u:
                for f in ("full_name", "email", "phone", "is_org_admin", "is_active"):
                    if f in payload and payload[f] is not None:
                        setattr(u, f, payload[f])
                if "default_branch_id" in payload:
                    u.default_branch_id = str(payload["default_branch_id"]) if payload["default_branch_id"] else None
            db.flush()

        elif entity_type == "role":
            role = db.query(Role).filter_by(id=entity_id).first()
            if not role:
                role = Role(
                    id=entity_id,
                    organization_id=organization_id,
                    name=payload.get("name", "Role"),
                    description=payload.get("description", ""),
                    is_system=bool(payload.get("is_system", False)),
                    is_active=bool(payload.get("is_active", True)),
                )
                db.add(role)
            else:
                if payload.get("name"):
                    role.name = payload["name"]
                if "description" in payload and payload["description"] is not None:
                    role.description = payload["description"]
                if "is_active" in payload and payload["is_active"] is not None:
                    role.is_active = bool(payload["is_active"])
            db.flush()
            perm_codes = payload.get("permission_codes")
            if isinstance(perm_codes, list):
                db.query(RolePermission).filter_by(role_id=role.id).delete()
                for code in dict.fromkeys(perm_codes):
                    perm = db.query(Permission).filter_by(code=code).first()
                    if not perm:
                        perm = Permission(
                            id=str(uuid.uuid4()),
                            code=code,
                            name=code.replace(".", " - ").title(),
                            category=code.split(".")[0].title(),
                        )
                        db.add(perm)
                        db.flush()
                    db.add(RolePermission(id=str(uuid.uuid4()), role_id=role.id, permission_id=perm.id))
                db.flush()

        elif entity_type == "user_role":
            ur = db.query(UserRole).filter_by(id=entity_id).first()
            u_id = payload.get("user_id") or payload.get("user")
            r_id = payload.get("role_id") or payload.get("role")
            b_id = payload.get("branch_id") or payload.get("branch")
            if not ur and u_id and r_id:
                ur = UserRole(
                    id=entity_id,
                    user_id=str(u_id),
                    role_id=str(r_id),
                    branch_id=str(b_id) if b_id else None,
                    is_active=bool(payload.get("is_active", True)),
                )
                db.add(ur)
            elif ur:
                if "is_active" in payload and payload["is_active"] is not None:
                    ur.is_active = bool(payload["is_active"])
            db.flush()

        elif entity_type == "category":
            cat = db.query(Category).filter_by(id=entity_id).first()
            if not cat:
                cat = Category(
                    id=entity_id,
                    organization_id=organization_id,
                    name=payload["name"],
                    parent_id=payload.get("parent_id") or payload.get("parent"),
                    is_active=payload.get("is_active", True),
                )
                db.add(cat)
            else:
                cat.name = payload.get("name", cat.name)
                cat.parent_id = payload.get("parent_id") or payload.get("parent")
                if "is_active" in payload:
                    cat.is_active = bool(payload["is_active"])
            db.flush()

        elif entity_type == "product_type":
            pt = db.query(ProductType).filter_by(id=entity_id).first()
            if not pt:
                pt = ProductType(
                    id=entity_id,
                    organization_id=organization_id,
                    name=payload["name"],
                    description=payload.get("description", ""),
                    is_active=payload.get("is_active", True),
                )
                db.add(pt)
            else:
                pt.name = payload.get("name", pt.name)
                pt.description = payload.get("description", pt.description)
                if "is_active" in payload:
                    pt.is_active = bool(payload["is_active"])
            db.flush()

        elif entity_type == "manufacturer":
            mfg = db.query(Manufacturer).filter_by(id=entity_id).first()
            if not mfg:
                mfg = Manufacturer(
                    id=entity_id,
                    organization_id=organization_id,
                    name=payload["name"],
                    country=payload.get("country", ""),
                    contact_info=payload.get("contact_info", ""),
                    is_active=payload.get("is_active", True),
                )
                db.add(mfg)
            else:
                mfg.name = payload.get("name", mfg.name)
                mfg.country = payload.get("country", mfg.country)
                mfg.contact_info = payload.get("contact_info", mfg.contact_info)
            db.flush()

        elif entity_type == "supplier":
            sup = db.query(Supplier).filter_by(id=entity_id).first()
            if not sup:
                sup = Supplier(
                    id=entity_id,
                    organization_id=organization_id,
                    name=payload["name"],
                    contact_person=payload.get("contact_person", ""),
                    phone=payload.get("phone", ""),
                    email=payload.get("email", ""),
                    address=payload.get("address", ""),
                    notes=payload.get("notes", ""),
                    is_active=payload.get("is_active", True),
                )
                db.add(sup)
            else:
                for f in ("name", "contact_person", "phone", "email", "address", "notes", "is_active"):
                    if f in payload and payload[f] is not None:
                        setattr(sup, f, payload[f])
            db.flush()

        elif entity_type == "product":
            prod = db.query(Product).filter_by(id=entity_id).first()
            cat_id = str(payload.get("category_id") or payload.get("category"))
            pt_id = payload.get("product_type_id") or payload.get("product_type")
            mfg_id = payload.get("manufacturer_id") or payload.get("manufacturer")
            if not prod:
                prod = Product(
                    id=entity_id,
                    organization_id=organization_id,
                    sku=payload["sku"],
                    name=payload["name"],
                    category_id=cat_id,
                )
                db.add(prod)
            prod.sku = payload.get("sku", prod.sku)
            prod.name = payload.get("name", prod.name)
            prod.category_id = cat_id
            prod.product_type_id = str(pt_id) if pt_id else None
            prod.manufacturer_id = str(mfg_id) if mfg_id else None
            for f in (
                "barcode",
                "generic_name",
                "brand_name",
                "description",
                "active_ingredients",
                "strength",
                "dosage_form",
                "route",
                "formulation",
                "indication",
                "contraindications",
                "precautions",
                "drug_interactions",
                "side_effects",
                "storage_conditions",
                "age_suitability",
                "pregnancy_caution",
                "prescription_required",
                "controlled_status",
                "importer",
                "regulatory_info",
                "image_url",
                "notes",
                "is_active",
            ):
                if f in payload:
                    setattr(prod, f, payload[f])
            db.flush()

        elif entity_type == "product_branch":
            pb = db.query(ProductBranch).filter_by(id=entity_id).first()
            prod_id = str(payload.get("product_id") or payload.get("product"))
            br_id = str(payload.get("branch_id") or payload.get("branch"))
            if not pb:
                pb = ProductBranch(
                    id=entity_id,
                    product_id=prod_id,
                    branch_id=br_id,
                    is_active=payload.get("is_active", True),
                    reorder_level=payload.get("reorder_level"),
                )
                db.add(pb)
            else:
                pb.is_active = payload.get("is_active", pb.is_active)
                pb.reorder_level = payload.get("reorder_level", pb.reorder_level)
            db.flush()

        elif entity_type == "batch":
            batch = db.query(Batch).filter_by(id=entity_id).first()
            prod_id = str(payload.get("product_id") or payload.get("product"))
            if not batch:
                batch = Batch(
                    id=entity_id,
                    organization_id=organization_id,
                    product_id=prod_id,
                    batch_number=payload["batch_number"],
                    manufacturing_date=payload.get("manufacturing_date"),
                    expiry_date=str(payload["expiry_date"])[:10],
                    purchase_price=Decimal(str(payload.get("purchase_price", "0.00"))),
                    supplier_id=str(payload["supplier_id"]) if payload.get("supplier_id") else None,
                    invoice_reference=payload.get("invoice_reference", ""),
                    received_date=str(payload.get("received_date") or date.today().isoformat())[:10],
                    status=payload.get("status", BatchStatus.ACTIVE.value),
                    notes=payload.get("notes", ""),
                )
                db.add(batch)
            else:
                if "status" in payload:
                    batch.status = payload["status"]
                if "notes" in payload:
                    batch.notes = payload["notes"]
            db.flush()

        elif entity_type == "storage_location":
            loc = db.query(StorageLocation).filter_by(id=entity_id).first()
            br_id = str(payload.get("branch_id") or payload.get("branch"))
            if not loc:
                loc = StorageLocation(
                    id=entity_id,
                    organization_id=organization_id,
                    branch_id=br_id,
                    name=payload["name"],
                    description=payload.get("description", ""),
                    location_type=payload.get("location_type", ""),
                    is_active=payload.get("is_active", True),
                )
                db.add(loc)
            else:
                loc.name = payload.get("name", loc.name)
                loc.description = payload.get("description", loc.description)
                loc.location_type = payload.get("location_type", loc.location_type)
                loc.is_active = payload.get("is_active", loc.is_active)
            db.flush()

        elif entity_type == "price":
            prod_id = str(payload.get("product_id") or payload.get("product"))
            br_id = payload.get("branch_id") or payload.get("branch")
            br_id_str = str(br_id) if br_id else None
            is_curr = bool(payload.get("is_current", True))

            if is_curr:
                prev_prices = (
                    db.query(Price)
                    .filter_by(
                        organization_id=organization_id,
                        product_id=prod_id,
                        branch_id=br_id_str,
                        is_current=True,
                    )
                    .all()
                )
                for p in prev_prices:
                    if p.id != entity_id:
                        p.is_current = False
                        p.effective_to = datetime.now(timezone.utc).isoformat()

            price = db.query(Price).filter_by(id=entity_id).first()
            if not price:
                price = Price(
                    id=entity_id,
                    organization_id=organization_id,
                    product_id=prod_id,
                    branch_id=br_id_str,
                    selling_price=Decimal(str(payload["selling_price"])),
                    currency=payload.get("currency", "NGN"),
                    is_current=is_curr,
                    version=int(payload.get("version", 1)),
                    effective_from=payload.get("effective_from") or datetime.now(timezone.utc).isoformat(),
                    sync_status="SYNCED",
                )
                db.add(price)
            else:
                price.selling_price = Decimal(str(payload["selling_price"]))
                price.is_current = is_curr
                price.version = int(payload.get("version", price.version))
                price.sync_status = "SYNCED"
            db.flush()

        elif entity_type == "inventory_movement":
            # Idempotent check: if movement already exists locally, skip delta application
            existing_mov = db.query(InventoryMovement).filter_by(id=entity_id).first()
            if existing_mov:
                return

            mov_branch_id = str(payload["branch_id"])
            mov_batch_id = str(payload["batch_id"])
            loc_id = str(payload["storage_location_id"]) if payload.get("storage_location_id") else None
            qty_change = int(payload["quantity_change"])

            inv = (
                db.query(BranchInventory)
                .filter_by(
                    organization_id=organization_id,
                    branch_id=mov_branch_id,
                    batch_id=mov_batch_id,
                    storage_location_id=loc_id,
                )
                .first()
            )
            if not inv:
                inv = BranchInventory(
                    id=str(uuid.uuid4()),
                    organization_id=organization_id,
                    branch_id=mov_branch_id,
                    batch_id=mov_batch_id,
                    storage_location_id=loc_id,
                    quantity=0,
                    reserved_quantity=0,
                    status=InventoryStatus.AVAILABLE.value,
                )
                db.add(inv)
                db.flush()

            qty_before = inv.quantity
            qty_after = qty_before + qty_change
            inv.quantity = qty_after
            if qty_after <= 0:
                inv.status = InventoryStatus.DEPLETED.value
            elif inv.status == InventoryStatus.DEPLETED.value and qty_after > 0:
                inv.status = InventoryStatus.AVAILABLE.value
            db.flush()

            dev_id = str(payload["device_id"]) if payload.get("device_id") else None
            if dev_id and not db.query(Device).filter_by(id=dev_id).first():
                dev_id = None

            mov = InventoryMovement(
                id=entity_id,
                organization_id=organization_id,
                branch_id=mov_branch_id,
                batch_id=mov_batch_id,
                storage_location_id=loc_id,
                movement_type=payload["movement_type"],
                quantity_change=qty_change,
                quantity_before=qty_before,
                quantity_after=qty_after,
                reference_type=payload.get("reference_type", "sync"),
                reference_id=str(payload.get("reference_id") or entity_id),
                user_id=str(payload.get("user_id") or "00000000-0000-0000-0000-000000000000"),
                device_id=dev_id,
                notes=payload.get("notes", ""),
                local_timestamp=payload.get("local_timestamp") or datetime.now(timezone.utc).isoformat(),
                server_timestamp=payload.get("server_timestamp") or datetime.now(timezone.utc).isoformat(),
                is_offline=bool(payload.get("is_offline", False)),
            )
            db.add(mov)
            db.flush()

            # Update Batch status if depleted/expired
            batch = db.query(Batch).filter_by(id=mov_batch_id).first()
            if batch and batch.status != BatchStatus.RECALLED.value:
                total_qty = (
                    db.query(func.sum(BranchInventory.quantity))
                    .filter(BranchInventory.batch_id == mov_batch_id)
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

    def download_updates(
        self,
        organization_id: str,
        branch_id: str,
        device_id: str,
        limit: int = 100,
    ) -> dict:
        """
        Incrementally downloads SyncDelivery rows from `/api/v1/sync/download/`,
        applies them locally with device-level echo suppression (`source_device_id != device_id`),
        processes disabled user lockouts and piggybacked license status, and advances
        `SyncCursor.last_server_sequence`.
        """
        with self.db_manager.get_session() as db:
            cursor = db.query(SyncCursor).filter_by(device_id=device_id).first()
            if not cursor:
                cursor = SyncCursor(
                    device_id=device_id,
                    last_server_sequence=0,
                    needs_full_resync=False,
                )
                db.add(cursor)
                db.flush()
            last_seq = cursor.last_server_sequence or 0

        applied_count = 0
        skipped_echo_count = 0
        has_more = True
        needs_full_resync = False

        while has_more:
            response = self.api_client.get(
                "/api/v1/sync/download/",
                params={
                    "branch_id": branch_id,
                    "device_id": device_id,
                    "last_sequence": last_seq,
                    "limit": limit,
                },
            )
            needs_full_resync = bool(response.get("needs_full_resync", False))
            deliveries = response.get("deliveries", [])
            new_seq = int(response.get("last_sequence", last_seq))
            has_more = bool(response.get("has_more", False))
            disabled_user_ids = response.get("disabled_user_ids", [])
            license_status = response.get("license_status")

            with self.db_manager.get_session() as db:
                cursor = db.query(SyncCursor).filter_by(device_id=device_id).first()
                if needs_full_resync:
                    cursor.needs_full_resync = True
                    db.flush()
                    break

                # 1. Process disabled user lockouts immediately
                for disabled_uid in disabled_user_ids:
                    u = db.query(User).filter_by(id=str(disabled_uid)).first()
                    if u and u.is_active:
                        u.is_active = False
                    cred = db.query(OfflineCredential).filter_by(user_id=str(disabled_uid)).first()
                    if cred and cred.is_active:
                        cred.is_active = False

                # 2. Piggybacked license_status update
                if license_status:
                    org = db.query(Organization).filter_by(id=organization_id).first()
                    if org:
                        try:
                            settings_dict = json.loads(org.settings or "{}")
                        except Exception:
                            settings_dict = {}
                        settings_dict["license_status"] = license_status
                        org.settings = json.dumps(settings_dict)

                    lic_state = db.query(LicenseState).filter_by(organization_id=organization_id).first()
                    entitlements = license_status.get("entitlements", {})
                    entitlements_str = json.dumps(entitlements) if isinstance(entitlements, dict) else str(entitlements)
                    now_iso = datetime.now(timezone.utc).isoformat()
                    if not lic_state:
                        lic_state = LicenseState(
                            organization_id=organization_id,
                            status=license_status.get("status", "ACTIVE"),
                            plan=license_status.get("plan", "professional"),
                            current_period_end=license_status.get("current_period_end"),
                            grace_period_days=int(license_status.get("grace_period_days", 14)),
                            entitlements=entitlements_str,
                            last_checked_at=now_iso,
                            updated_at=now_iso,
                        )
                        db.add(lic_state)
                    else:
                        lic_state.status = license_status.get("status", lic_state.status)
                        lic_state.plan = license_status.get("plan", lic_state.plan)
                        if license_status.get("current_period_end"):
                            lic_state.current_period_end = license_status["current_period_end"]
                        if "grace_period_days" in license_status:
                            lic_state.grace_period_days = int(license_status["grace_period_days"])
                        lic_state.entitlements = entitlements_str
                        lic_state.last_checked_at = now_iso
                        lic_state.updated_at = now_iso

                    if "license_status" in CUSTOM_DOWNLOAD_HANDLERS:
                        CUSTOM_DOWNLOAD_HANDLERS["license_status"](
                            db, organization_id, organization_id, "UPDATE", license_status, {}
                        )

                # 3. Apply deliveries in sequence order with client-side echo suppression guard
                for d in deliveries:
                    if str(d.get("source_device_id") or "") == str(device_id):
                        skipped_echo_count += 1
                        continue
                    self._apply_downloaded_delivery(db, organization_id, d)
                    applied_count += 1

                cursor.last_server_sequence = new_seq
                cursor.last_sync_at = datetime.now(timezone.utc).isoformat()
                db.flush()

            last_seq = new_seq
            if not deliveries:
                break

        return {
            "applied": applied_count,
            "skipped_echo": skipped_echo_count,
            "last_sequence": last_seq,
            "needs_full_resync": needs_full_resync,
        }

    def sync_once(self, organization_id: str, branch_id: str, device_id: str) -> dict:
        """Performs one full upload + download synchronization cycle."""
        upload_stats = self.upload_pending_events(branch_id=branch_id, device_id=device_id)
        download_stats = self.download_updates(
            organization_id=organization_id,
            branch_id=branch_id,
            device_id=device_id,
        )
        return {
            "upload": upload_stats,
            "download": download_stats,
        }
