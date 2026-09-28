# Phase 3 Report — Product Catalog, Categories & Suppliers

- **Phase Number**: 3
- **Phase Name**: Product Catalog, Categories & Suppliers
- **Status**: PASS
- **Date**: 2026-09-25

---

## 1. Functionality Implemented

- **Server Product Catalog (`server/apps/products/`)**:
  - Implemented `Category` (hierarchical via `parent`), `ProductType`, `Manufacturer`, `Supplier`, `Product` (with nullable pharmaceutical fields so cosmetics, supplements, and devices work without requiring drug-specific metadata), `ProductBranch` (opt-in branch availability), and `ProductDocument` models.
  - Added composite indexes `(organization, sku)`, `(organization, barcode)`, and `(organization, name)` on `Product`.
  - Built DRF serializers and ViewSets (`/api/v1/categories/`, `/api/v1/product-types/`, `/api/v1/manufacturers/`, `/api/v1/suppliers/`, `/api/v1/products/`, `/api/v1/product-branches/`, `/api/v1/product-documents/`) with search (`?search=`), barcode lookup (`?barcode=`), SKU lookup (`?sku=`), and branch availability filter (`?branch_id=`), plus `select_all_branches` / `branch_ids` assignment on product creation/update.
  - Enforced RBAC permissions (`products.view`, `products.create`, `products.edit`, `products.delete`, `suppliers.manage`) and recorded `AuditEvent`s (`PRODUCT_CREATED`, `PRODUCT_UPDATED`) using `DjangoJSONEncoder`.
- **Desktop Product Catalog & FTS5 Search (`desktop/`)**:
  - Added `Category`, `ProductType`, `Manufacturer`, `Supplier`, `Product`, `ProductBranch`, and `ProductDocument` SQLAlchemy models to `desktop/app/db/models.py`.
  - Configured SQLite `products_fts` FTS5 virtual table and automatic `INSERT`/`UPDATE`/`DELETE` synchronization triggers in `DatabaseManager` and migration `002_phase3_products.py`.
  - Implemented `ProductService` (`desktop/app/services/product_service.py`) with FTS5 prefix search, barcode lookup, branch opt-in filtering, and correlated `SyncEvent` + `AuditEvent` generation.
  - Built and wired `ProductsWidget` (`desktop/app/ui/products/products_widget.py`) into `MainWindow` with tabs for Products, Categories, and Suppliers.

---

## 2. Files Created & Modified

- **Server**: `apps/products/{__init__,apps,models,serializers,views,urls}.py`, `apps/products/migrations/0001_initial.py`, `apps/audit/models.py`, `apps/sync/models.py`, `config/settings/base.py`, `apps/api/urls.py`, `tests/test_phase3_acceptance.py`.
- **Desktop**: `app/db/models.py`, `app/db/database.py`, `app/db/migrations/versions/002_phase3_products.py`, `app/services/product_service.py`, `app/ui/products/{__init__,products_widget}.py`, `app/ui/main_window.py`, `app/application.py`, `tests/test_phase3_acceptance.py`.

---

## 3. Bugs Discovered & Fixed During Phase 3 Gate

1. **UUID Serialization in `AuditEvent` JSONField**: Storing `ProductSerializer(product).data` inside `AuditEvent.data_after` raised `TypeError: Object of type UUID is not JSON serializable` with Django's default JSON encoder. Fixed by configuring `encoder=DjangoJSONEncoder` on `AuditEvent.data_before`, `AuditEvent.data_after`, and `SyncDelivery.payload`.
2. **DRF `UniqueTogetherValidator` on Read-Only `organization` Field**: DRF automatically added a `UniqueTogetherValidator` requiring `organization` in the input payload before `perform_create` ran. Fixed by setting `validators = []` on the org-scoped serializers where `organization_id` is injected server-side.

---

## 4. Test Execution & Acceptance Results

- **Server Tests**: 31 executed, **31 passed**, 0 failed
- **Desktop Tests**: 14 executed, **14 passed**, 0 failed
- **Total Regression + Acceptance Tests**: **45 passed, 0 failed**
