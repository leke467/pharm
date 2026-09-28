import json
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QPushButton,
    QLineEdit,
    QComboBox,
    QHeaderView,
    QDialog,
    QTextEdit,
    QMessageBox,
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from desktop.app.services.audit_service import AuditService
from desktop.app.ui.common.title_bar import DialogHeaderBanner


class AuditDetailsDialog(QDialog):
    """Technical Audit Dialog displaying JSON snapshots of data_before and data_after."""

    def __init__(self, event_data: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Audit Event Details — {event_data.get('action')}")
        self.resize(650, 560)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        banner = DialogHeaderBanner(
            title=f"Technical Audit Snapshot — {event_data.get('action')}",
            subtitle=f"Entity: {event_data.get('entity_type')} • Branch: {event_data.get('branch_name', 'N/A')} • By: {event_data.get('account_name', 'N/A')}",
            parent_dialog=self,
        )
        layout.addWidget(banner)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(24, 18, 24, 20)
        body_layout.setSpacing(12)

        ts = str(event_data.get("local_timestamp") or event_data.get("created_at") or "")[:19].replace("T", " ")
        info_lbl = QLabel(
            f"Action Code: {event_data.get('action')}\n"
            f"Branch: {event_data.get('branch_name') or 'Main Branch (HQ)'}\n"
            f"Account / Staff: {event_data.get('account_name') or 'Administrator'}\n"
            f"Entity: {event_data.get('entity_type')} (ID: {event_data.get('entity_id')})\n"
            f"Timestamp: {ts}   |   Source: {event_data.get('source')}\n"
            f"Summary / Reason: {event_data.get('summary') or event_data.get('reason') or 'None'}"
        )
        info_lbl.setStyleSheet("color: #334155; font-size: 12.5px; font-weight: 600; line-height: 1.4;")
        body_layout.addWidget(info_lbl)

        body_layout.addWidget(QLabel("Data Before (JSON Snapshot):"))
        self.before_edit = QTextEdit()
        self.before_edit.setReadOnly(True)
        before_val = event_data.get("data_before")
        if before_val:
            try:
                parsed = json.loads(before_val) if isinstance(before_val, str) else before_val
                self.before_edit.setPlainText(json.dumps(parsed, indent=2))
            except Exception:
                self.before_edit.setPlainText(str(before_val))
        else:
            self.before_edit.setPlainText("(None)")
        body_layout.addWidget(self.before_edit)

        body_layout.addWidget(QLabel("Data After (JSON Snapshot):"))
        self.after_edit = QTextEdit()
        self.after_edit.setReadOnly(True)
        after_val = event_data.get("data_after")
        if after_val:
            try:
                parsed = json.loads(after_val) if isinstance(after_val, str) else after_val
                self.after_edit.setPlainText(json.dumps(parsed, indent=2))
            except Exception:
                self.after_edit.setPlainText(str(after_val))
        else:
            self.after_edit.setPlainText("(None)")
        body_layout.addWidget(self.after_edit)

        close_btn = QPushButton("Close")
        close_btn.setObjectName("SecondaryBtn")
        close_btn.clicked.connect(self.accept)
        body_layout.addWidget(close_btn, alignment=Qt.AlignRight)
        layout.addWidget(body)


class ActivityLogWidget(QWidget):
    """
    Operational Activity Logs Widget.
    Displays human-readable operational logs (Price Changes, Stock Adjustments, Batch Additions,
    Sales, Purchases, Transfers, and Product Updates) with explicit Branch and Staff Account attribution.
    Separated from the technical Security & Compliance Audit Trail.
    """

    def __init__(self, db_manager, get_session_callable, parent=None):
        super().__init__(parent)
        self.db_manager = db_manager
        self.get_session = get_session_callable
        self.audit_service = AuditService(db_manager) if db_manager else None
        self.logs: list[dict] = []

        self.current_page = 1
        self.page_size = 50
        self.total_pages = 1

        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(150)
        self.search_timer.timeout.connect(self.refresh_data)

        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        # Header
        header_layout = QHBoxLayout()
        title_col = QVBoxLayout()
        title_col.setSpacing(4)

        title = QLabel("Operational Activity Logs")
        title.setObjectName("PageHeader")
        subtitle = QLabel(
            "Day-to-day operational history showing which Branch and Staff Account updated prices, stock, batches, and sales"
        )
        subtitle.setObjectName("PageSubtitle")
        title_col.addWidget(title)
        title_col.addWidget(subtitle)
        header_layout.addLayout(title_col)
        header_layout.addStretch()

        self.category_combo = QComboBox()
        self.category_combo.addItems([
            "All Activities",
            "Price Changes",
            "Inventory & Batches",
            "Products & Catalog",
            "Sales & Returns",
            "Purchases & Transfers",
            "Users & Settings",
        ])
        self.category_combo.setMinimumWidth(175)
        self.category_combo.currentTextChanged.connect(lambda _: self.refresh_data())
        header_layout.addWidget(self.category_combo)

        self.branch_combo = QComboBox()
        self.branch_combo.addItem("All Branches")
        self.branch_combo.setMinimumWidth(165)
        self.branch_combo.currentTextChanged.connect(lambda _: self.refresh_data())
        header_layout.addWidget(self.branch_combo)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search product, price, branch, or staff...")
        self.search_input.setMinimumWidth(240)
        self.search_input.textChanged.connect(lambda _: self.search_timer.start())
        header_layout.addWidget(self.search_input)

        self.refresh_btn = QPushButton("🔄 Refresh")
        self.refresh_btn.setObjectName("SecondaryBtn")
        self.refresh_btn.clicked.connect(self.refresh_data)
        header_layout.addWidget(self.refresh_btn)

        self.details_btn = QPushButton("📋 View Details")
        self.details_btn.setStyleSheet(
            "background-color: #10B981; color: white; font-weight: 700; padding: 8px 16px; border-radius: 6px;"
        )
        self.details_btn.clicked.connect(self._on_view_selected_details)
        header_layout.addWidget(self.details_btn)

        layout.addLayout(header_layout)

        # Table (6 clear human-readable columns)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels([
            "Timestamp",
            "Branch",
            "Account / Staff",
            "Activity",
            "Item & Change Details",
            "Reason / Notes",
        ])
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.Interactive)
        hdr.setSectionResizeMode(1, QHeaderView.Interactive)
        hdr.setSectionResizeMode(2, QHeaderView.Interactive)
        hdr.setSectionResizeMode(3, QHeaderView.Interactive)
        hdr.setSectionResizeMode(4, QHeaderView.Stretch)
        hdr.setSectionResizeMode(5, QHeaderView.Interactive)

        self.table.setColumnWidth(0, 145)
        self.table.setColumnWidth(1, 145)
        self.table.setColumnWidth(2, 175)
        self.table.setColumnWidth(3, 155)
        self.table.setColumnWidth(5, 220)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.cellDoubleClicked.connect(self._on_table_double_clicked)

        self.table.verticalHeader().setDefaultSectionSize(38)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table)

        # Pagination Bar
        pagination_layout = QHBoxLayout()
        pagination_layout.setSpacing(12)

        self.page_status_label = QLabel("Showing 0 activity logs")
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

    def _populate_branches(self, org_id: str):
        if not self.audit_service:
            return
        try:
            branches = self.audit_service.list_branches(org_id)
            current_txt = self.branch_combo.currentText()
            self.branch_combo.blockSignals(True)
            self.branch_combo.clear()
            self.branch_combo.addItem("All Branches")
            for b in branches:
                self.branch_combo.addItem(b["name"])
            idx = self.branch_combo.findText(current_txt)
            if idx >= 0:
                self.branch_combo.setCurrentIndex(idx)
            self.branch_combo.blockSignals(False)
        except Exception:
            self.branch_combo.blockSignals(False)

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
        if not session or not self.audit_service:
            return

        self._populate_branches(session.organization_id)
        cat = self.category_combo.currentText()
        br = self.branch_combo.currentText()
        search_q = self.search_input.text().strip()

        self.logs = self.audit_service.list_activity_logs(
            organization_id=session.organization_id,
            branch_name_filter=br,
            category_filter=cat,
            search_query=search_q,
            limit=500,
        )
        self.current_page = 1
        self._render_current_page()

    def _render_current_page(self):
        total_count = len(self.logs)
        self.total_pages = max(1, (total_count + self.page_size - 1) // self.page_size) if self.page_size > 0 else 1
        self.current_page = min(self.current_page, self.total_pages)

        start_idx = (self.current_page - 1) * self.page_size
        end_idx = min(start_idx + self.page_size, total_count)
        page_items = self.logs[start_idx:end_idx]

        price_bg = QColor("#ECFDF5")
        branch_fg = QColor("#1E40AF")
        price_fg = QColor("#065F46")

        self.table.setUpdatesEnabled(False)
        self.table.blockSignals(True)
        try:
            self.table.setRowCount(len(page_items))
            for idx, item in enumerate(page_items):
                ts = str(item.get("local_timestamp") or item.get("created_at") or "")[:19].replace("T", " ")
                br_name = str(item.get("branch_name") or "Main Branch (HQ)")
                acct_name = str(item.get("account_name") or "Administrator")
                act_lbl = str(item.get("activity_label") or item.get("action") or "")
                summary = str(item.get("summary") or "")
                reason = str(item.get("reason") or "")

                c0 = QTableWidgetItem(ts)
                c1 = QTableWidgetItem(br_name)
                c1.setForeground(branch_fg)
                c2 = QTableWidgetItem(acct_name)
                c3 = QTableWidgetItem(act_lbl)
                c4 = QTableWidgetItem(summary)
                c5 = QTableWidgetItem(reason)

                is_price_change = item.get("action") == "PRICE_CHANGED" or item.get("entity_type") == "price"
                if is_price_change:
                    c3.setForeground(price_fg)
                    c4.setForeground(price_fg)
                    for cell in (c0, c1, c2, c3, c4, c5):
                        cell.setBackground(price_bg)

                self.table.setItem(idx, 0, c0)
                self.table.setItem(idx, 1, c1)
                self.table.setItem(idx, 2, c2)
                self.table.setItem(idx, 3, c3)
                self.table.setItem(idx, 4, c4)
                self.table.setItem(idx, 5, c5)
        finally:
            self.table.blockSignals(False)
            self.table.setUpdatesEnabled(True)

        if total_count == 0:
            self.page_status_label.setText("Showing 0 activity logs")
        else:
            self.page_status_label.setText(f"Showing {start_idx + 1}–{end_idx} of {total_count} activity logs")
        self.page_info_label.setText(f"Page {self.current_page} of {self.total_pages}")
        self.prev_page_btn.setEnabled(self.current_page > 1)
        self.next_page_btn.setEnabled(self.current_page < self.total_pages)

    def _on_view_selected_details(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(
                self,
                "Selection Required",
                "Please select a row in the Activity Logs table first.",
            )
            return
        self._on_table_double_clicked(row, 0)

    def _on_table_double_clicked(self, row: int, _column: int):
        actual_idx = (self.current_page - 1) * self.page_size + row
        if 0 <= actual_idx < len(self.logs):
            item = self.logs[actual_idx]
            ts = str(item.get("local_timestamp") or item.get("created_at") or "")[:19].replace("T", " ")
            QMessageBox.information(
                self,
                f"Activity Log Details — {item.get('activity_label')}",
                f"<b>Activity:</b> {item.get('activity_label')}<br>"
                f"<b>Category:</b> {item.get('category')}<br><br>"
                f"<b>Updated By Branch:</b> <span style='color:#1E40AF; font-weight:bold;'>{item.get('branch_name')}</span><br>"
                f"<b>Updated By Account:</b> <span style='color:#0F172A; font-weight:bold;'>{item.get('account_name')}</span><br><br>"
                f"<b>Item & Change Details:</b><br>{item.get('summary')}<br><br>"
                f"<b>Reason / Notes:</b> {item.get('reason') or 'None'}<br>"
                f"<b>Timestamp:</b> {ts}",
            )


class AuditLogWidget(QWidget):
    """
    Technical Security & Compliance Audit Trail Viewer Widget (Architecture Plan §6, §13).
    Displays immutable technical audit events with Branch, Account, Action Code, Entity IDs, and JSON Snapshot inspection.
    """

    def __init__(self, db_manager, get_session_callable, parent=None):
        super().__init__(parent)
        self.db_manager = db_manager
        self.get_session = get_session_callable
        self.audit_service = AuditService(db_manager) if db_manager else None
        self.events: list[dict] = []

        self.current_page = 1
        self.page_size = 50
        self.total_pages = 1

        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(150)
        self.search_timer.timeout.connect(self.refresh_data)

        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        # Header
        header_layout = QHBoxLayout()
        title_col = QVBoxLayout()
        title_col.setSpacing(4)

        title = QLabel("Security & Compliance Audit Trail")
        title.setObjectName("PageHeader")
        subtitle = QLabel(
            "Immutable technical compliance trail with Entity IDs, sync sources, and raw JSON before/after state snapshots"
        )
        subtitle.setObjectName("PageSubtitle")
        title_col.addWidget(title)
        title_col.addWidget(subtitle)
        header_layout.addLayout(title_col)
        header_layout.addStretch()

        self.action_filter = QLineEdit()
        self.action_filter.setPlaceholderText("Filter by action code (e.g. PRICE_CHANGED)...")
        self.action_filter.setMinimumWidth(220)
        self.action_filter.textChanged.connect(lambda: self.search_timer.start())
        header_layout.addWidget(self.action_filter)

        self.entity_filter = QLineEdit()
        self.entity_filter.setPlaceholderText("Filter by entity type (e.g. price, batch)...")
        self.entity_filter.setMinimumWidth(210)
        self.entity_filter.textChanged.connect(lambda: self.search_timer.start())
        header_layout.addWidget(self.entity_filter)

        self.refresh_btn = QPushButton("🔄 Refresh")
        self.refresh_btn.setObjectName("SecondaryBtn")
        self.refresh_btn.clicked.connect(self.refresh_data)
        header_layout.addWidget(self.refresh_btn)

        self.inspect_btn = QPushButton("🔍 Inspect JSON Snapshot")
        self.inspect_btn.setStyleSheet(
            "background-color: #2563EB; color: white; font-weight: 700; padding: 8px 18px; border-radius: 6px;"
        )
        self.inspect_btn.clicked.connect(self._on_inspect_selected_event)
        header_layout.addWidget(self.inspect_btn)

        layout.addLayout(header_layout)

        # Table (7 technical audit columns including Branch & Account)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels([
            "Timestamp",
            "Branch",
            "Account / Staff",
            "Action Code",
            "Entity Type",
            "Entity ID",
            "Source",
        ])
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.Interactive)
        hdr.setSectionResizeMode(1, QHeaderView.Interactive)
        hdr.setSectionResizeMode(2, QHeaderView.Interactive)
        hdr.setSectionResizeMode(3, QHeaderView.Interactive)
        hdr.setSectionResizeMode(4, QHeaderView.Interactive)
        hdr.setSectionResizeMode(5, QHeaderView.Stretch)
        hdr.setSectionResizeMode(6, QHeaderView.Interactive)

        self.table.setColumnWidth(0, 150)
        self.table.setColumnWidth(1, 145)
        self.table.setColumnWidth(2, 175)
        self.table.setColumnWidth(3, 150)
        self.table.setColumnWidth(4, 120)
        self.table.setColumnWidth(6, 110)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.cellDoubleClicked.connect(self._on_table_double_clicked)

        self.table.verticalHeader().setDefaultSectionSize(38)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table)

        # Pagination Bar
        pagination_layout = QHBoxLayout()
        pagination_layout.setSpacing(12)

        self.page_status_label = QLabel("Showing 0 audit events")
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
        if not session or not self.audit_service:
            return

        action = self.action_filter.text().strip() or None
        entity = self.entity_filter.text().strip() or None

        self.events = self.audit_service.list_audit_events(
            organization_id=session.organization_id,
            action=action,
            entity_type=entity,
            limit=500,
        )
        self.current_page = 1
        self._render_current_page()

    def _render_current_page(self):
        total_count = len(self.events)
        self.total_pages = max(1, (total_count + self.page_size - 1) // self.page_size) if self.page_size > 0 else 1
        self.current_page = min(self.current_page, self.total_pages)

        start_idx = (self.current_page - 1) * self.page_size
        end_idx = min(start_idx + self.page_size, total_count)
        page_items = self.events[start_idx:end_idx]

        self.table.setUpdatesEnabled(False)
        self.table.blockSignals(True)
        try:
            self.table.setRowCount(len(page_items))
            for idx, event in enumerate(page_items):
                ts = str(event.get("local_timestamp") or event.get("created_at") or "")[:19].replace("T", " ")
                self.table.setItem(idx, 0, QTableWidgetItem(ts))
                self.table.setItem(idx, 1, QTableWidgetItem(str(event.get("branch_name") or "Main Branch (HQ)")))
                self.table.setItem(idx, 2, QTableWidgetItem(str(event.get("account_name") or "Administrator")))
                self.table.setItem(idx, 3, QTableWidgetItem(str(event.get("action") or "")))
                self.table.setItem(idx, 4, QTableWidgetItem(str(event.get("entity_type") or "")))
                self.table.setItem(idx, 5, QTableWidgetItem(str(event.get("entity_id") or "")))
                self.table.setItem(idx, 6, QTableWidgetItem(str(event.get("source") or "")))
        finally:
            self.table.blockSignals(False)
            self.table.setUpdatesEnabled(True)

        if total_count == 0:
            self.page_status_label.setText("Showing 0 audit events")
        else:
            self.page_status_label.setText(f"Showing {start_idx + 1}–{end_idx} of {total_count} audit events")
        self.page_info_label.setText(f"Page {self.current_page} of {self.total_pages}")
        self.prev_page_btn.setEnabled(self.current_page > 1)
        self.next_page_btn.setEnabled(self.current_page < self.total_pages)

    def _on_inspect_selected_event(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(
                self,
                "Selection Required",
                "Please select an audit event row in the table first to inspect its JSON snapshot.",
            )
            return
        self._on_table_double_clicked(row, 0)

    def _on_table_double_clicked(self, row: int, _column: int):
        actual_idx = (self.current_page - 1) * self.page_size + row
        if 0 <= actual_idx < len(self.events):
            event = self.events[actual_idx]
            dlg = AuditDetailsDialog(event, self)
            dlg.exec()
