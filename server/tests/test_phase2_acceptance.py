import pytest
from django.urls import reverse
from rest_framework.test import APIClient
from apps.audit.models import AuditEvent
from apps.branches.models import Branch
from apps.users.models import Role, UserRole, Permission
from apps.users.services import seed_permissions_and_roles
from shared.enums import PermissionCode, AuditAction


@pytest.mark.django_db
class TestPhase2Acceptance:
    """Phase 2 Acceptance Tests: Authentication, RBAC Permissions, Branch Scoping, and Audit."""

    def test_seed_permissions_and_default_system_roles(self, test_organization):
        perms, roles = seed_permissions_and_roles(test_organization)
        assert len(perms) == 25
        assert Permission.objects.count() >= 25
        assert set(roles.keys()) == {
            "Organization Admin",
            "Branch Manager",
            "Pharmacist",
            "Cashier",
            "Storekeeper",
            "Auditor",
        }
        # Running a second time must be idempotent
        perms2, roles2 = seed_permissions_and_roles(test_organization)
        assert len(roles2) == 6

    def test_system_role_cannot_be_deleted(self, authenticated_client, test_organization):
        _, roles = seed_permissions_and_roles(test_organization)
        cashier_role = roles["Cashier"]
        url = reverse('role-detail', kwargs={'pk': cashier_role.id})
        res = authenticated_client.delete(url)
        assert res.status_code == 400
        cashier_role.refresh_from_db()
        assert cashier_role.is_active is True

    def test_rbac_blocks_unauthorized_writes_and_allows_authorized(
        self, staff_client, staff_user, test_organization, test_branch
    ):
        seed_permissions_and_roles(test_organization)

        # 1. Staff without permissions cannot create branches, users, or update org settings
        assert staff_client.post(
            reverse('branch-list'), {'name': 'Unauthorized Branch', 'code': 'UB01'}
        ).status_code == 403

        assert staff_client.post(
            reverse('user-list'),
            {'username': 'newstaff', 'full_name': 'New Staff', 'password': 'pass'},
        ).status_code == 403

        assert staff_client.patch(
            reverse('organization-detail', kwargs={'pk': test_organization.id}),
            {'name': 'Hacked Org Name'},
        ).status_code == 403

        # 2. Grant staff_user a role with users.manage permission
        _, roles = seed_permissions_and_roles(test_organization)
        manager_role = roles["Branch Manager"]
        UserRole.objects.create(
            user=staff_user,
            role=manager_role,
            branch=None,  # org-wide manager
        )

        # Now staff_client CAN create a user
        create_user_res = staff_client.post(
            reverse('user-list'),
            {'username': 'cashier01', 'full_name': 'Cashier One', 'password': 'pass'},
        )
        assert create_user_res.status_code == 201

        # Still cannot create a branch (Branch Manager does not have branches.manage)
        assert staff_client.post(
            reverse('branch-list'), {'name': 'Still Forbidden', 'code': 'SF01'}
        ).status_code == 403

    def test_branch_scoped_permissions_on_login(self, staff_user, test_organization):
        _, roles = seed_permissions_and_roles(test_organization)
        branch_a = Branch.objects.create(
            organization=test_organization, name='Ikeja Branch', code='IKJ'
        )
        branch_b = Branch.objects.create(
            organization=test_organization, name='Lekki Branch', code='LEK'
        )

        # Staff user is Cashier at Branch A, and Branch Manager at Branch B
        UserRole.objects.create(
            user=staff_user, role=roles["Cashier"], branch=branch_a
        )
        UserRole.objects.create(
            user=staff_user, role=roles["Branch Manager"], branch=branch_b
        )

        client = APIClient()
        res_a = client.post(
            reverse('login'),
            {
                'username': staff_user.username,
                'password': 'password123',
                'org_code': test_organization.code,
                'branch_id': str(branch_a.id),
            },
        )
        assert res_a.status_code == 200
        perms_a = set(res_a.data['permissions'])
        assert PermissionCode.SALES_SELL.value in perms_a
        assert PermissionCode.USERS_MANAGE.value not in perms_a

        res_b = client.post(
            reverse('login'),
            {
                'username': staff_user.username,
                'password': 'password123',
                'org_code': test_organization.code,
                'branch_id': str(branch_b.id),
            },
        )
        assert res_b.status_code == 200
        perms_b = set(res_b.data['permissions'])
        assert PermissionCode.USERS_MANAGE.value in perms_b
        assert PermissionCode.STOCK_COUNTS_APPROVE.value in perms_b

    def test_audit_events_recorded_for_auth_and_settings(
        self, authenticated_client, test_user, test_organization, test_branch
    ):
        # Login creates USER_LOGIN audit event
        client = APIClient()
        login_res = client.post(
            reverse('login'),
            {
                'username': test_user.username,
                'password': 'password123',
                'org_code': test_organization.code,
                'branch_id': str(test_branch.id),
            },
        )
        assert login_res.status_code == 200
        assert AuditEvent.objects.filter(
            organization=test_organization,
            user_id=test_user.id,
            action=AuditAction.USER_LOGIN.value,
        ).exists()

        # Organization update creates SETTINGS_CHANGED audit event
        patch_res = authenticated_client.patch(
            reverse('organization-detail', kwargs={'pk': test_organization.id}),
            {'phone': '+2348000000000'},
        )
        assert patch_res.status_code == 200
        assert AuditEvent.objects.filter(
            organization=test_organization,
            action=AuditAction.SETTINGS_CHANGED.value,
            entity_type='organization',
        ).exists()
