# Pharmacy Management System: User Quick-Start Guide

Welcome to the Pharmacy Management System — an offline-first, multi-branch, commercial pharmacy operating system.

---

## 1. First-Time Setup & Login

1. **Launch Application**:
   - Double click `PharmacyManagement.exe` on your desktop.
2. **Initial Online Login**:
   - Enter your **Username** and **Password**.
   - Select your assigned **Branch**.
   - Click **Login**. On first login, your permissions, profile, and offline credentials are securely cached locally.
3. **Offline Operation**:
   - If internet connectivity drops, you can continue logging in and operating completely offline using your locally cached credentials.

---

## 2. Point of Sale (POS)

1. Open the **POS** screen from the sidebar navigation.
2. **Scan / Search Product**:
   - Type medication name, generic name, brand, or scan barcode.
   - Products are instantly searched using local full-text indexing (FTS5).
3. **Price Freezing**:
   - When an item is added to the cart, its price is frozen. If background price updates occur while ringing up a customer, the cart price does not shift.
4. **FEFO Allocation**:
   - Batches are automatically allocated First-Expired, First-Out (FEFO). Expired or recalled batches are blocked from dispensation.
5. **Checkout**:
   - Choose payment method (Cash, Card, Mobile, Split).
   - Enter tendered amount and click **Complete Sale**.
   - An immutable receipt and inventory movement are instantly created.

---

## 3. Stock Management & Purchasing

1. **Purchases**:
   - Create Purchase Orders, request manager approval, and receive stock upon delivery.
   - Receiving stock automatically creates new batches, logs ledger movements, and updates wholesale/cost basis.
2. **Stock Counts**:
   - Initiate physical blind stock counts without seeing system quantities.
   - Enter physical counts. Variances generate reviewable adjustments upon manager sign-off.
3. **Inter-Branch Transfers**:
   - Request transfers between branches. Stock is reserved at source, dispatched in-transit, and confirmed at the receiving branch.

---

## 4. Maintenance & Backups

1. Navigate to **Settings** -> **Backup & Maintenance**.
2. **Backups**:
   - Click **Create Backup Now** to take an instant snapshot of your local database.
   - Up to 30 daily backups are automatically maintained.
3. **Ledger Reconciliation**:
   - Click **Run Inventory Reconciliation** to verify that physical stock balances match the immutable movement ledger.
