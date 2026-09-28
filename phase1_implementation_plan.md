# Phase 1 — Foundation Implementation Plan

> **Date**: 2026-09-25  
> **Architecture source**: `architecture_plan.md` v2.0  
> **Scope**: Foundation scaffolding only. No business workflows (POS, purchasing, stock counts, etc.)

---

## What Phase 1 Implements

### 1. Repository Root
- `.gitignore` (Python, Django, PySide6, SQLite, env files)
- `.env.example` (all required environment variables documented)
- `README.md` (project overview, setup instructions)

### 2. Central Server (`server/`)
- **Django project** with split settings (`base.py`, `development.py`, `production.py`, `testing.py`)
- **Django REST Framework** configuration (pagination, auth, versioning)
- **PostgreSQL** configuration with `TIMESTAMPTZ` (UTC)
- **Core app** (`apps/core/`):
  - `BaseModel`: UUID v4 PK, `created_at`, `updated_at`, `is_active` (soft-delete)
  - `OrganizationScopeMiddleware`: injects `request.organization` from authenticated user
  - `IsOrganizationMember` permission class (queryset + object-level)
  - Standard pagination class
  - Centralized exception handler
- **Organizations app** (`apps/organizations/`): Organization model + serializer + viewset
- **Branches app** (`apps/branches/`): Branch model, Device model (with `code` field) + serializers + viewsets
- **Users app** (`apps/users/`):
  - Custom User model (UUID PK, `organization_id`, `is_org_admin`, `default_branch_id`)
  - Role, Permission, RolePermission, UserRole models
  - JWT auth endpoints: login, refresh, me, logout
  - User/Role/Permission serializers + viewsets
- **Sync app** (`apps/sync/`): SyncDelivery model, ProcessedEvent model (schema only, no processing logic)
- **Audit app** (`apps/audit/`): AuditEvent model (schema only, append-only)
- **API** (`/api/v1/`):
  - `health/` — health check endpoint
  - `auth/login/`, `auth/refresh/`, `auth/me/`, `auth/logout/`
  - `organizations/`, `branches/`, `devices/`, `users/`, `roles/`, `permissions/`
- **Migrations**: All Phase 1 models
- **Tests**: Model creation, tenant isolation, auth flow, permission enforcement

### 3. Desktop Application (`desktop/`)
- **SQLAlchemy ORM models** mirroring Phase 1 server models + local-only tables:
  - Organization, Branch, Device, User, Role, Permission, RolePermission, UserRole
  - SyncEvent (outbox), SyncCursor
  - OfflineCredential
  - PrinterConfiguration
  - SchemaVersion (migration tracking)
- **Database initialization**: SQLite with WAL mode, `PRAGMA` optimizations, app-data directory
- **Migration framework**: Versioned migration runner with `schema_version` table
- **Layered architecture**:
  - `repositories/base_repository.py` — base CRUD with session management
  - `services/` — service base class with transaction support
  - `domain/` — enums, exceptions, validators (foundations)
- **Auth foundation** (`auth/`):
  - `AuthManager` — online login via API, offline login via `OfflineCredential`
  - `Session` — current user context, branch context, device context
  - `OfflineAuth` — bcrypt hash verification (desktop-generated, never server-transmitted)
- **API client** (`sync/api_client.py`):
  - httpx-based async client
  - Configurable server URL, auth headers, 30-second timeout
  - Handles connection errors, returns structured errors
  - Non-blocking (runs off main thread)
- **Sync foundation** (`sync/`):
  - SyncEvent SQLAlchemy model
  - SyncCursor SQLAlchemy model
  - Sync worker stub (QThread-based, not yet processing events)
- **Configuration** (`config/`):
  - `AppConfig` — loads `.env`/settings, server URL, data directory
  - `constants.py` — non-secret constants
- **Logging**: Structured logging, separate handlers for app/auth/db/sync errors
- **UI foundation** (`ui/`):
  - `MainWindow` — sidebar navigation shell, status bar with sync indicator
  - `LoginWidget` — login form with branch selector
  - Placeholder dashboard page
  - Clean modern styling via QSS
- **Tests**: SQLite initialization, WAL mode, repository operations, config loading, API client error handling

### 4. Shared (`shared/`)
- `enums.py` — movement types, statuses, permission codes
- `schemas.py` — sync event schema version constants

---

## What Phase 1 Does NOT Implement

- Products, Categories, ProductTypes, Manufacturers, Suppliers
- Batches, BranchInventory, StorageLocations
- InventoryMovements, InventoryAlerts
- Sales, POS, Receipts, Payments
- Purchases, PurchaseItems, PurchasePayments
- Stock Counts, Transfers, Expenses
- Prices, PriceHistory
- Complete sync upload/download processing
- Complete offline auth workflow (foundation only)
- Reports, Dashboards (beyond placeholder)
- Subscription/Licensing
- Receipt printing
- Packaging/installer

These belong to Phases 2–17 as defined in the architecture plan.

---

## Key Architecture Constraints Enforced

1. UUID v4 primary keys generated client-side
2. `organization_id` on all tenant-scoped tables
3. Soft-delete via `is_active` — no hard deletes
4. All timestamps UTC (PostgreSQL `TIMESTAMPTZ`, SQLite ISO 8601 UTC strings)
5. `local_timestamp` with TZ offset where applicable
6. Server NEVER sends password hash to desktop
7. Three-layer tenant security (queryset, object, middleware)
8. Desktop ↔ Server via REST API only — no direct PostgreSQL access
9. No assumption of specific branch/device/shelf counts
10. No network call blocks the UI thread
