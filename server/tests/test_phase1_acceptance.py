import uuid
import pytest
from django.urls import reverse
from apps.branches.models import Branch, Device
from apps.users.models import User, Role


@pytest.mark.django_db
class TestPhase1Acceptance:
    """Explicit Phase 1 acceptance tests verifying foundation architecture, security, and data integrity."""

    def test_soft_delete_never_hard_deletes(self, authenticated_client, test_branch):
        url = reverse('branch-detail', kwargs={'pk': test_branch.id})
        response = authenticated_client.delete(url)
        assert response.status_code == 204

        # Record must still exist in database with is_active=False
        test_branch.refresh_from_db()
        assert test_branch.is_active is False

    def test_cross_org_device_registration_blocked(
        self, authenticated_client, other_organization
    ):
        other_branch = Branch.objects.create(
            organization=other_organization,
            name='Other Org Branch',
            code='OB01',
        )
        response = authenticated_client.post(
            reverse('device-list'),
            {
                'branch_id': str(other_branch.id),
                'name': 'Malicious Till',
                'code': 'D9',
                'device_identifier': 'malicious-fp-001',
            },
        )
        assert response.status_code == 404
        assert not Device.objects.filter(device_identifier='malicious-fp-001').exists()

    def test_password_hash_never_leaked_in_any_user_endpoint(
        self, authenticated_client, test_user, test_organization
    ):
        # 1. Login endpoint
        login_res = authenticated_client.post(
            reverse('login'),
            {
                'username': 'testuser',
                'password': 'password123',
                'org_code': test_organization.code,
            },
        )
        assert login_res.status_code == 200
        raw_login = str(login_res.data)
        assert 'password' not in login_res.data['user']
        assert 'password_hash' not in raw_login
        assert test_user.password not in raw_login

        # 2. /auth/me/ endpoint
        me_res = authenticated_client.get(reverse('current_user'))
        assert me_res.status_code == 200
        assert 'password' not in me_res.data
        assert 'password_hash' not in me_res.data

        # 3. /users/ list and detail endpoints
        list_res = authenticated_client.get(reverse('user-list'))
        assert list_res.status_code == 200
        for u in list_res.data['results']:
            assert 'password' not in u
            assert 'password_hash' not in u

        detail_res = authenticated_client.get(
            reverse('user-detail', kwargs={'pk': test_user.id})
        )
        assert detail_res.status_code == 200
        assert 'password' not in detail_res.data
        assert 'password_hash' not in detail_res.data

    def test_multi_branch_and_multi_device_support(
        self, authenticated_client, test_organization
    ):
        # Verify architecture supports arbitrary number of branches (e.g., 7 branches) and multiple devices per branch
        branch_ids = []
        for i in range(1, 8):
            res = authenticated_client.post(
                reverse('branch-list'),
                {'name': f'Branch {i}', 'code': f'BR0{i}'},
            )
            assert res.status_code == 201
            branch_ids.append(res.data['id'])

        # Register 3 devices in Branch 1
        for d in range(1, 4):
            res = authenticated_client.post(
                reverse('device-list'),
                {
                    'branch_id': branch_ids[0],
                    'name': f'POS Terminal {d}',
                    'code': f'D{d}',
                    'device_identifier': f'fp-br1-d{d}',
                },
            )
            assert res.status_code == 201
            assert isinstance(uuid.UUID(res.data['id']), uuid.UUID)

        assert Device.objects.filter(branch_id=branch_ids[0]).count() == 3
