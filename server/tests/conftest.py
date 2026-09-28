import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken
from apps.organizations.models import Organization
from apps.branches.models import Branch, Device
from apps.users.models import User, Role, Permission, RolePermission


@pytest.fixture
def test_organization(db):
    return Organization.objects.create(name='Test Org', code='TEST')


@pytest.fixture
def test_branch(db, test_organization):
    return Branch.objects.create(
        organization=test_organization,
        name='Main Branch',
        code='MAIN',
    )


@pytest.fixture
def test_device(db, test_organization, test_branch):
    return Device.objects.create(
        organization=test_organization,
        branch=test_branch,
        name='Till 1',
        code='T1',
        device_identifier='dev-123',
    )


@pytest.fixture
def test_user(db, test_organization):
    return User.objects.create_user(
        username='testuser',
        organization_id=test_organization.id,
        password='password123',
        full_name='Test User',
        is_org_admin=True,
    )


@pytest.fixture
def staff_user(db, test_organization):
    return User.objects.create_user(
        username='staffuser',
        organization_id=test_organization.id,
        password='password123',
        full_name='Staff User',
        is_org_admin=False,
    )


@pytest.fixture
def test_role(db, test_organization):
    role = Role.objects.create(organization=test_organization, name='Manager')
    perm = Permission.objects.create(
        code='manage_users',
        name='Manage Users',
        category='Users',
    )
    RolePermission.objects.create(role=role, permission=perm)
    return role


@pytest.fixture
def authenticated_client(db, test_user):
    client = APIClient()
    refresh = RefreshToken.for_user(test_user)
    client.credentials(HTTP_AUTHORIZATION=f'Bearer {refresh.access_token}')
    return client


@pytest.fixture
def staff_client(db, staff_user):
    client = APIClient()
    refresh = RefreshToken.for_user(staff_user)
    client.credentials(HTTP_AUTHORIZATION=f'Bearer {refresh.access_token}')
    return client


@pytest.fixture
def other_organization(db):
    return Organization.objects.create(name='Other Org', code='OTHER')
