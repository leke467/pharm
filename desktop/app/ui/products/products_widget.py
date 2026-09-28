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
    QComboBox,
    QCheckBox,
    QTabWidget,
    QGridLayout,
    QDialog,
    QMessageBox,
    QFormLayout,
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from desktop.app.ui.common.title_bar import DialogHeaderBanner
from shared.enums import PermissionCode


def create_price_cell_widget(parent, product_name: str, price_text: str, update_info: dict, on_select_row=None) -> QWidget:
    """
    Creates a right-aligned table cell widget displaying the new selling price alongside
    an interactive 'ⓘ' info badge showing the previous price, branch, and account (for 24 hours after price update).
    """
    old_p = update_info.get("old_price")
    new_p = update_info.get("new_price")
    branch_name = update_info.get("branch_name") or "Main Branch (HQ)"
    account_name = update_info.get("account_name") or "Administrator"
    reason = update_info.get("change_reason") or "Price update"
    ts = str(update_info.get("received_at") or "")[:19].replace("T", " ")

    old_str = f"₦{old_p:,.2f}" if old_p is not None else "No previous price (Initial)"
    new_str = f"₦{new_p:,.2f}" if new_p is not None else price_text
    tooltip_text = (
        f"🟢 Price Updated (Within Last 24h)\n"
        f"• Previous Price: {old_str}\n"
        f"• New Selling Price: {new_str}\n"
        f"• Updated By Branch: {branch_name}\n"
        f"• Updated By Account: {account_name}\n"
        f"• Source / Reason: {reason}\n"
        f"• Updated At: {ts}"
    )

    container = QWidget(parent)
    container.setStyleSheet("background-color: #DCFCE7;")
    container.setToolTip(tooltip_text)

    h_layout = QHBoxLayout(container)
    h_layout.setContentsMargins(8, 2, 8, 2)
    h_layout.setSpacing(6)
    h_layout.addStretch()

    price_lbl = QLabel(price_text)
    price_lbl.setStyleSheet(
        "color: #065F46; font-weight: 800; font-size: 13px; background: transparent; border: none;"
    )
    price_lbl.setToolTip(tooltip_text)
    h_layout.addWidget(price_lbl)

    info_btn = QPushButton("ⓘ")
    info_btn.setCursor(Qt.PointingHandCursor)
    info_btn.setFixedSize(22, 22)
    info_btn.setToolTip(tooltip_text)
    info_btn.setStyleSheet(
        "QPushButton {"
        "  background-color: #10B981;"
        "  color: #FFFFFF;"
        "  font-size: 12px;"
        "  font-weight: 900;"
        "  border-radius: 11px;"
        "  padding: 0px;"
        "  min-height: 22px;"
        "  max-height: 22px;"
        "  border: 1.5px solid #047857;"
        "}"
        "QPushButton:hover {"
        "  background-color: #059669;"
        "}"
    )

    def _show_info_popup():
        if callable(on_select_row):
            on_select_row()
        QMessageBox.information(
            parent,
            "Recent Price Change Details (24h Highlight)",
            f"<b>Product:</b> {product_name}<br><br>"
            f"<b>Previous Selling Price:</b> <span style='color:#DC2626;'>{old_str}</span><br>"
            f"<b>New Selling Price:</b> <span style='color:#059669; font-weight:bold;'>{new_str}</span><br><br>"
            f"<b>Updated By Branch:</b> <span style='color:#1E40AF; font-weight:bold;'>{branch_name}</span><br>"
            f"<b>Updated By Account:</b> <span style='color:#0F172A; font-weight:bold;'>{account_name}</span><br>"
            f"<b>Source / Reason:</b> {reason}<br>"
            f"<b>Updated At:</b> {ts}",
        )

    info_btn.clicked.connect(_show_info_popup)
    h_layout.addWidget(info_btn)
    return container


class CreateProductDialog(QDialog):
    """Clean popup modal dialog to register a new product with selling price."""

    def __init__(self, parent, product_service, pricing_service, session, categories):
        super().__init__(parent)
        self.product_service = product_service
        self.pricing_service = pricing_service
        self.session = session
        self.categories = categories

        self.setWindowTitle("Add New Product")
        self.setMinimumWidth(500)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        banner = DialogHeaderBanner(
            title="Register New Product",
            subtitle="Enter SKU, brand/generic naming, category, and retail selling price",
            parent_dialog=self,
        )
        layout.addWidget(banner)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(24, 18, 24, 22)
        body_layout.setSpacing(14)

        form = QFormLayout()
        form.setSpacing(12)

        self.sku_input = QLineEdit()
        self.sku_input.setPlaceholderText("e.g. PCM-500MG-01")
        form.addRow("Product SKU *:", self.sku_input)

        self.barcode_input = QLineEdit()
        self.barcode_input.setPlaceholderText("e.g. 8901234567890 (optional)")
        form.addRow("Barcode Scan:", self.barcode_input)

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("e.g. Paracetamol Tablets 500mg")
        form.addRow("Product Name *:", self.name_input)

        self.generic_input = QLineEdit()
        self.generic_input.setPlaceholderText("e.g. Acetaminophen")
        form.addRow("Generic / Molecule:", self.generic_input)

        self.brand_input = QLineEdit()
        self.brand_input.setPlaceholderText("e.g. Emzor / GSK (optional)")
        form.addRow("Brand Manufacturer:", self.brand_input)

        self.category_combo = QComboBox()
        self.category_combo.addItem("Select Category...", None)
        for cat in self.categories:
            self.category_combo.addItem(cat.name, cat.id)
        form.addRow("Dosage Category:", self.category_combo)

        self.price_input = QLineEdit()
        self.price_input.setPlaceholderText("e.g. 500.00")
        form.addRow("Selling Price (NGN) *:", self.price_input)

        self.rx_check = QCheckBox("Prescription Required (Rx Only)")
        form.addRow("", self.rx_check)

        self.all_branches_check = QCheckBox("Available in All Branches")
        self.all_branches_check.setChecked(True)
        form.addRow("", self.all_branches_check)

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

        self.save_btn = QPushButton("Save Product")
        self.save_btn.setStyleSheet(
            "background-color: #10B981; color: white; font-weight: 700; padding: 8px 18px; border-radius: 6px;"
        )
        self.save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(self.save_btn)

        body_layout.addLayout(btn_row)
        layout.addWidget(body)

    def _on_save(self):
        sku = self.sku_input.text().strip()
        name = self.name_input.text().strip()
        price_val = self.price_input.text().strip()

        if not sku:
            self.error_lbl.setText("Product SKU is required.")
            self.sku_input.setFocus()
            return
        if not name:
            self.error_lbl.setText("Product name is required.")
            self.name_input.setFocus()
            return
        if not price_val:
            self.error_lbl.setText("Selling price is required.")
            self.price_input.setFocus()
            return

        try:
            cat_id = self.category_combo.currentData()
            p = self.product_service.create_product(
                self.session,
                sku=sku,
                name=name,
                category_id=cat_id,
                barcode=self.barcode_input.text().strip() or None,
                generic_name=self.generic_input.text().strip() or None,
                brand_name=self.brand_input.text().strip() or None,
                prescription_required=self.rx_check.isChecked(),
                select_all_branches=self.all_branches_check.isChecked(),
            )
            if price_val and self.pricing_service:
                try:
                    branch_lbl = getattr(self.session, "branch_name", None) or "Branch"
                    self.pricing_service.set_price(
                        self.session,
                        product_id=p.id,
                        selling_price=price_val.replace(",", ""),
                        force_all_branches=True,
                        change_reason=f"Initial product price ({branch_lbl})",
                    )
                except Exception:
                    pass

            QMessageBox.information(
                self,
                "Product Created",
                f"Product '{name}' (SKU: {sku}) has been successfully created with selling price ₦{price_val}!",
            )
            self.accept()
        except Exception as e:
            self.error_lbl.setText(f"Error: {str(e)}")


class CreateCategoryDialog(QDialog):
    """Clean popup modal dialog to create a new dosage/product category."""

    def __init__(self, parent, product_service, session):
        super().__init__(parent)
        self.product_service = product_service
        self.session = session

        self.setWindowTitle("Add Dosage Category")
        self.setMinimumWidth(420)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        banner = DialogHeaderBanner(
            title="Add Dosage Category",
            subtitle="Create a classification category (e.g. Tablets, Syrups, Injections)",
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
        self.name_input.setPlaceholderText("e.g. Antibiotics, Analgesics, Syrups")
        form.addRow("Category Name *:", self.name_input)

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

        self.save_btn = QPushButton("Save Category")
        self.save_btn.setStyleSheet(
            "background-color: #10B981; color: white; font-weight: 700; padding: 8px 18px; border-radius: 6px;"
        )
        self.save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(self.save_btn)

        body_layout.addLayout(btn_row)
        layout.addWidget(body)

    def _on_save(self):
        name = self.name_input.text().strip()
        if not name:
            self.error_lbl.setText("Category name cannot be empty.")
            return

        try:
            self.product_service.create_category(self.session, name=name)
            QMessageBox.information(self, "Category Created", f"Category '{name}' created successfully.")
            self.accept()
        except Exception as e:
            self.error_lbl.setText(f"Error: {str(e)}")


class CreateSupplierDialog(QDialog):
    """Clean popup modal dialog to create a new pharmaceutical supplier/vendor."""

    def __init__(self, parent, product_service, session):
        super().__init__(parent)
        self.product_service = product_service
        self.session = session

        self.setWindowTitle("Add New Supplier")
        self.setMinimumWidth(460)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        banner = DialogHeaderBanner(
            title="Register New Supplier",
            subtitle="Record pharmaceutical manufacturer or wholesale distributor details",
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
        self.name_input.setPlaceholderText("e.g. Mega Pharma Distributors Ltd")
        form.addRow("Supplier Name *:", self.name_input)

        self.contact_input = QLineEdit()
        self.contact_input.setPlaceholderText("e.g. Dr. Jane Smith")
        form.addRow("Contact Person:", self.contact_input)

        self.phone_input = QLineEdit()
        self.phone_input.setPlaceholderText("e.g. 08012345678")
        form.addRow("Phone Number:", self.phone_input)

        self.email_input = QLineEdit()
        self.email_input.setPlaceholderText("e.g. orders@megapharma.com")
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

        self.save_btn = QPushButton("Save Supplier")
        self.save_btn.setStyleSheet(
            "background-color: #10B981; color: white; font-weight: 700; padding: 8px 18px; border-radius: 6px;"
        )
        self.save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(self.save_btn)

        body_layout.addLayout(btn_row)
        layout.addWidget(body)

    def _on_save(self):
        name = self.name_input.text().strip()
        if not name:
            self.error_lbl.setText("Supplier name is required.")
            return

        try:
            self.product_service.create_supplier(
                self.session,
                name=name,
                contact_person=self.contact_input.text().strip(),
                phone=self.phone_input.text().strip(),
                email=self.email_input.text().strip(),
            )
            QMessageBox.information(self, "Supplier Added", f"Supplier '{name}' added successfully.")
            self.accept()
        except Exception as e:
            self.error_lbl.setText(f"Error: {str(e)}")


class EditProductDialog(QDialog):
    """Modal dialog allowing users with PRODUCTS_EDIT permission to safely update a product and its Selling Price."""

    def __init__(self, parent, product_service, pricing_service, session, product, categories):
        super().__init__(parent)
        self.product_service = product_service
        self.pricing_service = pricing_service
        self.session = session
        self.product = product
        self.categories = categories

        self.setWindowTitle(f"Edit Product & Selling Price — {self.product.name}")
        self.setMinimumWidth(520)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        banner = DialogHeaderBanner(
            title=f"Edit Product & Price — {self.product.name}",
            subtitle=f"SKU: {self.product.sku} • ID: {self.product.id[:8]}",
            parent_dialog=self,
        )
        layout.addWidget(banner)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(24, 18, 24, 22)
        body_layout.setSpacing(14)

        grid = QGridLayout()
        grid.setSpacing(10)

        grid.addWidget(QLabel("Product Name: *"), 0, 0)
        self.name_input = QLineEdit(self.product.name)
        grid.addWidget(self.name_input, 0, 1)

        grid.addWidget(QLabel("Generic Name:"), 1, 0)
        self.generic_input = QLineEdit(self.product.generic_name or "")
        grid.addWidget(self.generic_input, 1, 1)

        grid.addWidget(QLabel("Barcode:"), 2, 0)
        self.barcode_input = QLineEdit(self.product.barcode or "")
        grid.addWidget(self.barcode_input, 2, 1)

        grid.addWidget(QLabel("Category:"), 3, 0)
        self.category_combo = QComboBox()
        for cat in self.categories:
            self.category_combo.addItem(cat.name, cat.id)
        if self.product.category_id:
            idx = self.category_combo.findData(self.product.category_id)
            if idx >= 0:
                self.category_combo.setCurrentIndex(idx)
        grid.addWidget(self.category_combo, 3, 1)

        grid.addWidget(QLabel("Brand Name:"), 4, 0)
        self.brand_input = QLineEdit(self.product.brand_name or "")
        grid.addWidget(self.brand_input, 4, 1)

        # Retail Selling Price field
        current_price_str = ""
        if self.pricing_service and self.session.organization_id:
            try:
                p_obj = self.pricing_service.resolve_price(
                    self.session.organization_id,
                    self.product.id,
                    self.session.branch_id,
                )
                if p_obj and p_obj.selling_price is not None:
                    current_price_str = f"{p_obj.selling_price:.2f}"
            except Exception:
                pass

        grid.addWidget(QLabel("Selling Price (NGN): *"), 5, 0)
        self.price_input = QLineEdit(current_price_str)
        self.price_input.setPlaceholderText("e.g. 3000.00 (Retail price charged at POS)")
        grid.addWidget(self.price_input, 5, 1)

        self.sync_all_branches_check = QCheckBox("Sync Selling Price Across All Branches (Recommended)")
        self.sync_all_branches_check.setChecked(True)
        grid.addWidget(self.sync_all_branches_check, 6, 1)

        self.rx_check = QCheckBox("Prescription Required (Rx)")
        self.rx_check.setChecked(bool(getattr(self.product, "prescription_required", False)))
        grid.addWidget(self.rx_check, 7, 1)

        body_layout.addLayout(grid)

        self.error_label = QLabel("")
        self.error_label.setStyleSheet("color: #EF4444; font-size: 12px; font-weight: 600;")
        body_layout.addWidget(self.error_label)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("SecondaryBtn")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        save_btn = QPushButton("Save Changes")
        save_btn.setStyleSheet(
            "background-color: #2563EB; color: white; font-weight: 700; padding: 8px 18px; border-radius: 6px;"
        )
        save_btn.clicked.connect(self._on_save)
        btn_layout.addWidget(save_btn)

        body_layout.addLayout(btn_layout)
        layout.addWidget(body)

    def _on_save(self):
        name = self.name_input.text().strip()
        if not name:
            self.error_label.setText("Product name cannot be empty.")
            self.name_input.setFocus()
            return

        price_raw = self.price_input.text().strip().replace(",", "")
        cat_id = self.category_combo.currentData()
        try:
            self.product_service.update_product(
                user_session=self.session,
                product_id=self.product.id,
                name=name,
                generic_name=self.generic_input.text().strip() or None,
                barcode=self.barcode_input.text().strip() or None,
                brand_name=self.brand_input.text().strip() or None,
                category_id=cat_id,
                prescription_required=self.rx_check.isChecked(),
            )
            if price_raw and self.pricing_service:
                sync_all = self.sync_all_branches_check.isChecked()
                branch_lbl = getattr(self.session, "branch_name", None) or "Branch"
                self.pricing_service.set_price(
                    self.session,
                    product_id=self.product.id,
                    selling_price=price_raw,
                    branch_id=None if sync_all else self.session.branch_id,
                    force_all_branches=sync_all,
                    change_reason=f"Updated by {branch_lbl} (Product Catalog)",
                )
            QMessageBox.information(
                self,
                "Product Updated",
                f"Product '{name}' and its selling price have been updated successfully.",
            )
            self.accept()
        except Exception as e:
            self.error_label.setText(str(e))


class PriceHistoryDialog(QDialog):
    """Modal dialog displaying recent retail selling price updates across all branches."""

    def __init__(self, parent, pricing_service, session):
        super().__init__(parent)
        self.pricing_service = pricing_service
        self.session = session
        self.setWindowTitle("Multi-Branch Price Change History & Notifications")
        self.resize(980, 500)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        banner = DialogHeaderBanner(
            title="Price Change History & Branch Notifications",
            subtitle="Complete log of retail selling price updates with originating Branch and Staff Account attribution",
            parent_dialog=self,
        )
        layout.addWidget(banner)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(24, 18, 24, 22)
        body_layout.setSpacing(14)

        table = QTableWidget(0, 8)
        table.setHorizontalHeaderLabels([
            "Product Name",
            "SKU",
            "Previous Price",
            "New Selling Price",
            "Updated By Branch",
            "Updated By Account",
            "Reason / Source",
            "Updated At",
        ])
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(38)
        table.setAlternatingRowColors(True)

        hdr = table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.Stretch)
        for c in range(1, 8):
            hdr.setSectionResizeMode(c, QHeaderView.Interactive)
        table.setColumnWidth(1, 95)
        table.setColumnWidth(2, 115)
        table.setColumnWidth(3, 125)
        table.setColumnWidth(4, 135)
        table.setColumnWidth(5, 165)
        table.setColumnWidth(6, 165)
        table.setColumnWidth(7, 135)

        changes = []
        if self.pricing_service and self.session.organization_id:
            try:
                changes = self.pricing_service.get_recent_price_changes(
                    self.session.organization_id, limit=50
                )
            except Exception:
                pass

        table.setRowCount(len(changes))
        for r, item in enumerate(changes):
            table.setItem(r, 0, QTableWidgetItem(item.get("product_name", "")))
            table.setItem(r, 1, QTableWidgetItem(item.get("product_sku", "")))

            old_p = item.get("old_price")
            old_str = f"₦{old_p:,.2f}" if old_p is not None else "— (Initial)"
            old_cell = QTableWidgetItem(old_str)
            old_cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            table.setItem(r, 2, old_cell)

            new_p = item.get("new_price")
            new_str = f"₦{new_p:,.2f}" if new_p is not None else "₦0.00"
            new_cell = QTableWidgetItem(new_str)
            new_cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            new_cell.setForeground(Qt.darkGreen)
            table.setItem(r, 3, new_cell)

            branch_cell = QTableWidgetItem(item.get("branch_name") or "Main Branch (HQ)")
            branch_cell.setForeground(QColor("#1E40AF"))
            table.setItem(r, 4, branch_cell)

            acct_cell = QTableWidgetItem(item.get("account_name") or "Administrator")
            table.setItem(r, 5, acct_cell)

            table.setItem(r, 6, QTableWidgetItem(item.get("change_reason", "")))
            ts = str(item.get("local_timestamp", ""))[:19].replace("T", " ")
            table.setItem(r, 7, QTableWidgetItem(ts))

        body_layout.addWidget(table)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.setObjectName("SecondaryBtn")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        body_layout.addLayout(btn_row)

        layout.addWidget(body)


class EditCategoryDialog(QDialog):
    """Modal dialog allowing users to rename a category."""

    def __init__(self, parent, product_service, session, category):
        super().__init__(parent)
        self.product_service = product_service
        self.session = session
        self.category = category

        self.setWindowTitle(f"Edit Category — {self.category.name}")
        self.setMinimumWidth(420)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        banner = DialogHeaderBanner(
            title=f"Edit Category — {self.category.name}",
            subtitle="Rename dosage or classification category",
            parent_dialog=self,
        )
        layout.addWidget(banner)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(24, 18, 24, 22)
        body_layout.setSpacing(14)

        self.name_input = QLineEdit(self.category.name)
        body_layout.addWidget(self.name_input)

        self.error_label = QLabel("")
        self.error_label.setStyleSheet("color: #EF4444; font-size: 12px; font-weight: 600;")
        body_layout.addWidget(self.error_label)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("SecondaryBtn")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        save_btn = QPushButton("Save Category")
        save_btn.setStyleSheet("background-color: #2563EB; color: white; font-weight: 700; padding: 8px 16px; border-radius: 6px;")
        save_btn.clicked.connect(self._on_save)
        btn_layout.addWidget(save_btn)

        body_layout.addLayout(btn_layout)
        layout.addWidget(body)

    def _on_save(self):
        name = self.name_input.text().strip()
        if not name:
            self.error_label.setText("Category name cannot be empty.")
            return

        try:
            self.product_service.update_category(
                user_session=self.session,
                category_id=self.category.id,
                name=name,
            )
            self.accept()
        except Exception as e:
            self.error_label.setText(str(e))


class EditSupplierDialog(QDialog):
    """Modal dialog allowing users to edit supplier contact info."""

    def __init__(self, parent, product_service, session, supplier):
        super().__init__(parent)
        self.product_service = product_service
        self.session = session
        self.supplier = supplier

        self.setWindowTitle(f"Edit Supplier — {self.supplier.name}")
        self.setMinimumWidth(460)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        banner = DialogHeaderBanner(
            title=f"Edit Supplier — {self.supplier.name}",
            subtitle="Update supplier contact and distributor details",
            parent_dialog=self,
        )
        layout.addWidget(banner)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(24, 18, 24, 22)
        body_layout.setSpacing(14)

        grid = QGridLayout()
        grid.setSpacing(10)

        grid.addWidget(QLabel("Supplier Name: *"), 0, 0)
        self.name_input = QLineEdit(self.supplier.name)
        grid.addWidget(self.name_input, 0, 1)

        grid.addWidget(QLabel("Contact Person:"), 1, 0)
        self.contact_input = QLineEdit(self.supplier.contact_person or "")
        grid.addWidget(self.contact_input, 1, 1)

        grid.addWidget(QLabel("Phone:"), 2, 0)
        self.phone_input = QLineEdit(self.supplier.phone or "")
        grid.addWidget(self.phone_input, 2, 1)

        grid.addWidget(QLabel("Email:"), 3, 0)
        self.email_input = QLineEdit(self.supplier.email or "")
        grid.addWidget(self.email_input, 3, 1)

        body_layout.addLayout(grid)

        self.error_label = QLabel("")
        self.error_label.setStyleSheet("color: #EF4444; font-size: 12px; font-weight: 600;")
        body_layout.addWidget(self.error_label)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("SecondaryBtn")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        save_btn = QPushButton("Save Supplier")
        save_btn.setStyleSheet("background-color: #2563EB; color: white; font-weight: 700; padding: 8px 16px; border-radius: 6px;")
        save_btn.clicked.connect(self._on_save)
        btn_layout.addWidget(save_btn)

        body_layout.addLayout(btn_layout)
        layout.addWidget(body)

    def _on_save(self):
        name = self.name_input.text().strip()
        if not name:
            self.error_label.setText("Supplier name cannot be empty.")
            return

        try:
            self.product_service.update_supplier(
                user_session=self.session,
                supplier_id=self.supplier.id,
                name=name,
                contact_person=self.contact_input.text().strip(),
                phone=self.phone_input.text().strip(),
                email=self.email_input.text().strip(),
            )
            self.accept()
        except Exception as e:
            self.error_label.setText(str(e))


class ProductsWidget(QWidget):
    """Desktop UI screen for Product Catalog (FTS5 search, creation, branch availability), Categories, and Suppliers."""

    def __init__(self, session, product_service=None, pricing_service=None):
        super().__init__()
        self.session = session
        self.product_service = product_service
        self.pricing_service = pricing_service

        # Categories and Suppliers Cache
        self.categories_list = []
        self.suppliers_list = []

        # Pagination & Data Cache
        self.all_products = []
        self.prices_map = {}
        self.current_page = 1
        self.page_size = 50
        self.total_pages = 1

        # Search debounce timer (150ms)
        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(150)
        self.search_timer.timeout.connect(self.refresh_products)

        self.init_ui()
        self.refresh_all()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        header_layout = QHBoxLayout()
        title_col = QVBoxLayout()
        title_col.setSpacing(4)

        header = QLabel("Product Catalog & Suppliers")
        header.setObjectName("PageHeader")
        subtitle = QLabel("Full-text searchable medicine catalog, retail selling prices, formulation categories, and verified suppliers")
        subtitle.setObjectName("PageSubtitle")
        title_col.addWidget(header)
        title_col.addWidget(subtitle)
        header_layout.addLayout(title_col)
        header_layout.addStretch()

        self.price_history_btn = QPushButton("📈 Price History")
        self.price_history_btn.setObjectName("SecondaryBtn")
        self.price_history_btn.clicked.connect(self._open_price_history_dialog)
        header_layout.addWidget(self.price_history_btn)

        self.refresh_btn = QPushButton("Refresh All")
        self.refresh_btn.setObjectName("SecondaryBtn")
        self.refresh_btn.clicked.connect(self.refresh_all)
        header_layout.addWidget(self.refresh_btn)

        layout.addLayout(header_layout)

        self.tabs = QTabWidget()
        self.products_tab = QWidget()
        self.categories_tab = QWidget()
        self.suppliers_tab = QWidget()

        self._init_products_tab()
        self._init_categories_tab()
        self._init_suppliers_tab()

        self.tabs.addTab(self.products_tab, "📦 Products Catalog")
        self.tabs.addTab(self.categories_tab, "🏷️ Dosage Categories")
        self.tabs.addTab(self.suppliers_tab, "🏭 Suppliers & Vendors")
        layout.addWidget(self.tabs)

    def _open_price_history_dialog(self):
        dlg = PriceHistoryDialog(
            parent=self,
            pricing_service=self.pricing_service,
            session=self.session,
        )
        dlg.exec()

    def _init_products_tab(self):
        layout = QVBoxLayout(self.products_tab)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(14)
        can_create = self.session.has_permission(PermissionCode.PRODUCTS_CREATE.value)
        can_edit = self.session.has_permission(PermissionCode.PRODUCTS_EDIT.value)
        can_del = self.session.has_permission(PermissionCode.PRODUCTS_DELETE.value)

        # Search & Action Toolbar matching master button bar standard
        toolbar = QHBoxLayout()
        toolbar.setSpacing(10)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search products by name, generic name, brand, SKU, or scan barcode...")
        self.search_input.textChanged.connect(lambda: self.search_timer.start())
        toolbar.addWidget(self.search_input, stretch=3)

        self.add_product_btn = QPushButton("+ Add Product")
        self.add_product_btn.setStyleSheet(
            "background-color: #10B981; color: white; font-weight: 700; padding: 8px 16px; border-radius: 6px;"
        )
        self.add_product_btn.setEnabled(can_create)
        self.add_product_btn.clicked.connect(self._open_create_product_dialog)
        toolbar.addWidget(self.add_product_btn)

        self.edit_product_btn = QPushButton("✏️ Edit Product / Price")
        self.edit_product_btn.setStyleSheet(
            "background-color: #2563EB; color: white; font-weight: 700; padding: 8px 16px; border-radius: 6px;"
        )
        self.edit_product_btn.setEnabled(can_edit)
        self.edit_product_btn.clicked.connect(self._on_edit_selected_product)
        toolbar.addWidget(self.edit_product_btn)

        self.delete_product_btn = QPushButton("🗑️ Deactivate")
        self.delete_product_btn.setStyleSheet(
            "background-color: #EF4444; color: white; font-weight: 700; padding: 8px 16px; border-radius: 6px;"
        )
        self.delete_product_btn.setEnabled(can_del)
        self.delete_product_btn.clicked.connect(self._on_delete_selected_product)
        toolbar.addWidget(self.delete_product_btn)

        layout.addLayout(toolbar)

        # High-Performance Products Table (with Selling Price column)
        self.products_table = QTableWidget(0, 6)
        self.products_table.setHorizontalHeaderLabels(
            ["SKU", "Barcode", "Product Name", "Generic Name", "Selling Price (NGN)", "Rx Req."]
        )
        self.products_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.products_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.products_table.setSelectionMode(QTableWidget.SingleSelection)
        self.products_table.cellDoubleClicked.connect(self._on_product_double_clicked)

        p_hdr = self.products_table.horizontalHeader()
        p_hdr.setSectionResizeMode(0, QHeaderView.Interactive)
        p_hdr.setSectionResizeMode(1, QHeaderView.Interactive)
        p_hdr.setSectionResizeMode(2, QHeaderView.Stretch)
        p_hdr.setSectionResizeMode(3, QHeaderView.Interactive)
        p_hdr.setSectionResizeMode(4, QHeaderView.Interactive)
        p_hdr.setSectionResizeMode(5, QHeaderView.Interactive)

        self.products_table.setColumnWidth(0, 135)
        self.products_table.setColumnWidth(1, 140)
        self.products_table.setColumnWidth(3, 185)
        self.products_table.setColumnWidth(4, 150)
        self.products_table.setColumnWidth(5, 95)

        self.products_table.verticalHeader().setDefaultSectionSize(38)
        self.products_table.verticalHeader().setVisible(False)
        self.products_table.setAlternatingRowColors(True)
        layout.addWidget(self.products_table)

        # Pagination Bar
        pagination_layout = QHBoxLayout()
        pagination_layout.setSpacing(12)

        self.page_status_label = QLabel("Showing 0 products")
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

    def _open_create_product_dialog(self):
        dlg = CreateProductDialog(
            parent=self,
            product_service=self.product_service,
            pricing_service=self.pricing_service,
            session=self.session,
            categories=self.categories_list,
        )
        if dlg.exec() == QDialog.Accepted:
            self.refresh_products()

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

    def _init_categories_tab(self):
        layout = QVBoxLayout(self.categories_tab)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(12)
        can_create = self.session.has_permission(PermissionCode.PRODUCTS_CREATE.value)
        can_edit = self.session.has_permission(PermissionCode.PRODUCTS_EDIT.value)
        can_del = self.session.has_permission(PermissionCode.PRODUCTS_DELETE.value)

        cat_toolbar = QHBoxLayout()
        cat_lbl = QLabel("Product & Formulation Categories")
        cat_lbl.setStyleSheet("font-size: 15px; font-weight: 700; color: #1E293B;")
        cat_toolbar.addWidget(cat_lbl)
        cat_toolbar.addStretch()

        self.add_cat_btn = QPushButton("+ Add Category")
        self.add_cat_btn.setStyleSheet(
            "background-color: #10B981; color: white; font-weight: 700; padding: 8px 16px; border-radius: 6px;"
        )
        self.add_cat_btn.setEnabled(can_create)
        self.add_cat_btn.clicked.connect(self._open_create_category_dialog)
        cat_toolbar.addWidget(self.add_cat_btn)

        self.edit_cat_btn = QPushButton("✏️ Edit Category")
        self.edit_cat_btn.setStyleSheet(
            "background-color: #2563EB; color: white; font-weight: 700; padding: 8px 16px; border-radius: 6px;"
        )
        self.edit_cat_btn.setEnabled(can_edit)
        self.edit_cat_btn.clicked.connect(self._on_edit_selected_category)
        cat_toolbar.addWidget(self.edit_cat_btn)

        self.delete_cat_btn = QPushButton("🗑️ Deactivate")
        self.delete_cat_btn.setStyleSheet(
            "background-color: #EF4444; color: white; font-weight: 700; padding: 8px 16px; border-radius: 6px;"
        )
        self.delete_cat_btn.setEnabled(can_del)
        self.delete_cat_btn.clicked.connect(self._on_delete_selected_category)
        cat_toolbar.addWidget(self.delete_cat_btn)

        layout.addLayout(cat_toolbar)

        self.cat_table = QTableWidget(0, 1)
        self.cat_table.setHorizontalHeaderLabels(["Category Name"])
        self.cat_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.cat_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.cat_table.setSelectionMode(QTableWidget.SingleSelection)
        self.cat_table.cellDoubleClicked.connect(self._on_cat_double_clicked)

        c_hdr = self.cat_table.horizontalHeader()
        c_hdr.setSectionResizeMode(0, QHeaderView.Stretch)
        self.cat_table.verticalHeader().setDefaultSectionSize(38)
        self.cat_table.verticalHeader().setVisible(False)
        self.cat_table.setAlternatingRowColors(True)
        layout.addWidget(self.cat_table)

    def _open_create_category_dialog(self):
        dlg = CreateCategoryDialog(self, self.product_service, self.session)
        if dlg.exec() == QDialog.Accepted:
            self.refresh_categories()

    def _on_cat_double_clicked(self, row, col):
        if 0 <= row < len(self.categories_list):
            cat = self.categories_list[row]
            self._open_edit_category_dialog(cat)

    def _on_edit_selected_category(self):
        row = self.cat_table.currentRow()
        if row < 0 or row >= len(self.categories_list):
            QMessageBox.information(self, "Select Category", "Please click a category row in the table to select it first.")
            return
        self._open_edit_category_dialog(self.categories_list[row])

    def _on_delete_selected_category(self):
        row = self.cat_table.currentRow()
        if row < 0 or row >= len(self.categories_list):
            QMessageBox.information(self, "Select Category", "Please click a category row in the table to select it first.")
            return
        self._delete_category(self.categories_list[row])

    def _init_suppliers_tab(self):
        layout = QVBoxLayout(self.suppliers_tab)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(12)
        can_manage = self.session.has_permission(PermissionCode.SUPPLIERS_MANAGE.value)

        sup_toolbar = QHBoxLayout()
        sup_lbl = QLabel("Verified Pharmaceutical Suppliers & Vendors")
        sup_lbl.setStyleSheet("font-size: 15px; font-weight: 700; color: #1E293B;")
        sup_toolbar.addWidget(sup_lbl)
        sup_toolbar.addStretch()

        self.add_sup_btn = QPushButton("+ Add Supplier")
        self.add_sup_btn.setStyleSheet(
            "background-color: #10B981; color: white; font-weight: 700; padding: 8px 16px; border-radius: 6px;"
        )
        self.add_sup_btn.setEnabled(can_manage)
        self.add_sup_btn.clicked.connect(self._open_create_supplier_dialog)
        sup_toolbar.addWidget(self.add_sup_btn)

        self.edit_sup_btn = QPushButton("✏️ Edit Supplier")
        self.edit_sup_btn.setStyleSheet(
            "background-color: #2563EB; color: white; font-weight: 700; padding: 8px 16px; border-radius: 6px;"
        )
        self.edit_sup_btn.setEnabled(can_manage)
        self.edit_sup_btn.clicked.connect(self._on_edit_selected_supplier)
        sup_toolbar.addWidget(self.edit_sup_btn)

        self.delete_sup_btn = QPushButton("🗑️ Deactivate")
        self.delete_sup_btn.setStyleSheet(
            "background-color: #EF4444; color: white; font-weight: 700; padding: 8px 16px; border-radius: 6px;"
        )
        self.delete_sup_btn.setEnabled(can_manage)
        self.delete_sup_btn.clicked.connect(self._on_delete_selected_supplier)
        sup_toolbar.addWidget(self.delete_sup_btn)

        layout.addLayout(sup_toolbar)

        self.sup_table = QTableWidget(0, 4)
        self.sup_table.setHorizontalHeaderLabels(["Supplier Name", "Contact Person", "Phone", "Email Address"])
        self.sup_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.sup_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.sup_table.setSelectionMode(QTableWidget.SingleSelection)
        self.sup_table.cellDoubleClicked.connect(self._on_sup_double_clicked)

        s_hdr = self.sup_table.horizontalHeader()
        s_hdr.setSectionResizeMode(0, QHeaderView.Stretch)
        s_hdr.setSectionResizeMode(1, QHeaderView.Interactive)
        s_hdr.setSectionResizeMode(2, QHeaderView.Interactive)
        s_hdr.setSectionResizeMode(3, QHeaderView.Interactive)
        self.sup_table.setColumnWidth(1, 180)
        self.sup_table.setColumnWidth(2, 140)
        self.sup_table.setColumnWidth(3, 180)
        self.sup_table.verticalHeader().setDefaultSectionSize(38)
        self.sup_table.verticalHeader().setVisible(False)
        self.sup_table.setAlternatingRowColors(True)
        layout.addWidget(self.sup_table)

    def _open_create_supplier_dialog(self):
        dlg = CreateSupplierDialog(self, self.product_service, self.session)
        if dlg.exec() == QDialog.Accepted:
            self.refresh_suppliers()

    def _on_sup_double_clicked(self, row, col):
        if 0 <= row < len(self.suppliers_list):
            sup = self.suppliers_list[row]
            self._open_edit_supplier_dialog(sup)

    def _on_edit_selected_supplier(self):
        row = self.sup_table.currentRow()
        if row < 0 or row >= len(self.suppliers_list):
            QMessageBox.information(self, "Select Supplier", "Please click a supplier row in the table to select it first.")
            return
        self._open_edit_supplier_dialog(self.suppliers_list[row])

    def _on_delete_selected_supplier(self):
        row = self.sup_table.currentRow()
        if row < 0 or row >= len(self.suppliers_list):
            QMessageBox.information(self, "Select Supplier", "Please click a supplier row in the table to select it first.")
            return
        self._delete_supplier(self.suppliers_list[row])

    def refresh_all(self):
        self.refresh_categories()
        self.refresh_suppliers()
        self.refresh_products()

    def refresh_categories(self):
        if not self.product_service or not self.session.organization_id:
            return
        self.categories_list = self.product_service.list_categories(self.session.organization_id)

        self.cat_table.setUpdatesEnabled(False)
        self.cat_table.blockSignals(True)
        try:
            self.cat_table.setRowCount(len(self.categories_list))
            for row, c in enumerate(self.categories_list):
                self.cat_table.setItem(row, 0, QTableWidgetItem(c.name))
        finally:
            self.cat_table.blockSignals(False)
            self.cat_table.setUpdatesEnabled(True)

    def refresh_suppliers(self):
        if not self.product_service or not self.session.organization_id:
            return
        self.suppliers_list = self.product_service.list_suppliers(self.session.organization_id)

        self.sup_table.setUpdatesEnabled(False)
        self.sup_table.blockSignals(True)
        try:
            self.sup_table.setRowCount(len(self.suppliers_list))
            for row, s in enumerate(self.suppliers_list):
                self.sup_table.setItem(row, 0, QTableWidgetItem(s.name))
                self.sup_table.setItem(row, 1, QTableWidgetItem(s.contact_person or ""))
                self.sup_table.setItem(row, 2, QTableWidgetItem(s.phone or ""))
                self.sup_table.setItem(row, 3, QTableWidgetItem(s.email or ""))
        finally:
            self.sup_table.blockSignals(False)
            self.sup_table.setUpdatesEnabled(True)

    def refresh_products(self):
        if not self.product_service or not self.session.organization_id:
            return
        query = self.search_input.text().strip()
        self.all_products = self.product_service.search_products(
            organization_id=self.session.organization_id,
            query=query,
        )
        self.prices_map = {}
        self.recent_prices_map = {}
        if self.pricing_service and self.all_products:
            try:
                p_ids = [p.id for p in self.all_products]
                self.prices_map = self.pricing_service.resolve_prices_bulk(
                    organization_id=self.session.organization_id,
                    product_ids=p_ids,
                    branch_id=self.session.branch_id,
                )
                self.recent_prices_map = self.pricing_service.get_recently_updated_product_ids(
                    organization_id=self.session.organization_id,
                    hours=24,
                )
            except Exception:
                self.prices_map = {}
                self.recent_prices_map = {}
        self.current_page = 1
        self._render_current_page()

    def _render_current_page(self):
        total_count = len(self.all_products)
        self.total_pages = max(1, (total_count + self.page_size - 1) // self.page_size) if self.page_size > 0 else 1
        self.current_page = min(self.current_page, self.total_pages)

        start_idx = (self.current_page - 1) * self.page_size
        end_idx = min(start_idx + self.page_size, total_count)
        page_items = self.all_products[start_idx:end_idx]
        green_bg = QColor("#DCFCE7")

        self.products_table.setUpdatesEnabled(False)
        self.products_table.blockSignals(True)
        try:
            self.products_table.setRowCount(len(page_items))
            for row, p in enumerate(page_items):
                c0 = QTableWidgetItem(p.sku)
                c1 = QTableWidgetItem(p.barcode or "")
                c2 = QTableWidgetItem(p.name)
                c3 = QTableWidgetItem(p.generic_name or "")

                price_obj = self.prices_map.get(p.id)
                if price_obj and price_obj.selling_price is not None:
                    price_str = f"₦{price_obj.selling_price:,.2f}"
                    price_cell = QTableWidgetItem(price_str)
                    price_cell.setForeground(Qt.darkGreen)
                else:
                    price_str = "Not Set"
                    price_cell = QTableWidgetItem("Not Set")
                    price_cell.setForeground(Qt.darkYellow)
                price_cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)

                rx_cell = QTableWidgetItem("Yes" if getattr(p, "prescription_required", False) else "No")
                rx_cell.setTextAlignment(Qt.AlignCenter)

                update_info = getattr(self, "recent_prices_map", {}).get(p.id)
                if update_info:
                    for cell in (c0, c1, c2, c3, price_cell, rx_cell):
                        cell.setBackground(green_bg)

                self.products_table.setItem(row, 0, c0)
                self.products_table.setItem(row, 1, c1)
                self.products_table.setItem(row, 2, c2)
                self.products_table.setItem(row, 3, c3)
                self.products_table.setItem(row, 4, price_cell)
                self.products_table.setItem(row, 5, rx_cell)

                if update_info and price_obj and price_obj.selling_price is not None:
                    price_cell.setText("")
                    widget = create_price_cell_widget(
                        self,
                        product_name=f"{p.name} ({p.sku})",
                        price_text=price_str,
                        update_info=update_info,
                        on_select_row=lambda r_idx=row: self.products_table.selectRow(r_idx),
                    )
                    self.products_table.setCellWidget(row, 4, widget)
        finally:
            self.products_table.blockSignals(False)
            self.products_table.setUpdatesEnabled(True)

        if total_count == 0:
            self.page_status_label.setText("Showing 0 products")
        else:
            self.page_status_label.setText(f"Showing {start_idx + 1}–{end_idx} of {total_count} products")
        self.page_info_label.setText(f"Page {self.current_page} of {self.total_pages}")
        self.prev_page_btn.setEnabled(self.current_page > 1)
        self.next_page_btn.setEnabled(self.current_page < self.total_pages)

    def _on_edit_selected_product(self):
        row = self.products_table.currentRow()
        start_idx = (self.current_page - 1) * self.page_size
        actual_idx = start_idx + row
        if row < 0 or actual_idx >= len(self.all_products):
            QMessageBox.information(self, "Select Product", "Please click a product row in the table to select it first.")
            return
        prod = self.all_products[actual_idx]
        self._open_edit_product_dialog(prod)

    def _on_delete_selected_product(self):
        row = self.products_table.currentRow()
        start_idx = (self.current_page - 1) * self.page_size
        actual_idx = start_idx + row
        if row < 0 or actual_idx >= len(self.all_products):
            QMessageBox.information(self, "Select Product", "Please click a product row in the table to select it first.")
            return
        prod = self.all_products[actual_idx]
        self._delete_product(prod)

    def _on_product_double_clicked(self, row, col):
        start_idx = (self.current_page - 1) * self.page_size
        actual_idx = start_idx + row
        if 0 <= actual_idx < len(self.all_products):
            prod = self.all_products[actual_idx]
            self._open_edit_product_dialog(prod)

    def _open_edit_product_dialog(self, product):
        if not self.session.has_permission(PermissionCode.PRODUCTS_EDIT.value):
            QMessageBox.warning(self, "Permission Denied", "You do not have permission to edit products.")
            return
        dlg = EditProductDialog(
            parent=self,
            product_service=self.product_service,
            pricing_service=self.pricing_service,
            session=self.session,
            product=product,
            categories=self.categories_list,
        )
        if dlg.exec():
            self.refresh_products()

    def _delete_product(self, product):
        if not self.session.has_permission(PermissionCode.PRODUCTS_DELETE.value):
            QMessageBox.warning(self, "Permission Denied", "You do not have permission to delete products.")
            return
        reply = QMessageBox.question(
            self,
            "Confirm Deactivation",
            f"Are you sure you want to deactivate product '{product.name}' (SKU: {product.sku})?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            try:
                self.product_service.delete_product(self.session, product.id)
                self.refresh_products()
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to deactivate product: {str(e)}")

    def _open_edit_category_dialog(self, category):
        if not self.session.has_permission(PermissionCode.PRODUCTS_EDIT.value):
            QMessageBox.warning(self, "Permission Denied", "You do not have permission to edit categories.")
            return
        dlg = EditCategoryDialog(self, self.product_service, self.session, category)
        if dlg.exec():
            self.refresh_categories()

    def _delete_category(self, category):
        if not self.session.has_permission(PermissionCode.PRODUCTS_DELETE.value):
            QMessageBox.warning(self, "Permission Denied", "You do not have permission to delete categories.")
            return
        reply = QMessageBox.question(
            self,
            "Confirm Deactivation",
            f"Are you sure you want to deactivate category '{category.name}'?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            try:
                self.product_service.delete_category(self.session, category.id)
                self.refresh_categories()
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to deactivate category: {str(e)}")

    def _open_edit_supplier_dialog(self, supplier):
        if not self.session.has_permission(PermissionCode.SUPPLIERS_MANAGE.value):
            QMessageBox.warning(self, "Permission Denied", "You do not have permission to edit suppliers.")
            return
        dlg = EditSupplierDialog(self, self.product_service, self.session, supplier)
        if dlg.exec():
            self.refresh_suppliers()

    def _delete_supplier(self, supplier):
        if not self.session.has_permission(PermissionCode.SUPPLIERS_MANAGE.value):
            QMessageBox.warning(self, "Permission Denied", "You do not have permission to delete suppliers.")
            return
        reply = QMessageBox.question(
            self,
            "Confirm Deactivation",
            f"Are you sure you want to deactivate supplier '{supplier.name}'?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            try:
                self.product_service.delete_supplier(self.session, supplier.id)
                self.refresh_suppliers()
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to deactivate supplier: {str(e)}")
