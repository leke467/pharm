from decimal import Decimal
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QFrame,
    QWidget,
    QMessageBox,
    QApplication,
)
from desktop.app.ui.common.title_bar import DialogHeaderBanner
from desktop.app.utils.date_utils import format_display


class SubscriptionBillingDialog(QDialog):
    """
    Monnify Subscription & Billing Modal.
    - Displays live remaining subscription days (synced from Django server & counted down locally).
    - Shows the pharmacy's dedicated Monnify Reserved Virtual Account for instant bank transfer.
    - Provides 1-click 'Pay Monthly (+30 Days)' and 'Pay Yearly (+365 Days)' online Monnify checkout buttons
      using the custom prices set for this pharmacy in Django Admin.
    - Includes 'Verify Payment / Sync Status' to immediately refresh days left and unlock the app.
    """

    def __init__(
        self,
        parent,
        licensing_service,
        api_client=None,
        organization_id: str | None = None,
        org_code: str = "MEDCARE",
        org_name: str = "MedCare Pharmacy",
        locked_mode: bool = False,
    ):
        super().__init__(parent)
        self.licensing_service = licensing_service
        self.api_client = api_client
        self.organization_id = organization_id
        self.org_code = (org_code or "MEDCARE").strip().upper()
        self.org_name = (org_name or "MedCare Pharmacy").strip()
        self.locked_mode = locked_mode
        self.last_payment_reference = ""
        self.unlocked_successfully = False

        self.setWindowTitle("Pharmacy Subscription & Monnify Billing")
        self.setMinimumSize(680, 590)
        self.resize(720, 620)
        self.init_ui()
        self.refresh_state(sync_online=True)

    def init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header_title = (
            "🔒 Subscription Expired — Renew via Monnify"
            if self.locked_mode
            else "💳 Pharmacy Subscription & Monnify Billing"
        )
        header_sub = (
            f"{self.org_name} ({self.org_code})  •  Managed via Django Platform & Monnify"
        )
        banner = DialogHeaderBanner(header_title, header_sub, parent_dialog=self)
        root.addWidget(banner)

        body = QWidget()
        body.setStyleSheet("background-color: #F8FAFC; color: #0F172A;")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(24, 18, 24, 18)
        body_layout.setSpacing(14)

        # 1. Hard-Lock Alert Banner (shown when 0 days left)
        self.lock_alert_frame = QFrame()
        self.lock_alert_frame.setStyleSheet(
            "QFrame { background-color: #FEF2F2; border: 1px solid #FECACA; border-radius: 10px; }"
        )
        lock_layout = QHBoxLayout(self.lock_alert_frame)
        lock_layout.setContentsMargins(14, 10, 14, 10)
        self.lock_alert_label = QLabel(
            "🚨  <b>0 Days Remaining — System Locked:</b> Your pharmacy subscription has expired. "
            "Please pay your Monthly or Yearly subscription below via Monnify, then click "
            "<b>'🔄 Verify Payment & Refresh Days'</b> to unlock immediately."
        )
        self.lock_alert_label.setWordWrap(True)
        self.lock_alert_label.setStyleSheet("color: #991B1B; font-size: 12.5px; border: none; background: transparent;")
        lock_layout.addWidget(self.lock_alert_label)
        self.lock_alert_frame.setVisible(self.locked_mode)
        body_layout.addWidget(self.lock_alert_frame)

        # 2. Top Status & Countdown Card
        status_card = QFrame()
        status_card.setStyleSheet(
            "QFrame { background-color: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 12px; }"
        )
        sc_layout = QHBoxLayout(status_card)
        sc_layout.setContentsMargins(20, 16, 20, 16)
        sc_layout.setSpacing(18)

        # Left: Big Countdown Badge
        countdown_box = QFrame()
        countdown_box.setFixedWidth(185)
        self.countdown_box = countdown_box
        cb_layout = QVBoxLayout(countdown_box)
        cb_layout.setContentsMargins(14, 12, 14, 12)
        cb_layout.setSpacing(2)
        cb_layout.setAlignment(Qt.AlignCenter)

        self.days_number_lbl = QLabel("30")
        self.days_number_lbl.setAlignment(Qt.AlignCenter)
        self.days_number_lbl.setStyleSheet("font-size: 32px; font-weight: 900; border: none; background: transparent;")

        self.days_caption_lbl = QLabel("DAYS REMAINING")
        self.days_caption_lbl.setAlignment(Qt.AlignCenter)
        self.days_caption_lbl.setStyleSheet("font-size: 10px; font-weight: 800; letter-spacing: 0.8px; border: none; background: transparent;")

        cb_layout.addWidget(self.days_number_lbl)
        cb_layout.addWidget(self.days_caption_lbl)
        sc_layout.addWidget(countdown_box)

        # Right: Subscription Metadata
        meta_col = QVBoxLayout()
        meta_col.setSpacing(5)

        self.pharm_title_lbl = QLabel(f"{self.org_name} ({self.org_code})")
        self.pharm_title_lbl.setStyleSheet("font-size: 16px; font-weight: 800; color: #0F172A; border: none;")
        meta_col.addWidget(self.pharm_title_lbl)

        self.status_line_lbl = QLabel("Status: ACTIVE  |  Plan: Standard")
        self.status_line_lbl.setStyleSheet("font-size: 12.5px; font-weight: 700; color: #334155; border: none;")
        meta_col.addWidget(self.status_line_lbl)

        self.expiry_line_lbl = QLabel("Current Period Ends: —")
        self.expiry_line_lbl.setStyleSheet("font-size: 12px; color: #475569; border: none;")
        meta_col.addWidget(self.expiry_line_lbl)

        self.pricing_line_lbl = QLabel("Monthly Rate: ₦25,000.00  •  Yearly Rate: ₦250,000.00")
        self.pricing_line_lbl.setStyleSheet("font-size: 12.5px; font-weight: 700; color: #059669; border: none;")
        meta_col.addWidget(self.pricing_line_lbl)

        self.last_sync_lbl = QLabel("Last confirmed with server: —")
        self.last_sync_lbl.setStyleSheet("font-size: 11px; color: #64748B; border: none;")
        meta_col.addWidget(self.last_sync_lbl)

        sc_layout.addLayout(meta_col, stretch=1)
        body_layout.addWidget(status_card)

        # 3. Dedicated Monnify Reserved Virtual Account Card (Bank Transfer)
        va_card = QFrame()
        va_card.setStyleSheet(
            "QFrame { background-color: #EFF6FF; border: 1px solid #BFDBFE; border-radius: 12px; }"
        )
        va_layout = QVBoxLayout(va_card)
        va_layout.setContentsMargins(18, 14, 18, 14)
        va_layout.setSpacing(8)

        va_header_row = QHBoxLayout()
        va_title = QLabel("🏦  Option 1: Dedicated Monnify Virtual Account (Instant Bank Transfer)")
        va_title.setStyleSheet("font-size: 13px; font-weight: 800; color: #1E3A8A; border: none; background: transparent;")
        va_header_row.addWidget(va_title)
        va_header_row.addStretch()

        self.copy_acc_btn = QPushButton("📋 Copy Account No.")
        self.copy_acc_btn.setCursor(Qt.PointingHandCursor)
        self.copy_acc_btn.setStyleSheet(
            "QPushButton { background-color: #DBEAFE; color: #1D4ED8; border: 1px solid #93C5FD; "
            "border-radius: 6px; padding: 4px 10px; font-size: 11.5px; font-weight: 700; } "
            "QPushButton:hover { background-color: #BFDBFE; }"
        )
        self.copy_acc_btn.clicked.connect(self._copy_account_number)
        va_header_row.addWidget(self.copy_acc_btn)
        va_layout.addLayout(va_header_row)

        va_details_row = QHBoxLayout()
        va_details_row.setSpacing(20)

        self.va_bank_lbl = QLabel("Bank: Moniepoint MFB")
        self.va_bank_lbl.setStyleSheet("font-size: 12.5px; font-weight: 600; color: #1E293B; border: none; background: transparent;")
        va_details_row.addWidget(self.va_bank_lbl)

        self.va_number_lbl = QLabel("Account No: —")
        self.va_number_lbl.setStyleSheet("font-size: 15px; font-weight: 900; color: #1D4ED8; border: none; background: transparent;")
        va_details_row.addWidget(self.va_number_lbl)

        self.va_name_lbl = QLabel("Account Name: —")
        self.va_name_lbl.setStyleSheet("font-size: 12.5px; font-weight: 600; color: #1E293B; border: none; background: transparent;")
        va_details_row.addWidget(self.va_name_lbl, stretch=1)

        va_layout.addLayout(va_details_row)

        va_hint = QLabel(
            "Transfer either the Monthly fee (+30 days) or Yearly fee (+365 days) to this pharmacy's dedicated Monnify account "
            "from any bank app, then click '🔄 Verify Payment & Refresh Days' below."
        )
        va_hint.setWordWrap(True)
        va_hint.setStyleSheet("font-size: 11.5px; color: #475569; border: none; background: transparent;")
        va_layout.addWidget(va_hint)
        body_layout.addWidget(va_card)

        # 4. Online Monnify Checkout Card (Monthly vs Yearly)
        checkout_card = QFrame()
        checkout_card.setStyleSheet(
            "QFrame { background-color: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 12px; }"
        )
        ck_layout = QVBoxLayout(checkout_card)
        ck_layout.setContentsMargins(18, 14, 18, 14)
        ck_layout.setSpacing(10)

        ck_title = QLabel("💳  Option 2: Pay Online via Monnify Checkout (Card / Transfer / USSD)")
        ck_title.setStyleSheet("font-size: 13px; font-weight: 800; color: #0F172A; border: none;")
        ck_layout.addWidget(ck_title)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(14)

        self.pay_monthly_btn = QPushButton("💳  Pay Monthly — ₦25,000.00 (+30 Days)")
        self.pay_monthly_btn.setCursor(Qt.PointingHandCursor)
        self.pay_monthly_btn.setStyleSheet(
            "QPushButton { background-color: #059669; color: #FFFFFF; font-size: 13px; font-weight: 800; "
            "padding: 12px 16px; border-radius: 8px; border: none; } "
            "QPushButton:hover { background-color: #047857; }"
        )
        self.pay_monthly_btn.clicked.connect(lambda: self._start_monnify_checkout("MONTHLY"))
        btn_row.addWidget(self.pay_monthly_btn, stretch=1)

        self.pay_yearly_btn = QPushButton("🌟  Pay Yearly — ₦250,000.00 (+365 Days)")
        self.pay_yearly_btn.setCursor(Qt.PointingHandCursor)
        self.pay_yearly_btn.setStyleSheet(
            "QPushButton { background-color: #1D4ED8; color: #FFFFFF; font-size: 13px; font-weight: 800; "
            "padding: 12px 16px; border-radius: 8px; border: none; } "
            "QPushButton:hover { background-color: #1E40AF; }"
        )
        self.pay_yearly_btn.clicked.connect(lambda: self._start_monnify_checkout("YEARLY"))
        btn_row.addWidget(self.pay_yearly_btn, stretch=1)

        ck_layout.addLayout(btn_row)

        self.checkout_feedback_lbl = QLabel("")
        self.checkout_feedback_lbl.setWordWrap(True)
        self.checkout_feedback_lbl.setStyleSheet("font-size: 12px; font-weight: 600; color: #0F766E; border: none;")
        self.checkout_feedback_lbl.setVisible(False)
        ck_layout.addWidget(self.checkout_feedback_lbl)

        body_layout.addWidget(checkout_card)
        body_layout.addStretch()

        # 5. Footer Bar
        footer_row = QHBoxLayout()
        footer_row.setSpacing(12)

        self.verify_btn = QPushButton("🔄  Verify Payment & Refresh Days")
        self.verify_btn.setCursor(Qt.PointingHandCursor)
        self.verify_btn.setStyleSheet(
            "QPushButton { background-color: #0F172A; color: #FFFFFF; font-size: 13px; font-weight: 800; "
            "padding: 10px 20px; border-radius: 8px; border: none; } "
            "QPushButton:hover { background-color: #1E293B; }"
        )
        self.verify_btn.clicked.connect(self._on_verify_clicked)
        footer_row.addWidget(self.verify_btn)

        footer_row.addStretch()

        close_text = "Exit / Back to Sign In" if self.locked_mode else "Close"
        self.close_btn = QPushButton(close_text)
        self.close_btn.setCursor(Qt.PointingHandCursor)
        self.close_btn.setStyleSheet(
            "QPushButton { background-color: #E2E8F0; color: #1E293B; font-size: 13px; font-weight: 700; "
            "padding: 10px 20px; border-radius: 8px; border: none; } "
            "QPushButton:hover { background-color: #CBD5E1; }"
        )
        self.close_btn.clicked.connect(self.reject)
        footer_row.addWidget(self.close_btn)

        body_layout.addLayout(footer_row)
        root.addWidget(body, stretch=1)

    def refresh_state(self, sync_online: bool = False):
        if sync_online and self.api_client:
            self.licensing_service.sync_subscription_from_server(
                self.api_client,
                organization_id=self.organization_id,
                org_code=self.org_code,
            )

        state = self.licensing_service.ensure_or_get_subscription_state(
            organization_id=self.organization_id,
            org_code=self.org_code,
            org_name=self.org_name,
        )
        self._apply_state_to_ui(state)

    def _apply_state_to_ui(self, state: dict):
        if not state:
            return
        days = int(state.get("days_remaining", 0))
        eff_status = state.get("effective_status", "ACTIVE")
        plan = (state.get("plan") or "standard").title()
        monthly = Decimal(str(state.get("monthly_price") or "25000.00"))
        yearly = Decimal(str(state.get("yearly_price") or "250000.00"))

        self.days_number_lbl.setText(str(days))
        if days <= 0 or eff_status in ("EXPIRED", "SUSPENDED", "CANCELLED"):
            self.countdown_box.setStyleSheet(
                "QFrame { background-color: #FEF2F2; border: 2px solid #EF4444; border-radius: 10px; }"
            )
            self.days_number_lbl.setStyleSheet("font-size: 32px; font-weight: 900; color: #DC2626; border: none; background: transparent;")
            self.days_caption_lbl.setText("DAYS LEFT (LOCKED)")
            self.days_caption_lbl.setStyleSheet("font-size: 10px; font-weight: 800; color: #991B1B; border: none; background: transparent;")
        elif days <= 7:
            self.countdown_box.setStyleSheet(
                "QFrame { background-color: #FFFBEB; border: 2px solid #F59E0B; border-radius: 10px; }"
            )
            self.days_number_lbl.setStyleSheet("font-size: 32px; font-weight: 900; color: #D97706; border: none; background: transparent;")
            self.days_caption_lbl.setText("DAYS REMAINING")
            self.days_caption_lbl.setStyleSheet("font-size: 10px; font-weight: 800; color: #92400E; border: none; background: transparent;")
        else:
            self.countdown_box.setStyleSheet(
                "QFrame { background-color: #ECFDF5; border: 2px solid #10B981; border-radius: 10px; }"
            )
            self.days_number_lbl.setStyleSheet("font-size: 32px; font-weight: 900; color: #059669; border: none; background: transparent;")
            self.days_caption_lbl.setText("DAYS REMAINING")
            self.days_caption_lbl.setStyleSheet("font-size: 10px; font-weight: 800; color: #065F46; border: none; background: transparent;")

        org_name = state.get("organization_name") or self.org_name
        org_code = state.get("organization_code") or self.org_code
        self.pharm_title_lbl.setText(f"{org_name} ({org_code})")
        self.status_line_lbl.setText(f"Subscription Status: {eff_status}   •   Plan: {plan}")

        exp_raw = state.get("current_period_end")
        exp_fmt = format_display(exp_raw) if exp_raw else "—"
        self.expiry_line_lbl.setText(f"Current Period Ends: {exp_fmt}")
        self.pricing_line_lbl.setText(f"Monthly Fee: ₦{monthly:,.2f} (30 Days)   •   Yearly Fee: ₦{yearly:,.2f} (365 Days)")

        last_chk = state.get("last_checked_at")
        self.last_sync_lbl.setText(
            f"Last synced with server: {format_display(last_chk) if last_chk else 'Local Cache'}"
        )

        self._current_acc_no = state.get("monnify_account_number") or "—"
        self.va_bank_lbl.setText(f"Bank: {state.get('monnify_bank_name') or 'Moniepoint MFB'}")
        self.va_number_lbl.setText(f"Account No: {self._current_acc_no}")
        self.va_name_lbl.setText(f"Account Name: {state.get('monnify_account_name') or f'PharmaCare - {org_name}'}")

        self.pay_monthly_btn.setText(f"💳  Pay Monthly — ₦{monthly:,.2f} (+30 Days)")
        self.pay_yearly_btn.setText(f"🌟  Pay Yearly — ₦{yearly:,.2f} (+365 Days)")

        if self.locked_mode and days > 0 and eff_status in ("ACTIVE", "TRIAL"):
            self.unlocked_successfully = True
            self.lock_alert_frame.setVisible(False)

    def _copy_account_number(self):
        acc = getattr(self, "_current_acc_no", "")
        if acc and acc != "—":
            clipboard = QGuiApplication.clipboard()
            if clipboard:
                clipboard.setText(acc)
            self.copy_acc_btn.setText("✅ Copied!")

    def _start_monnify_checkout(self, cycle: str):
        if not self.api_client:
            QMessageBox.warning(
                self,
                "Offline",
                "Please connect to the internet / Pharmacy Server to initiate an online Monnify payment.",
            )
            return

        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            resp = self.licensing_service.initiate_monnify_payment(
                self.api_client,
                organization_id=self.organization_id,
                org_code=self.org_code,
                billing_cycle=cycle,
            )
            checkout_url = resp.get("checkout_url")
            pay_ref = resp.get("payment_reference", "")
            self.last_payment_reference = pay_ref
            if checkout_url:
                QDesktopServices.openUrl(QUrl(checkout_url))
                self.checkout_feedback_lbl.setText(
                    f"✅ Monnify checkout opened in your browser (Ref: {pay_ref}). "
                    f"After completing payment, click '🔄 Verify Payment & Refresh Days' below."
                )
                self.checkout_feedback_lbl.setVisible(True)
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Monnify Checkout Error",
                f"Could not initialize Monnify checkout:\n{exc}\n\n"
                "Please ensure the Django server is reachable, or transfer directly to the Monnify Reserved Account above.",
            )
        finally:
            QApplication.restoreOverrideCursor()

    def _on_verify_clicked(self):
        if not self.api_client:
            QMessageBox.warning(self, "Offline", "Internet connection required to verify payment with server.")
            return

        self.verify_btn.setEnabled(False)
        self.verify_btn.setText("⏳ Verifying with Monnify & Server...")
        QApplication.processEvents()
        try:
            resp = self.licensing_service.verify_monnify_payment(
                self.api_client,
                organization_id=self.organization_id,
                org_code=self.org_code,
                payment_reference=self.last_payment_reference,
            )
            state = self.licensing_service.sync_subscription_from_server(
                self.api_client,
                organization_id=self.organization_id,
                org_code=self.org_code,
            )
            if state:
                self._apply_state_to_ui(state)
                days = int(state.get("days_remaining", 0))
                eff = state.get("effective_status", "ACTIVE")
                if days > 0 and eff in ("ACTIVE", "TRIAL"):
                    self.unlocked_successfully = True
                    QMessageBox.information(
                        self,
                        "Subscription Active",
                        f"Subscription verified! Your pharmacy has {days} active day(s) remaining.",
                    )
                    if self.locked_mode:
                        self.accept()
                else:
                    msg = resp.get("message") if isinstance(resp, dict) else "No active days remaining yet."
                    QMessageBox.warning(
                        self,
                        "Subscription Still Expired",
                        f"{msg}\n\nDays Remaining: {days}. Please complete payment via Monnify to unlock.",
                    )
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Verification Failed",
                f"Could not verify subscription status with the server:\n{exc}",
            )
        finally:
            self.verify_btn.setEnabled(True)
            self.verify_btn.setText("🔄  Verify Payment & Refresh Days")
