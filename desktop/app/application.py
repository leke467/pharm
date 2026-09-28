import os
import subprocess
from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont
from desktop.app.config.app_config import AppConfig
from desktop.app.db.database import DatabaseManager
from desktop.app.db.migrations.runner import MigrationRunner
from desktop.app.sync.api_client import ApiClient
from desktop.app.auth.offline_auth import OfflineAuthenticator
from desktop.app.auth.auth_manager import AuthManager
from desktop.app.services.organization_service import OrganizationService
from desktop.app.services.user_service import UserService
from desktop.app.services.product_service import ProductService
from desktop.app.services.inventory_service import InventoryService
from desktop.app.services.pricing_service import PricingService
from desktop.app.services.sales_service import SalesService
from desktop.app.services.purchase_service import PurchaseService
from desktop.app.services.stock_count_service import StockCountService
from desktop.app.services.transfer_service import TransferService
from desktop.app.services.expense_service import ExpenseService
from desktop.app.services.audit_service import AuditService
from desktop.app.services.report_service import ReportService
from desktop.app.services.licensing_service import LicensingService
from desktop.app.services.backup_service import BackupService
from desktop.app.services.maintenance_service import MaintenanceService
from desktop.app.services.reconciliation_service import ReconciliationService
from desktop.app.sync.sync_worker import SyncWorker
from desktop.app.utils.logging_config import setup_logging
from desktop.app.ui.main_window import MainWindow
from desktop.app.ui.login.login_widget import LoginWidget
from desktop.app.ui.common.logo import create_logo_icon


class PharmacyApplication(QApplication):
    def __init__(self, argv, args):
        super().__init__(argv)
        self.setFont(QFont("Segoe UI", 10))
        self.setWindowIcon(create_logo_icon(64))
        self.config = AppConfig(args.server_url, args.data_dir, args.log_level)
        setup_logging(self.config.log_level, self.config.data_dir)

        self.db_manager = DatabaseManager(self.config)
        self.run_migrations()

        self.api_client = ApiClient(self.config)
        self.offline_auth = OfflineAuthenticator()
        self.auth_manager = AuthManager(self.api_client, self.db_manager, self.offline_auth)
        self.organization_service = OrganizationService(self.db_manager)
        self.user_service = UserService(self.db_manager)
        self.product_service = ProductService(self.db_manager)
        self.inventory_service = InventoryService(self.db_manager)
        self.pricing_service = PricingService(self.db_manager)
        self.sales_service = SalesService(self.db_manager)
        self.purchase_service = PurchaseService(self.db_manager)
        self.stock_count_service = StockCountService(self.db_manager)
        self.transfer_service = TransferService(self.db_manager)
        self.expense_service = ExpenseService(self.db_manager)
        self.audit_service = AuditService(self.db_manager)
        self.report_service = ReportService(self.db_manager)
        self.licensing_service = LicensingService(self.db_manager)
        self.backup_service = BackupService(self.db_manager, self.config)
        self.maintenance_service = MaintenanceService(self.db_manager)
        self.reconciliation_service = ReconciliationService(self.db_manager)
        self.user_service.seed_local_permissions()
        self._apply_pending_wizard_setup()
        self.current_session = None
        self.sync_worker = SyncWorker(
            self.api_client,
            self.db_manager,
            self.config,
            session_provider=lambda: self.current_session,
        )

        if not getattr(args, "apply_wizard_setup", False):
            self.aboutToQuit.connect(self._on_about_to_quit)
            self.show_login()

    def _on_about_to_quit(self):
        try:
            if self.sync_worker and self.sync_worker.isRunning():
                self.sync_worker.request_stop()
        except Exception:
            pass
        try:
            if self.api_client:
                self.api_client.close()
        except Exception:
            pass
        try:
            if self.sync_worker and self.sync_worker.isRunning():
                self.sync_worker.stop(150)
        except Exception:
            pass

    def _apply_pending_wizard_setup(self):
        import json
        from PySide6.QtCore import QSettings

        setup_file = self.config.data_dir / "wizard_setup.json"
        if not setup_file.exists():
            return
        try:
            raw = setup_file.read_text(encoding="utf-8-sig")
            data = json.loads(raw)
            res = self.organization_service.setup_pharmacy_onboarding(
                pharmacy_name=data.get("pharmacy_name", "MedCare Pharmacy"),
                org_code=data.get("org_code", "MEDCARE"),
                branch_name=data.get("branch_name", "Main Branch"),
                branch_code=data.get("branch_code", "HQ"),
                admin_username="admin",
                admin_full_name="System Superuser (Admin)",
                admin_password="admin123!",
                address=data.get("branch_address", ""),
                phone=data.get("branch_phone", ""),
                cloud_server_url=data.get("cloud_server_url", ""),
                device_code=data.get("device_code", "POS01"),
            )
            settings = QSettings("PharmaCare", "PharmaCareEnterprise")
            settings.setValue("saved_org_code", res["organization_code"])
            settings.setValue("saved_pharmacy_name", res["organization_name"])
            settings.setValue("saved_branch_code", res["branch_code"])
            settings.setValue("saved_username", "admin")
            settings.setValue("remember_username", True)
            if data.get("cloud_server_url"):
                settings.setValue("server_url", data.get("cloud_server_url").strip())
                self.config.server_url = data.get("cloud_server_url").strip()
            if data.get("device_code"):
                settings.setValue("device_code", data.get("device_code").strip().upper())

            applied_file = self.config.data_dir / "wizard_setup_applied.json"
            setup_file.replace(applied_file)
        except Exception:
            pass

    def run_migrations(self):
        runner = MigrationRunner(self.db_manager, self.config)
        runner.run_pending()

    def show_login(self):
        self.login_window = LoginWidget(
            self.auth_manager,
            self.organization_service,
            licensing_service=self.licensing_service,
            api_client=self.api_client,
            backup_service=self.backup_service,
        )
        self.login_window.login_successful.connect(self.on_login_success)
        self.login_window.show()

    def on_login_success(self, session):
        self.current_session = session
        self.inventory_service.refresh_expired_batches(session.organization_id)
        self.login_window.close()
        self.main_window = MainWindow(
            self.auth_manager,
            self.sync_worker,
            self.current_session,
            user_service=self.user_service,
            organization_service=self.organization_service,
            product_service=self.product_service,
            inventory_service=self.inventory_service,
            pricing_service=self.pricing_service,
            sales_service=self.sales_service,
            purchase_service=self.purchase_service,
            stock_count_service=self.stock_count_service,
            transfer_service=self.transfer_service,
            expense_service=self.expense_service,
            audit_service=self.audit_service,
            report_service=self.report_service,
            backup_service=self.backup_service,
            maintenance_service=self.maintenance_service,
            reconciliation_service=self.reconciliation_service,
            licensing_service=self.licensing_service,
            api_client=self.api_client,
        )
        self.main_window.logout_requested.connect(self.on_logout)
        self.main_window.showMaximized()
        if not self.sync_worker.isRunning():
            self.sync_worker.start()

    def on_logout(self):
        try:
            self.auth_manager.logout()
        except Exception:
            pass
        self.current_session = None
        old_win = getattr(self, "main_window", None)
        self.main_window = None
        if old_win is not None:
            old_win._is_logging_out = True
            old_win.hide()
        self.show_login()
        if old_win is not None:
            old_win.close()
            old_win.deleteLater()

    def notify(self, receiver, event):
        try:
            if event.type() == QEvent.Type.KeyPress and hasattr(event, "key") and event.key() == Qt.Key.Key_Print:
                self._handle_print_screen()
        except Exception:
            pass
        return super().notify(receiver, event)

    def _handle_print_screen(self):
        try:
            os.startfile("ms-screenclip:")
        except Exception:
            try:
                subprocess.Popen(["SnippingTool.exe", "/clip"])
            except Exception:
                try:
                    screen = self.primaryScreen()
                    if screen:
                        pixmap = screen.grabWindow(0)
                        self.clipboard().setPixmap(pixmap)
                except Exception:
                    pass
