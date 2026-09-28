import random
from datetime import date, datetime
from decimal import Decimal
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QPushButton,
    QHeaderView,
    QComboBox,
    QDialog,
    QMessageBox,
    QSpinBox,
    QDoubleSpinBox,
    QDateEdit,
    QGroupBox,
    QGridLayout,
    QScrollArea,
    QFrame,
)
from PySide6.QtCore import Qt, QTimer, QDate
from desktop.app.db.models import Product, Supplier
from desktop.app.services.purchase_service import PurchaseService
from desktop.app.ui.common.title_bar import DialogHeaderBanner
from shared.enums import PermissionCode, PaymentStatus, ReceivingStatus


class CreateSupplierDialog(QDialog):
    """Quick modal dialog to register a new supplier."""

    def __init__(self, parent, purchase_service, session):
        super().__init__(parent)
        self.purchase_service = purchase_service
        self.session = session
        self.created_supplier = None

        self.setWindowTitle("Add New Supplier")
        self.setMinimumWidth(440)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        banner = DialogHeaderBanner(
            title="Register New Supplier",
            subtitle="Record supplier / pharmaceutical vendor contact information",
            parent_dialog=self,
        )
        layout.addWidget(banner)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(24, 18, 24, 22)
        body_layout.setSpacing(12)

        self.name_in = QLineEdit()
        self.name_in.setPlaceholderText("Supplier / Company Name *")
        body_layout.addWidget(self.name_in)

        self.contact_in = QLineEdit()
        self.contact_in.setPlaceholderText("Contact Person")
        body_layout.addWidget(self.contact_in)

        self.phone_in = QLineEdit()
        self.phone_in.setPlaceholderText("Phone Number")
        body_layout.addWidget(self.phone_in)

        self.email_in = QLineEdit()
        self.email_in.setPlaceholderText("Email Address")
        body_layout.addWidget(self.email_in)

        self.address_in = QLineEdit()
        self.address_in.setPlaceholderText("Physical / Office Address")
        body_layout.addWidget(self.address_in)

        self.err_lbl = QLabel("")
        self.err_lbl.setStyleSheet("color: #EF4444; font-size: 12px; font-weight: 600;")
        body_layout.addWidget(self.err_lbl)

        btn_box = QHBoxLayout()
        btn_box.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("SecondaryBtn")
        cancel_btn.clicked.connect(self.reject)
        btn_box.addWidget(cancel_btn)

        save_btn = QPushButton("Save Supplier")
        save_btn.setStyleSheet(
            "background-color: #10B981; color: white; font-weight: 600; padding: 7px 16px; border-radius: 6px;"
        )
        save_btn.clicked.connect(self._save)
        btn_box.addWidget(save_btn)

        body_layout.addLayout(btn_box)
        layout.addWidget(body)

    def _save(self):
        name = self.name_in.text().strip()
        if not name:
            self.err_lbl.setText("Supplier name is required.")
            self.name_in.setFocus()
            return
        try:
            sup = self.purchase_service.create_supplier(
                user_session=self.session,
                name=name,
                contact_person=self.contact_in.text().strip(),
                phone=self.phone_in.text().strip(),
                email=self.email_in.text().strip(),
                address=self.address_in.text().strip(),
            )
            self.created_supplier = sup
            self.accept()
        except Exception as e:
            self.err_lbl.setText(f"Error: {str(e)}")


class CreatePurchaseDialog(QDialog):
    """Modal dialog for creating a new purchase order."""

    def __init__(self, parent, purchase_service, session):
        super().__init__(parent)
        self.purchase_service = purchase_service
        self.session = session
        self.suppliers = []
        self.products = []
        self.line_items = []  # list of dicts: {'product_combo', 'qty_spin', 'cost_in', 'sell_in', 'tot_lbl'}

        self.setWindowTitle("Create New Purchase Order")
        self.setMinimumSize(880, 620)
        self.init_ui()
        self.load_data()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        banner = DialogHeaderBanner(
            title="New Purchase Order / Stock Acquisition",
            subtitle="Record supplier details, order references, and acquisition line items",
            parent_dialog=self,
        )
        layout.addWidget(banner)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(24, 16, 24, 20)
        body_layout.setSpacing(14)

        # Top Form Grid
        top_group = QGroupBox("Order Information")
        top_grid = QGridLayout(top_group)
        top_grid.setSpacing(10)

        # Supplier selector & Add button
        sup_layout = QHBoxLayout()
        self.supplier_combo = QComboBox()
        self.supplier_combo.setMinimumWidth(220)
        sup_layout.addWidget(self.supplier_combo, stretch=1)

        add_sup_btn = QPushButton("+ New")
        add_sup_btn.setObjectName("SecondaryBtn")
        add_sup_btn.clicked.connect(self._open_new_supplier_dialog)
        sup_layout.addWidget(add_sup_btn)

        # Auto-generated reference
        today_code = datetime.now().strftime("%Y%m%d")
        rand_suffix = f"{random.randint(1000, 9999)}"
        self.ref_input = QLineEdit(f"PO-{today_code}-{rand_suffix}")

        self.inv_input = QLineEdit()
        self.inv_input.setPlaceholderText("Supplier Invoice / Bill # (Optional)")

        self.date_input = QDateEdit()
        self.date_input.setCalendarPopup(True)
        self.date_input.setDate(QDate.currentDate())

        top_grid.addWidget(QLabel("Supplier *:"), 0, 0)
        top_grid.addLayout(sup_layout, 0, 1)
        top_grid.addWidget(QLabel("Reference *:"), 0, 2)
        top_grid.addWidget(self.ref_input, 0, 3)

        top_grid.addWidget(QLabel("Invoice Number:"), 1, 0)
        top_grid.addWidget(self.inv_input, 1, 1)
        top_grid.addWidget(QLabel("Purchase Date:"), 1, 2)
        top_grid.addWidget(self.date_input, 1, 3)

        body_layout.addWidget(top_group)

        # Line Items Header
        items_hdr_layout = QHBoxLayout()
        items_title = QLabel("Order Items")
        items_title.setStyleSheet("font-size: 15px; font-weight: 700; color: #1E293B;")
        items_hdr_layout.addWidget(items_title)
        items_hdr_layout.addStretch()

        add_line_btn = QPushButton("+ Add Product Line")
        add_line_btn.setStyleSheet(
            "background-color: #2563EB; color: white; font-weight: 600; padding: 6px 14px; border-radius: 5px;"
        )
        add_line_btn.clicked.connect(self.add_line_item)
        items_hdr_layout.addWidget(add_line_btn)
        body_layout.addLayout(items_hdr_layout)

        # Scroll Area for Items
        self.items_scroll = QScrollArea()
        self.items_scroll.setWidgetResizable(True)
        self.items_scroll.setFrameShape(QFrame.NoFrame)

        self.items_container = QWidget()
        self.items_layout = QVBoxLayout(self.items_container)
        self.items_layout.setContentsMargins(0, 0, 0, 0)
        self.items_layout.setSpacing(8)
        self.items_layout.setAlignment(Qt.AlignTop)

        self.items_scroll.setWidget(self.items_container)
        body_layout.addWidget(self.items_scroll, stretch=1)

        # Summary Bar & Notes
        summary_group = QGroupBox("Order Summary & Financials")
        summary_grid = QGridLayout(summary_group)
        summary_grid.setSpacing(10)

        self.notes_input = QLineEdit()
        self.notes_input.setPlaceholderText("Delivery instructions, terms, or auditor notes...")

        self.discount_input = QDoubleSpinBox()
        self.discount_input.setRange(0, 10000000)
        self.discount_input.setDecimals(2)
        self.discount_input.setPrefix("₦ ")
        self.discount_input.valueChanged.connect(self.calculate_totals)

        self.subtotal_lbl = QLabel("₦ 0.00")
        self.subtotal_lbl.setStyleSheet("font-size: 14px; font-weight: 600; color: #334155;")

        self.grand_total_lbl = QLabel("₦ 0.00")
        self.grand_total_lbl.setStyleSheet("font-size: 18px; font-weight: 800; color: #10B981;")

        summary_grid.addWidget(QLabel("Order Notes:"), 0, 0)
        summary_grid.addWidget(self.notes_input, 0, 1, 1, 3)

        summary_grid.addWidget(QLabel("Overall Discount:"), 1, 0)
        summary_grid.addWidget(self.discount_input, 1, 1)

        summary_grid.addWidget(QLabel("Subtotal:"), 1, 2, Qt.AlignRight)
        summary_grid.addWidget(self.subtotal_lbl, 1, 3)

        summary_grid.addWidget(QLabel("Grand Total:"), 2, 2, Qt.AlignRight)
        summary_grid.addWidget(self.grand_total_lbl, 2, 3)

        body_layout.addWidget(summary_group)

        self.err_lbl = QLabel("")
        self.err_lbl.setStyleSheet("color: #EF4444; font-size: 12px; font-weight: 600;")
        body_layout.addWidget(self.err_lbl)

        # Bottom Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("SecondaryBtn")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        submit_btn = QPushButton("Create Purchase Order")
        submit_btn.setStyleSheet(
            "background-color: #10B981; color: white; font-weight: 700; padding: 10px 22px; border-radius: 6px; font-size: 14px;"
        )
        submit_btn.clicked.connect(self.on_submit)
        btn_layout.addWidget(submit_btn)

        body_layout.addLayout(btn_layout)
        layout.addWidget(body)

    def load_data(self):
        # Load Suppliers
        try:
            self.suppliers = self.purchase_service.list_suppliers(self.session.organization_id)
            self.supplier_combo.clear()
            for s in self.suppliers:
                self.supplier_combo.addItem(s.name, s.id)
        except Exception:
            self.suppliers = []

        # Load Products
        with self.purchase_service.transaction() as db:
            self.products = (
                db.query(Product)
                .filter_by(organization_id=self.session.organization_id, is_active=True)
                .order_by(Product.name.asc())
                .all()
            )

        if not self.line_items:
            self.add_line_item()

    def _open_new_supplier_dialog(self):
        dlg = CreateSupplierDialog(self, self.purchase_service, self.session)
        if dlg.exec() and dlg.created_supplier:
            self.load_data()
            idx = self.supplier_combo.findData(dlg.created_supplier.id)
            if idx >= 0:
                self.supplier_combo.setCurrentIndex(idx)

    def add_line_item(self):
        row_widget = QFrame()
        row_widget.setObjectName("LineItemRow")
        row_widget.setStyleSheet(
            "QFrame#LineItemRow { background-color: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 6px; padding: 4px; }"
        )
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(8, 6, 8, 6)
        row_layout.setSpacing(10)

        # Product dropdown
        prod_combo = QComboBox()
        prod_combo.setMinimumWidth(260)
        prod_combo.addItem("Select Product...", None)
        for p in self.products:
            sku_tag = f" [{p.sku}]" if p.sku else ""
            prod_combo.addItem(f"{p.name}{sku_tag}", p.id)

        # Quantity
        qty_spin = QSpinBox()
        qty_spin.setRange(1, 999999)
        qty_spin.setValue(10)
        qty_spin.setFixedWidth(80)

        # Cost Price
        cost_spin = QDoubleSpinBox()
        cost_spin.setRange(0, 10000000)
        cost_spin.setDecimals(2)
        cost_spin.setPrefix("Cost ₦ ")
        cost_spin.setValue(1000.00)
        cost_spin.setFixedWidth(130)

        # Selling Price
        sell_spin = QDoubleSpinBox()
        sell_spin.setRange(0, 10000000)
        sell_spin.setDecimals(2)
        sell_spin.setPrefix("Sell ₦ ")
        sell_spin.setValue(1300.00)
        sell_spin.setFixedWidth(130)

        # Line Total Label
        tot_lbl = QLabel("₦ 10,000.00")
        tot_lbl.setStyleSheet("font-weight: 700; color: #1E293B; font-size: 13px; min-width: 90px;")
        tot_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        # Remove button
        del_btn = QPushButton("✕")
        del_btn.setStyleSheet(
            "background-color: #FEE2E2; color: #EF4444; font-weight: bold; border-radius: 4px; padding: 4px 8px;"
        )
        del_btn.setToolTip("Remove Line")

        row_layout.addWidget(prod_combo, stretch=2)
        row_layout.addWidget(qty_spin)
        row_layout.addWidget(cost_spin)
        row_layout.addWidget(sell_spin)
        row_layout.addWidget(tot_lbl)
        row_layout.addWidget(del_btn)

        item_dict = {
            "widget": row_widget,
            "prod_combo": prod_combo,
            "qty_spin": qty_spin,
            "cost_spin": cost_spin,
            "sell_spin": sell_spin,
            "tot_lbl": tot_lbl,
        }
        self.line_items.append(item_dict)

        def _update_row_total():
            qty = qty_spin.value()
            cost = cost_spin.value()
            total = qty * cost
            tot_lbl.setText(f"₦ {total:,.2f}")
            self.calculate_totals()

        qty_spin.valueChanged.connect(_update_row_total)
        cost_spin.valueChanged.connect(_update_row_total)

        del_btn.clicked.connect(lambda: self.remove_line_item(item_dict))

        self.items_layout.addWidget(row_widget)
        _update_row_total()

    def remove_line_item(self, item_dict):
        if len(self.line_items) <= 1:
            return  # keep at least one line
        self.line_items.remove(item_dict)
        self.items_layout.removeWidget(item_dict["widget"])
        item_dict["widget"].deleteLater()
        self.calculate_totals()

    def calculate_totals(self):
        subtotal = Decimal("0.00")
        for it in self.line_items:
            qty = it["qty_spin"].value()
            cost = Decimal(str(it["cost_spin"].value()))
            subtotal += Decimal(qty) * cost

        disc = Decimal(str(self.discount_input.value()))
        grand_total = max(Decimal("0.00"), subtotal - disc)

        self.subtotal_lbl.setText(f"₦ {subtotal:,.2f}")
        self.grand_total_lbl.setText(f"₦ {grand_total:,.2f}")

    def on_submit(self):
        supplier_id = self.supplier_combo.currentData()
        if not supplier_id:
            self.err_lbl.setText("Please select a supplier.")
            self.supplier_combo.setFocus()
            return

        ref = self.ref_input.text().strip()
        if not ref:
            self.err_lbl.setText("Purchase reference is required.")
            self.ref_input.setFocus()
            return

        items_payload = []
        for it in self.line_items:
            prod_id = it["prod_combo"].currentData()
            if not prod_id:
                self.err_lbl.setText("Please select a product for all order lines.")
                return
            items_payload.append({
                "product_id": prod_id,
                "quantity_ordered": it["qty_spin"].value(),
                "purchase_price": str(it["cost_spin"].value()),
                "selling_price": str(it["sell_spin"].value()),
                "discount": "0.00",
            })

        try:
            self.purchase_service.create_purchase(
                user_session=self.session,
                supplier_id=supplier_id,
                purchase_reference=ref,
                purchase_date=self.date_input.date().toString(Qt.ISODate),
                items=items_payload,
                invoice_number=self.inv_input.text().strip() or None,
                discount_amount=str(self.discount_input.value()),
                notes=self.notes_input.text().strip(),
            )
            QMessageBox.information(
                self,
                "Purchase Order Created",
                f"Purchase order '{ref}' was created successfully.\nYou can now receive stock batches against this order.",
            )
            self.accept()
        except Exception as e:
            self.err_lbl.setText(f"Error: {str(e)}")


class ReceivePurchaseDialog(QDialog):
    """Modal dialog to receive batches against a purchase order."""

    def __init__(self, parent, purchase_service, session, purchase_id: str):
        super().__init__(parent)
        self.purchase_service = purchase_service
        self.session = session
        self.purchase_id = purchase_id
        self.details = None
        self.receive_rows = []

        self.setWindowTitle("Receive Inventory Stock")
        self.setMinimumSize(800, 560)
        self.init_ui()
        self.load_details()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.banner = DialogHeaderBanner(
            title="Receive Inventory Stock",
            subtitle="Assign batch numbers and expiry dates to add received stock to branch inventory",
            parent_dialog=self,
        )
        layout.addWidget(self.banner)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(24, 18, 24, 22)
        body_layout.setSpacing(14)

        # Invoice Number Header
        inv_box = QHBoxLayout()
        inv_box.addWidget(QLabel("Supplier Invoice #:"))
        self.inv_in = QLineEdit()
        self.inv_in.setPlaceholderText("Invoice # if provided on delivery...")
        inv_box.addWidget(self.inv_in)
        inv_box.addStretch()
        body_layout.addLayout(inv_box)

        # Scroll area for items
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)

        self.container = QWidget()
        self.items_layout = QVBoxLayout(self.container)
        self.items_layout.setContentsMargins(0, 0, 0, 0)
        self.items_layout.setSpacing(10)
        self.items_layout.setAlignment(Qt.AlignTop)

        self.scroll.setWidget(self.container)
        body_layout.addWidget(self.scroll, stretch=1)

        self.err_lbl = QLabel("")
        self.err_lbl.setStyleSheet("color: #EF4444; font-size: 12px; font-weight: 600;")
        body_layout.addWidget(self.err_lbl)

        btn_box = QHBoxLayout()
        btn_box.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("SecondaryBtn")
        cancel_btn.clicked.connect(self.reject)
        btn_box.addWidget(cancel_btn)

        self.submit_btn = QPushButton("Confirm Stock Receipt")
        self.submit_btn.setStyleSheet(
            "background-color: #10B981; color: white; font-weight: 700; padding: 9px 20px; border-radius: 6px;"
        )
        self.submit_btn.clicked.connect(self.on_submit)
        btn_box.addWidget(self.submit_btn)

        body_layout.addLayout(btn_box)
        layout.addWidget(body)

    def load_details(self):
        self.details = self.purchase_service.get_purchase_details(self.purchase_id)
        if not self.details:
            self.err_lbl.setText("Purchase order not found.")
            return

        self.banner.title_lbl.setText(f"Receive Stock — {self.details['purchase_reference']}")
        self.banner.sub_lbl.setText(f"Supplier: {self.details['supplier_name']} • Date: {self.details['purchase_date']}")
        if self.details.get("invoice_number"):
            self.inv_in.setText(self.details["invoice_number"])

        for it in self.details["items"]:
            rem = it["remaining_quantity"]
            if rem <= 0:
                continue

            card = QFrame()
            card.setStyleSheet("background-color: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 6px; padding: 8px;")
            card_layout = QGridLayout(card)
            card_layout.setSpacing(8)

            p_title = QLabel(f"📦 {it['product_name']} (Ordered: {it['quantity_ordered']}, Remaining: {rem})")
            p_title.setStyleSheet("font-weight: 700; color: #1E293B; font-size: 13px;")
            card_layout.addWidget(p_title, 0, 0, 1, 4)

            # Row 1: Quantity to receive, Batch Number
            qty_spin = QSpinBox()
            qty_spin.setRange(1, rem)
            qty_spin.setValue(rem)

            batch_in = QLineEdit(f"BN-{datetime.now().strftime('%Y%m%d')}-{random.randint(100, 999)}")
            batch_in.setPlaceholderText("Batch Number *")

            mfg_edit = QDateEdit()
            mfg_edit.setCalendarPopup(True)
            mfg_edit.setDate(QDate.currentDate())

            exp_edit = QDateEdit()
            exp_edit.setCalendarPopup(True)
            exp_edit.setDate(QDate.currentDate().addYears(2))

            card_layout.addWidget(QLabel("Qty to Receive:"), 1, 0)
            card_layout.addWidget(qty_spin, 1, 1)
            card_layout.addWidget(QLabel("Batch Number *:"), 1, 2)
            card_layout.addWidget(batch_in, 1, 3)

            card_layout.addWidget(QLabel("Mfg Date:"), 2, 0)
            card_layout.addWidget(mfg_edit, 2, 1)
            card_layout.addWidget(QLabel("Expiry Date *:"), 2, 2)
            card_layout.addWidget(exp_edit, 2, 3)

            self.receive_rows.append({
                "item_id": it["id"],
                "qty_spin": qty_spin,
                "batch_in": batch_in,
                "mfg_edit": mfg_edit,
                "exp_edit": exp_edit,
            })
            self.items_layout.addWidget(card)

    def on_submit(self):
        items_payload = []
        today_str = date.today().isoformat()
        for r in self.receive_rows:
            batch_no = r["batch_in"].text().strip()
            if not batch_no:
                self.err_lbl.setText("Batch number is required for all items being received.")
                r["batch_in"].setFocus()
                return

            mfg_str = r["mfg_edit"].date().toString(Qt.ISODate)
            exp_str = r["exp_edit"].date().toString(Qt.ISODate)
            if exp_str <= today_str:
                self.err_lbl.setText("Expiry date must be in the future.")
                r["exp_edit"].setFocus()
                return

            items_payload.append({
                "purchase_item_id": r["item_id"],
                "quantity_received": r["qty_spin"].value(),
                "batch_number": batch_no,
                "manufacturing_date": mfg_str,
                "expiry_date": exp_str,
                "update_selling_price": True,
            })

        try:
            self.purchase_service.receive_purchase(
                user_session=self.session,
                purchase_id=self.purchase_id,
                items=items_payload,
                invoice_number=self.inv_in.text().strip() or None,
            )
            QMessageBox.information(
                self,
                "Stock Received",
                "Inventory stock has been successfully received and posted into branch inventory!",
            )
            self.accept()
        except Exception as e:
            self.err_lbl.setText(f"Error receiving stock: {str(e)}")


class RecordPurchasePaymentDialog(QDialog):
    """Modal dialog to record a payment voucher for a supplier invoice."""

    def __init__(self, parent, purchase_service, session, purchase_id: str):
        super().__init__(parent)
        self.purchase_service = purchase_service
        self.session = session
        self.purchase_id = purchase_id
        self.details = None

        self.setWindowTitle("Record Supplier Payment")
        self.setMinimumWidth(460)
        self.init_ui()
        self.load_details()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.banner = DialogHeaderBanner(
            title="Record Payment Voucher",
            subtitle="Log supplier invoice payment and update outstanding balance",
            parent_dialog=self,
        )
        layout.addWidget(self.banner)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(24, 18, 24, 22)
        body_layout.setSpacing(12)

        self.info_lbl = QLabel("")
        self.info_lbl.setStyleSheet("font-size: 13px; color: #334155; font-weight: 600;")
        body_layout.addWidget(self.info_lbl)

        form_grid = QGridLayout()
        form_grid.setSpacing(10)

        self.method_combo = QComboBox()
        self.method_combo.addItems(["CASH", "BANK_TRANSFER", "CHEQUE", "POS_CARD"])

        self.amount_spin = QDoubleSpinBox()
        self.amount_spin.setRange(0.01, 100000000)
        self.amount_spin.setDecimals(2)
        self.amount_spin.setPrefix("₦ ")

        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDate(QDate.currentDate())

        self.ref_in = QLineEdit()
        self.ref_in.setPlaceholderText("Bank Ref / Cheque # / Slip #")

        form_grid.addWidget(QLabel("Payment Method:"), 0, 0)
        form_grid.addWidget(self.method_combo, 0, 1)

        form_grid.addWidget(QLabel("Amount (NGN) *:"), 1, 0)
        form_grid.addWidget(self.amount_spin, 1, 1)

        form_grid.addWidget(QLabel("Payment Date:"), 2, 0)
        form_grid.addWidget(self.date_edit, 2, 1)

        form_grid.addWidget(QLabel("Reference:"), 3, 0)
        form_grid.addWidget(self.ref_in, 3, 1)

        body_layout.addLayout(form_grid)

        self.err_lbl = QLabel("")
        self.err_lbl.setStyleSheet("color: #EF4444; font-size: 12px; font-weight: 600;")
        body_layout.addWidget(self.err_lbl)

        btn_box = QHBoxLayout()
        btn_box.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("SecondaryBtn")
        cancel_btn.clicked.connect(self.reject)
        btn_box.addWidget(cancel_btn)

        save_btn = QPushButton("Save Payment")
        save_btn.setStyleSheet(
            "background-color: #10B981; color: white; font-weight: 700; padding: 8px 18px; border-radius: 6px;"
        )
        save_btn.clicked.connect(self.on_save)
        btn_box.addWidget(save_btn)

        body_layout.addLayout(btn_box)
        layout.addWidget(body)

    def load_details(self):
        self.details = self.purchase_service.get_purchase_details(self.purchase_id)
        if not self.details:
            return
        total_val = self.details["total"]
        paid_val = sum(Decimal(str(p["amount"])) for p in self.details.get("payments", []))
        balance = max(Decimal("0.00"), total_val - paid_val)

        self.banner.title_lbl.setText(f"Record Payment — {self.details['purchase_reference']}")
        self.info_lbl.setText(
            f"Supplier: {self.details['supplier_name']} | Total: ₦ {total_val:,.2f} | Balance: ₦ {balance:,.2f}"
        )
        self.amount_spin.setValue(float(balance))

    def on_save(self):
        amt = self.amount_spin.value()
        if amt <= 0:
            self.err_lbl.setText("Payment amount must be greater than zero.")
            return

        try:
            self.purchase_service.record_payment(
                user_session=self.session,
                purchase_id=self.purchase_id,
                payment_method=self.method_combo.currentText(),
                amount=str(amt),
                payment_date=self.date_edit.date().toString(Qt.ISODate),
                reference=self.ref_in.text().strip() or None,
            )
            QMessageBox.information(
                self,
                "Payment Recorded",
                f"Payment voucher of ₦ {amt:,.2f} recorded successfully.",
            )
            self.accept()
        except Exception as e:
            self.err_lbl.setText(f"Error: {str(e)}")


class PurchasesWidget(QWidget):
    """
    Phase 8 Purchases & Stock Receiving UI widget.
    Displays purchase orders, receiving status, payment status, and allows PO creation, receiving & payment.
    """

    def __init__(self, db_manager, get_session_callable, parent=None):
        super().__init__(parent)
        self.db_manager = db_manager
        self.get_session = get_session_callable
        self.purchase_service = PurchaseService(db_manager)

        # Pagination & Data Cache
        self.all_purchases = []
        self.filtered_purchases = []
        self.current_page = 1
        self.page_size = 50
        self.total_pages = 1

        # Search debounce timer (150ms)
        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(150)
        self.search_timer.timeout.connect(self._apply_filter_and_render)

        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        # Header
        header_layout = QHBoxLayout()
        title_col = QVBoxLayout()
        title_col.setSpacing(4)

        title = QLabel("Purchases & Stock Receiving")
        title.setObjectName("PageHeader")
        subtitle = QLabel("Manage supplier purchase orders, invoice payments, and warehouse receipt status")
        subtitle.setObjectName("PageSubtitle")
        title_col.addWidget(title)
        title_col.addWidget(subtitle)
        header_layout.addLayout(title_col)
        header_layout.addStretch()

        self.create_po_btn = QPushButton("+ New Purchase Order")
        self.create_po_btn.setStyleSheet(
            "background-color: #10B981; color: white; font-weight: 700; padding: 9px 18px; border-radius: 6px;"
        )
        self.create_po_btn.clicked.connect(self._open_create_purchase_dialog)
        header_layout.addWidget(self.create_po_btn)

        self.receive_btn = QPushButton("📦 Receive Items")
        self.receive_btn.setStyleSheet(
            "background-color: #2563EB; color: white; font-weight: 700; padding: 9px 18px; border-radius: 6px;"
        )
        self.receive_btn.clicked.connect(self._on_receive_selected)
        header_layout.addWidget(self.receive_btn)

        self.pay_btn = QPushButton("💳 Record Payment")
        self.pay_btn.setStyleSheet(
            "background-color: #059669; color: white; font-weight: 700; padding: 9px 18px; border-radius: 6px;"
        )
        self.pay_btn.clicked.connect(self._on_pay_selected)
        header_layout.addWidget(self.pay_btn)

        self.refresh_btn = QPushButton("Refresh Data")
        self.refresh_btn.setObjectName("SecondaryBtn")
        self.refresh_btn.clicked.connect(self.refresh_data)
        header_layout.addWidget(self.refresh_btn)
        layout.addLayout(header_layout)

        # Search Bar
        search_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search purchases by reference, invoice number, or status...")
        self.search_input.textChanged.connect(lambda: self.search_timer.start())
        search_layout.addWidget(self.search_input)
        layout.addLayout(search_layout)

        # Table (Clean 6 columns)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels([
            "Reference",
            "Invoice #",
            "Purchase Date",
            "Total Amount (NGN)",
            "Receiving Status",
            "Payment Status",
        ])
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.Interactive)
        hdr.setSectionResizeMode(1, QHeaderView.Interactive)
        hdr.setSectionResizeMode(2, QHeaderView.Interactive)
        hdr.setSectionResizeMode(3, QHeaderView.Stretch)
        hdr.setSectionResizeMode(4, QHeaderView.Interactive)
        hdr.setSectionResizeMode(5, QHeaderView.Interactive)

        self.table.setColumnWidth(0, 160)
        self.table.setColumnWidth(1, 140)
        self.table.setColumnWidth(2, 130)
        self.table.setColumnWidth(4, 150)
        self.table.setColumnWidth(5, 140)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.cellDoubleClicked.connect(self._on_table_double_clicked)

        self.table.verticalHeader().setDefaultSectionSize(40)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table)

        # Pagination Bar
        pagination_layout = QHBoxLayout()
        pagination_layout.setSpacing(12)

        self.page_status_label = QLabel("Showing 0 purchases")
        self.page_status_label.setStyleSheet("font-size: 13px; color: #64748B; font-weight: 500;")
        pagination_layout.addWidget(self.page_status_label)

        pagination_layout.addStretch()

        page_size_lbl = QLabel("Show:")
        page_size_lbl.setStyleSheet("font-size: 12px; color: #64748B;")
        pagination_layout.addWidget(page_size_lbl)

        self.page_size_combo = QComboBox()
        self.page_size_combo.addItems(["25", "50", "100", "250", "All"])
        self.page_size_combo.setCurrentText("50")
        self.page_size_combo.currentTextChanged.connect(self._on_page_size_changed)
        pagination_layout.addWidget(self.page_size_combo)

        self.prev_page_btn = QPushButton("◀ Previous")
        self.prev_page_btn.setObjectName("SecondaryBtn")
        self.prev_page_btn.clicked.connect(self._prev_page)
        pagination_layout.addWidget(self.prev_page_btn)

        self.page_info_label = QLabel("Page 1 of 1")
        self.page_info_label.setStyleSheet("font-size: 13px; font-weight: 600; color: #334155; padding: 0 4px;")
        pagination_layout.addWidget(self.page_info_label)

        self.next_page_btn = QPushButton("Next ▶")
        self.next_page_btn.setObjectName("SecondaryBtn")
        self.next_page_btn.clicked.connect(self._next_page)
        pagination_layout.addWidget(self.next_page_btn)

        layout.addLayout(pagination_layout)

    def _open_create_purchase_dialog(self):
        session = self.get_session()
        if not session:
            return
        dlg = CreatePurchaseDialog(self, self.purchase_service, session)
        if dlg.exec():
            self.refresh_data()

    def _open_receive_dialog(self, purchase_id: str):
        session = self.get_session()
        if not session:
            return
        dlg = ReceivePurchaseDialog(self, self.purchase_service, session, purchase_id)
        if dlg.exec():
            self.refresh_data()

    def _open_payment_dialog(self, purchase_id: str):
        session = self.get_session()
        if not session:
            return
        dlg = RecordPurchasePaymentDialog(self, self.purchase_service, session, purchase_id)
        if dlg.exec():
            self.refresh_data()

    def _on_page_size_changed(self, text):
        if text == "All":
            self.page_size = 999999
        else:
            try:
                self.page_size = int(text)
            except ValueError:
                self.page_size = 50
        self.current_page = 1
        self._render_current_page()

    def _prev_page(self):
        if self.current_page > 1:
            self.current_page -= 1
            self._render_current_page()

    def _next_page(self):
        if self.current_page < self.total_pages:
            self.current_page += 1
            self._render_current_page()

    def refresh_data(self):
        session = self.get_session()
        if not session:
            return
        self.all_purchases = self.purchase_service.list_purchases(session.branch_id)
        self._apply_filter_and_render()

    def _apply_filter_and_render(self):
        query = self.search_input.text().strip().lower()
        if not query:
            self.filtered_purchases = list(self.all_purchases)
        else:
            self.filtered_purchases = [
                p for p in self.all_purchases
                if query in (p.purchase_reference or "").lower()
                or query in (p.invoice_number or "").lower()
                or query in (p.receiving_status or "").lower()
                or query in (p.payment_status or "").lower()
            ]
        self.current_page = 1
        self._render_current_page()

    def _render_current_page(self):
        total_count = len(self.filtered_purchases)
        self.total_pages = max(1, (total_count + self.page_size - 1) // self.page_size) if self.page_size > 0 else 1
        self.current_page = min(self.current_page, self.total_pages)

        start_idx = (self.current_page - 1) * self.page_size
        end_idx = min(start_idx + self.page_size, total_count)
        page_items = self.filtered_purchases[start_idx:end_idx]

        session = self.get_session()
        can_receive = session.has_permission(PermissionCode.STOCK_RECEIVE.value) if session else True

        self.table.setUpdatesEnabled(False)
        self.table.blockSignals(True)
        try:
            self.table.setRowCount(len(page_items))
            for idx, p in enumerate(page_items):
                self.table.setItem(idx, 0, QTableWidgetItem(p.purchase_reference))
                self.table.setItem(idx, 1, QTableWidgetItem(p.invoice_number or "-"))
                self.table.setItem(idx, 2, QTableWidgetItem(p.purchase_date))
                tot_item = QTableWidgetItem(f"{p.total:,.2f}")
                tot_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(idx, 3, tot_item)
                self.table.setItem(idx, 4, QTableWidgetItem(p.receiving_status))
                self.table.setItem(idx, 5, QTableWidgetItem(p.payment_status))
        finally:
            self.table.blockSignals(False)
            self.table.setUpdatesEnabled(True)

        if total_count == 0:
            self.page_status_label.setText("Showing 0 purchases")
        else:
            self.page_status_label.setText(f"Showing {start_idx + 1}–{end_idx} of {total_count} purchases")
        self.page_info_label.setText(f"Page {self.current_page} of {self.total_pages}")
        self.prev_page_btn.setEnabled(self.current_page > 1)
        self.next_page_btn.setEnabled(self.current_page < self.total_pages)

    def _on_receive_selected(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(
                self,
                "Selection Required",
                "Please click a row in the table to select a purchase order first."
            )
            return
        start_idx = (self.current_page - 1) * self.page_size
        idx = start_idx + row
        if 0 <= idx < len(self.filtered_purchases):
            p = self.filtered_purchases[idx]
            if p.receiving_status == ReceivingStatus.RECEIVED.value:
                QMessageBox.information(self, "Already Received", f"Purchase '{p.purchase_reference}' is already fully received.")
                return
            self._open_receive_dialog(p.id)

    def _on_pay_selected(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(
                self,
                "Selection Required",
                "Please click a row in the table to select a purchase order first."
            )
            return
        start_idx = (self.current_page - 1) * self.page_size
        idx = start_idx + row
        if 0 <= idx < len(self.filtered_purchases):
            p = self.filtered_purchases[idx]
            if p.payment_status == PaymentStatus.PAID.value:
                QMessageBox.information(self, "Already Paid", f"Purchase '{p.purchase_reference}' is already fully paid.")
                return
            self._open_payment_dialog(p.id)

    def _on_table_double_clicked(self, row, col):
        start_idx = (self.current_page - 1) * self.page_size
        idx = start_idx + row
        if 0 <= idx < len(self.filtered_purchases):
            p = self.filtered_purchases[idx]
            if p.receiving_status != ReceivingStatus.RECEIVED.value:
                self._open_receive_dialog(p.id)
            elif p.payment_status != PaymentStatus.PAID.value:
                self._open_payment_dialog(p.id)
