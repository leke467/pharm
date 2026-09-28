# Phase 7 Report — Returns & Voids

## 1. Phase Summary
- **Phase**: Phase 7 — Returns & Voids
- **Status**: **PASS (COMPLETE)**
- **Completed At**: 2026-09-25

## 2. Files Created & Modified
### Server (`server/`)
- `server/apps/sales/models.py`: Added `SaleReturn` and `SaleReturnItem` models with strict no-delete protection (`delete()` raises `ValidationError`).
- `server/apps/sales/migrations/0002_salereturn_salereturnitem.py`: Generated migration for `SaleReturn` and `SaleReturnItem`.
- `server/apps/sales/serializers.py`: Added `SaleReturnItemSerializer`, `SaleReturnSerializer`, and `CreateSaleReturnRequestSerializer`.
- `server/apps/sales/views.py`:
  - Added `SaleViewSet.void` (`POST /api/v1/sales/{id}/void/`) enforcing `SALES_VOID` permission, mandatory non-empty `reason`, full `SaleReturn` + `SaleReturnItem` creation, positive `InventoryMovement(SALE_RETURN)` reversal deltas restoring stock to original batches, `Sale.status = VOIDED`, and `AuditEvent(SALE_VOIDED)`.
  - Added `SaleReturnViewSet` (`GET/POST /api/v1/sale-returns/`) enforcing `SALES_RETURN` permission, cumulative over-return prevention across multiple partial returns, `PARTIALLY_RETURNED` / `RETURNED` status transitions, positive `InventoryMovement(SALE_RETURN)` movements, and `AuditEvent(SALE_RETURNED)`.
- `server/apps/sales/urls.py`: Registered `/api/v1/sale-returns/`.
- `server/apps/sales/sync_handlers.py`: Registered `sale_return` and `sale_return_item` sync handlers.
- `server/tests/test_phase7_acceptance.py`: Added Phase 7 server acceptance tests.

### Desktop (`desktop/`)
- `desktop/app/db/models.py`: Added `SaleReturn` and `SaleReturnItem` SQLAlchemy models.
- `desktop/app/db/migrations/versions/005_phase7_returns.py`: Added schema version 5 migration for `sale_returns` and `sale_return_items`.
- `desktop/app/repositories/base_repository.py`: Enforced no-delete on `SaleReturn` and `SaleReturnItem`, and immutability on `SaleReturnItem`.
- `desktop/app/services/sales_service.py`: Added `void_sale()`, `return_sale()`, `list_returns()`, and download handlers `_download_sale_return` and `_download_sale_return_item`.
- `desktop/tests/test_phase7_acceptance.py`: Added Phase 7 desktop acceptance tests.

## 3. Verification & Test Results
- **Server Test Suite**: `46 passed` (`tests/test_phase7_acceptance.py` + full regression suite Phases 1–6)
- **Desktop Test Suite**: `26 passed` (`tests/test_phase7_acceptance.py` + full regression suite Phases 1–6)
