import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Column,
    String,
    Boolean,
    ForeignKey,
    Integer,
    BigInteger,
    Numeric,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import declarative_base

Base = declarative_base()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class BaseModel(Base):
    __abstract__ = True
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    created_at = Column(String, default=utc_now_iso)
    updated_at = Column(String, default=utc_now_iso, onupdate=utc_now_iso)
    is_active = Column(Boolean, default=True)


class Organization(BaseModel):
    __tablename__ = 'organizations'
    name = Column(String(255), nullable=False)
    code = Column(String(50), nullable=False, unique=True)
    address = Column(String, default='')
    phone = Column(String(50), default='')
    email = Column(String(255), default='')
    logo_url = Column(String(500), default='')
    settings = Column(String, default='{}')  # JSON text


class Branch(BaseModel):
    __tablename__ = 'branches'
    __table_args__ = (
        UniqueConstraint('organization_id', 'code', name='uq_branch_org_code'),
    )
    organization_id = Column(String(36), ForeignKey('organizations.id'), nullable=False)
    name = Column(String(255), nullable=False)
    code = Column(String(20), nullable=False)
    address = Column(String, default='')
    phone = Column(String(50), default='')
    email = Column(String(255), default='')
    uses_storage_locations = Column(Boolean, default=False)
    initial_stock_loaded = Column(Boolean, default=False)
    settings = Column(String, default='{}')  # JSON text


class Device(BaseModel):
    __tablename__ = 'devices'
    __table_args__ = (
        UniqueConstraint('branch_id', 'code', name='uq_device_branch_code'),
    )
    organization_id = Column(String(36), ForeignKey('organizations.id'), nullable=False)
    branch_id = Column(String(36), ForeignKey('branches.id'), nullable=False)
    name = Column(String(255), nullable=False)
    code = Column(String(5), nullable=False)
    device_identifier = Column(String(255), unique=True, nullable=False)
    last_seen_at = Column(String, nullable=True)


class User(BaseModel):
    """
    Local user profile cache.
    NOTE: Server password_hash is NEVER transmitted or stored here.
    Offline password verification uses OfflineCredential.offline_password_hash.
    """
    __tablename__ = 'users'
    __table_args__ = (
        UniqueConstraint('organization_id', 'username', name='uq_user_org_username'),
    )
    organization_id = Column(String(36), ForeignKey('organizations.id'), nullable=False)
    username = Column(String(150), nullable=False)
    email = Column(String(255), default='')
    full_name = Column(String(255), default='')
    phone = Column(String(50), default='')
    is_org_admin = Column(Boolean, default=False)
    default_branch_id = Column(String(36), ForeignKey('branches.id'), nullable=True)


class Role(BaseModel):
    __tablename__ = 'roles'
    organization_id = Column(String(36), ForeignKey('organizations.id'), nullable=False)
    name = Column(String(100), nullable=False)
    description = Column(String, default='')
    is_system = Column(Boolean, default=False)


class Permission(BaseModel):
    __tablename__ = 'permissions'
    code = Column(String(100), unique=True, nullable=False)
    name = Column(String(255), nullable=False)
    category = Column(String(100), nullable=False)


class RolePermission(BaseModel):
    __tablename__ = 'role_permissions'
    __table_args__ = (
        UniqueConstraint('role_id', 'permission_id', name='uq_role_permission'),
    )
    role_id = Column(String(36), ForeignKey('roles.id'), nullable=False)
    permission_id = Column(String(36), ForeignKey('permissions.id'), nullable=False)


class UserRole(BaseModel):
    __tablename__ = 'user_roles'
    __table_args__ = (
        UniqueConstraint('user_id', 'role_id', 'branch_id', name='uq_user_role_branch'),
    )
    user_id = Column(String(36), ForeignKey('users.id'), nullable=False)
    role_id = Column(String(36), ForeignKey('roles.id'), nullable=False)
    branch_id = Column(String(36), ForeignKey('branches.id'), nullable=True)
    assigned_by_id = Column(String(36), ForeignKey('users.id'), nullable=True)


class OfflineCredential(Base):
    """
    Local-only offline credential cache.
    offline_password_hash is generated locally by the desktop using bcrypt.
    """
    __tablename__ = 'offline_credentials'
    user_id = Column(String(36), primary_key=True)
    offline_password_hash = Column(String(255), nullable=False)
    cached_permissions = Column(String, default='[]')  # JSON text
    cached_roles = Column(String, default='[]')  # JSON text
    cached_user_profile = Column(String, default='{}')  # JSON text
    is_active = Column(Boolean, default=True)
    last_online_login_at = Column(String, nullable=False)
    updated_at = Column(String, default=utc_now_iso, onupdate=utc_now_iso)


class SyncEvent(BaseModel):
    """Local outbox table for event-based synchronization."""
    __tablename__ = 'sync_events'
    __table_args__ = (
        Index('ix_sync_events_status_created', 'status', 'created_at'),
    )
    branch_id = Column(String(36), nullable=False)
    device_id = Column(String(36), nullable=False)
    entity_type = Column(String(50), nullable=False)
    entity_id = Column(String(36), nullable=False)
    operation = Column(String(20), nullable=False)
    payload = Column(String, nullable=False)  # JSON text
    correlation_id = Column(String(36), nullable=True)
    dependency_level = Column(Integer, default=1)
    schema_version = Column(Integer, default=1)
    local_created_at = Column(String, default=utc_now_iso)
    retry_count = Column(Integer, default=0)
    max_retries = Column(Integer, default=10)
    last_attempt_at = Column(String, nullable=True)
    status = Column(String(20), default='PENDING')
    error_message = Column(String, nullable=True)
    server_received_at = Column(String, nullable=True)


class SyncCursor(Base):
    """Single download cursor per device based on monotonic SyncDelivery.id."""
    __tablename__ = 'sync_cursors'
    device_id = Column(String(36), primary_key=True)
    last_server_sequence = Column(BigInteger, default=0)
    last_sync_at = Column(String, nullable=True)
    needs_full_resync = Column(Boolean, default=False)


class SchemaVersion(Base):
    """Tracks applied embedded SQLite schema migrations."""
    __tablename__ = 'schema_versions'
    version = Column(Integer, primary_key=True)
    applied_at = Column(String, default=utc_now_iso)
    description = Column(String(255), default='')


class AuditEvent(BaseModel):
    """Immutable local audit trail table."""
    __tablename__ = 'audit_events'
    __table_args__ = (
        Index('ix_audit_org_branch_created', 'organization_id', 'branch_id', 'created_at'),
        Index('ix_audit_entity', 'entity_type', 'entity_id'),
    )
    organization_id = Column(String(36), nullable=False)
    branch_id = Column(String(36), nullable=False)
    user_id = Column(String(36), nullable=False)
    device_id = Column(String(36), nullable=True)
    action = Column(String(50), nullable=False)
    entity_type = Column(String(50), nullable=False)
    entity_id = Column(String(36), nullable=False)
    data_before = Column(String, nullable=True)  # JSON text
    data_after = Column(String, nullable=True)  # JSON text
    reason = Column(String, default='')
    correlation_id = Column(String(36), nullable=True)
    transaction_id = Column(String(36), nullable=True)
    local_timestamp = Column(String, nullable=False)
    server_timestamp = Column(String, nullable=True)
    is_offline = Column(Boolean, default=True)
    source = Column(String(20), default='DESKTOP')
    sync_id = Column(String(36), nullable=True)


class PrinterConfiguration(BaseModel):
    """Local-only thermal receipt printer configuration."""
    __tablename__ = 'printer_configurations'
    branch_id = Column(String(36), ForeignKey('branches.id'), nullable=True)
    device_id = Column(String(36), ForeignKey('devices.id'), nullable=True)
    printer_name = Column(String(255), nullable=False)
    printer_type = Column(String(50), default='thermal_80mm')  # thermal_58mm, thermal_80mm
    connection_type = Column(String(50), default='usb')  # usb, serial, network
    connection_string = Column(String(255), default='')
    is_default = Column(Boolean, default=True)
    settings = Column(String, default='{}')  # JSON text


class Category(BaseModel):
    __tablename__ = 'categories'
    organization_id = Column(String(36), ForeignKey('organizations.id'), nullable=False)
    name = Column(String(255), nullable=False)
    parent_id = Column(String(36), ForeignKey('categories.id'), nullable=True)


class ProductType(BaseModel):
    __tablename__ = 'product_types'
    __table_args__ = (
        UniqueConstraint('organization_id', 'name', name='uq_product_type_org_name'),
    )
    organization_id = Column(String(36), ForeignKey('organizations.id'), nullable=False)
    name = Column(String(100), nullable=False)
    description = Column(String, default='')


class Manufacturer(BaseModel):
    __tablename__ = 'manufacturers'
    __table_args__ = (
        UniqueConstraint('organization_id', 'name', name='uq_manufacturer_org_name'),
    )
    organization_id = Column(String(36), ForeignKey('organizations.id'), nullable=False)
    name = Column(String(255), nullable=False)
    country = Column(String(100), default='')
    contact_info = Column(String, default='')


class Supplier(BaseModel):
    __tablename__ = 'suppliers'
    __table_args__ = (
        UniqueConstraint('organization_id', 'name', name='uq_supplier_org_name'),
    )
    organization_id = Column(String(36), ForeignKey('organizations.id'), nullable=False)
    name = Column(String(255), nullable=False)
    contact_person = Column(String(255), default='')
    phone = Column(String(50), default='')
    email = Column(String(255), default='')
    address = Column(String, default='')
    notes = Column(String, default='')


class Product(BaseModel):
    """
    Organization-level product master catalog record.
    All pharmaceutical fields are nullable so cosmetics, supplements, and devices
    work without requiring drug-specific metadata.
    """
    __tablename__ = 'products'
    __table_args__ = (
        UniqueConstraint('organization_id', 'sku', name='uq_product_org_sku'),
        Index('ix_product_org_sku', 'organization_id', 'sku'),
        Index('ix_product_org_barcode', 'organization_id', 'barcode'),
        Index('ix_product_org_name', 'organization_id', 'name'),
    )
    organization_id = Column(String(36), ForeignKey('organizations.id'), nullable=False)
    sku = Column(String(50), nullable=False)
    barcode = Column(String(100), nullable=True)
    name = Column(String(255), nullable=False)
    generic_name = Column(String(255), nullable=True)
    brand_name = Column(String(255), nullable=True)
    category_id = Column(String(36), ForeignKey('categories.id'), nullable=False)
    product_type_id = Column(String(36), ForeignKey('product_types.id'), nullable=True)
    manufacturer_id = Column(String(36), ForeignKey('manufacturers.id'), nullable=True)
    description = Column(String, default='')
    active_ingredients = Column(String, nullable=True)
    strength = Column(String(100), nullable=True)
    dosage_form = Column(String(100), nullable=True)
    route = Column(String(100), nullable=True)
    formulation = Column(String(255), nullable=True)
    indication = Column(String, nullable=True)
    contraindications = Column(String, nullable=True)
    precautions = Column(String, nullable=True)
    drug_interactions = Column(String, nullable=True)
    side_effects = Column(String, nullable=True)
    storage_conditions = Column(String(255), nullable=True)
    age_suitability = Column(String(100), nullable=True)
    pregnancy_caution = Column(Boolean, default=False)
    prescription_required = Column(Boolean, default=False)
    controlled_status = Column(String(50), nullable=True)
    importer = Column(String(255), nullable=True)
    regulatory_info = Column(String, nullable=True)
    image_url = Column(String(500), nullable=True)
    notes = Column(String, nullable=True)


class ProductBranch(BaseModel):
    """Opt-in branch availability mapping for products."""
    __tablename__ = 'product_branches'
    __table_args__ = (
        UniqueConstraint('product_id', 'branch_id', name='uq_product_branch'),
    )
    product_id = Column(String(36), ForeignKey('products.id'), nullable=False)
    branch_id = Column(String(36), ForeignKey('branches.id'), nullable=False)
    reorder_level = Column(Integer, nullable=True)
    settings = Column(String, default='{}')  # JSON text


class ProductDocument(Base):
    __tablename__ = 'product_documents'
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    product_id = Column(String(36), ForeignKey('products.id'), nullable=False)
    name = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=False)
    document_type = Column(String(50), nullable=True)
    uploaded_by_id = Column(String(36), ForeignKey('users.id'), nullable=True)
    created_at = Column(String, default=utc_now_iso)


class Batch(Base):
    __tablename__ = 'batches'
    __table_args__ = (
        UniqueConstraint('product_id', 'batch_number', name='uq_batch_product_number'),
        Index('ix_batch_product_expiry', 'product_id', 'expiry_date'),
    )
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id = Column(String(36), ForeignKey('organizations.id'), nullable=False)
    product_id = Column(String(36), ForeignKey('products.id'), nullable=False)
    batch_number = Column(String(100), nullable=False)
    manufacturing_date = Column(String(20), nullable=True)  # ISO YYYY-MM-DD
    expiry_date = Column(String(20), nullable=False)  # ISO YYYY-MM-DD
    purchase_price = Column(Numeric(12, 2), nullable=False)
    supplier_id = Column(String(36), ForeignKey('suppliers.id'), nullable=True)
    invoice_reference = Column(String(100), default='')
    received_date = Column(String(20), nullable=False)  # ISO YYYY-MM-DD
    status = Column(String(20), default='ACTIVE')  # ACTIVE, EXPIRED, RECALLED, DEPLETED
    regulatory_metadata = Column(String, nullable=True)  # JSON text
    notes = Column(String, default='')
    created_at = Column(String, default=utc_now_iso)
    updated_at = Column(String, default=utc_now_iso, onupdate=utc_now_iso)


class StorageLocation(BaseModel):
    __tablename__ = 'storage_locations'
    __table_args__ = (
        UniqueConstraint('branch_id', 'name', name='uq_storage_location_branch_name'),
    )
    organization_id = Column(String(36), ForeignKey('organizations.id'), nullable=False)
    branch_id = Column(String(36), ForeignKey('branches.id'), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(String, default='')
    location_type = Column(String(50), default='')


class StorageLocationAssignment(BaseModel):
    __tablename__ = 'storage_location_assignments'
    organization_id = Column(String(36), ForeignKey('organizations.id'), nullable=False)
    storage_location_id = Column(String(36), ForeignKey('storage_locations.id'), nullable=False)
    user_id = Column(String(36), ForeignKey('users.id'), nullable=False)
    branch_id = Column(String(36), ForeignKey('branches.id'), nullable=False)
    start_date = Column(String(20), nullable=False)
    end_date = Column(String(20), nullable=True)
    assigned_by_id = Column(String(36), ForeignKey('users.id'), nullable=True)


class BranchInventory(Base):
    __tablename__ = 'branch_inventories'
    __table_args__ = (
        UniqueConstraint(
            'branch_id', 'batch_id', 'storage_location_id', name='uq_branch_batch_location'
        ),
        Index('ix_branch_inventory_status', 'branch_id', 'status'),
    )
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id = Column(String(36), ForeignKey('organizations.id'), nullable=False)
    branch_id = Column(String(36), ForeignKey('branches.id'), nullable=False)
    batch_id = Column(String(36), ForeignKey('batches.id'), nullable=False)
    storage_location_id = Column(String(36), ForeignKey('storage_locations.id'), nullable=True)
    quantity = Column(Integer, default=0, nullable=False)
    reserved_quantity = Column(Integer, default=0, nullable=False)
    reorder_level = Column(Integer, nullable=True)
    status = Column(String(20), default='AVAILABLE')  # AVAILABLE, DEPLETED, QUARANTINED
    last_counted_at = Column(String, nullable=True)
    created_at = Column(String, default=utc_now_iso)
    updated_at = Column(String, default=utc_now_iso, onupdate=utc_now_iso)

    @property
    def available_quantity(self) -> int:
        return (self.quantity or 0) - (self.reserved_quantity or 0)


class InventoryMovement(Base):
    """
    Immutable local inventory movement ledger (Architecture Decision #15).
    No UPDATE or DELETE is ever permitted on this table.
    """
    __tablename__ = 'inventory_movements'
    __table_args__ = (
        Index('ix_inv_movement_branch_batch_created', 'branch_id', 'batch_id', 'created_at'),
        Index('ix_inv_movement_ref', 'reference_type', 'reference_id'),
    )
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id = Column(String(36), ForeignKey('organizations.id'), nullable=False)
    branch_id = Column(String(36), ForeignKey('branches.id'), nullable=False)
    batch_id = Column(String(36), ForeignKey('batches.id'), nullable=False)
    storage_location_id = Column(String(36), ForeignKey('storage_locations.id'), nullable=True)
    movement_type = Column(String(30), nullable=False)
    quantity_change = Column(Integer, nullable=False)
    quantity_before = Column(Integer, nullable=False)
    quantity_after = Column(Integer, nullable=False)
    reference_type = Column(String(50), nullable=False)
    reference_id = Column(String(36), nullable=False)
    user_id = Column(String(36), nullable=False)
    device_id = Column(String(36), nullable=True)
    notes = Column(String, default='')
    local_timestamp = Column(String, nullable=False)
    server_timestamp = Column(String, nullable=True)
    is_offline = Column(Boolean, default=True)
    created_at = Column(String, default=utc_now_iso)


class Price(Base):
    __tablename__ = 'prices'
    __table_args__ = (
        Index('ix_price_product_branch_current', 'product_id', 'branch_id', 'is_current'),
    )
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id = Column(String(36), ForeignKey('organizations.id'), nullable=False)
    product_id = Column(String(36), ForeignKey('products.id'), nullable=False)
    branch_id = Column(String(36), ForeignKey('branches.id'), nullable=True)
    selling_price = Column(Numeric(12, 2), nullable=False)
    currency = Column(String(10), default='NGN')
    is_current = Column(Boolean, default=True)
    version = Column(Integer, default=1)
    effective_from = Column(String, default=utc_now_iso)
    effective_to = Column(String, nullable=True)
    created_by_id = Column(String(36), ForeignKey('users.id'), nullable=True)
    sync_status = Column(String(20), default='PENDING')
    created_at = Column(String, default=utc_now_iso)
    updated_at = Column(String, default=utc_now_iso, onupdate=utc_now_iso)


class PriceHistory(Base):
    """
    Immutable audit ledger of price changes (Architecture Plan §2.3 & §11).
    No UPDATE or DELETE is ever permitted on this table.
    """
    __tablename__ = 'price_histories'
    __table_args__ = (
        Index('ix_price_hist_prod_branch_ver', 'product_id', 'branch_id', 'version'),
    )
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id = Column(String(36), ForeignKey('organizations.id'), nullable=False)
    price_id = Column(String(36), ForeignKey('prices.id'), nullable=False)
    product_id = Column(String(36), ForeignKey('products.id'), nullable=False)
    branch_id = Column(String(36), ForeignKey('branches.id'), nullable=True)
    old_price = Column(Numeric(12, 2), nullable=True)
    new_price = Column(Numeric(12, 2), nullable=False)
    changed_by_id = Column(String(36), ForeignKey('users.id'), nullable=True)
    change_reason = Column(String, default='')
    version = Column(Integer, nullable=False)
    local_timestamp = Column(String, default=utc_now_iso)
    server_timestamp = Column(String, nullable=True)
    sync_status = Column(String(20), default='PENDING')
    created_at = Column(String, default=utc_now_iso)



class ReceiptSequence(Base):
    """
    Local per-(branch, device, date) receipt counter (Architecture Plan §7.2).
    Guarantees multi-device collision-free receipt numbers `{branch_code}-{device_code}-{YYYYMMDD}-{sequence:06d}`.
    """
    __tablename__ = 'receipt_sequences'
    __table_args__ = (
        UniqueConstraint('branch_id', 'device_id', 'date_str', name='uq_receipt_seq_branch_device_date'),
    )
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    branch_id = Column(String(36), ForeignKey('branches.id'), nullable=False)
    device_id = Column(String(36), ForeignKey('devices.id'), nullable=False)
    date_str = Column(String(8), nullable=False)  # YYYYMMDD
    last_sequence = Column(Integer, default=0, nullable=False)


class Sale(Base):
    __tablename__ = 'sales'
    __table_args__ = (
        UniqueConstraint('branch_id', 'receipt_number', name='uq_sale_branch_receipt'),
        Index('ix_sale_branch_date', 'branch_id', 'sale_date'),
        Index('ix_sale_branch_receipt', 'branch_id', 'receipt_number'),
    )
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id = Column(String(36), ForeignKey('organizations.id'), nullable=False)
    branch_id = Column(String(36), ForeignKey('branches.id'), nullable=False)
    user_id = Column(String(36), nullable=False)
    device_id = Column(String(36), ForeignKey('devices.id'), nullable=False)
    receipt_number = Column(String(50), nullable=False)
    customer_name = Column(String(255), nullable=True)
    customer_phone = Column(String(50), nullable=True)
    subtotal = Column(Numeric(12, 2), nullable=False)
    discount_amount = Column(Numeric(12, 2), default=0, nullable=False)
    tax_amount = Column(Numeric(12, 2), default=0, nullable=False)
    total = Column(Numeric(12, 2), nullable=False)
    status = Column(String(20), default='COMPLETED', nullable=False)
    sale_date = Column(String, nullable=False)
    server_received_at = Column(String, nullable=True)
    is_offline = Column(Boolean, default=True)
    sync_status = Column(String(20), default='PENDING')
    notes = Column(String, default='')
    created_at = Column(String, default=utc_now_iso)
    updated_at = Column(String, default=utc_now_iso, onupdate=utc_now_iso)


class SaleItem(Base):
    """
    Immutable POS sale line item (Architecture Plan §2.3 & §7.3).
    `unit_price` is frozen at add-to-cart time and can never be modified.
    """
    __tablename__ = 'sale_items'
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    sale_id = Column(String(36), ForeignKey('sales.id'), nullable=False)
    product_id = Column(String(36), ForeignKey('products.id'), nullable=False)
    batch_id = Column(String(36), ForeignKey('batches.id'), nullable=False)
    quantity = Column(Integer, nullable=False)
    unit_price = Column(Numeric(12, 2), nullable=False)
    discount_amount = Column(Numeric(12, 2), default=0, nullable=False)
    line_total = Column(Numeric(12, 2), nullable=False)
    created_at = Column(String, default=utc_now_iso)


class Payment(Base):
    __tablename__ = 'payments'
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    sale_id = Column(String(36), ForeignKey('sales.id'), nullable=False)
    payment_method = Column(String(50), nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)
    reference = Column(String(100), nullable=True)
    created_at = Column(String, default=utc_now_iso)


class Receipt(Base):
    __tablename__ = 'receipts'
    __table_args__ = (
        UniqueConstraint('sale_id', name='uq_receipt_sale'),
    )
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    sale_id = Column(String(36), ForeignKey('sales.id'), nullable=False)
    receipt_number = Column(String(50), nullable=False)
    printed_at = Column(String, nullable=False)
    printer_name = Column(String(100), nullable=True)
    reprint_count = Column(Integer, default=0, nullable=False)
    created_at = Column(String, default=utc_now_iso)


class SaleReturn(Base):
    __tablename__ = 'sale_returns'
    __table_args__ = (
        Index('ix_sale_return_branch_date', 'branch_id', 'return_date'),
        Index('ix_sale_return_original_sale', 'original_sale_id'),
    )
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id = Column(String(36), ForeignKey('organizations.id'), nullable=False)
    branch_id = Column(String(36), ForeignKey('branches.id'), nullable=False)
    original_sale_id = Column(String(36), ForeignKey('sales.id'), nullable=False)
    user_id = Column(String(36), nullable=False)
    device_id = Column(String(36), ForeignKey('devices.id'), nullable=False)
    return_receipt_number = Column(String(50), nullable=False)
    reason = Column(String, nullable=False)
    refund_amount = Column(Numeric(12, 2), nullable=False)
    return_date = Column(String, nullable=False)
    server_received_at = Column(String, nullable=True)
    is_offline = Column(Boolean, default=True)
    sync_status = Column(String(20), default='PENDING')
    created_at = Column(String, default=utc_now_iso)


class SaleReturnItem(Base):
    __tablename__ = 'sale_return_items'
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    sale_return_id = Column(String(36), ForeignKey('sale_returns.id'), nullable=False)
    sale_item_id = Column(String(36), ForeignKey('sale_items.id'), nullable=False)
    batch_id = Column(String(36), ForeignKey('batches.id'), nullable=False)
    quantity = Column(Integer, nullable=False)
    refund_amount = Column(Numeric(12, 2), nullable=False)
    created_at = Column(String, default=utc_now_iso)


class Purchase(Base):
    __tablename__ = 'purchases'
    __table_args__ = (
        UniqueConstraint('organization_id', 'purchase_reference', name='uq_purchase_org_ref'),
        Index('ix_purchase_branch_date', 'branch_id', 'purchase_date'),
    )
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id = Column(String(36), ForeignKey('organizations.id'), nullable=False)
    branch_id = Column(String(36), ForeignKey('branches.id'), nullable=False)
    supplier_id = Column(String(36), ForeignKey('suppliers.id'), nullable=False)
    user_id = Column(String(36), nullable=False)
    purchase_reference = Column(String(100), nullable=False)
    invoice_number = Column(String(100), nullable=True)
    purchase_date = Column(String(10), nullable=False)
    subtotal = Column(Numeric(14, 2), default=0, nullable=False)
    discount_amount = Column(Numeric(14, 2), default=0, nullable=False)
    total = Column(Numeric(14, 2), default=0, nullable=False)
    payment_status = Column(String(20), default='UNPAID', nullable=False)
    receiving_status = Column(String(20), default='PENDING', nullable=False)
    notes = Column(String, default='')
    created_at = Column(String, default=utc_now_iso)
    updated_at = Column(String, default=utc_now_iso, onupdate=utc_now_iso)


class PurchaseItem(Base):
    __tablename__ = 'purchase_items'
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    purchase_id = Column(String(36), ForeignKey('purchases.id'), nullable=False)
    product_id = Column(String(36), ForeignKey('products.id'), nullable=False)
    batch_id = Column(String(36), ForeignKey('batches.id'), nullable=True)
    quantity_ordered = Column(Integer, nullable=False)
    quantity_received = Column(Integer, default=0, nullable=False)
    purchase_price = Column(Numeric(12, 2), nullable=False)
    selling_price = Column(Numeric(12, 2), default=0, nullable=False)
    discount = Column(Numeric(12, 2), default=0, nullable=False)
    line_total = Column(Numeric(14, 2), nullable=False)
    created_at = Column(String, default=utc_now_iso)
    updated_at = Column(String, default=utc_now_iso, onupdate=utc_now_iso)


class PurchasePayment(Base):
    __tablename__ = 'purchase_payments'
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    purchase_id = Column(String(36), ForeignKey('purchases.id'), nullable=False)
    payment_method = Column(String(50), nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)
    reference = Column(String(100), nullable=True)
    payment_date = Column(String(10), nullable=False)
    created_at = Column(String, default=utc_now_iso)


class StockCount(Base):
    __tablename__ = 'stock_counts'
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id = Column(String(36), ForeignKey('organizations.id'), nullable=False)
    branch_id = Column(String(36), ForeignKey('branches.id'), nullable=False)
    device_id = Column(String(36), ForeignKey('devices.id'), nullable=True)
    storage_location_id = Column(String(36), ForeignKey('storage_locations.id'), nullable=True)
    count_type = Column(String(30), default='FULL_BRANCH', nullable=False)
    status = Column(String(20), default='DRAFT', nullable=False)
    started_by_id = Column(String(36), nullable=False)
    started_at = Column(String, nullable=False)
    submitted_by_id = Column(String(36), nullable=True)
    submitted_at = Column(String, nullable=True)
    approved_by_id = Column(String(36), nullable=True)
    approved_at = Column(String, nullable=True)
    notes = Column(String, default='')
    created_at = Column(String, default=utc_now_iso)
    updated_at = Column(String, default=utc_now_iso, onupdate=utc_now_iso)


class StockCountItem(Base):
    __tablename__ = 'stock_count_items'
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    stock_count_id = Column(String(36), ForeignKey('stock_counts.id'), nullable=False)
    product_id = Column(String(36), ForeignKey('products.id'), nullable=False)
    batch_id = Column(String(36), ForeignKey('batches.id'), nullable=False)
    storage_location_id = Column(String(36), ForeignKey('storage_locations.id'), nullable=True)
    system_quantity = Column(Integer, nullable=False)
    counted_quantity = Column(Integer, nullable=False)
    variance = Column(Integer, nullable=False)
    current_quantity_at_approval = Column(Integer, nullable=True)
    approval_status = Column(String(20), default='PENDING', nullable=False)
    rejection_reason = Column(String, default='')
    created_at = Column(String, default=utc_now_iso)
    updated_at = Column(String, default=utc_now_iso, onupdate=utc_now_iso)


class StockTransfer(Base):
    __tablename__ = 'stock_transfers'
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id = Column(String(36), ForeignKey('organizations.id'), nullable=False)
    source_branch_id = Column(String(36), ForeignKey('branches.id'), nullable=False)
    destination_branch_id = Column(String(36), ForeignKey('branches.id'), nullable=False)
    status = Column(String(20), default='REQUESTED', nullable=False)
    requested_by_id = Column(String(36), ForeignKey('users.id'), nullable=False)
    approved_by_id = Column(String(36), ForeignKey('users.id'), nullable=True)
    dispatched_by_id = Column(String(36), ForeignKey('users.id'), nullable=True)
    received_by_id = Column(String(36), ForeignKey('users.id'), nullable=True)
    requested_at = Column(String, default=utc_now_iso)
    approved_at = Column(String, nullable=True)
    dispatched_at = Column(String, nullable=True)
    received_at = Column(String, nullable=True)
    notes = Column(String, default='')
    created_at = Column(String, default=utc_now_iso)
    updated_at = Column(String, default=utc_now_iso, onupdate=utc_now_iso)


class StockTransferItem(Base):
    __tablename__ = 'stock_transfer_items'
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    stock_transfer_id = Column(String(36), ForeignKey('stock_transfers.id'), nullable=False)
    product_id = Column(String(36), ForeignKey('products.id'), nullable=False)
    batch_id = Column(String(36), ForeignKey('batches.id'), nullable=False)
    quantity = Column(Integer, nullable=False)
    created_at = Column(String, default=utc_now_iso)
    updated_at = Column(String, default=utc_now_iso, onupdate=utc_now_iso)


class ExpenseCategory(Base):
    __tablename__ = 'expense_categories'
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id = Column(String(36), ForeignKey('organizations.id'), nullable=False)
    name = Column(String(100), nullable=False)
    description = Column(String, default='')
    is_active = Column(Boolean, default=True)
    created_at = Column(String, default=utc_now_iso)
    updated_at = Column(String, default=utc_now_iso, onupdate=utc_now_iso)


class Expense(Base):
    __tablename__ = 'expenses'
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id = Column(String(36), ForeignKey('organizations.id'), nullable=False)
    branch_id = Column(String(36), ForeignKey('branches.id'), nullable=False)
    expense_category_id = Column(String(36), ForeignKey('expense_categories.id'), nullable=False)
    description = Column(String, nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)
    payment_method = Column(String(50), default='CASH')
    expense_date = Column(String(10), nullable=False)
    created_by_id = Column(String(36), ForeignKey('users.id'), nullable=False)
    approved_by_id = Column(String(36), ForeignKey('users.id'), nullable=True)
    status = Column(String(20), default='PENDING_APPROVAL', nullable=False)
    attachment_path = Column(String(500), nullable=True)
    notes = Column(String, default='')
    created_at = Column(String, default=utc_now_iso)
    updated_at = Column(String, default=utc_now_iso, onupdate=utc_now_iso)


class LicenseState(Base):
    """
    Cached subscription & license state on desktop (Architecture Plan §14).
    Controls local write permissions, grace period enforcement, and read-only mode.
    """
    __tablename__ = 'license_states'
    organization_id = Column(String(36), primary_key=True)
    status = Column(String(20), default='ACTIVE', nullable=False)
    plan = Column(String(50), default='professional', nullable=False)
    current_period_end = Column(String, nullable=True)
    grace_period_days = Column(Integer, default=14, nullable=False)
    entitlements = Column(String, default='{}')  # JSON text
    last_checked_at = Column(String, nullable=True)
    updated_at = Column(String, default=utc_now_iso, onupdate=utc_now_iso)


class InventoryAlert(Base):
    """
    Local copy of inventory anomalies / reconciliation mismatches (Architecture Plan §3.3).
    """
    __tablename__ = 'inventory_alerts'
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id = Column(String(36), ForeignKey('organizations.id'), nullable=False)
    branch_id = Column(String(36), ForeignKey('branches.id'), nullable=False)
    batch_id = Column(String(36), ForeignKey('batches.id'), nullable=False)
    alert_type = Column(String(30), nullable=False)
    details = Column(String, default='{}')  # JSON text
    is_resolved = Column(Boolean, default=False, nullable=False)
    resolved_by_id = Column(String(36), nullable=True)
    resolved_at = Column(String, nullable=True)
    created_at = Column(String, default=utc_now_iso)






