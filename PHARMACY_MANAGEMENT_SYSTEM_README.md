# Pharmacy Management System — Product Requirements & Technical Specification

## 1. Purpose

Build a **commercial, production-ready pharmacy management system** for pharmacies operating one or more branches.

This is not a school/demo application. The system must be designed for real pharmacy operations, including sales, inventory, purchasing, batches, staff, stock counts, expenses, reporting, auditing, offline operation, and synchronization.

The first known customer has **5 branches**, but **do not hard-code 5 branches anywhere**. The architecture must support any practical number of branches.

The first known customer also uses shelves/storage locations with staff responsibility and monthly stock counting. However, **shelf/storage-location management must be optional and configurable per branch**, because not every pharmacy will use shelves in the same way.

The commercial product should support a **2-month trial followed by monthly subscription**.

---

# 2. Core Product Principles

The system must be:

- **OFFLINE-FIRST**
- **MULTI-BRANCH**
- **AUDITABLE**
- **SYNCHRONIZED**
- **CONFIGURABLE**
- **ROLE-BASED**
- **BATCH-AWARE**
- **INVENTORY-SAFE**
- **PROFESSIONAL**
- **MAINTAINABLE**

Do not sacrifice data integrity for a quick implementation.

---

# 3. Required Architecture

## 3.1 Desktop Application

The pharmacy branch application should use:

- Python
- PySide6
- Qt Designer where useful
- Qt Model/View for data-heavy screens
- requests/httpx for API communication
- SQLite for local/offline persistence
- SQLAlchemy or another structured SQLite persistence layer
- PyInstaller for packaging
- Inno Setup for Windows installation

The desktop application must remain useful during Internet outages.

Normal pharmacy operations must not stop merely because the Internet is unavailable.

## 3.2 Central Server

The central backend should use:

- Python
- Django
- Django REST Framework
- PostgreSQL
- HTTPS
- Appropriate token/session authentication for the desktop application

The central server is responsible for organization-level data, synchronization, centralized administration, subscriptions/licenses, reporting where appropriate, and server-side validation.

## 3.3 Multi-Tenant Structure

Design for:

```text
Organization
    ├── Branch
    │   ├── Devices
    │   ├── Users
    │   ├── Products/Inventory
    │   └── Transactions
    └── Organization-level configuration
```

Do not build the system around one pharmacy.

---

# 4. Identity, Branch Context and Users

A user identity is separate from the user's current branch.

The same administrator account may operate in different branches on different days.

Therefore, do not assume:

```text
User = permanently attached to one Branch
```

Every relevant transaction should record:

- User
- Branch
- Device
- Local date/time
- UTC/server time where available
- Offline/online context

The system must always know the branch context in which an action occurred.

---

# 5. Roles and Permissions

Use individual staff accounts.

Do not create one shared account such as `cashier`.

The system needs granular role/permission control.

Suggested roles include:

- Super Admin
- Organization Admin
- Branch Manager
- Pharmacist
- Sales Staff
- Store/Inventory Staff
- Auditor
- Accountant
- Custom Role

The actual role system must be configurable rather than permanently hard-coded.

Permissions should cover areas such as:

- View products
- Create/edit products
- Manage batches
- View inventory
- Adjust inventory
- Sell products
- Process returns
- Manage prices
- Receive stock
- Transfer stock
- Perform stock counts
- Approve stock-count variances
- Manage suppliers
- Manage expenses
- View reports
- Manage users
- Manage branches
- Manage settings
- View audit logs
- Manage subscriptions/licenses

Permissions must be enforced in both:

1. UI
2. Backend/API

Hiding a button is not a security control.

---

# 6. Product Management

Use the terminology **Product**, not only "Drug".

A pharmacy may sell:

- Medicines
- Supplements
- Cosmetics
- Personal care products
- Medical devices
- Baby products
- Other pharmacy products

## 6.1 Product Stable Data

Product-level data should include:

- Product ID
- SKU/product code
- Barcode
- Product name
- Generic name
- Brand name
- Category
- Product type

Optional pharmaceutical information:

- Active ingredients
- Strength
- Dosage form
- Route
- Formulation
- Indication
- Contraindications
- Precautions
- Drug interactions
- Side effects
- Storage conditions
- Age suitability
- Pregnancy caution
- Prescription required
- Controlled/restricted status

Manufacturer/importer/regulatory information may include:

- Manufacturer
- Importer
- Regulatory fields
- Product registration information where required

Additional fields:

- Description
- Product image
- Documents
- Notes

Do not put batch-specific information directly into the permanent Product record.

---

# 7. Product and Branch Relationship

A Product must not be duplicated simply because it exists in another branch.

Use a relationship such as:

```text
Product
   |
   +---- ProductBranch ---- Branch
```

ProductBranch should control whether the product is available/active in a branch and may hold branch-specific configuration.

Do not create:

```text
Paracetamol Branch 1
Paracetamol Branch 2
Paracetamol Branch 3
```

as separate Product records.

---

# 8. Batch Management

Batch information must be separate from Product information.

A Batch should include:

- Batch ID
- Product ID
- Batch number
- Manufacturing date
- Expiry date
- Purchase price
- Supplier
- Invoice/reference
- Received date
- Regulatory metadata where applicable
- Status
- Notes

Manufacturing date, expiry date and purchase price belong to the **batch**, not the stable Product record.

A single product may have many batches.

---

# 9. Branch Inventory

Do not store one global quantity for a Product.

Inventory belongs to a branch and batch.

Conceptually:

```text
Branch
   |
   +--- BranchInventory --- Batch --- Product
```

Inventory should support:

- Branch
- Batch
- Optional StorageLocation
- Quantity
- Reserved quantity
- Available quantity
- Reorder level
- Last updated
- Status

This allows the same product/batch to exist independently in multiple branches.

---

# 10. Storage Locations / Shelves

Storage locations must be a generalized concept.

Examples:

- Shelf 1
- Shelf 2
- Main Store
- Refrigerator
- Controlled Drug Cabinet
- Cosmetics Section
- Warehouse
- Counter

Do not hard-code "Shelf 1–5".

A pharmacy may have:

- 0 shelves
- 5 shelves
- 20 shelves
- Other storage locations

Storage-location management should therefore be configurable per branch.

---

# 11. Staff-to-Shelf / Storage Assignment

Where a branch uses staff responsibility for storage locations, use an assignment entity rather than adding a permanent `shelf_id` to the User.

An assignment should include:

- Branch
- Storage location
- User
- Start date
- End date
- Active status
- Assigned by
- Created timestamp
- Updated timestamp

The design should allow more than one staff member where the business requires it.

Do not assume that every staff member owns exactly one shelf.

---

# 12. Monthly Stock Counts

The first known pharmacy uses monthly stock counting, but the system must support configurable stock-count workflows.

A stock count can cover:

- Entire branch
- Specific shelf/storage location
- Selected products
- Selected categories
- Selected batches

Stock count items should record:

- Product
- Batch
- Storage location where applicable
- System quantity
- Physical quantity
- Variance
- Notes
- Counted by
- Count date/time

## Critical rule

A stock count must **not silently overwrite inventory**.

If physical count differs from system quantity:

```text
System Quantity
       ↓
Physical Count
       ↓
Variance
       ↓
Pending Approval
       ↓
Authorized Manager Approval/Rejection
       ↓
Inventory Adjustment
```

The approval/rejection and adjustment must be auditable.

---

# 13. Inventory Movement/Event Model

Inventory changes should be represented as movements/events.

Examples:

- STOCK_RECEIVED
- SALE
- SALE_RETURN
- STOCK_TRANSFER_OUT
- STOCK_TRANSFER_IN
- STOCK_ADJUSTMENT
- DAMAGE
- EXPIRY
- COUNT_VARIANCE
- OPENING_BALANCE

This event-oriented approach is especially important for offline synchronization.

Do not rely on blindly replacing a quantity value during synchronization.

---

# 14. Sales / POS

The POS must be designed for real pharmacy operation.

A Sale should include:

- Sale ID
- Branch
- User
- Device
- Date/time
- Customer if desired/configured
- Payment method
- Subtotal
- Discount
- Tax if configured
- Total
- Status
- Receipt number
- Sync state

Sale items should include:

- Product
- Batch
- Quantity
- Unit selling price
- Discount
- Line total

The system must support barcode scanning and fast product search.

Search should support:

- Product name
- Generic name
- Brand
- SKU
- Barcode
- Batch
- Category
- Manufacturer

Barcode scanning should be a high-priority POS workflow.

---

# 15. Batch Selection for Sales

Batch selection should support:

- FEFO
- FIFO
- Manual selection

FEFO should be the preferred default where appropriate because products with earlier expiry should normally be sold first.

The system must detect:

- Expired batches
- Near-expiry batches
- Unavailable batches
- Insufficient stock

Do not allow expired stock to be sold unless an explicit authorized business rule permits it.

---

# 16. Pricing

Price management must support controlled price changes.

Use price configuration/history rather than overwriting historical sale information.

Price history should record:

- Old price
- New price
- User/admin who changed it
- Branch context
- Timestamp
- Version
- Sync status
- Affected branches

When a central administrator changes a price:

1. The change is recorded centrally.
2. It is synchronized to branches.
3. Each branch records when the change was received/applied.
4. Historical sales retain their original prices.

Offline price changes require explicit conflict rules.

Recommended rule:

- Ordinary branch staff cannot change prices.
- Authorized administrators can change prices.
- Branches use the latest cached valid price while offline.
- Conflicts must be handled explicitly rather than silently overwritten.

---

# 17. Purchasing and Receiving

Purchasing/receiving should support:

- Supplier
- Branch
- Purchase reference
- Invoice
- Date
- User
- Products
- Batches
- Quantities
- Purchase prices
- Selling prices
- Discounts
- Totals
- Payment/received status

Receiving stock must create inventory movements.

---

# 18. Suppliers

Supplier management should include appropriate supplier information and allow suppliers to be linked to purchases/batches.

The system should retain historical supplier relationships for traceability.

---

# 19. Stock Transfers Between Branches

Support branch-to-branch stock transfers.

Suggested statuses:

```text
Draft
Requested
Approved
Dispatched
In Transit
Received
Cancelled
```

Transfers must create appropriate inventory movements.

Do not simply edit branch quantities without a traceable transfer record.

---

# 20. Returns, Refunds and Voids

Never delete a completed sale to handle a return.

Preserve the original sale.

Use reversal/return records and inventory movements.

Possible sale statuses:

- Completed
- Returned
- Partially Returned
- Voided
- Cancelled

Returns should identify the original transaction and record who processed the return.

---

# 21. Payments

Payment methods should be configurable.

Examples:

- Cash
- POS
- Bank Transfer
- Card
- Other

A sale should retain its payment information.

---

# 22. Receipts

Support common thermal printers:

- 58mm
- 80mm

Receipt configuration should support:

- Pharmacy name
- Branch information
- Receipt number
- Date/time
- Cashier
- Items
- Quantities
- Prices
- Discounts
- Subtotal
- Tax
- Total
- Payment method
- Change
- Footer
- Refund information where applicable

Receipt printing must work while offline.

---

# 23. Receipt Numbering

Receipt numbers must remain unique across branches without requiring an Internet connection.

A practical human-readable approach is similar to:

```text
BR01-20260925-000123
```

The exact format may be configurable.

The underlying transaction should also have a globally unique ID.

Do not depend on a central server to generate every receipt number before a sale can be completed.

---

# 24. Expenses

Expenses should support:

- Branch
- Expense category
- Description
- Amount
- Payment method
- Date/time
- Created by
- Approved by
- Attachment
- Notes
- Status

Expense categories should be configurable.

---

# 25. Audit Trail

The audit system is critical.

Normal users should not be able to casually edit/delete audit history.

An audit event should contain fields such as:

- Audit event ID
- Organization
- Branch
- User
- Device
- Action
- Entity type
- Entity ID
- Local timestamp
- UTC/server timestamp
- Source
- Offline/online state
- Server received timestamp
- Before data
- After data
- Reason
- Correlation ID
- Transaction ID
- Sync ID

The audit system should answer:

- Who did it?
- What did they do?
- When?
- Where/which branch?
- On which device?
- Was the action offline?
- What was the old value?
- What is the new value?
- When did the server receive it?
- Was approval required?
- Who approved it?

---

# 26. Offline-First Operation

Offline operation is a core requirement, not an optional feature.

A branch must continue normal operations during Internet outages.

Examples that must work offline:

- Login using appropriate locally cached credentials/session policy
- Product lookup
- Barcode scanning
- Sales
- Receipt printing
- Inventory updates
- Stock receiving where permitted
- Stock counts
- Expense entry
- Audit event creation

The system must queue synchronization work locally.

---

# 27. Synchronization Architecture

**Do not copy SQLite database files to the server.**

Use event/change-based synchronization.

Each local transaction should:

1. Update the local SQLite database.
2. Create the required inventory/business/audit records.
3. Create a local outbox/sync event.
4. Print the receipt if relevant.
5. Continue operating normally.

When Internet returns:

1. Upload pending events.
2. Download remote changes.
3. Apply remote changes safely.
4. Resolve conflicts according to explicit rules.
5. Mark successful events as synchronized.

Synchronization must be idempotent.

The same event must never create a duplicate sale or duplicate inventory movement if retried.

Use globally unique event IDs.

---

# 28. Local Outbox

The local outbox should include fields such as:

- Event ID
- Branch
- Device
- Entity type
- Entity ID
- Operation
- Payload
- Local created timestamp
- Retry count
- Last attempt
- Status
- Error

Suggested statuses:

- PENDING
- SENDING
- SENT
- FAILED
- CONFLICT
- RESOLVED

Retries should use backoff.

Synchronization must never freeze or block the POS.

---

# 29. Conflict Handling

Do not use blind last-write-wins for important inventory operations.

Inventory changes should be represented as operations/events.

For example, these are separate events:

```text
SALE -5
RECEIPT +20
TRANSFER_OUT -10
TRANSFER_IN +10
DAMAGE -2
```

The server can then reason about the operations instead of guessing which quantity value is "latest".

Conflicts requiring human intervention should be visible and auditable.

---

# 30. Sync Dashboard

The branch application should show synchronization status.

Useful information:

- Online/offline
- Syncing
- Last successful sync
- Pending events
- Failed events
- Conflict count

Staff should be able to understand whether the branch is synchronized without needing technical knowledge.

---

# 31. Dashboard and Reporting

Provide dashboards/reports for:

### Sales

- Revenue by day
- Revenue by week
- Revenue by month
- Revenue by branch
- Revenue by product
- Revenue by category
- Discounts
- Returns
- Payment breakdown
- Top products
- Slow-moving products

### Inventory

- Current stock
- Low stock
- Out of stock
- Near expiry
- Expired stock
- Inventory by branch
- Inventory by storage location
- Inventory by batch
- Stock movement history

Expiry alerts should be configurable, with examples such as:

- 90 days
- 60 days
- 30 days

### Expenses

- Expense totals
- Expense categories
- Branch comparison
- Date-range reports

### Staff/Productivity

Where appropriate and permitted:

- Sales activity
- Transaction counts
- Stock-count activity
- Approved adjustments

Do not expose sensitive staff information to users without the necessary permission.

---

# 32. User Interface Requirements

The application should look like a modern commercial application.

Use:

- Sidebar/navigation
- Dashboard cards
- Tables
- Search
- Filters
- Pagination
- Clear primary actions
- Confirmation dialogs where necessary
- Status badges
- Consistent spacing
- Consistent typography
- Clear empty states
- Useful error messages

Avoid:

- Giant forms
- Tiny text
- Cluttered screens
- Old-looking default Qt widgets
- Excessive modal dialogs
- Random colors
- Inconsistent button placement
- Unnecessary duplication of screens

For large data sets, use Qt Model/View rather than loading everything into a simple widget.

---

# 33. Product Screen Organization

The Product screen can be organized into sections/tabs such as:

1. Basic Information
2. Pharmaceutical Information
3. Safety Information
4. Pricing
5. Batches
6. Branches
7. Storage Locations
8. Documents
9. Audit History

Do not force every product to fill every pharmaceutical field.

A cosmetics product and a prescription medicine should not have identical mandatory data requirements.

---

# 34. Performance Requirements

The system must be designed for:

- Tens of thousands of products
- Large numbers of transactions
- Many batches
- Multiple branches
- Years of sales history
- Large audit history

Use:

- Pagination
- Indexed searches
- Efficient queries
- Caching for read-heavy master data where appropriate
- Incremental synchronization
- Background sync
- Efficient model/view architecture

Do not load an entire multi-year transaction table into memory just to display the first page.

---

# 35. Database Migrations

Both local and central databases need controlled migration strategies.

SQLite migrations must be planned carefully.

Django/PostgreSQL migrations should be used on the server.

Before risky migrations:

- Back up data
- Test migration
- Provide recovery/rollback procedure where possible

Never destroy existing business data simply because a schema has changed.

---

# 36. Backup and Restore

Provide backup/restore procedures.

Backups should be designed around real business data.

The documentation should explain:

- What is backed up
- How often
- Where backups are stored
- How backups are restored
- What happens after device failure
- How local offline data is protected
- How central PostgreSQL backups are handled

Do not treat synchronization as a replacement for backup.

---

# 37. Security

Never commit secrets.

Use configuration/environment variables.

Provide:

```text
.env.example
```

but never commit real credentials.

Separate:

- Development
- Testing
- Staging
- Production

Use HTTPS for server communication.

Apply authentication and authorization at the backend.

Validate input server-side.

Protect sensitive configuration.

---

# 38. Subscription and Licensing

The product should support:

- 2-month trial
- Monthly subscription afterward
- License/subscription status
- Entitlements
- Organization-level subscription
- Branch/device limits if the commercial plan eventually requires them
- Grace/expiry behavior

Do not hard-code one customer's subscription.

Suggested concepts:

```text
License
Subscription
Entitlement
```

The exact billing provider can be integrated later if necessary.

The system should clearly separate product functionality from billing-provider implementation.

---

# 39. Suggested Core Entities

The architecture should consider entities such as:

```text
Organization
Branch
Device
User
Role
Permission
RolePermission
UserRole

Product
Category
ProductType
ProductBranch
ProductDocument
Manufacturer

Supplier
Batch
BranchInventory
StorageLocation
StorageLocationAssignment

InventoryMovement
StockAdjustment
StockTransfer

Sale
SaleItem
SaleReturn
SaleReturnItem
Payment
Receipt

Purchase
PurchaseItem
PurchasePayment
StockReceipt

Expense
ExpenseCategory

StockCount
StockCountItem
StockCountApproval

Price
PriceHistory

AuditEvent
Approval

SyncEvent
SyncCursor
SyncDelivery

License
Subscription
Entitlement

Settings
PrinterConfiguration
```

The exact implementation may add supporting entities where required.

---

# 40. Recommended Relationships

At a high level:

```text
Organization
    |
    +--- Branch
    |      |
    |      +--- Device
    |      +--- Users/roles
    |      +--- Inventory
    |      +--- Sales
    |      +--- Purchases
    |      +--- Expenses
    |      +--- Stock Counts
    |
    +--- Product
           |
           +--- Batch
           |
           +--- ProductBranch
```

Storage:

```text
Branch
   |
   +--- StorageLocation
           |
           +--- StorageLocationAssignment
           |
           +--- BranchInventory
```

Inventory history:

```text
Sale
  ↓
InventoryMovement

Purchase/Receiving
  ↓
InventoryMovement

Transfer
  ↓
InventoryMovement

Stock Count Variance
  ↓
Approval
  ↓
InventoryMovement
```

---

# 41. API Design

The backend should expose clean REST APIs.

Expected API areas include:

```text
/auth/
/organizations/
/branches/
/users/
/roles/
/permissions/
/products/
/categories/
/product-branches/
/batches/
/inventory/
/storage-locations/
/inventory-movements/
/sales/
/returns/
/payments/
/receipts/
/purchases/
/suppliers/
/stock-receipts/
/stock-counts/
/stock-transfers/
/expenses/
/prices/
/price-history/
/audit/
/sync/
/reports/
/subscriptions/
/licenses/
/settings/
```

The exact endpoint names can be refined during architecture design.

Every endpoint must enforce the correct organization/branch/permission scope.

---

# 42. Local vs Central Responsibilities

The local desktop application should own the branch's ability to operate offline.

The central server should provide:

- Centralized organization data
- Cross-branch administration
- Synchronization
- Server-side validation
- Central reporting where appropriate
- Subscription/license management
- Audit consolidation
- Remote administration where implemented

Do not make the desktop application dependent on a live server for every POS click.

---

# 43. Important Offline Scenario

Example:

```text
Internet goes down
        ↓
Cashier makes sale
        ↓
SQLite transaction succeeds
        ↓
Inventory updates locally
        ↓
Receipt prints
        ↓
Audit event created
        ↓
Sync event added to outbox
        ↓
Pharmacy continues operating
        ↓
Internet returns
        ↓
Sync uploads event
        ↓
Server accepts idempotently
        ↓
Other branches receive relevant changes
```

There must be no duplicate sale simply because synchronization was retried.

---

# 44. Acceptance Scenarios

## Scenario A — Offline Sale

1. Disconnect Internet.
2. Make a sale.
3. Inventory updates locally.
4. Receipt prints.
5. Audit record is created.
6. Sync event is queued.
7. Restore Internet.
8. Event synchronizes.
9. No duplicate sale exists.

## Scenario B — Central Price Update

1. Authorized administrator changes a price.
2. Old and new prices are recorded.
3. User, branch/device context and timestamp are recorded.
4. Branches receive the update.
5. Branch applies the new price.
6. Branch records received/applied time.
7. Historical sales retain old prices.

## Scenario C — Same Administrator Across Branches

1. Administrator operates in Branch A.
2. Later operates in Branch B.
3. System records the correct branch context for each action.
4. Reports and audit history remain branch-correct.

## Scenario D — Shelf Stock Count

1. Branch has storage locations.
2. Staff is assigned to a storage location.
3. Monthly count is performed.
4. Physical quantity differs from system quantity.
5. Variance is recorded.
6. Approval is required.
7. Approved adjustment becomes an inventory movement.
8. Audit history remains complete.

## Scenario E — Pharmacy Without Shelves

1. Disable storage-location/shelf workflow.
2. Product and inventory management still works.
3. Sales still work.
4. Purchasing still works.
5. Stock counts still work.
6. No shelf fields should become unnecessarily mandatory.

## Scenario F — Multiple Branches

1. Five branches operate independently.
2. One branch loses Internet.
3. Other branches remain online.
4. Offline branch continues selling.
5. Offline branch reconnects.
6. Its events synchronize safely.
7. No duplicate transactions occur.

---

# 45. Testing Strategy

Test at several levels.

## Unit Tests

Test:

- Pricing
- Batch selection
- FEFO/FIFO
- Inventory calculations
- Permissions
- Stock-count variance
- Approval logic
- Receipt numbering
- Sync event creation
- Idempotency

## Integration Tests

Test:

- Desktop ↔ API
- API ↔ PostgreSQL
- Sync upload/download
- Offline → online transitions
- Inventory movements
- Sales
- Purchases
- Returns
- Transfers

## End-to-End Tests

Test complete business workflows.

At minimum include the acceptance scenarios above.

---

# 46. Development Structure

Keep business logic separate from UI logic and synchronization logic.

A possible desktop structure:

```text
desktop/
    app/
        ui/
        models/
        services/
        repositories/
        domain/
        sync/
        printing/
        auth/
        configuration/
        migrations/
        tests/
```

A possible backend structure:

```text
server/
    manage.py
    config/
    apps/
        organizations/
        branches/
        users/
        products/
        inventory/
        sales/
        purchasing/
        suppliers/
        expenses/
        stock_counts/
        transfers/
        pricing/
        audit/
        sync/
        subscriptions/
        reports/
```

This is a starting structure; refine it during architecture design.

---

# 47. Configuration

Avoid hard-coded business assumptions.

Examples of things that should be configurable:

- Number of branches
- Storage locations
- Shelf usage
- Roles
- Permissions
- Payment methods
- Expense categories
- Product categories
- Expiry alert thresholds
- Printer settings
- Receipt format
- Tax settings
- Price rules
- Stock-count frequency/workflow
- Subscription entitlements

The first customer's configuration must not become the architecture.

---

# 48. What NOT to Do

Do not:

- Hard-code five branches.
- Hard-code five shelves.
- Assume every pharmacy has shelves.
- Create duplicate Product records for every branch.
- Store one global product quantity.
- Copy SQLite database files to synchronize.
- Use blind last-write-wins for inventory.
- Delete sales to process returns.
- Silently overwrite stock during stock counts.
- Depend on Internet connectivity for ordinary POS operations.
- Put secrets in source control.
- Put all business logic inside PySide6 widgets.
- Put all functionality into one giant Python file.
- Remove historical records merely to simplify the UI.
- Disable auditing because it is inconvenient.
- Make every pharmaceutical field mandatory for every product type.
- Build only for the first customer's exact 5-branch setup.

---

# 49. Development Order

Before implementing the full UI, produce an architecture/design package containing:

1. System architecture diagram
2. Local SQLite ERD
3. Central PostgreSQL ERD
4. Django module structure
5. PySide6 application structure
6. Sync protocol
7. Audit event model
8. Inventory movement model
9. Product/Batch/Inventory relationship
10. Branch/Storage Location relationship
11. Role/Permission model
12. Price versioning model
13. Stock-count workflow
14. Subscription/license design
15. Backup/restore approach
16. API endpoint plan
17. Migration strategy
18. Testing strategy

Do not rush directly into building hundreds of screens.

---

# 50. Suggested MVP

The first commercial MVP should include:

- Authentication
- Organizations
- Branches
- Roles and permissions
- Products
- Categories
- Product types
- Batches
- Inventory
- Optional storage locations/shelves
- Staff/storage assignment
- Sales/POS
- Receipts
- Purchasing
- Suppliers
- Expenses
- Stock counts
- Audit trail
- Offline SQLite operation
- Synchronization
- Dashboards
- Reports
- Backups
- Installer

---

# 51. Future Features

Possible future modules:

- Advanced accounting
- Customer loyalty
- SMS
- Email
- Supplier portals
- Forecasting
- Purchase recommendations
- Mobile application
- Web administration
- Advanced analytics
- Barcode label printing
- External integrations

Do not allow future features to destabilize the core MVP architecture.

---

# 52. IDE AI Instructions

When working on this project, the IDE AI must follow these rules.

## Before coding

Read this README completely.

Understand:

- Multi-branch architecture
- Offline-first requirement
- Optional storage locations
- Batch-aware inventory
- Event-based synchronization
- Audit requirements
- Role/permission requirements
- Subscription architecture

Do not begin by assuming the first customer configuration is the universal configuration.

## Before complex features

Explain:

1. Data model
2. Integration points
3. Business rules
4. Offline implications
5. Synchronization implications
6. Permission implications
7. Audit implications
8. Migration requirements
9. Tests required

Then implement incrementally.

## Preserve existing functionality

Do not rewrite working modules unnecessarily.

Before modifying an existing module:

- Understand current behavior.
- Identify dependencies.
- Preserve existing functionality.
- Add tests where appropriate.
- Avoid regressions.

## Database discipline

Use migrations.

Do not casually drop tables.

Do not destroy existing business data.

Provide migration/back-up procedures before risky schema changes.

## Security discipline

Never hard-code secrets.

Never commit real credentials.

Enforce permissions server-side.

Validate organization and branch scope on every relevant API operation.

## Sync discipline

Do not copy database files.

Do not use unsafe last-write-wins inventory synchronization.

Use globally unique events.

Make event processing idempotent.

Do not let sync freeze normal branch operations.

## UI discipline

Use maintainable components.

Do not place all logic in UI event handlers.

Use services/repositories/domain logic where appropriate.

For large tables, use model/view and pagination.

---

# 53. Definition of Done

A feature is not considered complete merely because the screen exists.

For a production feature, verify as applicable:

- UI
- Local database
- Business rules
- Permissions
- Audit
- Offline operation
- Synchronization
- Error handling
- Tests
- Migrations
- Data safety
- Reports
- Performance
- Recovery behavior
- No regressions

---

# 54. Final Product Requirement

Treat this project as a **commercial offline-first multi-branch pharmacy management platform**.

The architecture must be:

```text
OFFLINE-FIRST
MULTI-BRANCH
AUDITABLE
SYNCHRONIZED
CONFIGURABLE
ROLE-BASED
BATCH-AWARE
INVENTORY-SAFE
PROFESSIONAL
MAINTAINABLE
```

The first customer's five branches are an example deployment, not an architectural limit.

The first customer's shelf workflow is an optional configurable feature, not a universal assumption.

The system must remain useful without Internet connectivity and must synchronize safely when connectivity returns.

Build incrementally, test carefully, preserve data, and prioritize correctness and maintainability over shortcuts.
