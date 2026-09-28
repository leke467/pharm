"""Phase 15 Acceptance Tests — Subscription & Licensing (Server)."""
import uuid
from datetime import timedelta
import pytest
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.organizations.models import Organization
from apps.branches.models import Branch, Device
from apps.users.models import User, Role, Permission, RolePermission, UserRole
from apps.licensing.models import Subscription, Entitlement, License
from shared.enums import PermissionCode, LicenseStatus, SubscriptionStatus


@pytest.mark.django_db
class TestPhase15ServerLicensingAcceptance:
    """Server acceptance tests for Phase 15 Subscription & Licensing."""

    @pytest.fixture
    def setup_data(self):
        org = Organization.objects.create(name="Licensed Org", code="LIC")
        branch = Branch.objects.create(organization=org, name="Main Branch", code="MBR")
        device = Device.objects.create(
            organization=org,
            branch=branch,
            name="POS 1",
            code="P1",
            device_identifier="DEV-LIC-01",
        )
        user = User.objects.create_user(
            username="license_admin",
            organization_id=org.id,
            password="password123",
            full_name="License Admin",
            is_org_admin=False,
        )

        perm, _ = Permission.objects.get_or_create(
            code=PermissionCode.SUBSCRIPTIONS_MANAGE.value,
            defaults={"name": "Manage Subscriptions", "category": "Subscriptions"},
        )
        role = Role.objects.create(organization=org, name="Subscription Manager")
        RolePermission.objects.create(role=role, permission=perm)
        UserRole.objects.create(user=user, role=role, branch=None)

        client = APIClient()
        client.force_authenticate(user=user)

        return {
            'org': org,
            'branch': branch,
            'device': device,
            'user': user,
            'client': client,
        }

    def test_subscription_and_entitlement_crud(self, setup_data):
        client = setup_data['client']
        org = setup_data['org']

        now = timezone.now()
        end = now + timedelta(days=365)

        # 1. Create Subscription
        sub_res = client.post('/api/v1/subscriptions/', {
            'plan': 'enterprise',
            'status': SubscriptionStatus.ACTIVE.value,
            'current_period_start': now.isoformat(),
            'current_period_end': end.isoformat(),
            'grace_period_days': 14,
            'auto_renew': True,
        }, format='json')
        assert sub_res.status_code == status.HTTP_201_CREATED, sub_res.data
        sub_id = sub_res.data['id']
        assert sub_res.data['plan'] == 'enterprise'
        assert sub_res.data['is_expired'] is False

        # 2. Add Entitlements
        ent_res1 = client.post('/api/v1/entitlements/', {
            'subscription': sub_id,
            'feature_code': 'max_branches',
            'feature_value': '25',
        }, format='json')
        assert ent_res1.status_code == status.HTTP_201_CREATED

        ent_res2 = client.post('/api/v1/entitlements/', {
            'subscription': sub_id,
            'feature_code': 'max_devices',
            'feature_value': '50',
        }, format='json')
        assert ent_res2.status_code == status.HTTP_201_CREATED

        # 3. Add License Key
        lic_res = client.post('/api/v1/licenses/', {
            'license_key': 'LIC-ENT-2026-X99-ABCD',
            'status': LicenseStatus.ACTIVE.value,
            'issued_at': now.isoformat(),
            'expires_at': end.isoformat(),
        }, format='json')
        assert lic_res.status_code == status.HTTP_201_CREATED
        assert lic_res.data['license_key'] == 'LIC-ENT-2026-X99-ABCD'

    def test_sync_download_piggybacks_subscription_license_status(self, setup_data):
        client = setup_data['client']
        org = setup_data['org']
        branch = setup_data['branch']
        device = setup_data['device']

        now = timezone.now()
        end = now + timedelta(days=180)

        # Create active enterprise subscription with entitlements
        sub = Subscription.objects.create(
            organization=org,
            plan='enterprise',
            status=SubscriptionStatus.ACTIVE.value,
            current_period_start=now,
            current_period_end=end,
            grace_period_days=14,
        )
        Entitlement.objects.create(
            organization=org,
            subscription=sub,
            feature_code='max_branches',
            feature_value='10',
        )
        Entitlement.objects.create(
            organization=org,
            subscription=sub,
            feature_code='max_devices',
            feature_value='20',
        )

        # Download sync
        res = client.get(f'/api/v1/sync/download/?device_id={device.id}&branch_id={branch.id}')
        assert res.status_code == status.HTTP_200_OK

        lic_data = res.data.get('license_status')
        assert lic_data is not None
        assert lic_data['status'] == SubscriptionStatus.ACTIVE.value
        assert lic_data['plan'] == 'enterprise'
        assert lic_data['grace_period_days'] == 14
        assert lic_data['entitlements']['max_branches'] == '10'
        assert lic_data['entitlements']['max_devices'] == '20'

    def test_sync_download_reflects_expired_and_suspended_subscription(self, setup_data):
        client = setup_data['client']
        org = setup_data['org']
        branch = setup_data['branch']
        device = setup_data['device']

        now = timezone.now()
        past = now - timedelta(days=5)

        # Create expired subscription
        sub = Subscription.objects.create(
            organization=org,
            plan='starter',
            status=SubscriptionStatus.EXPIRED.value,
            current_period_start=past - timedelta(days=30),
            current_period_end=past,
            grace_period_days=14,
        )

        res = client.get(f'/api/v1/sync/download/?device_id={device.id}&branch_id={branch.id}')
        assert res.status_code == status.HTTP_200_OK
        lic_data = res.data['license_status']
        assert lic_data['status'] == SubscriptionStatus.EXPIRED.value

        # Update to suspended
        sub.status = LicenseStatus.SUSPENDED.value
        sub.save()

        res2 = client.get(f'/api/v1/sync/download/?device_id={device.id}&branch_id={branch.id}')
        assert res2.status_code == status.HTTP_200_OK
        assert res2.data['license_status']['status'] == LicenseStatus.SUSPENDED.value

    def test_monnify_subscription_status_and_payment_flow(self, setup_data):
        client = setup_data['client']
        org = setup_data['org']

        # 1. Public/Authenticated status endpoint auto-creates subscription + virtual account
        res_status = client.get(f'/api/v1/licensing/status/?org_code={org.code}')
        assert res_status.status_code == status.HTTP_200_OK
        data = res_status.data
        assert data['organization_code'] == org.code
        assert data['days_remaining'] > 0
        assert data['monnify_account_number'] != ''
        assert data['monthly_price'] == '25000.00'
        assert data['yearly_price'] == '250000.00'

        # 2. Set subscription to 0 days left (expired)
        sub = Subscription.objects.get(organization=org)
        sub.current_period_end = timezone.now() - timedelta(days=1)
        sub.status = SubscriptionStatus.EXPIRED.value
        sub.save()

        res_expired = client.get(f'/api/v1/licensing/status/?org_code={org.code}')
        assert res_expired.data['days_remaining'] == 0
        assert res_expired.data['status'] == SubscriptionStatus.EXPIRED.value

        # 3. Initiate Monthly Monnify checkout
        res_init = client.post(
            '/api/v1/licensing/monnify/initiate/',
            {'org_code': org.code, 'billing_cycle': 'MONTHLY'},
            format='json',
        )
        assert res_init.status_code == status.HTTP_201_CREATED
        pay_ref = res_init.data['payment_reference']
        assert res_init.data['days_credited'] == 30
        assert 'checkout_url' in res_init.data

        # 4. Complete checkout via local Monnify checkout endpoint
        res_checkout = client.post(
            f'/api/v1/licensing/monnify/checkout/{pay_ref}/',
            {'payment_method': 'MONNIFY_CHECKOUT'},
        )
        assert res_checkout.status_code == status.HTTP_200_OK

        # 5. Verify payment and confirm +30 days credited
        res_verify = client.post(
            '/api/v1/licensing/monnify/verify/',
            {'org_code': org.code, 'payment_reference': pay_ref},
            format='json',
        )
        assert res_verify.status_code == status.HTTP_200_OK
        assert res_verify.data['paid'] is True
        assert res_verify.data['subscription']['days_remaining'] >= 29
        assert res_verify.data['subscription']['status'] == SubscriptionStatus.ACTIVE.value

