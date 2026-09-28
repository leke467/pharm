import os
import re
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QComboBox,
    QPushButton,
    QCheckBox,
    QFrame,
    QApplication,
    QDialog,
    QFormLayout,
    QMessageBox,
)
from PySide6.QtGui import (
    QPixmap,
    QPainter,
    QColor,
    QPen,
    QBrush,
    QIcon,
    QLinearGradient,
    QKeySequence,
    QShortcut,
)
from PySide6.QtCore import Signal, Qt, QSettings
from desktop.app.ui.common.logo import create_logo_icon, LogoWidget
from desktop.app.ui.common.title_bar import CustomTitleBar, DialogHeaderBanner


class PharmacyOnboardingDialog(QDialog):
    """
    First-time Setup & Branch Onboarding Wizard launched directly from the Login Screen.
    Lets an installer or owner configure the Pharmacy Name, Organization Code, Branch Name/Code,
    Admin login credentials, and Cloud Sync URL on any new computer.
    """

    def __init__(self, parent, organization_service):
        super().__init__(parent)
        self.organization_service = organization_service
        self.setup_result = None
        self.setWindowTitle("New Pharmacy & Branch Terminal Setup")
        self.setMinimumWidth(520)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        banner = DialogHeaderBanner(
            title="New Pharmacy & Branch Setup Wizard",
            subtitle="Configure pharmacy name, branch terminal identity, admin login, and cloud sync",
            parent_dialog=self,
        )
        layout.addWidget(banner)

        body = QWidget()
        body.setStyleSheet(
            "QWidget { background-color: #FFFFFF; color: #0F172A; } "
            "QLineEdit { background-color: #FFFFFF; border: 1px solid #CBD5E1; border-radius: 6px; padding: 7px 10px; color: #0F172A; } "
            "QLabel { color: #1E293B; font-weight: 600; }"
        )
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(24, 18, 24, 22)
        body_layout.setSpacing(12)

        form = QFormLayout()
        form.setSpacing(10)

        self.pharm_name_in = QLineEdit()
        self.pharm_name_in.setPlaceholderText("e.g. GraceLand Pharmacy Ltd")
        form.addRow("Pharmacy Name *:", self.pharm_name_in)

        self.org_code_in = QLineEdit()
        self.org_code_in.setPlaceholderText("e.g. GRACELAND (same across all branches)")
        form.addRow("Organization Code *:", self.org_code_in)

        self.branch_name_in = QLineEdit("Main Branch")
        self.branch_name_in.setPlaceholderText("e.g. Main Branch - Ikeja or Lekki Branch")
        form.addRow("This PC's Branch Name *:", self.branch_name_in)

        self.branch_code_in = QLineEdit("BR01")
        self.branch_code_in.setPlaceholderText("e.g. BR01 (HQ), BR02 (Branch 2)")
        form.addRow("This PC's Branch Code *:", self.branch_code_in)

        self.address_in = QLineEdit()
        self.address_in.setPlaceholderText("Branch street address & phone (optional)")
        form.addRow("Branch Address:", self.address_in)

        self.admin_user_in = QLineEdit("admin")
        self.admin_user_in.setPlaceholderText("e.g. admin")
        form.addRow("Admin Username *:", self.admin_user_in)

        self.admin_name_in = QLineEdit("Pharmacy Administrator")
        form.addRow("Admin Full Name *:", self.admin_name_in)

        self.admin_pwd_in = QLineEdit()
        self.admin_pwd_in.setEchoMode(QLineEdit.Password)
        self.admin_pwd_in.setPlaceholderText("Set admin login password (min 4 chars) *")
        form.addRow("Admin Password *:", self.admin_pwd_in)

        self.cloud_url_in = QLineEdit()
        self.cloud_url_in.setPlaceholderText("Optional: https://cloud.yourpharmacy.com (leave blank if offline)")
        form.addRow("Cloud Server URL:", self.cloud_url_in)

        body_layout.addLayout(form)

        self.err_lbl = QLabel("")
        self.err_lbl.setStyleSheet("color: #EF4444; font-size: 12px; font-weight: 600;")
        body_layout.addWidget(self.err_lbl)

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet(
            "background-color: #F1F5F9; color: #334155; border: 1px solid #CBD5E1; "
            "font-weight: 600; padding: 8px 16px; border-radius: 6px;"
        )
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        save_btn = QPushButton("🚀 Initialize Pharmacy & Branch")
        save_btn.setStyleSheet(
            "background-color: #10B981; color: #FFFFFF; font-weight: 700; padding: 8px 18px; border-radius: 6px;"
        )
        save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(save_btn)

        body_layout.addLayout(btn_row)
        layout.addWidget(body)

    def _on_save(self):
        if not self.organization_service:
            self.err_lbl.setText("Organization service unavailable.")
            return
        try:
            res = self.organization_service.setup_pharmacy_onboarding(
                pharmacy_name=self.pharm_name_in.text(),
                org_code=self.org_code_in.text(),
                branch_name=self.branch_name_in.text(),
                branch_code=self.branch_code_in.text(),
                admin_username=self.admin_user_in.text(),
                admin_full_name=self.admin_name_in.text(),
                admin_password=self.admin_pwd_in.text(),
                address=self.address_in.text(),
                cloud_server_url=self.cloud_url_in.text(),
            )
            self.setup_result = res
            if self.cloud_url_in.text().strip():
                qset = QSettings("PharmaCare", "PharmaCareEnterprise")
                qset.setValue("cloud_server_url", self.cloud_url_in.text().strip())
            QMessageBox.information(
                self,
                "Pharmacy Setup Complete",
                f"Pharmacy '{res['organization_name']}' ({res['organization_code']}) and branch "
                f"'{res['branch_name']}' ({res['branch_code']}) have been configured!\n\n"
                f"You can now sign in with username '{res['admin_username']}'.",
            )
            self.accept()
        except Exception as e:
            self.err_lbl.setText(str(e))


class HeroPanel(QFrame):
    """
    Left-hand hero panel displaying a cinematic pharmacy graphic with dark gradient overlay,
    welcome typography, and floating KPI stat callout cards matching the split-screen design.
    """

    def __init__(self, image_path: str, parent=None):
        super().__init__(parent)
        self.image_path = image_path
        self._pixmap = QPixmap(image_path) if os.path.exists(image_path) else None

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        w, h = self.width(), self.height()

        if self._pixmap and not self._pixmap.isNull():
            # Scale pixmap to cover the whole frame preserving aspect ratio
            scaled = self._pixmap.scaled(
                self.size(),
                Qt.KeepAspectRatioByExpanding,
                Qt.SmoothTransformation,
            )
            # Center crop
            x = max(0, (scaled.width() - w) // 2)
            y = max(0, (scaled.height() - h) // 2)
            painter.drawPixmap(0, 0, scaled, x, y, w, h)
        else:
            # Fallback deep navy/slate gradient
            grad = QLinearGradient(0, 0, w, h)
            grad.setColorAt(0.0, QColor(15, 23, 42))
            grad.setColorAt(1.0, QColor(6, 78, 59))
            painter.fillRect(0, 0, w, h, grad)

        # Draw a rich dark gradient overlay from bottom to top for contrast
        overlay = QLinearGradient(0, 0, 0, h)
        overlay.setColorAt(0.0, QColor(10, 15, 25, 75))
        overlay.setColorAt(0.35, QColor(10, 15, 25, 110))
        overlay.setColorAt(0.65, QColor(10, 15, 25, 190))
        overlay.setColorAt(1.0, QColor(10, 15, 25, 245))
        painter.fillRect(0, 0, w, h, overlay)

        painter.end()


class LoginWidget(QWidget):
    login_successful = Signal(object)

    def __init__(
        self,
        auth_manager,
        organization_service=None,
        licensing_service=None,
        api_client=None,
        backup_service=None,
    ):
        super().__init__()
        self.auth_manager = auth_manager
        self.organization_service = organization_service
        self.licensing_service = licensing_service
        self.api_client = api_client
        self.backup_service = backup_service
        self.setWindowTitle("Sign In — PharmaCare Enterprise")
        self.setWindowIcon(create_logo_icon(32))
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.resize(1020, 680)
        self.setMinimumSize(920, 620)
        self.init_ui()
        self.center_on_screen()
        self.populate_branches()
        self.load_remembered_credentials()
        self.refresh_subscription_badge()

        try:
            self._prt_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Print), self)
            self._prt_shortcut.activated.connect(self._handle_print_screen)
        except Exception:
            pass

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
            screen_geo = screen.availableGeometry()
            x = (screen_geo.width() - self.width()) // 2
            y = (screen_geo.height() - self.height()) // 2
            self.move(x, y)

    @staticmethod
    def _create_eye_icon(closed: bool = False) -> QIcon:
        """Draws a clean, crisp vector eye icon for toggling password visibility."""
        pixmap = QPixmap(24, 24)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)

        color = QColor(160, 175, 195)
        pen = QPen(color, 2.0)
        painter.setPen(pen)

        # Outer eye almond shape
        painter.drawEllipse(2, 6, 20, 12)

        # Inner pupil
        painter.setBrush(QBrush(color))
        painter.drawEllipse(9, 9, 6, 6)

        if closed:
            # Diagonal red slash across the eye to indicate hidden state
            slash_pen = QPen(QColor(239, 68, 68), 2.2)
            painter.setPen(slash_pen)
            painter.drawLine(3, 4, 21, 20)

        painter.end()
        return QIcon(pixmap)

    def init_ui(self):
        # Outer vertical layout: CustomTitleBar + split-screen body
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        self.custom_title_bar = CustomTitleBar(
            self,
            title_text="PharmaCare Pro",
            subtitle_text="Secure Sign-In Portal",
        )
        outer_layout.addWidget(self.custom_title_bar)

        body_container = QWidget()
        root_layout = QHBoxLayout(body_container)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        outer_layout.addWidget(body_container, 1)

        # ----------------------------------------------------------------------
        # LEFT PANEL: Hero Graphic + Overlaid Typography & Stat Cards
        # ----------------------------------------------------------------------
        hero_img_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "resources",
            "login_hero.jpg",
        )
        self.hero_panel = HeroPanel(hero_img_path, self)

        hero_layout = QVBoxLayout(self.hero_panel)
        hero_layout.setContentsMargins(40, 44, 40, 40)
        hero_layout.setSpacing(16)

        # Top pill badge with geometric logo
        top_badge = QFrame()
        top_badge.setStyleSheet(
            "background-color: rgba(18, 20, 29, 0.85); "
            "border: 1px solid rgba(255, 255, 255, 0.18); "
            "border-radius: 14px; padding: 4px 10px;"
        )
        tb_layout = QHBoxLayout(top_badge)
        tb_layout.setContentsMargins(4, 2, 8, 2)
        tb_layout.setSpacing(8)
        mini_logo = LogoWidget(size=18, on_dark=True)
        tb_text = QLabel("PHARMACARE OS v1.0")
        tb_text.setStyleSheet(
            "color: #FFFFFF; font-size: 11px; font-weight: 800; letter-spacing: 0.5px; background: transparent;"
        )
        tb_layout.addWidget(mini_logo)
        tb_layout.addWidget(tb_text)
        hero_layout.addWidget(top_badge, alignment=Qt.AlignLeft)
        hero_layout.addStretch()

        # Large "PharmaCare" Brand Name (User requested: name of the application on the left)
        brand_name = QLabel("PharmaCare")
        brand_name.setStyleSheet(
            "color: #FFFFFF; font-size: 52px; font-weight: 900; "
            "letter-spacing: -1.5px; background: transparent;"
        )
        hero_layout.addWidget(brand_name)

        brand_tagline = QLabel("Enterprise Pharmacy Platform")
        brand_tagline.setStyleSheet(
            "color: #F59E0B; font-size: 14px; font-weight: 700; "
            "letter-spacing: 2px; text-transform: uppercase; "
            "margin-bottom: 8px; background: transparent;"
        )
        hero_layout.addWidget(brand_tagline)

        # Welcome Back Headline
        welcome_title = QLabel("Welcome Back")
        welcome_title.setStyleSheet(
            "color: #FFFFFF; font-size: 34px; font-weight: 900; letter-spacing: -0.5px; background: transparent;"
        )
        hero_layout.addWidget(welcome_title)

        # Welcome Subtitle
        welcome_sub = QLabel(
            "Clinical-grade dispensing, multi-branch synchronization & zero-downtime offline resilience."
        )
        welcome_sub.setWordWrap(True)
        welcome_sub.setStyleSheet(
            "color: #CBD5E1; font-size: 13px; line-height: 1.5; margin-bottom: 12px; background: transparent;"
        )
        hero_layout.addWidget(welcome_sub)

        hero_layout.addSpacing(12)

        root_layout.addWidget(self.hero_panel, 5)

        # ----------------------------------------------------------------------
        # RIGHT PANEL: Sleek Dark Login Card (Matching Reference Screenshot)
        # ----------------------------------------------------------------------
        right_panel = QFrame()
        right_panel.setObjectName("RightPanel")
        right_panel.setStyleSheet("background-color: #12131C; border: none;")

        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(40, 36, 40, 36)
        right_layout.setAlignment(Qt.AlignCenter)

        # Form Container (Constrained width for centered, crisp look)
        form_card = QFrame()
        form_card.setMaximumWidth(400)
        form_layout = QVBoxLayout(form_card)
        form_layout.setContentsMargins(0, 0, 0, 0)
        form_layout.setSpacing(14)

        # 1. Top Brand Logo Badge (Apex 3D isometric prism)
        logo_badge = QFrame()
        logo_badge.setFixedSize(58, 58)
        logo_badge.setStyleSheet(
            "background-color: rgba(26, 130, 252, 0.1); "
            "border: 1px solid rgba(26, 130, 252, 0.3); "
            "border-radius: 16px;"
        )
        lb_layout = QVBoxLayout(logo_badge)
        lb_layout.setContentsMargins(0, 0, 0, 0)
        lb_layout.setAlignment(Qt.AlignCenter)
        main_logo = LogoWidget(size=40, on_dark=True)
        lb_layout.addWidget(main_logo)

        badge_container = QHBoxLayout()
        badge_container.addStretch()
        badge_container.addWidget(logo_badge)
        badge_container.addStretch()
        form_layout.addLayout(badge_container)

        # 2. Title (Dynamic pharmacy name from org code) & Subtitle
        self.pharmacy_name_label = QLabel("MEDCARE")
        self.pharmacy_name_label.setAlignment(Qt.AlignCenter)
        self.pharmacy_name_label.setStyleSheet(
            "font-size: 24px; font-weight: 900; color: #F59E0B; letter-spacing: 2px; margin-top: 4px;"
        )
        form_layout.addWidget(self.pharmacy_name_label)

        subtitle = QLabel("Sign in to your account")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet("font-size: 13px; color: #8E95A5; margin-bottom: 8px;")
        form_layout.addWidget(subtitle)

        # Input Field Styles
        res_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "resources").replace("\\", "/")
        input_style = f"""
            QLineEdit {{
                background-color: #1E202B;
                border: 1px solid #2D3142;
                border-radius: 8px;
                padding: 10px 14px;
                color: #FFFFFF;
                font-size: 13px;
                min-height: 22px;
            }}
            QComboBox {{
                background-color: #1E202B;
                border: 1px solid #2D3142;
                border-radius: 8px;
                padding: 10px 34px 10px 14px;
                color: #FFFFFF;
                font-size: 13px;
                min-height: 22px;
            }}
            QLineEdit:focus, QComboBox:focus {{
                border: 1.5px solid #F59E0B;
                background-color: #232736;
            }}
            QComboBox::drop-down {{
                subcontrol-origin: border;
                subcontrol-position: top right;
                width: 30px;
                border-left: 1px solid #2D3142;
                border-top-right-radius: 7px;
                border-bottom-right-radius: 7px;
                background-color: #25293A;
                margin-right: 1px;
                margin-top: 1px;
                margin-bottom: 1px;
            }}
            QComboBox::drop-down:hover {{
                background-color: #2D3246;
            }}
            QComboBox::down-arrow {{
                image: url({res_dir}/arrow_down_hover.svg);
                width: 12px;
                height: 12px;
            }}
            QComboBox QAbstractItemView {{
                background-color: #1E202B;
                border: 1px solid #2D3142;
                color: #FFFFFF;
                selection-background-color: #D97706;
                selection-color: #FFFFFF;
                padding: 4px;
            }}
        """
        form_card.setStyleSheet(input_style)

        # 3. Organization / Pharmacy Name Display (Read-Only after setup)
        self._resolved_org_code = "MEDCARE"
        self.org_code_input = QLineEdit()
        self.org_code_input.setText("MEDCARE")
        self.org_code_input.setReadOnly(True)
        self.org_code_input.setFocusPolicy(Qt.NoFocus)
        self.org_code_input.setToolTip("Pharmacy Organization (Configured during Setup Wizard)")
        self.org_code_input.setStyleSheet("""
            QLineEdit {
                background-color: #151722;
                border: 1px solid #25293A;
                border-radius: 8px;
                padding: 10px 14px;
                color: #94A3B8;
                font-size: 13px;
                font-weight: 700;
                min-height: 22px;
            }
        """)
        form_layout.addWidget(self.org_code_input)

        # 4. Username Input
        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("Enter your username *")
        self.username_input.textChanged.connect(self.clear_error)
        self.username_input.returnPressed.connect(self.attempt_login)
        form_layout.addWidget(self.username_input)

        # 5. Password Input with Vector Eye Toggle
        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText("Enter your password *")
        self.password_input.setEchoMode(QLineEdit.Password)
        self.password_input.textChanged.connect(self.clear_error)
        self.password_input.returnPressed.connect(self.attempt_login)

        self.eye_open_icon = self._create_eye_icon(closed=False)
        self.eye_closed_icon = self._create_eye_icon(closed=True)

        self.toggle_pwd_action = self.password_input.addAction(
            self.eye_closed_icon,
            QLineEdit.TrailingPosition,
        )
        self.toggle_pwd_action.setToolTip("Click to show / hide password")
        self.toggle_pwd_action.triggered.connect(self.toggle_password_visibility)
        form_layout.addWidget(self.password_input)

        # 6. Branch Selector
        self.branch_select = QComboBox()
        self.branch_select.currentIndexChanged.connect(self._on_branch_changed)
        form_layout.addWidget(self.branch_select)

        # 7. Remember Username / Offline Status Row
        aux_row = QHBoxLayout()
        self.remember_check = QCheckBox("Remember username")
        self.remember_check.setChecked(True)
        self.remember_check.setStyleSheet("color: #8E95A5; font-size: 12px;")
        aux_row.addWidget(self.remember_check)
        aux_row.addStretch()

        offline_indicator = QLabel("Offline Ready")
        offline_indicator.setStyleSheet("color: #F59E0B; font-size: 12px; font-weight: 600;")
        aux_row.addWidget(offline_indicator)
        form_layout.addLayout(aux_row)

        # 8. Primary Sign In Button (Golden/Amber gradient matching reference)
        self.login_btn = QPushButton("➔  SIGN IN")
        self.login_btn.setCursor(Qt.PointingHandCursor)
        self.login_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #E58E26, stop:1 #D35400);
                color: #FFFFFF;
                font-size: 14px;
                font-weight: 800;
                border: none;
                border-radius: 8px;
                padding: 12px 20px;
                letter-spacing: 1px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #F39C12, stop:1 #E67E22);
            }
            QPushButton:pressed {
                background: #BA4A00;
            }
            QPushButton:disabled {
                background: #3E3B3A;
                color: #7A7674;
            }
        """)
        self.login_btn.clicked.connect(self.attempt_login)
        form_layout.addWidget(self.login_btn)

        # 9. Divider with "OR" text (Matching reference screenshot)
        sep_row = QHBoxLayout()
        line1 = QFrame()
        line1.setFrameShape(QFrame.HLine)
        line1.setStyleSheet("border: none; background-color: #2D3142; max-height: 1px;")
        sep_lbl = QLabel("OR")
        sep_lbl.setStyleSheet("color: #555C70; font-size: 11px; font-weight: 700; padding: 0 8px;")
        line2 = QFrame()
        line2.setFrameShape(QFrame.HLine)
        line2.setStyleSheet("border: none; background-color: #2D3142; max-height: 1px;")
        sep_row.addWidget(line1)
        sep_row.addWidget(sep_lbl)
        sep_row.addWidget(line2)
        form_layout.addLayout(sep_row)

        # 10. Secondary Offline Emergency Action
        self.offline_btn = QPushButton("⚙  Offline Emergency Sign In")
        self.offline_btn.setCursor(Qt.PointingHandCursor)
        self.offline_btn.setStyleSheet("""
            QPushButton {
                background-color: #1A1D27;
                border: 1px solid #2D3142;
                color: #CBD5E1;
                font-size: 13px;
                font-weight: 600;
                border-radius: 8px;
                padding: 10px 16px;
            }
            QPushButton:hover {
                background-color: #232736;
                border-color: #475569;
                color: #FFFFFF;
            }
        """)
        self.offline_btn.clicked.connect(self.attempt_login)
        form_layout.addWidget(self.offline_btn)

        # 11. Error Alert Banner (Hidden until triggered)
        self.error_label = QLabel("")
        self.error_label.setObjectName("ErrorLabel")
        self.error_label.setAlignment(Qt.AlignCenter)
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("""
            QLabel#ErrorLabel {
                color: #FCA5A5;
                background-color: rgba(239, 68, 68, 0.15);
                border: 1px solid rgba(239, 68, 68, 0.4);
                border-radius: 8px;
                padding: 10px 14px;
                font-size: 12px;
                font-weight: 500;
                line-height: 1.4;
            }
        """)
        self.error_label.setVisible(False)
        form_layout.addWidget(self.error_label)

        # 12. Bottom Subscription & Help Row
        help_row = QHBoxLayout()
        self.sub_status_btn = QPushButton("💳  Sub: 30 Days Left")
        self.sub_status_btn.setCursor(Qt.PointingHandCursor)
        self.sub_status_btn.setStyleSheet("""
            QPushButton {
                background-color: #065F46;
                color: #ECFDF5;
                font-size: 11px;
                font-weight: 700;
                border-radius: 14px;
                padding: 6px 14px;
                border: 1px solid #10B981;
            }
            QPushButton:hover {
                background-color: #047857;
            }
        """)
        self.sub_status_btn.clicked.connect(lambda: self._open_subscription_dialog(locked_mode=False))
        help_row.addWidget(self.sub_status_btn)

        help_row.addStretch()

        self.cloud_restore_btn = QPushButton("☁️  Restore Branch")
        self.cloud_restore_btn.setCursor(Qt.PointingHandCursor)
        self.cloud_restore_btn.setToolTip("Got a new PC? Restore your branch from the last cloud backup (FILO Max 4)")
        self.cloud_restore_btn.setStyleSheet("""
            QPushButton {
                background-color: #1E3A8A;
                color: #DBEAFE;
                font-size: 11px;
                font-weight: 700;
                border-radius: 14px;
                padding: 6px 12px;
                border: 1px solid #3B82F6;
            }
            QPushButton:hover {
                background-color: #1D4ED8;
                color: #FFFFFF;
            }
        """)
        self.cloud_restore_btn.clicked.connect(self._open_cloud_restore_dialog)
        help_row.addWidget(self.cloud_restore_btn)

        help_btn = QPushButton("💬  Help")
        help_btn.setCursor(Qt.PointingHandCursor)
        help_btn.setStyleSheet("""
            QPushButton {
                background-color: #D97706;
                color: #FFFFFF;
                font-size: 11px;
                font-weight: 700;
                border-radius: 14px;
                padding: 6px 12px;
                border: none;
            }
            QPushButton:hover {
                background-color: #B45309;
            }
        """)
        help_btn.clicked.connect(lambda: self.show_error("Contact your Pharmacy Administrator or IT Helpdesk for assistance."))
        help_row.addWidget(help_btn)
        form_layout.addLayout(help_row)

        right_layout.addWidget(form_card)
        root_layout.addWidget(right_panel, 5)

    def _open_cloud_restore_dialog(self):
        if not self.backup_service or not self.api_client:
            self.show_error("Cloud backup service is not configured.")
            return
        from desktop.app.ui.settings.cloud_restore_dialog import CloudBranchRestoreDialog

        org_code = getattr(self, "_resolved_org_code", "MEDCARE") or "MEDCARE"
        dlg = CloudBranchRestoreDialog(
            backup_service=self.backup_service,
            api_client=self.api_client,
            org_code=org_code,
            branch_code="",
            parent=self,
        )
        if dlg.exec() == QDialog.Accepted:
            self.load_remembered_credentials()
            self.load_branches()
            self.refresh_subscription_badge(sync_online=False)

    def refresh_subscription_badge(self, sync_online: bool = False):
        if not self.licensing_service:
            return
        try:
            org_code = getattr(self, "_resolved_org_code", "MEDCARE") or "MEDCARE"
            org_name = self.pharmacy_name_label.text() or "MedCare Pharmacy"
            if sync_online and self.api_client and self.api_client.is_server_available():
                self.licensing_service.sync_subscription_from_server(self.api_client, org_code=org_code)
            state = self.licensing_service.ensure_or_get_subscription_state(org_code=org_code, org_name=org_name)
            days = int(state.get("days_remaining", 0))
            eff = state.get("effective_status", "ACTIVE")
            if days <= 0 or eff in ("EXPIRED", "SUSPENDED", "CANCELLED"):
                self.sub_status_btn.setText("🔒  Sub: 0 Days Left (Renew via Monnify)")
                self.sub_status_btn.setStyleSheet(
                    "QPushButton { background-color: #991B1B; color: #FEE2E2; font-size: 11px; font-weight: 800; "
                    "border-radius: 14px; padding: 6px 14px; border: 1px solid #F87171; } "
                    "QPushButton:hover { background-color: #7F1D1D; }"
                )
            elif days <= 7:
                self.sub_status_btn.setText(f"⚠️  Sub: {days} Days Left (Renew)")
                self.sub_status_btn.setStyleSheet(
                    "QPushButton { background-color: #92400E; color: #FEF3C7; font-size: 11px; font-weight: 800; "
                    "border-radius: 14px; padding: 6px 14px; border: 1px solid #FBBF24; } "
                    "QPushButton:hover { background-color: #78350F; }"
                )
            else:
                self.sub_status_btn.setText(f"💳  Sub: {days} Days Left")
                self.sub_status_btn.setStyleSheet(
                    "QPushButton { background-color: #065F46; color: #ECFDF5; font-size: 11px; font-weight: 700; "
                    "border-radius: 14px; padding: 6px 14px; border: 1px solid #10B981; } "
                    "QPushButton:hover { background-color: #047857; }"
                )
        except Exception:
            pass

    def _open_subscription_dialog(self, locked_mode: bool = False) -> bool:
        if not self.licensing_service:
            return True
        from desktop.app.ui.licensing.subscription_dialog import SubscriptionBillingDialog

        org_code = getattr(self, "_resolved_org_code", "MEDCARE") or "MEDCARE"
        org_name = self.pharmacy_name_label.text() or "MedCare Pharmacy"
        dlg = SubscriptionBillingDialog(
            parent=self,
            licensing_service=self.licensing_service,
            api_client=self.api_client,
            org_code=org_code,
            org_name=org_name,
            locked_mode=locked_mode,
        )
        dlg.exec()
        self.refresh_subscription_badge(sync_online=False)
        return dlg.unlocked_successfully

    def _open_onboarding_wizard(self):
        dlg = PharmacyOnboardingDialog(self, self.organization_service)
        if dlg.exec() == QDialog.Accepted and dlg.setup_result:
            res = dlg.setup_result
            self.populate_branches()
            self._resolved_org_code = res["organization_code"]
            self.org_code_input.setText(f"🔒  {res['organization_name']}  ({res['organization_code']})")
            self._update_pharmacy_name(res["organization_name"])
            self.username_input.setText(res["admin_username"])
            idx = self.branch_select.findData(res["branch_id"])
            if idx >= 0:
                self.branch_select.setCurrentIndex(idx)
            self.password_input.setFocus()

    def toggle_password_visibility(self):
        """Toggles between masked password and visible plaintext with eye icon."""
        if self.password_input.echoMode() == QLineEdit.Password:
            self.password_input.setEchoMode(QLineEdit.Normal)
            self.toggle_pwd_action.setIcon(self.eye_open_icon)
            self.toggle_pwd_action.setToolTip("Click to hide password")
        else:
            self.password_input.setEchoMode(QLineEdit.Password)
            self.toggle_pwd_action.setIcon(self.eye_closed_icon)
            self.toggle_pwd_action.setToolTip("Click to show password")

    def _on_branch_changed(self, _index: int = -1):
        self.clear_error()
        self._save_selected_branch()

    def _save_selected_branch(self, branch_id: str | None = None):
        settings = QSettings("PharmaCare", "PharmaCareEnterprise")
        sel_id = branch_id if branch_id is not None else self.branch_select.currentData()
        sel_text = self.branch_select.currentText() or ""
        if sel_id:
            settings.setValue("saved_branch_id", str(sel_id))
            if "(" in sel_text and sel_text.endswith(")"):
                code = sel_text.split("(")[-1].rstrip(")").strip()
                if code:
                    settings.setValue("saved_branch_code", code)
        else:
            settings.setValue("saved_branch_id", "")
            settings.setValue("saved_branch_code", "")

    def populate_branches(self):
        self.branch_select.blockSignals(True)
        try:
            self.branch_select.clear()
            self.branch_select.addItem("Default / Auto-Select Branch", None)
            settings = QSettings("PharmaCare", "PharmaCareEnterprise")
            saved_branch_id = str(settings.value("saved_branch_id", "") or "").strip()
            saved_branch_code = str(settings.value("saved_branch_code", "") or "").strip()
            selected_idx = 0
            if self.organization_service:
                try:
                    branches = self.organization_service.list_branches()
                    for idx, b in enumerate(branches, start=1):
                        self.branch_select.addItem(f"{b.name} ({b.code})", b.id)
                        if saved_branch_id and str(b.id) == saved_branch_id:
                            selected_idx = idx
                        elif not saved_branch_id and saved_branch_code and b.code.upper() == saved_branch_code.upper():
                            selected_idx = idx
                        elif selected_idx == 0 and idx == 1:
                            selected_idx = 1
                except Exception:
                    pass
            if selected_idx > 0 and self.branch_select.count() > selected_idx:
                self.branch_select.setCurrentIndex(selected_idx)
        finally:
            self.branch_select.blockSignals(False)

    def load_remembered_credentials(self):
        """Loads configured pharmacy organization (locked read-only) and remembered username."""
        settings = QSettings("PharmaCare", "PharmaCareEnterprise")
        remember = settings.value("remember_username", True, type=bool)
        self.remember_check.setChecked(remember)

        org_name = settings.value("saved_pharmacy_name", "")
        org_code = settings.value("saved_org_code", "MEDCARE")

        if self.organization_service:
            try:
                org = self.organization_service.get_organization()
                if org:
                    org_name = org.name
                    org_code = org.code
            except Exception:
                pass

        self._resolved_org_code = (org_code or "MEDCARE").strip().upper()
        display_title = (org_name or self._resolved_org_code or "MEDCARE").strip().upper()
        self.pharmacy_name_label.setText(display_title)
        if org_name and org_name.strip().upper() != self._resolved_org_code:
            self.org_code_input.setText(f"🔒  {org_name.strip()}  ({self._resolved_org_code})")
        else:
            self.org_code_input.setText(f"🔒  {self._resolved_org_code}")
        self.org_code_input.setReadOnly(True)

        if remember:
            saved_user = settings.value("saved_username", "admin")
            if saved_user:
                self.username_input.setText(saved_user)
                self.password_input.clear()
                self.password_input.setFocus()

    def show_error(self, message: str):
        """Displays a clean, sanitized error message."""
        clean = re.sub(r"<[^>]+>", "", str(message)).strip()
        if "<!doctype" in clean.lower() or "page not found" in clean.lower():
            clean = "Cannot reach authentication service. Please ensure the Pharmacy Server is running on port 8001."
        elif "connection refused" in clean.lower() or "cannot connect" in clean.lower():
            clean = "Cannot connect to the Pharmacy Server. Please ensure the backend server is running."
        self.error_label.setText(clean)
        self.error_label.setVisible(True)

    def _update_pharmacy_name(self, text: str):
        """Dynamically updates the right-panel pharmacy name header."""
        name = text.strip().upper()
        self.pharmacy_name_label.setText(name if name else "PHARMACY")

    def clear_error(self):
        """Clears the error banner when the user starts typing."""
        if self.error_label.isVisible():
            self.error_label.setText("")
            self.error_label.setVisible(False)

    def attempt_login(self):
        self.clear_error()

        raw_org = getattr(self, "_resolved_org_code", "") or self.org_code_input.text()
        org_code = raw_org.replace("🔒", "").strip().upper()
        if "(" in org_code and org_code.endswith(")"):
            org_code = org_code.split("(")[-1].rstrip(")").strip()

        user = self.username_input.text().strip()
        pwd = self.password_input.text()
        branch = self.branch_select.currentData()

        # Client-side validation
        if not org_code:
            org_code = "MEDCARE"

        if not user:
            self.show_error("Please enter your Username.")
            self.username_input.setFocus()
            return

        if not pwd:
            self.show_error("Please enter your Password.")
            self.password_input.setFocus()
            return

        self.login_btn.setEnabled(False)
        self.login_btn.setText("Signing In...")
        QApplication.processEvents()

        try:
            # 0. Sync subscription status from server when online, then enforce 0-days hard lock
            if self.licensing_service:
                if self.api_client and self.api_client.is_server_available():
                    self.licensing_service.sync_subscription_from_server(
                        self.api_client, org_code=org_code
                    )
                self.refresh_subscription_badge(sync_online=False)
                is_locked, _ = self.licensing_service.is_subscription_locked(org_code=org_code)
                if is_locked:
                    unlocked = self._open_subscription_dialog(locked_mode=True)
                    if not unlocked:
                        self.show_error(
                            "🔒 Pharmacy subscription expired (0 days remaining). "
                            "Please complete your Monnify subscription payment to sign in."
                        )
                        return

            session = self.auth_manager.login(
                username=user,
                password=pwd,
                branch_id=branch,
                device_id=None,
                org_code=org_code,
            )
            # Persist last selected branch, username, and org code (never store passwords)
            self._save_selected_branch(session.branch_id or branch)
            settings = QSettings("PharmaCare", "PharmaCareEnterprise")
            if self.remember_check.isChecked():
                settings.setValue("remember_username", True)
                settings.setValue("saved_username", user)
                settings.setValue("saved_org_code", org_code)
            else:
                settings.setValue("remember_username", False)
                settings.remove("saved_username")

            # Always ensure the password field is blanked out
            self.password_input.clear()
            self.login_successful.emit(session)
        except Exception as e:
            self.show_error(str(e))
        finally:
            self.login_btn.setEnabled(True)
            self.login_btn.setText("➔  SIGN IN")
