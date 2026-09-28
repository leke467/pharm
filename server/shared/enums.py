"""
Pharmacy Management System — Shared Enums

Canonical definitions of all enum/status values used across the system.
Both the Django server and the PySide6 desktop app import from this module.
"""

from enum import StrEnum


# =============================================================================
# Inventory Movement Types
# =============================================================================

class MovementType(StrEnum):
    """Types of inventory movements in the movement ledger."""
    STOCK_RECEIVED = "STOCK_RECEIVED"
    SALE = "SALE"
    SALE_RETURN = "SALE_RETURN"
    STOCK_TRANSFER_OUT = "STOCK_TRANSFER_OUT"
    STOCK_TRANSFER_IN = "STOCK_TRANSFER_IN"
    STOCK_ADJUSTMENT = "STOCK_ADJUSTMENT"
    DAMAGE = "DAMAGE"
    EXPIRY = "EXPIRY"
    COUNT_VARIANCE = "COUNT_VARIANCE"
    OPENING_BALANCE = "OPENING_BALANCE"


# =============================================================================
# Batch Statuses
# =============================================================================

class BatchStatus(StrEnum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    RECALLED = "RECALLED"
    DEPLETED = "DEPLETED"


# =============================================================================
# Branch Inventory Statuses
# =============================================================================

class InventoryStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    DEPLETED = "DEPLETED"
    QUARANTINED = "QUARANTINED"


# =============================================================================
# Sale Statuses
# =============================================================================

class SaleStatus(StrEnum):
    COMPLETED = "COMPLETED"
    RETURNED = "RETURNED"
    PARTIALLY_RETURNED = "PARTIALLY_RETURNED"
    VOIDED = "VOIDED"
    CANCELLED = "CANCELLED"


# =============================================================================
# Sale Return Statuses
# =============================================================================

class SaleReturnStatus(StrEnum):
    COMPLETED = "COMPLETED"
    PENDING_APPROVAL = "PENDING_APPROVAL"


# =============================================================================
# Purchase Payment Statuses
# =============================================================================

class PaymentStatus(StrEnum):
    UNPAID = "UNPAID"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"


# =============================================================================
# Purchase Receiving Statuses
# =============================================================================

class ReceivingStatus(StrEnum):
    PENDING = "PENDING"
    PARTIALLY_RECEIVED = "PARTIALLY_RECEIVED"
    RECEIVED = "RECEIVED"


# =============================================================================
# Stock Count Statuses
# =============================================================================

class StockCountStatus(StrEnum):
    DRAFT = "DRAFT"
    IN_PROGRESS = "IN_PROGRESS"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    PARTIALLY_APPROVED = "PARTIALLY_APPROVED"
    REJECTED = "REJECTED"
    CONFLICT = "CONFLICT"


# =============================================================================
# Stock Count Item Approval Statuses
# =============================================================================

class ApprovalStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


# =============================================================================
# Stock Count Types
# =============================================================================

class StockCountType(StrEnum):
    FULL_BRANCH = "FULL_BRANCH"
    STORAGE_LOCATION = "STORAGE_LOCATION"
    CATEGORY = "CATEGORY"
    SELECTED_PRODUCTS = "SELECTED_PRODUCTS"


# =============================================================================
# Stock Transfer Statuses
# =============================================================================

class TransferStatus(StrEnum):
    DRAFT = "DRAFT"
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DISPATCHED = "DISPATCHED"
    IN_TRANSIT = "IN_TRANSIT"
    RECEIVED = "RECEIVED"
    CANCELLED = "CANCELLED"


# =============================================================================
# Expense Statuses
# =============================================================================

class ExpenseStatus(StrEnum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


# =============================================================================
# Sync Event Statuses
# =============================================================================

class SyncEventStatus(StrEnum):
    PENDING = "PENDING"
    SENDING = "SENDING"
    SENT = "SENT"
    FAILED = "FAILED"
    CONFLICT = "CONFLICT"
    RESOLVED = "RESOLVED"


# =============================================================================
# Sync Event Operations
# =============================================================================

class SyncOperation(StrEnum):
    CREATE = "CREATE"
    UPDATE = "UPDATE"


# =============================================================================
# Sync Delivery Target Scopes
# =============================================================================

class SyncTargetScope(StrEnum):
    ALL_BRANCHES = "ALL_BRANCHES"
    SPECIFIC_BRANCH = "SPECIFIC_BRANCH"
    ORGANIZATION = "ORGANIZATION"


# =============================================================================
# License Statuses
# =============================================================================

class LicenseStatus(StrEnum):
    TRIAL = "TRIAL"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    SUSPENDED = "SUSPENDED"
    CANCELLED = "CANCELLED"


# =============================================================================
# Subscription Statuses
# =============================================================================

class SubscriptionStatus(StrEnum):
    ACTIVE = "ACTIVE"
    PAST_DUE = "PAST_DUE"
    SUSPENDED = "SUSPENDED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


# =============================================================================
# Audit Event Sources
# =============================================================================

class AuditSource(StrEnum):
    DESKTOP = "DESKTOP"
    SERVER = "SERVER"
    SERVER_SYNC = "SERVER_SYNC"
    API = "API"


# =============================================================================
# Audit Action Types
# =============================================================================

class AuditAction(StrEnum):
    # Sales
    SALE_CREATED = "SALE_CREATED"
    SALE_VOIDED = "SALE_VOIDED"
    SALE_RETURNED = "SALE_RETURNED"
    # Products
    PRODUCT_CREATED = "PRODUCT_CREATED"
    PRODUCT_UPDATED = "PRODUCT_UPDATED"
    # Batches
    BATCH_CREATED = "BATCH_CREATED"
    BATCH_RECALLED = "BATCH_RECALLED"
    # Pricing
    PRICE_CHANGED = "PRICE_CHANGED"
    # Stock
    STOCK_RECEIVED = "STOCK_RECEIVED"
    STOCK_ADJUSTED = "STOCK_ADJUSTED"
    INVENTORY_ADJUSTED = "INVENTORY_ADJUSTED"
    # Stock Counts
    STOCK_COUNT_STARTED = "STOCK_COUNT_STARTED"
    STOCK_COUNT_SUBMITTED = "STOCK_COUNT_SUBMITTED"
    STOCK_COUNT_APPROVED = "STOCK_COUNT_APPROVED"
    STOCK_COUNT_REJECTED = "STOCK_COUNT_REJECTED"
    # Transfers
    TRANSFER_REQUESTED = "TRANSFER_REQUESTED"
    TRANSFER_APPROVED = "TRANSFER_APPROVED"
    TRANSFER_DISPATCHED = "TRANSFER_DISPATCHED"
    TRANSFER_RECEIVED = "TRANSFER_RECEIVED"
    TRANSFER_CANCELLED = "TRANSFER_CANCELLED"
    # Auth
    USER_LOGIN = "USER_LOGIN"
    USER_LOGOUT = "USER_LOGOUT"
    # Permissions
    PERMISSION_CHANGED = "PERMISSION_CHANGED"
    # Expenses
    EXPENSE_CREATED = "EXPENSE_CREATED"
    EXPENSE_APPROVED = "EXPENSE_APPROVED"
    EXPENSE_REJECTED = "EXPENSE_REJECTED"
    # Settings
    SETTINGS_CHANGED = "SETTINGS_CHANGED"
    # Security flags (server-generated)
    DISABLED_USER_ACTION = "DISABLED_USER_ACTION"
    UNAUTHORIZED_OFFLINE_ACTION = "UNAUTHORIZED_OFFLINE_ACTION"


# =============================================================================
# Inventory Alert Types
# =============================================================================

class InventoryAlertType(StrEnum):
    OVERSOLD = "OVERSOLD"
    RECONCILIATION_MISMATCH = "RECONCILIATION_MISMATCH"
    NEGATIVE_STOCK = "NEGATIVE_STOCK"


# =============================================================================
# Permission Codes (Seed Data)
# =============================================================================

class PermissionCode(StrEnum):
    """
    Canonical permission codes. These are seed data, not hard-coded restrictions.
    Organizations can create custom roles with any combination of these.
    """
    DASHBOARD_VIEW = "dashboard.view"
    PRODUCTS_VIEW = "products.view"
    PRODUCTS_CREATE = "products.create"
    PRODUCTS_EDIT = "products.edit"
    PRODUCTS_DELETE = "products.delete"
    BATCHES_MANAGE = "batches.manage"
    INVENTORY_VIEW = "inventory.view"
    INVENTORY_ADJUST = "inventory.adjust"
    SALES_SELL = "sales.sell"
    SALES_VOID = "sales.void"
    SALES_RETURN = "sales.return"
    PRICES_VIEW = "prices.view"
    PRICES_MANAGE = "prices.manage"
    STOCK_RECEIVE = "stock.receive"
    STOCK_TRANSFER = "stock.transfer"
    STOCK_COUNTS_PERFORM = "stock_counts.perform"
    STOCK_COUNTS_APPROVE = "stock_counts.approve"
    SUPPLIERS_MANAGE = "suppliers.manage"
    EXPENSES_CREATE = "expenses.create"
    EXPENSES_APPROVE = "expenses.approve"
    REPORTS_VIEW = "reports.view"
    USERS_MANAGE = "users.manage"
    BRANCHES_MANAGE = "branches.manage"
    SETTINGS_MANAGE = "settings.manage"
    AUDIT_VIEW = "audit.view"
    SUBSCRIPTIONS_MANAGE = "subscriptions.manage"


# =============================================================================
# Sync Entity Dependency Levels (for upload ordering)
# =============================================================================

SYNC_DEPENDENCY_LEVELS: dict[str, int] = {
    # Level 1: Reference/master data
    "organization": 1,
    "branch": 1,
    "device": 1,
    "user": 1,
    "role": 1,
    "permission": 1,
    "role_permission": 1,
    "user_role": 1,
    # Level 2: Product catalog
    "product": 2,
    "category": 2,
    "product_type": 2,
    "manufacturer": 2,
    "supplier": 2,
    "product_branch": 2,
    "product_document": 2,
    # Level 3: Batches
    "batch": 3,
    # Level 4: Inventory state, Pricing
    "branch_inventory": 4,
    "storage_location": 4,
    "storage_location_assignment": 4,
    "price": 4,
    # Level 5: Transactions
    "sale": 5,
    "purchase": 5,
    "stock_count": 5,
    "stock_transfer": 5,
    "expense": 5,
    "expense_category": 5,
    "sale_return": 5,
    # Level 6: Line items
    "sale_item": 6,
    "purchase_item": 6,
    "stock_count_item": 6,
    "stock_transfer_item": 6,
    "payment": 6,
    "purchase_payment": 6,
    "sale_return_item": 6,
    "receipt": 6,
    "price_history": 6,
    # Level 7: Movements
    "inventory_movement": 7,
    # Level 8: Audit
    "audit_event": 8,
}

# =============================================================================
# Sync Schema Version
# =============================================================================

SYNC_SCHEMA_VERSION = 1
