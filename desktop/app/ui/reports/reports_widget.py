from datetime import date, timedelta
from decimal import Decimal
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QPushButton,
    QComboBox,
    QHeaderView,
    QFrame,
    QGridLayout,
)
from PySide6.QtCore import Qt
from desktop.app.services.report_service import ReportService


class ReportsWidget(QWidget):
    """
    Phase 14 Reports & Analytics Widget (Architecture Plan §14).
    Provides Sales, Inventory Valuation & Expiry, Profit & Loss, and Cashier Shift reports.
    """

    def __init__(self, db_manager, get_session_callable, parent=None):
        super().__init__(parent)
        self.db_manager = db_manager
        self.get_session = get_session_callable
        self.report_service = ReportService(db_manager)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        # Header
        header_layout = QHBoxLayout()
        title_col = QVBoxLayout()
        title_col.setSpacing(4)

        title = QLabel("Reports & Analytics")
        title.setObjectName("PageHeader")
        subtitle = QLabel("Financial summaries, sales breakdowns, inventory valuation, P&L statements and cashier shifts")
        subtitle.setObjectName("PageSubtitle")
        title_col.addWidget(title)
        title_col.addWidget(subtitle)
        header_layout.addLayout(title_col)
        header_layout.addStretch()

        period_lbl = QLabel("Period:")
        period_lbl.setStyleSheet("font-size: 12px; font-weight: 600; color: #64748B;")
        self.period_combo = QComboBox()
        self.period_combo.addItems(["Today", "Last 7 Days", "Last 30 Days", "All Time"])
        self.period_combo.currentIndexChanged.connect(self.refresh_all_reports)
        header_layout.addWidget(period_lbl)
        header_layout.addWidget(self.period_combo)

        self.refresh_btn = QPushButton("Refresh Reports")
        self.refresh_btn.setObjectName("SecondaryBtn")
        self.refresh_btn.clicked.connect(self.refresh_all_reports)
        header_layout.addWidget(self.refresh_btn)

        layout.addLayout(header_layout)

        # Tabs
        self.tabs = QTabWidget()

        # Tab 1: Sales Summary
        self.sales_tab = QWidget()
        self._setup_sales_tab()
        self.tabs.addTab(self.sales_tab, "Sales Summary")

        # Tab 2: Inventory & Expiry
        self.inventory_tab = QWidget()
        self._setup_inventory_tab()
        self.tabs.addTab(self.inventory_tab, "Inventory & Expiry")

        # Tab 3: Profit & Loss
        self.pnl_tab = QWidget()
        self._setup_pnl_tab()
        self.tabs.addTab(self.pnl_tab, "Profit & Loss")

        # Tab 4: Cashier Shifts
        self.shifts_tab = QWidget()
        self._setup_shifts_tab()
        self.tabs.addTab(self.shifts_tab, "Cashier Shifts")

        layout.addWidget(self.tabs)

    def _get_date_range(self):
        idx = self.period_combo.currentIndex()
        today = date.today()
        if idx == 0:  # Today
            return today.isoformat(), None
        elif idx == 1:  # Last 7 Days
            return (today - timedelta(days=7)).isoformat(), None
        elif idx == 2:  # Last 30 Days
            return (today - timedelta(days=30)).isoformat(), None
        else:  # All Time
            return None, None

    # --- Sales Tab ---
    def _setup_sales_tab(self):
        l = QVBoxLayout(self.sales_tab)
        self.sales_metrics = QLabel("Total Revenue: 0.00 | Transactions: 0 | Items Sold: 0")
        self.sales_metrics.setStyleSheet("font-size: 14px; font-weight: bold; margin: 8px 0;")
        l.addWidget(self.sales_metrics)

        l.addWidget(QLabel("Payment Method Breakdown:"))
        self.payments_table = QTableWidget(0, 3)
        self.payments_table.setHorizontalHeaderLabels(["Payment Method", "Total Collected (NGN)", "Count"])
        self.payments_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.payments_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.payments_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.payments_table.setSelectionMode(QTableWidget.SingleSelection)
        self.payments_table.verticalHeader().setVisible(False)
        self.payments_table.setAlternatingRowColors(True)
        l.addWidget(self.payments_table)

    def _refresh_sales(self):
        session = self.get_session()
        if not session:
            return
        start, end = self._get_date_range()
        data = self.report_service.get_sales_summary(
            session.organization_id,
            branch_id=session.branch_id,
            start_date=start,
            end_date=end,
        )
        rev = Decimal(data.get("total_revenue", "0.00"))
        gp = Decimal(data.get("gross_profit", "0.00"))
        self.sales_metrics.setText(
            f"Total Revenue: {rev:,.2f} | Gross Profit: {gp:,.2f} | "
            f"Sales Count: {data.get('total_sales_count', 0)} | Items Sold: {data.get('total_items_sold', 0)}"
        )

        payments = data.get("payment_breakdown", [])
        self.payments_table.setUpdatesEnabled(False)
        self.payments_table.blockSignals(True)
        try:
            self.payments_table.setRowCount(len(payments))
            for idx, p in enumerate(payments):
                self.payments_table.setItem(idx, 0, QTableWidgetItem(str(p['method'])))
                self.payments_table.setItem(idx, 1, QTableWidgetItem(f"{Decimal(p['total']):,.2f}"))
                self.payments_table.setItem(idx, 2, QTableWidgetItem(str(p['count'])))
        finally:
            self.payments_table.blockSignals(False)
            self.payments_table.setUpdatesEnabled(True)

    # --- Inventory Tab ---
    def _setup_inventory_tab(self):
        l = QVBoxLayout(self.inventory_tab)
        self.inv_metrics = QLabel("Valuation (Cost): 0.00 | Units in Stock: 0 | Low Stock: 0")
        self.inv_metrics.setStyleSheet("font-size: 14px; font-weight: bold; margin: 8px 0;")
        l.addWidget(self.inv_metrics)

        l.addWidget(QLabel("Low Stock Items:"))
        self.low_stock_table = QTableWidget(0, 4)
        self.low_stock_table.setHorizontalHeaderLabels(["Product", "Batch", "Quantity", "Reorder Level"])
        self.low_stock_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.low_stock_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.low_stock_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.low_stock_table.setSelectionMode(QTableWidget.SingleSelection)
        self.low_stock_table.verticalHeader().setVisible(False)
        self.low_stock_table.setAlternatingRowColors(True)
        l.addWidget(self.low_stock_table)

    def _refresh_inventory(self):
        session = self.get_session()
        if not session:
            return
        data = self.report_service.get_inventory_valuation(
            session.organization_id,
            branch_id=session.branch_id,
        )
        cost_val = Decimal(data.get("total_cost_valuation", "0.00"))
        units = data.get("total_units_in_stock", 0)
        low = data.get("low_stock_count", 0)
        expired = data.get("expired_batches_count", 0)
        expiring = data.get("expiring_soon_batches_count", 0)

        self.inv_metrics.setText(
            f"Valuation (Cost): {cost_val:,.2f} | Units in Stock: {units:,} | "
            f"Low Stock: {low} | Expired: {expired} | Expiring Soon: {expiring}"
        )

        items = data.get("low_stock_items", [])
        self.low_stock_table.setUpdatesEnabled(False)
        self.low_stock_table.blockSignals(True)
        try:
            self.low_stock_table.setRowCount(len(items))
            for idx, it in enumerate(items):
                self.low_stock_table.setItem(idx, 0, QTableWidgetItem(it.get('product_name', '')))
                self.low_stock_table.setItem(idx, 1, QTableWidgetItem(it.get('batch_number', '')))
                self.low_stock_table.setItem(idx, 2, QTableWidgetItem(str(it.get('current_quantity', 0))))
                self.low_stock_table.setItem(idx, 3, QTableWidgetItem(str(it.get('reorder_level', 0))))
        finally:
            self.low_stock_table.blockSignals(False)
            self.low_stock_table.setUpdatesEnabled(True)

    # --- Profit & Loss Tab ---
    def _setup_pnl_tab(self):
        l = QVBoxLayout(self.pnl_tab)
        self.pnl_frame = QFrame()
        self.pnl_frame.setStyleSheet("background-color: #f8fafc; border: 1px solid #cbd5e1; border-radius: 8px; padding: 20px;")
        grid = QGridLayout(self.pnl_frame)

        self.pnl_rev = QLabel("0.00")
        self.pnl_cogs = QLabel("0.00")
        self.pnl_gp = QLabel("0.00")
        self.pnl_exp = QLabel("0.00")
        self.pnl_net = QLabel("0.00")

        self.pnl_gp.setStyleSheet("font-weight: bold; color: #0369a1;")
        self.pnl_net.setStyleSheet("font-size: 18px; font-weight: bold; color: #15803d;")

        grid.addWidget(QLabel("1. Revenue:"), 0, 0)
        grid.addWidget(self.pnl_rev, 0, 1)

        grid.addWidget(QLabel("2. Cost of Goods Sold (COGS):"), 1, 0)
        grid.addWidget(self.pnl_cogs, 1, 1)

        grid.addWidget(QLabel("3. Gross Profit (Revenue - COGS):"), 2, 0)
        grid.addWidget(self.pnl_gp, 2, 1)

        grid.addWidget(QLabel("4. Operating Expenses:"), 3, 0)
        grid.addWidget(self.pnl_exp, 3, 1)

        grid.addWidget(QLabel("5. Net Profit (Gross Profit - Expenses):"), 4, 0)
        grid.addWidget(self.pnl_net, 4, 1)

        l.addWidget(self.pnl_frame)
        l.addStretch()

    def _refresh_pnl(self):
        session = self.get_session()
        if not session:
            return
        start, end = self._get_date_range()
        data = self.report_service.get_profit_loss(
            session.organization_id,
            branch_id=session.branch_id,
            start_date=start,
            end_date=end,
        )
        self.pnl_rev.setText(f"{Decimal(data['revenue']):,.2f}")
        self.pnl_cogs.setText(f"{Decimal(data['cost_of_goods_sold']):,.2f}")
        self.pnl_gp.setText(f"{Decimal(data['gross_profit']):,.2f}")
        self.pnl_exp.setText(f"{Decimal(data['operating_expenses']):,.2f}")
        self.pnl_net.setText(f"{Decimal(data['net_profit']):,.2f}")

    # --- Cashier Shifts Tab ---
    def _setup_shifts_tab(self):
        l = QVBoxLayout(self.shifts_tab)
        l.addWidget(QLabel("Today's Cashier Sales & Reconciliation:"))
        self.shifts_table = QTableWidget(0, 4)
        self.shifts_table.setHorizontalHeaderLabels(["Cashier", "Full Name", "Sales Count", "Total Collected (NGN)"])
        self.shifts_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.shifts_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.shifts_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.shifts_table.setSelectionMode(QTableWidget.SingleSelection)
        self.shifts_table.verticalHeader().setVisible(False)
        self.shifts_table.setAlternatingRowColors(True)
        l.addWidget(self.shifts_table)

    def _refresh_shifts(self):
        session = self.get_session()
        if not session:
            return
        today_str = date.today().isoformat()
        data = self.report_service.get_cashier_shift_summary(
            session.organization_id,
            branch_id=session.branch_id,
            date_str=today_str,
        )
        shifts = data.get("shifts", [])
        self.shifts_table.setUpdatesEnabled(False)
        self.shifts_table.blockSignals(True)
        try:
            self.shifts_table.setRowCount(len(shifts))
            for idx, s in enumerate(shifts):
                self.shifts_table.setItem(idx, 0, QTableWidgetItem(s.get('username', '')))
                self.shifts_table.setItem(idx, 1, QTableWidgetItem(s.get('full_name', '')))
                self.shifts_table.setItem(idx, 2, QTableWidgetItem(str(s.get('sales_count', 0))))
                self.shifts_table.setItem(idx, 3, QTableWidgetItem(f"{Decimal(s.get('total_collected', '0.00')):,.2f}"))
        finally:
            self.shifts_table.blockSignals(False)
            self.shifts_table.setUpdatesEnabled(True)

    def refresh_all_reports(self):
        self._refresh_sales()
        self._refresh_inventory()
        self._refresh_pnl()
        self._refresh_shifts()
