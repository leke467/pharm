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
    QDoubleSpinBox,
    QDateEdit,
    QGridLayout,
)
from PySide6.QtCore import Qt, QTimer, QDate
from desktop.app.services.expense_service import ExpenseService
from desktop.app.ui.common.title_bar import DialogHeaderBanner
from shared.enums import PermissionCode, ExpenseStatus


class CreateExpenseCategoryDialog(QDialog):
    """Modal dialog to create an expense category."""

    def __init__(self, parent, expense_service, session):
        super().__init__(parent)
        self.expense_service = expense_service
        self.session = session
        self.created_category = None

        self.setWindowTitle("Add Expense Category")
        self.setMinimumWidth(420)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        banner = DialogHeaderBanner(
            title="New Expense Category",
            subtitle="Define a financial classification for operational vouchers",
            parent_dialog=self,
        )
        layout.addWidget(banner)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(24, 18, 24, 20)
        body_layout.setSpacing(12)

        self.name_in = QLineEdit()
        self.name_in.setPlaceholderText("Category Name (e.g. Utilities, Fuel, Rent) *")
        body_layout.addWidget(self.name_in)

        self.desc_in = QLineEdit()
        self.desc_in.setPlaceholderText("Description (Optional)")
        body_layout.addWidget(self.desc_in)

        self.err_lbl = QLabel("")
        self.err_lbl.setStyleSheet("color: #EF4444; font-size: 12px; font-weight: 600;")
        body_layout.addWidget(self.err_lbl)

        btn_box = QHBoxLayout()
        btn_box.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("SecondaryBtn")
        cancel_btn.clicked.connect(self.reject)
        btn_box.addWidget(cancel_btn)

        save_btn = QPushButton("Save Category")
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
            self.err_lbl.setText("Category name is required.")
            self.name_in.setFocus()
            return
        try:
            cat = self.expense_service.create_category(
                user_session=self.session,
                name=name,
                description=self.desc_in.text().strip(),
            )
            self.created_category = cat
            self.accept()
        except Exception as e:
            self.err_lbl.setText(f"Error: {str(e)}")


class CreateExpenseDialog(QDialog):
    """Modal dialog to record a new operational expense voucher."""

    def __init__(self, parent, expense_service, session):
        super().__init__(parent)
        self.expense_service = expense_service
        self.session = session
        self.categories = []

        self.setWindowTitle("Record Branch Expense")
        self.setMinimumWidth(480)
        self.init_ui()
        self.load_categories()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        banner = DialogHeaderBanner(
            title="Record Expense / Payment Voucher",
            subtitle="Record operational costs, petty cash disbursements, or bill payments",
            parent_dialog=self,
        )
        layout.addWidget(banner)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(24, 18, 24, 22)
        body_layout.setSpacing(14)

        grid = QGridLayout()
        grid.setSpacing(10)

        # Category with + New button
        cat_layout = QHBoxLayout()
        self.cat_combo = QComboBox()
        cat_layout.addWidget(self.cat_combo, stretch=1)

        new_cat_btn = QPushButton("+ New")
        new_cat_btn.setObjectName("SecondaryBtn")
        new_cat_btn.clicked.connect(self._open_new_cat_dialog)
        cat_layout.addWidget(new_cat_btn)

        self.amount_spin = QDoubleSpinBox()
        self.amount_spin.setRange(0.01, 100000000)
        self.amount_spin.setDecimals(2)
        self.amount_spin.setPrefix("₦ ")
        self.amount_spin.setValue(5000.00)

        self.desc_in = QLineEdit()
        self.desc_in.setPlaceholderText("Voucher description / purpose *")

        self.method_combo = QComboBox()
        self.method_combo.addItems(["CASH", "BANK_TRANSFER", "POS_CARD", "CHEQUE"])

        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDate(QDate.currentDate())

        self.notes_in = QLineEdit()
        self.notes_in.setPlaceholderText("Invoice/receipt reference or remarks...")

        grid.addWidget(QLabel("Category *:"), 0, 0)
        grid.addLayout(cat_layout, 0, 1)

        grid.addWidget(QLabel("Amount (NGN) *:"), 1, 0)
        grid.addWidget(self.amount_spin, 1, 1)

        grid.addWidget(QLabel("Description *:"), 2, 0)
        grid.addWidget(self.desc_in, 2, 1)

        grid.addWidget(QLabel("Payment Method:"), 3, 0)
        grid.addWidget(self.method_combo, 3, 1)

        grid.addWidget(QLabel("Expense Date:"), 4, 0)
        grid.addWidget(self.date_edit, 4, 1)

        grid.addWidget(QLabel("Reference / Notes:"), 5, 0)
        grid.addWidget(self.notes_in, 5, 1)

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

        save_btn = QPushButton("Record Expense")
        save_btn.setStyleSheet(
            "background-color: #10B981; color: white; font-weight: 700; padding: 9px 20px; border-radius: 6px;"
        )
        save_btn.clicked.connect(self.on_save)
        btn_box.addWidget(save_btn)

        body_layout.addLayout(btn_box)
        layout.addWidget(body)

    def load_categories(self):
        try:
            self.categories = self.expense_service.list_categories(self.session.organization_id)
            self.cat_combo.clear()
            for c in self.categories:
                self.cat_combo.addItem(c.name, c.id)
        except Exception:
            self.categories = []

        if not self.categories:
            # Seed default categories if empty
            try:
                for default_cat in ["Utilities & Electricity", "Generator & Fuel", "Office & Pharmacy Supplies", "Repairs & Maintenance", "Transportation & Delivery", "Staff Refreshments", "Miscellaneous Overhead"]:
                    self.expense_service.create_category(self.session, default_cat)
                self.categories = self.expense_service.list_categories(self.session.organization_id)
                self.cat_combo.clear()
                for c in self.categories:
                    self.cat_combo.addItem(c.name, c.id)
            except Exception:
                pass

    def _open_new_cat_dialog(self):
        dlg = CreateExpenseCategoryDialog(self, self.expense_service, self.session)
        if dlg.exec() and dlg.created_category:
            self.load_categories()
            idx = self.cat_combo.findData(dlg.created_category.id)
            if idx >= 0:
                self.cat_combo.setCurrentIndex(idx)

    def on_save(self):
        cat_id = self.cat_combo.currentData()
        if not cat_id:
            self.err_lbl.setText("Please select or create an expense category.")
            return

        desc = self.desc_in.text().strip()
        if not desc:
            self.err_lbl.setText("Description is required.")
            self.desc_in.setFocus()
            return

        amt = self.amount_spin.value()
        if amt <= 0:
            self.err_lbl.setText("Amount must be greater than zero.")
            return

        try:
            self.expense_service.record_expense(
                user_session=self.session,
                expense_category_id=cat_id,
                description=desc,
                amount=str(amt),
                payment_method=self.method_combo.currentText(),
                expense_date=self.date_edit.date().toString(Qt.ISODate),
                notes=self.notes_in.text().strip(),
            )
            QMessageBox.information(
                self,
                "Expense Recorded",
                f"Expense voucher for ₦ {amt:,.2f} recorded successfully.",
            )
            self.accept()
        except Exception as e:
            self.err_lbl.setText(f"Error: {str(e)}")


class ExpensesWidget(QWidget):
    """
    Phase 12 Expenses UI widget.
    Displays expenses, categories, approval statuses, amounts, and allows recording & approving vouchers.
    """

    def __init__(self, db_manager, get_session_callable, parent=None):
        super().__init__(parent)
        self.db_manager = db_manager
        self.get_session = get_session_callable
        self.expense_service = ExpenseService(db_manager)

        # Pagination & Data Cache
        self.all_expenses = []
        self.filtered_expenses = []
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

        title = QLabel("Branch Expenses")
        title.setObjectName("PageHeader")
        subtitle = QLabel("Track operational overhead, petty cash vouchers, approval workflows & categories")
        subtitle.setObjectName("PageSubtitle")
        title_col.addWidget(title)
        title_col.addWidget(subtitle)
        header_layout.addLayout(title_col)
        header_layout.addStretch()

        self.create_exp_btn = QPushButton("+ Record Expense")
        self.create_exp_btn.setStyleSheet(
            "background-color: #10B981; color: white; font-weight: 700; padding: 9px 18px; border-radius: 6px;"
        )
        self.create_exp_btn.clicked.connect(self._open_create_expense_dialog)
        header_layout.addWidget(self.create_exp_btn)

        self.approve_btn = QPushButton("✓ Approve Voucher")
        self.approve_btn.setStyleSheet(
            "background-color: #059669; color: white; font-weight: 700; padding: 9px 18px; border-radius: 6px;"
        )
        self.approve_btn.clicked.connect(self._on_approve_selected)
        header_layout.addWidget(self.approve_btn)

        self.reject_btn = QPushButton("✗ Reject Voucher")
        self.reject_btn.setStyleSheet(
            "background-color: #EF4444; color: white; font-weight: 700; padding: 9px 18px; border-radius: 6px;"
        )
        self.reject_btn.clicked.connect(self._on_reject_selected)
        header_layout.addWidget(self.reject_btn)

        self.create_cat_btn = QPushButton("+ New Category")
        self.create_cat_btn.setObjectName("SecondaryBtn")
        self.create_cat_btn.clicked.connect(self._open_create_category_dialog)
        header_layout.addWidget(self.create_cat_btn)

        self.refresh_btn = QPushButton("Refresh Data")
        self.refresh_btn.setObjectName("SecondaryBtn")
        self.refresh_btn.clicked.connect(self.refresh_data)
        header_layout.addWidget(self.refresh_btn)
        layout.addLayout(header_layout)

        # Search Bar
        search_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search expenses by category, description, payment method, or status...")
        self.search_input.textChanged.connect(lambda: self.search_timer.start())
        search_layout.addWidget(self.search_input)
        layout.addLayout(search_layout)

        # Table (Clean 6 columns)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels([
            "Expense Date",
            "Category",
            "Description",
            "Amount (NGN)",
            "Payment Method",
            "Approval Status",
        ])
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.Interactive)
        hdr.setSectionResizeMode(1, QHeaderView.Interactive)
        hdr.setSectionResizeMode(2, QHeaderView.Stretch)
        hdr.setSectionResizeMode(3, QHeaderView.Interactive)
        hdr.setSectionResizeMode(4, QHeaderView.Interactive)
        hdr.setSectionResizeMode(5, QHeaderView.Interactive)

        self.table.setColumnWidth(0, 130)
        self.table.setColumnWidth(1, 160)
        self.table.setColumnWidth(3, 150)
        self.table.setColumnWidth(4, 140)
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

        self.page_status_label = QLabel("Showing 0 expenses")
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

    def _open_create_expense_dialog(self):
        session = self.get_session()
        if not session:
            return
        dlg = CreateExpenseDialog(self, self.expense_service, session)
        if dlg.exec():
            self.refresh_data()

    def _open_create_category_dialog(self):
        session = self.get_session()
        if not session:
            return
        dlg = CreateExpenseCategoryDialog(self, self.expense_service, session)
        if dlg.exec():
            self.refresh_data()

    def _approve_expense(self, exp_id: str):
        session = self.get_session()
        if not session:
            return
        try:
            self.expense_service.approve_expense(session, exp_id)
            self.refresh_data()
        except Exception as e:
            QMessageBox.critical(self, "Approval Failed", str(e))

    def _reject_expense(self, exp_id: str):
        session = self.get_session()
        if not session:
            return
        try:
            self.expense_service.reject_expense(session, exp_id)
            self.refresh_data()
        except Exception as e:
            QMessageBox.critical(self, "Rejection Failed", str(e))

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
        self.all_expenses = self.expense_service.list_expenses(session.branch_id)
        self._apply_filter_and_render()

    def _apply_filter_and_render(self):
        query = self.search_input.text().strip().lower()
        if not query:
            self.filtered_expenses = list(self.all_expenses)
        else:
            self.filtered_expenses = [
                e for e in self.all_expenses
                if query in (e.get('category_name') or "").lower()
                or query in (e.get('description') or "").lower()
                or query in (e.get('payment_method') or "").lower()
                or query in (e.get('status') or "").lower()
                or query in str(e.get('expense_date') or "").lower()
            ]
        self.current_page = 1
        self._render_current_page()

    def _render_current_page(self):
        total_count = len(self.filtered_expenses)
        self.total_pages = max(1, (total_count + self.page_size - 1) // self.page_size) if self.page_size > 0 else 1
        self.current_page = min(self.current_page, self.total_pages)

        start_idx = (self.current_page - 1) * self.page_size
        end_idx = min(start_idx + self.page_size, total_count)
        page_items = self.filtered_expenses[start_idx:end_idx]

        session = self.get_session()
        can_approve = session.has_permission(PermissionCode.EXPENSES_APPROVE.value) if session else True

        self.table.setUpdatesEnabled(False)
        self.table.blockSignals(True)
        try:
            self.table.setRowCount(len(page_items))
            for idx, e in enumerate(page_items):
                self.table.setItem(idx, 0, QTableWidgetItem(str(e.get('expense_date', ''))))
                self.table.setItem(idx, 1, QTableWidgetItem(e.get('category_name', '')))
                self.table.setItem(idx, 2, QTableWidgetItem(e.get('description', '')))

                amt_val = Decimal(str(e.get('amount', 0)))
                amt_item = QTableWidgetItem(f"{amt_val:,.2f}")
                amt_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(idx, 3, amt_item)

                self.table.setItem(idx, 4, QTableWidgetItem(e.get('payment_method', '')))
                self.table.setItem(idx, 5, QTableWidgetItem(e.get('status', '')))
        finally:
            self.table.blockSignals(False)
            self.table.setUpdatesEnabled(True)

        if total_count == 0:
            self.page_status_label.setText("Showing 0 expenses")
        else:
            self.page_status_label.setText(f"Showing {start_idx + 1}–{end_idx} of {total_count} expenses")
        self.page_info_label.setText(f"Page {self.current_page} of {self.total_pages}")
        self.prev_page_btn.setEnabled(self.current_page > 1)
        self.next_page_btn.setEnabled(self.current_page < self.total_pages)

    def _on_approve_selected(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(
                self,
                "Selection Required",
                "Please click a row in the table to select an expense voucher first."
            )
            return
        start_idx = (self.current_page - 1) * self.page_size
        idx = start_idx + row
        if 0 <= idx < len(self.filtered_expenses):
            exp = self.filtered_expenses[idx]
            self._approve_expense(exp.get('id', ''))

    def _on_reject_selected(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(
                self,
                "Selection Required",
                "Please click a row in the table to select an expense voucher first."
            )
            return
        start_idx = (self.current_page - 1) * self.page_size
        idx = start_idx + row
        if 0 <= idx < len(self.filtered_expenses):
            exp = self.filtered_expenses[idx]
            self._reject_expense(exp.get('id', ''))

    def _on_table_double_clicked(self, row, col):
        start_idx = (self.current_page - 1) * self.page_size
        idx = start_idx + row
        if 0 <= idx < len(self.filtered_expenses):
            exp = self.filtered_expenses[idx]
            status_val = exp.get('status', '')
            if status_val in (ExpenseStatus.DRAFT.value, ExpenseStatus.PENDING_APPROVAL.value):
                reply = QMessageBox.question(
                    self,
                    "Approve Expense Voucher",
                    f"Would you like to approve this voucher of ₦ {float(exp.get('amount', 0)):,.2f} for '{exp.get('description', '')}'?",
                    QMessageBox.Yes | QMessageBox.No
                )
                if reply == QMessageBox.Yes:
                    self._approve_expense(exp.get('id', ''))
