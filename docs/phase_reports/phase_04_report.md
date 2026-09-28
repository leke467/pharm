# Phase 4 Report — Batches, Inventory & Basic Pricing

## 1. Phase Summary
- **Phase**: Phase 4 — Batches, Inventory & Basic Pricing
- **Status**: **PASS**

## 2. Files Created & Modified
### Server (`server/`)
- `server/apps/inventory/{__init__,apps,models,serializers,views,urls}.py`:
  - `Batch`, `StorageLocation`, `StorageLocationAssignment`, `BranchInventory`, immutable `InventoryMovement`, and `InventoryAlert`.
  - `apply_inventory_movement()` atomic movement engine with `DEPLETED`/`EXPIRED` batch status transitions and `OVERSOLD` alert generation.
  - `OpeningBalanceView` (one-time per branch, sets `Branch.initial_stock_loaded=True`), `StockAdjustmentView`, and `BatchViewSet.recall`.
- `server/apps/pricing/{__init__,apps,models,serializers,views,urls}.py`:
  - `Price` model with versioned `is_current` switching and `resolve_product_price()` (`branch` override -> `org` default).
- `server/tests/test_phase4_acceptance.py`: Phase 4 server acceptance test suite.

### Desktop (`desktop/`)
- `desktop/app/db/models.py` & `desktop/app/db/migrations/versions/003_phase4_inventory_pricing.py`:
  - Added `Batch`, `StorageLocation`, `StorageLocationAssignment`, `BranchInventory`, `InventoryMovement`, and `Price`.
- `desktop/app/repositories/base_repository.py`:
  - Enforced immutability on `InventoryMovement` (`update` and `soft_delete` blocked).
- `desktop/app/services/inventory_service.py` & `desktop/app/services/pricing_service.py`:
  - Full offline-first batch management, optional storage locations, one-time opening balance, movement-based stock adjustments, and price resolution.
- `desktop/app/ui/inventory/inventory_widget.py`:
  - Tabbed PySide6 UI for Branch Stock, Batches, Storage Locations, Stock Adjustments, Opening Balance, and Pricing.
- `desktop/tests/test_phase4_acceptance.py`: Phase 4 desktop acceptance test suite.

## 3. Architecture Compliance & Self-Review
- **Movement-Based Inventory Ledger**: Every stock change creates an immutable `InventoryMovement` record and emits an `inventory_movement` sync delta (`BranchInventory` absolute quantities are never synced directly).
- **Batch Status Lifecycle**: Batches automatically detect `EXPIRED` when `expiry_date < today`, transition to `DEPLETED` when total quantity across branch inventories reaches `0`, and support manual `RECALLED` transitions.
- **Optional Storage Locations**: Strictly opt-in per branch via `Branch.uses_storage_locations`.
- **One-Time Opening Balance**: Enforced via `Branch.initial_stock_loaded` on both server and desktop.
- **Pricing Hierarchy**: Branch-specific `is_current=True` override takes precedence over organization-wide `is_current=True` default, with atomic version incrementation.

## 4. Test Execution Results
- **Server Test Suite**: `36 passed` (including 5 new Phase 4 acceptance tests and all Phases 1–3 regression tests)
- **Desktop Test Suite**: `19 passed` (including 5 new Phase 4 acceptance tests and all Phases 1–3 regression tests)
