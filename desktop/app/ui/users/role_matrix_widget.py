from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QCheckBox,
    QComboBox,
    QDialog,
    QMessageBox,
    QFrame,
)
from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QFont, QColor, QBrush, QPainter, QPen, QPainterPath
from desktop.app.ui.common.title_bar import DialogHeaderBanner
from shared.enums import PermissionCode


class MatrixCheckBox(QCheckBox):
    """
    High-contrast, custom-painted checkbox for the Roles & Permissions Matrix.
    Renders a crisp bordered box when unchecked and a vibrant filled box with a
    bold white checkmark when checked, immune to global QSS overrides.
    """

    def __init__(self, is_parent: bool = False, parent=None):
        super().__init__(parent)
        self.is_parent = is_parent
        self._hovered = False
        self.setFixedSize(26, 26)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet("background: transparent; border: none;")

    def enterEvent(self, event):
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def hitButton(self, pos):
        return self.rect().contains(pos)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        box_size = 19.0
        x = (self.width() - box_size) / 2.0
        y = (self.height() - box_size) / 2.0
        rect = QRectF(x, y, box_size, box_size)

        if self.isChecked():
            fill_color = QColor("#2563EB") if self.is_parent else QColor("#10B981")
            if self._hovered:
                fill_color = QColor("#1D4ED8") if self.is_parent else QColor("#059669")
            painter.setPen(QPen(fill_color, 1.8))
            painter.setBrush(QBrush(fill_color))
            painter.drawRoundedRect(rect, 5.0, 5.0)

            # Draw crisp white checkmark
            check_pen = QPen(QColor("#FFFFFF"), 2.3, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
            painter.setPen(check_pen)
            path = QPainterPath()
            path.moveTo(QPointF(x + 4.8, y + 9.8))
            path.lineTo(QPointF(x + 8.3, y + 13.4))
            path.lineTo(QPointF(x + 14.5, y + 6.2))
            painter.drawPath(path)
        else:
            border_color = QColor("#2563EB") if self._hovered else QColor("#94A3B8")
            bg_color = QColor("#EFF6FF") if self._hovered else QColor("#FFFFFF")
            painter.setPen(QPen(border_color, 1.8))
            painter.setBrush(QBrush(bg_color))
            painter.drawRoundedRect(rect, 5.0, 5.0)

        painter.end()


class MatrixCellWidget(QWidget):
    """Transparent table cell wrapper that forwards clicks anywhere in the cell to the checkbox."""

    def __init__(self, checkbox: MatrixCheckBox, parent=None):
        super().__init__(parent)
        self.checkbox = checkbox
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet("background: transparent; border: none;")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.checkbox)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.checkbox.isEnabled():
            self.checkbox.click()
            event.accept()
            return
        super().mousePressEvent(event)


# Matrix rows definition with module hierarchy and canonical permission code mappings.
# Every cell (view, create, edit, delete) is clickable and maps to its domain PermissionCode.
MATRIX_ROWS = [
    {
        "menu": "Dashboard",
        "is_parent": True,
        "view": PermissionCode.DASHBOARD_VIEW.value,
        "create": PermissionCode.DASHBOARD_VIEW.value,
        "edit": PermissionCode.DASHBOARD_VIEW.value,
        "delete": PermissionCode.DASHBOARD_VIEW.value,
    },
    {
        "menu": "Point of Sale (Main Menu)",
        "is_parent": True,
        "view": PermissionCode.SALES_SELL.value,
        "create": PermissionCode.SALES_SELL.value,
        "edit": PermissionCode.SALES_RETURN.value,
        "delete": PermissionCode.SALES_VOID.value,
    },
    {
        "menu": "  ↳ POS: Cashier Checkout & Dispensing",
        "is_parent": False,
        "view": PermissionCode.SALES_SELL.value,
        "create": PermissionCode.SALES_SELL.value,
        "edit": PermissionCode.SALES_SELL.value,
        "delete": PermissionCode.SALES_VOID.value,
    },
    {
        "menu": "  ↳ POS: Sales Returns & Refunds",
        "is_parent": False,
        "view": PermissionCode.SALES_RETURN.value,
        "create": PermissionCode.SALES_RETURN.value,
        "edit": PermissionCode.SALES_RETURN.value,
        "delete": PermissionCode.SALES_VOID.value,
    },
    {
        "menu": "  ↳ POS: Void Sales & Transactions",
        "is_parent": False,
        "view": PermissionCode.SALES_VOID.value,
        "create": PermissionCode.SALES_VOID.value,
        "edit": PermissionCode.SALES_VOID.value,
        "delete": PermissionCode.SALES_VOID.value,
    },
    {
        "menu": "Inventory (Main Menu)",
        "is_parent": True,
        "view": PermissionCode.INVENTORY_VIEW.value,
        "create": PermissionCode.INVENTORY_ADJUST.value,
        "edit": PermissionCode.INVENTORY_ADJUST.value,
        "delete": PermissionCode.INVENTORY_ADJUST.value,
    },
    {
        "menu": "  ↳ Inventory: Stock Overview & Balances",
        "is_parent": False,
        "view": PermissionCode.INVENTORY_VIEW.value,
        "create": PermissionCode.INVENTORY_ADJUST.value,
        "edit": PermissionCode.INVENTORY_ADJUST.value,
        "delete": PermissionCode.INVENTORY_ADJUST.value,
    },
    {
        "menu": "  ↳ Inventory: Stock Adjustments & Damage",
        "is_parent": False,
        "view": PermissionCode.INVENTORY_VIEW.value,
        "create": PermissionCode.INVENTORY_ADJUST.value,
        "edit": PermissionCode.INVENTORY_ADJUST.value,
        "delete": PermissionCode.INVENTORY_ADJUST.value,
    },
    {
        "menu": "  ↳ Inventory: Shelves & Storage Locations",
        "is_parent": False,
        "view": PermissionCode.INVENTORY_VIEW.value,
        "create": PermissionCode.INVENTORY_ADJUST.value,
        "edit": PermissionCode.INVENTORY_ADJUST.value,
        "delete": PermissionCode.INVENTORY_ADJUST.value,
    },
    {
        "menu": "Products (Main Menu)",
        "is_parent": True,
        "view": PermissionCode.PRODUCTS_VIEW.value,
        "create": PermissionCode.PRODUCTS_CREATE.value,
        "edit": PermissionCode.PRODUCTS_EDIT.value,
        "delete": PermissionCode.PRODUCTS_DELETE.value,
    },
    {
        "menu": "  ↳ Products: Catalog & Directory",
        "is_parent": False,
        "view": PermissionCode.PRODUCTS_VIEW.value,
        "create": PermissionCode.PRODUCTS_CREATE.value,
        "edit": PermissionCode.PRODUCTS_EDIT.value,
        "delete": PermissionCode.PRODUCTS_DELETE.value,
    },
    {
        "menu": "  ↳ Products: Batches, Expiry & Recalls",
        "is_parent": False,
        "view": PermissionCode.PRODUCTS_VIEW.value,
        "create": PermissionCode.BATCHES_MANAGE.value,
        "edit": PermissionCode.BATCHES_MANAGE.value,
        "delete": PermissionCode.BATCHES_MANAGE.value,
    },
    {
        "menu": "  ↳ Products: Selling Prices & Markups",
        "is_parent": False,
        "view": PermissionCode.PRICES_VIEW.value,
        "create": PermissionCode.PRICES_MANAGE.value,
        "edit": PermissionCode.PRICES_MANAGE.value,
        "delete": PermissionCode.PRICES_MANAGE.value,
    },
    {
        "menu": "Purchases & Inbound Stock (Main Menu)",
        "is_parent": True,
        "view": PermissionCode.STOCK_RECEIVE.value,
        "create": PermissionCode.STOCK_RECEIVE.value,
        "edit": PermissionCode.SUPPLIERS_MANAGE.value,
        "delete": PermissionCode.SUPPLIERS_MANAGE.value,
    },
    {
        "menu": "  ↳ Purchases: Purchase Orders & Receiving",
        "is_parent": False,
        "view": PermissionCode.STOCK_RECEIVE.value,
        "create": PermissionCode.STOCK_RECEIVE.value,
        "edit": PermissionCode.STOCK_RECEIVE.value,
        "delete": PermissionCode.STOCK_RECEIVE.value,
    },
    {
        "menu": "  ↳ Purchases: Supplier Directory",
        "is_parent": False,
        "view": PermissionCode.STOCK_RECEIVE.value,
        "create": PermissionCode.SUPPLIERS_MANAGE.value,
        "edit": PermissionCode.SUPPLIERS_MANAGE.value,
        "delete": PermissionCode.SUPPLIERS_MANAGE.value,
    },
    {
        "menu": "Stock Counts (Main Menu)",
        "is_parent": True,
        "view": PermissionCode.STOCK_COUNTS_PERFORM.value,
        "create": PermissionCode.STOCK_COUNTS_PERFORM.value,
        "edit": PermissionCode.STOCK_COUNTS_APPROVE.value,
        "delete": PermissionCode.STOCK_COUNTS_APPROVE.value,
    },
    {
        "menu": "  ↳ Stock Counts: Physical Counting",
        "is_parent": False,
        "view": PermissionCode.STOCK_COUNTS_PERFORM.value,
        "create": PermissionCode.STOCK_COUNTS_PERFORM.value,
        "edit": PermissionCode.STOCK_COUNTS_PERFORM.value,
        "delete": PermissionCode.STOCK_COUNTS_APPROVE.value,
    },
    {
        "menu": "  ↳ Stock Counts: Review & Variance Approvals",
        "is_parent": False,
        "view": PermissionCode.STOCK_COUNTS_APPROVE.value,
        "create": PermissionCode.STOCK_COUNTS_APPROVE.value,
        "edit": PermissionCode.STOCK_COUNTS_APPROVE.value,
        "delete": PermissionCode.STOCK_COUNTS_APPROVE.value,
    },
    {
        "menu": "Stock Transfers (Main Menu)",
        "is_parent": True,
        "view": PermissionCode.STOCK_TRANSFER.value,
        "create": PermissionCode.STOCK_TRANSFER.value,
        "edit": PermissionCode.STOCK_TRANSFER.value,
        "delete": PermissionCode.STOCK_TRANSFER.value,
    },
    {
        "menu": "Expenses (Main Menu)",
        "is_parent": True,
        "view": PermissionCode.EXPENSES_CREATE.value,
        "create": PermissionCode.EXPENSES_CREATE.value,
        "edit": PermissionCode.EXPENSES_APPROVE.value,
        "delete": PermissionCode.EXPENSES_APPROVE.value,
    },
    {
        "menu": "  ↳ Expenses: Record Expense Vouchers",
        "is_parent": False,
        "view": PermissionCode.EXPENSES_CREATE.value,
        "create": PermissionCode.EXPENSES_CREATE.value,
        "edit": PermissionCode.EXPENSES_CREATE.value,
        "delete": PermissionCode.EXPENSES_APPROVE.value,
    },
    {
        "menu": "  ↳ Expenses: Approve & Manage Categories",
        "is_parent": False,
        "view": PermissionCode.EXPENSES_APPROVE.value,
        "create": PermissionCode.EXPENSES_APPROVE.value,
        "edit": PermissionCode.EXPENSES_APPROVE.value,
        "delete": PermissionCode.EXPENSES_APPROVE.value,
    },
    {
        "menu": "Reports & Financials (Main Menu)",
        "is_parent": True,
        "view": PermissionCode.REPORTS_VIEW.value,
        "create": PermissionCode.REPORTS_VIEW.value,
        "edit": PermissionCode.REPORTS_VIEW.value,
        "delete": PermissionCode.REPORTS_VIEW.value,
    },
    {
        "menu": "Staff & User Roles (Main Menu)",
        "is_parent": True,
        "view": PermissionCode.USERS_MANAGE.value,
        "create": PermissionCode.USERS_MANAGE.value,
        "edit": PermissionCode.USERS_MANAGE.value,
        "delete": PermissionCode.USERS_MANAGE.value,
    },
    {
        "menu": "System Settings & Branches (Main Menu)",
        "is_parent": True,
        "view": PermissionCode.SETTINGS_MANAGE.value,
        "create": PermissionCode.BRANCHES_MANAGE.value,
        "edit": PermissionCode.SETTINGS_MANAGE.value,
        "delete": PermissionCode.SUBSCRIPTIONS_MANAGE.value,
    },
    {
        "menu": "Audit Log & Security (Main Menu)",
        "is_parent": True,
        "view": PermissionCode.AUDIT_VIEW.value,
        "create": PermissionCode.AUDIT_VIEW.value,
        "edit": PermissionCode.AUDIT_VIEW.value,
        "delete": PermissionCode.AUDIT_VIEW.value,
    },
]


class CreateRoleDialog(QDialog):
    """Dialog to create a new role name and description."""

    def __init__(self, parent, user_service, session):
        super().__init__(parent)
        self.user_service = user_service
        self.session = session
        self.created_role_id = None

        self.setWindowTitle("Create New System Role")
        self.setMinimumWidth(460)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        banner = DialogHeaderBanner(
            title="Create Custom Staff Role",
            subtitle="Define a job role (e.g. Senior Pharmacist, Cashier Supervisor)",
            parent_dialog=self,
        )
        layout.addWidget(banner)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(24, 18, 24, 22)
        body_layout.setSpacing(14)

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Role Name (e.g. Senior Cashier) *")
        body_layout.addWidget(self.name_input)

        self.desc_input = QLineEdit()
        self.desc_input.setPlaceholderText("Description (Optional)")
        body_layout.addWidget(self.desc_input)

        self.error_label = QLabel("")
        self.error_label.setStyleSheet("color: #EF4444; font-size: 12px; font-weight: 600;")
        body_layout.addWidget(self.error_label)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("SecondaryBtn")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        save_btn = QPushButton("Create Role")
        save_btn.setStyleSheet("background-color: #2563EB; color: white; font-weight: 700; padding: 8px 16px; border-radius: 6px;")
        save_btn.clicked.connect(self._on_save)
        btn_layout.addWidget(save_btn)

        body_layout.addLayout(btn_layout)
        layout.addWidget(body)

    def _on_save(self):
        name = self.name_input.text().strip()
        desc = self.desc_input.strip() if hasattr(self.desc_input, "strip") else self.desc_input.text().strip()
        if not name:
            self.error_label.setText("Role name is required.")
            self.name_input.setFocus()
            return

        try:
            role = self.user_service.create_role(
                user_session=self.session,
                name=name,
                description=desc,
                permission_codes=[],
            )
            self.created_role_id = role.id
            self.accept()
        except Exception as e:
            self.error_label.setText(str(e))


class RolePermissionMatrixWidget(QWidget):
    """
    Full-featured Roles & Permissions Matrix Editor matching the enterprise standard.
    Displays Menu/Module rows with View, Create, Edit, and Delete action checkboxes.
    Every cell in the matrix is interactive and independently saved.
    """

    COL_KEYS = ["view", "create", "edit", "delete"]

    def __init__(self, session, user_service=None):
        super().__init__()
        self.session = session
        self.user_service = user_service
        self.roles = []
        self.selected_role = None
        self.active_perm_codes = set()
        self.checkbox_map = {}  # (row_idx, col_idx) -> (MatrixCheckBox, perm_code, cell_token)
        self._updating_checks = False

        self.init_ui()
        self.refresh_roles()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(14)

        # Top Control Bar: Role selection and action buttons
        top_bar = QFrame()
        top_bar.setStyleSheet("background: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 8px; padding: 6px;")
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(14, 10, 14, 10)
        top_layout.setSpacing(12)

        role_lbl = QLabel("Active Role:")
        role_lbl.setStyleSheet("font-weight: 700; font-size: 13px; color: #1E293B; border: none;")
        top_layout.addWidget(role_lbl)

        self.role_combo = QComboBox()
        self.role_combo.setMinimumWidth(220)
        self.role_combo.currentIndexChanged.connect(self._on_role_selected)
        top_layout.addWidget(self.role_combo)

        self.new_role_btn = QPushButton("+ New Role")
        self.new_role_btn.setObjectName("SecondaryBtn")
        self.new_role_btn.clicked.connect(self._on_create_role)
        top_layout.addWidget(self.new_role_btn)

        top_layout.addStretch()

        self.check_all_btn = QPushButton("☑️ Check All")
        self.check_all_btn.setObjectName("SecondaryBtn")
        self.check_all_btn.clicked.connect(self._check_all)
        top_layout.addWidget(self.check_all_btn)

        self.clear_all_btn = QPushButton("⬜ Clear All")
        self.clear_all_btn.setObjectName("SecondaryBtn")
        self.clear_all_btn.clicked.connect(self._clear_all)
        top_layout.addWidget(self.clear_all_btn)

        self.save_btn = QPushButton("💾 Save Permissions")
        self.save_btn.setStyleSheet(
            "background-color: #10B981; color: white; font-weight: 700; padding: 8px 18px; border-radius: 6px;"
        )
        self.save_btn.clicked.connect(self._save_permissions)
        top_layout.addWidget(self.save_btn)

        layout.addWidget(top_bar)

        # Role Information Bar
        info_bar = QHBoxLayout()
        info_bar.setSpacing(12)

        self.role_name_input = QLineEdit()
        self.role_name_input.setPlaceholderText("Role Name")
        self.role_name_input.setStyleSheet("font-weight: 600; font-size: 13px;")

        self.role_desc_input = QLineEdit()
        self.role_desc_input.setPlaceholderText("Role Description")

        info_bar.addWidget(QLabel("Role Details:"))
        info_bar.addWidget(self.role_name_input, 1)
        info_bar.addWidget(self.role_desc_input, 2)
        layout.addLayout(info_bar)

        self.status_msg = QLabel("")
        self.status_msg.setStyleSheet("font-size: 12px; font-weight: 600;")
        layout.addWidget(self.status_msg)

        # Permissions Matrix Table
        self.table = QTableWidget(len(MATRIX_ROWS), 5)
        self.table.setHorizontalHeaderLabels(["Menu / Feature", "View", "Create", "Edit", "Delete"])
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.Fixed)
        hdr.setSectionResizeMode(2, QHeaderView.Fixed)
        hdr.setSectionResizeMode(3, QHeaderView.Fixed)
        hdr.setSectionResizeMode(4, QHeaderView.Fixed)

        self.table.setColumnWidth(1, 100)
        self.table.setColumnWidth(2, 100)
        self.table.setColumnWidth(3, 100)
        self.table.setColumnWidth(4, 100)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.verticalHeader().setDefaultSectionSize(38)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)

        self._build_table_rows()
        layout.addWidget(self.table)

    def _build_table_rows(self):
        self.checkbox_map.clear()
        bold_font = QFont()
        bold_font.setBold(True)
        bold_font.setPointSize(10)

        normal_font = QFont()
        normal_font.setPointSize(10)

        parent_color = QColor("#0F172A")
        sub_color = QColor("#334155")
        parent_bg = QColor("#F8FAFC")

        for row_idx, rdata in enumerate(MATRIX_ROWS):
            menu_text = rdata["menu"]
            is_parent = bool(rdata.get("is_parent"))
            item = QTableWidgetItem(menu_text)
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            if is_parent:
                item.setFont(bold_font)
                item.setForeground(QBrush(parent_color))
                item.setBackground(QBrush(parent_bg))
            else:
                item.setFont(normal_font)
                item.setForeground(QBrush(sub_color))
            self.table.setItem(row_idx, 0, item)

            for col_idx, key in enumerate(self.COL_KEYS, start=1):
                pcode = rdata.get(key)
                cell_token = f"matrix.r{row_idx}.{key}"

                cb = MatrixCheckBox(is_parent=is_parent)
                cb.setToolTip(f"{menu_text.strip()} — {key.title()}")
                cb.toggled.connect(
                    lambda checked, r=row_idx, c=col_idx, parent_row=is_parent: self._on_checkbox_toggled(
                        r, c, checked, parent_row
                    )
                )

                self.checkbox_map[(row_idx, col_idx)] = (cb, pcode, cell_token)
                cell_widget = MatrixCellWidget(cb)
                self.table.setCellWidget(row_idx, col_idx, cell_widget)

    def _on_checkbox_toggled(self, row_idx: int, col_idx: int, checked: bool, is_parent: bool):
        """When a Main Menu parent checkbox is toggled, cascade to its child sub-rows in the same column."""
        if self._updating_checks:
            return
        if is_parent:
            self._updating_checks = True
            try:
                next_row = row_idx + 1
                while next_row < len(MATRIX_ROWS) and not MATRIX_ROWS[next_row].get("is_parent"):
                    entry = self.checkbox_map.get((next_row, col_idx))
                    if entry:
                        entry[0].setChecked(checked)
                    next_row += 1
            finally:
                self._updating_checks = False

    def refresh_roles(self):
        if not self.user_service or not self.session.organization_id:
            return

        try:
            self.user_service.ensure_default_roles(self.session)
            self.roles = self.user_service.list_roles(self.session.organization_id)
            self.role_combo.blockSignals(True)
            self.role_combo.clear()
            for r in self.roles:
                label = f"{r.name} (Default)" if r.is_system else r.name
                self.role_combo.addItem(label, r.id)
            self.role_combo.blockSignals(False)

            if self.roles:
                self._load_role(self.roles[0].id)
        except Exception as e:
            self.status_msg.setStyleSheet("color: #EF4444;")
            self.status_msg.setText(f"Error loading roles: {str(e)}")

    def _on_role_selected(self, index):
        if index < 0:
            return
        role_id = self.role_combo.currentData()
        if role_id:
            self._load_role(role_id)

    def _load_role(self, role_id: str):
        self.selected_role = next((r for r in self.roles if r.id == role_id), None)
        if not self.selected_role:
            return

        self.role_name_input.setText(self.selected_role.name)
        self.role_desc_input.setText(self.selected_role.description or "")

        try:
            assigned = set(self.user_service.get_role_permissions(role_id))
            self.active_perm_codes = assigned
            has_custom_matrix = "matrix.configured" in assigned or any(
                c.startswith("matrix.r") for c in assigned
            )

            self._updating_checks = True
            try:
                checked_count = 0
                for (r_idx, c_idx), (cb, pcode, cell_token) in self.checkbox_map.items():
                    if has_custom_matrix:
                        is_checked = cell_token in assigned
                    else:
                        is_checked = bool(pcode and pcode in assigned)
                    cb.setChecked(is_checked)
                    if is_checked:
                        checked_count += 1
            finally:
                self._updating_checks = False

            canonical_count = len([c for c in assigned if not c.startswith("matrix.")])
            self.status_msg.setStyleSheet("color: #64748B;")
            self.status_msg.setText(
                f"Loaded {canonical_count} system permissions ({checked_count} matrix actions checked) for '{self.selected_role.name}'."
            )
        except Exception as e:
            self.status_msg.setStyleSheet("color: #EF4444;")
            self.status_msg.setText(f"Failed to load permissions: {str(e)}")

    def _check_all(self):
        self._updating_checks = True
        try:
            for (r_idx, c_idx), (cb, pcode, cell_token) in self.checkbox_map.items():
                if cb.isEnabled():
                    cb.setChecked(True)
        finally:
            self._updating_checks = False

    def _clear_all(self):
        self._updating_checks = True
        try:
            for (r_idx, c_idx), (cb, pcode, cell_token) in self.checkbox_map.items():
                cb.setChecked(False)
        finally:
            self._updating_checks = False

    def _on_create_role(self):
        dlg = CreateRoleDialog(self, self.user_service, self.session)
        if dlg.exec() and dlg.created_role_id:
            self.refresh_roles()
            idx = self.role_combo.findData(dlg.created_role_id)
            if idx >= 0:
                self.role_combo.setCurrentIndex(idx)

    def _save_permissions(self):
        if not self.selected_role:
            return

        name = self.role_name_input.text().strip()
        desc = self.role_desc_input.text().strip()
        if not name:
            QMessageBox.warning(self, "Validation Error", "Role name cannot be empty.")
            return

        selected_pcodes = ["matrix.configured"]
        checked_boxes = 0
        for (r_idx, c_idx), (cb, pcode, cell_token) in self.checkbox_map.items():
            if cb.isChecked():
                checked_boxes += 1
                selected_pcodes.append(cell_token)
                if pcode and pcode not in selected_pcodes:
                    selected_pcodes.append(pcode)

        try:
            self.user_service.update_role_permissions(
                user_session=self.session,
                role_id=self.selected_role.id,
                permission_codes=selected_pcodes,
                name=name,
                description=desc,
            )
            self.status_msg.setStyleSheet("color: #10B981; font-weight: 700;")
            self.status_msg.setText(
                f"✓ Successfully saved {checked_boxes} checked matrix actions for role '{name}'!"
            )
            QMessageBox.information(
                self,
                "Permissions Updated",
                f"Permissions for role '{name}' have been saved successfully.\n"
                f"Staff accounts assigned to this role will now reflect these access rights.",
            )
            self.refresh_roles()
            idx = self.role_combo.findData(self.selected_role.id)
            if idx >= 0:
                self.role_combo.setCurrentIndex(idx)
        except Exception as e:
            self.status_msg.setStyleSheet("color: #EF4444; font-weight: 700;")
            self.status_msg.setText(f"Save failed: {str(e)}")
