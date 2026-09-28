import json
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from sqlalchemy import func
from desktop.app.db.models import (
    Supplier,
    Product,
    Batch,
    Price,
    Purchase,
    PurchaseItem,
    PurchasePayment,
    SyncEvent,
    User,
)
from desktop.app.domain.exceptions import ValidationError
from desktop.app.services.base_service import BaseService
from desktop.app.services.inventory_service import InventoryService
from desktop.app.sync.sync_engine import register_download_handler
from shared.enums import (
    AuditAction,
    BatchStatus,
    MovementType,
    PaymentStatus,
    PermissionCode,
    ReceivingStatus,
    SyncOperation,
    SYNC_DEPENDENCY_LEVELS,
    SYNC_SCHEMA_VERSION,
)


class PurchaseService(BaseService):
    """
    Offline-first Purchasing & Inventory Receiving Service (Architecture Plan §8).
    """

    def __init__(self, db_manager):
        super().__init__(db_manager)
        self.inventory_service = InventoryService(db_manager)

    def create_purchase(
        self,
        user_session,
        supplier_id: str,
        purchase_reference: str,
        purchase_date: str,
        items: list[dict],
        invoice_number: str | None = None,
        discount_amount: str | Decimal = "0.00",
        notes: str = "",
    ) -> Purchase:
        """
        Creates a Purchase order in `PENDING` / `UNPAID` status with `PurchaseItem` lines
        and emits correlated SyncEvents.
        """
        self.require_permission(user_session, PermissionCode.STOCK_RECEIVE.value)
        if not purchase_reference or not purchase_reference.strip():
            raise ValidationError("Purchase reference is required.")
        if not items:
            raise ValidationError("At least one purchase item is required.")

        corr_id = str(uuid.uuid4())
        now_local = datetime.now().astimezone().isoformat()
        now_utc = datetime.now(timezone.utc).isoformat()

        with self.transaction() as db:
            supplier = (
                db.query(Supplier)
                .filter_by(
                    id=supplier_id,
                    organization_id=user_session.organization_id,
                    is_active=True,
                )
                .first()
            )
            if not supplier:
                raise ValidationError("Active supplier not found.")

            dup = (
                db.query(Purchase)
                .filter_by(
                    organization_id=user_session.organization_id,
                    purchase_reference=purchase_reference.strip(),
                )
                .first()
            )
            if dup:
                raise ValidationError(
                    f"Purchase reference '{purchase_reference.strip()}' already exists."
                )

            subtotal = Decimal("0.00")
            prepared_lines = []
            for item_in in items:
                product = (
                    db.query(Product)
                    .filter_by(
                        id=str(item_in["product_id"]),
                        organization_id=user_session.organization_id,
                        is_active=True,
                    )
                    .first()
                )
                if not product:
                    raise ValidationError(f"Product {item_in['product_id']} not found.")
                qty = int(item_in["quantity_ordered"])
                if qty <= 0:
                    raise ValidationError("Ordered quantity must be positive.")
                p_price = Decimal(str(item_in["purchase_price"])).quantize(Decimal("0.01"))
                s_price = Decimal(str(item_in.get("selling_price", "0.00"))).quantize(
                    Decimal("0.01")
                )
                disc = Decimal(str(item_in.get("discount", "0.00"))).quantize(
                    Decimal("0.01")
                )
                line_tot = max(Decimal("0.00"), (p_price * Decimal(qty)) - disc).quantize(
                    Decimal("0.01")
                )
                subtotal += line_tot
                prepared_lines.append((product, qty, p_price, s_price, disc, line_tot))

            order_disc = Decimal(str(discount_amount)).quantize(Decimal("0.01"))
            total = max(Decimal("0.00"), subtotal - order_disc).quantize(Decimal("0.01"))

            purchase = Purchase(
                id=str(uuid.uuid4()),
                organization_id=user_session.organization_id,
                branch_id=user_session.branch_id,
                supplier_id=supplier.id,
                user_id=user_session.user_id,
                purchase_reference=purchase_reference.strip(),
                invoice_number=invoice_number,
                purchase_date=purchase_date[:10],
                subtotal=subtotal,
                discount_amount=order_disc,
                total=total,
                payment_status=PaymentStatus.UNPAID.value,
                receiving_status=ReceivingStatus.PENDING.value,
                notes=notes or "",
                created_at=now_utc,
                updated_at=now_utc,
            )
            db.add(purchase)
            db.flush()

            purchase_sync = SyncEvent(
                id=str(uuid.uuid4()),
                branch_id=user_session.branch_id,
                device_id=user_session.device_id,
                entity_type="purchase",
                entity_id=purchase.id,
                operation=SyncOperation.CREATE.value,
                payload=json.dumps({
                    "id": purchase.id,
                    "organization_id": purchase.organization_id,
                    "branch_id": purchase.branch_id,
                    "supplier_id": purchase.supplier_id,
                    "user_id": purchase.user_id,
                    "purchase_reference": purchase.purchase_reference,
                    "invoice_number": purchase.invoice_number,
                    "purchase_date": purchase.purchase_date,
                    "subtotal": str(purchase.subtotal),
                    "discount_amount": str(purchase.discount_amount),
                    "total": str(purchase.total),
                    "payment_status": purchase.payment_status,
                    "receiving_status": purchase.receiving_status,
                    "notes": purchase.notes,
                }),
                correlation_id=corr_id,
                dependency_level=SYNC_DEPENDENCY_LEVELS["purchase"],
                schema_version=SYNC_SCHEMA_VERSION,
                local_created_at=now_local,
                status="PENDING",
            )
            db.add(purchase_sync)

            for product, qty, p_price, s_price, disc, line_tot in prepared_lines:
                pi = PurchaseItem(
                    id=str(uuid.uuid4()),
                    purchase_id=purchase.id,
                    product_id=product.id,
                    batch_id=None,
                    quantity_ordered=qty,
                    quantity_received=0,
                    purchase_price=p_price,
                    selling_price=s_price,
                    discount=disc,
                    line_total=line_tot,
                    created_at=now_utc,
                    updated_at=now_utc,
                )
                db.add(pi)
                db.flush()

                pi_sync = SyncEvent(
                    id=str(uuid.uuid4()),
                    branch_id=user_session.branch_id,
                    device_id=user_session.device_id,
                    entity_type="purchase_item",
                    entity_id=pi.id,
                    operation=SyncOperation.CREATE.value,
                    payload=json.dumps({
                        "id": pi.id,
                        "purchase_id": purchase.id,
                        "product_id": pi.product_id,
                        "batch_id": None,
                        "quantity_ordered": pi.quantity_ordered,
                        "quantity_received": 0,
                        "purchase_price": str(pi.purchase_price),
                        "selling_price": str(pi.selling_price),
                        "discount": str(pi.discount),
                        "line_total": str(pi.line_total),
                    }),
                    correlation_id=corr_id,
                    dependency_level=SYNC_DEPENDENCY_LEVELS["purchase_item"],
                    schema_version=SYNC_SCHEMA_VERSION,
                    local_created_at=now_local,
                    status="PENDING",
                )
                db.add(pi_sync)

            db.expunge(purchase)
            return purchase

    def receive_purchase(
        self,
        user_session,
        purchase_id: str,
        items: list[dict],
        invoice_number: str | None = None,
    ) -> dict:
        """
        Receives stock for one or more PurchaseItem lines on a Purchase:
        - Validates `STOCK_RECEIVE` permission, non-expired `expiry_date`, and over-receive prevention.
        - Creates or updates `Batch` (`ACTIVE`) and emits `batch` SyncEvent.
        - Applies `STOCK_RECEIVED` InventoryMovement and updates `BranchInventory`.
        - Updates `PurchaseItem.quantity_received` and `PurchaseItem.batch_id` + SyncEvent.
        - Optionally updates current `Price` (`update_selling_price=True`).
        - Updates `Purchase.receiving_status` (`PARTIALLY_RECEIVED` or `RECEIVED`).
        - Records `AuditEvent(STOCK_RECEIVED)` + `purchase` UPDATE SyncEvent sharing `correlation_id`.
        """
        self.require_permission(user_session, PermissionCode.STOCK_RECEIVE.value)
        if not items:
            raise ValidationError("At least one item to receive is required.")

        corr_id = str(uuid.uuid4())
        today_iso = date.today().isoformat()
        now_local = datetime.now().astimezone().isoformat()
        now_utc = datetime.now(timezone.utc).isoformat()

        with self.transaction() as db:
            purchase = (
                db.query(Purchase)
                .filter_by(id=purchase_id, organization_id=user_session.organization_id)
                .first()
            )
            if not purchase:
                raise ValidationError("Purchase not found.")
            if purchase.receiving_status == ReceivingStatus.RECEIVED.value:
                raise ValidationError("Purchase is already fully received.")

            if invoice_number:
                purchase.invoice_number = invoice_number

            p_items_map = {
                pi.id: pi
                for pi in db.query(PurchaseItem).filter_by(purchase_id=purchase.id).all()
            }

            for rec_in in items:
                pi_id = str(rec_in["purchase_item_id"])
                if pi_id not in p_items_map:
                    raise ValidationError(
                        f"PurchaseItem {pi_id} does not belong to purchase {purchase.purchase_reference}."
                    )
                pi = p_items_map[pi_id]
                qty_rec = int(rec_in["quantity_received"])
                if qty_rec <= 0:
                    raise ValidationError("Received quantity must be positive.")
                remaining = pi.quantity_ordered - pi.quantity_received
                if qty_rec > remaining:
                    raise ValidationError(
                        f"Cannot receive {qty_rec} units; only {remaining} units remain on order."
                    )

                exp_date = str(rec_in["expiry_date"])[:10]
                if exp_date <= today_iso:
                    raise ValidationError(
                        "Cannot receive an already-expired batch."
                    )
                batch_no = str(rec_in["batch_number"]).strip()
                if not batch_no:
                    raise ValidationError("Batch number is required when receiving stock.")

                batch = (
                    db.query(Batch)
                    .filter_by(
                        organization_id=user_session.organization_id,
                        product_id=pi.product_id,
                        batch_number=batch_no,
                    )
                    .first()
                )
                batch_op = SyncOperation.UPDATE.value
                if not batch:
                    batch_op = SyncOperation.CREATE.value
                    batch = Batch(
                        id=str(uuid.uuid4()),
                        organization_id=user_session.organization_id,
                        product_id=pi.product_id,
                        batch_number=batch_no,
                        expiry_date=exp_date,
                        manufacturing_date=rec_in.get("manufacturing_date"),
                        purchase_price=pi.purchase_price,
                        supplier_id=purchase.supplier_id,
                        received_date=today_iso,
                        status=BatchStatus.ACTIVE.value,
                        created_at=now_utc,
                        updated_at=now_utc,
                    )
                    db.add(batch)
                else:
                    batch.expiry_date = exp_date
                    batch.purchase_price = pi.purchase_price
                    batch.supplier_id = purchase.supplier_id
                    if batch.status == BatchStatus.DEPLETED.value:
                        batch.status = BatchStatus.ACTIVE.value
                    batch.updated_at = now_utc
                db.flush()

                batch_sync = SyncEvent(
                    id=str(uuid.uuid4()),
                    branch_id=purchase.branch_id,
                    device_id=user_session.device_id,
                    entity_type="batch",
                    entity_id=batch.id,
                    operation=batch_op,
                    payload=json.dumps({
                        "id": batch.id,
                        "organization_id": batch.organization_id,
                        "product_id": batch.product_id,
                        "batch_number": batch.batch_number,
                        "expiry_date": batch.expiry_date,
                        "manufacturing_date": batch.manufacturing_date,
                        "purchase_price": str(batch.purchase_price),
                        "supplier_id": batch.supplier_id,
                        "received_date": batch.received_date,
                        "status": batch.status,
                    }),
                    correlation_id=corr_id,
                    dependency_level=SYNC_DEPENDENCY_LEVELS["batch"],
                    schema_version=SYNC_SCHEMA_VERSION,
                    local_created_at=now_local,
                    status="PENDING",
                )
                db.add(batch_sync)

                # Apply positive STOCK_RECEIVED movement
                self.inventory_service._apply_movement_in_tx(
                    db=db,
                    user_session=user_session,
                    branch_id=purchase.branch_id,
                    batch_id=batch.id,
                    storage_location_id=rec_in.get("storage_location_id"),
                    movement_type=MovementType.STOCK_RECEIVED.value,
                    quantity_change=qty_rec,
                    reference_type="purchase",
                    reference_id=purchase.id,
                    notes=f"Purchase {purchase.purchase_reference} received",
                    correlation_id=corr_id,
                    allow_negative=False,
                    emit_movement_sync=True,
                )

                pi.batch_id = batch.id
                pi.quantity_received += qty_rec
                if rec_in.get("selling_price") is not None:
                    pi.selling_price = Decimal(str(rec_in["selling_price"])).quantize(
                        Decimal("0.01")
                    )
                pi.updated_at = now_utc
                db.flush()

                pi_sync = SyncEvent(
                    id=str(uuid.uuid4()),
                    branch_id=purchase.branch_id,
                    device_id=user_session.device_id,
                    entity_type="purchase_item",
                    entity_id=pi.id,
                    operation=SyncOperation.UPDATE.value,
                    payload=json.dumps({
                        "id": pi.id,
                        "purchase_id": purchase.id,
                        "product_id": pi.product_id,
                        "batch_id": pi.batch_id,
                        "quantity_ordered": pi.quantity_ordered,
                        "quantity_received": pi.quantity_received,
                        "purchase_price": str(pi.purchase_price),
                        "selling_price": str(pi.selling_price),
                        "discount": str(pi.discount),
                        "line_total": str(pi.line_total),
                    }),
                    correlation_id=corr_id,
                    dependency_level=SYNC_DEPENDENCY_LEVELS["purchase_item"],
                    schema_version=SYNC_SCHEMA_VERSION,
                    local_created_at=now_local,
                    status="PENDING",
                )
                db.add(pi_sync)

                # Optionally update current Price when receiving stock
                if rec_in.get("update_selling_price") and pi.selling_price > Decimal("0.00"):
                    prev_prices = (
                        db.query(Price)
                        .filter_by(
                            organization_id=user_session.organization_id,
                            product_id=pi.product_id,
                            branch_id=purchase.branch_id,
                            is_current=True,
                        )
                        .all()
                    )
                    max_ver = max((p.version for p in prev_prices), default=0)
                    for p in prev_prices:
                        p.is_current = False
                        p.effective_to = now_utc
                    new_price = Price(
                        id=str(uuid.uuid4()),
                        organization_id=user_session.organization_id,
                        product_id=pi.product_id,
                        branch_id=purchase.branch_id,
                        selling_price=pi.selling_price,
                        is_current=True,
                        version=max_ver + 1,
                        effective_from=now_utc,
                        created_by_id=(
                            user_session.user_id
                            if db.query(User).filter_by(id=user_session.user_id).first()
                            else None
                        ),
                        sync_status="PENDING",
                        created_at=now_utc,
                        updated_at=now_utc,
                    )
                    db.add(new_price)
                    db.flush()

                    price_sync = SyncEvent(
                        id=str(uuid.uuid4()),
                        branch_id=purchase.branch_id,
                        device_id=user_session.device_id,
                        entity_type="price",
                        entity_id=new_price.id,
                        operation=SyncOperation.CREATE.value,
                        payload=json.dumps({
                            "id": new_price.id,
                            "organization_id": new_price.organization_id,
                            "product_id": new_price.product_id,
                            "branch_id": new_price.branch_id,
                            "selling_price": str(new_price.selling_price),
                            "currency": new_price.currency,
                            "is_current": True,
                            "version": new_price.version,
                            "effective_from": new_price.effective_from,
                        }),
                        correlation_id=corr_id,
                        dependency_level=SYNC_DEPENDENCY_LEVELS["price"],
                        schema_version=SYNC_SCHEMA_VERSION,
                        local_created_at=now_local,
                        status="PENDING",
                    )
                    db.add(price_sync)

            all_received = all(
                item.quantity_received >= item.quantity_ordered
                for item in p_items_map.values()
            )
            before_status = purchase.receiving_status
            purchase.receiving_status = (
                ReceivingStatus.RECEIVED.value
                if all_received
                else ReceivingStatus.PARTIALLY_RECEIVED.value
            )
            purchase.updated_at = now_utc
            db.flush()

            purchase_payload = {
                "id": purchase.id,
                "organization_id": purchase.organization_id,
                "branch_id": purchase.branch_id,
                "supplier_id": purchase.supplier_id,
                "user_id": purchase.user_id,
                "purchase_reference": purchase.purchase_reference,
                "invoice_number": purchase.invoice_number,
                "purchase_date": purchase.purchase_date,
                "subtotal": str(purchase.subtotal),
                "discount_amount": str(purchase.discount_amount),
                "total": str(purchase.total),
                "payment_status": purchase.payment_status,
                "receiving_status": purchase.receiving_status,
                "notes": purchase.notes,
            }

            self.record_audit_and_sync(
                db_session=db,
                user_session=user_session,
                action=AuditAction.STOCK_RECEIVED.value,
                entity_type="purchase",
                entity_id=purchase.id,
                operation=SyncOperation.UPDATE.value,
                payload=purchase_payload,
                data_before={"receiving_status": before_status},
                correlation_id=corr_id,
                transaction_id=purchase.id,
            )

            return {
                "purchase_id": purchase.id,
                "receiving_status": purchase.receiving_status,
                "correlation_id": corr_id,
            }

    def record_payment(
        self,
        user_session,
        purchase_id: str,
        payment_method: str,
        amount: str | Decimal,
        payment_date: str,
        reference: str | None = None,
    ) -> dict:
        self.require_permission(user_session, PermissionCode.STOCK_RECEIVE.value)
        pay_amount = Decimal(str(amount)).quantize(Decimal("0.01"))
        if pay_amount <= Decimal("0.00"):
            raise ValidationError("Payment amount must be positive.")

        corr_id = str(uuid.uuid4())
        now_local = datetime.now().astimezone().isoformat()
        now_utc = datetime.now(timezone.utc).isoformat()

        with self.transaction() as db:
            purchase = (
                db.query(Purchase)
                .filter_by(id=purchase_id, organization_id=user_session.organization_id)
                .first()
            )
            if not purchase:
                raise ValidationError("Purchase not found.")

            payment = PurchasePayment(
                id=str(uuid.uuid4()),
                purchase_id=purchase.id,
                payment_method=payment_method,
                amount=pay_amount,
                reference=reference,
                payment_date=payment_date[:10],
                created_at=now_utc,
            )
            db.add(payment)
            db.flush()

            pay_sync = SyncEvent(
                id=str(uuid.uuid4()),
                branch_id=purchase.branch_id,
                device_id=user_session.device_id,
                entity_type="purchase_payment",
                entity_id=payment.id,
                operation=SyncOperation.CREATE.value,
                payload=json.dumps({
                    "id": payment.id,
                    "purchase_id": purchase.id,
                    "payment_method": payment.payment_method,
                    "amount": str(payment.amount),
                    "reference": payment.reference,
                    "payment_date": payment.payment_date,
                }),
                correlation_id=corr_id,
                dependency_level=SYNC_DEPENDENCY_LEVELS["purchase_payment"],
                schema_version=SYNC_SCHEMA_VERSION,
                local_created_at=now_local,
                status="PENDING",
            )
            db.add(pay_sync)

            total_paid = (
                db.query(func.coalesce(func.sum(PurchasePayment.amount), 0))
                .filter(PurchasePayment.purchase_id == purchase.id)
                .scalar()
                or Decimal("0.00")
            )
            total_paid = Decimal(str(total_paid)).quantize(Decimal("0.01"))
            if total_paid >= purchase.total:
                purchase.payment_status = PaymentStatus.PAID.value
            elif total_paid > Decimal("0.00"):
                purchase.payment_status = PaymentStatus.PARTIALLY_PAID.value
            else:
                purchase.payment_status = PaymentStatus.UNPAID.value
            purchase.updated_at = now_utc
            db.flush()

            pur_sync = SyncEvent(
                id=str(uuid.uuid4()),
                branch_id=purchase.branch_id,
                device_id=user_session.device_id,
                entity_type="purchase",
                entity_id=purchase.id,
                operation=SyncOperation.UPDATE.value,
                payload=json.dumps({
                    "id": purchase.id,
                    "organization_id": purchase.organization_id,
                    "branch_id": purchase.branch_id,
                    "supplier_id": purchase.supplier_id,
                    "user_id": purchase.user_id,
                    "purchase_reference": purchase.purchase_reference,
                    "invoice_number": purchase.invoice_number,
                    "purchase_date": purchase.purchase_date,
                    "subtotal": str(purchase.subtotal),
                    "discount_amount": str(purchase.discount_amount),
                    "total": str(purchase.total),
                    "payment_status": purchase.payment_status,
                    "receiving_status": purchase.receiving_status,
                    "notes": purchase.notes,
                }),
                correlation_id=corr_id,
                dependency_level=SYNC_DEPENDENCY_LEVELS["purchase"],
                schema_version=SYNC_SCHEMA_VERSION,
                local_created_at=now_local,
                status="PENDING",
            )
            db.add(pur_sync)

            return {
                "purchase_id": purchase.id,
                "payment_id": payment.id,
                "payment_status": purchase.payment_status,
                "total_paid": total_paid,
                "correlation_id": corr_id,
            }

    def list_suppliers(self, organization_id: str, active_only: bool = True) -> list[Supplier]:
        with self.transaction() as db:
            q = db.query(Supplier).filter_by(organization_id=organization_id)
            if active_only:
                q = q.filter_by(is_active=True)
            rows = q.order_by(Supplier.name.asc()).all()
            for r in rows:
                db.expunge(r)
            return rows

    def create_supplier(
        self,
        user_session,
        name: str,
        contact_person: str = "",
        phone: str = "",
        email: str = "",
        address: str = "",
    ) -> Supplier:
        if not name or not name.strip():
            raise ValidationError("Supplier name is required.")
        now_utc = datetime.now(timezone.utc).isoformat()
        now_local = datetime.now().astimezone().isoformat()
        with self.transaction() as db:
            existing = (
                db.query(Supplier)
                .filter_by(organization_id=user_session.organization_id, name=name.strip())
                .first()
            )
            if existing:
                db.expunge(existing)
                return existing

            sup = Supplier(
                id=str(uuid.uuid4()),
                organization_id=user_session.organization_id,
                name=name.strip(),
                contact_person=contact_person or "",
                phone=phone or "",
                email=email or "",
                address=address or "",
                is_active=True,
                created_at=now_utc,
                updated_at=now_utc,
            )
            db.add(sup)
            db.flush()

            db.add(
                SyncEvent(
                    id=str(uuid.uuid4()),
                    branch_id=user_session.branch_id,
                    device_id=user_session.device_id,
                    entity_type="supplier",
                    entity_id=sup.id,
                    operation=SyncOperation.CREATE.value,
                    payload=json.dumps({
                        "id": sup.id,
                        "organization_id": sup.organization_id,
                        "name": sup.name,
                        "contact_person": sup.contact_person,
                        "phone": sup.phone,
                        "email": sup.email,
                        "address": sup.address,
                        "is_active": True,
                    }),
                    correlation_id=sup.id,
                    dependency_level=SYNC_DEPENDENCY_LEVELS.get("supplier", 2),
                    schema_version=SYNC_SCHEMA_VERSION,
                    local_created_at=now_local,
                    status="PENDING",
                )
            )
            db.expunge(sup)
            return sup

    def get_purchase_details(self, purchase_id: str) -> dict | None:
        with self.transaction() as db:
            p = db.query(Purchase).filter_by(id=purchase_id).first()
            if not p:
                return None
            sup = db.query(Supplier).filter_by(id=p.supplier_id).first()
            items = db.query(PurchaseItem).filter_by(purchase_id=p.id).all()
            item_list = []
            for it in items:
                prod = db.query(Product).filter_by(id=it.product_id).first()
                item_list.append({
                    "id": it.id,
                    "product_id": it.product_id,
                    "product_name": prod.name if prod else "Unknown Product",
                    "product_sku": prod.sku if prod else "",
                    "quantity_ordered": it.quantity_ordered,
                    "quantity_received": it.quantity_received,
                    "remaining_quantity": max(0, it.quantity_ordered - it.quantity_received),
                    "purchase_price": it.purchase_price,
                    "selling_price": it.selling_price,
                    "discount": it.discount,
                    "line_total": it.line_total,
                })
            payments = db.query(PurchasePayment).filter_by(purchase_id=p.id).all()
            pay_list = [
                {
                    "id": pay.id,
                    "payment_method": pay.payment_method,
                    "amount": pay.amount,
                    "reference": pay.reference,
                    "payment_date": pay.payment_date,
                }
                for pay in payments
            ]
            return {
                "id": p.id,
                "purchase_reference": p.purchase_reference,
                "invoice_number": p.invoice_number,
                "purchase_date": p.purchase_date,
                "supplier_name": sup.name if sup else "Unknown Supplier",
                "subtotal": p.subtotal,
                "discount_amount": p.discount_amount,
                "total": p.total,
                "payment_status": p.payment_status,
                "receiving_status": p.receiving_status,
                "notes": p.notes,
                "items": item_list,
                "payments": pay_list,
            }

    def list_purchases(self, branch_id: str, limit: int = 100) -> list[Purchase]:
        with self.transaction() as db:
            rows = (
                db.query(Purchase)
                .filter_by(branch_id=branch_id)
                .order_by(Purchase.purchase_date.desc())
                .limit(limit)
                .all()
            )
            for r in rows:
                db.expunge(r)
            return rows


def _download_purchase(db, organization_id, entity_id, operation, payload, delivery):
    p = db.query(Purchase).filter_by(id=entity_id).first()
    if not p:
        db.add(
            Purchase(
                id=entity_id,
                organization_id=organization_id,
                branch_id=str(payload["branch_id"]),
                supplier_id=str(payload["supplier_id"]),
                user_id=str(payload["user_id"]),
                purchase_reference=payload["purchase_reference"],
                invoice_number=payload.get("invoice_number"),
                purchase_date=str(payload.get("purchase_date", ""))[:10]
                or date.today().isoformat(),
                subtotal=Decimal(str(payload.get("subtotal", "0.00"))),
                discount_amount=Decimal(str(payload.get("discount_amount", "0.00"))),
                total=Decimal(str(payload.get("total", "0.00"))),
                payment_status=payload.get("payment_status", PaymentStatus.UNPAID.value),
                receiving_status=payload.get(
                    "receiving_status", ReceivingStatus.PENDING.value
                ),
                notes=payload.get("notes", ""),
            )
        )
    else:
        p.payment_status = payload.get("payment_status", p.payment_status)
        p.receiving_status = payload.get("receiving_status", p.receiving_status)
        if payload.get("invoice_number"):
            p.invoice_number = payload["invoice_number"]
    db.flush()


def _download_purchase_item(db, organization_id, entity_id, operation, payload, delivery):
    pi = db.query(PurchaseItem).filter_by(id=entity_id).first()
    if not pi:
        db.add(
            PurchaseItem(
                id=entity_id,
                purchase_id=str(payload["purchase_id"]),
                product_id=str(payload["product_id"]),
                batch_id=str(payload["batch_id"]) if payload.get("batch_id") else None,
                quantity_ordered=int(payload.get("quantity_ordered", 0)),
                quantity_received=int(payload.get("quantity_received", 0)),
                purchase_price=Decimal(str(payload.get("purchase_price", "0.00"))),
                selling_price=Decimal(str(payload.get("selling_price", "0.00"))),
                discount=Decimal(str(payload.get("discount", "0.00"))),
                line_total=Decimal(str(payload.get("line_total", "0.00"))),
            )
        )
    else:
        pi.batch_id = str(payload["batch_id"]) if payload.get("batch_id") else pi.batch_id
        pi.quantity_received = int(
            payload.get("quantity_received", pi.quantity_received)
        )
    db.flush()


def _download_purchase_payment(db, organization_id, entity_id, operation, payload, delivery):
    if not db.query(PurchasePayment).filter_by(id=entity_id).first():
        db.add(
            PurchasePayment(
                id=entity_id,
                purchase_id=str(payload["purchase_id"]),
                payment_method=payload["payment_method"],
                amount=Decimal(str(payload["amount"])),
                reference=payload.get("reference"),
                payment_date=str(payload.get("payment_date", ""))[:10]
                or date.today().isoformat(),
            )
        )
        db.flush()


register_download_handler("purchase", _download_purchase)
register_download_handler("purchase_item", _download_purchase_item)
register_download_handler("purchase_payment", _download_purchase_payment)
