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
    QScrollArea,
    QFrame,
    QGridLayout,
)
from PySide6.QtCore import Qt, QTimer
from desktop.app.services.transfer_service import TransferService
from desktop.app.ui.common.title_bar import DialogHeaderBanner
from shared.enums import TransferStatus


class CreateTransferDialog(QDialog):
    """Modal dialog to request an inter-branch stock transfer."""

    def __init__(self, parent, transfer_service, session):
        super().__init__(parent)
        self.transfer_service = transfer_service
        self.session = session
        self.branches = []
        self.transferable_batches = []
        self.line_items = []

        self.setWindowTitle("Request Inter-Branch Stock Transfer")
        self.setMinimumSize(800, 560)
        self.init_ui()
        self.load_data()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        banner = DialogHeaderBanner(
            title="Request Stock Transfer Requisition",
            subtitle="Request inventory transfer from current branch to another organization branch",
            parent_dialog=self,
        )
        layout.addWidget(banner)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(24, 18, 24, 22)
        body_layout.setSpacing(14)

        # Top Branch & Notes Grid
        top_grid = QGridLayout()
        top_grid.setSpacing(10)

        self.src_combo = QComboBox()
        self.src_combo.setMinimumWidth(240)
        self.src_combo.currentIndexChanged.connect(self._on_source_branch_changed)

        self.dest_combo = QComboBox()
        self.dest_combo.setMinimumWidth(240)

        self.notes_in = QLineEdit()
        self.notes_in.setPlaceholderText("Reason for transfer / urgency / requisition notes...")

        top_grid.addWidget(QLabel("Origin / Giving Branch (From) *:"), 0, 0)
        top_grid.addWidget(self.src_combo, 0, 1)

        top_grid.addWidget(QLabel("Destination / Receiving Branch (To) *:"), 1, 0)
        top_grid.addWidget(self.dest_combo, 1, 1)

        top_grid.addWidget(QLabel("Requisition Notes:"), 2, 0)
        top_grid.addWidget(self.notes_in, 2, 1)

        body_layout.addLayout(top_grid)

        # Line Items Header
        items_hdr = QHBoxLayout()
        items_title = QLabel("Items to Transfer")
        items_title.setStyleSheet("font-size: 15px; font-weight: 700; color: #1E293B;")
        items_hdr.addWidget(items_title)
        items_hdr.addStretch()

        add_line_btn = QPushButton("+ Add Product Line")
        add_line_btn.setStyleSheet(
            "background-color: #2563EB; color: white; font-weight: 600; padding: 6px 14px; border-radius: 5px;"
        )
        add_line_btn.clicked.connect(self.add_line_item)
        items_hdr.addWidget(add_line_btn)
        body_layout.addLayout(items_hdr)

        # Scroll area for items
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)

        self.container = QWidget()
        self.items_layout = QVBoxLayout(self.container)
        self.items_layout.setContentsMargins(0, 0, 0, 0)
        self.items_layout.setSpacing(8)
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

        submit_btn = QPushButton("Submit Transfer Request")
        submit_btn.setStyleSheet(
            "background-color: #10B981; color: white; font-weight: 700; padding: 9px 20px; border-radius: 6px;"
        )
        submit_btn.clicked.connect(self.on_submit)
        btn_box.addWidget(submit_btn)

        body_layout.addLayout(btn_box)
        layout.addWidget(body)

    def load_data(self):
        try:
            all_branches = self.transfer_service.list_branches(
                self.session.organization_id,
                exclude_branch_id=None,
            )
            self.branches = all_branches
            self.src_combo.blockSignals(True)
            self.src_combo.clear()
            self.dest_combo.clear()
            src_idx = 0
            dest_idx = 0
            for idx, b in enumerate(all_branches):
                label = f"{b.name} ({b.code})"
                self.src_combo.addItem(label, b.id)
                self.dest_combo.addItem(label, b.id)
                if str(b.id) == str(self.session.branch_id):
                    src_idx = idx
                elif dest_idx == 0:
                    dest_idx = idx
            if self.src_combo.count() > 0:
                self.src_combo.setCurrentIndex(src_idx)
            if self.dest_combo.count() > 0:
                self.dest_combo.setCurrentIndex(dest_idx if dest_idx != src_idx else max(0, (src_idx + 1) % self.dest_combo.count()))
            self.src_combo.blockSignals(False)
        except Exception:
            self.branches = []

        self._reload_batches_for_source()
        if not self.line_items:
            self.add_line_item()

    def _on_source_branch_changed(self):
        self._reload_batches_for_source()
        for it in self.line_items:
            combo = it["combo"]
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("Select Product & Batch...", None)
            for b in self.transferable_batches:
                combo.addItem(
                    f"{b['product_name']} [Batch: {b['batch_number']}, Avail: {b['available_quantity']}]",
                    b,
                )
            combo.blockSignals(False)
            it["avail_lbl"].setText("Avail: 0")

    def _reload_batches_for_source(self):
        src_id = self.src_combo.currentData() or self.session.branch_id
        try:
            self.transferable_batches = self.transfer_service.list_transferable_batches(src_id)
        except Exception:
            self.transferable_batches = []

    def add_line_item(self):
        row_widget = QFrame()
        row_widget.setStyleSheet(
            "background-color: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 6px; padding: 6px;"
        )
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(8, 4, 8, 4)
        row_layout.setSpacing(10)

        batch_combo = QComboBox()
        batch_combo.setMinimumWidth(320)
        batch_combo.addItem("Select Product & Batch...", None)
        for b in self.transferable_batches:
            batch_combo.addItem(
                f"{b['product_name']} [Batch: {b['batch_number']}, Avail: {b['available_quantity']}]",
                b,
            )

        avail_lbl = QLabel("Avail: 0")
        avail_lbl.setStyleSheet("font-weight: 600; color: #475569; min-width: 70px;")

        qty_spin = QSpinBox()
        qty_spin.setRange(1, 999999)
        qty_spin.setValue(1)
        qty_spin.setFixedWidth(90)

        del_btn = QPushButton("✕")
        del_btn.setStyleSheet(
            "background-color: #FEE2E2; color: #EF4444; font-weight: bold; border-radius: 4px; padding: 4px 8px;"
        )

        row_layout.addWidget(batch_combo, stretch=2)
        row_layout.addWidget(avail_lbl)
        row_layout.addWidget(QLabel("Qty:"))
        row_layout.addWidget(qty_spin)
        row_layout.addWidget(del_btn)

        item_dict = {
            "widget": row_widget,
            "combo": batch_combo,
            "avail_lbl": avail_lbl,
            "qty_spin": qty_spin,
        }
        self.line_items.append(item_dict)

        def _on_batch_selected(idx):
            data = batch_combo.itemData(idx)
            if data:
                # Calculate total available across all batches of this product at the source branch
                prod_id = data["product_id"]
                total_prod_avail = sum(
                    b["available_quantity"]
                    for b in self.transferable_batches
                    if b["product_id"] == prod_id
                )
                batch_avail = data["available_quantity"]
                if total_prod_avail > batch_avail:
                    avail_lbl.setText(f"Batch: {batch_avail} (Total: {total_prod_avail})")
                else:
                    avail_lbl.setText(f"Avail: {batch_avail}")
                qty_spin.setRange(1, max(1, total_prod_avail))
            else:
                avail_lbl.setText("Avail: 0")

        batch_combo.currentIndexChanged.connect(_on_batch_selected)
        del_btn.clicked.connect(lambda: self.remove_line_item(item_dict))

        self.items_layout.addWidget(row_widget)

    def remove_line_item(self, item_dict):
        if len(self.line_items) <= 1:
            return
        self.line_items.remove(item_dict)
        self.items_layout.removeWidget(item_dict["widget"])
        item_dict["widget"].deleteLater()

    def on_submit(self):
        src_id = self.src_combo.currentData() or self.session.branch_id
        dest_id = self.dest_combo.currentData()
        if not dest_id:
            self.err_lbl.setText("Please select a destination branch.")
            return
        if str(src_id) == str(dest_id):
            self.err_lbl.setText("Origin and Destination branches cannot be the same.")
            return

        items_payload = []
        for it in self.line_items:
            b_data = it["combo"].currentData()
            if not b_data:
                self.err_lbl.setText("Please select a product batch for all lines.")
                return
            items_payload.append({
                "product_id": b_data["product_id"],
                "batch_id": b_data["batch_id"],
                "quantity": it["qty_spin"].value(),
            })

        try:
            self.transfer_service.create_transfer(
                user_session=self.session,
                destination_branch_id=dest_id,
                source_branch_id=src_id,
                items=items_payload,
                notes=self.notes_in.text().strip(),
            )
            QMessageBox.information(
                self,
                "Transfer Requisition Created",
                "Stock transfer request has been successfully created and queued for approval.",
            )
            self.accept()
        except Exception as e:
            self.err_lbl.setText(f"Error: {str(e)}")


class ApproveTransferDialog(QDialog):
    """
    Modal dialog shown when approving a transfer request so the giving branch can
    choose which batch to give (or auto-allocate FEFO across multiple batches) when
    a requested product has multiple batches in stock.
    """

    def __init__(self, parent, transfer_service, session, transfer_data: dict | str):
        super().__init__(parent)
        self.transfer_service = transfer_service
        self.session = session
        if isinstance(transfer_data, str):
            self.transfer_data = self.transfer_service.get_transfer(transfer_data) or {"id": transfer_data, "items": []}
        else:
            self.transfer_data = transfer_data
        self.batch_overrides: dict[str, str] = {}
        self.combo_map: dict[str, QComboBox] = {}

        self.setWindowTitle("Approve Stock Transfer & Select Batch(es)")
        self.setMinimumWidth(680)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        ref = self.transfer_data.get("id", "")[:8].upper()
        src_name = self.transfer_data.get("source_branch_name", "Origin Branch")
        dst_name = self.transfer_data.get("destination_branch_name", "Destination Branch")

        banner = DialogHeaderBanner(
            title=f"Approve Transfer #{ref} — Batch Allocation",
            subtitle=f"From {src_name}  ➔  To {dst_name}",
            parent_dialog=self,
        )
        layout.addWidget(banner)

        body = QWidget()
        body.setStyleSheet("background-color: #FFFFFF; color: #0F172A;")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(24, 18, 24, 22)
        body_layout.setSpacing(14)

        info_lbl = QLabel(
            "Select which batch of each product to give for this transfer, or keep "
            "<b>Auto-Allocate (FEFO)</b> to automatically fulfill across your available batches:"
        )
        info_lbl.setWordWrap(True)
        info_lbl.setStyleSheet("font-size: 12.5px; color: #334155;")
        body_layout.addWidget(info_lbl)

        src_branch_id = self.transfer_data.get("source_branch_id") or self.session.branch_id
        avail_batches = self.transfer_service.list_transferable_batches(src_branch_id)
        session_batches = (
            self.transfer_service.list_transferable_batches(self.session.branch_id)
            if self.session.branch_id and self.session.branch_id != src_branch_id
            else avail_batches
        )

        for it in self.transfer_data.get("items", []):
            item_id = it["id"]
            prod_id = it["product_id"]
            prod_name = it.get("product_name") or prod_id[:8]
            req_batch_id = it.get("batch_id", "")
            req_qty = it.get("quantity", 0)

            prod_batches = [b for b in avail_batches if b["product_id"] == prod_id]
            if not prod_batches and session_batches:
                prod_batches = [b for b in session_batches if b["product_id"] == prod_id]
            total_avail = sum(b["available_quantity"] for b in prod_batches)

            card = QFrame()
            card.setStyleSheet(
                "QFrame { background-color: #F8FAFC; border: 1px solid #CBD5E1; border-radius: 8px; } "
                "QLabel { border: none; background: transparent; }"
            )
            c_layout = QVBoxLayout(card)
            c_layout.setContentsMargins(14, 10, 14, 10)
            c_layout.setSpacing(6)

            top_row = QHBoxLayout()
            p_lbl = QLabel(f"💊  {prod_name}")
            p_lbl.setStyleSheet("font-size: 13.5px; font-weight: 800; color: #0F172A;")
            q_lbl = QLabel(f"Requested Qty: {req_qty}   |   Total Available Across Batches: {total_avail}")
            q_lbl.setStyleSheet("font-size: 12.5px; font-weight: 700; color: #059669;")
            top_row.addWidget(p_lbl)
            top_row.addStretch()
            top_row.addWidget(q_lbl)
            c_layout.addLayout(top_row)

            combo = QComboBox()
            combo.setStyleSheet(
                "QComboBox { font-size: 13px; font-weight: 600; color: #0F172A; background-color: #FFFFFF; "
                "border: 1px solid #94A3B8; border-radius: 6px; padding: 6px 10px; }"
            )
            combo.addItem(
                f"✨ Auto-Allocate FEFO Across Available Batches (Total Available: {total_avail})",
                "",
            )
            selected_index = 0
            for idx, b in enumerate(prod_batches, start=1):
                exp = (b.get("expiry_date") or "")[:10]
                combo.addItem(
                    f"Batch: {b['batch_number']}  —  Available: {b['available_quantity']}  (Exp: {exp})",
                    b["batch_id"],
                )
                if b["batch_id"] == req_batch_id and b["available_quantity"] >= req_qty:
                    selected_index = idx
            combo.setCurrentIndex(selected_index)
            self.combo_map[item_id] = combo
            c_layout.addWidget(combo)

            body_layout.addWidget(card)

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("SecondaryBtn")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        approve_btn = QPushButton("✓ Confirm & Approve Transfer")
        approve_btn.setStyleSheet(
            "background-color: #059669; color: white; font-weight: 800; padding: 9px 20px; border-radius: 6px;"
        )
        approve_btn.clicked.connect(self._on_confirm)
        btn_row.addWidget(approve_btn)

        body_layout.addLayout(btn_row)
        layout.addWidget(body)

    def _on_confirm(self):
        for item_id, combo in self.combo_map.items():
            chosen_batch = combo.currentData()
            if chosen_batch:
                self.batch_overrides[item_id] = str(chosen_batch)
        self.accept()



class TransfersWidget(QWidget):
    """
    Phase 10 Stock Transfers UI widget.
    Displays stock transfers between branches, status, and allows requesting, approving, dispatching, receiving, and cancelling.
    """

    def __init__(self, db_manager, get_session_callable, parent=None):
        super().__init__(parent)
        self.db_manager = db_manager
        self.get_session = get_session_callable
        self.transfer_service = TransferService(db_manager)

        # Pagination & Data Cache
        self.all_transfers = []
        self.filtered_transfers = []
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

        header_layout = QHBoxLayout()
        title_col = QVBoxLayout()
        title_col.setSpacing(4)

        title = QLabel("Stock Transfers")
        title.setObjectName("PageHeader")
        subtitle = QLabel("Inter-branch inventory requisition, dispatch tracking, receipt confirmation & transit status")
        subtitle.setObjectName("PageSubtitle")
        title_col.addWidget(title)
        title_col.addWidget(subtitle)
        header_layout.addLayout(title_col)
        header_layout.addStretch()

        self.create_req_btn = QPushButton("+ Request Transfer")
        self.create_req_btn.setStyleSheet(
            "background-color: #10B981; color: white; font-weight: 700; padding: 9px 18px; border-radius: 6px;"
        )
        self.create_req_btn.clicked.connect(self._open_create_transfer_dialog)
        header_layout.addWidget(self.create_req_btn)

        self.appr_btn = QPushButton("✓ Approve")
        self.appr_btn.setStyleSheet(
            "background-color: #059669; color: white; font-weight: 700; padding: 9px 18px; border-radius: 6px;"
        )
        self.appr_btn.clicked.connect(self._on_approve_selected)
        header_layout.addWidget(self.appr_btn)

        self.dispatch_btn = QPushButton("🚚 Dispatch")
        self.dispatch_btn.setStyleSheet(
            "background-color: #2563EB; color: white; font-weight: 700; padding: 9px 18px; border-radius: 6px;"
        )
        self.dispatch_btn.clicked.connect(self._on_dispatch_selected)
        header_layout.addWidget(self.dispatch_btn)

        self.receive_btn = QPushButton("📥 Receive")
        self.receive_btn.setStyleSheet(
            "background-color: #0D9488; color: white; font-weight: 700; padding: 9px 18px; border-radius: 6px;"
        )
        self.receive_btn.clicked.connect(self._on_receive_selected)
        header_layout.addWidget(self.receive_btn)

        self.cancel_btn = QPushButton("✗ Cancel")
        self.cancel_btn.setStyleSheet(
            "background-color: #EF4444; color: white; font-weight: 700; padding: 9px 18px; border-radius: 6px;"
        )
        self.cancel_btn.clicked.connect(self._on_cancel_selected)
        header_layout.addWidget(self.cancel_btn)

        self.refresh_btn = QPushButton("Refresh Data")
        self.refresh_btn.setObjectName("SecondaryBtn")
        self.refresh_btn.clicked.connect(self.refresh_data)
        header_layout.addWidget(self.refresh_btn)
        layout.addLayout(header_layout)

        # Search Bar
        search_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search transfers by reference, origin, destination, status, or notes...")
        self.search_input.textChanged.connect(lambda: self.search_timer.start())
        search_layout.addWidget(self.search_input)
        layout.addLayout(search_layout)

        # Table (Clean 7 columns)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels([
            "Transfer Reference",
            "Origin Branch",
            "Destination Branch",
            "Transfer Status",
            "Requested At",
            "Items Included",
            "Requisition Notes",
        ])
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.Interactive)
        hdr.setSectionResizeMode(1, QHeaderView.Interactive)
        hdr.setSectionResizeMode(2, QHeaderView.Interactive)
        hdr.setSectionResizeMode(3, QHeaderView.Interactive)
        hdr.setSectionResizeMode(4, QHeaderView.Interactive)
        hdr.setSectionResizeMode(5, QHeaderView.Interactive)
        hdr.setSectionResizeMode(6, QHeaderView.Stretch)

        self.table.setColumnWidth(0, 160)
        self.table.setColumnWidth(1, 150)
        self.table.setColumnWidth(2, 150)
        self.table.setColumnWidth(3, 130)
        self.table.setColumnWidth(4, 140)
        self.table.setColumnWidth(5, 120)
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

        self.page_status_label = QLabel("Showing 0 transfers")
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

    def _open_create_transfer_dialog(self):
        session = self.get_session()
        if not session:
            return
        dlg = CreateTransferDialog(self, self.transfer_service, session)
        if dlg.exec():
            self.refresh_data()

    def _approve_transfer(self, transfer_id: str):
        session = self.get_session()
        if not session:
            return
        dlg = ApproveTransferDialog(self, self.transfer_service, session, transfer_id)
        if not dlg.exec():
            return
        try:
            self.transfer_service.approve_transfer(
                session, transfer_id, batch_overrides=dlg.batch_overrides
            )
            QMessageBox.information(self, "Transfer Approved", "Stock transfer request approved and inventory reserved.")
            self.refresh_data()
        except Exception as e:
            QMessageBox.critical(self, "Approval Failed", str(e))

    def _dispatch_transfer(self, transfer_id: str):
        session = self.get_session()
        if not session:
            return
        try:
            self.transfer_service.dispatch_transfer(session, transfer_id)
            QMessageBox.information(self, "Transfer Dispatched", "Stock dispatched from source branch and marked in-transit.")
            self.refresh_data()
        except Exception as e:
            QMessageBox.critical(self, "Dispatch Failed", str(e))

    def _receive_transfer(self, transfer_id: str):
        session = self.get_session()
        if not session:
            return
        try:
            self.transfer_service.receive_transfer(session, transfer_id)
            QMessageBox.information(self, "Transfer Received", "Stock received and added to destination branch inventory.")
            self.refresh_data()
        except Exception as e:
            QMessageBox.critical(self, "Receipt Failed", str(e))

    def _cancel_transfer(self, transfer_id: str):
        session = self.get_session()
        if not session:
            return
        try:
            self.transfer_service.cancel_transfer(session, transfer_id)
            self.refresh_data()
        except Exception as e:
            QMessageBox.critical(self, "Cancel Failed", str(e))

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
        self.all_transfers = self.transfer_service.list_transfers(session.branch_id)
        self._apply_filter_and_render()

    def _apply_filter_and_render(self):
        query = self.search_input.text().strip().lower()
        if not query:
            self.filtered_transfers = list(self.all_transfers)
        else:
            self.filtered_transfers = [
                t for t in self.all_transfers
                if query in (t.get('id') or "").lower()
                or query in (t.get('source_branch_name') or "").lower()
                or query in (t.get('destination_branch_name') or "").lower()
                or query in (t.get('status') or "").lower()
                or query in (t.get('notes') or "").lower()
            ]
        self.current_page = 1
        self._render_current_page()

    def _render_current_page(self):
        total_count = len(self.filtered_transfers)
        self.total_pages = max(1, (total_count + self.page_size - 1) // self.page_size) if self.page_size > 0 else 1
        self.current_page = min(self.current_page, self.total_pages)

        start_idx = (self.current_page - 1) * self.page_size
        end_idx = min(start_idx + self.page_size, total_count)
        page_items = self.filtered_transfers[start_idx:end_idx]

        session = self.get_session()

        self.table.setUpdatesEnabled(False)
        self.table.blockSignals(True)
        try:
            self.table.setRowCount(len(page_items))
            for idx, t in enumerate(page_items):
                tid = t['id']
                status_val = t.get('status', '')

                self.table.setItem(idx, 0, QTableWidgetItem(tid[:8].upper()))
                self.table.setItem(idx, 1, QTableWidgetItem(t.get('source_branch_name') or t.get('source_branch_id', '')[:8]))
                self.table.setItem(idx, 2, QTableWidgetItem(t.get('destination_branch_name') or t.get('destination_branch_id', '')[:8]))
                self.table.setItem(idx, 3, QTableWidgetItem(status_val))
                self.table.setItem(idx, 4, QTableWidgetItem(str(t.get('requested_at', ''))[:16]))
                self.table.setItem(idx, 5, QTableWidgetItem(f"{len(t.get('items', []))} item(s)"))
                self.table.setItem(idx, 6, QTableWidgetItem(t.get('notes') or "-"))
        finally:
            self.table.blockSignals(False)
            self.table.setUpdatesEnabled(True)

        if total_count == 0:
            self.page_status_label.setText("Showing 0 transfers")
        else:
            self.page_status_label.setText(f"Showing {start_idx + 1}–{end_idx} of {total_count} transfers")
        self.page_info_label.setText(f"Page {self.current_page} of {self.total_pages}")
        self.prev_page_btn.setEnabled(self.current_page > 1)
        self.next_page_btn.setEnabled(self.current_page < self.total_pages)

    def _get_selected_transfer(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(
                self,
                "Selection Required",
                "Please click a row in the table to select a transfer first."
            )
            return None
        start_idx = (self.current_page - 1) * self.page_size
        idx = start_idx + row
        if 0 <= idx < len(self.filtered_transfers):
            return self.filtered_transfers[idx]
        return None

    def _on_approve_selected(self):
        t = self._get_selected_transfer()
        if not t:
            return
        if t.get('status') != TransferStatus.REQUESTED.value:
            QMessageBox.information(self, "Invalid Status", f"Only REQUESTED transfers can be approved. Current status: {t.get('status')}")
            return
        self._approve_transfer(t['id'])

    def _on_dispatch_selected(self):
        t = self._get_selected_transfer()
        if not t:
            return
        if t.get('status') != TransferStatus.APPROVED.value:
            QMessageBox.information(self, "Invalid Status", f"Only APPROVED transfers can be dispatched. Current status: {t.get('status')}")
            return
        self._dispatch_transfer(t['id'])

    def _on_receive_selected(self):
        t = self._get_selected_transfer()
        if not t:
            return
        if t.get('status') not in (TransferStatus.DISPATCHED.value, TransferStatus.IN_TRANSIT.value):
            QMessageBox.information(self, "Invalid Status", f"Only DISPATCHED or IN_TRANSIT transfers can be received. Current status: {t.get('status')}")
            return
        self._receive_transfer(t['id'])

    def _on_cancel_selected(self):
        t = self._get_selected_transfer()
        if not t:
            return
        if t.get('status') != TransferStatus.REQUESTED.value:
            QMessageBox.information(self, "Invalid Status", f"Only REQUESTED transfers can be cancelled. Current status: {t.get('status')}")
            return
        self._cancel_transfer(t['id'])

    def _on_table_double_clicked(self, row, col):
        start_idx = (self.current_page - 1) * self.page_size
        idx = start_idx + row
        if 0 <= idx < len(self.filtered_transfers):
            t = self.filtered_transfers[idx]
            status_val = t.get('status', '')
            if status_val == TransferStatus.REQUESTED.value:
                self._approve_transfer(t['id'])
            elif status_val == TransferStatus.APPROVED.value:
                self._dispatch_transfer(t['id'])
            elif status_val in (TransferStatus.DISPATCHED.value, TransferStatus.IN_TRANSIT.value):
                self._receive_transfer(t['id'])
