from django.db import transaction
from shared.enums import PermissionCode
from .models import Permission, Role, RolePermission


CANONICAL_PERMISSIONS = [
    (PermissionCode.PRODUCTS_VIEW, "View Products", "Products"),
    (PermissionCode.PRODUCTS_CREATE, "Create Products", "Products"),
    (PermissionCode.PRODUCTS_EDIT, "Edit Products", "Products"),
    (PermissionCode.PRODUCTS_DELETE, "Delete Products", "Products"),
    (PermissionCode.BATCHES_MANAGE, "Manage Batches", "Batches"),
    (PermissionCode.INVENTORY_VIEW, "View Inventory", "Inventory"),
    (PermissionCode.INVENTORY_ADJUST, "Adjust Inventory", "Inventory"),
    (PermissionCode.SALES_SELL, "Perform Sales (POS)", "Sales"),
    (PermissionCode.SALES_VOID, "Void Sales", "Sales"),
    (PermissionCode.SALES_RETURN, "Process Sale Returns", "Sales"),
    (PermissionCode.PRICES_VIEW, "View Prices", "Pricing"),
    (PermissionCode.PRICES_MANAGE, "Manage Prices", "Pricing"),
    (PermissionCode.STOCK_RECEIVE, "Receive Stock", "Stock"),
    (PermissionCode.STOCK_TRANSFER, "Transfer Stock", "Stock"),
    (PermissionCode.STOCK_COUNTS_PERFORM, "Perform Stock Counts", "Stock Counts"),
    (PermissionCode.STOCK_COUNTS_APPROVE, "Approve Stock Counts", "Stock Counts"),
    (PermissionCode.SUPPLIERS_MANAGE, "Manage Suppliers", "Suppliers"),
    (PermissionCode.EXPENSES_CREATE, "Create Expenses", "Expenses"),
    (PermissionCode.EXPENSES_APPROVE, "Approve Expenses", "Expenses"),
    (PermissionCode.REPORTS_VIEW, "View Reports", "Reports"),
    (PermissionCode.USERS_MANAGE, "Manage Users & Roles", "Users"),
    (PermissionCode.BRANCHES_MANAGE, "Manage Branches & Devices", "Branches"),
    (PermissionCode.SETTINGS_MANAGE, "Manage Settings", "Settings"),
    (PermissionCode.AUDIT_VIEW, "View Audit Trail", "Audit"),
    (PermissionCode.SUBSCRIPTIONS_MANAGE, "Manage Subscriptions", "Subscriptions"),
]

DEFAULT_SYSTEM_ROLES = {
    "Organization Admin": [p[0].value for p in CANONICAL_PERMISSIONS],
    "Branch Manager": [
        PermissionCode.PRODUCTS_VIEW.value,
        PermissionCode.PRODUCTS_CREATE.value,
        PermissionCode.PRODUCTS_EDIT.value,
        PermissionCode.BATCHES_MANAGE.value,
        PermissionCode.INVENTORY_VIEW.value,
        PermissionCode.INVENTORY_ADJUST.value,
        PermissionCode.SALES_SELL.value,
        PermissionCode.SALES_VOID.value,
        PermissionCode.SALES_RETURN.value,
        PermissionCode.PRICES_VIEW.value,
        PermissionCode.PRICES_MANAGE.value,
        PermissionCode.STOCK_RECEIVE.value,
        PermissionCode.STOCK_TRANSFER.value,
        PermissionCode.STOCK_COUNTS_PERFORM.value,
        PermissionCode.STOCK_COUNTS_APPROVE.value,
        PermissionCode.SUPPLIERS_MANAGE.value,
        PermissionCode.EXPENSES_CREATE.value,
        PermissionCode.EXPENSES_APPROVE.value,
        PermissionCode.REPORTS_VIEW.value,
        PermissionCode.USERS_MANAGE.value,
        PermissionCode.AUDIT_VIEW.value,
    ],
    "Pharmacist": [
        PermissionCode.PRODUCTS_VIEW.value,
        PermissionCode.PRODUCTS_CREATE.value,
        PermissionCode.PRODUCTS_EDIT.value,
        PermissionCode.BATCHES_MANAGE.value,
        PermissionCode.INVENTORY_VIEW.value,
        PermissionCode.SALES_SELL.value,
        PermissionCode.SALES_RETURN.value,
        PermissionCode.PRICES_VIEW.value,
        PermissionCode.STOCK_RECEIVE.value,
        PermissionCode.STOCK_COUNTS_PERFORM.value,
    ],
    "Cashier": [
        PermissionCode.PRODUCTS_VIEW.value,
        PermissionCode.INVENTORY_VIEW.value,
        PermissionCode.SALES_SELL.value,
        PermissionCode.PRICES_VIEW.value,
    ],
    "Storekeeper": [
        PermissionCode.PRODUCTS_VIEW.value,
        PermissionCode.BATCHES_MANAGE.value,
        PermissionCode.INVENTORY_VIEW.value,
        PermissionCode.STOCK_RECEIVE.value,
        PermissionCode.STOCK_TRANSFER.value,
        PermissionCode.STOCK_COUNTS_PERFORM.value,
        PermissionCode.SUPPLIERS_MANAGE.value,
    ],
    "Auditor": [
        PermissionCode.PRODUCTS_VIEW.value,
        PermissionCode.INVENTORY_VIEW.value,
        PermissionCode.PRICES_VIEW.value,
        PermissionCode.REPORTS_VIEW.value,
        PermissionCode.AUDIT_VIEW.value,
    ],
}


@transaction.atomic
def seed_permissions_and_roles(organization=None):
    """
    Idempotently seed all 25 canonical permissions and optionally create
    default system roles for the given organization.
    """
    perm_map = {}
    for code_enum, name, category in CANONICAL_PERMISSIONS:
        code = code_enum.value if hasattr(code_enum, 'value') else str(code_enum)
        perm, _ = Permission.objects.update_or_create(
            code=code,
            defaults={"name": name, "category": category},
        )
        perm_map[code] = perm

    created_roles = {}
    if organization is not None:
        for role_name, perm_codes in DEFAULT_SYSTEM_ROLES.items():
            role, _ = Role.objects.get_or_create(
                organization=organization,
                name=role_name,
                defaults={
                    "description": f"Default {role_name} role",
                    "is_system": True,
                },
            )
            for code in perm_codes:
                perm = perm_map.get(code)
                if perm:
                    RolePermission.objects.get_or_create(role=role, permission=perm)
            created_roles[role_name] = role

    return perm_map, created_roles
