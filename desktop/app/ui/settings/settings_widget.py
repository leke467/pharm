import json
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
    QGroupBox,
    QTabWidget,
    QMessageBox,
    QDialog,
    QFormLayout,
    QFrame,
)
from PySide6.QtCore import Qt, QSettings
from shared.enums import PermissionCode
from desktop.app.ui.common.title_bar import DialogHeaderBanner
from desktop.app.ui.users.role_matrix_widget import RolePermissionMatrixWidget


class EditOrganizationDialog(QDialog):
    """Frameless modal dialog to edit the Pharmacy's Organization Name, Code, and Contact Profile."""

    def __init__(self, parent, organization_service, session, org):
        super().__init__(parent)
        self.organization_service = organization_service
        self.session = session
        self.org = org

        self.setWindowTitle("Edit Pharmacy Profile")
        self.setMinimumWidth(480)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        banner = DialogHeaderBanner(
            title="Edit Pharmacy Name & Profile",
            subtitle="Configure your pharmacy's official brand name, organization code, and contact details",
            parent_dialog=self,
        )
        layout.addWidget(banner)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(24, 18, 24, 22)
        body_layout.setSpacing(14)

        form = QFormLayout()
        form.setSpacing(12)

        self.name_input = QLineEdit()
        self.name_input.setText((self.org.name if self.org else self.session.organization_name) or "")
        self.name_input.setPlaceholderText("e.g. GraceLand Pharmacy Ltd")
        form.addRow("Pharmacy Name *:", self.name_input)

        self.code_input = QLineEdit()
        self.code_input.setText((self.org.code if self.org else "MEDCARE") or "")
        self.code_input.setPlaceholderText("e.g. GRACELAND (used at login & cloud sync)")
        form.addRow("Organization Code *:", self.code_input)

        self.address_input = QLineEdit()
        self.address_input.setText((self.org.address if self.org else "") or "")
        self.address_input.setPlaceholderText("Headquarters address (printed on receipts)")
        form.addRow("HQ Address:", self.address_input)

        self.phone_input = QLineEdit()
        self.phone_input.setText((self.org.phone if self.org else "") or "")
        self.phone_input.setPlaceholderText("e.g. +234 800 123 4567")
        form.addRow("Phone Number:", self.phone_input)

        self.email_input = QLineEdit()
        self.email_input.setText((self.org.email if self.org else "") or "")
        self.email_input.setPlaceholderText("e.g. info@gracelandpharmacy.com")
        form.addRow("Email Address:", self.email_input)

        body_layout.addLayout(form)

        self.error_lbl = QLabel("")
        self.error_lbl.setStyleSheet("color: #EF4444; font-size: 12px; font-weight: 600;")
        body_layout.addWidget(self.error_lbl)

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("SecondaryBtn")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        self.save_btn = QPushButton("Save Pharmacy Profile")
        self.save_btn.setStyleSheet(
            "background-color: #10B981; color: white; font-weight: 700; padding: 8px 18px; border-radius: 6px;"
        )
        self.save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(self.save_btn)

        body_layout.addLayout(btn_row)
        layout.addWidget(body)

    def _on_save(self):
        name = self.name_input.text().strip()
        code = self.code_input.text().strip().upper()
        if not name or not code:
            self.error_lbl.setText("Pharmacy Name and Organization Code are required.")
            return

        try:
            updated_org = self.organization_service.update_organization(
                user_session=self.session,
                name=name,
                code=code,
                address=self.address_input.text().strip(),
                phone=self.phone_input.text().strip(),
                email=self.email_input.text().strip(),
            )
            self.session.organization_name = updated_org.name
            settings = QSettings("PharmaCare", "PharmaCareEnterprise")
            settings.setValue("saved_org_code", updated_org.code)

            QMessageBox.information(
                self,
                "Pharmacy Profile Updated",
                f"Pharmacy name updated to '{updated_org.name}' (Code: {updated_org.code}).",
            )
            self.accept()
        except Exception as e:
            self.error_lbl.setText(f"Error: {str(e)}")


class CloudSyncConfigDialog(QDialog):
    """Frameless modal dialog to configure Cloud Server URL and Multi-Branch Terminal linking."""

    def __init__(self, parent, organization_service, session, org):
        super().__init__(parent)
        self.organization_service = organization_service
        self.session = session
        self.org = org

        self.setWindowTitle("Cloud Server & Multi-Branch Sync Setup")
        self.setMinimumWidth(520)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        banner = DialogHeaderBanner(
            title="Cloud Server & Multi-Branch Sync",
            subtitle="Link this branch computer to your central Django Cloud Server for real-time sync",
            parent_dialog=self,
        )
        layout.addWidget(banner)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(24, 18, 24, 22)
        body_layout.setSpacing(14)

        org_settings = {}
        if self.org and self.org.settings:
            try:
                org_settings = json.loads(self.org.settings)
            except Exception:
                org_settings = {}

        qset = QSettings("PharmaCare", "PharmaCareEnterprise")
        saved_url = org_settings.get("cloud_server_url") or qset.value("cloud_server_url", "http://127.0.0.1:8001")
        saved_dev = org_settings.get("terminal_code") or qset.value("terminal_code", self.session.device_code or "POS01")

        info_lbl = QLabel(
            "How Multi-Branch Cloud Sync Works:\n"
            "1. Host the Django server (`server/`) on a cloud VPS (e.g. Render, AWS, DigitalOcean) or LAN IP.\n"
            "2. Enter that Server URL below on each branch computer using the SAME Organization Code.\n"
            "3. Each branch works 100% offline on local SQLite WAL and automatically syncs sales, stock, "
            "and inter-branch transfers whenever internet is available."
        )
        info_lbl.setWordWrap(True)
        info_lbl.setStyleSheet(
            "background-color: #F0FDF4; color: #065F46; border: 1px solid #A7F3D0; "
            "border-radius: 8px; padding: 10px 12px; font-size: 12px;"
        )
        body_layout.addWidget(info_lbl)

        form = QFormLayout()
        form.setSpacing(12)

        self.url_input = QLineEdit()
        self.url_input.setText(str(saved_url))
        self.url_input.setPlaceholderText("e.g. https://cloud.yourpharmacy.com or http://192.168.1.100:8001")
        form.addRow("Cloud Server URL *:", self.url_input)

        self.dev_code_input = QLineEdit()
        self.dev_code_input.setText(str(saved_dev))
        self.dev_code_input.setPlaceholderText("e.g. POS01, POS02, DISP01")
        form.addRow("Terminal Device Code *:", self.dev_code_input)

        body_layout.addLayout(form)

        self.status_lbl = QLabel("")
        self.status_lbl.setWordWrap(True)
        self.status_lbl.setStyleSheet("font-size: 12px; font-weight: 600;")
        body_layout.addWidget(self.status_lbl)

        btn_row = QHBoxLayout()
        test_btn = QPushButton("🔌 Test Cloud Connection")
        test_btn.setObjectName("SecondaryBtn")
        test_btn.clicked.connect(self._test_connection)
        btn_row.addWidget(test_btn)

        btn_row.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("SecondaryBtn")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        save_btn = QPushButton("Save Cloud Settings")
        save_btn.setStyleSheet(
            "background-color: #2563EB; color: white; font-weight: 700; padding: 8px 18px; border-radius: 6px;"
        )
        save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(save_btn)

        body_layout.addLayout(btn_row)
        layout.addWidget(body)

    def _test_connection(self):
        import httpx
        url = self.url_input.text().strip().rstrip("/")
        if not url:
            self.status_lbl.setStyleSheet("color: #EF4444; font-weight: 600;")
            self.status_lbl.setText("Please enter a Cloud Server URL first.")
            return
        health_url = f"{url}/api/v1/health/" if "/api/v1" not in url else f"{url}/health/"
        try:
            resp = httpx.get(health_url, timeout=4.0)
            if resp.status_code == 200:
                self.status_lbl.setStyleSheet("color: #10B981; font-weight: 700;")
                self.status_lbl.setText(f"✓ Connected to Cloud Server at {url}!")
            else:
                self.status_lbl.setStyleSheet("color: #F59E0B; font-weight: 600;")
                self.status_lbl.setText(f"Server responded with HTTP {resp.status_code} at {health_url}.")
        except Exception:
            self.status_lbl.setStyleSheet("color: #64748B; font-weight: 600;")
            self.status_lbl.setText(
                f"Cloud server at {url} is currently unreachable (App will continue running in 100% Offline Local WAL mode and auto-sync when online)."
            )

    def _on_save(self):
        url = self.url_input.text().strip().rstrip("/")
        dev_code = self.dev_code_input.text().strip().upper() or "POS01"
        if not url:
            self.status_lbl.setStyleSheet("color: #EF4444; font-weight: 600;")
            self.status_lbl.setText("Cloud Server URL is required.")
            return

        try:
            self.organization_service.update_organization(
                user_session=self.session,
                settings_updates={
                    "cloud_server_url": url,
                    "terminal_code": dev_code,
                },
            )
            qset = QSettings("PharmaCare", "PharmaCareEnterprise")
            qset.setValue("cloud_server_url", url)
            qset.setValue("terminal_code", dev_code)
            QMessageBox.information(
                self,
                "Cloud Settings Saved",
                f"Cloud Server URL ({url}) and Terminal Code ({dev_code}) have been saved.",
            )
            self.accept()
        except Exception as e:
            self.status_lbl.setStyleSheet("color: #EF4444; font-weight: 600;")
            self.status_lbl.setText(f"Error: {str(e)}")


class CreateBranchDialog(QDialog):
    """Clean popup modal dialog to create a new branch."""

    def __init__(self, parent, organization_service, session):
        super().__init__(parent)
        self.organization_service = organization_service
        self.session = session

        self.setWindowTitle("Add New Branch")
        self.setMinimumWidth(460)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        banner = DialogHeaderBanner(
            title="Create New Branch",
            subtitle="Register a retail branch or storage facility for your organization",
            parent_dialog=self,
        )
        layout.addWidget(banner)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(24, 18, 24, 22)
        body_layout.setSpacing(14)

        form = QFormLayout()
        form.setSpacing(12)

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("e.g. Main Street Branch")
        form.addRow("Branch Name *:", self.name_input)

        self.code_input = QLineEdit()
        self.code_input.setPlaceholderText("e.g. BR01 (unique)")
        form.addRow("Branch Code *:", self.code_input)

        self.address_input = QLineEdit()
        self.address_input.setPlaceholderText("e.g. 123 Commercial Ave (optional)")
        form.addRow("Address:", self.address_input)

        self.phone_input = QLineEdit()
        self.phone_input.setPlaceholderText("e.g. 08012345678 (optional)")
        form.addRow("Phone Number:", self.phone_input)

        self.uses_shelves_check = QCheckBox("Enable Storage Locations / Shelves")
        form.addRow("", self.uses_shelves_check)

        body_layout.addLayout(form)

        self.error_lbl = QLabel("")
        self.error_lbl.setStyleSheet("color: #EF4444; font-size: 12px; font-weight: 600;")
        body_layout.addWidget(self.error_lbl)

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("SecondaryBtn")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        self.save_btn = QPushButton("Create Branch")
        self.save_btn.setStyleSheet(
            "background-color: #10B981; color: white; font-weight: 700; padding: 8px 18px; border-radius: 6px;"
        )
        self.save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(self.save_btn)

        body_layout.addLayout(btn_row)
        layout.addWidget(body)

    def _on_save(self):
        name = self.name_input.text().strip()
        code = self.code_input.text().strip()
        if not name or not code:
            self.error_lbl.setText("Branch name and code are required.")
            return

        try:
            self.organization_service.create_branch(
                user_session=self.session,
                name=name,
                code=code,
                address=self.address_input.text().strip(),
                phone=self.phone_input.text().strip(),
                uses_storage_locations=self.uses_shelves_check.isChecked(),
            )
            QMessageBox.information(self, "Success", f"Branch '{name}' created successfully!")
            self.accept()
        except Exception as e:
            self.error_lbl.setText(f"Error: {str(e)}")


class EditBranchDialog(QDialog):
    """Clean popup modal dialog to edit an existing branch."""

    def __init__(self, parent, organization_service, session, branch):
        super().__init__(parent)
        self.organization_service = organization_service
        self.session = session
        self.branch = branch

        self.setWindowTitle(f"Edit Branch — {self.branch.name}")
        self.setMinimumWidth(460)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        banner = DialogHeaderBanner(
            title=f"Edit Branch — {self.branch.name}",
            subtitle=f"Branch Code: {self.branch.code}",
            parent_dialog=self,
        )
        layout.addWidget(banner)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(24, 18, 24, 22)
        body_layout.setSpacing(14)

        form = QFormLayout()
        form.setSpacing(12)

        self.name_input = QLineEdit()
        self.name_input.setText(self.branch.name or "")
        form.addRow("Branch Name *:", self.name_input)

        self.code_input = QLineEdit()
        self.code_input.setText(self.branch.code or "")
        form.addRow("Branch Code *:", self.code_input)

        self.address_input = QLineEdit()
        self.address_input.setText(self.branch.address or "")
        form.addRow("Address:", self.address_input)

        self.phone_input = QLineEdit()
        self.phone_input.setText(self.branch.phone or "")
        form.addRow("Phone Number:", self.phone_input)

        self.uses_shelves_check = QCheckBox("Enable Storage Locations / Shelves")
        self.uses_shelves_check.setChecked(bool(self.branch.uses_storage_locations))
        form.addRow("", self.uses_shelves_check)

        body_layout.addLayout(form)

        self.error_lbl = QLabel("")
        self.error_lbl.setStyleSheet("color: #EF4444; font-size: 12px; font-weight: 600;")
        body_layout.addWidget(self.error_lbl)

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("SecondaryBtn")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        self.save_btn = QPushButton("Save Changes")
        self.save_btn.setStyleSheet(
            "background-color: #2563EB; color: white; font-weight: 700; padding: 8px 18px; border-radius: 6px;"
        )
        self.save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(self.save_btn)

        body_layout.addLayout(btn_row)
        layout.addWidget(body)

    def _on_save(self):
        name = self.name_input.text().strip()
        code = self.code_input.text().strip()
        if not name or not code:
            self.error_lbl.setText("Branch name and code are required.")
            return

        try:
            self.organization_service.update_branch(
                user_session=self.session,
                branch_id=self.branch.id,
                name=name,
                code=code,
                address=self.address_input.text().strip(),
                phone=self.phone_input.text().strip(),
                uses_storage_locations=self.uses_shelves_check.isChecked(),
            )
            QMessageBox.information(self, "Success", f"Branch '{name}' updated successfully!")
            self.accept()
        except Exception as e:
            self.error_lbl.setText(f"Error: {str(e)}")


class SettingsWidget(QWidget):
    """
    Desktop UI screen for Organization/Branch settings, Cloud Sync configuration,
    SQLite Backups, Database Maintenance, and Inventory Ledger Reconciliation.
    """

    def __init__(
        self,
        session,
        organization_service=None,
        backup_service=None,
        maintenance_service=None,
        reconciliation_service=None,
        user_service=None,
        licensing_service=None,
        api_client=None,
    ):
        super().__init__()
        self.session = session
        self.organization_service = organization_service
        self.backup_service = backup_service
        self.maintenance_service = maintenance_service
        self.reconciliation_service = reconciliation_service
        self.user_service = user_service
        self.licensing_service = licensing_service
        self.api_client = api_client
        self.branches_list = []
        self.current_org = None
        self.init_ui()
        self.refresh_data()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(24, 24, 24, 24)
        main_layout.setSpacing(16)

        header_layout = QHBoxLayout()
        title_col = QVBoxLayout()
        title_col.setSpacing(4)

        header = QLabel("System Settings & Maintenance")
        header.setObjectName("PageHeader")
        subtitle = QLabel("Pharmacy identity, Monnify subscription billing, multi-branch cloud sync & SQLite backups")
        subtitle.setObjectName("PageSubtitle")
        title_col.addWidget(header)
        title_col.addWidget(subtitle)
        header_layout.addLayout(title_col)
        header_layout.addStretch()

        self.refresh_btn = QPushButton("Refresh Data")
        self.refresh_btn.setObjectName("SecondaryBtn")
        self.refresh_btn.clicked.connect(self.refresh_data)
        header_layout.addWidget(self.refresh_btn)

        main_layout.addLayout(header_layout)

        self.tabs = QTabWidget()

        # Tab 1: Branches & Organization
        branch_tab = QWidget()
        branch_layout = QVBoxLayout(branch_tab)
        branch_layout.setContentsMargins(0, 12, 0, 0)
        branch_layout.setSpacing(14)

        can_manage_settings = self.session.has_permission(PermissionCode.SETTINGS_MANAGE.value)
        can_manage_branches = self.session.has_permission(PermissionCode.BRANCHES_MANAGE.value)

        # Organization Profile & Cloud Sync Card
        org_card = QFrame()
        org_card.setStyleSheet(
            "QFrame { background-color: #F8FAFC; border: 1.5px solid #E2E8F0; border-radius: 10px; }"
        )
        org_card_layout = QHBoxLayout(org_card)
        org_card_layout.setContentsMargins(18, 14, 18, 14)
        org_card_layout.setSpacing(16)

        org_info_col = QVBoxLayout()
        org_info_col.setSpacing(4)
        self.org_title_lbl = QLabel(f"🏥  {self.session.organization_name or 'MedCare Pharmacy'}")
        self.org_title_lbl.setStyleSheet("font-size: 16px; font-weight: 800; color: #0F172A; border: none;")
        self.org_meta_lbl = QLabel("Organization Code: MEDCARE  •  Active Branch: Main Branch")
        self.org_meta_lbl.setStyleSheet("font-size: 12.5px; color: #475569; font-weight: 600; border: none;")
        self.org_cloud_lbl = QLabel("☁️ Cloud Server: Local / Offline WAL Engine")
        self.org_cloud_lbl.setStyleSheet("font-size: 12px; color: #059669; font-weight: 600; border: none;")
        org_info_col.addWidget(self.org_title_lbl)
        org_info_col.addWidget(self.org_meta_lbl)
        org_info_col.addWidget(self.org_cloud_lbl)
        org_card_layout.addLayout(org_info_col, stretch=1)

        self.edit_org_btn = QPushButton("🏥 Edit Pharmacy Name & Profile")
        self.edit_org_btn.setStyleSheet(
            "background-color: #0F172A; color: white; font-weight: 700; padding: 8px 16px; border-radius: 6px;"
        )
        self.edit_org_btn.setEnabled(can_manage_settings)
        self.edit_org_btn.clicked.connect(self._open_edit_org_dialog)
        org_card_layout.addWidget(self.edit_org_btn)

        self.cloud_cfg_btn = QPushButton("☁️ Cloud & Multi-Branch Sync")
        self.cloud_cfg_btn.setStyleSheet(
            "background-color: #2563EB; color: white; font-weight: 700; padding: 8px 16px; border-radius: 6px;"
        )
        self.cloud_cfg_btn.setEnabled(can_manage_settings)
        self.cloud_cfg_btn.clicked.connect(self._open_cloud_sync_dialog)
        org_card_layout.addWidget(self.cloud_cfg_btn)

        branch_layout.addWidget(org_card)

        # Subscription & Monnify Billing Card
        sub_card = QFrame()
        sub_card.setStyleSheet(
            "QFrame { background-color: #ECFDF5; border: 1.5px solid #A7F3D0; border-radius: 10px; }"
        )
        sub_card_layout = QHBoxLayout(sub_card)
        sub_card_layout.setContentsMargins(18, 12, 18, 12)
        sub_card_layout.setSpacing(16)

        sub_info_col = QVBoxLayout()
        sub_info_col.setSpacing(3)
        self.sub_title_lbl = QLabel("💳  Pharmacy Subscription: 30 Days Remaining (ACTIVE)")
        self.sub_title_lbl.setStyleSheet("font-size: 14px; font-weight: 800; color: #065F46; border: none; background: transparent;")
        self.sub_meta_lbl = QLabel("Monthly Rate: ₦25,000.00  •  Yearly Rate: ₦250,000.00  •  Monnify Reserved Account: —")
        self.sub_meta_lbl.setStyleSheet("font-size: 12px; font-weight: 600; color: #047857; border: none; background: transparent;")
        sub_info_col.addWidget(self.sub_title_lbl)
        sub_info_col.addWidget(self.sub_meta_lbl)
        sub_card_layout.addLayout(sub_info_col, stretch=1)

        self.manage_sub_btn = QPushButton("💳 Renew / Pay via Monnify")
        self.manage_sub_btn.setCursor(Qt.PointingHandCursor)
        self.manage_sub_btn.setStyleSheet(
            "background-color: #059669; color: white; font-weight: 800; padding: 8px 16px; border-radius: 6px;"
        )
        self.manage_sub_btn.clicked.connect(self._open_subscription_billing_dialog)
        sub_card_layout.addWidget(self.manage_sub_btn)

        branch_layout.addWidget(sub_card)

        branch_toolbar = QHBoxLayout()
        b_title = QLabel("Registered Branches")
        b_title.setStyleSheet("font-size: 15px; font-weight: 700; color: #1E293B;")
        branch_toolbar.addWidget(b_title)
        branch_toolbar.addStretch()

        self.add_branch_btn = QPushButton("+ Add Branch")
        self.add_branch_btn.setStyleSheet(
            "background-color: #10B981; color: white; font-weight: 700; padding: 8px 18px; border-radius: 6px;"
        )
        self.add_branch_btn.setEnabled(can_manage_branches)
        self.add_branch_btn.clicked.connect(self._open_create_branch_dialog)
        branch_toolbar.addWidget(self.add_branch_btn)

        self.edit_branch_btn = QPushButton("✏️ Edit Branch")
        self.edit_branch_btn.setStyleSheet(
            "background-color: #2563EB; color: white; font-weight: 700; padding: 8px 18px; border-radius: 6px;"
        )
        self.edit_branch_btn.setEnabled(can_manage_branches)
        self.edit_branch_btn.clicked.connect(self._on_edit_selected_branch)
        branch_toolbar.addWidget(self.edit_branch_btn)
        branch_layout.addLayout(branch_toolbar)

        self.branch_table = QTableWidget(0, 4)
        self.branch_table.setHorizontalHeaderLabels(
            ["Code", "Branch Name", "Uses Shelves/Locations", "Initial Stock Loaded"]
        )
        self.branch_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.branch_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.branch_table.setSelectionMode(QTableWidget.SingleSelection)
        self.branch_table.cellDoubleClicked.connect(self._on_branch_table_double_clicked)

        b_hdr = self.branch_table.horizontalHeader()
        b_hdr.setSectionResizeMode(0, QHeaderView.Interactive)
        b_hdr.setSectionResizeMode(1, QHeaderView.Stretch)
        b_hdr.setSectionResizeMode(2, QHeaderView.Interactive)
        b_hdr.setSectionResizeMode(3, QHeaderView.Interactive)

        self.branch_table.setColumnWidth(0, 130)
        self.branch_table.setColumnWidth(2, 220)
        self.branch_table.setColumnWidth(3, 170)

        self.branch_table.verticalHeader().setDefaultSectionSize(40)
        self.branch_table.verticalHeader().setVisible(False)
        self.branch_table.setAlternatingRowColors(True)
        branch_layout.addWidget(self.branch_table)

        self.tabs.addTab(branch_tab, "🏢 Branches & Organization")

        # Tab 2: Backup & Database Maintenance
        maint_tab = QWidget()
        maint_layout = QVBoxLayout(maint_tab)
        maint_layout.setContentsMargins(0, 12, 0, 0)
        maint_layout.setSpacing(14)

        # Backups section
        backup_group = QGroupBox("Branch Backups & Cloud Recovery (FILO — Max 4 Backups per Branch)")
        b_box_layout = QVBoxLayout(backup_group)
        b_box_layout.setSpacing(10)

        b_btn_layout = QHBoxLayout()
        self.btn_cloud_backup = QPushButton("☁️ Backup Branch to Cloud Now")
        self.btn_cloud_backup.setCursor(Qt.PointingHandCursor)
        self.btn_cloud_backup.setStyleSheet(
            "background-color: #2563EB; color: white; font-weight: 700; padding: 8px 14px; border-radius: 6px;"
        )
        self.btn_cloud_backup.clicked.connect(self.on_cloud_backup_now)

        self.btn_cloud_restore = QPushButton("📥 Restore Branch from Cloud Server")
        self.btn_cloud_restore.setCursor(Qt.PointingHandCursor)
        self.btn_cloud_restore.setStyleSheet(
            "background-color: #059669; color: white; font-weight: 700; padding: 8px 14px; border-radius: 6px;"
        )
        self.btn_cloud_restore.clicked.connect(self.on_open_cloud_restore_dialog)

        self.btn_backup_now = QPushButton("💾 Create Local Backup")
        self.btn_backup_now.setObjectName("SecondaryBtn")
        self.btn_backup_now.clicked.connect(self.on_create_backup)

        self.btn_restore = QPushButton("🔄 Restore Selected Local")
        self.btn_restore.setObjectName("SecondaryBtn")
        self.btn_restore.clicked.connect(self.on_restore_backup)

        b_btn_layout.addWidget(self.btn_cloud_backup)
        b_btn_layout.addWidget(self.btn_cloud_restore)
        b_btn_layout.addWidget(self.btn_backup_now)
        b_btn_layout.addWidget(self.btn_restore)
        b_btn_layout.addStretch()
        b_box_layout.addLayout(b_btn_layout)

        self.backup_table = QTableWidget(0, 3)
        self.backup_table.setHorizontalHeaderLabels(["Local FILO Backup File (Max 4)", "Size (KB)", "Created At (UTC)"])
        self.backup_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.backup_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.backup_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.backup_table.setSelectionMode(QTableWidget.SingleSelection)
        self.backup_table.verticalHeader().setDefaultSectionSize(36)
        self.backup_table.verticalHeader().setVisible(False)
        self.backup_table.setAlternatingRowColors(True)
        b_box_layout.addWidget(self.backup_table)
        maint_layout.addWidget(backup_group)

        # Maintenance & Reconciliation section
        tools_group = QGroupBox("Database Maintenance & Ledger Reconciliation")
        tools_layout = QHBoxLayout(tools_group)

        self.btn_optimize = QPushButton("⚡ Optimize DB (WAL & VACUUM)")
        self.btn_optimize.setObjectName("SecondaryBtn")
        self.btn_optimize.clicked.connect(self.on_optimize_db)

        self.btn_check_integrity = QPushButton("🔍 Check Database Integrity")
        self.btn_check_integrity.setObjectName("SecondaryBtn")
        self.btn_check_integrity.clicked.connect(self.on_check_integrity)

        self.btn_reconcile = QPushButton("⚖️ Run Inventory Reconciliation")
        self.btn_reconcile.setObjectName("SecondaryBtn")
        self.btn_reconcile.clicked.connect(self.on_reconcile_inventory)

        tools_layout.addWidget(self.btn_optimize)
        tools_layout.addWidget(self.btn_check_integrity)
        tools_layout.addWidget(self.btn_reconcile)
        maint_layout.addWidget(tools_group)

        self.maint_status_label = QLabel("")
        maint_layout.addWidget(self.maint_status_label)

        self.tabs.addTab(maint_tab, "💾 Backup & Maintenance")

        # Tab 3: Roles & Permissions Matrix
        if self.user_service:
            self.role_matrix_widget = RolePermissionMatrixWidget(self.session, self.user_service)
            self.tabs.addTab(self.role_matrix_widget, "🛡️ Roles & Permissions")

        main_layout.addWidget(self.tabs)

    def refresh_data(self):
        # Refresh organization & branches
        if self.organization_service and self.session.organization_id:
            try:
                self.current_org = self.organization_service.get_organization(self.session.organization_id)
                if self.current_org:
                    self.session.organization_name = self.current_org.name
                    self.org_title_lbl.setText(f"🏥  {self.current_org.name}")
                    addr_part = f"  •  📍 {self.current_org.address}" if self.current_org.address else ""
                    phone_part = f"  •  📞 {self.current_org.phone}" if self.current_org.phone else ""
                    self.org_meta_lbl.setText(
                        f"Organization Code: {self.current_org.code}  •  Active Branch: {self.session.branch_name}{addr_part}{phone_part}"
                    )
                    try:
                        s_dict = json.loads(self.current_org.settings or "{}")
                    except Exception:
                        s_dict = {}
                    cloud_url = s_dict.get("cloud_server_url") or "http://127.0.0.1:8001 (Default Local/Cloud Endpoint)"
                    term_code = s_dict.get("terminal_code") or self.session.device_code or "POS01"
                    self.org_cloud_lbl.setText(f"☁️ Cloud Sync Endpoint: {cloud_url}   •   💻 Terminal Code: {term_code}")

                    # Also update MainWindow sidebar title if available
                    win = self.window()
                    if hasattr(win, "org_name_label"):
                        win.org_name_label.setText(self.current_org.name)

                self.branches_list = self.organization_service.list_branches(self.session.organization_id)
                self.branch_table.setUpdatesEnabled(False)
                self.branch_table.blockSignals(True)
                try:
                    self.branch_table.setRowCount(len(self.branches_list))
                    for row, b in enumerate(self.branches_list):
                        self.branch_table.setItem(row, 0, QTableWidgetItem(b.code))
                        self.branch_table.setItem(row, 1, QTableWidgetItem(b.name))
                        self.branch_table.setItem(
                            row, 2, QTableWidgetItem("Enabled" if b.uses_storage_locations else "Disabled")
                        )
                        self.branch_table.setItem(
                            row, 3, QTableWidgetItem("Yes" if b.initial_stock_loaded else "No")
                        )
                finally:
                    self.branch_table.blockSignals(False)
                    self.branch_table.setUpdatesEnabled(True)
            except Exception:
                pass

        # Refresh subscription status card
        if self.licensing_service:
            try:
                org_code = (self.current_org.code if self.current_org else "MEDCARE") or "MEDCARE"
                org_name = (self.current_org.name if self.current_org else self.session.organization_name) or "MedCare Pharmacy"
                state = self.licensing_service.ensure_or_get_subscription_state(
                    organization_id=self.session.organization_id,
                    org_code=org_code,
                    org_name=org_name,
                )
                days = int(state.get("days_remaining", 0))
                eff = state.get("effective_status", "ACTIVE")
                monthly = state.get("monthly_price", 25000)
                yearly = state.get("yearly_price", 250000)
                acc_no = state.get("monnify_account_number") or "—"
                bank = state.get("monnify_bank_name") or "Moniepoint MFB"
                self.sub_title_lbl.setText(f"💳  Pharmacy Subscription: {days} Days Remaining ({eff})")
                self.sub_meta_lbl.setText(
                    f"Monthly Fee: ₦{monthly:,.2f}  •  Yearly Fee: ₦{yearly:,.2f}  •  Monnify Account: {bank} ({acc_no})"
                )
            except Exception:
                pass

        # Refresh backups
        if self.backup_service:
            try:
                backups = self.backup_service.list_backups()
                self.backup_table.setUpdatesEnabled(False)
                self.backup_table.blockSignals(True)
                try:
                    self.backup_table.setRowCount(len(backups))
                    for row, bck in enumerate(backups):
                        size_kb = f"{bck['size_bytes'] / 1024:.1f}"
                        self.backup_table.setItem(row, 0, QTableWidgetItem(bck['filename']))
                        self.backup_table.setItem(row, 1, QTableWidgetItem(size_kb))
                        self.backup_table.setItem(row, 2, QTableWidgetItem(bck['created_at']))
                finally:
                    self.backup_table.blockSignals(False)
                    self.backup_table.setUpdatesEnabled(True)
            except Exception:
                pass

    def _open_subscription_billing_dialog(self):
        if not self.licensing_service:
            return
        from desktop.app.ui.licensing.subscription_dialog import SubscriptionBillingDialog

        org_code = (self.current_org.code if self.current_org else "MEDCARE") or "MEDCARE"
        org_name = (self.current_org.name if self.current_org else self.session.organization_name) or "MedCare Pharmacy"
        dlg = SubscriptionBillingDialog(
            parent=self,
            licensing_service=self.licensing_service,
            api_client=self.api_client,
            organization_id=self.session.organization_id,
            org_code=org_code,
            org_name=org_name,
            locked_mode=False,
        )
        dlg.exec()
        self.refresh_data()
        win = self.window()
        if hasattr(win, "_refresh_subscription_countdown"):
            win._refresh_subscription_countdown()

    def _open_edit_org_dialog(self):
        dlg = EditOrganizationDialog(self, self.organization_service, self.session, self.current_org)
        if dlg.exec() == QDialog.Accepted:
            self.refresh_data()

    def _open_cloud_sync_dialog(self):
        dlg = CloudSyncConfigDialog(self, self.organization_service, self.session, self.current_org)
        if dlg.exec() == QDialog.Accepted:
            self.refresh_data()

    def _open_create_branch_dialog(self):
        dlg = CreateBranchDialog(self, self.organization_service, self.session)
        if dlg.exec() == QDialog.Accepted:
            self.refresh_data()

    def _open_edit_branch_dialog(self, branch):
        dlg = EditBranchDialog(self, self.organization_service, self.session, branch)
        if dlg.exec() == QDialog.Accepted:
            self.refresh_data()

    def _on_edit_selected_branch(self):
        row = self.branch_table.currentRow()
        if row < 0 or row >= len(self.branches_list):
            QMessageBox.information(
                self,
                "Selection Required",
                "Please click a row in the branch table to select a branch first."
            )
            return
        self._open_edit_branch_dialog(self.branches_list[row])

    def _on_branch_table_double_clicked(self, row, col):
        if 0 <= row < len(self.branches_list):
            branch = self.branches_list[row]
            if self.session.has_permission(PermissionCode.BRANCHES_MANAGE.value):
                self._open_edit_branch_dialog(branch)

    def _resolve_active_branch_code(self) -> str:
        if hasattr(self, "branches_list") and self.branches_list:
            for b in self.branches_list:
                if str(b.id) == str(self.session.branch_id):
                    return b.code or "HQ"
            return self.branches_list[0].code or "HQ"
        return "HQ"

    def on_cloud_backup_now(self):
        if not self.backup_service or not self.api_client:
            self.maint_status_label.setText("Cloud backup service unavailable.")
            return
        org_code = (self.current_org.code if self.current_org else "MEDCARE") or "MEDCARE"
        org_name = (self.current_org.name if self.current_org else self.session.organization_name) or "MedCare Pharmacy"
        branch_code = self._resolve_active_branch_code()
        branch_name = self.session.branch_name or "Main Branch"
        try:
            res = self.backup_service.upload_branch_backup_to_cloud(
                api_client=self.api_client,
                org_code=org_code,
                org_name=org_name,
                branch_id=self.session.branch_id or "",
                branch_code=branch_code,
                branch_name=branch_name,
                device_code=self.session.device_code or "POS01",
                note="Manual Cloud Backup",
                force_new_slot=True,
            )
            self.refresh_data()
            bck_count = len((res or {}).get("branch_backups", []))
            self.maint_status_label.setText(
                f"✓ Cloud backup uploaded for {branch_name} ({branch_code}) — {bck_count}/4 FILO slots stored on server."
            )
            QMessageBox.information(
                self,
                "Cloud Branch Backup Complete",
                f"✅ Branch '{branch_name} ({branch_code})' has been backed up to the Cloud Server!\n\n"
                f"Active Cloud Backups for this Branch: {bck_count} / 4 (FILO Order).",
            )
        except Exception as e:
            self.maint_status_label.setText(f"Cloud backup failed: {e}")
            QMessageBox.warning(self, "Cloud Backup Error", f"Could not upload backup to server:\n{e}")

    def on_open_cloud_restore_dialog(self):
        if not self.backup_service or not self.api_client:
            return
        from desktop.app.ui.settings.cloud_restore_dialog import CloudBranchRestoreDialog

        org_code = (self.current_org.code if self.current_org else "MEDCARE") or "MEDCARE"
        branch_code = self._resolve_active_branch_code()
        dlg = CloudBranchRestoreDialog(
            backup_service=self.backup_service,
            api_client=self.api_client,
            org_code=org_code,
            branch_code=branch_code,
            parent=self,
        )
        if dlg.exec() == QDialog.Accepted:
            self.refresh_data()

    def on_create_backup(self):
        if not self.backup_service:
            self.maint_status_label.setText("Backup service unavailable.")
            return
        try:
            branch_code = self._resolve_active_branch_code()
            meta = self.backup_service.create_backup(note="manual", branch_code=branch_code)
            self.maint_status_label.setText(f"Local backup created (max 4 FILO retained): {meta['filename']}")
            self.refresh_data()
        except Exception as e:
            self.maint_status_label.setText(f"Backup failed: {e}")

    def on_restore_backup(self):
        if not self.backup_service:
            return
        selected_row = self.backup_table.currentRow()
        if selected_row < 0:
            QMessageBox.warning(self, "Restore Backup", "Please select a backup from the list first.")
            return

        filename = self.backup_table.item(selected_row, 0).text()
        bck_path = self.backup_service.backup_dir / filename

        confirm = QMessageBox.question(
            self,
            "Confirm Restore",
            f"Are you sure you want to restore from '{filename}'?\nA safety copy of the current database will be preserved.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return

        try:
            self.backup_service.restore_backup(bck_path)
            self.maint_status_label.setText(f"Database successfully restored from {filename}.")
            QMessageBox.information(self, "Restore Complete", "Database restored successfully.")
            self.refresh_data()
        except Exception as e:
            self.maint_status_label.setText(f"Restore failed: {e}")
            QMessageBox.critical(self, "Restore Failed", str(e))

    def on_optimize_db(self):
        if not self.maintenance_service:
            self.maint_status_label.setText("Maintenance service unavailable.")
            return
        try:
            self.maintenance_service.optimize_database()
            self.maint_status_label.setText("Database optimized (WAL truncated and VACUUM completed).")
        except Exception as e:
            self.maint_status_label.setText(f"Optimization error: {e}")

    def on_check_integrity(self):
        if not self.maintenance_service:
            self.maint_status_label.setText("Maintenance service unavailable.")
            return
        try:
            ok, msg = self.maintenance_service.check_integrity()
            self.maint_status_label.setText(msg)
            if ok:
                QMessageBox.information(self, "Integrity Check", msg)
            else:
                QMessageBox.critical(self, "Integrity Check Failed", msg)
        except Exception as e:
            self.maint_status_label.setText(f"Integrity check error: {e}")

    def on_reconcile_inventory(self):
        if not self.reconciliation_service or not self.session.branch_id:
            self.maint_status_label.setText("Reconciliation service unavailable or no active branch.")
            return
        try:
            discrepancies = self.reconciliation_service.reconcile_branch_inventory(self.session.branch_id)
            if discrepancies:
                self.maint_status_label.setText(
                    f"Reconciliation completed: {len(discrepancies)} discrepancies detected and alerts raised."
                )
                QMessageBox.warning(
                    self,
                    "Reconciliation Discrepancies",
                    f"{len(discrepancies)} mismatch(es) detected between inventory balances and movement ledger.\nAlerts created for audit review.",
                )
            else:
                self.maint_status_label.setText(
                    "Reconciliation completed successfully: All branch inventory balances match movement ledger."
                )
                QMessageBox.information(
                    self,
                    "Reconciliation Passed",
                    "All inventory quantities match movement ledger sums.",
                )
        except Exception as e:
            self.maint_status_label.setText(f"Reconciliation error: {e}")
