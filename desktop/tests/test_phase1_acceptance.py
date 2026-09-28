from datetime import datetime, timezone, timedelta
import pytest
from sqlalchemy import inspect
from desktop.app.db.models import (
    Organization,
    Branch,
    Device,
    User,
    AuditEvent,
    OfflineCredential,
)
from desktop.app.db.migrations.runner import MigrationRunner
from desktop.app.repositories.base_repository import BaseRepository
from desktop.app.services.base_service import BaseService
from desktop.app.auth.offline_auth import OfflineAuthenticator
from desktop.app.auth.auth_manager import AuthManager
from desktop.app.domain.exceptions import (
    AuthenticationError,
    NetworkError,
    ValidationError,
)


def test_all_phase1_tables_exist(db_manager):
    inspector = inspect(db_manager.engine)
    tables = set(inspector.get_table_names())
    expected_tables = {
        'organizations',
        'branches',
        'devices',
        'users',
        'roles',
        'permissions',
        'role_permissions',
        'user_roles',
        'offline_credentials',
        'sync_events',
        'sync_cursors',
        'schema_versions',
        'audit_events',
        'printer_configurations',
    }
    assert expected_tables.issubset(tables)


def test_migration_runner_idempotent(db_manager, app_config):
    runner = MigrationRunner(db_manager, app_config)
    runner.run_pending()
    runner.run_pending()
    with db_manager.get_session() as session:
        assert runner.get_current_version(session) >= 1


def test_atomic_service_transaction_rollback(db_manager):
    service = BaseService(db_manager)
    repo = BaseRepository(db_manager.session_factory)

    with pytest.raises(RuntimeError):
        with service.transaction() as session:
            org = Organization(name="Atomic Org", code="ATOM1")
            repo.create(org, session=session)
            branch = Branch(
                organization_id=org.id,
                name="Atomic Branch",
                code="BR-ATOM",
            )
            repo.create(branch, session=session)
            # Simulate mid-transaction failure
            raise RuntimeError("Simulated crash before commit")

    # Neither Organization nor Branch should be persisted
    assert repo.count(Organization, {"code": "ATOM1"}) == 0
    assert repo.count(Branch, {"code": "BR-ATOM"}) == 0


def test_desktop_audit_event_immutability(db_manager):
    repo = BaseRepository(db_manager.session_factory)
    audit = AuditEvent(
        organization_id="00000000-0000-0000-0000-000000000001",
        branch_id="00000000-0000-0000-0000-000000000002",
        user_id="00000000-0000-0000-0000-000000000003",
        action="USER_LOGIN",
        entity_type="user",
        entity_id="00000000-0000-0000-0000-000000000003",
        local_timestamp=datetime.now(timezone.utc).isoformat(),
    )
    created = repo.create(audit)

    with pytest.raises(ValidationError):
        repo.update(created, reason="Tampered")

    with pytest.raises(ValidationError):
        repo.soft_delete(created)


def test_online_to_offline_authentication_lifecycle(db_manager):
    offline_auth = OfflineAuthenticator()

    class MockApiClient:
        def __init__(self):
            self.online = False
            self.token = None

        def set_auth_token(self, access, refresh):
            self.token = access

        def login(self, username, password, org_code, branch_id=None, device_id=None):
            if not self.online:
                raise NetworkError("Server unreachable")
            if username == "pharmacist1" and password == "StrongPass!23":
                return {
                    "access_token": "jwt-access-123",
                    "refresh_token": "jwt-refresh-456",
                    "user": {
                        "id": "11111111-1111-1111-1111-111111111111",
                        "username": "pharmacist1",
                        "full_name": "Adaobi Pharmacist",
                        "is_org_admin": False,
                        "organization": "22222222-2222-2222-2222-222222222222",
                    },
                    "org": {
                        "id": "22222222-2222-2222-2222-222222222222",
                        "name": "Lagoon Pharmacy",
                        "code": "LAGOON",
                        "settings": {
                            "default_currency": "NGN",
                            "offline_session_max_hours": 72,
                            "offline_login_max_days": 7,
                        },
                    },
                    "branch": {
                        "id": "33333333-3333-3333-3333-333333333333",
                        "name": "Ikeja Branch",
                        "code": "BR01",
                    },
                    "permissions": ["sales.sell", "products.view"],
                    "roles": [{"name": "Pharmacist"}],
                }
            raise AuthenticationError("Invalid credentials")

    mock_api = MockApiClient()
    auth_mgr = AuthManager(mock_api, db_manager, offline_auth)

    # 1. First login while offline MUST fail
    with pytest.raises(AuthenticationError, match="first login"):
        auth_mgr.login("pharmacist1", "StrongPass!23", org_code="LAGOON")

    # 2. Online login succeeds and caches local bcrypt hash
    mock_api.online = True
    online_session = auth_mgr.login(
        "pharmacist1",
        "StrongPass!23",
        branch_id="33333333-3333-3333-3333-333333333333",
        device_id="44444444-4444-4444-4444-444444444444",
        org_code="LAGOON",
    )
    assert online_session.is_offline is False
    assert online_session.has_permission("sales.sell") is True
    assert online_session.has_permission("users.manage") is False

    # 3. Go offline and login with cached credentials
    auth_mgr.logout()
    mock_api.online = False
    offline_session = auth_mgr.login(
        "pharmacist1",
        "StrongPass!23",
        branch_id="33333333-3333-3333-3333-333333333333",
        device_id="44444444-4444-4444-4444-444444444444",
        org_code="LAGOON",
    )
    assert offline_session.is_offline is True
    assert offline_session.user_id == "11111111-1111-1111-1111-111111111111"
    assert offline_session.has_permission("sales.sell") is True
    assert offline_session.session_expires_at is not None

    # 4. Offline login with wrong password fails
    with pytest.raises(AuthenticationError):
        auth_mgr.login("pharmacist1", "WrongPass", org_code="LAGOON")

    # 5. Offline login after > 7 days since last online login fails
    with db_manager.get_session() as session:
        cred = session.query(OfflineCredential).filter_by(
            user_id="11111111-1111-1111-1111-111111111111"
        ).first()
        cred.last_online_login_at = (
            datetime.now(timezone.utc) - timedelta(days=8)
        ).isoformat()

    with pytest.raises(AuthenticationError, match="exceeded 7 days"):
        auth_mgr.login("pharmacist1", "StrongPass!23", org_code="LAGOON")
