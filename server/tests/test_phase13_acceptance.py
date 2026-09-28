"""Phase 13 Acceptance Tests — Audit Trail API & Immutability (Server)."""
import uuid
import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.organizations.models import Organization
from apps.branches.models import Branch, Device
from apps.users.models import User, Role, Permission, RolePermission, UserRole
from apps.audit.models import AuditEvent
from shared.enums import PermissionCode, AuditAction, AuditSource


@pytest.mark.django_db
class TestPhase13ServerAuditAcceptance:
    """Server acceptance tests for Phase 13 Audit Trail."""

    def _setup_org(self, code="MDX"):
        org = Organization.objects.create(name=f"Org {code}", code=code)
        branch = Branch.objects.create(organization=org, name=f"Branch {code}", code=f"B{code}")
        device = Device.objects.create(
            organization=org,
            branch=branch,
            name=f"POS {code}",
            code=f"P1",
            device_identifier=f"DEV-{code}-01",
        )
        user = User.objects.create_user(
            username=f"auditor_{code.lower()}",
            organization_id=org.id,
            password="password123",
            is_org_admin=False,
        )
        # Grant audit.view permission
        perm, _ = Permission.objects.get_or_create(
            code=PermissionCode.AUDIT_VIEW.value,
            defaults={"name": "View Audit Log", "category": "Audit"},
        )
        role = Role.objects.create(organization=org, name="Auditor Role")
        RolePermission.objects.create(role=role, permission=perm)
        UserRole.objects.create(user=user, role=role, branch=None)

        return org, branch, device, user

    def _get_client(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def test_audit_event_read_only_and_tenant_isolation(self):
        org1, branch1, dev1, user1 = self._setup_org("ORG1")
        org2, branch2, dev2, user2 = self._setup_org("ORG2")

        client1 = self._get_client(user1)
        client2 = self._get_client(user2)

        # Create audit events for Org 1
        a1 = AuditEvent.objects.create(
            organization=org1,
            branch_id=branch1.id,
            user_id=user1.id,
            device_id=dev1.id,
            action=AuditAction.SALE_CREATED.value,
            entity_type="sale",
            entity_id=uuid.uuid4(),
            data_after={"total": "100.00"},
            local_timestamp=timezone.now(),
            source=AuditSource.DESKTOP.value,
        )
        a2 = AuditEvent.objects.create(
            organization=org1,
            branch_id=branch1.id,
            user_id=user1.id,
            device_id=dev1.id,
            action=AuditAction.PRICE_CHANGED.value,
            entity_type="price",
            entity_id=uuid.uuid4(),
            data_before={"price": "50.00"},
            data_after={"price": "60.00"},
            local_timestamp=timezone.now(),
            source=AuditSource.DESKTOP.value,
        )

        # Create audit event for Org 2
        a3 = AuditEvent.objects.create(
            organization=org2,
            branch_id=branch2.id,
            user_id=user2.id,
            device_id=dev2.id,
            action=AuditAction.EXPENSE_CREATED.value,
            entity_type="expense",
            entity_id=uuid.uuid4(),
            local_timestamp=timezone.now(),
            source=AuditSource.SERVER_SYNC.value,
        )

        # 1. Org 1 user queries audit events
        res1 = client1.get('/api/v1/audit-events/')
        assert res1.status_code == status.HTTP_200_OK
        results1 = res1.data['results'] if 'results' in res1.data else res1.data
        assert len(results1) == 2
        ids1 = [str(r['id']) for r in results1]
        assert str(a1.id) in ids1
        assert str(a2.id) in ids1
        assert str(a3.id) not in ids1  # Tenant isolated!

        # 2. Org 2 user queries audit events
        res2 = client2.get('/api/v1/audit-events/')
        assert res2.status_code == status.HTTP_200_OK
        results2 = res2.data['results'] if 'results' in res2.data else res2.data
        assert len(results2) == 1
        assert str(results2[0]['id']) == str(a3.id)

        # 3. Org 1 cannot retrieve Org 2's audit event by ID
        res_cross = client1.get(f'/api/v1/audit-events/{a3.id}/')
        assert res_cross.status_code in [status.HTTP_404_NOT_FOUND, status.HTTP_403_FORBIDDEN]

    def test_audit_event_filtering(self):
        org, branch, dev, user = self._setup_org("FLT")
        client = self._get_client(user)

        tx_id = uuid.uuid4()
        corr_id = uuid.uuid4()

        e1 = AuditEvent.objects.create(
            organization=org,
            branch_id=branch.id,
            user_id=user.id,
            device_id=dev.id,
            action=AuditAction.STOCK_COUNT_STARTED.value,
            entity_type="stock_count",
            entity_id=uuid.uuid4(),
            transaction_id=tx_id,
            correlation_id=corr_id,
            local_timestamp=timezone.now(),
            source=AuditSource.DESKTOP.value,
        )
        e2 = AuditEvent.objects.create(
            organization=org,
            branch_id=branch.id,
            user_id=user.id,
            device_id=dev.id,
            action=AuditAction.STOCK_COUNT_APPROVED.value,
            entity_type="stock_count",
            entity_id=uuid.uuid4(),
            transaction_id=tx_id,
            correlation_id=corr_id,
            local_timestamp=timezone.now(),
            source=AuditSource.SERVER_SYNC.value,
        )
        e3 = AuditEvent.objects.create(
            organization=org,
            branch_id=branch.id,
            user_id=user.id,
            device_id=dev.id,
            action=AuditAction.SALE_CREATED.value,
            entity_type="sale",
            entity_id=uuid.uuid4(),
            local_timestamp=timezone.now(),
            source=AuditSource.DESKTOP.value,
        )

        # Filter by action
        res = client.get(f'/api/v1/audit-events/?action={AuditAction.SALE_CREATED.value}')
        results = res.data.get('results', res.data)
        assert len(results) == 1
        assert str(results[0]['id']) == str(e3.id)

        # Filter by entity_type
        res = client.get('/api/v1/audit-events/?entity_type=stock_count')
        results = res.data.get('results', res.data)
        assert len(results) == 2

        # Filter by transaction_id
        res = client.get(f'/api/v1/audit-events/?transaction_id={tx_id}')
        results = res.data.get('results', res.data)
        assert len(results) == 2

        # Filter by source
        res = client.get(f'/api/v1/audit-events/?source={AuditSource.SERVER_SYNC.value}')
        results = res.data.get('results', res.data)
        assert len(results) == 1
        assert str(results[0]['id']) == str(e2.id)

    def test_audit_event_immutability_enforced(self):
        org, branch, dev, user = self._setup_org("IMM")
        client = self._get_client(user)

        event = AuditEvent.objects.create(
            organization=org,
            branch_id=branch.id,
            user_id=user.id,
            device_id=dev.id,
            action=AuditAction.SALE_CREATED.value,
            entity_type="sale",
            entity_id=uuid.uuid4(),
            local_timestamp=timezone.now(),
            source=AuditSource.DESKTOP.value,
        )

        # 1. API blocks POST (405)
        post_res = client.post('/api/v1/audit-events/', {
            'action': 'HACK',
            'entity_type': 'test',
        })
        assert post_res.status_code == status.HTTP_405_METHOD_NOT_ALLOWED

        # 2. API blocks PUT/PATCH (405)
        put_res = client.put(f'/api/v1/audit-events/{event.id}/', {'action': 'HACK'})
        assert put_res.status_code == status.HTTP_405_METHOD_NOT_ALLOWED

        patch_res = client.patch(f'/api/v1/audit-events/{event.id}/', {'action': 'HACK'})
        assert patch_res.status_code == status.HTTP_405_METHOD_NOT_ALLOWED

        # 3. API blocks DELETE (405)
        del_res = client.delete(f'/api/v1/audit-events/{event.id}/')
        assert del_res.status_code == status.HTTP_405_METHOD_NOT_ALLOWED

        # 4. Model level update raises ValidationError
        with pytest.raises(ValidationError):
            event.action = "MODIFIED"
            event.save()

        # 5. Model level delete raises ValidationError
        with pytest.raises(ValidationError):
            event.delete()
