from decimal import Decimal
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont, QTextDocument
from PySide6.QtPrintSupport import QPrinterInfo, QPrinter, QPrintDialog
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QComboBox,
    QSpinBox,
    QDoubleSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QMessageBox,
    QInputDialog,
    QFrame,
    QHeaderView,
    QSplitter,
    QDialog,
)
from desktop.app.domain.pos_cart import POSCart
from desktop.app.ui.common.title_bar import DialogHeaderBanner
from desktop.app.ui.products.products_widget import create_price_cell_widget


class POSWidget(QWidget):
    """
    Point of Sale (POS) Checkout & Sales Terminal Widget.
    Features:
    - Real-time product search by name, generic name, SKU, or barcode scan
    - Instant live search results catalog showing price, barcode, and stock availability
    - Automatic price resolution & inline price configuration prompt for unpriced products
    - FEFO / FIFO automated batch deduction
    - Cash tender & change due calculator
    - Multi-payment support (CASH, POS_CARD, BANK_TRANSFER)
    - Thermal ESC/POS 80mm receipt generation and preview
    """

    def __init__(
        self,
        session,
        sales_service=None,
        product_service=None,
        pricing_service=None,
        inventory_service=None,
    ):
        super().__init__()
        self.session = session
        self.sales_service = sales_service
        self.product_service = product_service
        self.pricing_service = pricing_service
        self.inventory_service = inventory_service
        self.cart = POSCart()
        self._current_search_products = []

        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(100)
        self.search_timer.timeout.connect(lambda: self.refresh_search_results(self.search_input.text()))

        self.init_ui()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(24, 24, 24, 24)
        main_layout.setSpacing(16)

        # 1. Page Header
        header_layout = QHBoxLayout()
        title_col = QVBoxLayout()
        title_col.setSpacing(4)

        header_title = QLabel("Point of Sale (POS) Terminal")
        header_title.setObjectName("PageHeader")
        subtitle = QLabel("Fast barcode scanning, live catalog search, automated FEFO/FIFO batch allocation & thermal receipts")
        subtitle.setObjectName("PageSubtitle")
        title_col.addWidget(header_title)
        title_col.addWidget(subtitle)
        header_layout.addLayout(title_col)
        header_layout.addStretch()

        self.clear_cart_btn = QPushButton("🗑️ Clear Cart")
        self.clear_cart_btn.setObjectName("SecondaryBtn")
        self.clear_cart_btn.clicked.connect(self.on_clear_cart)
        header_layout.addWidget(self.clear_cart_btn)
        main_layout.addLayout(header_layout)

        # 2. Main Splitter Layout (Left: Search & Cart & Checkout, Right: Thermal Receipt)
        content_layout = QHBoxLayout()
        content_layout.setSpacing(18)

        # Left Column
        left_card = QFrame()
        left_card.setObjectName("MetricCard")
        left = QVBoxLayout(left_card)
        left.setContentsMargins(18, 18, 18, 18)
        left.setSpacing(14)

        # Search Bar Row
        search_box_layout = QVBoxLayout()
        search_box_layout.setSpacing(6)

        search_header = QHBoxLayout()
        search_lbl = QLabel("🔍 Product Search & Barcode Scan")
        search_lbl.setStyleSheet("font-size: 13.5px; font-weight: 800; color: #0F172A;")
        self.search_status_lbl = QLabel("(Search across Name, Generic Name, Brand, SKU & Barcode)")
        self.search_status_lbl.setStyleSheet("font-size: 12px; font-weight: 600; color: #334155;")
        search_header.addWidget(search_lbl)
        search_header.addWidget(self.search_status_lbl)
        search_header.addStretch()
        search_box_layout.addLayout(search_header)

        search_row = QHBoxLayout()
        search_row.setSpacing(10)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Scan barcode or search by product name, generic name, SKU...")
        self.search_input.setStyleSheet(
            "padding: 10px 14px; font-size: 13.5px; font-weight: 600; color: #0F172A; "
            "background-color: #FFFFFF; border: 1.5px solid #94A3B8; border-radius: 8px;"
        )
        self.search_input.textChanged.connect(self.on_search_text_changed)
        self.search_input.returnPressed.connect(self.on_barcode_or_enter_pressed)

        qty_label = QLabel("Qty:")
        qty_label.setStyleSheet("font-size: 13px; font-weight: 800; color: #0F172A;")
        self.qty_spin = QSpinBox()
        self.qty_spin.setRange(1, 10000)
        self.qty_spin.setValue(1)
        self.qty_spin.setFixedWidth(85)
        self.qty_spin.setFixedHeight(40)
        self.qty_spin.setStyleSheet(
            "font-size: 14px; font-weight: 700; color: #0F172A; background-color: #FFFFFF; "
            "border: 1.5px solid #94A3B8; border-radius: 6px; padding: 4px 8px;"
        )

        self.add_btn = QPushButton("+ Add Product")
        self.add_btn.setStyleSheet("padding: 10px 18px; font-size: 13px; font-weight: 800;")
        self.add_btn.clicked.connect(self.on_barcode_or_enter_pressed)

        search_row.addWidget(self.search_input, 4)
        search_row.addWidget(qty_label)
        search_row.addWidget(self.qty_spin)
        search_row.addWidget(self.add_btn)
        search_box_layout.addLayout(search_row)

        left.addLayout(search_box_layout)

        # Live Search Results / Catalog Table (collapsible / quick select)
        self.search_results_table = QTableWidget(0, 8)
        self.search_results_table.setHorizontalHeaderLabels(
            [
                "Product Name",
                "Generic Name",
                "Selling Price (NGN)",
                "Available Stock",
                "Shelf / Location",
                "SKU",
                "Barcode",
                "Action",
            ]
        )
        header_sr = self.search_results_table.horizontalHeader()
        header_sr.setSectionResizeMode(0, QHeaderView.Stretch)
        for i in range(1, 8):
            header_sr.setSectionResizeMode(i, QHeaderView.Interactive)
        self.search_results_table.setColumnWidth(1, 130)
        self.search_results_table.setColumnWidth(2, 135)
        self.search_results_table.setColumnWidth(3, 105)
        self.search_results_table.setColumnWidth(4, 115)
        self.search_results_table.setColumnWidth(5, 100)
        self.search_results_table.setColumnWidth(6, 110)
        self.search_results_table.setColumnWidth(7, 85)
        self.search_results_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.search_results_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.search_results_table.setSelectionMode(QTableWidget.SingleSelection)

        self.search_results_table.verticalHeader().setDefaultSectionSize(46)
        self.search_results_table.verticalHeader().setVisible(False)
        self.search_results_table.setMinimumHeight(160)
        self.search_results_table.setMaximumHeight(260)
        self.search_results_table.setAlternatingRowColors(True)
        self.search_results_table.cellDoubleClicked.connect(self.on_search_table_double_clicked)
        left.addWidget(self.search_results_table)

        # Cart Table Section
        cart_lbl_row = QHBoxLayout()
        cart_title = QLabel("🛒 Current Sale Cart")
        cart_title.setStyleSheet("font-size: 14px; font-weight: 800; color: #0F172A;")
        self.cart_items_count_lbl = QLabel("0 item(s)")
        self.cart_items_count_lbl.setStyleSheet("font-size: 12.5px; color: #334155; font-weight: 700;")
        cart_lbl_row.addWidget(cart_title)
        cart_lbl_row.addWidget(self.cart_items_count_lbl)
        cart_lbl_row.addStretch()
        left.addLayout(cart_lbl_row)

        self.cart_table = QTableWidget(0, 6)
        self.cart_table.setHorizontalHeaderLabels(
            ["Product Name", "SKU", "Qty", "Unit Price (NGN)", "Line Total (NGN)", "Remove"]
        )
        self.cart_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.cart_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.cart_table.setSelectionMode(QTableWidget.SingleSelection)
        header_cart = self.cart_table.horizontalHeader()
        header_cart.setSectionResizeMode(0, QHeaderView.Stretch)
        for i in range(1, 6):
            header_cart.setSectionResizeMode(i, QHeaderView.Interactive)
        self.cart_table.setColumnWidth(1, 120)
        self.cart_table.setColumnWidth(2, 70)
        self.cart_table.setColumnWidth(3, 130)
        self.cart_table.setColumnWidth(4, 130)
        self.cart_table.setColumnWidth(5, 75)

        self.cart_table.verticalHeader().setDefaultSectionSize(46)
        self.cart_table.verticalHeader().setVisible(False)
        self.cart_table.setAlternatingRowColors(True)
        left.addWidget(self.cart_table, stretch=1)

        # Checkout Control Bar (scoped selector so child labels don't inherit frame border/padding)
        checkout_bar = QFrame()
        checkout_bar.setObjectName("POSCheckoutBar")
        checkout_bar.setStyleSheet(
            "QFrame#POSCheckoutBar { background-color: #F8FAFC; border: 1.5px solid #CBD5E1; border-radius: 12px; } "
            "QFrame#POSCheckoutBar QLabel { border: none; background: transparent; padding: 0px; }"
        )
        checkout_layout = QVBoxLayout(checkout_bar)
        checkout_layout.setContentsMargins(18, 14, 18, 14)
        checkout_layout.setSpacing(14)

        row1 = QHBoxLayout()
        row1.setSpacing(12)

        strategy_label = QLabel("Strategy:")
        strategy_label.setStyleSheet("font-size: 13px; font-weight: 800; color: #0F172A;")
        self.strategy_combo = QComboBox()
        self.strategy_combo.addItems(["FEFO (Near-Expiry First)", "FIFO (Oldest Batch First)"])
        self.strategy_combo.setMinimumWidth(195)
        self.strategy_combo.setStyleSheet(
            "QComboBox { font-size: 13px; font-weight: 700; color: #0F172A; background-color: #FFFFFF; "
            "border: 1.5px solid #94A3B8; border-radius: 6px; padding: 6px 10px; }"
        )

        pay_label = QLabel("Payment:")
        pay_label.setStyleSheet("font-size: 13px; font-weight: 800; color: #0F172A;")
        self.payment_method_combo = QComboBox()
        self.payment_method_combo.addItems(["CASH", "POS_CARD", "BANK_TRANSFER"])
        self.payment_method_combo.setMinimumWidth(145)
        self.payment_method_combo.setStyleSheet(
            "QComboBox { font-size: 13px; font-weight: 700; color: #0F172A; background-color: #FFFFFF; "
            "border: 1.5px solid #94A3B8; border-radius: 6px; padding: 6px 10px; }"
        )
        self.payment_method_combo.currentTextChanged.connect(self.on_payment_method_changed)

        tendered_label = QLabel("Tendered (₦):")
        tendered_label.setStyleSheet("font-size: 13px; font-weight: 800; color: #0F172A;")
        self.tendered_input = QLineEdit()
        self.tendered_input.setPlaceholderText("0.00")
        self.tendered_input.setMinimumWidth(125)
        self.tendered_input.setMaximumWidth(150)
        self.tendered_input.setStyleSheet(
            "QLineEdit { font-size: 14px; font-weight: 800; color: #0F172A; background-color: #FFFFFF; "
            "border: 1.5px solid #94A3B8; border-radius: 6px; padding: 6px 10px; }"
        )
        self.tendered_input.textChanged.connect(self.calculate_change)

        self.change_label = QLabel("Change: ₦0.00")
        self.change_label.setStyleSheet(
            "font-size: 13.5px; font-weight: 800; color: #1D4ED8; background-color: #EFF6FF; "
            "border: 1px solid #BFDBFE; border-radius: 6px; padding: 6px 12px;"
        )

        row1.addWidget(strategy_label)
        row1.addWidget(self.strategy_combo)
        row1.addSpacing(6)
        row1.addWidget(pay_label)
        row1.addWidget(self.payment_method_combo)
        row1.addSpacing(6)
        row1.addWidget(tendered_label)
        row1.addWidget(self.tendered_input)
        row1.addSpacing(6)
        row1.addWidget(self.change_label)
        row1.addStretch()
        checkout_layout.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(16)

        self.total_label = QLabel("TOTAL: ₦0.00")
        self.total_label.setObjectName("MetricValueGreen")
        self.total_label.setStyleSheet(
            "font-size: 26px; font-weight: 900; color: #059669; border: none; background: transparent; padding: 0px;"
        )
        row2.addWidget(self.total_label)
        row2.addStretch()

        self.checkout_btn = QPushButton("💳 Complete Sale && Print Receipt")
        self.checkout_btn.setCursor(Qt.PointingHandCursor)
        self.checkout_btn.setStyleSheet(
            "QPushButton { background-color: #059669; color: #FFFFFF; padding: 13px 26px; font-size: 15px; "
            "font-weight: 800; border-radius: 8px; border: none; } "
            "QPushButton:hover { background-color: #047857; }"
        )
        self.checkout_btn.clicked.connect(self.on_checkout)
        row2.addWidget(self.checkout_btn)
        checkout_layout.addLayout(row2)

        left.addWidget(checkout_bar)
        content_layout.addWidget(left_card, 7)

        # Right Column: Thermal Receipt Preview & Printing Panel
        right_card = QFrame()
        right_card.setObjectName("MetricCard")
        right = QVBoxLayout(right_card)
        right.setContentsMargins(18, 18, 18, 18)
        right.setSpacing(10)

        receipt_title = QLabel("Thermal Receipt & Printing")
        receipt_title.setStyleSheet("font-size: 14px; font-weight: 800; color: #0F172A;")
        self.receipt_sub = QLabel("Format: 80mm ESC/POS layout")
        self.receipt_sub.setStyleSheet("font-size: 12px; font-weight: 600; color: #334155;")
        right.addWidget(receipt_title)
        right.addWidget(self.receipt_sub)

        # Connected / Available Printers Selector
        printer_select_layout = QHBoxLayout()
        printer_lbl = QLabel("Target Printer:")
        printer_lbl.setStyleSheet("font-size: 12.5px; font-weight: 800; color: #0F172A;")

        self.refresh_printers_btn = QPushButton("🔄")
        self.refresh_printers_btn.setFixedSize(28, 28)
        self.refresh_printers_btn.setToolTip("Scan for connected thermal, USB & network printers")
        self.refresh_printers_btn.clicked.connect(self.populate_printers)

        printer_select_layout.addWidget(printer_lbl)
        printer_select_layout.addStretch()
        printer_select_layout.addWidget(self.refresh_printers_btn)
        right.addLayout(printer_select_layout)

        self.printer_combo = QComboBox()
        self.printer_combo.setStyleSheet(
            "QComboBox { font-size: 12.5px; font-weight: 700; color: #0F172A; background-color: #FFFFFF; "
            "border: 1.5px solid #94A3B8; border-radius: 6px; padding: 6px 10px; }"
        )
        right.addWidget(self.printer_combo)

        # Receipt Text Preview
        self.receipt_preview = QTextEdit()
        self.receipt_preview.setReadOnly(True)
        self.receipt_preview.setFixedWidth(340)
        self.receipt_preview.setStyleSheet(
            "QTextEdit { font-family: 'Consolas', 'Courier New', monospace; font-size: 12.5px; font-weight: 600; "
            "color: #0F172A; background-color: #F8FAFC; border: 1.5px solid #94A3B8; border-radius: 8px; padding: 12px; line-height: 1.3; }"
        )
        right.addWidget(self.receipt_preview, stretch=1)

        # Print Controls
        receipt_btns = QVBoxLayout()
        receipt_btns.setSpacing(8)

        self.print_btn = QPushButton("🖨️ Print Receipt")
        self.print_btn.setStyleSheet(
            "background-color: #0284C7; color: white; padding: 10px 18px; font-size: 13px; font-weight: 800; border-radius: 8px;"
        )
        self.print_btn.clicked.connect(lambda: self.on_print_receipt(use_dialog=False))
        receipt_btns.addWidget(self.print_btn)

        secondary_btns = QHBoxLayout()
        secondary_btns.setSpacing(6)

        self.print_dialog_btn = QPushButton("⚙️ Dialog...")
        self.print_dialog_btn.setToolTip("Open print dialog for advanced paper size and printer settings")
        self.print_dialog_btn.clicked.connect(lambda: self.on_print_receipt(use_dialog=True))

        self.copy_receipt_btn = QPushButton("📋 Copy")
        self.copy_receipt_btn.clicked.connect(self.on_copy_receipt)

        self.new_sale_btn = QPushButton("✨ New Sale")
        self.new_sale_btn.clicked.connect(self.on_clear_cart)

        secondary_btns.addWidget(self.print_dialog_btn)
        secondary_btns.addWidget(self.copy_receipt_btn)
        secondary_btns.addWidget(self.new_sale_btn)
        receipt_btns.addLayout(secondary_btns)

        right.addLayout(receipt_btns)

        content_layout.addWidget(right_card, 3)
        main_layout.addLayout(content_layout)

        # Initial populate of printers & search catalog
        self.populate_printers()
        self.refresh_search_results("")

    def on_search_text_changed(self, text_val: str):
        self.search_timer.start()

    def refresh_search_results(self, query: str = ""):
        if not self.product_service or not self.session.organization_id:
            return
        clean_q = query.strip()
        results = self.product_service.search_products(
            self.session.organization_id,
            query=clean_q,
            branch_id=self.session.branch_id,
            limit=100,
        )
        self._current_search_products = results

        prod_ids = [p.id for p in results]
        prices_map = {}
        recent_prices_map = {}
        if self.pricing_service and prod_ids:
            try:
                prices_map = self.pricing_service.resolve_prices_bulk(
                    self.session.organization_id, prod_ids, self.session.branch_id
                )
                recent_prices_map = self.pricing_service.get_recently_updated_product_ids(
                    self.session.organization_id, hours=24
                )
            except Exception:
                pass

        stocks_map = {}
        shelves_map = {}
        if self.inventory_service and prod_ids and self.session.branch_id:
            try:
                stocks_map = self.inventory_service.get_stocks_bulk(
                    self.session.organization_id, self.session.branch_id, prod_ids
                )
                shelves_map = self.inventory_service.get_product_shelves_bulk(
                    self.session.organization_id, self.session.branch_id, prod_ids
                )
            except Exception:
                pass

        if clean_q:
            self.search_status_lbl.setText(f"Found {len(results)} match(es) for '{clean_q}'")
            self.search_status_lbl.setStyleSheet("font-size: 11px; color: #059669; font-weight: 600;")
        else:
            self.search_status_lbl.setText(f"Showing {len(results)} products")
            self.search_status_lbl.setStyleSheet("font-size: 11px; color: #64748B;")

        green_bg = QColor("#DCFCE7")
        self.search_results_table.setUpdatesEnabled(False)
        self.search_results_table.blockSignals(True)
        try:
            self.search_results_table.setRowCount(len(results))
            for row, p in enumerate(results):
                self.search_results_table.setRowHeight(row, 46)

                price_obj = prices_map.get(p.id)
                price_str = f"₦{price_obj.selling_price:,.2f}" if price_obj else "—"

                stock_qty = stocks_map.get(p.id, 0)
                stock_str = f"{stock_qty} in stock" if stock_qty > 0 else "Out of stock"
                shelf_str = shelves_map.get(p.id, "—")

                name_item = QTableWidgetItem(p.name)
                name_item.setToolTip(f"{p.name} (Generic: {p.generic_name or 'N/A'})")
                generic_item = QTableWidgetItem(p.generic_name or "-")
                price_item = QTableWidgetItem(price_str)
                price_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                stock_item = QTableWidgetItem(stock_str)
                shelf_item = QTableWidgetItem(shelf_str)
                if shelf_str != "—":
                    shelf_item.setForeground(QColor("#1D4ED8"))
                else:
                    shelf_item.setForeground(QColor("#94A3B8"))
                sku_item = QTableWidgetItem(p.sku)
                barcode_item = QTableWidgetItem(p.barcode or "-")
                action_bg_item = QTableWidgetItem("")

                if stock_qty > 0:
                    stock_item.setForeground(Qt.darkGreen)
                else:
                    stock_item.setForeground(Qt.red)

                update_info = recent_prices_map.get(p.id)
                if update_info:
                    for cell in (
                        name_item,
                        generic_item,
                        price_item,
                        stock_item,
                        shelf_item,
                        sku_item,
                        barcode_item,
                        action_bg_item,
                    ):
                        cell.setBackground(green_bg)

                self.search_results_table.setItem(row, 0, name_item)
                self.search_results_table.setItem(row, 1, generic_item)
                self.search_results_table.setItem(row, 2, price_item)
                self.search_results_table.setItem(row, 3, stock_item)
                self.search_results_table.setItem(row, 4, shelf_item)
                self.search_results_table.setItem(row, 5, sku_item)
                self.search_results_table.setItem(row, 6, barcode_item)
                self.search_results_table.setItem(row, 7, action_bg_item)

                if update_info and price_obj:
                    price_item.setText("")
                    p_widget = create_price_cell_widget(
                        self,
                        product_name=f"{p.name} ({p.sku})",
                        price_text=price_str,
                        update_info=update_info,
                        on_select_row=lambda r_idx=row: self.search_results_table.selectRow(r_idx),
                    )
                    self.search_results_table.setCellWidget(row, 2, p_widget)

                # Centered action button container
                cell_widget = QWidget()
                cell_widget.setStyleSheet("background-color: #DCFCE7;" if update_info else "background: transparent;")
                cell_layout = QHBoxLayout(cell_widget)
                cell_layout.setContentsMargins(4, 2, 4, 2)
                cell_layout.setSpacing(0)
                cell_layout.setAlignment(Qt.AlignCenter)
                add_btn = QPushButton("+ Add")
                add_btn.setObjectName("TableActionBtn")
                add_btn.setCursor(Qt.PointingHandCursor)
                add_btn.setFixedSize(68, 28)
                add_btn.setStyleSheet(
                    "QPushButton { background-color: #10B981; color: #FFFFFF; font-weight: 800; font-size: 11px; border-radius: 6px; border: none; } "
                    "QPushButton:hover { background-color: #059669; } "
                    "QPushButton:pressed { background-color: #047857; }"
                )
                add_btn.clicked.connect(lambda _, prod=p: self.add_product_to_cart(prod))
                cell_layout.addWidget(add_btn)
                self.search_results_table.setCellWidget(row, 7, cell_widget)
        finally:
            self.search_results_table.blockSignals(False)
            self.search_results_table.setUpdatesEnabled(True)

    def on_search_table_double_clicked(self, row: int, col: int):
        if 0 <= row < len(self._current_search_products):
            self.add_product_to_cart(self._current_search_products[row])

    def on_barcode_or_enter_pressed(self):
        query = self.search_input.text().strip()
        if not query:
            return
        results = self.product_service.search_products(
            self.session.organization_id,
            query=query,
            branch_id=self.session.branch_id,
        )
        if not results:
            QMessageBox.warning(self, "Not Found", f"No active product matched '{query}'.")
            return

        # If exact barcode or SKU match exists, pick it; otherwise pick results[0]
        matched_prod = results[0]
        for p in results:
            if p.barcode and p.barcode.strip() == query:
                matched_prod = p
                break
            if p.sku and p.sku.strip().lower() == query.lower():
                matched_prod = p
                break

        self.add_product_to_cart(matched_prod)

    def add_product_to_cart(self, prod):
        if not self.pricing_service:
            return
        price_obj = self.pricing_service.resolve_price(
            self.session.organization_id, prod.id, self.session.branch_id
        )
        if not price_obj:
            # Prompt user to configure selling price via frameless executive modal
            dlg = QDialog(self)
            dlg.setWindowTitle("Set Selling Price")
            dlg.setMinimumWidth(420)
            dlg_layout = QVBoxLayout(dlg)
            dlg_layout.setContentsMargins(0, 0, 0, 0)
            dlg_layout.setSpacing(0)

            banner = DialogHeaderBanner(
                title="Configure Selling Price",
                subtitle=f"Product: {prod.name}",
                parent_dialog=dlg,
            )
            dlg_layout.addWidget(banner)

            body = QWidget()
            body_layout = QVBoxLayout(body)
            body_layout.setContentsMargins(24, 18, 24, 20)
            body_layout.setSpacing(12)

            body_layout.addWidget(QLabel("Enter retail selling price (NGN):"))
            spin = QDoubleSpinBox()
            spin.setRange(0.01, 10000000.0)
            spin.setDecimals(2)
            spin.setPrefix("₦ ")
            spin.setValue(500.0)
            body_layout.addWidget(spin)

            btn_row = QHBoxLayout()
            btn_row.addStretch()
            cancel_btn = QPushButton("Cancel")
            cancel_btn.setObjectName("SecondaryBtn")
            cancel_btn.clicked.connect(dlg.reject)
            save_btn = QPushButton("Save Price")
            save_btn.setStyleSheet(
                "background-color: #10B981; color: white; font-weight: 700; padding: 8px 18px; border-radius: 6px;"
            )
            save_btn.clicked.connect(dlg.accept)
            btn_row.addWidget(cancel_btn)
            btn_row.addWidget(save_btn)
            body_layout.addLayout(btn_row)
            dlg_layout.addWidget(body)

            if dlg.exec() != QDialog.Accepted or spin.value() <= 0:
                return
            price_val = spin.value()
            try:
                self.pricing_service.set_price(
                    self.session,
                    product_id=prod.id,
                    selling_price=Decimal(str(price_val)),
                    branch_id=self.session.branch_id,
                )
                price_obj = self.pricing_service.resolve_price(
                    self.session.organization_id, prod.id, self.session.branch_id
                )
            except Exception as e:
                QMessageBox.critical(self, "Error Setting Price", str(e))
                return

        qty = self.qty_spin.value()
        self.cart.add_item(
            product_id=prod.id,
            product_name=prod.name,
            sku=prod.sku,
            quantity=qty,
            unit_price=price_obj.selling_price,
        )
        self.search_input.clear()
        self.qty_spin.setValue(1)
        self.refresh_cart_ui()
        self.refresh_search_results("")

    def remove_cart_item(self, index: int):
        self.cart.remove_item(index)
        self.refresh_cart_ui()

    def on_clear_cart(self):
        self.cart.clear()
        self.refresh_cart_ui()
        self.receipt_preview.clear()
        self.tendered_input.clear()
        self.change_label.setText("Change: ₦0.00")
        self.change_label.setStyleSheet(
            "font-size: 13.5px; font-weight: 800; color: #1D4ED8; background-color: #EFF6FF; "
            "border: 1px solid #BFDBFE; border-radius: 6px; padding: 6px 12px;"
        )

    def on_payment_method_changed(self, method: str):
        if method != "CASH":
            self.tendered_input.setText(f"{self.cart.total:.2f}")
        else:
            self.tendered_input.clear()
        self.calculate_change()

    def calculate_change(self):
        try:
            tendered_str = self.tendered_input.text().strip()
            if not tendered_str:
                self.change_label.setText("Change: ₦0.00")
                self.change_label.setStyleSheet(
                    "font-size: 13.5px; font-weight: 800; color: #1D4ED8; background-color: #EFF6FF; "
                    "border: 1px solid #BFDBFE; border-radius: 6px; padding: 6px 12px;"
                )
                return
            tendered = Decimal(tendered_str)
            change = tendered - self.cart.total
            if change >= 0:
                self.change_label.setText(f"Change: ₦{change:,.2f}")
                self.change_label.setStyleSheet(
                    "font-size: 13.5px; font-weight: 800; color: #065F46; background-color: #ECFDF5; "
                    "border: 1px solid #6EE7B7; border-radius: 6px; padding: 6px 12px;"
                )
            else:
                self.change_label.setText(f"Short: ₦{abs(change):,.2f}")
                self.change_label.setStyleSheet(
                    "font-size: 13.5px; font-weight: 800; color: #991B1B; background-color: #FEF2F2; "
                    "border: 1px solid #FCA5A5; border-radius: 6px; padding: 6px 12px;"
                )
        except Exception:
            self.change_label.setText("Change: ₦0.00")
            self.change_label.setStyleSheet(
                "font-size: 13.5px; font-weight: 800; color: #1D4ED8; background-color: #EFF6FF; "
                "border: 1px solid #BFDBFE; border-radius: 6px; padding: 6px 12px;"
            )

    def refresh_cart_ui(self):
        self.cart_table.setUpdatesEnabled(False)
        self.cart_table.blockSignals(True)
        try:
            self.cart_table.setRowCount(len(self.cart.items))
            for row, item in enumerate(self.cart.items):
                self.cart_table.setRowHeight(row, 46)
                self.cart_table.setItem(row, 0, QTableWidgetItem(item.product_name))
                self.cart_table.setItem(row, 1, QTableWidgetItem(item.sku))
                qty_it = QTableWidgetItem(str(item.quantity))
                qty_it.setTextAlignment(Qt.AlignCenter)
                self.cart_table.setItem(row, 2, qty_it)

                unit_price_it = QTableWidgetItem(f"{item.unit_price:,.2f}")
                unit_price_it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.cart_table.setItem(row, 3, unit_price_it)

                line_tot_it = QTableWidgetItem(f"{item.line_total:,.2f}")
                line_tot_it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.cart_table.setItem(row, 4, line_tot_it)

                # Centered remove button container
                cell_widget = QWidget()
                cell_widget.setStyleSheet("background: transparent;")
                cell_layout = QHBoxLayout(cell_widget)
                cell_layout.setContentsMargins(4, 2, 4, 2)
                cell_layout.setSpacing(0)
                cell_layout.setAlignment(Qt.AlignCenter)
                remove_btn = QPushButton("✕")
                remove_btn.setObjectName("TableDeleteBtn")
                remove_btn.setCursor(Qt.PointingHandCursor)
                remove_btn.setFixedSize(30, 28)
                remove_btn.setToolTip("Remove item from cart")
                remove_btn.clicked.connect(lambda _, idx=row: self.remove_cart_item(idx))
                cell_layout.addWidget(remove_btn)
                self.cart_table.setCellWidget(row, 5, cell_widget)
        finally:
            self.cart_table.blockSignals(False)
            self.cart_table.setUpdatesEnabled(True)

        self.cart_items_count_lbl.setText(f"{len(self.cart.items)} item(s)")
        self.total_label.setText(f"TOTAL: ₦{self.cart.total:,.2f}")
        self.calculate_change()

    def on_checkout(self):
        if not self.sales_service or not self.cart.items:
            QMessageBox.information(self, "Cart Empty", "Please add at least one product to the cart before checkout.")
            return

        pay_method = self.payment_method_combo.currentText()
        tendered_str = self.tendered_input.text().strip()
        tendered_amt = self.cart.total
        if pay_method == "CASH" and tendered_str:
            try:
                tendered_amt = Decimal(tendered_str)
                if tendered_amt < self.cart.total:
                    QMessageBox.warning(
                        self,
                        "Insufficient Payment",
                        f"Amount tendered (₦{tendered_amt:,.2f}) is less than total (₦{self.cart.total:,.2f}).",
                    )
                    return
            except Exception:
                pass

        try:
            strategy_val = "FEFO" if "FEFO" in self.strategy_combo.currentText() else "FIFO"
            res = self.sales_service.checkout_cart(
                self.session,
                self.cart,
                payments=[
                    {
                        "payment_method": pay_method,
                        "amount": str(self.cart.total),
                    }
                ],
                strategy=strategy_val,
            )
            receipt_text = res.get("receipt_text", "")
            self.receipt_preview.setPlainText(receipt_text)
            self.cart.clear()
            self.refresh_cart_ui()
            self.refresh_search_results("")
            QMessageBox.information(
                self,
                "Sale Completed",
                "Transaction completed successfully!\nReceipt generated and stock deducted via FEFO/FIFO.",
            )
        except Exception as exc:
            QMessageBox.critical(self, "Checkout Error", str(exc))

    def on_copy_receipt(self):
        text_val = self.receipt_preview.toPlainText()
        if text_val:
            from PySide6.QtWidgets import QApplication
            clipboard = QApplication.clipboard()
            clipboard.setText(text_val)
            QMessageBox.information(self, "Copied", "Receipt text copied to clipboard.")

    def populate_printers(self):
        """Scans the operating system for available thermal, network, and USB printers."""
        try:
            self.printer_combo.blockSignals(True)
            self.printer_combo.clear()
            available = QPrinterInfo.availablePrinterNames()
            default_name = QPrinterInfo.defaultPrinterName()

            if not available:
                self.printer_combo.addItem("No Printers Detected", None)
            else:
                for p_name in available:
                    label = f"🖨️ {p_name}" + (" (Default)" if p_name == default_name else "")
                    self.printer_combo.addItem(label, p_name)

                if default_name:
                    idx = self.printer_combo.findData(default_name)
                    if idx >= 0:
                        self.printer_combo.setCurrentIndex(idx)
        except Exception as e:
            pass
        finally:
            self.printer_combo.blockSignals(False)

    def on_print_receipt(self, use_dialog: bool = False):
        """Sends formatted receipt text to the selected printer or opens the standard print dialog."""
        receipt_text = self.receipt_preview.toPlainText().strip()
        if not receipt_text:
            QMessageBox.information(
                self,
                "No Receipt to Print",
                "There is currently no receipt in the preview. Please complete a checkout or load a sale to print.",
            )
            return

        target_printer_name = self.printer_combo.currentData()
        try:
            if target_printer_name:
                pinfo = QPrinterInfo.printerInfo(target_printer_name)
                printer = QPrinter(pinfo, QPrinter.HighResolution)
            else:
                printer = QPrinter(QPrinter.HighResolution)

            printer.setDocName("Pharmacy_Receipt")

            if use_dialog:
                dlg = QPrintDialog(printer, self)
                dlg.setWindowTitle("Print Pharmacy Receipt")
                if dlg.exec() != QDialog.Accepted:
                    return

            doc = QTextDocument()
            font = QFont("Courier New", 9)
            font.setStyleHint(QFont.Monospace)
            doc.setDefaultFont(font)
            doc.setPlainText(receipt_text)
            doc.print_(printer)

            self.receipt_sub.setText(f"✓ Sent to {target_printer_name or 'Default Printer'}")
            self.receipt_sub.setStyleSheet("font-size: 11px; color: #059669; font-weight: 700;")
        except Exception as err:
            QMessageBox.critical(self, "Printing Error", f"Unable to print receipt:\n{err}")
