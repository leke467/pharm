from datetime import date
from decimal import Decimal
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QFrame,
    QPushButton,
    QGridLayout,
)
from PySide6.QtCore import Qt


class DashboardWidget(QWidget):
    """
    SaaS-Grade Enterprise Dashboard Widget (Livesteads Design).
    Provides live KPI metric cards with colored top-borders: sales, gross profit,
    expenses, inventory valuation, stock alerts, and system health status.
    """

    def __init__(self, session, report_service=None, parent=None):
        super().__init__(parent)
        self.session = session
        self.report_service = report_service
        self.init_ui()
        self.refresh_data()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(20)

        # 1. Header with Title, Subtitle and Refresh Action
        header_layout = QHBoxLayout()
        title_col = QVBoxLayout()
        title_col.setSpacing(4)

        header_title = QLabel("Dashboard Overview")
        header_title.setObjectName("PageHeader")

        today_str = date.today().strftime("%A, %B %d, %Y")
        user_name = self.session.full_name or self.session.username or "Staff"
        branch_name = self.session.branch_name or "Default Branch"
        mode_str = "Offline Mode" if self.session.is_offline else "Connected Online"

        subtitle = QLabel(f"Welcome back, {user_name}  ·  Branch: {branch_name}  ·  {today_str}  ·  {mode_str}")
        subtitle.setObjectName("PageSubtitle")

        title_col.addWidget(header_title)
        title_col.addWidget(subtitle)
        header_layout.addLayout(title_col)

        header_layout.addStretch()

        self.refresh_btn = QPushButton("Refresh Data")
        self.refresh_btn.setObjectName("SecondaryBtn")
        self.refresh_btn.clicked.connect(self.refresh_data)
        header_layout.addWidget(self.refresh_btn)
        layout.addLayout(header_layout)

        # 2. KPI Cards Grid (2 rows x 3 columns)
        grid = QGridLayout()
        grid.setSpacing(16)

        # 1. Today's Revenue (Green top accent)
        self.card_sales = self._create_metric_card(
            card_object_name="MetricCardGreen",
            title_text="TODAY'S REVENUE",
            val_object_name="MetricValueGreen",
            initial_val="0.00",
            initial_sub="0 transactions today",
        )
        grid.addWidget(self.card_sales["frame"], 0, 0)

        # 2. Today's Gross Profit (Green top accent)
        self.card_net = self._create_metric_card(
            card_object_name="MetricCardGreen",
            title_text="TODAY'S GROSS PROFIT",
            val_object_name="MetricValueGreen",
            initial_val="0.00",
            initial_sub="Sales minus COGS",
        )
        grid.addWidget(self.card_net["frame"], 0, 1)

        # 3. Today's Expenses (Orange top accent)
        self.card_expenses = self._create_metric_card(
            card_object_name="MetricCardOrange",
            title_text="TODAY'S EXPENSES",
            val_object_name="MetricValueOrange",
            initial_val="0.00",
            initial_sub="0 records approved",
        )
        grid.addWidget(self.card_expenses["frame"], 0, 2)

        # 4. Inventory Valuation (Blue top accent)
        self.card_inv = self._create_metric_card(
            card_object_name="MetricCardBlue",
            title_text="TOTAL INVENTORY VALUE",
            val_object_name="MetricValue",
            initial_val="0.00",
            initial_sub="0 units across 0 batches",
        )
        grid.addWidget(self.card_inv["frame"], 1, 0)

        # 5. Stock Alerts (Red top accent)
        self.card_alerts = self._create_metric_card(
            card_object_name="MetricCardRed",
            title_text="STOCK ALERTS",
            val_object_name="MetricValueRed",
            initial_val="0 Alerts",
            initial_sub="0 Low Stock  ·  0 Expiring Soon",
        )
        grid.addWidget(self.card_alerts["frame"], 1, 1)

        # 6. System Health (Blue top accent)
        self.card_health = self._create_metric_card(
            card_object_name="MetricCardBlue",
            title_text="SYSTEM HEALTH",
            val_object_name="MetricValue",
            initial_val="Active & Healthy",
            initial_sub="Local SQLite WAL  ·  Zero Data Loss",
        )
        grid.addWidget(self.card_health["frame"], 1, 2)

        layout.addLayout(grid)

        # 3. Quick System Overview Panel
        info_panel = QFrame()
        info_panel.setObjectName("MetricCard")
        info_layout = QVBoxLayout(info_panel)
        info_layout.setContentsMargins(18, 16, 18, 16)
        info_layout.setSpacing(8)

        panel_title = QLabel("System Architecture & Operational Readiness")
        panel_title.setStyleSheet("font-size: 14px; font-weight: 700; color: #0F172A;")
        info_layout.addWidget(panel_title)

        panel_desc = QLabel(
            "PharmaCare is operating with local-first transactional persistence. "
            "All sales, stock movements, and audit records are committed instantly to SQLite with Write-Ahead Logging (WAL) "
            "and synchronized securely with the central Django server when connectivity is established."
        )
        panel_desc.setWordWrap(True)
        panel_desc.setStyleSheet("font-size: 13px; color: #64748B; line-height: 1.4;")
        info_layout.addWidget(panel_desc)

        layout.addWidget(info_panel)
        layout.addStretch()

    def _create_metric_card(
        self,
        card_object_name: str,
        title_text: str,
        val_object_name: str,
        initial_val: str,
        initial_sub: str,
    ) -> dict:
        frame = QFrame()
        frame.setObjectName(card_object_name)
        l = QVBoxLayout(frame)
        l.setContentsMargins(18, 16, 18, 16)
        l.setSpacing(4)

        lbl_title = QLabel(title_text)
        lbl_title.setObjectName("MetricTitle")
        l.addWidget(lbl_title)

        lbl_val = QLabel(initial_val)
        lbl_val.setObjectName(val_object_name)
        l.addWidget(lbl_val)

        lbl_sub = QLabel(initial_sub)
        lbl_sub.setObjectName("MetricSubtitle")
        l.addWidget(lbl_sub)

        return {"frame": frame, "val": lbl_val, "sub": lbl_sub}

    def refresh_data(self):
        if not self.report_service or not self.session:
            return

        today_str = date.today().isoformat()
        try:
            # Sales & Profit
            sales = self.report_service.get_sales_summary(
                self.session.organization_id,
                branch_id=self.session.branch_id,
                start_date=today_str,
            )
            rev = Decimal(sales.get("total_revenue", "0.00"))
            count = sales.get("total_sales_count", 0)
            gp = Decimal(sales.get("gross_profit", "0.00"))
            sold_items = sales.get("total_items_sold", 0)

            self.card_sales["val"].setText(f"{rev:,.2f}")
            self.card_sales["sub"].setText(f"{count} transaction(s) today")

            self.card_net["val"].setText(f"{gp:,.2f}")
            self.card_net["sub"].setText(f"{sold_items} item(s) sold today")

            # Expenses
            exp = self.report_service.get_expense_summary(
                self.session.organization_id,
                branch_id=self.session.branch_id,
                start_date=today_str,
            )
            exp_amt = Decimal(exp.get("total_expenses", "0.00"))
            self.card_expenses["val"].setText(f"{exp_amt:,.2f}")
            self.card_expenses["sub"].setText(f"{exp.get('total_count', 0)} approved today")

            # Inventory Valuation
            inv = self.report_service.get_inventory_valuation(
                self.session.organization_id,
                branch_id=self.session.branch_id,
            )
            cost_val = Decimal(inv.get("total_cost_valuation", "0.00"))
            units = inv.get("total_units_in_stock", 0)
            batches_count = inv.get("total_batches_in_stock", 0)
            low = inv.get("low_stock_count", 0)
            expiring = inv.get("expiring_soon_batches_count", 0)
            expired = inv.get("expired_batches_count", 0)

            self.card_inv["val"].setText(f"{cost_val:,.2f}")
            self.card_inv["sub"].setText(f"{units:,} units across {batches_count} batches")

            total_alerts = low + expiring + expired
            self.card_alerts["val"].setText(f"{total_alerts} Alert{'s' if total_alerts != 1 else ''}")
            self.card_alerts["sub"].setText(f"{low} Low Stock  ·  {expiring} Expiring  ·  {expired} Expired")

            status_str = "Offline (Local Only)" if self.session.is_offline else "Connected (Online)"
            self.card_health["val"].setText(status_str)
            self.card_health["sub"].setText("Local SQLite WAL Active  ·  Zero Data Loss")

        except Exception as e:
            self.card_health["val"].setText("Notice")
            self.card_health["sub"].setText(str(e)[:45])

