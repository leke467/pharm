# Phase 2 Report — Authentication & Organization Structure

- **Phase Number**: 2
- **Phase Name**: Authentication & Organization Structure
- **Status**: PASS
- **Date**: 2026-09-25

---

## 1. Functionality Implemented

- **Server RBAC & Organization Structure (`server/`)**:
  - Added `seed_permissions_and_roles(organization)` in `apps/users/services.py` seeding all 25 canonical permissions and 6 default built-in system roles (`Organization Admin`, `Branch Manager`, `Pharmacist`, `Cashier`, `Storekeeper`, `Auditor`).
  - Implemented `user_has_permission` and `require_permission` DRF permission factory in `apps/core/permissions.py` supporting both org-wide (`branch=None`) and branch-scoped (`X-Branch-ID` / `branch_id`) role evaluation.
  - Enforced granular permissions on write endpoints:
    - `UserViewSet`, `RoleViewSet`, `UserRoleViewSet` require `users.manage`
    - `BranchViewSet`, `DeviceViewSet` require `branches.manage`
    - `OrganizationViewSet` update requires `settings.manage`
  - Protected built-in roles (`is_system=True`) from deletion in `RoleViewSet`.
  - Validated cross-organization references in `UserRoleViewSet.perform_create` and recorded `AuditEvent`s (`USER_LOGIN`, `USER_LOGOUT`, `PERMISSION_CHANGED`, `SETTINGS_CHANGED`).
- **Desktop Auth, Services & UI (`desktop/`)**:
  - Upgraded `BaseService` with `require_permission` (enforcing both RBAC permissions and 72-hour `offline_session_max_hours` expiry) and `record_audit_and_sync` (atomically appending `AuditEvent` + correlated `SyncEvent`s with `max_retries=50` on audit sync events).
  - Enhanced `AuthManager` with `validate_session()`, `switch_branch(branch_id)` (recomputing branch-scoped permissions), and `sync_user_status(user_id, is_active)` (locking disabled users out of both active sessions and offline login).
  - Implemented `OrganizationService` and `UserService` for local offline-capable management of Organizations, Branches, Devices, Users, Roles, and Permissions.
  - Built and wired `UsersWidget` (`ui/users/users_widget.py`) and `SettingsWidget` (`ui/settings/settings_widget.py`) into `MainWindow` and enhanced `LoginWidget` with Organization Code and dynamic branch selection.

---

## 2. Files Created & Modified

- **Server**: `apps/core/permissions.py`, `apps/users/services.py`, `apps/users/serializers.py`, `apps/users/views.py`, `apps/branches/views.py`, `apps/organizations/views.py`, `tests/conftest.py`, `tests/test_phase2_acceptance.py`.
- **Desktop**: `app/services/base_service.py`, `app/services/organization_service.py`, `app/services/user_service.py`, `app/auth/auth_manager.py`, `app/ui/users/{__init__,users_widget}.py`, `app/ui/settings/{__init__,settings_widget}.py`, `app/ui/login/login_widget.py`, `app/ui/main_window.py`, `app/application.py`, `tests/test_phase2_acceptance.py`.

---

## 3. Bugs Discovered & Fixed During Phase 2 Gate

1. **SQLite Foreign Key Check on `UserRole.assigned_by_id`**: When an admin session assigned a role offline before the admin's own `User` record was present in the local `users` table, SQLite's `PRAGMA foreign_keys=ON` rejected the insert. Fixed in `UserService.assign_role` by verifying whether `user_session.user_id` exists in local `users` before setting the local FK column while preserving `assigned_by_id` in the outbound `SyncEvent` payload.

---

## 4. Test Execution & Acceptance Results

- **Server Tests**: 28 executed, **28 passed**, 0 failed
- **Desktop Tests**: 13 executed, **13 passed**, 0 failed
- **Total Regression + Acceptance Tests**: **41 passed, 0 failed**
