import json
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from desktop.app.db.models import Price, PriceHistory, Product, Branch, User, SyncEvent, AuditEvent
from desktop.app.domain.exceptions import ValidationError
from desktop.app.services.base_service import BaseService
from desktop.app.sync.sync_engine import register_download_handler
from shared.enums import (
    PermissionCode,
    AuditAction,
    AuditSource,
    SyncOperation,
    SYNC_DEPENDENCY_LEVELS,
    SYNC_SCHEMA_VERSION,
)


def build_attribution_maps(db, organization_id: str) -> dict:
    """
    Preloads Branch, User, AuditEvent(price), and Price maps for fast, accurate
    attribution of which Branch and which Staff Account updated a product price.
    """
    branch_map: dict[str, str] = {}
    default_branch_label = "Main Branch (HQ)"
    for b in db.query(Branch).filter_by(organization_id=organization_id).all():
        branch_map[b.id] = b.name
        if "hq" in b.name.lower() or "main" in b.name.lower():
            default_branch_label = b.name
    if default_branch_label == "Main Branch (HQ)" and branch_map:
        default_branch_label = next(iter(branch_map.values()))

    user_map: dict[str, str] = {}
    default_user_label = "Administrator"
    for u in db.query(User).filter_by(organization_id=organization_id).all():
        label = (
            f"{u.full_name} (@{u.username})"
            if u.full_name and u.full_name.strip().lower() != u.username.strip().lower()
            else f"@{u.username}"
        )
        user_map[u.id] = label
        if u.is_org_admin and default_user_label == "Administrator":
            default_user_label = label
    if default_user_label == "Administrator" and user_map:
        default_user_label = next(iter(user_map.values()))

    audit_map: dict[str, AuditEvent] = {}
    for ae in (
        db.query(AuditEvent)
        .filter_by(organization_id=organization_id, entity_type="price")
        .all()
    ):
        audit_map[ae.entity_id] = ae

    price_obj_map: dict[str, Price] = {}
    for p in db.query(Price).filter_by(organization_id=organization_id).all():
        price_obj_map[p.id] = p

    return {
        "branch_map": branch_map,
        "user_map": user_map,
        "audit_map": audit_map,
        "price_obj_map": price_obj_map,
        "default_branch_label": default_branch_label,
        "default_user_label": default_user_label,
    }


def resolve_price_attribution(
    maps: dict,
    price_id: str | None = None,
    branch_id: str | None = None,
    changed_by_id: str | None = None,
    change_reason: str | None = None,
) -> tuple[str, str]:
    """
    Returns (branch_name, account_name) for a price change, resolving from
    AuditEvent, PriceHistory, Price, or change_reason string.
    """
    branch_map = maps["branch_map"]
    user_map = maps["user_map"]
    audit_map = maps["audit_map"]
    price_obj_map = maps["price_obj_map"]

    ae = audit_map.get(price_id) if price_id else None
    ae_after = {}
    if ae and ae.data_after:
        try:
            ae_after = (
                json.loads(ae.data_after)
                if isinstance(ae.data_after, str)
                else (ae.data_after or {})
            )
        except Exception:
            ae_after = {}

    # 1. Resolve Branch Name
    resolved_branch = None
    if ae_after.get("source_branch_name"):
        resolved_branch = str(ae_after["source_branch_name"])
    elif ae and ae.branch_id and ae.branch_id in branch_map:
        resolved_branch = branch_map[ae.branch_id]
    elif ae_after.get("source_branch_id") and str(ae_after["source_branch_id"]) in branch_map:
        resolved_branch = branch_map[str(ae_after["source_branch_id"])]
    elif branch_id and branch_id in branch_map:
        resolved_branch = branch_map[branch_id]
    elif change_reason:
        reason_lower = change_reason.lower()
        for b_name in branch_map.values():
            if b_name and b_name.lower() in reason_lower:
                resolved_branch = b_name
                break
    if not resolved_branch:
        resolved_branch = maps["default_branch_label"]

    # 2. Resolve Account Name
    resolved_account = None
    if ae_after.get("changed_by_name"):
        resolved_account = str(ae_after["changed_by_name"])
    elif changed_by_id and changed_by_id in user_map:
        resolved_account = user_map[changed_by_id]
    elif price_id and price_id in price_obj_map:
        p_obj = price_obj_map[price_id]
        if p_obj.created_by_id and p_obj.created_by_id in user_map:
            resolved_account = user_map[p_obj.created_by_id]
    if not resolved_account and ae and ae.user_id and ae.user_id in user_map:
        resolved_account = user_map[ae.user_id]
    if not resolved_account and ae_after.get("changed_by_id") and str(ae_after["changed_by_id"]) in user_map:
        resolved_account = user_map[str(ae_after["changed_by_id"])]
    if not resolved_account:
        resolved_account = maps["default_user_label"]

    return resolved_branch, resolved_account


class PricingService(BaseService):
    """
    Service managing product prices, versioning, history, and price resolution on the desktop
    (Architecture Plan §10 & §11).
    Resolution order: Branch-specific override (is_current=True) -> Org-wide default (is_current=True).
    """

    def set_price(
        self,
        user_session,
        product_id: str,
        selling_price: Decimal | float | str,
        branch_id: str | None = None,
        currency: str = "NGN",
        force_all_branches: bool = False,
        change_reason: str = "",
    ) -> Price:
        if not (
            user_session.has_permission(PermissionCode.PRICES_MANAGE.value)
            or user_session.has_permission(PermissionCode.PRODUCTS_EDIT.value)
            or user_session.has_permission(PermissionCode.PRODUCTS_CREATE.value)
            or user_session.has_permission(PermissionCode.BATCHES_MANAGE.value)
        ):
            self.require_permission(user_session, PermissionCode.PRICES_MANAGE.value)
        price_val = Decimal(str(selling_price))
        if price_val < 0:
            raise ValidationError("Selling price cannot be negative.")

        with self.transaction() as db:
            product = (
                db.query(Product)
                .filter_by(id=product_id, organization_id=user_session.organization_id)
                .first()
            )
            if not product:
                raise ValidationError("Product not found in your organization.")

            if branch_id:
                branch = (
                    db.query(Branch)
                    .filter_by(id=branch_id, organization_id=user_session.organization_id)
                    .first()
                )
                if not branch:
                    raise ValidationError("Branch not found in your organization.")

            now_iso = datetime.now(timezone.utc).isoformat()
            now_local = datetime.now().astimezone().isoformat()
            previous = (
                db.query(Price)
                .filter_by(
                    organization_id=user_session.organization_id,
                    product_id=product_id,
                    branch_id=branch_id,
                    is_current=True,
                )
                .first()
            )
            # If the exact same price is already active and no branch overrides need retiring, return it directly
            if previous and Decimal(str(previous.selling_price)) == price_val:
                if force_all_branches:
                    active_overrides = (
                        db.query(Price)
                        .filter(
                            Price.organization_id == user_session.organization_id,
                            Price.product_id == product_id,
                            Price.id != previous.id,
                            Price.is_current.is_(True),
                        )
                        .count()
                    )
                    if active_overrides == 0:
                        return previous
                else:
                    return previous

            next_version = 1
            before_snapshot = None
            old_price_val = None
            if previous:
                next_version = (previous.version or 1) + 1
                old_price_val = previous.selling_price
                before_snapshot = {
                    "id": previous.id,
                    "selling_price": str(previous.selling_price),
                    "version": previous.version,
                }
                previous.is_current = False
                previous.effective_to = now_iso
                db.flush()

            creator_exists = (
                db.query(User).filter_by(id=user_session.user_id).first() is not None
            )
            new_price = Price(
                id=str(uuid.uuid4()),
                organization_id=user_session.organization_id,
                product_id=product_id,
                branch_id=branch_id,
                selling_price=price_val,
                currency=currency,
                is_current=True,
                version=next_version,
                effective_from=now_iso,
                created_by_id=user_session.user_id if creator_exists else None,
                sync_status="PENDING",
            )
            db.add(new_price)
            db.flush()

            # Force all branches: retire any other active prices across the organization
            if force_all_branches:
                other_active_prices = (
                    db.query(Price)
                    .filter(
                        Price.organization_id == user_session.organization_id,
                        Price.product_id == product_id,
                        Price.id != new_price.id,
                        Price.is_current.is_(True),
                    )
                    .all()
                )
                for bo in other_active_prices:
                    bo_old = bo.selling_price
                    if old_price_val is None:
                        old_price_val = bo_old
                    bo.is_current = False
                    bo.effective_to = now_iso
                    # Record history for retired branch override
                    db.add(
                        PriceHistory(
                            id=str(uuid.uuid4()),
                            organization_id=user_session.organization_id,
                            price_id=bo.id,
                            product_id=product_id,
                            branch_id=bo.branch_id,
                            old_price=bo_old,
                            new_price=price_val,
                            changed_by_id=user_session.user_id if creator_exists else None,
                            change_reason=f"Synced from organization price: {change_reason}".strip(),
                            version=(bo.version or 1) + 1,
                            local_timestamp=now_local,
                            server_timestamp=None,
                            sync_status="PENDING",
                            created_at=now_iso,
                        )
                    )

            # Record immutable PriceHistory
            hist_id = str(uuid.uuid4())
            price_hist = PriceHistory(
                id=hist_id,
                organization_id=user_session.organization_id,
                price_id=new_price.id,
                product_id=product_id,
                branch_id=branch_id,
                old_price=old_price_val,
                new_price=price_val,
                changed_by_id=user_session.user_id if creator_exists else None,
                change_reason=change_reason or "",
                version=next_version,
                local_timestamp=now_local,
                server_timestamp=None,
                sync_status="PENDING",
                created_at=now_iso,
            )
            db.add(price_hist)

            source_branch_name = getattr(user_session, "branch_name", None) or ""
            if not source_branch_name and getattr(user_session, "branch_id", None):
                src_b = db.query(Branch).filter_by(id=user_session.branch_id).first()
                if src_b:
                    source_branch_name = src_b.name

            full_n = getattr(user_session, "full_name", None) or ""
            user_n = getattr(user_session, "username", None) or "staff"
            changed_by_name = (
                f"{full_n} (@{user_n})"
                if full_n and full_n.strip().lower() != user_n.strip().lower()
                else f"@{user_n}"
            )

            payload = {
                "id": new_price.id,
                "organization_id": new_price.organization_id,
                "product_id": new_price.product_id,
                "product_name": product.name,
                "product_sku": product.sku,
                "branch_id": new_price.branch_id,
                "selling_price": str(new_price.selling_price),
                "old_price": str(old_price_val) if old_price_val is not None else None,
                "new_price": str(price_val),
                "currency": new_price.currency,
                "is_current": True,
                "force_all_branches": bool(force_all_branches),
                "version": new_price.version,
                "effective_from": new_price.effective_from,
                "change_reason": change_reason or "",
                "created_by_id": user_session.user_id,
                "changed_by_id": user_session.user_id,
                "changed_by_name": changed_by_name,
                "source_branch_id": getattr(user_session, "branch_id", None),
                "source_branch_name": source_branch_name,
            }
            audit_reason = change_reason or (
                f"Updated {product.name} ({product.sku}) price from ₦{Decimal(str(old_price_val)):,.2f} to ₦{price_val:,.2f}"
                if old_price_val is not None
                else f"Set initial selling price for {product.name} ({product.sku}) to ₦{price_val:,.2f}"
            )
            self.record_audit_and_sync(
                db_session=db,
                user_session=user_session,
                action=AuditAction.PRICE_CHANGED.value,
                entity_type="price",
                entity_id=new_price.id,
                operation=SyncOperation.CREATE.value,
                payload=payload,
                data_before=before_snapshot,
                data_after=payload,
                reason=audit_reason,
            )

            # Queue sync for price history
            db.add(
                SyncEvent(
                    id=str(uuid.uuid4()),
                    branch_id=user_session.branch_id,
                    device_id=user_session.device_id,
                    entity_type="price_history",
                    entity_id=hist_id,
                    operation=SyncOperation.CREATE.value,
                    payload=json.dumps({
                        "id": hist_id,
                        "price_id": new_price.id,
                        "product_id": product_id,
                        "product_name": product.name,
                        "product_sku": product.sku,
                        "branch_id": branch_id,
                        "old_price": str(old_price_val) if old_price_val is not None else None,
                        "new_price": str(price_val),
                        "changed_by_id": user_session.user_id,
                        "changed_by_name": changed_by_name,
                        "source_branch_id": getattr(user_session, "branch_id", None),
                        "source_branch_name": source_branch_name,
                        "change_reason": change_reason or "",
                        "version": next_version,
                        "local_timestamp": now_local,
                    }),
                    correlation_id=new_price.id,
                    dependency_level=SYNC_DEPENDENCY_LEVELS.get("price_history", 4),
                    schema_version=SYNC_SCHEMA_VERSION,
                    local_created_at=now_local,
                )
            )

            db.flush()
            return new_price

    def resolve_price(
        self,
        organization_id: str,
        product_id: str,
        branch_id: str | None = None,
    ) -> Price | None:
        """
        Resolve active selling price for a product:
        1. Branch-specific override (`branch_id = branch_id AND is_current = True`)
        2. Organization-wide default (`branch_id IS NULL AND is_current = True`)
        """
        with self.transaction() as db:
            if branch_id:
                branch_price = (
                    db.query(Price)
                    .filter_by(
                        organization_id=organization_id,
                        product_id=product_id,
                        branch_id=branch_id,
                        is_current=True,
                    )
                    .first()
                )
                if branch_price:
                    return branch_price

            return (
                db.query(Price)
                .filter_by(
                    organization_id=organization_id,
                    product_id=product_id,
                    branch_id=None,
                    is_current=True,
                )
                .first()
            )

    def resolve_prices_bulk(
        self,
        organization_id: str,
        product_ids: list[str],
        branch_id: str | None = None,
    ) -> dict[str, Price]:
        """
        Batch-resolves active selling prices for a list of products in a single SQL query.
        Returns dict mapping product_id -> Price object.
        """
        if not product_ids:
            return {}
        with self.transaction() as db:
            q = db.query(Price).filter(
                Price.organization_id == organization_id,
                Price.product_id.in_(product_ids),
                Price.is_current == True,
            )
            prices = q.all()
            result = {}
            for p in prices:
                if p.product_id not in result:
                    result[p.product_id] = p
                elif branch_id and p.branch_id == branch_id:
                    result[p.product_id] = p
            return result

    def get_price_history(
        self,
        product_id: str,
        branch_id: str | None = None,
    ) -> list[dict]:
        with self.transaction() as db:
            q = db.query(PriceHistory).filter_by(product_id=product_id)
            if branch_id is not None:
                q = q.filter_by(branch_id=branch_id)
            histories = q.order_by(PriceHistory.version.desc(), PriceHistory.created_at.desc()).all()
            res = []
            for h in histories:
                res.append({
                    "id": h.id,
                    "price_id": h.price_id,
                    "product_id": h.product_id,
                    "branch_id": h.branch_id,
                    "old_price": h.old_price,
                    "new_price": h.new_price,
                    "changed_by_id": h.changed_by_id,
                    "change_reason": h.change_reason,
                    "version": h.version,
                    "local_timestamp": h.local_timestamp,
                    "server_timestamp": h.server_timestamp,
                    "created_at": h.created_at,
                })
            return res

    def get_recent_price_changes(
        self,
        organization_id: str,
        limit: int = 20,
    ) -> list[dict]:
        """
        Returns recent price updates across all branches in the organization joined with Product details,
        used for multi-branch price change notifications and the Price History modal.
        """
        with self.transaction() as db:
            attr_maps = build_attribution_maps(db, organization_id)
            rows = (
                db.query(
                    PriceHistory.id,
                    PriceHistory.price_id,
                    PriceHistory.product_id,
                    Product.name.label("product_name"),
                    Product.sku.label("product_sku"),
                    PriceHistory.branch_id,
                    PriceHistory.changed_by_id,
                    PriceHistory.old_price,
                    PriceHistory.new_price,
                    PriceHistory.change_reason,
                    PriceHistory.version,
                    PriceHistory.local_timestamp,
                    PriceHistory.created_at,
                )
                .join(Product, Product.id == PriceHistory.product_id)
                .filter(
                    PriceHistory.organization_id == organization_id,
                    ~PriceHistory.change_reason.like("Synced from organization price:%"),
                    ~PriceHistory.change_reason.like("Forced update from org default price:%"),
                )
                .order_by(PriceHistory.created_at.desc(), PriceHistory.version.desc())
                .limit(limit)
                .all()
            )
            results = []
            for r in rows:
                resolved_branch, resolved_account = resolve_price_attribution(
                    attr_maps,
                    price_id=r.price_id,
                    branch_id=r.branch_id,
                    changed_by_id=r.changed_by_id,
                    change_reason=r.change_reason,
                )
                results.append({
                    "id": r.id,
                    "price_id": r.price_id,
                    "product_id": r.product_id,
                    "product_name": r.product_name,
                    "product_sku": r.product_sku,
                    "branch_id": r.branch_id,
                    "branch_name": resolved_branch,
                    "account_name": resolved_account,
                    "old_price": Decimal(str(r.old_price)) if r.old_price is not None else None,
                    "new_price": Decimal(str(r.new_price)),
                    "change_reason": r.change_reason or "Standard price update",
                    "version": r.version,
                    "local_timestamp": r.local_timestamp or r.created_at,
                    "created_at": r.created_at,
                })
            return results

    def get_recently_updated_product_ids(
        self,
        organization_id: str,
        hours: int = 24,
    ) -> dict[str, dict]:
        """
        Returns a mapping of product_id -> price change info for products whose
        price update was created or received by this branch within the last `hours` hours (default 24h).
        """
        cutoff_iso = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        with self.transaction() as db:
            attr_maps = build_attribution_maps(db, organization_id)
            rows = (
                db.query(PriceHistory)
                .filter(
                    PriceHistory.organization_id == organization_id,
                    PriceHistory.created_at >= cutoff_iso,
                    ~PriceHistory.change_reason.like("Synced from organization price:%"),
                    ~PriceHistory.change_reason.like("Forced update from org default price:%"),
                )
                .order_by(PriceHistory.created_at.desc(), PriceHistory.version.desc())
                .all()
            )
            recent_map: dict[str, dict] = {}
            for r in rows:
                if r.product_id not in recent_map:
                    resolved_branch, resolved_account = resolve_price_attribution(
                        attr_maps,
                        price_id=r.price_id,
                        branch_id=r.branch_id,
                        changed_by_id=r.changed_by_id,
                        change_reason=r.change_reason,
                    )
                    recent_map[r.product_id] = {
                        "old_price": Decimal(str(r.old_price)) if r.old_price is not None else None,
                        "new_price": Decimal(str(r.new_price)),
                        "change_reason": r.change_reason or "Price updated",
                        "received_at": r.created_at,
                        "branch_name": resolved_branch,
                        "account_name": resolved_account,
                    }

            # Fallback for Price rows updated/synced directly within the last 24h
            updated_prices = (
                db.query(Price)
                .filter(
                    Price.organization_id == organization_id,
                    Price.is_current.is_(True),
                    Price.version > 1,
                    Price.updated_at >= cutoff_iso,
                )
                .all()
            )
            for p in updated_prices:
                if p.product_id not in recent_map:
                    resolved_branch, resolved_account = resolve_price_attribution(
                        attr_maps,
                        price_id=p.id,
                        branch_id=p.branch_id,
                        changed_by_id=p.created_by_id,
                        change_reason="Recent price update",
                    )
                    recent_map[p.product_id] = {
                        "old_price": None,
                        "new_price": Decimal(str(p.selling_price)),
                        "change_reason": "Recent price update",
                        "received_at": p.updated_at,
                        "branch_name": resolved_branch,
                        "account_name": resolved_account,
                    }

            # If any entry has old_price=None, check the most recent retired Price record for that product
            missing_old_pids = [pid for pid, info in recent_map.items() if info.get("old_price") is None]
            if missing_old_pids:
                retired_prices = (
                    db.query(Price)
                    .filter(
                        Price.organization_id == organization_id,
                        Price.product_id.in_(missing_old_pids),
                        Price.is_current.is_(False),
                    )
                    .order_by(Price.version.desc(), Price.updated_at.desc())
                    .all()
                )
                for rp in retired_prices:
                    if recent_map[rp.product_id].get("old_price") is None:
                        recent_map[rp.product_id]["old_price"] = Decimal(str(rp.selling_price))

            return recent_map


# =============================================================================
# Download Handlers
# =============================================================================

def _download_price(db, organization_id, entity_id, operation, payload, delivery):
    """
    Downloads Price updates with version-based conflict resolution:
    If incoming price is current, retire local existing current prices for that (product, branch).
    If incoming price is org-wide (branch_id is None) or force_all_branches is true, retire all local active prices for that product.
    Also records local PriceHistory and AuditEvent if not already present so receiving branches have complete attribution & logs.
    """
    prod_id = str(payload["product_id"])
    br_id = str(payload["branch_id"]) if payload.get("branch_id") else None
    incoming_version = int(payload.get("version", 1))
    is_curr = bool(payload.get("is_current", True))
    force_all = bool(payload.get("force_all_branches", br_id is None))
    new_price_dec = Decimal(str(payload["selling_price"]))

    # Capture previous local active price before retiring it
    prev_local_price = (
        db.query(Price)
        .filter(
            Price.organization_id == organization_id,
            Price.product_id == prod_id,
            Price.id != entity_id,
            Price.is_current == True,
        )
        .order_by(Price.version.desc())
        .first()
    )
    old_price_val = None
    if payload.get("old_price") is not None:
        try:
            old_price_val = Decimal(str(payload["old_price"]))
        except Exception:
            old_price_val = None
    elif prev_local_price is not None:
        old_price_val = Decimal(str(prev_local_price.selling_price))

    now_iso = datetime.now(timezone.utc).isoformat()
    if is_curr:
        if br_id is None or force_all:
            db.query(Price).filter(
                Price.product_id == prod_id,
                Price.id != entity_id,
                Price.is_current == True,
            ).update({"is_current": False, "effective_to": now_iso})
        else:
            db.query(Price).filter(
                Price.product_id == prod_id,
                Price.branch_id == br_id,
                Price.id != entity_id,
                Price.is_current == True,
            ).update({"is_current": False, "effective_to": now_iso})

    created_by_id = str(payload.get("created_by_id") or payload.get("changed_by_id") or "") or None
    if created_by_id and not db.query(User).filter_by(id=created_by_id).first():
        created_by_id = None

    price = db.query(Price).filter_by(id=entity_id).first()
    if not price:
        price = Price(
            id=entity_id,
            organization_id=organization_id,
            product_id=prod_id,
            branch_id=br_id,
            selling_price=new_price_dec,
            currency=payload.get("currency", "NGN"),
            is_current=is_curr,
            version=incoming_version,
            effective_from=payload.get("effective_from") or now_iso,
            effective_to=payload.get("effective_to"),
            created_by_id=created_by_id,
            sync_status="SYNCED",
        )
        db.add(price)
    else:
        if incoming_version >= (price.version or 0):
            price.selling_price = new_price_dec
            price.is_current = is_curr
            price.version = incoming_version
            price.effective_to = payload.get("effective_to", price.effective_to)
            if created_by_id:
                price.created_by_id = created_by_id
            price.sync_status = "SYNCED"
    db.flush()

    # Ensure local PriceHistory exists for this synced price
    existing_ph = db.query(PriceHistory).filter_by(price_id=entity_id).first()
    if not existing_ph:
        db.add(
            PriceHistory(
                id=str(uuid.uuid4()),
                organization_id=organization_id,
                price_id=entity_id,
                product_id=prod_id,
                branch_id=br_id,
                old_price=old_price_val,
                new_price=new_price_dec,
                changed_by_id=created_by_id,
                change_reason=payload.get("change_reason") or "Synced price update",
                version=incoming_version,
                local_timestamp=payload.get("effective_from") or now_iso,
                server_timestamp=now_iso,
                sync_status="SYNCED",
                created_at=now_iso,
            )
        )

    # Ensure local AuditEvent exists so the price change appears in Activity Logs & Audit Trail on all branches
    existing_ae = (
        db.query(AuditEvent)
        .filter_by(organization_id=organization_id, entity_type="price", entity_id=entity_id)
        .first()
    )
    if not existing_ae:
        src_branch_id = (
            payload.get("source_branch_id")
            or (delivery.get("source_branch_id") if isinstance(delivery, dict) else None)
            or br_id
            or ""
        )
        src_user_id = str(payload.get("changed_by_id") or payload.get("created_by_id") or "")
        prod_obj = db.query(Product).filter_by(id=prod_id).first()
        prod_name = payload.get("product_name") or (prod_obj.name if prod_obj else "Product")
        prod_sku = payload.get("product_sku") or (prod_obj.sku if prod_obj else "")
        reason_str = payload.get("change_reason") or (
            f"Updated {prod_name} ({prod_sku}) price from ₦{old_price_val:,.2f} to ₦{new_price_dec:,.2f}"
            if old_price_val is not None
            else f"Updated {prod_name} ({prod_sku}) price to ₦{new_price_dec:,.2f}"
        )
        enriched_after = dict(payload)
        enriched_after.setdefault("product_name", prod_name)
        enriched_after.setdefault("product_sku", prod_sku)
        if old_price_val is not None:
            enriched_after.setdefault("old_price", str(old_price_val))
        enriched_after.setdefault("new_price", str(new_price_dec))
        db.add(
            AuditEvent(
                id=str(uuid.uuid4()),
                organization_id=organization_id,
                branch_id=str(src_branch_id),
                user_id=src_user_id,
                device_id=str(delivery.get("source_device_id") or "") if isinstance(delivery, dict) else None,
                action=AuditAction.PRICE_CHANGED.value,
                entity_type="price",
                entity_id=entity_id,
                data_before=json.dumps({"selling_price": str(old_price_val)}) if old_price_val is not None else None,
                data_after=json.dumps(enriched_after),
                reason=reason_str,
                local_timestamp=payload.get("effective_from") or now_iso,
                server_timestamp=now_iso,
                is_offline=False,
                source=AuditSource.SERVER_SYNC.value,
                created_at=now_iso,
            )
        )
    db.flush()


def _download_price_history(db, organization_id, entity_id, operation, payload, delivery):
    price_id = str(payload["price_id"])
    prod_id = str(payload["product_id"])
    br_id = str(payload["branch_id"]) if payload.get("branch_id") else None
    old_p = Decimal(str(payload["old_price"])) if payload.get("old_price") is not None else None
    new_p = Decimal(str(payload["new_price"]))
    changed_by_id = str(payload["changed_by_id"]) if payload.get("changed_by_id") else None
    if changed_by_id and not db.query(User).filter_by(id=changed_by_id).first():
        changed_by_id = None

    ph = db.query(PriceHistory).filter_by(id=entity_id).first()
    if not ph:
        synth_ph = db.query(PriceHistory).filter_by(price_id=price_id).first()
        if synth_ph:
            if old_p is None and synth_ph.old_price is not None:
                old_p = Decimal(str(synth_ph.old_price))
            db.delete(synth_ph)
            db.flush()

    now_iso = datetime.now(timezone.utc).isoformat()
    if not ph:
        ph = PriceHistory(
            id=entity_id,
            organization_id=organization_id,
            price_id=price_id,
            product_id=prod_id,
            branch_id=br_id,
            old_price=old_p,
            new_price=new_p,
            changed_by_id=changed_by_id,
            change_reason=payload.get("change_reason", ""),
            version=int(payload.get("version", 1)),
            local_timestamp=payload.get("local_timestamp") or now_iso,
            server_timestamp=payload.get("server_timestamp"),
            sync_status="SYNCED",
            created_at=now_iso,
        )
        db.add(ph)
    else:
        if old_p is not None and ph.old_price is None:
            ph.old_price = old_p
        if changed_by_id and not ph.changed_by_id:
            ph.changed_by_id = changed_by_id
        if payload.get("change_reason") and (not ph.change_reason or ph.change_reason == "Synced price update"):
            ph.change_reason = payload["change_reason"]

    # Also ensure local AuditEvent exists or is enriched with attribution metadata
    existing_ae = (
        db.query(AuditEvent)
        .filter_by(organization_id=organization_id, entity_type="price", entity_id=price_id)
        .first()
    )
    src_branch_id = (
        payload.get("source_branch_id")
        or (delivery.get("source_branch_id") if isinstance(delivery, dict) else None)
        or br_id
        or ""
    )
    src_user_id = str(payload.get("changed_by_id") or "")
    prod_obj = db.query(Product).filter_by(id=prod_id).first()
    prod_name = payload.get("product_name") or (prod_obj.name if prod_obj else "Product")
    prod_sku = payload.get("product_sku") or (prod_obj.sku if prod_obj else "")
    reason_str = payload.get("change_reason") or (
        f"Updated {prod_name} ({prod_sku}) price from ₦{old_p:,.2f} to ₦{new_p:,.2f}"
        if old_p is not None
        else f"Updated {prod_name} ({prod_sku}) price to ₦{new_p:,.2f}"
    )
    enriched_after = dict(payload)
    enriched_after.setdefault("product_name", prod_name)
    enriched_after.setdefault("product_sku", prod_sku)
    if not existing_ae:
        db.add(
            AuditEvent(
                id=str(uuid.uuid4()),
                organization_id=organization_id,
                branch_id=str(src_branch_id),
                user_id=src_user_id,
                device_id=str(delivery.get("source_device_id") or "") if isinstance(delivery, dict) else None,
                action=AuditAction.PRICE_CHANGED.value,
                entity_type="price",
                entity_id=price_id,
                data_before=json.dumps({"selling_price": str(old_p)}) if old_p is not None else None,
                data_after=json.dumps(enriched_after),
                reason=reason_str,
                local_timestamp=payload.get("local_timestamp") or now_iso,
                server_timestamp=now_iso,
                is_offline=False,
                source=AuditSource.SERVER_SYNC.value,
                created_at=now_iso,
            )
        )
    else:
        if src_branch_id and not existing_ae.branch_id:
            existing_ae.branch_id = str(src_branch_id)
        if src_user_id and not existing_ae.user_id:
            existing_ae.user_id = src_user_id
        if reason_str and not existing_ae.reason:
            existing_ae.reason = reason_str
        existing_ae.data_after = json.dumps(enriched_after)
    db.flush()


register_download_handler("price", _download_price)
register_download_handler("price_history", _download_price_history)
