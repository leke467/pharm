from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from desktop.app.ui.common.title_bar import DialogHeaderBanner


class CloudBranchRestoreDialog(QDialog):
    """
    Modal dialog allowing a pharmacy to restore a branch's database from the Django Cloud Server
    (e.g., when a laptop spoils and they install the desktop app on a new PC).
    Displays up to 4 cloud backups per branch in FILO/LIFO order (newest first).
    """

    def __init__(
        self,
        backup_service,
        api_client,
        org_code: str = "MEDCARE",
        branch_code: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self.backup_service = backup_service
        self.api_client = api_client
        self.org_code = (org_code or "MEDCARE").strip().upper()
        self.branch_code = (branch_code or "").strip().upper()
        self.restored_meta: dict | None = None
        self._backups: list[dict] = []

        self.setWindowTitle("Cloud Branch Backup & New PC Recovery (FILO — Max 4 / Branch)")
        self.setMinimumSize(780, 520)
        self.init_ui()
        self.refresh_cloud_backups()

    def init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(
            DialogHeaderBanner(
                "Cloud Branch Recovery (New PC Restore)",
                "Restore your branch from the last cloud backup (up to 4 backups saved per branch in FILO order)",
                icon_text="☁️",
                parent_dialog=self,
            )
        )

        body = QWidget()
        body.setStyleSheet("background-color: #F8FAFC;")
        layout = QVBoxLayout(body)
        layout.setContentsMargins(24, 18, 24, 22)
        layout.setSpacing(14)

        # Info banner
        info_card = QFrame()
        info_card.setStyleSheet(
            "background-color: #EFF6FF; border: 1px solid #BFDBFE; border-radius: 8px; padding: 10px 14px;"
        )
        info_layout = QVBoxLayout(info_card)
        info_layout.setContentsMargins(6, 4, 6, 4)
        info_lbl = QLabel(
            "🛡️  <b>Automatic Laptop Protection:</b> Every time a branch syncs, its database is backed up to the server. "
            "Up to <b>4 backups per branch</b> are kept in <b>FILO (First-In, Last-Out)</b> order — select <b>#1 Latest</b> "
            "below to restore a spoiled laptop onto a new PC and continue immediately."
        )
        info_lbl.setWordWrap(True)
        info_lbl.setStyleSheet("color: #1E3A8A; font-size: 12px; background: transparent; border: none;")
        info_layout.addWidget(info_lbl)
        layout.addWidget(info_card)

        # Filter bar: Pharmacy Code + Branch selector + Refresh button
        filter_row = QHBoxLayout()
        filter_row.setSpacing(10)

        org_lbl = QLabel("Pharmacy Code:")
        org_lbl.setStyleSheet("font-weight: 700; color: #334155; font-size: 12.5px;")
        filter_row.addWidget(org_lbl)

        self.org_input = QLineEdit(self.org_code)
        self.org_input.setPlaceholderText("e.g. MEDCARE")
        self.org_input.setFixedWidth(140)
        self.org_input.setStyleSheet(
            "background: white; border: 1px solid #CBD5E1; border-radius: 6px; padding: 6px 10px; font-weight: 700;"
        )
        filter_row.addWidget(self.org_input)

        br_lbl = QLabel("Branch:")
        br_lbl.setStyleSheet("font-weight: 700; color: #334155; font-size: 12.5px;")
        filter_row.addWidget(br_lbl)

        self.branch_combo = QComboBox()
        self.branch_combo.setMinimumWidth(210)
        self.branch_combo.addItem("All Branches (Up to 4 each)", "")
        if self.branch_code:
            self.branch_combo.addItem(f"Branch ({self.branch_code})", self.branch_code)
            self.branch_combo.setCurrentIndex(1)
        self.branch_combo.currentIndexChanged.connect(self._on_branch_filter_changed)
        filter_row.addWidget(self.branch_combo)

        filter_row.addStretch()

        self.refresh_btn = QPushButton("🔄  Fetch Cloud Backups")
        self.refresh_btn.setCursor(Qt.PointingHandCursor)
        self.refresh_btn.setStyleSheet(
            "background-color: #2563EB; color: white; font-weight: 700; padding: 7px 14px; border-radius: 6px;"
        )
        self.refresh_btn.clicked.connect(self.refresh_cloud_backups)
        filter_row.addWidget(self.refresh_btn)

        layout.addLayout(filter_row)

        # Status label
        self.status_lbl = QLabel("")
        self.status_lbl.setStyleSheet("font-size: 12px; font-weight: 600; color: #475569;")
        layout.addWidget(self.status_lbl)

        # Backups Table
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels([
            "FILO Slot",
            "Branch",
            "Device",
            "Size",
            "Synced At (UTC)",
            "Note",
        ])
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(5, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(38)
        self.table.setStyleSheet(
            "QTableWidget { background: white; border: 1px solid #E2E8F0; border-radius: 8px; }"
        )
        layout.addWidget(self.table, stretch=1)

        # Bottom Action Row
        btn_row = QHBoxLayout()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setCursor(Qt.PointingHandCursor)
        cancel_btn.setStyleSheet(
            "background: #E2E8F0; color: #334155; font-weight: 700; padding: 9px 18px; border-radius: 6px;"
        )
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        btn_row.addStretch()

        self.restore_btn = QPushButton("📥  Restore Selected Branch Backup & Continue")
        self.restore_btn.setCursor(Qt.PointingHandCursor)
        self.restore_btn.setStyleSheet(
            "background-color: #059669; color: white; font-size: 13px; font-weight: 800; "
            "padding: 10px 22px; border-radius: 8px;"
        )
        self.restore_btn.clicked.connect(self._on_restore_selected)
        btn_row.addWidget(self.restore_btn)

        layout.addLayout(btn_row)
        root.addWidget(body, stretch=1)

    def _on_branch_filter_changed(self):
        self._populate_table()

    def refresh_cloud_backups(self):
        if not self.backup_service or not self.api_client:
            self.status_lbl.setText("⚠️ Cloud backup service is not available.")
            return

        org_code = self.org_input.text().strip().upper() or self.org_code
        try:
            data = self.backup_service.list_cloud_branch_backups(
                self.api_client,
                org_code=org_code,
                branch_code="",
            )
            self._backups = data.get("backups", [])
            branches = data.get("branches", [])

            current_br = self.branch_combo.currentData() or self.branch_code
            self.branch_combo.blockSignals(True)
            self.branch_combo.clear()
            self.branch_combo.addItem("All Branches (Up to 4 each)", "")
            sel_idx = 0
            for idx, b in enumerate(branches, start=1):
                bcode = b.get("branch_code", "")
                bname = b.get("branch_name", bcode)
                cnt = b.get("backup_count", 0)
                self.branch_combo.addItem(f"{bname} ({bcode}) — {cnt}/4 backups", bcode)
                if current_br and bcode.upper() == current_br.upper():
                    sel_idx = idx
            self.branch_combo.setCurrentIndex(sel_idx)
            self.branch_combo.blockSignals(False)

            self._populate_table()
        except Exception as exc:
            self.status_lbl.setStyleSheet("font-size: 12px; font-weight: 700; color: #DC2626;")
            self.status_lbl.setText(f"⚠️ Could not reach cloud server: {exc}")

    def _populate_table(self):
        selected_branch = (self.branch_combo.currentData() or "").strip().upper()
        filtered = [
            b for b in self._backups
            if not selected_branch or (b.get("branch_code", "").upper() == selected_branch)
        ]

        self.table.setRowCount(len(filtered))
        per_branch_slot: dict[str, int] = {}

        for row_idx, bck in enumerate(filtered):
            bcode = (bck.get("branch_code") or "HQ").upper()
            slot_num = per_branch_slot.get(bcode, 0) + 1
            per_branch_slot[bcode] = slot_num

            slot_label = f"#{slot_num} Latest (Last-In)" if slot_num == 1 else f"#{slot_num} Previous"
            slot_item = QTableWidgetItem(slot_label)
            slot_item.setData(Qt.UserRole, bck)

            br_item = QTableWidgetItem(f"{bck.get('branch_name', 'Branch')} ({bcode})")
            dev_item = QTableWidgetItem(bck.get("device_code") or "POS01")
            kb = (int(bck.get("size_bytes") or 0)) / 1024.0
            size_item = QTableWidgetItem(f"{kb:,.1f} KB")
            ts_str = (bck.get("created_at") or "")[:19].replace("T", " ")
            ts_item = QTableWidgetItem(ts_str)
            note_item = QTableWidgetItem(bck.get("note") or "Auto-Sync Cloud Backup")

            self.table.setItem(row_idx, 0, slot_item)
            self.table.setItem(row_idx, 1, br_item)
            self.table.setItem(row_idx, 2, dev_item)
            self.table.setItem(row_idx, 3, size_item)
            self.table.setItem(row_idx, 4, ts_item)
            self.table.setItem(row_idx, 5, note_item)

        if filtered:
            self.table.selectRow(0)
            self.restore_btn.setEnabled(True)
            self.status_lbl.setStyleSheet("font-size: 12px; font-weight: 700; color: #059669;")
            self.status_lbl.setText(
                f"✓ Showing {len(filtered)} cloud backup(s) (FILO order: #1 is the latest backup)."
            )
        else:
            self.restore_btn.setEnabled(False)
            self.status_lbl.setStyleSheet("font-size: 12px; font-weight: 600; color: #64748B;")
            self.status_lbl.setText("No cloud backups found for this pharmacy/branch yet.")

    def _on_restore_selected(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "Select a Backup", "Please select a cloud backup row to restore.")
            return

        item = self.table.item(row, 0)
        bck = item.data(Qt.UserRole) if item else None
        if not bck:
            return

        bname = bck.get("branch_name", "Branch")
        bcode = bck.get("branch_code", "HQ")
        ts_str = (bck.get("created_at") or "")[:19].replace("T", " ")

        confirm = QMessageBox.question(
            self,
            "Confirm Cloud Branch Restore",
            f"Are you sure you want to restore branch '{bname} ({bcode})' from the cloud backup created at {ts_str}?\n\n"
            "• A safety snapshot of the current local database will be saved first.\n"
            "• All products, stock batches, sales, users, and branch settings from this backup will be restored.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return

        try:
            self.restore_btn.setEnabled(False)
            self.restore_btn.setText("Restoring from Cloud...")
            self.restored_meta = self.backup_service.restore_branch_from_cloud(
                self.api_client,
                backup_id=str(bck["id"]),
            )
            QMessageBox.information(
                self,
                "Branch Restored Successfully",
                f"✅ Branch '{bname} ({bcode})' has been restored from the cloud backup!\n\n"
                "You can now sign in and continue operations right where this backup left off.",
            )
            self.accept()
        except Exception as exc:
            self.restore_btn.setEnabled(True)
            self.restore_btn.setText("📥  Restore Selected Branch Backup & Continue")
            QMessageBox.critical(self, "Cloud Restore Failed", f"Could not restore backup:\n{exc}")
