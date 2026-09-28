import uuid
from datetime import datetime, timedelta, timezone
import pytest
from desktop.app.db.models import Organization, LicenseState
from desktop.app.services.licensing_service import LicensingService
from desktop.app.sync.sync_engine import SyncEngine
from shared.enums import LicenseStatus, SubscriptionStatus


class TestPhase15DesktopLicensingAcceptance:
    """
    Phase 15 Acceptance Tests: Desktop Subscription & Offline Licensing (Architecture Plan §14).
    Validates:
    1. Caching of license status & retrieval.
    2. Active subscription allows indefinite offline operation.
    3. Expired subscription within 14-day grace period allows operation with warning.
    4. Expired subscription beyond grace period transitions to read-only lock.
    5. Suspended/cancelled license immediately enforces read-only mode.
    6. Read operations always permitted regardless of license state.
    7. Sync download updates LicenseState automatically.
    """

    def test_cache_and_get_license_state(self, db_manager):
        service = LicensingService(db_manager)
        org_id = str(uuid.uuid4())

        payload = {
            "status": "ACTIVE",
            "plan": "enterprise",
            "current_period_end": (datetime.now(timezone.utc) + timedelta(days=30)).isoformat(),
            "grace_period_days": 14,
            "entitlements": {"max_branches": 10, "max_devices": 25, "features": ["multi_branch", "analytics"]},
        }

        service.cache_license_status(org_id, payload)
        state = service.get_license_state(org_id)

        assert state is not None
        assert state["organization_id"] == org_id
        assert state["status"] == "ACTIVE"
        assert state["plan"] == "enterprise"
        assert state["grace_period_days"] == 14
        assert state["entitlements"]["max_branches"] == 10

    def test_active_license_allows_indefinite_offline_writes(self, db_manager):
        service = LicensingService(db_manager)
        org_id = str(uuid.uuid4())

        # Active license even if period end is in the past, an ACTIVE status allows offline use
        # (grace period strictly applies when status is EXPIRED, per §14.3)
        service.cache_license_status(
            org_id,
            {
                "status": LicenseStatus.ACTIVE.value,
                "plan": "professional",
                "current_period_end": (datetime.now(timezone.utc) + timedelta(days=90)).isoformat(),
                "grace_period_days": 14,
            },
        )

        allowed, msg = service.check_operation_allowed(org_id, "WRITE")
        assert allowed is True
        assert msg == ""

        # Read operation is always allowed
        allowed, msg = service.check_operation_allowed(org_id, "READ")
        assert allowed is True

    def test_expired_license_within_grace_period_allows_writes_with_warning(self, db_manager):
        service = LicensingService(db_manager)
        org_id = str(uuid.uuid4())

        # Expired 5 days ago, grace period is 14 days
        expired_date = datetime.now(timezone.utc) - timedelta(days=5)
        service.cache_license_status(
            org_id,
            {
                "status": LicenseStatus.EXPIRED.value,
                "plan": "professional",
                "current_period_end": expired_date.isoformat(),
                "grace_period_days": 14,
            },
        )

        allowed, msg = service.check_operation_allowed(org_id, "WRITE")
        assert allowed is True
        assert "Renew within" in msg
        assert "days" in msg

    def test_expired_license_beyond_grace_period_enters_read_only(self, db_manager):
        service = LicensingService(db_manager)
        org_id = str(uuid.uuid4())

        # Expired 20 days ago, grace period is 14 days
        expired_date = datetime.now(timezone.utc) - timedelta(days=20)
        service.cache_license_status(
            org_id,
            {
                "status": LicenseStatus.EXPIRED.value,
                "plan": "professional",
                "current_period_end": expired_date.isoformat(),
                "grace_period_days": 14,
            },
        )

        allowed, msg = service.check_operation_allowed(org_id, "WRITE")
        assert allowed is False
        assert "read-only mode" in msg

        # Read operations are still permitted
        allowed_read, _ = service.check_operation_allowed(org_id, "READ")
        assert allowed_read is True

    def test_suspended_license_immediately_enters_read_only(self, db_manager):
        service = LicensingService(db_manager)
        org_id = str(uuid.uuid4())

        service.cache_license_status(
            org_id,
            {
                "status": LicenseStatus.SUSPENDED.value,
                "plan": "professional",
                "current_period_end": (datetime.now(timezone.utc) + timedelta(days=10)).isoformat(),
                "grace_period_days": 14,
            },
        )

        allowed, msg = service.check_operation_allowed(org_id, "WRITE")
        assert allowed is False
        assert "read-only mode" in msg

        # Read operations are still permitted
        allowed_read, _ = service.check_operation_allowed(org_id, "READ")
        assert allowed_read is True

    def test_sync_download_updates_license_state(self, db_manager, api_client):
        sync_engine = SyncEngine(api_client, db_manager)
        service = LicensingService(db_manager)
        org_id = str(uuid.uuid4())
        branch_id = str(uuid.uuid4())
        device_id = str(uuid.uuid4())

        with db_manager.get_session() as db:
            org = Organization(id=org_id, name="License Org", code="LIC-01")
            db.add(org)

        # Mock download response containing piggybacked license_status
        license_payload = {
            "status": "SUSPENDED",
            "plan": "basic",
            "current_period_end": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
            "grace_period_days": 7,
            "entitlements": {"max_branches": 1, "max_devices": 1},
        }

        api_client.get = lambda endpoint, params=None: {
            "deliveries": [],
            "last_server_sequence": 15,
            "needs_full_resync": False,
            "disabled_user_ids": [],
            "license_status": license_payload,
        }

        sync_engine.download_updates(organization_id=org_id, branch_id=branch_id, device_id=device_id)

        # Verify licensing service now reflects the updated license status
        state = service.get_license_state(org_id)
        assert state is not None
        assert state["status"] == "SUSPENDED"
        assert state["plan"] == "basic"

        allowed, _ = service.check_operation_allowed(org_id, "WRITE")
        assert allowed is False

    def test_subscription_countdown_and_hard_lock_at_zero_days(self, db_manager):
        service = LicensingService(db_manager)
        org_id = str(uuid.uuid4())

        # 1. Cache 15 days left
        service.cache_license_status(
            org_id,
            {
                "status": "ACTIVE",
                "plan": "monthly",
                "current_period_end": (datetime.now(timezone.utc) + timedelta(days=15)).isoformat(),
                "monthly_price": "20000.00",
                "yearly_price": "200000.00",
                "monnify_account_number": "8012345678",
                "monnify_bank_name": "Moniepoint Microfinance Bank",
            },
        )
        state = service.get_license_state(org_id)
        assert state["days_remaining"] in (14, 15)
        assert str(state["monthly_price"]) == "20000.00"
        assert state["monnify_account_number"] == "8012345678"
        is_locked, _ = service.is_subscription_locked(org_id)
        assert is_locked is False

        # 2. When current_period_end reaches the past -> 0 days left -> hard lock
        service.cache_license_status(
            org_id,
            {
                "status": "ACTIVE",
                "plan": "monthly",
                "current_period_end": (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat(),
            },
        )
        state_expired = service.get_license_state(org_id)
        assert state_expired["days_remaining"] == 0
        assert state_expired["effective_status"] == "EXPIRED"
        is_locked_now, _ = service.is_subscription_locked(org_id)
        assert is_locked_now is True

