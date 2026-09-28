import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
import uuid
from apps.organizations.models import Organization
from apps.branches.models import Branch, Device
from apps.users.models import User, Role, Permission, RolePermission, UserRole
from apps.audit.models import AuditEvent


@pytest.mark.django_db
class TestModels:
    def test_organization_creation(self, test_organization):
        assert test_organization.pk is not None
        assert isinstance(test_organization.pk, uuid.UUID)
        assert test_organization.code == 'TEST'
        assert test_organization.settings['default_currency'] == 'NGN'
        assert test_organization.settings['offline_session_max_hours'] == 72

    def test_branch_belongs_to_organization(self, test_branch, test_organization):
        assert test_branch.organization == test_organization
        assert Branch.objects.filter(organization=test_organization).count() == 1

    def test_device_belongs_to_branch_and_org(self, test_device, test_branch, test_organization):
        assert test_device.branch == test_branch
        assert test_device.organization == test_organization

    def test_user_creation(self, test_user, test_organization):
        assert test_user.organization == test_organization
        assert test_user.username == 'testuser'

    def test_role_permission(self, test_role):
        assert test_role.permissions.count() == 1
        assert test_role.permissions.first().permission.code == 'manage_users'

    def test_user_role_branch_scope(self, test_user, test_role, test_branch):
        ur = UserRole.objects.create(user=test_user, role=test_role, branch=test_branch)
        assert ur.branch == test_branch

    def test_user_role_org_wide(self, test_user, test_role):
        ur = UserRole.objects.create(user=test_user, role=test_role, branch=None)
        assert ur.branch is None

    def test_unique_constraints(self, test_organization, test_user):
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                Organization.objects.create(name='Duplicate', code='TEST')
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                User.objects.create_user(
                    username='testuser',
                    organization_id=test_organization.id,
                    password='123',
                )

    def test_audit_event_immutability(self, test_organization, test_branch, test_user):
        event = AuditEvent.objects.create(
            organization=test_organization,
            branch_id=test_branch.id,
            user_id=test_user.id,
            action='USER_LOGIN',
            entity_type='user',
            entity_id=test_user.id,
            local_timestamp=timezone.now(),
            source='SERVER',
        )
        event.reason = "Attempted tamper"
        with pytest.raises(ValidationError):
            event.save()
        with pytest.raises(ValidationError):
            event.delete()
