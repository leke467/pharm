# Phase 1 Report — Foundation

- **Phase Number**: 1
- **Phase Name**: Foundation
- **Status**: PASS
- **Date**: 2026-09-25

---

## 1. Functionality Implemented

- **Monorepo Scaffolding**: Established `server/` (Django 5.1 + DRF + SimpleJWT), `desktop/` (PySide6 + SQLAlchemy 2 + httpx + bcrypt), and `shared/` (canonical enums, permission codes, sync dependency levels).
- **Central Server Foundation (`server/`)**:
  - Split settings (`base.py`, `development.py`, `production.py`, `testing.py`) with `USE_TZ = True` and `TIME_ZONE = 'UTC'`.
  - Abstract `TimestampedModel` and `BaseModel` with UUID v4 primary keys, UTC timestamps, and `soft_delete()` (`is_active = False`).
  - Three-Layer Tenant Security:
    1. Queryset scoping via `OrganizationQuerysetMixin.get_queryset()`
    2. Object-level permission verification via `IsOrganizationMember`
    3. `OrganizationScopeMiddleware` resolving JWT / session user and injecting `request.organization` and `request.organization_id`
  - Core models: `Organization`, `Branch`, `Device`, `User`, `Role`, `Permission`, `RolePermission`, `UserRole`, `SyncDelivery`, `ProcessedEvent`, `AuditEvent` (immutable).
  - API v1 endpoints (`/api/v1/health/`, `/api/v1/auth/login/`, `/api/v1/auth/refresh/`, `/api/v1/auth/me/`, `/api/v1/auth/logout/`, `/api/v1/organizations/`, `/api/v1/branches/`, `/api/v1/devices/`, `/api/v1/users/`, `/api/v1/roles/`, `/api/v1/permissions/`, `/api/v1/user-roles/`).
- **Desktop Foundation (`desktop/`)**:
  - `AppConfig` loading environment variables and defaulting to OS app-data directory (`%LOCALAPPDATA%/PharmacyManagement`).
  - `DatabaseManager` configuring SQLite in WAL mode (`PRAGMA journal_mode=WAL`, `foreign_keys=ON`, `synchronous=NORMAL`, `busy_timeout=5000`, `optimize`).
  - Versioned `MigrationRunner` with automatic pre-migration database backup and `SchemaVersion` tracking.
  - 14 SQLAlchemy models: `Organization`, `Branch`, `Device`, `User`, `Role`, `Permission`, `RolePermission`, `UserRole`, `OfflineCredential`, `SyncEvent`, `SyncCursor`, `SchemaVersion`, `AuditEvent`, `PrinterConfiguration`.
  - Layered architecture: `BaseRepository` (with standalone auto-commit and multi-repository transaction session support, soft-delete, and `AuditEvent` immutability), `BaseService` (`transaction()` context manager), `ApiClient` (30s timeout, structured exception mapping), `OfflineAuthenticator` (local bcrypt hashing), `AuthManager` (online + offline auth with 7-day / 72-hour offline limits), `SyncWorker` (`QThread`), and PySide6 shell (`MainWindow`, `LoginWidget`, `DashboardWidget`, `StatusBadge`).

---

## 2. Files Created & Modified

- **Root & Shared**: `.gitignore`, `.env.example`, `README.md`, `phase1_implementation_plan.md`, `shared/__init__.py`, `shared/enums.py`, `docs/architecture_plan.md`.
- **Server (`server/`)**: `requirements.txt`, `manage.py`, `pytest.ini`, `config/settings/{base,development,production,testing}.py`, `config/{urls,wsgi,asgi}.py`, `apps/core/{models,permissions,middleware,mixins,pagination,exceptions}.py`, `apps/organizations/{models,serializers,views,urls}.py`, `apps/branches/{models,serializers,views,urls}.py`, `apps/users/{models,managers,auth_backend,serializers,views,urls}.py`, `apps/sync/models.py`, `apps/audit/models.py`, `apps/api/{views,urls}.py`, migrations for all apps, and `tests/{conftest,test_models,test_auth,test_tenant_isolation,test_api,test_phase1_acceptance}.py`.
- **Desktop (`desktop/`)**: `requirements.txt`, `app/{main,application}.py`, `app/config/{app_config,constants}.py`, `app/db/{database,models}.py`, `app/db/migrations/runner.py`, `app/db/migrations/versions/001_initial.py`, `app/repositories/base_repository.py`, `app/services/base_service.py`, `app/domain/{enums,exceptions}.py`, `app/auth/{session,offline_auth,auth_manager}.py`, `app/sync/{api_client,sync_worker}.py`, `app/ui/{main_window,login/login_widget,dashboard/dashboard_widget,common/status_badge,resources/styles.qss}`, `app/utils/{uuid_utils,date_utils,logging_config}.py`, and `tests/{conftest,test_database,test_repositories,test_config,test_api_client,test_auth,test_phase1_acceptance}.py`.

---

## 3. Bugs Discovered & Fixed During Phase 1 Gate

1. **DRF JWT vs Django Middleware Timing**: `OrganizationScopeMiddleware` ran before DRF's `JWTAuthentication`, leaving `request.organization_id = None` for token-authenticated requests. Fixed by resolving JWT bearer tokens in `OrganizationScopeMiddleware` and enforcing `request.organization_id` in `OrganizationQuerysetMixin.initial()`.
2. **Cross-Organization Login Bypass via `ModelBackend`**: Having `django.contrib.auth.backends.ModelBackend` as a fallback in `AUTHENTICATION_BACKENDS` allowed authenticating a username against the wrong organization code. Removed `ModelBackend` and hardened `CustomAuthBackend` + `LoginView` to strictly verify `user.organization_id == org.id`.
3. **Cross-Organization Device Registration**: `DeviceViewSet.perform_create` previously accepted any `branch_id` UUID without verifying that the branch belonged to `request.organization_id`. Fixed with `get_object_or_404(Branch, id=branch_id, organization_id=org_id)`.
4. **SQLAlchemy Session Commit & Detachment in `BaseRepository`**: `BaseRepository.create` previously expunged instances without committing the session. Fixed with `_session_scope()` that auto-commits standalone calls, supports shared transactional `session` passed from `BaseService.transaction()`, and sets `expire_on_commit=False`.
5. **Missing `PrinterConfiguration` & `import os` in Desktop**: Added `PrinterConfiguration` model to `desktop/app/db/models.py` and fixed missing `import os` in `MainWindow`.

---

## 4. Test Execution & Acceptance Results

- **Server Tests**: 23 executed, **23 passed**, 0 failed (`pytest tests/ -v`)
- **Desktop Tests**: 10 executed, **10 passed**, 0 failed (`pytest tests/ -v`)
- **Total Phase 1 Tests**: **33 passed, 0 failed**
- **Architecture & Security Checks**:
  - UUID v4 primary keys everywhere: PASS
  - Password hash never transmitted by server: PASS
  - Three-layer tenant isolation: PASS
  - Soft-delete (`is_active=False`) enforced: PASS
  - `AuditEvent` immutability enforced on both server and desktop: PASS
  - SQLite WAL mode + foreign keys enabled: PASS
