import json
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from sqlalchemy import func
from desktop.app.db.models import (
    Branch,
    Device,
    Product,
    Batch,
    BranchInventory,
    ReceiptSequence,
    Sale,
    SaleItem,
    SaleReturn,
    SaleReturnItem,
    Payment,
    Receipt,
    SyncEvent,
)
from desktop.app.domain.batch_selector import (
    BatchStock,
    BatchAllocation,
    select_batches_fefo,
    select_batches_fifo,
)
from desktop.app.domain.exceptions import ValidationError, InsufficientStockError
from desktop.app.domain.pos_cart import POSCart
from desktop.app.printing.printer_manager import PrinterManager
from desktop.app.services.base_service import BaseService
from desktop.app.services.inventory_service import InventoryService
from desktop.app.sync.sync_engine import register_download_handler
from shared.enums import (
    PermissionCode,
    BatchStatus,
    MovementType,
    SaleStatus,
    AuditAction,
    SyncOperation,
    SYNC_DEPENDENCY_LEVELS,
    SYNC_SCHEMA_VERSION,
)


class SalesService(BaseService):
    """
    Offline-first POS / Sales service (Architecture Plan §7).
    Implements:
    - Per-(branch, device, date) collision-free receipt number generation.
    - Cart price freezing (`SaleItem.unit_price` captured from `CartItem.unit_price`).
    - FEFO / FIFO / Manual batch allocation with strict blocking of EXPIRED, RECALLED, DEPLETED batches.
    - Single atomic SQLite transaction creating Sale, SaleItems, Payments, InventoryMovements,
      Receipt, AuditEvent, and correlated SyncEvents (`correlation_id`).
    - Thermal receipt formatting and printing OUTSIDE the database transaction.
    """

    def __init__(self, db_manager, printer_manager: PrinterManager | None = None):
        super().__init__(db_manager)
        self.inventory_service = InventoryService(db_manager)
        self.printer_manager = printer_manager or PrinterManager(db_manager)

    def _resolve_device(self, db, branch_id: str, device_id: str | None = None) -> Device:
        branch = db.query(Branch).filter_by(id=branch_id).first()
        if not branch:
            raise ValidationError("Valid branch is required.")

        device = None
        if device_id and str(device_id).strip():
            device = db.query(Device).filter_by(id=str(device_id).strip()).first()
        if not device:
            device = db.query(Device).filter_by(branch_id=branch_id, is_active=True).first()
        if not device:
            new_id = (
                str(device_id).strip()
                if (device_id and str(device_id).strip())
                else str(uuid.uuid4())
            )
            device = Device(
                id=new_id,
                organization_id=branch.organization_id,
                branch_id=branch_id,
                name="POS Terminal 1",
                code="POS1",
                device_identifier=f"DEV-{branch.code}-POS1",
                is_active=True,
            )
            db.add(device)
            db.flush()
        return device

    def generate_receipt_number(
        self,
        db,
        branch_id: str,
        device_id: str | None = None,
        date_str: str | None = None,
    ) -> str:
        branch = db.query(Branch).filter_by(id=branch_id).first()
        if not branch:
            raise ValidationError("Valid branch is required to generate receipt numbers.")

        device = self._resolve_device(db, branch_id, device_id)
        dev_id = device.id

        day_code = date_str or date.today().strftime("%Y%m%d")
        seq_row = (
            db.query(ReceiptSequence)
            .filter_by(branch_id=branch_id, device_id=dev_id, date_str=day_code)
            .first()
        )
        if not seq_row:
            seq_row = ReceiptSequence(
                id=str(uuid.uuid4()),
                branch_id=branch_id,
                device_id=dev_id,
                date_str=day_code,
                last_sequence=1,
            )
            db.add(seq_row)
        else:
            seq_row.last_sequence += 1
        db.flush()

        return f"{branch.code}-{device.code}-{day_code}-{seq_row.last_sequence:06d}"

    def _get_batch_stocks_in_tx(
        self, db, organization_id: str, branch_id: str, product_id: str
    ) -> list[BatchStock]:
        today_iso = date.today().isoformat()
        batches = (
            db.query(Batch)
            .filter_by(organization_id=organization_id, product_id=product_id)
            .all()
        )
        stocks: list[BatchStock] = []
        for b in batches:
            # Automatically mark expired batches at POS sale time (Architecture Plan §2.3)
            if b.status == BatchStatus.ACTIVE.value and b.expiry_date < today_iso:
                b.status = BatchStatus.EXPIRED.value
                db.flush()

            invs = (
                db.query(BranchInventory)
                .filter_by(
                    organization_id=organization_id,
                    branch_id=branch_id,
                    batch_id=b.id,
                )
                .all()
            )
            avail = sum(i.available_quantity for i in invs)
            stocks.append(
                BatchStock(
                    batch_id=b.id,
                    batch_number=b.batch_number,
                    expiry_date=b.expiry_date,
                    received_date=b.received_date,
                    status=b.status,
                    available_quantity=avail,
                )
            )
        return stocks

    def checkout_cart(
        self,
        user_session,
        cart: POSCart,
        payments: list[dict],
        strategy: str = "FEFO",
    ) -> dict:
        """
        Finalizes a POS cart into an atomic Sale transaction and prints the receipt outside the transaction.
        `payments`: list of dicts `[{'payment_method': 'CASH', 'amount': '1500.00', 'reference': None}]`.
        """
        self.require_permission(user_session, PermissionCode.SALES_SELL.value)
        if not cart.items:
            raise ValidationError("Cannot checkout an empty cart.")
        if not payments:
            raise ValidationError("At least one payment method is required.")

        total_paid = sum(Decimal(str(p["amount"])) for p in payments).quantize(Decimal("0.01"))
        if total_paid < cart.total:
            raise ValidationError(
                f"Insufficient payment: paid {total_paid}, required {cart.total}."
            )

        today_iso = date.today().isoformat()
        corr_id = str(uuid.uuid4())
        now_local = datetime.now().astimezone().isoformat()
        now_utc = datetime.now(timezone.utc).isoformat()

        with self.transaction() as db:
            branch = (
                db.query(Branch)
                .filter_by(id=user_session.branch_id, organization_id=user_session.organization_id)
                .first()
            )
            if not branch:
                raise ValidationError("Active branch not found.")

            device = self._resolve_device(db, user_session.branch_id, getattr(user_session, "device_id", None))
            effective_device_id = device.id
            if not getattr(user_session, "device_id", None):
                user_session.device_id = effective_device_id

            receipt_no = self.generate_receipt_number(
                db, user_session.branch_id, effective_device_id
            )

            # 1. Resolve batch allocations for every CartItem using frozen CartItem.unit_price
            expanded_sale_items = []
            for c_item in cart.items:
                product = (
                    db.query(Product)
                    .filter_by(id=c_item.product_id, organization_id=user_session.organization_id)
                    .first()
                )
                if not product or not product.is_active:
                    raise ValidationError(f"Product '{c_item.product_name}' is not active.")

                if c_item.batch_id:
                    batch = (
                        db.query(Batch)
                        .filter_by(
                            id=c_item.batch_id,
                            product_id=product.id,
                            organization_id=user_session.organization_id,
                        )
                        .first()
                    )
                    if not batch:
                        raise ValidationError("Selected batch not found.")
                    if batch.expiry_date < today_iso and batch.status == BatchStatus.ACTIVE.value:
                        batch.status = BatchStatus.EXPIRED.value
                        db.flush()
                    if batch.status in (
                        BatchStatus.EXPIRED.value,
                        BatchStatus.RECALLED.value,
                        BatchStatus.DEPLETED.value,
                    ):
                        raise ValidationError(
                            f"Cannot sell from batch '{batch.batch_number}' because its status is {batch.status}."
                        )
                    invs = (
                        db.query(BranchInventory)
                        .filter_by(
                            organization_id=user_session.organization_id,
                            branch_id=user_session.branch_id,
                            batch_id=batch.id,
                        )
                        .all()
                    )
                    avail = sum(i.available_quantity for i in invs)
                    if avail < c_item.quantity:
                        raise InsufficientStockError(
                            f"Insufficient stock in batch '{batch.batch_number}' (available: {avail}, needed: {c_item.quantity})."
                        )
                    allocations = [
                        BatchAllocation(
                            batch_id=batch.id,
                            batch_number=batch.batch_number,
                            expiry_date=batch.expiry_date,
                            quantity=c_item.quantity,
                        )
                    ]
                else:
                    stocks = self._get_batch_stocks_in_tx(
                        db, user_session.organization_id, user_session.branch_id, product.id
                    )
                    if strategy.upper() == "FIFO":
                        allocations = select_batches_fifo(stocks, c_item.quantity, today_iso)
                    else:
                        allocations = select_batches_fefo(stocks, c_item.quantity, today_iso)

                for alloc in allocations:
                    alloc_disc = (
                        c_item.discount_amount
                        if len(allocations) == 1
                        else (
                            c_item.discount_amount
                            * Decimal(alloc.quantity)
                            / Decimal(c_item.quantity)
                        ).quantize(Decimal("0.01"))
                    )
                    line_sub = (c_item.unit_price * Decimal(alloc.quantity)).quantize(Decimal("0.01"))
                    line_tot = max(Decimal("0.00"), line_sub - alloc_disc)
                    expanded_sale_items.append({
                        "product_id": product.id,
                        "product_name": product.name,
                        "batch_id": alloc.batch_id,
                        "batch_number": alloc.batch_number,
                        "quantity": alloc.quantity,
                        "unit_price": c_item.unit_price,
                        "discount_amount": alloc_disc,
                        "line_total": line_tot,
                    })

            # 2. Insert Sale
            sale = Sale(
                id=str(uuid.uuid4()),
                organization_id=user_session.organization_id,
                branch_id=user_session.branch_id,
                user_id=user_session.user_id,
                device_id=effective_device_id,
                receipt_number=receipt_no,
                customer_name=cart.customer_name or None,
                customer_phone=cart.customer_phone or None,
                subtotal=cart.subtotal,
                discount_amount=cart.total_discount,
                tax_amount=cart.tax_amount,
                total=cart.total,
                status=SaleStatus.COMPLETED.value,
                sale_date=now_local,
                is_offline=user_session.is_offline,
                sync_status="PENDING",
                notes=cart.notes or "",
                created_at=now_utc,
                updated_at=now_utc,
            )
            db.add(sale)
            db.flush()

            sale_payload = {
                "id": sale.id,
                "organization_id": sale.organization_id,
                "branch_id": sale.branch_id,
                "user_id": sale.user_id,
                "device_id": sale.device_id,
                "receipt_number": sale.receipt_number,
                "customer_name": sale.customer_name,
                "customer_phone": sale.customer_phone,
                "subtotal": str(sale.subtotal),
                "discount_amount": str(sale.discount_amount),
                "tax_amount": str(sale.tax_amount),
                "total": str(sale.total),
                "status": sale.status,
                "sale_date": sale.sale_date,
                "is_offline": sale.is_offline,
                "notes": sale.notes,
            }

            # 3. Insert SaleItems and apply InventoryMovement(SALE) deltas
            created_items = []
            for exp in expanded_sale_items:
                s_item = SaleItem(
                    id=str(uuid.uuid4()),
                    sale_id=sale.id,
                    product_id=exp["product_id"],
                    batch_id=exp["batch_id"],
                    quantity=exp["quantity"],
                    unit_price=exp["unit_price"],
                    discount_amount=exp["discount_amount"],
                    line_total=exp["line_total"],
                    created_at=now_utc,
                )
                db.add(s_item)
                db.flush()
                created_items.append((s_item, exp["product_name"], exp["batch_number"]))

                item_sync = SyncEvent(
                    id=str(uuid.uuid4()),
                    branch_id=user_session.branch_id,
                    device_id=effective_device_id,
                    entity_type="sale_item",
                    entity_id=s_item.id,
                    operation=SyncOperation.CREATE.value,
                    payload=json.dumps({
                        "id": s_item.id,
                        "sale_id": sale.id,
                        "product_id": s_item.product_id,
                        "batch_id": s_item.batch_id,
                        "quantity": s_item.quantity,
                        "unit_price": str(s_item.unit_price),
                        "discount_amount": str(s_item.discount_amount),
                        "line_total": str(s_item.line_total),
                    }),
                    correlation_id=corr_id,
                    dependency_level=SYNC_DEPENDENCY_LEVELS["sale_item"],
                    schema_version=SYNC_SCHEMA_VERSION,
                    local_created_at=now_local,
                    status="PENDING",
                )
                db.add(item_sync)

                # Decrement BranchInventory and create immutable InventoryMovement(SALE) + SyncEvent
                self.inventory_service._apply_movement_in_tx(
                    db=db,
                    user_session=user_session,
                    branch_id=user_session.branch_id,
                    batch_id=s_item.batch_id,
                    storage_location_id=None,
                    movement_type=MovementType.SALE.value,
                    quantity_change=-s_item.quantity,
                    reference_type="sale",
                    reference_id=sale.id,
                    notes=f"POS Sale {sale.receipt_number}",
                    correlation_id=corr_id,
                    allow_negative=False,
                    emit_movement_sync=True,
                )

            # 4. Insert Payments + SyncEvents
            created_payments = []
            for p_in in payments:
                pay = Payment(
                    id=str(uuid.uuid4()),
                    sale_id=sale.id,
                    payment_method=p_in["payment_method"],
                    amount=Decimal(str(p_in["amount"])).quantize(Decimal("0.01")),
                    reference=p_in.get("reference"),
                    created_at=now_utc,
                )
                db.add(pay)
                db.flush()
                created_payments.append(pay)

                pay_sync = SyncEvent(
                    id=str(uuid.uuid4()),
                    branch_id=user_session.branch_id,
                    device_id=effective_device_id,
                    entity_type="payment",
                    entity_id=pay.id,
                    operation=SyncOperation.CREATE.value,
                    payload=json.dumps({
                        "id": pay.id,
                        "sale_id": sale.id,
                        "payment_method": pay.payment_method,
                        "amount": str(pay.amount),
                        "reference": pay.reference,
                    }),
                    correlation_id=corr_id,
                    dependency_level=SYNC_DEPENDENCY_LEVELS["payment"],
                    schema_version=SYNC_SCHEMA_VERSION,
                    local_created_at=now_local,
                    status="PENDING",
                )
                db.add(pay_sync)

            # 5. Insert Receipt + SyncEvent
            receipt = Receipt(
                id=str(uuid.uuid4()),
                sale_id=sale.id,
                receipt_number=sale.receipt_number,
                printed_at=now_local,
                printer_name="Default Thermal Printer",
                reprint_count=0,
                created_at=now_utc,
            )
            db.add(receipt)
            db.flush()

            rec_sync = SyncEvent(
                id=str(uuid.uuid4()),
                branch_id=user_session.branch_id,
                device_id=effective_device_id,
                entity_type="receipt",
                entity_id=receipt.id,
                operation=SyncOperation.CREATE.value,
                payload=json.dumps({
                    "id": receipt.id,
                    "sale_id": sale.id,
                    "receipt_number": receipt.receipt_number,
                    "printed_at": receipt.printed_at,
                    "printer_name": receipt.printer_name,
                    "reprint_count": 0,
                }),
                correlation_id=corr_id,
                dependency_level=SYNC_DEPENDENCY_LEVELS["receipt"],
                schema_version=SYNC_SCHEMA_VERSION,
                local_created_at=now_local,
                status="PENDING",
            )
            db.add(rec_sync)

            # 6. Record AuditEvent(SALE_CREATED) + Sale SyncEvent sharing correlation_id
            self.record_audit_and_sync(
                db_session=db,
                user_session=user_session,
                action=AuditAction.SALE_CREATED.value,
                entity_type="sale",
                entity_id=sale.id,
                operation=SyncOperation.CREATE.value,
                payload=sale_payload,
                correlation_id=corr_id,
                transaction_id=sale.id,
            )

            receipt_context = {
                "organization_name": user_session.organization_name,
                "branch_name": branch.name,
                "branch_address": branch.address or "",
                "branch_phone": branch.phone or "",
                "receipt_number": sale.receipt_number,
                "sale_date": sale.sale_date,
                "cashier_name": user_session.full_name or user_session.username,
                "customer_name": sale.customer_name,
                "items": [
                    {
                        "product_name": p_name,
                        "batch_number": b_num,
                        "quantity": si.quantity,
                        "unit_price": si.unit_price,
                        "line_total": si.line_total,
                    }
                    for si, p_name, b_num in created_items
                ],
                "subtotal": sale.subtotal,
                "discount_amount": sale.discount_amount,
                "tax_amount": sale.tax_amount,
                "total": sale.total,
                "payments": [
                    {"payment_method": p.payment_method, "amount": p.amount}
                    for p in created_payments
                ],
            }
            sale_result = {
                "sale_id": sale.id,
                "receipt_number": sale.receipt_number,
                "subtotal": sale.subtotal,
                "discount_amount": sale.discount_amount,
                "tax_amount": sale.tax_amount,
                "total": sale.total,
                "status": sale.status,
                "correlation_id": corr_id,
                "items_count": len(created_items),
            }

        # 7. Print Receipt OUTSIDE the SQLite transaction (Architecture Plan §7.1)
        receipt_text = self.printer_manager.print_sale_receipt(
            receipt_context, branch_id=user_session.branch_id
        )
        sale_result["receipt_text"] = receipt_text
        cart.clear()
        return sale_result

    def reprint_receipt(self, user_session, sale_id: str) -> str:
        self.require_permission(user_session, PermissionCode.SALES_SELL.value)
        with self.transaction() as db:
            sale = (
                db.query(Sale)
                .filter_by(id=sale_id, organization_id=user_session.organization_id)
                .first()
            )
            if not sale:
                raise ValidationError("Sale not found.")
            receipt = db.query(Receipt).filter_by(sale_id=sale.id).first()
            if receipt:
                receipt.reprint_count += 1
                db.flush()

            branch = db.query(Branch).filter_by(id=sale.branch_id).first()
            s_items = db.query(SaleItem).filter_by(sale_id=sale.id).all()
            payments = db.query(Payment).filter_by(sale_id=sale.id).all()

            items_ctx = []
            for si in s_items:
                prod = db.query(Product).filter_by(id=si.product_id).first()
                batch = db.query(Batch).filter_by(id=si.batch_id).first()
                items_ctx.append({
                    "product_name": prod.name if prod else si.product_id,
                    "batch_number": batch.batch_number if batch else "",
                    "quantity": si.quantity,
                    "unit_price": si.unit_price,
                    "line_total": si.line_total,
                })

            ctx = {
                "organization_name": user_session.organization_name,
                "branch_name": branch.name if branch else user_session.branch_name,
                "branch_address": branch.address if branch else "",
                "branch_phone": branch.phone if branch else "",
                "receipt_number": sale.receipt_number,
                "sale_date": sale.sale_date,
                "cashier_name": user_session.full_name or user_session.username,
                "customer_name": sale.customer_name,
                "items": items_ctx,
                "subtotal": sale.subtotal,
                "discount_amount": sale.discount_amount,
                "tax_amount": sale.tax_amount,
                "total": sale.total,
                "payments": [
                    {"payment_method": p.payment_method, "amount": p.amount}
                    for p in payments
                ],
                "is_reprint": True,
            }

        return self.printer_manager.print_sale_receipt(ctx, branch_id=user_session.branch_id)

    def list_sales(self, branch_id: str, limit: int = 100) -> list[Sale]:
        with self.transaction() as db:
            return (
                db.query(Sale)
                .filter_by(branch_id=branch_id)
                .order_by(Sale.sale_date.desc())
                .limit(limit)
                .all()
            )

    def void_sale(self, user_session, sale_id: str, reason: str) -> dict:
        """
        Voids an entire completed sale that has had no partial returns yet.
        Requires SALES_VOID permission and a non-empty reason.
        Creates a full SaleReturn, SaleReturnItems, positive InventoryMovement(SALE_RETURN)
        deltas restoring stock to the original batches, sets Sale.status = VOIDED,
        and emits correlated SyncEvents + AuditEvent(SALE_VOIDED).
        """
        self.require_permission(user_session, PermissionCode.SALES_VOID.value)
        if not reason or not reason.strip():
            raise ValidationError("A reason is required when voiding a sale.")

        corr_id = str(uuid.uuid4())
        now_local = datetime.now().astimezone().isoformat()
        now_utc = datetime.now(timezone.utc).isoformat()

        with self.transaction() as db:
            sale = (
                db.query(Sale)
                .filter_by(id=sale_id, organization_id=user_session.organization_id)
                .first()
            )
            if not sale:
                raise ValidationError("Sale not found.")
            if sale.status == SaleStatus.VOIDED.value:
                raise ValidationError("Sale is already voided.")
            if sale.status == SaleStatus.RETURNED.value:
                raise ValidationError("Cannot void a sale that has already been returned.")
            if sale.status == SaleStatus.PARTIALLY_RETURNED.value:
                raise ValidationError(
                    "Cannot void a sale that already has partial returns; return remaining items instead."
                )

            device = self._resolve_device(db, sale.branch_id, getattr(user_session, "device_id", None))
            effective_device_id = device.id
            if not getattr(user_session, "device_id", None):
                user_session.device_id = effective_device_id

            existing_returns = db.query(SaleReturn).filter_by(original_sale_id=sale.id).count()
            return_receipt_no = f"VOID-{sale.receipt_number}-{existing_returns + 1:02d}"

            sale_return = SaleReturn(
                id=str(uuid.uuid4()),
                organization_id=user_session.organization_id,
                branch_id=sale.branch_id,
                original_sale_id=sale.id,
                user_id=user_session.user_id,
                device_id=effective_device_id,
                return_receipt_number=return_receipt_no,
                reason=reason.strip(),
                refund_amount=sale.total,
                return_date=now_local,
                is_offline=user_session.is_offline,
                sync_status="PENDING",
                created_at=now_utc,
            )
            db.add(sale_return)
            db.flush()

            ret_sync = SyncEvent(
                id=str(uuid.uuid4()),
                branch_id=sale.branch_id,
                device_id=effective_device_id,
                entity_type="sale_return",
                entity_id=sale_return.id,
                operation=SyncOperation.CREATE.value,
                payload=json.dumps({
                    "id": sale_return.id,
                    "organization_id": sale_return.organization_id,
                    "branch_id": sale_return.branch_id,
                    "original_sale_id": sale.id,
                    "user_id": sale_return.user_id,
                    "device_id": sale_return.device_id,
                    "return_receipt_number": sale_return.return_receipt_number,
                    "reason": sale_return.reason,
                    "refund_amount": str(sale_return.refund_amount),
                    "return_date": sale_return.return_date,
                    "is_offline": sale_return.is_offline,
                }),
                correlation_id=corr_id,
                dependency_level=SYNC_DEPENDENCY_LEVELS["sale_return"],
                schema_version=SYNC_SCHEMA_VERSION,
                local_created_at=now_local,
                status="PENDING",
            )
            db.add(ret_sync)

            sale_items = db.query(SaleItem).filter_by(sale_id=sale.id).all()
            for si in sale_items:
                ret_item = SaleReturnItem(
                    id=str(uuid.uuid4()),
                    sale_return_id=sale_return.id,
                    sale_item_id=si.id,
                    batch_id=si.batch_id,
                    quantity=si.quantity,
                    refund_amount=si.line_total,
                    created_at=now_utc,
                )
                db.add(ret_item)
                db.flush()

                ret_item_sync = SyncEvent(
                    id=str(uuid.uuid4()),
                    branch_id=sale.branch_id,
                    device_id=effective_device_id,
                    entity_type="sale_return_item",
                    entity_id=ret_item.id,
                    operation=SyncOperation.CREATE.value,
                    payload=json.dumps({
                        "id": ret_item.id,
                        "sale_return_id": sale_return.id,
                        "sale_item_id": si.id,
                        "batch_id": si.batch_id,
                        "quantity": si.quantity,
                        "refund_amount": str(ret_item.refund_amount),
                    }),
                    correlation_id=corr_id,
                    dependency_level=SYNC_DEPENDENCY_LEVELS["sale_return_item"],
                    schema_version=SYNC_SCHEMA_VERSION,
                    local_created_at=now_local,
                    status="PENDING",
                )
                db.add(ret_item_sync)

                # Restore stock to the original batch via positive SALE_RETURN movement
                self.inventory_service._apply_movement_in_tx(
                    db=db,
                    user_session=user_session,
                    branch_id=sale.branch_id,
                    batch_id=si.batch_id,
                    storage_location_id=None,
                    movement_type=MovementType.SALE_RETURN.value,
                    quantity_change=si.quantity,
                    reference_type="sale_return",
                    reference_id=sale_return.id,
                    notes=f"Void Sale {sale.receipt_number}: {reason.strip()}",
                    correlation_id=corr_id,
                    allow_negative=False,
                    emit_movement_sync=True,
                )

            before_status = sale.status
            sale.status = SaleStatus.VOIDED.value
            sale.sync_status = "PENDING"
            sale.updated_at = now_utc
            db.flush()

            sale_update_payload = {
                "id": sale.id,
                "organization_id": sale.organization_id,
                "branch_id": sale.branch_id,
                "user_id": sale.user_id,
                "device_id": sale.device_id,
                "receipt_number": sale.receipt_number,
                "customer_name": sale.customer_name,
                "customer_phone": sale.customer_phone,
                "subtotal": str(sale.subtotal),
                "discount_amount": str(sale.discount_amount),
                "tax_amount": str(sale.tax_amount),
                "total": str(sale.total),
                "status": sale.status,
                "sale_date": sale.sale_date,
                "is_offline": sale.is_offline,
                "notes": sale.notes,
            }

            self.record_audit_and_sync(
                db_session=db,
                user_session=user_session,
                action=AuditAction.SALE_VOIDED.value,
                entity_type="sale",
                entity_id=sale.id,
                operation=SyncOperation.UPDATE.value,
                payload=sale_update_payload,
                data_before={"status": before_status},
                reason=reason.strip(),
                correlation_id=corr_id,
                transaction_id=sale_return.id,
            )

            return {
                "sale_id": sale.id,
                "sale_return_id": sale_return.id,
                "return_receipt_number": sale_return.return_receipt_number,
                "status": sale.status,
                "refund_amount": sale_return.refund_amount,
                "correlation_id": corr_id,
            }

    def return_sale(
        self,
        user_session,
        original_sale_id: str,
        items: list[dict],
        reason: str,
    ) -> dict:
        """
        Processes a full or partial return against an existing sale.
        `items`: `[{'sale_item_id': '...', 'quantity': 2}]`
        Requires SALES_RETURN permission and a non-empty reason.
        Validates that cumulative returned quantity never exceeds original `SaleItem.quantity`.
        Creates `SaleReturn`, `SaleReturnItem`s, positive `InventoryMovement(SALE_RETURN)` deltas,
        updates `Sale.status` (`PARTIALLY_RETURNED` or `RETURNED`), and emits correlated SyncEvents + AuditEvent.
        """
        self.require_permission(user_session, PermissionCode.SALES_RETURN.value)
        if not reason or not reason.strip():
            raise ValidationError("A reason is required when returning items.")
        if not items:
            raise ValidationError("At least one item is required for a return.")

        corr_id = str(uuid.uuid4())
        now_local = datetime.now().astimezone().isoformat()
        now_utc = datetime.now(timezone.utc).isoformat()

        with self.transaction() as db:
            sale = (
                db.query(Sale)
                .filter_by(id=original_sale_id, organization_id=user_session.organization_id)
                .first()
            )
            if not sale:
                raise ValidationError("Original sale not found.")
            if sale.status in (SaleStatus.VOIDED.value, SaleStatus.RETURNED.value):
                raise ValidationError(
                    f"Cannot return items from a sale with status {sale.status}."
                )

            all_sale_items = {
                si.id: si
                for si in db.query(SaleItem).filter_by(sale_id=sale.id).all()
            }

            # Compute already returned quantities per SaleItem across all prior SaleReturns
            already_returned_map = {}
            for s_id in all_sale_items:
                prev_qty = (
                    db.query(func.coalesce(func.sum(SaleReturnItem.quantity), 0))
                    .filter(SaleReturnItem.sale_item_id == s_id)
                    .scalar()
                    or 0
                )
                already_returned_map[s_id] = int(prev_qty)

            validated_lines = []
            total_refund = Decimal("0.00")

            for req_line in items:
                si_id = str(req_line["sale_item_id"])
                qty_to_return = int(req_line["quantity"])
                if qty_to_return <= 0:
                    raise ValidationError("Return quantity must be greater than zero.")
                if si_id not in all_sale_items:
                    raise ValidationError(
                        f"SaleItem {si_id} does not belong to sale {sale.receipt_number}."
                    )
                si = all_sale_items[si_id]
                prev_returned = already_returned_map.get(si_id, 0)
                remaining_returnable = si.quantity - prev_returned
                if qty_to_return > remaining_returnable:
                    raise ValidationError(
                        f"Cannot return {qty_to_return} units for SaleItem {si_id}; only {remaining_returnable} units remain returnable."
                    )

                already_returned_map[si_id] = prev_returned + qty_to_return
                line_refund = (
                    si.line_total * Decimal(qty_to_return) / Decimal(si.quantity)
                ).quantize(Decimal("0.01"))
                total_refund += line_refund
                validated_lines.append((si, qty_to_return, line_refund))

            device = self._resolve_device(db, sale.branch_id, getattr(user_session, "device_id", None))
            effective_device_id = device.id
            if not getattr(user_session, "device_id", None):
                user_session.device_id = effective_device_id

            existing_returns = db.query(SaleReturn).filter_by(original_sale_id=sale.id).count()
            return_receipt_no = f"RET-{sale.receipt_number}-{existing_returns + 1:02d}"

            sale_return = SaleReturn(
                id=str(uuid.uuid4()),
                organization_id=user_session.organization_id,
                branch_id=sale.branch_id,
                original_sale_id=sale.id,
                user_id=user_session.user_id,
                device_id=effective_device_id,
                return_receipt_number=return_receipt_no,
                reason=reason.strip(),
                refund_amount=total_refund,
                return_date=now_local,
                is_offline=user_session.is_offline,
                sync_status="PENDING",
                created_at=now_utc,
            )
            db.add(sale_return)
            db.flush()

            ret_payload = {
                "id": sale_return.id,
                "organization_id": sale_return.organization_id,
                "branch_id": sale_return.branch_id,
                "original_sale_id": sale.id,
                "user_id": sale_return.user_id,
                "device_id": sale_return.device_id,
                "return_receipt_number": sale_return.return_receipt_number,
                "reason": sale_return.reason,
                "refund_amount": str(sale_return.refund_amount),
                "return_date": sale_return.return_date,
                "is_offline": sale_return.is_offline,
            }

            for si, qty_to_return, line_refund in validated_lines:
                ret_item = SaleReturnItem(
                    id=str(uuid.uuid4()),
                    sale_return_id=sale_return.id,
                    sale_item_id=si.id,
                    batch_id=si.batch_id,
                    quantity=qty_to_return,
                    refund_amount=line_refund,
                    created_at=now_utc,
                )
                db.add(ret_item)
                db.flush()

                ret_item_sync = SyncEvent(
                    id=str(uuid.uuid4()),
                    branch_id=sale.branch_id,
                    device_id=effective_device_id,
                    entity_type="sale_return_item",
                    entity_id=ret_item.id,
                    operation=SyncOperation.CREATE.value,
                    payload=json.dumps({
                        "id": ret_item.id,
                        "sale_return_id": sale_return.id,
                        "sale_item_id": si.id,
                        "batch_id": si.batch_id,
                        "quantity": qty_to_return,
                        "refund_amount": str(line_refund),
                    }),
                    correlation_id=corr_id,
                    dependency_level=SYNC_DEPENDENCY_LEVELS["sale_return_item"],
                    schema_version=SYNC_SCHEMA_VERSION,
                    local_created_at=now_local,
                    status="PENDING",
                )
                db.add(ret_item_sync)

                # Restore stock to original batch via positive SALE_RETURN movement
                self.inventory_service._apply_movement_in_tx(
                    db=db,
                    user_session=user_session,
                    branch_id=sale.branch_id,
                    batch_id=si.batch_id,
                    storage_location_id=None,
                    movement_type=MovementType.SALE_RETURN.value,
                    quantity_change=qty_to_return,
                    reference_type="sale_return",
                    reference_id=sale_return.id,
                    notes=f"Return {sale_return.return_receipt_number}: {reason.strip()}",
                    correlation_id=corr_id,
                    allow_negative=False,
                    emit_movement_sync=True,
                )

            # Determine whether all items of the sale are now fully returned
            all_fully_returned = all(
                already_returned_map.get(s_id, 0) >= s_obj.quantity
                for s_id, s_obj in all_sale_items.items()
            )
            before_status = sale.status
            sale.status = (
                SaleStatus.RETURNED.value
                if all_fully_returned
                else SaleStatus.PARTIALLY_RETURNED.value
            )
            sale.sync_status = "PENDING"
            sale.updated_at = now_utc
            db.flush()

            sale_update_sync = SyncEvent(
                id=str(uuid.uuid4()),
                branch_id=sale.branch_id,
                device_id=effective_device_id,
                entity_type="sale",
                entity_id=sale.id,
                operation=SyncOperation.UPDATE.value,
                payload=json.dumps({
                    "id": sale.id,
                    "organization_id": sale.organization_id,
                    "branch_id": sale.branch_id,
                    "user_id": sale.user_id,
                    "device_id": sale.device_id,
                    "receipt_number": sale.receipt_number,
                    "customer_name": sale.customer_name,
                    "customer_phone": sale.customer_phone,
                    "subtotal": str(sale.subtotal),
                    "discount_amount": str(sale.discount_amount),
                    "tax_amount": str(sale.tax_amount),
                    "total": str(sale.total),
                    "status": sale.status,
                    "sale_date": sale.sale_date,
                    "is_offline": sale.is_offline,
                    "notes": sale.notes,
                }),
                correlation_id=corr_id,
                dependency_level=SYNC_DEPENDENCY_LEVELS["sale"],
                schema_version=SYNC_SCHEMA_VERSION,
                local_created_at=now_local,
                status="PENDING",
            )
            db.add(sale_update_sync)

            self.record_audit_and_sync(
                db_session=db,
                user_session=user_session,
                action=AuditAction.SALE_RETURNED.value,
                entity_type="sale_return",
                entity_id=sale_return.id,
                operation=SyncOperation.CREATE.value,
                payload=ret_payload,
                data_before={"sale_status": before_status},
                reason=reason.strip(),
                correlation_id=corr_id,
                transaction_id=sale_return.id,
            )

            return {
                "sale_return_id": sale_return.id,
                "original_sale_id": sale.id,
                "return_receipt_number": sale_return.return_receipt_number,
                "refund_amount": sale_return.refund_amount,
                "sale_status": sale.status,
                "correlation_id": corr_id,
            }

    def list_returns(self, branch_id: str, limit: int = 100) -> list[SaleReturn]:
        with self.transaction() as db:
            return (
                db.query(SaleReturn)
                .filter_by(branch_id=branch_id)
                .order_by(SaleReturn.return_date.desc())
                .limit(limit)
                .all()
            )


def _download_sale(db, organization_id, entity_id, operation, payload, delivery):
    sale = db.query(Sale).filter_by(id=entity_id).first()
    if not sale:
        sale = Sale(
            id=entity_id,
            organization_id=organization_id,
            branch_id=str(payload["branch_id"]),
            user_id=str(payload["user_id"]),
            device_id=str(payload["device_id"]),
            receipt_number=payload["receipt_number"],
            customer_name=payload.get("customer_name"),
            customer_phone=payload.get("customer_phone"),
            subtotal=Decimal(str(payload.get("subtotal", "0.00"))),
            discount_amount=Decimal(str(payload.get("discount_amount", "0.00"))),
            tax_amount=Decimal(str(payload.get("tax_amount", "0.00"))),
            total=Decimal(str(payload.get("total", "0.00"))),
            status=payload.get("status", SaleStatus.COMPLETED.value),
            sale_date=payload.get("sale_date") or datetime.now(timezone.utc).isoformat(),
            server_received_at=payload.get("server_received_at"),
            is_offline=bool(payload.get("is_offline", False)),
            sync_status="SYNCED",
            notes=payload.get("notes", ""),
        )
        db.add(sale)
    else:
        sale.status = payload.get("status", sale.status)
        sale.sync_status = "SYNCED"
    db.flush()


def _download_sale_item(db, organization_id, entity_id, operation, payload, delivery):
    if not db.query(SaleItem).filter_by(id=entity_id).first():
        db.add(
            SaleItem(
                id=entity_id,
                sale_id=str(payload["sale_id"]),
                product_id=str(payload["product_id"]),
                batch_id=str(payload["batch_id"]),
                quantity=int(payload["quantity"]),
                unit_price=Decimal(str(payload["unit_price"])),
                discount_amount=Decimal(str(payload.get("discount_amount", "0.00"))),
                line_total=Decimal(str(payload["line_total"])),
            )
        )
        db.flush()


def _download_payment(db, organization_id, entity_id, operation, payload, delivery):
    if not db.query(Payment).filter_by(id=entity_id).first():
        db.add(
            Payment(
                id=entity_id,
                sale_id=str(payload["sale_id"]),
                payment_method=payload["payment_method"],
                amount=Decimal(str(payload["amount"])),
                reference=payload.get("reference"),
            )
        )
        db.flush()


def _download_receipt(db, organization_id, entity_id, operation, payload, delivery):
    rec = db.query(Receipt).filter_by(id=entity_id).first()
    if not rec:
        db.add(
            Receipt(
                id=entity_id,
                sale_id=str(payload["sale_id"]),
                receipt_number=payload["receipt_number"],
                printed_at=payload.get("printed_at") or datetime.now(timezone.utc).isoformat(),
                printer_name=payload.get("printer_name"),
                reprint_count=int(payload.get("reprint_count", 0)),
            )
        )
    else:
        rec.reprint_count = int(payload.get("reprint_count", rec.reprint_count))
    db.flush()


def _download_sale_return(db, organization_id, entity_id, operation, payload, delivery):
    ret = db.query(SaleReturn).filter_by(id=entity_id).first()
    if not ret:
        db.add(
            SaleReturn(
                id=entity_id,
                organization_id=organization_id,
                branch_id=str(payload["branch_id"]),
                original_sale_id=str(payload["original_sale_id"]),
                user_id=str(payload["user_id"]),
                device_id=str(payload["device_id"]),
                return_receipt_number=payload["return_receipt_number"],
                reason=payload.get("reason", ""),
                refund_amount=Decimal(str(payload.get("refund_amount", "0.00"))),
                return_date=payload.get("return_date") or datetime.now(timezone.utc).isoformat(),
                server_received_at=payload.get("server_received_at"),
                is_offline=bool(payload.get("is_offline", False)),
                sync_status="SYNCED",
            )
        )
        db.flush()


def _download_sale_return_item(db, organization_id, entity_id, operation, payload, delivery):
    if not db.query(SaleReturnItem).filter_by(id=entity_id).first():
        db.add(
            SaleReturnItem(
                id=entity_id,
                sale_return_id=str(payload["sale_return_id"]),
                sale_item_id=str(payload["sale_item_id"]),
                batch_id=str(payload["batch_id"]),
                quantity=int(payload["quantity"]),
                refund_amount=Decimal(str(payload.get("refund_amount", "0.00"))),
            )
        )
        db.flush()


register_download_handler("sale", _download_sale)
register_download_handler("sale_item", _download_sale_item)
register_download_handler("payment", _download_payment)
register_download_handler("receipt", _download_receipt)
register_download_handler("sale_return", _download_sale_return)
register_download_handler("sale_return_item", _download_sale_return_item)

