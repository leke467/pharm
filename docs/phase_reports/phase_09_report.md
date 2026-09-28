# Phase 9 Report — Stock Counts & Approval

## 1. Phase Summary
- **Phase**: Phase 9 — Stock Counts & Approval
- **Status**: **PASS (COMPLETE)**
- **Completed At**: 2026-09-25

## 2. Files Created & Modified
### Server (`server/`)
- `server/apps/inventory/models.py`: Added `StockCount` and `StockCountItem` models matching architecture specifications.
- `server/apps/inventory/migrations/0002_stock_counts.py`: Generated and applied Django migration for `StockCount` and `StockCountItem`.
- `server/apps/inventory/serializers.py`: Added `StockCountItemSerializer`, `StockCountSerializer`, `StockCountStartSerializer`, `StockCountSubmitSerializer`, and `StockCountApprovalSerializer`.
- `server/apps/inventory/views.py`: Added `StockCountViewSet` with `start`, `submit`, and `approve` custom actions. Enforced:
  - Variance calculation: `physical_quantity - system_quantity`.
  - Negative quantity guard at approval: `current_quantity_at_approval + item.variance >= 0`.
  - Immutable `InventoryMovement(COUNT_VARIANCE)` ledger entries and `AuditEvent(STOCK_COUNT_APPROVED)`.
  - Multi-device offline conflict detection (`CONFLICT` status) if branch or storage location is already under an active unsubmitted count.
- `server/apps/inventory/urls.py`: Registered router route `r'stock-counts'` under `/api/v1/inventory/stock-counts/`.
- `server/apps/inventory/sync_handlers.py`: Added upload sync handlers for `stock_count` and `stock_count_item` with device safety guards and conflict detection.
- `server/tests/test_phase9_acceptance.py`: Acceptance test suite covering start, submit, variance computation, approval with negative stock blocking, inventory movement ledger generation, and conflict handling.

### Desktop (`desktop/`)
- `desktop/app/db/models.py`: Added SQLAlchemy ORM models `StockCount` and `StockCountItem`.
- `desktop/app/db/migrations/versions/007_phase9_stock_counts.py`: Added SQLite schema migration version 7 for stock counts.
- `desktop/app/services/stock_count_service.py`: Implemented `StockCountService` (`start_stock_count`, `submit_stock_count`, `approve_stock_count`, `list_stock_counts`) and registered sync download handlers for `stock_count` and `stock_count_item`.
- `desktop/app/ui/stock_counts/__init__.py`, `stock_counts_widget.py`: Implemented desktop Stock Count widget with count initiation, physical count data entry, variance review, and approval flow.
- `desktop/app/ui/main_window.py`: Enabled Stock Count navigation item and wired `StockCountsWidget` into `QStackedWidget`.
- `desktop/tests/test_phase9_acceptance.py`: Acceptance test suite verifying desktop stock count initiation, recording, submit, approval, inventory movement generation, negative quantity guard, and download handlers.

## 3. Verification & Test Results
- **Server Test Suite**: `50 passed` (`tests/test_phase9_acceptance.py` + full regression suite Phases 1–8)
- **Desktop Test Suite**: `28 passed` (`tests/test_phase9_acceptance.py` + full regression suite Phases 1–8)
