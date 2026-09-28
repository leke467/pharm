from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from desktop.app.db.models import (
    AuditEvent,
    SyncEvent,
    Branch,
    User,
    Product,
    Batch,
    Price,
    PriceHistory,
)
from desktop.app.services.base_service import BaseService
from desktop.app.services.pricing_service import build_attribution_maps, resolve_price_attribution
from shared.enums import SyncEventStatus, AuditAction


ACTION_LABELS = {
    "PRICE_CHANGED": ("💰 Price Updated", "Price Changes"),
    "PRODUCT_CREATED": ("💊 Product Created", "Products & Catalog"),
    "PRODUCT_UPDATED": ("✏️ Product Updated", "Products & Catalog"),
    "BATCH_CREATED": ("📦 Batch Added", "Inventory & Batches"),
    "STOCK_RECEIVED": ("📥 Stock Received", "Inventory & Batches"),
    "STOCK_ADJUSTED": ("📊 Stock Adjusted", "Inventory & Batches"),
    "SALE_CREATED": ("💳 Sale Completed", "Sales & Returns"),
    "SALE_RETURNED": ("↩️ Sale Returned", "Sales & Returns"),
    "RETURN_PROCESSED": ("↩️ Sale Returned", "Sales & Returns"),
    "PURCHASE_ORDER_CREATED": ("📋 Purchase Order Created", "Purchases & Transfers"),
    "PURCHASE_ORDER_APPROVED": ("✅ Purchase Order Approved", "Purchases & Transfers"),
    "PURCHASE_ORDER_RECEIVED": ("📥 Purchase Order Received", "Purchases & Transfers"),
    "STOCK_COUNT_CREATED": ("🔢 Stock Count Started", "Inventory & Batches"),
    "STOCK_COUNT_COMPLETED": ("✅ Stock Count Approved", "Inventory & Batches"),
    "STOCK_TRANSFER_CREATED": ("🔄 Stock Transfer Dispatched", "Purchases & Transfers"),
    "STOCK_TRANSFER_COMPLETED": ("✅ Stock Transfer Received", "Purchases & Transfers"),
    "EXPENSE_CREATED": ("💵 Expense Logged", "Purchases & Transfers"),
    "EXPENSE_APPROVED": ("✅ Expense Approved", "Purchases & Transfers"),
    "USER_CREATED": ("👤 Staff Account Created", "Users & Settings"),
    "USER_UPDATED": ("👤 Staff Account Updated", "Users & Settings"),
    "ROLE_ASSIGNED": ("🛡️ Role Assigned", "Users & Settings"),
    "SETTINGS_CHANGED": ("⚙️ Settings Updated", "Users & Settings"),
    "LOGIN": ("🔑 User Logged In", "Users & Settings"),
    "LOGOUT": ("🚪 User Logged Out", "Users & Settings"),
}


def _safe_json(val) -> dict:
    if not val:
        return {}
    if isinstance(val, dict):
        return val
    try:
        parsed = json.loads(val)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _fmt_money(val) -> str | None:
    if val is None or val == "":
        return None
    try:
        return f"₦{Decimal(str(val)):,.2f}"
    except Exception:
        return str(val)


class AuditService(BaseService):
    """
    Offline Audit & Operational Activity Log Service (Architecture Plan §6, §13).
    Provides both:
      1. Technical Security & Compliance Audit Trail (`list_audit_events`)
      2. Human-Readable Operational Activity Logs (`list_activity_logs`) with full Branch & Account attribution.
    """

    def list_branches(self, organization_id: str) -> list[dict]:
        with self.transaction() as db:
            branches = (
                db.query(Branch)
                .filter_by(organization_id=organization_id, is_active=True)
                .order_by(Branch.name.asc())
                .all()
            )
            return [{"id": b.id, "name": b.name, "code": b.code} for b in branches]

    def _build_lookup_context(self, db, organization_id: str) -> dict:
        attr_maps = build_attribution_maps(db, organization_id)
        products = {
            p.id: p
            for p in db.query(Product).filter_by(organization_id=organization_id).all()
        }
        batches = {
            b.id: b
            for b in db.query(Batch).filter_by(organization_id=organization_id).all()
        }
        ph_by_price_id = {}
        for ph in (
            db.query(PriceHistory)
            .filter_by(organization_id=organization_id)
            .order_by(PriceHistory.version.desc(), PriceHistory.created_at.desc())
            .all()
        ):
            if ph.price_id not in ph_by_price_id:
                ph_by_price_id[ph.price_id] = ph

        return {
            "attr_maps": attr_maps,
            "products": products,
            "batches": batches,
            "ph_by_price_id": ph_by_price_id,
        }

    def _enrich_audit_event(self, e: AuditEvent, ctx: dict) -> dict:
        attr_maps = ctx["attr_maps"]
        branch_map = attr_maps["branch_map"]
        user_map = attr_maps["user_map"]
        products = ctx["products"]
        batches = ctx["batches"]
        ph_by_price_id = ctx["ph_by_price_id"]

        before_dict = _safe_json(e.data_before)
        after_dict = _safe_json(e.data_after)

        action_str = str(e.action or "")
        entity_type_str = str(e.entity_type or "")

        # Resolve Branch & Account
        if entity_type_str == "price" or action_str == AuditAction.PRICE_CHANGED.value:
            ph = ph_by_price_id.get(e.entity_id)
            branch_name, account_name = resolve_price_attribution(
                attr_maps,
                price_id=e.entity_id,
                branch_id=(ph.branch_id if ph else None) or e.branch_id,
                changed_by_id=(ph.changed_by_id if ph else None) or e.user_id,
                change_reason=e.reason or (ph.change_reason if ph else None),
            )
        else:
            branch_name = (
                after_dict.get("source_branch_name")
                or branch_map.get(e.branch_id)
                or branch_map.get(str(after_dict.get("branch_id") or ""))
                or attr_maps["default_branch_label"]
            )
            account_name = (
                after_dict.get("changed_by_name")
                or user_map.get(e.user_id)
                or user_map.get(str(after_dict.get("user_id") or after_dict.get("created_by_id") or ""))
                or attr_maps["default_user_label"]
            )

        label_tuple = ACTION_LABELS.get(action_str)
        if label_tuple:
            activity_label, category = label_tuple
        else:
            pretty = action_str.replace("_", " ").title() if action_str else "System Activity"
            activity_label = f"🔹 {pretty}"
            category = "Users & Settings"

        # Build human-readable summary & reason
        summary = ""
        reason_display = e.reason or ""

        if entity_type_str == "price" or action_str == AuditAction.PRICE_CHANGED.value:
            ph = ph_by_price_id.get(e.entity_id)
            prod_id = (
                after_dict.get("product_id")
                or (ph.product_id if ph else None)
                or (attr_maps["price_obj_map"].get(e.entity_id).product_id if e.entity_id in attr_maps["price_obj_map"] else None)
            )
            prod = products.get(prod_id) if prod_id else None
            prod_name = after_dict.get("product_name") or (prod.name if prod else "Product")
            prod_sku = after_dict.get("product_sku") or (prod.sku if prod else "")
            sku_part = f" ({prod_sku})" if prod_sku else ""

            old_p = (
                before_dict.get("selling_price")
                or before_dict.get("price")
                or after_dict.get("old_price")
                or (ph.old_price if ph else None)
            )
            new_p = (
                after_dict.get("selling_price")
                or after_dict.get("new_price")
                or after_dict.get("price")
                or (ph.new_price if ph else None)
            )
            old_fmt = _fmt_money(old_p)
            new_fmt = _fmt_money(new_p) or "₦0.00"
            if old_fmt:
                summary = f"{prod_name}{sku_part}: {old_fmt} → {new_fmt}"
            else:
                summary = f"{prod_name}{sku_part}: Initial Price set to {new_fmt}"

            if not reason_display and ph and ph.change_reason:
                reason_display = ph.change_reason
            if not reason_display:
                reason_display = f"Price updated by {account_name} at {branch_name}"

        elif entity_type_str == "product":
            prod = products.get(e.entity_id)
            p_name = after_dict.get("name") or (prod.name if prod else "Product")
            p_sku = after_dict.get("sku") or (prod.sku if prod else "")
            summary = f"{p_name} ({p_sku})" if p_sku else p_name
            if not reason_display:
                reason_display = "Catalog product created/updated"

        elif entity_type_str == "batch":
            batch = batches.get(e.entity_id)
            b_num = after_dict.get("batch_number") or (batch.batch_number if batch else str(e.entity_id)[:8])
            prod_id = after_dict.get("product_id") or (batch.product_id if batch else None)
            prod = products.get(prod_id) if prod_id else None
            p_name = prod.name if prod else "Product"
            cost_fmt = _fmt_money(after_dict.get("purchase_price") or (batch.purchase_price if batch else None))
            exp = after_dict.get("expiry_date") or (batch.expiry_date if batch else "")
            summary = f"{p_name} • Batch #{b_num}"
            if cost_fmt:
                summary += f" • Unit Cost: {cost_fmt}"
            if exp:
                summary += f" • Exp: {exp}"
            if not reason_display:
                reason_display = after_dict.get("notes") or "Inventory batch recorded"

        elif entity_type_str == "inventory_movement":
            b_id = after_dict.get("batch_id")
            batch = batches.get(b_id) if b_id else None
            prod = products.get(batch.product_id) if batch else None
            p_name = prod.name if prod else "Stock Item"
            b_num = f" (Batch #{batch.batch_number})" if batch else ""
            qty_chg = after_dict.get("quantity_change")
            mov_type = after_dict.get("movement_type", "")
            sign = f"+{qty_chg}" if isinstance(qty_chg, int) and qty_chg > 0 else str(qty_chg or 0)
            summary = f"{p_name}{b_num}: {sign} units ({mov_type})"
            if not reason_display:
                reason_display = after_dict.get("notes") or f"Stock movement ({mov_type})"

        elif entity_type_str == "sale":
            rcp = after_dict.get("receipt_number") or str(e.entity_id)[:8]
            tot = _fmt_money(after_dict.get("total_amount") or after_dict.get("total"))
            summary = f"Sale #{rcp}" + (f" • Total: {tot}" if tot else "")
            if not reason_display:
                reason_display = f"POS checkout ({after_dict.get('payment_method', 'CASH')})"

        else:
            name_val = (
                after_dict.get("name")
                or after_dict.get("username")
                or after_dict.get("title")
                or after_dict.get("reference_number")
                or f"{entity_type_str} ({str(e.entity_id)[:8]})"
            )
            summary = str(name_val)

        return {
            "id": e.id,
            "organization_id": e.organization_id,
            "branch_id": e.branch_id,
            "branch_name": branch_name,
            "user_id": e.user_id,
            "account_name": account_name,
            "device_id": e.device_id,
            "action": e.action,
            "activity_label": activity_label,
            "category": category,
            "summary": summary,
            "entity_type": e.entity_type,
            "entity_id": e.entity_id,
            "data_before": e.data_before,
            "data_after": e.data_after,
            "reason": reason_display if reason_display else e.reason,
            "correlation_id": e.correlation_id,
            "transaction_id": e.transaction_id,
            "local_timestamp": e.local_timestamp,
            "server_timestamp": e.server_timestamp,
            "is_offline": e.is_offline,
            "source": e.source,
            "sync_id": e.sync_id,
            "created_at": e.created_at,
        }

    def list_audit_events(
        self,
        organization_id: str,
        branch_id: str | None = None,
        entity_type: str | None = None,
        entity_id: str | None = None,
        action: str | None = None,
        user_id: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        with self.transaction() as db:
            ctx = self._build_lookup_context(db, organization_id)
            q = db.query(AuditEvent).filter_by(organization_id=organization_id)
            if branch_id:
                q = q.filter_by(branch_id=branch_id)
            if entity_type:
                q = q.filter(AuditEvent.entity_type.ilike(f"%{entity_type}%")) if "%" in entity_type else q.filter_by(entity_type=entity_type)
            if entity_id:
                q = q.filter_by(entity_id=entity_id)
            if action:
                q = q.filter_by(action=action)
            if user_id:
                q = q.filter_by(user_id=user_id)
            if start_date:
                q = q.filter(AuditEvent.created_at >= start_date)
            if end_date:
                q = q.filter(AuditEvent.created_at <= end_date)

            events = q.order_by(AuditEvent.created_at.desc()).offset(offset).limit(limit).all()
            return [self._enrich_audit_event(e, ctx) for e in events]

    def list_activity_logs(
        self,
        organization_id: str,
        branch_name_filter: str | None = None,
        category_filter: str | None = None,
        search_query: str | None = None,
        limit: int = 400,
    ) -> list[dict]:
        """
        Returns human-readable operational activity logs across the organization,
        combining AuditEvents with any PriceHistory records that did not yet have a local AuditEvent.
        """
        with self.transaction() as db:
            ctx = self._build_lookup_context(db, organization_id)
            attr_maps = ctx["attr_maps"]
            products = ctx["products"]

            raw_events = (
                db.query(AuditEvent)
                .filter_by(organization_id=organization_id)
                .order_by(AuditEvent.created_at.desc())
                .limit(limit)
                .all()
            )
            logs = [self._enrich_audit_event(e, ctx) for e in raw_events]
            covered_price_ids = {
                e.entity_id for e in raw_events if e.entity_type == "price" or e.action == AuditAction.PRICE_CHANGED.value
            }

            # Include any PriceHistory records that do not yet have a matching AuditEvent
            ph_rows = (
                db.query(PriceHistory)
                .filter(
                    PriceHistory.organization_id == organization_id,
                    ~PriceHistory.change_reason.like("Synced from organization price:%"),
                    ~PriceHistory.change_reason.like("Forced update from org default price:%"),
                )
                .order_by(PriceHistory.created_at.desc(), PriceHistory.version.desc())
                .limit(150)
                .all()
            )
            for ph in ph_rows:
                if ph.price_id in covered_price_ids:
                    continue
                covered_price_ids.add(ph.price_id)
                branch_name, account_name = resolve_price_attribution(
                    attr_maps,
                    price_id=ph.price_id,
                    branch_id=ph.branch_id,
                    changed_by_id=ph.changed_by_id,
                    change_reason=ph.change_reason,
                )
                prod = products.get(ph.product_id)
                prod_name = prod.name if prod else "Product"
                prod_sku = prod.sku if prod else ""
                sku_part = f" ({prod_sku})" if prod_sku else ""
                old_fmt = _fmt_money(ph.old_price)
                new_fmt = _fmt_money(ph.new_price) or "₦0.00"
                if old_fmt:
                    summary = f"{prod_name}{sku_part}: {old_fmt} → {new_fmt}"
                else:
                    summary = f"{prod_name}{sku_part}: Initial Price set to {new_fmt}"

                logs.append({
                    "id": ph.id,
                    "organization_id": ph.organization_id,
                    "branch_id": ph.branch_id,
                    "branch_name": branch_name,
                    "user_id": ph.changed_by_id,
                    "account_name": account_name,
                    "device_id": None,
                    "action": AuditAction.PRICE_CHANGED.value,
                    "activity_label": "💰 Price Updated",
                    "category": "Price Changes",
                    "summary": summary,
                    "entity_type": "price",
                    "entity_id": ph.price_id,
                    "data_before": json.dumps({"selling_price": str(ph.old_price)}) if ph.old_price is not None else None,
                    "data_after": json.dumps({
                        "product_id": ph.product_id,
                        "product_name": prod_name,
                        "product_sku": prod_sku,
                        "old_price": str(ph.old_price) if ph.old_price is not None else None,
                        "new_price": str(ph.new_price),
                        "source_branch_name": branch_name,
                        "changed_by_name": account_name,
                        "change_reason": ph.change_reason,
                    }),
                    "reason": ph.change_reason or f"Price updated by {account_name} at {branch_name}",
                    "correlation_id": ph.price_id,
                    "transaction_id": None,
                    "local_timestamp": ph.local_timestamp or ph.created_at,
                    "server_timestamp": ph.server_timestamp,
                    "is_offline": False,
                    "source": "SYNC",
                    "sync_id": None,
                    "created_at": ph.created_at or ph.local_timestamp,
                })

            # Sort combined logs newest first
            logs.sort(key=lambda item: str(item.get("created_at") or item.get("local_timestamp") or ""), reverse=True)

            # Apply filters
            if branch_name_filter and branch_name_filter != "All Branches":
                logs = [l for l in logs if (l.get("branch_name") or "").lower() == branch_name_filter.lower()]

            if category_filter and category_filter != "All Activities":
                logs = [l for l in logs if l.get("category") == category_filter]

            if search_query and search_query.strip():
                q_low = search_query.strip().lower()
                logs = [
                    l for l in logs
                    if q_low in (l.get("summary") or "").lower()
                    or q_low in (l.get("activity_label") or "").lower()
                    or q_low in (l.get("branch_name") or "").lower()
                    or q_low in (l.get("account_name") or "").lower()
                    or q_low in (l.get("reason") or "").lower()
                    or q_low in (l.get("action") or "").lower()
                ]

            return logs[:limit]

    def get_audit_event(self, event_id: str) -> dict | None:
        with self.transaction() as db:
            e = db.query(AuditEvent).filter_by(id=event_id).first()
            if not e:
                return None
            ctx = self._build_lookup_context(db, e.organization_id)
            return self._enrich_audit_event(e, ctx)

    def purge_synced_audit_events(self, organization_id: str, retention_days: int = 90) -> int:
        """
        Purges audit events older than retention_days (default 90 days) from SQLite
        ONLY AFTER confirming they are synced (SyncEvent status = SENT).
        Un-synced events (PENDING, SENDING, FAILED) are never purged.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        cutoff_iso = cutoff.isoformat()

        with self.transaction() as db:
            candidates = (
                db.query(AuditEvent)
                .filter(
                    AuditEvent.organization_id == organization_id,
                    AuditEvent.created_at < cutoff_iso,
                )
                .all()
            )

            if not candidates:
                return 0

            candidate_ids = [c.id for c in candidates]

            # Find corresponding SyncEvents
            sync_events = (
                db.query(SyncEvent)
                .filter(
                    SyncEvent.entity_type == "audit_event",
                    SyncEvent.entity_id.in_(candidate_ids),
                )
                .all()
            )
            sync_status_by_id = {se.entity_id: se.status for se in sync_events}

            # Only purge if SyncEvent exists AND status is SENT
            purged_ids = []
            for cid in candidate_ids:
                status = sync_status_by_id.get(cid)
                if status == SyncEventStatus.SENT.value:
                    purged_ids.append(cid)

            if purged_ids:
                db.query(AuditEvent).filter(AuditEvent.id.in_(purged_ids)).delete(
                    synchronize_session=False
                )
                db.query(SyncEvent).filter(
                    SyncEvent.entity_type == "audit_event",
                    SyncEvent.entity_id.in_(purged_ids),
                ).delete(synchronize_session=False)

            return len(purged_ids)
