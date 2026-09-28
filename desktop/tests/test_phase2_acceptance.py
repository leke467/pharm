from datetime import datetime, timezone, timedelta
import pytest
from desktop.app.auth.session import Session
from desktop.app.auth.offline_auth import OfflineAuthenticator
from desktop.app.auth.auth_manager import AuthManager
from desktop.app.db.models import AuditEvent, SyncEvent, Organization
from desktop.app.domain.exceptions import (
    AuthenticationError,
    PermissionDeniedError,
    NetworkError,
)
from desktop.app.services.organization_service import OrganizationService
from desktop.app.services.user_service import UserService
from shared.enums import PermissionCode, AuditAction


def _make_admin_session(org_id: str, branch_id: str = "") -> Session:
    return Session(
        user_id="admin-0001",
        username="admin",
        full_name="Org Admin",
        organization_id=org_id,
        organization_name="Test Pharmacy",
        branch_id=branch_id,
        branch_name="Main Branch",
        device_id="dev-0001",
        device_code="D1",
        permissions=[p.value for p in PermissionCode],
        roles=[{"name": "Organization Admin"}],
        is_offline=False,
        is_org_admin=True,
        logged_in_at=datetime.now(timezone.utc).isoformat(),
    )


def _make_cashier_session(org_id: str, branch_id: str = "") -> Session:
    return Session(
        user_id="cashier-0001",
        username="cashier",
        full_name="Cashier One",
        organization_id=org_id,
        organization_name="Test Pharmacy",
        branch_id=branch_id,
        branch_name="Main Branch",
        device_id="dev-0001",
        device_code="D1",
        permissions=[PermissionCode.SALES_SELL.value, PermissionCode.PRODUCTS_VIEW.value],
        roles=[{"name": "Cashier"}],
        is_offline=True,
        is_org_admin=False,
        logged_in_at=datetime.now(timezone.utc).isoformat(),
        session_expires_at=(datetime.now(timezone.utc) + timedelta(hours=72)).isoformat(),
    )


def test_desktop_rbac_and_atomic_audit_sync_events(db_manager):
    org_svc = OrganizationService(db_manager)
    user_svc = UserService(db_manager)

    with db_manager.get_session() as db:
        org = Organization(id="org-100", name="MedPlus Pharmacy", code="MEDP")
        db.add(org)

    admin_session = _make_admin_session("org-100")
    cashier_session = _make_cashier_session("org-100")

    # 1. Cashier cannot create branch, user, or update organization settings
    with pytest.raises(PermissionDeniedError):
        org_svc.create_branch(cashier_session, name="Forbidden", code="FRB")

    with pytest.raises(PermissionDeniedError):
        user_svc.create_user(cashier_session, username="u1", full_name="User 1")

    with pytest.raises(PermissionDeniedError):
        org_svc.update_organization(cashier_session, name="New Name")

    # 2. Admin creates branch (with storage locations enabled) and branch without storage locations
    b1 = org_svc.create_branch(
        admin_session,
        name="Ikeja Branch",
        code="BR01",
        uses_storage_locations=True,
    )
    b2 = org_svc.create_branch(
        admin_session,
        name="Yaba Branch",
        code="BR02",
        uses_storage_locations=False,
    )
    assert b1.uses_storage_locations is True
    assert b2.uses_storage_locations is False

    # 3. Admin creates role, user, and assigns role to Branch 1
    role = user_svc.create_role(
        admin_session,
        name="Pharmacist",
        permission_codes=[PermissionCode.SALES_SELL.value, PermissionCode.STOCK_RECEIVE.value],
    )
    staff = user_svc.create_user(
        admin_session,
        username="pharm_john",
        full_name="John Doe",
        default_branch_id=b1.id,
    )
    ur = user_svc.assign_role(admin_session, staff.id, role.id, branch_id=b1.id)
    assert ur.branch_id == b1.id

    # 4. Verify AuditEvents and correlated SyncEvents (including max_retries=50 on audit sync)
    with db_manager.get_session() as db:
        audits = db.query(AuditEvent).filter_by(organization_id="org-100").all()
        assert len(audits) == 5  # 2 branches + 1 role + 1 user + 1 user_role

        sync_events = db.query(SyncEvent).all()
        assert len(sync_events) == 10  # 5 entity events + 5 audit_event sync records
        audit_syncs = [s for s in sync_events if s.entity_type == "audit_event"]
        assert len(audit_syncs) == 5
        assert all(s.max_retries == 50 for s in audit_syncs)


def test_offline_session_expiration_enforced(db_manager):
    org_svc = OrganizationService(db_manager)
    expired_session = _make_cashier_session("org-100")
    expired_session.permissions.append(PermissionCode.BRANCHES_MANAGE.value)
    expired_session.session_expires_at = (
        datetime.now(timezone.utc) - timedelta(minutes=5)
    ).isoformat()

    with pytest.raises(AuthenticationError, match="expired"):
        org_svc.create_branch(expired_session, name="Late Branch", code="LB01")


def test_disabled_user_lockout_and_branch_switching(db_manager):
    offline_auth = OfflineAuthenticator()

    class MockApi:
        def __init__(self):
            self.online = True

        def set_auth_token(self, a, r):
            pass

        def login(self, username, password, org_code, branch_id=None, device_id=None):
            if not self.online:
                raise NetworkError("Offline")
            return {
                "access_token": "tok-1",
                "refresh_token": "ref-1",
                "user": {
                    "id": "u-500",
                    "username": username,
                    "full_name": "Mary Staff",
                    "is_org_admin": False,
                    "organization": "org-500",
                },
                "org": {"id": "org-500", "name": "Care Pharm", "code": "CARE"},
                "branch": {"id": "br-501", "name": "Victoria Island", "code": "VI01"},
                "permissions": [PermissionCode.SALES_SELL.value],
                "roles": [],
            }

    api = MockApi()
    auth_mgr = AuthManager(api, db_manager, offline_auth)
    org_svc = OrganizationService(db_manager)
    user_svc = UserService(db_manager)

    # Online login
    session = auth_mgr.login("mary", "Secret#1", org_code="CARE")
    assert session.branch_id == "br-501"

    # Admin creates a second branch and assigns roles per branch
    admin_sess = _make_admin_session("org-500", "br-501")
    b2 = org_svc.create_branch(admin_sess, name="Surulere", code="SUR01")
    r_cashier = user_svc.create_role(
        admin_sess, name="Cashier", permission_codes=[PermissionCode.SALES_SELL.value]
    )
    r_mgr = user_svc.create_role(
        admin_sess,
        name="Manager",
        permission_codes=[PermissionCode.SALES_SELL.value, PermissionCode.USERS_MANAGE.value],
    )
    user_svc.assign_role(admin_sess, "u-500", r_cashier.id, branch_id="br-501")
    user_svc.assign_role(admin_sess, "u-500", r_mgr.id, branch_id=b2.id)

    # Switch Mary's active branch to Surulere -> permissions update to include users.manage
    switched = auth_mgr.switch_branch(b2.id)
    assert switched.branch_id == b2.id
    assert switched.branch_name == "Surulere"
    assert switched.has_permission(PermissionCode.USERS_MANAGE.value) is True

    # Central server disables Mary -> sync_user_status locks her out
    auth_mgr.sync_user_status("u-500", is_active=False)
    assert auth_mgr.get_current_session() is None

    # Mary tries to login offline -> blocked because account is disabled
    api.online = False
    with pytest.raises(AuthenticationError, match="disabled"):
        auth_mgr.login("mary", "Secret#1", org_code="CARE")
