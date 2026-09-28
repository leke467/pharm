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
from desktop.app.services.stock_count_service import StockCountService
from desktop.app.ui.common.title_bar import DialogHeaderBanner
from shared.enums import PermissionCode, StockCountStatus


class StartStockCountDialog(QDialog):
    """Modal dialog to initiate a new inventory count session."""

    def __init__(self, parent, stock_count_service, session):
        super().__init__(parent)
        self.stock_count_service = stock_count_service
        self.session = session

        self.setWindowTitle("Start Stock Count Audit")
        self.setMinimumWidth(480)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Executive Branded Header Banner
        banner = DialogHeaderBanner(
            title="Initiate Stock Count Session",
            subtitle="Select audit scope & physical inventory verification objectives",
            parent_dialog=self,
        )
        layout.addWidget(banner)

        # Form Body Container
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(24, 20, 24, 24)
        body_layout.setSpacing(16)

        grid = QGridLayout()
        grid.setSpacing(12)

        self.type_combo = QComboBox()
        self.type_combo.addItems([
            "FULL_BRANCH",
            "CYCLE_COUNT",
            "HIGH_VALUE",
            "SPOT_CHECK",
        ])

        self.shelf_combo = QComboBox()
        self.shelf_combo.addItem("All Shelves (Full Branch)", None)
        try:
            locs = self.stock_count_service.inventory_service.list_storage_locations(
                self.session.organization_id,
                self.session.branch_id,
            )
            for loc in locs:
                self.shelf_combo.addItem(f"🗄️ {loc.name} ({loc.location_type})", loc.id)
        except Exception:
            pass

        self.notes_in = QLineEdit()
        self.notes_in.setPlaceholderText("e.g. End-of-month audit / Shelf A1 cycle count")

        grid.addWidget(QLabel("Audit Type *:"), 0, 0)
        grid.addWidget(self.type_combo, 0, 1)
        grid.addWidget(QLabel("Shelf / Location Scope:"), 1, 0)
        grid.addWidget(self.shelf_combo, 1, 1)
        grid.addWidget(QLabel("Session Notes:"), 2, 0)
        grid.addWidget(self.notes_in, 2, 1)

        body_layout.addLayout(grid)

        self.err_lbl = QLabel("")
        self.err_lbl.setStyleSheet("color: #EF4444; font-size: 12px; font-weight: 600;")
        body_layout.addWidget(self.err_lbl)

        btn_box = QHBoxLayout()
        btn_box.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("SecondaryBtn")
        cancel_btn.clicked.connect(self.reject)
        btn_box.addWidget(cancel_btn)

        start_btn = QPushButton("🚀 Start Audit Session")
        start_btn.setStyleSheet(
            "background-color: #10B981; color: white; font-weight: 700; padding: 9px 22px; border-radius: 6px; font-size: 13px;"
        )
        start_btn.clicked.connect(self.on_start)
        btn_box.addWidget(start_btn)

        body_layout.addLayout(btn_box)
        layout.addWidget(body)

    def on_start(self):
        try:
            self.stock_count_service.start_stock_count(
                user_session=self.session,
                count_type=self.type_combo.currentText(),
                storage_location_id=self.shelf_combo.currentData(),
                notes=self.notes_in.text().strip(),
            )
            QMessageBox.information(
                self,
                "Stock Count Session Started",
                "New inventory count session is now active.\nYou can now record physical counts against inventory batches.",
            )
            self.accept()
        except Exception as e:
            self.err_lbl.setText(f"Error: {str(e)}")


class RecordPhysicalCountsDialog(QDialog):
    """Modal dialog to enter counted quantities against active inventory batches."""

    def __init__(self, parent, stock_count_service, session, stock_count_id: str):
        super().__init__(parent)
        self.stock_count_service = stock_count_service
        self.session = session
        self.stock_count_id = stock_count_id
        self.details = None
        self.count_rows = []

        self.setWindowTitle("Record Physical Stock Counts")
        self.setMinimumSize(860, 600)
        self.init_ui()
        self.load_data()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.banner = DialogHeaderBanner(
            title="Physical Stock Count Entry",
            subtitle="Enter verified quantities found on pharmacy shelves & warehouse racks",
            parent_dialog=self,
        )
        layout.addWidget(self.banner)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(24, 16, 24, 20)
        body_layout.setSpacing(14)

        # Scroll area for count rows
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

        # Notes
        notes_box = QHBoxLayout()
        notes_box.addWidget(QLabel("Submission Notes:"))
        self.submit_notes_in = QLineEdit()
        self.submit_notes_in.setPlaceholderText("Auditor remarks, damaged items notes, etc.")
        notes_box.addWidget(self.submit_notes_in)
        body_layout.addLayout(notes_box)

        self.err_lbl = QLabel("")
        self.err_lbl.setStyleSheet("color: #EF4444; font-size: 12px; font-weight: 600;")
        body_layout.addWidget(self.err_lbl)

        btn_box = QHBoxLayout()
        btn_box.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("SecondaryBtn")
        cancel_btn.clicked.connect(self.reject)
        btn_box.addWidget(cancel_btn)

        submit_btn = QPushButton("📋 Submit Counts for Review")
        submit_btn.setStyleSheet(
            "background-color: #2563EB; color: white; font-weight: 700; padding: 9px 22px; border-radius: 6px; font-size: 13px;"
        )
        submit_btn.clicked.connect(self.on_submit)
        btn_box.addWidget(submit_btn)

        body_layout.addLayout(btn_box)
        layout.addWidget(body)

    def load_data(self):
        self.details = self.stock_count_service.get_stock_count_details(self.stock_count_id)
        if not self.details:
            self.err_lbl.setText("Session details not found.")
            return

        batches = self.details.get("branch_batches") or []
        if not batches and self.details.get("items"):
            batches = self.details["items"]

        for b in batches:
            card = QFrame()
            card.setStyleSheet(
                "background-color: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 6px; padding: 8px;"
            )
            card_layout = QHBoxLayout(card)
            card_layout.setContentsMargins(10, 6, 10, 6)
            card_layout.setSpacing(12)

            info_col = QVBoxLayout()
            info_col.setSpacing(2)
            p_name = QLabel(f"💊 {b['product_name']}")
            p_name.setStyleSheet("font-weight: 700; color: #1E293B; font-size: 13px;")
            shelf_lbl = b.get("shelf_name") or "Unassigned"
            b_meta = QLabel(
                f"Batch: {b['batch_number']} | Shelf: {shelf_lbl} | Expiry: {b.get('expiry_date', 'N/A')}"
            )
            b_meta.setStyleSheet("font-size: 11px; color: #64748B;")
            info_col.addWidget(p_name)
            info_col.addWidget(b_meta)
            card_layout.addLayout(info_col, stretch=2)

            sys_qty = b.get("system_quantity", 0)
            sys_lbl = QLabel(f"System: {sys_qty}")
            sys_lbl.setStyleSheet("font-size: 12px; font-weight: 600; color: #475569; min-width: 80px;")
            card_layout.addWidget(sys_lbl)

            qty_spin = QSpinBox()
            qty_spin.setRange(0, 999999)
            qty_spin.setValue(sys_qty)
            qty_spin.setFixedWidth(90)
            card_layout.addWidget(qty_spin)

            var_lbl = QLabel("Variance: 0")
            var_lbl.setStyleSheet("font-weight: 700; color: #10B981; font-size: 12px; min-width: 100px;")
            card_layout.addWidget(var_lbl)

            def _update_variance(val, s_qty=sys_qty, label=var_lbl):
                diff = val - s_qty
                if diff > 0:
                    label.setText(f"Variance: +{diff}")
                    label.setStyleSheet("font-weight: 700; color: #2563EB; font-size: 12px; min-width: 100px;")
                elif diff < 0:
                    label.setText(f"Variance: {diff}")
                    label.setStyleSheet("font-weight: 700; color: #EF4444; font-size: 12px; min-width: 100px;")
                else:
                    label.setText("Variance: 0")
                    label.setStyleSheet("font-weight: 700; color: #10B981; font-size: 12px; min-width: 100px;")

            qty_spin.valueChanged.connect(_update_variance)

            self.count_rows.append({
                "batch_id": b["batch_id"],
                "storage_location_id": b.get("storage_location_id"),
                "qty_spin": qty_spin,
            })
            self.items_layout.addWidget(card)

    def on_submit(self):
        items_payload = []
        for r in self.count_rows:
            items_payload.append({
                "batch_id": r["batch_id"],
                "storage_location_id": r.get("storage_location_id"),
                "counted_quantity": r["qty_spin"].value(),
            })

        if not items_payload:
            self.err_lbl.setText("No items found to count.")
            return

        try:
            self.stock_count_service.submit_stock_count(
                user_session=self.session,
                stock_count_id=self.stock_count_id,
                items=items_payload,
                notes=self.submit_notes_in.text().strip() or None,
            )
            QMessageBox.information(
                self,
                "Stock Counts Submitted",
                "Physical count entries recorded and submitted for manager approval!",
            )
            self.accept()
        except Exception as e:
            self.err_lbl.setText(f"Error submitting count: {str(e)}")


class ReviewStockCountDialog(QDialog):
    """Modal dialog for manager review and approval of count variances."""

    def __init__(self, parent, stock_count_service, session, stock_count_id: str):
        super().__init__(parent)
        self.stock_count_service = stock_count_service
        self.session = session
        self.stock_count_id = stock_count_id
        self.details = None
        self.review_rows = []

        self.setWindowTitle("Review & Approve Stock Count Variances")
        self.setMinimumSize(880, 580)
        self.init_ui()
        self.load_data()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.banner = DialogHeaderBanner(
            title="Review Count Variances & Reconcile",
            subtitle="Approve or reject stock count adjustments to balance live branch inventory",
            parent_dialog=self,
        )
        layout.addWidget(self.banner)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(24, 16, 24, 20)
        body_layout.setSpacing(14)

        # Table of items
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels([
            "Product",
            "Batch Number",
            "Shelf",
            "System Qty",
            "Counted Qty",
            "Variance",
            "Review Decision",
        ])
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.Stretch)
        for col_idx in range(1, 7):
            hdr.setSectionResizeMode(col_idx, QHeaderView.Interactive)

        self.table.setColumnWidth(1, 135)
        self.table.setColumnWidth(2, 110)
        self.table.setColumnWidth(3, 90)
        self.table.setColumnWidth(4, 95)
        self.table.setColumnWidth(5, 85)
        self.table.setColumnWidth(6, 155)

        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.verticalHeader().setDefaultSectionSize(44)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        body_layout.addWidget(self.table)

        self.err_lbl = QLabel("")
        self.err_lbl.setStyleSheet("color: #EF4444; font-size: 12px; font-weight: 600;")
        body_layout.addWidget(self.err_lbl)

        btn_box = QHBoxLayout()
        btn_box.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("SecondaryBtn")
        cancel_btn.clicked.connect(self.reject)
        btn_box.addWidget(cancel_btn)

        approve_btn = QPushButton("✅ Approve & Post to Inventory")
        approve_btn.setStyleSheet(
            "background-color: #10B981; color: white; font-weight: 700; padding: 9px 22px; border-radius: 6px; font-size: 13px;"
        )
        approve_btn.clicked.connect(self.on_approve)
        btn_box.addWidget(approve_btn)

        body_layout.addLayout(btn_box)
        layout.addWidget(body)

    def load_data(self):
        self.details = self.stock_count_service.get_stock_count_details(self.stock_count_id)
        if not self.details:
            self.err_lbl.setText("Details not found.")
            return

        items = self.details.get("items", [])
        self.table.setRowCount(len(items))
        for row, it in enumerate(items):
            self.table.setRowHeight(row, 44)
            self.table.setItem(row, 0, QTableWidgetItem(it["product_name"]))
            self.table.setItem(row, 1, QTableWidgetItem(it["batch_number"]))
            self.table.setItem(row, 2, QTableWidgetItem(it.get("shelf_name") or "—"))

            sys_item = QTableWidgetItem(str(it["system_quantity"]))
            sys_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 3, sys_item)

            cnt_item = QTableWidgetItem(str(it["counted_quantity"]))
            cnt_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 4, cnt_item)

            var_val = it["variance"]
            var_item = QTableWidgetItem(f"{'+' if var_val > 0 else ''}{var_val}")
            var_item.setTextAlignment(Qt.AlignCenter)
            if var_val < 0:
                var_item.setForeground(Qt.red)
            elif var_val > 0:
                var_item.setForeground(Qt.blue)
            self.table.setItem(row, 5, var_item)

            action_combo = QComboBox()
            action_combo.addItem("✅ APPROVE", "APPROVE")
            action_combo.addItem("❌ REJECT", "REJECT")
            action_combo.setFixedSize(130, 28)

            def _style_decision_combo(combo: QComboBox):
                is_approve = (combo.currentData() or combo.currentText()) == "APPROVE"
                if is_approve:
                    combo.setStyleSheet(
                        "QComboBox { background-color: #ECFDF5; color: #047857; border: 1px solid #6EE7B7; "
                        "border-radius: 6px; padding: 2px 24px 2px 8px; font-size: 11px; font-weight: 700; min-height: 22px; }"
                    )
                else:
                    combo.setStyleSheet(
                        "QComboBox { background-color: #FEF2F2; color: #B91C1C; border: 1px solid #FCA5A5; "
                        "border-radius: 6px; padding: 2px 24px 2px 8px; font-size: 11px; font-weight: 700; min-height: 22px; }"
                    )

            _style_decision_combo(action_combo)
            action_combo.currentIndexChanged.connect(lambda _, c=action_combo: _style_decision_combo(c))

            cell_widget = QWidget()
            cell_widget.setStyleSheet("background: transparent;")
            cell_layout = QHBoxLayout(cell_widget)
            cell_layout.setContentsMargins(6, 4, 6, 4)
            cell_layout.setSpacing(0)
            cell_layout.setAlignment(Qt.AlignCenter)
            cell_layout.addWidget(action_combo)
            self.table.setCellWidget(row, 6, cell_widget)

            self.review_rows.append({
                "item_id": it["id"],
                "action_combo": action_combo,
            })

    def on_approve(self):
        reviews_payload = []
        for r in self.review_rows:
            reviews_payload.append({
                "stock_count_item_id": r["item_id"],
                "action": r["action_combo"].currentData() or r["action_combo"].currentText(),
                "rejection_reason": "Variance rejected by auditor",
            })

        try:
            self.stock_count_service.approve_stock_count(
                user_session=self.session,
                stock_count_id=self.stock_count_id,
                reviews=reviews_payload,
                notes="Approved via desktop UI manager interface.",
            )
            QMessageBox.information(
                self,
                "Stock Count Finalized",
                "Approved variances have been posted to the inventory ledger and branch inventory is updated!",
            )
            self.accept()
        except Exception as e:
            self.err_lbl.setText(f"Error approving count: {str(e)}")


class StockCountsWidget(QWidget):
    """
    Phase 9 Stock Counts & Variance Approval UI widget.
    Displays stock count sessions, type, status, started date, and supports session initiation, counting & review.
    """

    def __init__(self, db_manager, get_session_callable, parent=None):
        super().__init__(parent)
        self.db_manager = db_manager
        self.get_session = get_session_callable
        self.stock_count_service = StockCountService(db_manager)

        # Pagination & Data Cache
        self.all_counts = []
        self.filtered_counts = []
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

        title = QLabel("Stock Counts & Variance Approval")
        title.setObjectName("PageHeader")
        subtitle = QLabel("Cycle counts, full inventory audits, blind counts, and reconciliation workflows")
        subtitle.setObjectName("PageSubtitle")
        title_col.addWidget(title)
        title_col.addWidget(subtitle)
        header_layout.addLayout(title_col)
        header_layout.addStretch()

        self.start_btn = QPushButton("+ Start Stock Count")
        self.start_btn.setStyleSheet(
            "background-color: #10B981; color: white; font-weight: 700; padding: 9px 18px; border-radius: 6px;"
        )
        self.start_btn.clicked.connect(self._open_start_dialog)
        header_layout.addWidget(self.start_btn)

        self.count_btn = QPushButton("🔢 Count Items")
        self.count_btn.setStyleSheet(
            "background-color: #2563EB; color: white; font-weight: 700; padding: 9px 18px; border-radius: 6px;"
        )
        self.count_btn.clicked.connect(self._on_count_selected)
        header_layout.addWidget(self.count_btn)

        self.review_btn = QPushButton("⚖️ Review & Approve")
        self.review_btn.setStyleSheet(
            "background-color: #059669; color: white; font-weight: 700; padding: 9px 18px; border-radius: 6px;"
        )
        self.review_btn.clicked.connect(self._on_review_selected)
        header_layout.addWidget(self.review_btn)

        self.refresh_btn = QPushButton("Refresh Data")
        self.refresh_btn.setObjectName("SecondaryBtn")
        self.refresh_btn.clicked.connect(self.refresh_data)
        header_layout.addWidget(self.refresh_btn)
        layout.addLayout(header_layout)

        # Search Bar
        search_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search count sessions by ID, type, status, or notes...")
        self.search_input.textChanged.connect(lambda: self.search_timer.start())
        search_layout.addWidget(self.search_input)
        layout.addLayout(search_layout)

        # Table (Clean 6 columns including Shelf / Scope)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels([
            "Audit Session ID",
            "Count Type",
            "Shelf / Scope",
            "Audit Status",
            "Started At",
            "Auditor Notes",
        ])
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.Interactive)
        hdr.setSectionResizeMode(1, QHeaderView.Interactive)
        hdr.setSectionResizeMode(2, QHeaderView.Interactive)
        hdr.setSectionResizeMode(3, QHeaderView.Interactive)
        hdr.setSectionResizeMode(4, QHeaderView.Interactive)
        hdr.setSectionResizeMode(5, QHeaderView.Stretch)

        self.table.setColumnWidth(0, 150)
        self.table.setColumnWidth(1, 135)
        self.table.setColumnWidth(2, 145)
        self.table.setColumnWidth(3, 130)
        self.table.setColumnWidth(4, 155)
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

        self.page_status_label = QLabel("Showing 0 sessions")
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

    def _open_start_dialog(self):
        session = self.get_session()
        if not session:
            return
        dlg = StartStockCountDialog(self, self.stock_count_service, session)
        if dlg.exec():
            self.refresh_data()

    def _open_count_entry_dialog(self, sc_id: str):
        session = self.get_session()
        if not session:
            return
        dlg = RecordPhysicalCountsDialog(self, self.stock_count_service, session, sc_id)
        if dlg.exec():
            self.refresh_data()

    def _open_review_dialog(self, sc_id: str):
        session = self.get_session()
        if not session:
            return
        dlg = ReviewStockCountDialog(self, self.stock_count_service, session, sc_id)
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
        self.shelves_map = {}
        try:
            locs = self.stock_count_service.inventory_service.list_storage_locations(
                session.organization_id, session.branch_id
            )
            self.shelves_map = {loc.id: loc.name for loc in locs}
        except Exception:
            pass
        self.all_counts = self.stock_count_service.list_stock_counts(session.branch_id)
        self._apply_filter_and_render()

    def _apply_filter_and_render(self):
        query = self.search_input.text().strip().lower()
        if not query:
            self.filtered_counts = list(self.all_counts)
        else:
            shelves_map = getattr(self, "shelves_map", {})
            self.filtered_counts = [
                sc for sc in self.all_counts
                if query in (sc.id or "").lower()
                or query in (sc.count_type or "").lower()
                or query in (shelves_map.get(sc.storage_location_id, "all shelves") or "").lower()
                or query in (sc.status or "").lower()
                or query in (sc.notes or "").lower()
            ]
        self.current_page = 1
        self._render_current_page()

    def _render_current_page(self):
        total_count = len(self.filtered_counts)
        self.total_pages = max(1, (total_count + self.page_size - 1) // self.page_size) if self.page_size > 0 else 1
        self.current_page = min(self.current_page, self.total_pages)

        start_idx = (self.current_page - 1) * self.page_size
        end_idx = min(start_idx + self.page_size, total_count)
        page_items = self.filtered_counts[start_idx:end_idx]

        shelves_map = getattr(self, "shelves_map", {})

        self.table.setUpdatesEnabled(False)
        self.table.blockSignals(True)
        try:
            self.table.setRowCount(len(page_items))
            for idx, sc in enumerate(page_items):
                shelf_lbl = (
                    f"🗄️ {shelves_map.get(sc.storage_location_id, 'Shelf')}"
                    if sc.storage_location_id
                    else "All Shelves"
                )
                self.table.setItem(idx, 0, QTableWidgetItem(sc.id[:8].upper()))
                self.table.setItem(idx, 1, QTableWidgetItem(sc.count_type))
                self.table.setItem(idx, 2, QTableWidgetItem(shelf_lbl))
                self.table.setItem(idx, 3, QTableWidgetItem(sc.status))
                self.table.setItem(idx, 4, QTableWidgetItem(sc.started_at[:19] if sc.started_at else "-"))
                self.table.setItem(idx, 5, QTableWidgetItem(sc.notes or "-"))
        finally:
            self.table.blockSignals(False)
            self.table.setUpdatesEnabled(True)

        if total_count == 0:
            self.page_status_label.setText("Showing 0 sessions")
        else:
            self.page_status_label.setText(f"Showing {start_idx + 1}–{end_idx} of {total_count} sessions")
        self.page_info_label.setText(f"Page {self.current_page} of {self.total_pages}")
        self.prev_page_btn.setEnabled(self.current_page > 1)
        self.next_page_btn.setEnabled(self.current_page < self.total_pages)

    def _get_selected_session(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(
                self,
                "Selection Required",
                "Please click a row in the table to select a stock count session first."
            )
            return None
        start_idx = (self.current_page - 1) * self.page_size
        idx = start_idx + row
        if 0 <= idx < len(self.filtered_counts):
            return self.filtered_counts[idx]
        return None

    def _on_count_selected(self):
        sc = self._get_selected_session()
        if not sc:
            return
        if sc.status not in (StockCountStatus.DRAFT.value, StockCountStatus.IN_PROGRESS.value):
            QMessageBox.information(self, "Invalid Status", f"Only DRAFT or IN_PROGRESS counts can be updated. Current status: {sc.status}")
            return
        self._open_count_entry_dialog(sc.id)

    def _on_review_selected(self):
        sc = self._get_selected_session()
        if not sc:
            return
        if sc.status != StockCountStatus.SUBMITTED.value:
            QMessageBox.information(self, "Invalid Status", f"Only SUBMITTED counts are pending review & approval. Current status: {sc.status}")
            return
        self._open_review_dialog(sc.id)

    def _on_table_double_clicked(self, row, col):
        start_idx = (self.current_page - 1) * self.page_size
        idx = start_idx + row
        if 0 <= idx < len(self.filtered_counts):
            sc = self.filtered_counts[idx]
            if sc.status in (StockCountStatus.DRAFT.value, StockCountStatus.IN_PROGRESS.value):
                self._open_count_entry_dialog(sc.id)
            elif sc.status == StockCountStatus.SUBMITTED.value:
                self._open_review_dialog(sc.id)
