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
    QTabWidget,
    QFormLayout,
)
from PySide6.QtCore import Qt, QTimer
from shared.enums import PermissionCode
from desktop.app.ui.users.role_matrix_widget import RolePermissionMatrixWidget
from desktop.app.ui.common.title_bar import DialogHeaderBanner


class ResetPasswordDialog(QDialog):
    """Modal dialog allowing managers/admins to reset credentials for a staff account."""

    def __init__(self, parent, user_service, session, target_user_id: str, username: str, full_name: str):
        super().__init__(parent)
        self.user_service = user_service
        self.session = session
        self.target_user_id = target_user_id
        self.username = username
        self.full_name = full_name

        self.setWindowTitle(f"Reset Staff Password — {self.username}")
        self.setMinimumWidth(440)
        self.init_ui()

    def init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(DialogHeaderBanner(
            f"Reset Password: {self.full_name}",
            f"Username: {self.username} (Set a new login password)",
            icon_text="🔑",
            parent_dialog=self,
        ))

        layout = QVBoxLayout()
        layout.setContentsMargins(24, 20, 24, 24)
        layout.setSpacing(16)

        form_layout = QVBoxLayout()
        form_layout.setSpacing(10)

        self.new_pwd_input = QLineEdit()
        self.new_pwd_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.new_pwd_input.setPlaceholderText("New Password (minimum 4 characters) *")
        form_layout.addWidget(self.new_pwd_input)

        self.confirm_pwd_input = QLineEdit()
        self.confirm_pwd_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.confirm_pwd_input.setPlaceholderText("Confirm New Password *")
        form_layout.addWidget(self.confirm_pwd_input)

        self.show_pwd_check = QCheckBox("Show Password")
        self.show_pwd_check.toggled.connect(self._toggle_pwd_visibility)
        form_layout.addWidget(self.show_pwd_check)

        layout.addLayout(form_layout)

        self.error_label = QLabel("")
        self.error_label.setStyleSheet("color: #EF4444; font-size: 12px; font-weight: 600;")
        layout.addWidget(self.error_label)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("SecondaryBtn")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        self.submit_btn = QPushButton("Save New Password")
        self.submit_btn.setStyleSheet(
            "background-color: #2563EB; color: white; font-weight: 600; padding: 8px 16px; border-radius: 6px;"
        )
        self.submit_btn.clicked.connect(self._on_save)
        btn_layout.addWidget(self.submit_btn)

        layout.addLayout(btn_layout)
        root.addLayout(layout)

    def _toggle_pwd_visibility(self, checked: bool):
        mode = QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
        self.new_pwd_input.setEchoMode(mode)
        self.confirm_pwd_input.setEchoMode(mode)

    def _on_save(self):
        pwd = self.new_pwd_input.text()
        conf = self.confirm_pwd_input.text()

        if not pwd or len(pwd) < 4:
            self.error_label.setText("Password must be at least 4 characters.")
            self.new_pwd_input.setFocus()
            return
        if pwd != conf:
            self.error_label.setText("Passwords do not match.")
            self.confirm_pwd_input.setFocus()
            return

        try:
            self.user_service.reset_password(
                user_session=self.session,
                target_user_id=self.target_user_id,
                new_password=pwd,
            )
            QMessageBox.information(
                self,
                "Password Reset Successful",
                f"Password for '{self.username}' has been successfully updated.\nThe staff member can now log in using this password.",
            )
            self.accept()
        except Exception as e:
            self.error_label.setText(f"Error: {str(e)}")


class AddStaffDialog(QDialog):
    """Clean popup modal dialog to create a new staff account and login credentials."""

    def __init__(self, parent, user_service, session, roles: list):
        super().__init__(parent)
        self.user_service = user_service
        self.session = session
        self.roles = roles

        self.setWindowTitle("Add New Staff Account & Login")
        self.setMinimumWidth(480)
        self.init_ui()

    def init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(DialogHeaderBanner(
            "Create Staff Account",
            "Set staff personal details, assigned role, and login password",
            icon_text="👤",
            parent_dialog=self,
        ))

        layout = QVBoxLayout()
        layout.setContentsMargins(24, 20, 24, 24)
        layout.setSpacing(16)

        form = QFormLayout()
        form.setSpacing(12)

        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("e.g. jdoe")
        form.addRow("Username *:", self.username_input)

        self.fullname_input = QLineEdit()
        self.fullname_input.setPlaceholderText("e.g. John Doe")
        form.addRow("Full Name *:", self.fullname_input)

        self.email_input = QLineEdit()
        self.email_input.setPlaceholderText("e.g. jdoe@pharmacy.com (optional)")
        form.addRow("Email Address:", self.email_input)

        self.phone_input = QLineEdit()
        self.phone_input.setPlaceholderText("e.g. 08012345678 (optional)")
        form.addRow("Phone Number:", self.phone_input)

        self.role_combo = QComboBox()
        self.role_combo.addItem("Select Role (Optional)...", None)
        for r in self.roles:
            self.role_combo.addItem(r.name, r.id)
        form.addRow("Assigned Role:", self.role_combo)

        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_input.setPlaceholderText("Minimum 4 characters *")
        form.addRow("Initial Password *:", self.password_input)

        self.confirm_password_input = QLineEdit()
        self.confirm_password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.confirm_password_input.setPlaceholderText("Confirm password *")
        form.addRow("Confirm Password *:", self.confirm_password_input)

        self.admin_check = QCheckBox("Grant Organization Administrator Privileges")
        form.addRow("", self.admin_check)

        layout.addLayout(form)

        self.error_lbl = QLabel("")
        self.error_lbl.setStyleSheet("color: #EF4444; font-size: 12px; font-weight: 600;")
        layout.addWidget(self.error_lbl)

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("SecondaryBtn")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        self.save_btn = QPushButton("+ Create Account & Login")
        self.save_btn.setStyleSheet(
            "background-color: #10B981; color: white; font-weight: 700; padding: 8px 18px; border-radius: 6px;"
        )
        self.save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(self.save_btn)

        layout.addLayout(btn_row)
        root.addLayout(layout)

    def _on_save(self):
        username = self.username_input.text().strip()
        full_name = self.fullname_input.text().strip()
        password = self.password_input.text()
        confirm_password = self.confirm_password_input.text()
        role_id = self.role_combo.currentData()

        if not username:
            self.error_lbl.setText("Please enter a username.")
            self.username_input.setFocus()
            return
        if not full_name:
            self.error_lbl.setText("Please enter a full name.")
            self.fullname_input.setFocus()
            return
        if not password or len(password) < 4:
            self.error_lbl.setText("Password must be at least 4 characters.")
            self.password_input.setFocus()
            return
        if password != confirm_password:
            self.error_lbl.setText("Passwords do not match.")
            self.confirm_password_input.setFocus()
            return

        try:
            self.user_service.create_user(
                user_session=self.session,
                username=username,
                full_name=full_name,
                email=self.email_input.text().strip(),
                phone=self.phone_input.text().strip(),
                is_org_admin=self.admin_check.isChecked(),
                default_branch_id=self.session.branch_id or None,
                password=password,
                role_id=role_id,
            )
            QMessageBox.information(
                self,
                "Account Created",
                f"Staff account '{username}' has been successfully created and is ready to log in.",
            )
            self.accept()
        except Exception as e:
            self.error_lbl.setText(f"Error: {str(e)}")


class EditStaffDialog(QDialog):
    """Clean popup modal dialog to edit an existing staff account's profile, role, and status."""

    def __init__(self, parent, user_service, session, target_user, roles: list, current_role_names: list):
        super().__init__(parent)
        self.user_service = user_service
        self.session = session
        self.user = target_user
        self.roles = roles
        self.current_role_names = current_role_names

        self.setWindowTitle(f"Edit Staff Member — {self.user.username}")
        self.setMinimumWidth(480)
        self.init_ui()

    def init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(DialogHeaderBanner(
            f"Edit Staff: {self.user.full_name or self.user.username}",
            f"Username: {self.user.username}",
            icon_text="✏️",
            parent_dialog=self,
        ))

        layout = QVBoxLayout()
        layout.setContentsMargins(24, 20, 24, 24)
        layout.setSpacing(16)

        form = QFormLayout()
        form.setSpacing(12)

        self.fullname_input = QLineEdit()
        self.fullname_input.setText(self.user.full_name or "")
        form.addRow("Full Name *:", self.fullname_input)

        self.email_input = QLineEdit()
        self.email_input.setText(self.user.email or "")
        form.addRow("Email Address:", self.email_input)

        self.phone_input = QLineEdit()
        self.phone_input.setText(self.user.phone or "")
        form.addRow("Phone Number:", self.phone_input)

        self.role_combo = QComboBox()
        self.role_combo.addItem("Select Role (Optional)...", None)
        selected_idx = 0
        for idx, r in enumerate(self.roles):
            self.role_combo.addItem(r.name, r.id)
            if r.name in self.current_role_names:
                selected_idx = idx + 1
        self.role_combo.setCurrentIndex(selected_idx)
        form.addRow("Assigned Role:", self.role_combo)

        self.admin_check = QCheckBox("Organization Administrator Privileges")
        self.admin_check.setChecked(bool(self.user.is_org_admin))
        form.addRow("", self.admin_check)

        self.active_check = QCheckBox("Account Active (Can log in)")
        self.active_check.setChecked(bool(self.user.is_active))
        form.addRow("Account Status:", self.active_check)

        layout.addLayout(form)

        self.error_lbl = QLabel("")
        self.error_lbl.setStyleSheet("color: #EF4444; font-size: 12px; font-weight: 600;")
        layout.addWidget(self.error_lbl)

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

        layout.addLayout(btn_row)
        root.addLayout(layout)

    def _on_save(self):
        full_name = self.fullname_input.text().strip()
        if not full_name:
            self.error_lbl.setText("Full name cannot be empty.")
            self.fullname_input.setFocus()
            return

        role_id = self.role_combo.currentData()
        try:
            self.user_service.update_user(
                user_session=self.session,
                target_user_id=self.user.id,
                full_name=full_name,
                email=self.email_input.text().strip(),
                phone=self.phone_input.text().strip(),
                is_org_admin=self.admin_check.isChecked(),
                is_active=self.active_check.isChecked(),
                role_id=role_id,
            )
            QMessageBox.information(
                self,
                "Profile Updated",
                f"Staff member '{self.user.username}' has been updated successfully.",
            )
            self.accept()
        except Exception as e:
            self.error_lbl.setText(f"Error: {str(e)}")


class UsersWidget(QWidget):
    """Desktop UI screen for viewing and managing users, passwords, and roles within the organization."""

    def __init__(self, session, user_service=None):
        super().__init__()
        self.session = session
        self.user_service = user_service

        # Roles cache
        self.roles = []
        self.user_roles_map = {}

        # Pagination & Data Cache
        self.all_users = []
        self.filtered_users = []
        self.current_page = 1
        self.page_size = 50
        self.total_pages = 1

        # Search debounce timer (150ms)
        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(150)
        self.search_timer.timeout.connect(self._apply_filter_and_render)

        self.init_ui()
        self.refresh_data()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        # Header with Title, Subtitle, and Add Staff Action Button
        header_layout = QHBoxLayout()
        title_col = QVBoxLayout()
        title_col.setSpacing(4)

        header = QLabel("User & Role Management")
        header.setObjectName("PageHeader")
        subtitle = QLabel("Staff credentials, branch assignments, role-based access control (RBAC) & login access")
        subtitle.setObjectName("PageSubtitle")
        title_col.addWidget(header)
        title_col.addWidget(subtitle)
        header_layout.addLayout(title_col)
        header_layout.addStretch()

        can_manage = self.session.has_permission(PermissionCode.USERS_MANAGE.value)

        self.add_staff_btn = QPushButton("+ Add Staff Account")
        self.add_staff_btn.setStyleSheet(
            "background-color: #10B981; color: white; font-weight: 700; padding: 8px 18px; border-radius: 6px;"
        )
        self.add_staff_btn.setEnabled(can_manage)
        self.add_staff_btn.clicked.connect(self._open_add_staff_dialog)
        header_layout.addWidget(self.add_staff_btn)

        self.edit_staff_btn = QPushButton("✏️ Edit Staff")
        self.edit_staff_btn.setStyleSheet(
            "background-color: #2563EB; color: white; font-weight: 700; padding: 8px 18px; border-radius: 6px;"
        )
        self.edit_staff_btn.setEnabled(can_manage)
        self.edit_staff_btn.clicked.connect(self._on_edit_selected_staff)
        header_layout.addWidget(self.edit_staff_btn)

        self.pwd_btn = QPushButton("🔑 Reset Password")
        self.pwd_btn.setStyleSheet(
            "background-color: #D97706; color: white; font-weight: 700; padding: 8px 18px; border-radius: 6px;"
        )
        self.pwd_btn.setEnabled(can_manage)
        self.pwd_btn.clicked.connect(self._on_reset_selected_password)
        header_layout.addWidget(self.pwd_btn)

        self.refresh_btn = QPushButton("Refresh Data")
        self.refresh_btn.setObjectName("SecondaryBtn")
        self.refresh_btn.clicked.connect(self.refresh_data)
        header_layout.addWidget(self.refresh_btn)

        layout.addLayout(header_layout)

        self.tabs = QTabWidget()

        # Tab 1: Staff Accounts
        staff_tab = QWidget()
        staff_layout = QVBoxLayout(staff_tab)
        staff_layout.setContentsMargins(0, 8, 0, 0)
        staff_layout.setSpacing(14)

        # Search and Role Filter Bar
        filter_layout = QHBoxLayout()
        filter_layout.setSpacing(12)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search staff by username, full name, email, or phone...")
        self.search_input.textChanged.connect(lambda: self.search_timer.start())
        filter_layout.addWidget(self.search_input, stretch=3)

        self.role_filter = QComboBox()
        self.role_filter.addItem("All Roles", None)
        self.role_filter.currentIndexChanged.connect(self._apply_filter_and_render)
        filter_layout.addWidget(self.role_filter, stretch=1)

        self.status_filter = QComboBox()
        self.status_filter.addItem("All Statuses", "ALL")
        self.status_filter.addItem("Active Only", "ACTIVE")
        self.status_filter.addItem("Inactive Only", "INACTIVE")
        self.status_filter.currentIndexChanged.connect(self._apply_filter_and_render)
        filter_layout.addWidget(self.status_filter, stretch=1)

        staff_layout.addLayout(filter_layout)

        # Users Table (Clean 6 columns)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels([
            "Username",
            "Full Name",
            "Role / Privileges",
            "Email Address",
            "Phone Number",
            "Status",
        ])
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.cellDoubleClicked.connect(self._on_table_double_clicked)

        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.Interactive)
        hdr.setSectionResizeMode(1, QHeaderView.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.Interactive)
        hdr.setSectionResizeMode(3, QHeaderView.Interactive)
        hdr.setSectionResizeMode(4, QHeaderView.Interactive)
        hdr.setSectionResizeMode(5, QHeaderView.Interactive)

        self.table.setColumnWidth(0, 140)
        self.table.setColumnWidth(2, 180)
        self.table.setColumnWidth(3, 190)
        self.table.setColumnWidth(4, 130)
        self.table.setColumnWidth(5, 100)

        self.table.verticalHeader().setDefaultSectionSize(40)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        staff_layout.addWidget(self.table)

        # Pagination Bar
        pagination_layout = QHBoxLayout()
        pagination_layout.setSpacing(12)

        self.page_status_label = QLabel("Showing 0 staff members")
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

        staff_layout.addLayout(pagination_layout)
        self.tabs.addTab(staff_tab, "👥 Staff Accounts & Passwords")

        # Tab 2: Roles & Permissions Matrix
        self.role_matrix_widget = RolePermissionMatrixWidget(self.session, self.user_service)
        self.tabs.addTab(self.role_matrix_widget, "🛡️ Roles & Permissions Matrix")

        layout.addWidget(self.tabs)

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
        if not self.user_service or not self.session.organization_id:
            return

        # Refresh roles in combobox
        try:
            self.roles = self.user_service.list_roles(self.session.organization_id)
            self.role_filter.blockSignals(True)
            self.role_filter.clear()
            self.role_filter.addItem("All Roles", None)
            for r in self.roles:
                self.role_filter.addItem(r.name, r.name)
            self.role_filter.blockSignals(False)
        except Exception:
            pass

        # Refresh user roles map
        try:
            self.user_roles_map = self.user_service.get_user_roles_map(self.session.organization_id)
        except Exception:
            self.user_roles_map = {}

        self.all_users = self.user_service.list_users(self.session.organization_id, active_only=False)
        self._apply_filter_and_render()

    def _apply_filter_and_render(self):
        query = self.search_input.text().strip().lower()
        selected_role = self.role_filter.currentData()
        selected_status = self.status_filter.currentData()

        filtered = []
        for u in self.all_users:
            if query:
                match_str = f"{u.username} {u.full_name or ''} {u.email or ''} {u.phone or ''}".lower()
                if query not in match_str:
                    continue

            if selected_role:
                assigned = self.user_roles_map.get(u.id, [])
                if selected_role not in assigned:
                    continue

            if selected_status == "ACTIVE" and not u.is_active:
                continue
            elif selected_status == "INACTIVE" and u.is_active:
                continue

            filtered.append(u)

        self.filtered_users = filtered
        total_count = len(filtered)
        self.total_pages = max(1, (total_count + self.page_size - 1) // self.page_size) if self.page_size > 0 else 1
        self.current_page = min(self.current_page, self.total_pages)
        self._render_current_page()

    def _render_current_page(self):
        total_count = len(self.filtered_users)
        start_idx = (self.current_page - 1) * self.page_size
        end_idx = min(start_idx + self.page_size, total_count)
        page_items = self.filtered_users[start_idx:end_idx]

        can_manage = self.session.has_permission(PermissionCode.USERS_MANAGE.value)

        self.table.setUpdatesEnabled(False)
        self.table.blockSignals(True)
        try:
            self.table.setRowCount(len(page_items))
            for row, u in enumerate(page_items):
                self.table.setItem(row, 0, QTableWidgetItem(u.username))
                self.table.setItem(row, 1, QTableWidgetItem(u.full_name or ""))

                # Role or Org Admin Tag
                assigned = self.user_roles_map.get(u.id, [])
                role_display = ", ".join(assigned) if assigned else ("Org Admin" if u.is_org_admin else "Staff")
                if u.is_org_admin and "Org Admin" not in role_display:
                    role_display += " (Org Admin)"
                self.table.setItem(row, 2, QTableWidgetItem(role_display))

                self.table.setItem(row, 3, QTableWidgetItem(u.email or "-"))
                self.table.setItem(row, 4, QTableWidgetItem(u.phone or "-"))

                # Status
                status_item = QTableWidgetItem("Active" if u.is_active else "Inactive")
                status_item.setTextAlignment(Qt.AlignCenter)
                if u.is_active:
                    status_item.setForeground(Qt.darkGreen)
                else:
                    status_item.setForeground(Qt.gray)
                self.table.setItem(row, 5, status_item)
        finally:
            self.table.blockSignals(False)
            self.table.setUpdatesEnabled(True)

        if total_count == 0:
            self.page_status_label.setText("Showing 0 staff members")
        else:
            self.page_status_label.setText(f"Showing {start_idx + 1}–{end_idx} of {total_count} staff members")
        self.page_info_label.setText(f"Page {self.current_page} of {self.total_pages}")
        self.prev_page_btn.setEnabled(self.current_page > 1)
        self.next_page_btn.setEnabled(self.current_page < self.total_pages)

    def _on_edit_selected_staff(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(
                self,
                "Selection Required",
                "Please click a row in the table to select a staff member first."
            )
            return
        start_idx = (self.current_page - 1) * self.page_size
        idx = start_idx + row
        if 0 <= idx < len(self.filtered_users):
            self._open_edit_staff_dialog(self.filtered_users[idx])

    def _on_reset_selected_password(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(
                self,
                "Selection Required",
                "Please click a row in the table to select a staff member first."
            )
            return
        start_idx = (self.current_page - 1) * self.page_size
        idx = start_idx + row
        if 0 <= idx < len(self.filtered_users):
            self._open_reset_password_dialog(self.filtered_users[idx])

    def _on_table_double_clicked(self, row, col):
        start_idx = (self.current_page - 1) * self.page_size
        idx = start_idx + row
        if 0 <= idx < len(self.filtered_users):
            user = self.filtered_users[idx]
            if self.session.has_permission(PermissionCode.USERS_MANAGE.value):
                self._open_edit_staff_dialog(user)

    def _open_add_staff_dialog(self):
        dlg = AddStaffDialog(
            parent=self,
            user_service=self.user_service,
            session=self.session,
            roles=self.roles,
        )
        if dlg.exec() == QDialog.Accepted:
            self.refresh_data()

    def _open_edit_staff_dialog(self, target_user):
        assigned = self.user_roles_map.get(target_user.id, [])
        dlg = EditStaffDialog(
            parent=self,
            user_service=self.user_service,
            session=self.session,
            target_user=target_user,
            roles=self.roles,
            current_role_names=assigned,
        )
        if dlg.exec() == QDialog.Accepted:
            self.refresh_data()

    def _open_reset_password_dialog(self, target_user):
        dlg = ResetPasswordDialog(
            parent=self,
            user_service=self.user_service,
            session=self.session,
            target_user_id=target_user.id,
            username=target_user.username,
            full_name=target_user.full_name or target_user.username,
        )
        dlg.exec()
