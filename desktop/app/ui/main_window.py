import json
import os
from datetime import datetime
from pathlib import Path
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QStackedWidget,
    QPushButton,
    QFrame,
    QScrollArea,
)
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut

from desktop.app.ui.dashboard.dashboard_widget import DashboardWidget
from desktop.app.ui.products.products_widget import ProductsWidget, PriceHistoryDialog
from desktop.app.ui.inventory.inventory_widget import InventoryWidget
from desktop.app.ui.pos.pos_widget import POSWidget
from desktop.app.ui.users.users_widget import UsersWidget
from desktop.app.ui.settings.settings_widget import SettingsWidget
from desktop.app.ui.purchases.purchases_widget import PurchasesWidget
from desktop.app.ui.stock_counts.stock_counts_widget import StockCountsWidget
from desktop.app.ui.transfers.transfers_widget import TransfersWidget
from desktop.app.ui.expenses.expenses_widget import ExpensesWidget
from desktop.app.ui.audit.audit_widget import ActivityLogWidget, AuditLogWidget
from desktop.app.ui.reports.reports_widget import ReportsWidget
from desktop.app.ui.common.logo import create_logo_icon, LogoWidget
from desktop.app.ui.common.title_bar import CustomTitleBar
from shared.enums import PermissionCode


class MainWindow(QMainWindow):
    logout_requested = Signal()

    def __init__(
        self,
        auth_manager,
        sync_worker,
        session,
        user_service=None,
        organization_service=None,
        product_service=None,
        inventory_service=None,
        pricing_service=None,
        sales_service=None,
        purchase_service=None,
        stock_count_service=None,
        transfer_service=None,
        expense_service=None,
        audit_service=None,
        report_service=None,
        backup_service=None,
        maintenance_service=None,
        reconciliation_service=None,
        licensing_service=None,
        api_client=None,
    ):
        super().__init__()
        self.auth_manager = auth_manager
        self.sync_worker = sync_worker
        self.session = session
        self.user_service = user_service
        self.organization_service = organization_service
        self.product_service = product_service
        self.inventory_service = inventory_service
        self.pricing_service = pricing_service
        self.sales_service = sales_service
        self.purchase_service = purchase_service
        self.stock_count_service = stock_count_service
        self.transfer_service = transfer_service
        self.expense_service = expense_service
        self.audit_service = audit_service
        self.report_service = report_service
        self.backup_service = backup_service
        self.maintenance_service = maintenance_service
        self.reconciliation_service = reconciliation_service
        self.licensing_service = licensing_service
        self.api_client = api_client
        self.nav_buttons: dict[str, QPushButton] = {}
        self.page_indices: dict[str, int] = {}
        self.current_page_name = "Dashboard"
        self._latest_price_change_id = None
        self._is_logging_out = False
        self._lock_dialog_open = False
        self._clock_ticks = 0

        self.setWindowTitle("PharmaCare Pro — Pharmacy Management System")
        self.setWindowIcon(create_logo_icon(32))
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setMinimumSize(1080, 680)
        self.center_on_screen()

        self.init_ui()
        if self.sync_worker:
            self.sync_worker.sync_status_changed.connect(self.update_sync_status)
            if hasattr(self.sync_worker, "sync_completed"):
                self.sync_worker.sync_completed.connect(self._on_sync_completed)
            if hasattr(self.sync_worker, "subscription_updated"):
                self.sync_worker.subscription_updated.connect(self._on_subscription_updated)

        # Real-time digital clock timer (updates every second)
        self.clock_timer = QTimer(self)
        self.clock_timer.timeout.connect(self._update_clock)
        self.clock_timer.start(1000)

        try:
            self._prt_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Print), self)
            self._prt_shortcut.activated.connect(self._handle_print_screen)
        except Exception:
            pass

    def closeEvent(self, event):
        if hasattr(self, "clock_timer") and self.clock_timer.isActive():
            self.clock_timer.stop()
        try:
            if self.sync_worker:
                self.sync_worker.sync_status_changed.disconnect(self.update_sync_status)
                if hasattr(self.sync_worker, "sync_completed"):
                    self.sync_worker.sync_completed.disconnect(self._on_sync_completed)
                if hasattr(self.sync_worker, "subscription_updated"):
                    self.sync_worker.subscription_updated.disconnect(self._on_subscription_updated)
        except Exception:
            pass
        self.hide()
        if not getattr(self, "_is_logging_out", False):
            if self.sync_worker and self.sync_worker.isRunning():
                self.sync_worker.stop(150)
        event.accept()

    def _update_clock(self):
        now = datetime.now()
        date_str = now.strftime("%a, %b %d, %Y")
        time_str = now.strftime("%I:%M:%S %p")
        if hasattr(self, "live_clock_badge"):
            self.live_clock_badge.setText(f"📅  {date_str}   •   🕒  {time_str}")
        self._clock_ticks += 1
        if self._clock_ticks % 60 == 0:
            self._refresh_subscription_countdown()

    def _handle_print_screen(self):
        import subprocess
        try:
            os.startfile("ms-screenclip:")
        except Exception:
            try:
                subprocess.Popen(["SnippingTool.exe", "/clip"])
            except Exception:
                try:
                    screen = QApplication.primaryScreen()
                    if screen:
                        pixmap = screen.grabWindow(0)
                        QApplication.clipboard().setPixmap(pixmap)
                except Exception:
                    pass

    def center_on_screen(self):
        screen = QApplication.primaryScreen()
        if screen:
            avail = screen.availableGeometry()
            w = min(1320, int(avail.width() * 0.94))
            h = min(840, int(avail.height() * 0.90))
            self.resize(w, h)
            x = avail.x() + (avail.width() - self.width()) // 2
            y = avail.y() + (avail.height() - self.height()) // 2
            self.move(max(avail.x(), x), max(avail.y(), y))

    def init_ui(self):
        main_widget = QWidget()
        main_widget.setObjectName("RootWindow")
        self.setCentralWidget(main_widget)
        root_layout = QVBoxLayout(main_widget)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # 0. Custom Branded Sleek Title Bar
        self.custom_title_bar = CustomTitleBar(self)
        root_layout.addWidget(self.custom_title_bar)

        # Body Container
        body_widget = QWidget()
        main_layout = QHBoxLayout(body_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # =====================================================================
        # 1. Left Sidebar (Modern White SaaS Theme)
        # =====================================================================
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 16)
        sidebar_layout.setSpacing(0)
        sidebar.setFixedWidth(260)

        # Organization & Branch Header in Sidebar (replaces redundant PharmaCare title)
        org_name = self.session.organization_name or "MedCare Pharmacy"
        branch_text = self.session.branch_name or "Main Branch"

        brand_container = QWidget()
        brand_container.setObjectName("BrandContainer")
        brand_h_layout = QHBoxLayout(brand_container)
        brand_h_layout.setContentsMargins(16, 16, 16, 14)
        brand_h_layout.setSpacing(12)

        logo_widget = LogoWidget(size=34, on_dark=False)
        brand_h_layout.addWidget(logo_widget)

        brand_text_col = QVBoxLayout()
        brand_text_col.setContentsMargins(0, 0, 0, 0)
        brand_text_col.setSpacing(4)

        self.org_name_label = QLabel(org_name)
        self.org_name_label.setObjectName("AppTitle")
        self.org_name_label.setWordWrap(True)

        branch_pill_row = QHBoxLayout()
        branch_pill_row.setContentsMargins(0, 0, 0, 0)
        branch_pill_row.setSpacing(0)
        self.branch_label = QLabel(f"📍 {branch_text.upper()}")
        self.branch_label.setObjectName("BranchBadgeTag")
        branch_pill_row.addWidget(self.branch_label)
        branch_pill_row.addStretch()

        brand_text_col.addWidget(self.org_name_label)
        brand_text_col.addLayout(branch_pill_row)

        brand_h_layout.addLayout(brand_text_col, stretch=1)
        sidebar_layout.addWidget(brand_container)

        # User Profile Card Wrapper (Outer Margins)
        user_card_wrapper = QWidget()
        ucw_layout = QVBoxLayout(user_card_wrapper)
        ucw_layout.setContentsMargins(14, 8, 14, 8)
        ucw_layout.setSpacing(0)

        user_card = QFrame()
        user_card.setObjectName("UserProfileCard")
        user_card_layout = QHBoxLayout(user_card)
        user_card_layout.setContentsMargins(12, 10, 12, 10)
        user_card_layout.setSpacing(10)

        initials = (self.session.full_name or self.session.username or "AD")[:2].upper()
        avatar = QLabel(initials)
        avatar.setObjectName("UserAvatar")
        avatar.setAlignment(Qt.AlignCenter)

        user_info_layout = QVBoxLayout()
        user_info_layout.setContentsMargins(0, 0, 0, 0)
        user_info_layout.setSpacing(2)
        user_name = QLabel(self.session.full_name or self.session.username)
        user_name.setObjectName("UserName")

        role_display = "Organization Admin" if getattr(self.session, "is_org_admin", False) else "Staff Member"
        if getattr(self.session, "roles", None):
            first_role = self.session.roles[0]
            role_display = first_role.get("name", role_display) if isinstance(first_role, dict) else str(first_role)
        user_role = QLabel(f"🛡️ {role_display}")
        user_role.setObjectName("UserRole")
        user_info_layout.addWidget(user_name)
        user_info_layout.addWidget(user_role)

        user_card_layout.addWidget(avatar)
        user_card_layout.addLayout(user_info_layout, stretch=1)
        ucw_layout.addWidget(user_card)
        sidebar_layout.addWidget(user_card_wrapper)

        # Navigation Scroll Area / Container
        nav_scroll = QScrollArea()
        nav_scroll.setWidgetResizable(True)
        nav_scroll.setFrameShape(QFrame.NoFrame)
        nav_widget = QWidget()
        nav_layout = QVBoxLayout(nav_widget)
        nav_layout.setContentsMargins(6, 4, 6, 4)
        nav_layout.setSpacing(2)
        nav_layout.setAlignment(Qt.AlignTop)

        nav_defs = [
            (
                "Dashboard",
                "📊  Dashboard",
                [
                    PermissionCode.DASHBOARD_VIEW.value,
                    "matrix.r0.view",
                    "matrix.r0.create",
                    "matrix.r0.edit",
                    "matrix.r0.delete",
                ],
            ),
            ("Inventory", "📦  Inventory", [PermissionCode.INVENTORY_VIEW.value]),
            ("POS", "💳  Point of Sale", [PermissionCode.SALES_SELL.value]),
            ("Products", "💊  Products", [PermissionCode.PRODUCTS_VIEW.value]),
            ("Purchases", "📥  Purchases", [PermissionCode.STOCK_RECEIVE.value, PermissionCode.SUPPLIERS_MANAGE.value]),
            ("Stock Count", "🔢  Stock Counts", [PermissionCode.STOCK_COUNTS_PERFORM.value, PermissionCode.STOCK_COUNTS_APPROVE.value]),
            ("Transfers", "🔄  Transfers", [PermissionCode.STOCK_TRANSFER.value]),
            ("Expenses", "💵  Expenses", [PermissionCode.EXPENSES_CREATE.value, PermissionCode.EXPENSES_APPROVE.value]),
            ("Reports", "📈  Reports", [PermissionCode.REPORTS_VIEW.value]),
            ("Users", "👥  Staff Accounts", [PermissionCode.USERS_MANAGE.value]),
            ("Settings", "⚙️  Settings", [PermissionCode.SETTINGS_MANAGE.value]),
            (
                "Activity Logs",
                "📋  Activity Logs",
                [
                    PermissionCode.AUDIT_VIEW.value,
                    PermissionCode.INVENTORY_VIEW.value,
                    PermissionCode.PRODUCTS_VIEW.value,
                    PermissionCode.SALES_SELL.value,
                ],
            ),
            ("Audit Log", "🛡️  Audit Trail", [PermissionCode.AUDIT_VIEW.value]),
        ]

        for page_key, display_label, required_perms in nav_defs:
            # RBAC Visibility Check: Hide tabs if the user lacks the required permission(s)
            if required_perms is not None:
                if not any(self.session.has_permission(p) for p in required_perms):
                    continue

            btn = QPushButton(display_label)
            btn.setObjectName("NavButton")
            btn.setCheckable(False)
            btn.clicked.connect(lambda checked=False, name=page_key: self.switch_page(name))
            nav_layout.addWidget(btn)
            self.nav_buttons[page_key] = btn

        nav_scroll.setWidget(nav_widget)
        sidebar_layout.addWidget(nav_scroll, stretch=1)

        # Logout Button at bottom
        logout_btn = QPushButton("🚪  Logout")
        logout_btn.setObjectName("LogoutButton")
        logout_btn.clicked.connect(self._on_logout_clicked)
        sidebar_layout.addWidget(logout_btn)

        main_layout.addWidget(sidebar)

        # =====================================================================
        # 2. Main Content Area & Top Header Bar
        # =====================================================================
        content_area = QWidget()
        content_layout = QVBoxLayout(content_area)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        # Top Bar
        top_bar = QFrame()
        top_bar.setObjectName("TopBar")
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(24, 10, 24, 10)
        top_layout.setSpacing(14)

        # Left: Breadcrumb + Page Title Group
        left_group = QVBoxLayout()
        left_group.setSpacing(2)
        left_group.setContentsMargins(0, 0, 0, 0)

        self.top_breadcrumb = QLabel("🏠  Workspace  ›  Analytics & Overview")
        self.top_breadcrumb.setObjectName("TopBarBreadcrumb")
        left_group.addWidget(self.top_breadcrumb)

        self.top_title = QLabel("Dashboard")
        self.top_title.setObjectName("TopBarTitle")
        left_group.addWidget(self.top_title)

        top_layout.addLayout(left_group, stretch=1)

        # Right: Live Subscription Countdown Pill Button
        self.sub_countdown_btn = QPushButton("💳 30 Days Left")
        self.sub_countdown_btn.setCursor(Qt.PointingHandCursor)
        self.sub_countdown_btn.setToolTip("Click to view Pharmacy Subscription & Monnify Billing")
        self.sub_countdown_btn.setStyleSheet(
            "QPushButton { background-color: #ECFDF5; color: #065F46; border: 1px solid #A7F3D0; "
            "font-weight: 800; font-size: 12px; padding: 6px 12px; border-radius: 6px; } "
            "QPushButton:hover { background-color: #D1FAE5; }"
        )
        self.sub_countdown_btn.clicked.connect(lambda: self._open_subscription_modal(locked_mode=False))
        top_layout.addWidget(self.sub_countdown_btn)

        # Right: Price Updates Notification Button
        self.price_notif_btn = QPushButton("🔔 Price Updates")
        self.price_notif_btn.setObjectName("SecondaryBtn")
        self.price_notif_btn.setCursor(Qt.PointingHandCursor)
        self.price_notif_btn.setToolTip("View recent product selling price updates across all branches")
        self.price_notif_btn.clicked.connect(self._open_price_history_modal)
        top_layout.addWidget(self.price_notif_btn)

        # Right: Live Clock & Date Badge Widget
        self.live_clock_badge = QLabel()
        self.live_clock_badge.setObjectName("LiveClockBadge")
        self._update_clock()
        top_layout.addWidget(self.live_clock_badge)

        # Right: Connectivity / Sync Shield Badge
        self.sync_status_badge = QLabel("🛡️  Offline Engine  (Local WAL)")
        self.sync_status_badge.setObjectName("StatusBadgeOffline")
        top_layout.addWidget(self.sync_status_badge)

        content_layout.addWidget(top_bar)

        # Multi-Branch Price Change Notification Banner (auto-shown when a price is updated)
        self.price_alert_banner = QFrame()
        self.price_alert_banner.setStyleSheet(
            "QFrame { background-color: #EFF6FF; border-bottom: 1px solid #BFDBFE; }"
        )
        banner_layout = QHBoxLayout(self.price_alert_banner)
        banner_layout.setContentsMargins(24, 8, 24, 8)
        banner_layout.setSpacing(12)

        self.price_alert_label = QLabel("")
        self.price_alert_label.setStyleSheet(
            "color: #1E3A8A; font-size: 12.5px; font-weight: 600; border: none; background: transparent;"
        )
        banner_layout.addWidget(self.price_alert_label, stretch=1)

        view_hist_btn = QPushButton("View All Price Changes")
        view_hist_btn.setCursor(Qt.PointingHandCursor)
        view_hist_btn.setStyleSheet(
            "background-color: #2563EB; color: white; font-size: 11.5px; font-weight: 700; padding: 5px 12px; border-radius: 5px;"
        )
        view_hist_btn.clicked.connect(self._open_price_history_modal)
        banner_layout.addWidget(view_hist_btn)

        dismiss_btn = QPushButton("Dismiss ✓")
        dismiss_btn.setCursor(Qt.PointingHandCursor)
        dismiss_btn.setStyleSheet(
            "background-color: #DBEAFE; color: #1E40AF; font-size: 11.5px; font-weight: 700; padding: 5px 12px; border-radius: 5px;"
        )
        dismiss_btn.clicked.connect(self._dismiss_price_alert)
        banner_layout.addWidget(dismiss_btn)

        self.price_alert_banner.setVisible(False)
        content_layout.addWidget(self.price_alert_banner)

        # =====================================================================
        # 3. Stacked Pages
        # =====================================================================
        self.stacked_widget = QStackedWidget()
        self.dashboard = DashboardWidget(self.session, report_service=self.report_service)
        self.inventory_page = InventoryWidget(
            self.session,
            self.inventory_service,
            self.pricing_service,
            self.product_service,
        )
        self.pos_page = POSWidget(
            self.session,
            self.sales_service,
            self.product_service,
            self.pricing_service,
            self.inventory_service,
        )
        self.products_page = ProductsWidget(
            self.session, self.product_service, self.pricing_service
        )
        self.purchases_page = PurchasesWidget(
            getattr(self.purchase_service, 'db_manager', None),
            lambda: self.session,
        )
        self.stock_counts_page = StockCountsWidget(
            getattr(self.stock_count_service, 'db_manager', None),
            lambda: self.session,
        )
        self.transfers_page = TransfersWidget(
            getattr(self.transfer_service, 'db_manager', None),
            lambda: self.session,
        )
        self.expenses_page = ExpensesWidget(
            getattr(self.expense_service, 'db_manager', None)
            or getattr(self.inventory_service, 'db_manager', None)
            or getattr(self.product_service, 'db_manager', None),
            lambda: self.session,
        )
        self.reports_page = ReportsWidget(
            getattr(self.report_service, 'db_manager', None)
            or getattr(self.inventory_service, 'db_manager', None)
            or getattr(self.product_service, 'db_manager', None),
            lambda: self.session,
        )
        db_mgr = (
            getattr(self.audit_service, 'db_manager', None)
            or getattr(self.inventory_service, 'db_manager', None)
            or getattr(self.product_service, 'db_manager', None)
        )
        self.activity_logs_page = ActivityLogWidget(
            db_mgr,
            lambda: self.session,
        )
        self.audit_page = AuditLogWidget(
            db_mgr,
            lambda: self.session,
        )
        self.users_page = UsersWidget(self.session, self.user_service)
        self.settings_page = SettingsWidget(
            self.session,
            self.organization_service,
            self.backup_service,
            self.maintenance_service,
            self.reconciliation_service,
            user_service=self.user_service,
            licensing_service=self.licensing_service,
            api_client=self.api_client,
        )

        self.page_indices["Dashboard"] = self.stacked_widget.addWidget(self.dashboard)
        self.page_indices["Inventory"] = self.stacked_widget.addWidget(self.inventory_page)
        self.page_indices["POS"] = self.stacked_widget.addWidget(self.pos_page)
        self.page_indices["Products"] = self.stacked_widget.addWidget(self.products_page)
        self.page_indices["Purchases"] = self.stacked_widget.addWidget(self.purchases_page)
        self.page_indices["Stock Count"] = self.stacked_widget.addWidget(self.stock_counts_page)
        self.page_indices["Transfers"] = self.stacked_widget.addWidget(self.transfers_page)
        self.page_indices["Expenses"] = self.stacked_widget.addWidget(self.expenses_page)
        self.page_indices["Reports"] = self.stacked_widget.addWidget(self.reports_page)
        self.page_indices["Users"] = self.stacked_widget.addWidget(self.users_page)
        self.page_indices["Settings"] = self.stacked_widget.addWidget(self.settings_page)
        self.page_indices["Activity Logs"] = self.stacked_widget.addWidget(self.activity_logs_page)
        self.page_indices["Audit Log"] = self.stacked_widget.addWidget(self.audit_page)

        empty_page = QWidget()
        empty_layout = QVBoxLayout(empty_page)
        empty_layout.setAlignment(Qt.AlignCenter)
        empty_lbl = QLabel("🔒  No workspace modules are enabled for your assigned role.\nPlease contact your Pharmacy Administrator.")
        empty_lbl.setAlignment(Qt.AlignCenter)
        empty_lbl.setStyleSheet("color: #64748B; font-size: 15px; font-weight: 700;")
        empty_layout.addWidget(empty_lbl)
        self.empty_page_idx = self.stacked_widget.addWidget(empty_page)

        content_layout.addWidget(self.stacked_widget)
        main_layout.addWidget(content_area)
        root_layout.addWidget(body_widget)

        # Apply Global Stylesheet
        self._apply_theme()

        # Set Initial Page
        if "Dashboard" in self.nav_buttons:
            self.switch_page("Dashboard")
        elif self.nav_buttons:
            first_allowed = list(self.nav_buttons.keys())[0]
            self.switch_page(first_allowed)
        else:
            self.stacked_widget.setCurrentIndex(self.empty_page_idx)
            self.top_breadcrumb.setText("🏠  Workspace  ›  Restricted Access")
            self.top_title.setText("Access Restricted")
        self._check_price_notifications()
        self._refresh_subscription_countdown()

    def _get_seen_price_file(self) -> Path:
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return Path(base) / "PharmacyManagement" / "price_notifications_seen.json"

    def _check_price_notifications(self):
        if not self.pricing_service or not self.session or not self.session.organization_id:
            return
        try:
            changes = self.pricing_service.get_recent_price_changes(
                self.session.organization_id, limit=10
            )
            if not changes:
                self.price_alert_banner.setVisible(False)
                return

            latest = changes[0]
            self._latest_price_change_id = latest["id"]

            seen_map = {}
            seen_path = self._get_seen_price_file()
            if seen_path.exists():
                try:
                    seen_map = json.loads(seen_path.read_text(encoding="utf-8"))
                except Exception:
                    seen_map = {}

            branch_key = self.session.branch_id or "default"
            last_seen_id = seen_map.get(branch_key)

            if last_seen_id != latest["id"]:
                p_name = latest.get("product_name", "Product")
                p_sku = latest.get("product_sku", "")
                old_p = latest.get("old_price")
                new_p = latest.get("new_price")
                br_name = latest.get("branch_name") or "Main Branch (HQ)"
                acct_name = latest.get("account_name") or "Administrator"
                old_part = f" (was ₦{old_p:,.2f})" if old_p is not None else ""
                self.price_alert_label.setText(
                    f"🔔  Price Update:  {p_name} ({p_sku}) is now ₦{new_p:,.2f}{old_part}  •  Updated by {acct_name} at {br_name}"
                )
                self.price_alert_banner.setVisible(True)
                self.price_notif_btn.setText("🔔 Price Updates (New)")
                self.price_notif_btn.setStyleSheet(
                    "background-color: #DBEAFE; color: #1E40AF; font-weight: 700; padding: 6px 12px; border-radius: 6px;"
                )
            else:
                self.price_alert_banner.setVisible(False)
                self.price_notif_btn.setText("🔔 Price Updates")
                self.price_notif_btn.setStyleSheet("")
        except Exception:
            pass

    def _dismiss_price_alert(self):
        self.price_alert_banner.setVisible(False)
        self.price_notif_btn.setText("🔔 Price Updates")
        self.price_notif_btn.setStyleSheet("")
        if not self._latest_price_change_id:
            return
        try:
            seen_path = self._get_seen_price_file()
            seen_map = {}
            if seen_path.exists():
                try:
                    seen_map = json.loads(seen_path.read_text(encoding="utf-8"))
                except Exception:
                    seen_map = {}
            branch_key = (self.session.branch_id if self.session else None) or "default"
            seen_map[branch_key] = self._latest_price_change_id
            seen_path.parent.mkdir(parents=True, exist_ok=True)
            seen_path.write_text(json.dumps(seen_map, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _open_price_history_modal(self):
        self._dismiss_price_alert()
        dlg = PriceHistoryDialog(
            parent=self,
            pricing_service=self.pricing_service,
            session=self.session,
        )
        dlg.exec()

    def _on_sync_completed(self, result: dict):
        try:
            self._check_price_notifications()
            if result and result.get("downloaded", 0) > 0:
                current_widget = self.stacked_widget.currentWidget()
                if hasattr(current_widget, "refresh_all"):
                    current_widget.refresh_all()
                elif hasattr(current_widget, "refresh_data"):
                    current_widget.refresh_data()
        except Exception:
            pass

    def _apply_theme(self):
        try:
            qss_path = os.path.join(os.path.dirname(__file__), 'resources', 'styles.qss')
            with open(qss_path, 'r', encoding='utf-8') as f:
                content = f.read()
            res_dir = os.path.join(os.path.dirname(__file__), 'resources').replace('\\', '/')
            content = content.replace("url(resources/", f"url({res_dir}/")
            self.setStyleSheet(content)
        except Exception:
            pass

    def switch_page(self, page_name: str):
        if page_name in self.page_indices and page_name in self.nav_buttons:
            self.current_page_name = page_name
            self.stacked_widget.setCurrentIndex(self.page_indices[page_name])
            
            category_map = {
                "Dashboard": "Analytics & Overview",
                "Inventory": "Stock & Warehouse Management",
                "POS": "Point of Sale & Checkout",
                "Products": "Master Products & Catalog",
                "Purchases": "Procurement & Receiving",
                "Stock Count": "Audit & Physical Count",
                "Transfers": "Inter-Branch Logistics",
                "Expenses": "Finance & Overhead Vouchers",
                "Reports": "Executive Intelligence",
                "Users": "Staff & Role Access Control",
                "Settings": "System, Backups & Maintenance",
                "Activity Logs": "Operational Activity History",
                "Audit Log": "Security & Compliance Audit Trail",
            }
            cat = category_map.get(page_name, "Workspace Management")
            self.top_breadcrumb.setText(f"🏠  Workspace  ›  {cat}")
            self.top_title.setText(page_name)

            # Update active nav styling
            for name, btn in self.nav_buttons.items():
                is_active = (name == page_name)
                btn.setProperty("active", is_active)
                btn.style().unpolish(btn)
                btn.style().polish(btn)

            # Trigger refresh if the target page supports it
            current_widget = self.stacked_widget.currentWidget()
            if hasattr(current_widget, "refresh_all"):
                try:
                    current_widget.refresh_all()
                except Exception:
                    pass
            elif hasattr(current_widget, "refresh_data"):
                try:
                    current_widget.refresh_data()
                except Exception:
                    pass
            self._check_price_notifications()

    def update_sync_status(self, is_online):
        if is_online:
            self.sync_status_badge.setText("⚡  Cloud Synced  (Real-Time)")
            self.sync_status_badge.setObjectName("StatusBadgeOnline")
        else:
            self.sync_status_badge.setText("🛡️  Offline Engine  (Local WAL)")
            self.sync_status_badge.setObjectName("StatusBadgeOffline")

        self.sync_status_badge.style().unpolish(self.sync_status_badge)
        self.sync_status_badge.style().polish(self.sync_status_badge)

    def _on_logout_clicked(self):
        self._is_logging_out = True
        try:
            self.clock_timer.stop()
        except Exception:
            pass
        try:
            if self.sync_worker:
                self.sync_worker.sync_status_changed.disconnect(self.update_sync_status)
                self.sync_worker.sync_completed.disconnect(self._on_sync_completed)
                if hasattr(self.sync_worker, "subscription_updated"):
                    self.sync_worker.subscription_updated.disconnect(self._on_subscription_updated)
        except Exception:
            pass
        self.logout_requested.emit()

    def _on_subscription_updated(self, state: dict):
        self._refresh_subscription_countdown()

    def _refresh_subscription_countdown(self):
        if self._is_logging_out or not hasattr(self, "sub_countdown_btn") or not self.licensing_service:
            return
        try:
            state = self.licensing_service.get_license_state(self.session.organization_id)
            days_left = int(state.get("days_remaining", 30))
            eff_status = state.get("effective_status", "ACTIVE")

            if days_left <= 0 or eff_status in ("EXPIRED", "SUSPENDED"):
                self.sub_countdown_btn.setText("🔒  0 Days Left  (Renew Now)")
                self.sub_countdown_btn.setStyleSheet(
                    "background-color: #FEF2F2; color: #991B1B; border: 1.5px solid #F87171; "
                    "border-radius: 14px; padding: 5px 13px; font-size: 11.5px; font-weight: 800;"
                )
                if not getattr(self, "_sub_modal_open", False):
                    self._open_subscription_modal(locked_mode=True)
            elif days_left <= 3:
                self.sub_countdown_btn.setText(f"⚠️  {days_left} Day{'s' if days_left != 1 else ''} Left")
                self.sub_countdown_btn.setStyleSheet(
                    "background-color: #FEF2F2; color: #DC2626; border: 1.5px solid #FCA5A5; "
                    "border-radius: 14px; padding: 5px 13px; font-size: 11.5px; font-weight: 800;"
                )
            elif days_left <= 7:
                self.sub_countdown_btn.setText(f"⏳  {days_left} Days Left")
                self.sub_countdown_btn.setStyleSheet(
                    "background-color: #FFFBEB; color: #B45309; border: 1.5px solid #FCD34D; "
                    "border-radius: 14px; padding: 5px 13px; font-size: 11.5px; font-weight: 800;"
                )
            else:
                self.sub_countdown_btn.setText(f"💳  {days_left} Days Left")
                self.sub_countdown_btn.setStyleSheet(
                    "background-color: #EEF2FF; color: #3730A3; border: 1.5px solid #C7D2FE; "
                    "border-radius: 14px; padding: 5px 13px; font-size: 11.5px; font-weight: 800;"
                )
        except Exception:
            pass

    def _open_subscription_modal(self, locked_mode: bool = False):
        if not self.licensing_service or getattr(self, "_sub_modal_open", False):
            return

        is_admin = (
            getattr(self.session, "username", "").lower() == "admin"
            or bool(getattr(self.session, "is_org_admin", False))
            or self.session.has_permission(PermissionCode.SUBSCRIPTIONS_MANAGE.value)
            or self.session.has_permission(PermissionCode.SETTINGS_MANAGE.value)
            or self.session.has_permission(PermissionCode.USERS_MANAGE.value)
        )
        if not locked_mode and not is_admin:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(
                self,
                "Administrator Access Required",
                "🔒 Only a Pharmacy Administrator can manage subscriptions, pay via Monnify, or add more subscription days.",
            )
            return

        self._sub_modal_open = True
        try:
            from desktop.app.ui.licensing.subscription_dialog import SubscriptionBillingDialog

            org_code = getattr(self.session, "organization_code", None)
            if not org_code and self.organization_service:
                try:
                    org = self.organization_service.get_organization(self.session.organization_id)
                    if org:
                        org_code = org.code
                except Exception:
                    pass
            org_code = org_code or "MEDCARE"

            dlg = SubscriptionBillingDialog(
                parent=self,
                licensing_service=self.licensing_service,
                api_client=self.api_client,
                organization_id=self.session.organization_id,
                org_code=org_code,
                org_name=getattr(self.session, "organization_name", "Pharmacy"),
                locked_mode=locked_mode,
            )
            dlg.exec()
            self._sub_modal_open = False

            # Re-verify after dialog closes
            if locked_mode:
                still_locked, _ = self.licensing_service.is_subscription_locked(
                    organization_id=self.session.organization_id, org_code=org_code
                )
                if still_locked:
                    self._on_logout_clicked()
                    return
            self._refresh_subscription_countdown()
        except Exception:
            self._sub_modal_open = False


