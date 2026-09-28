"""Phase 13 Acceptance Tests — Audit Trail UI & Retention Purge (Desktop)."""
import json
import uuid
from datetime import datetime, timedelta, timezone
import pytest
from desktop.app.auth.session import Session
from desktop.app.db.models import (
    Organization,
    Branch,
    Device,
    User,
    AuditEvent,
    SyncEvent,
)
from desktop.app.domain.enums import PermissionCode, AuditAction, AuditSource, SyncEventStatus
from desktop.app.domain.exceptions import ValidationError
from desktop.app.repositories.base_repository import BaseRepository
from desktop.app.services.audit_service import AuditService
from desktop.app.utils.date_utils import utc_now
from desktop.app.utils.uuid_utils import generate_uuid


class TestPhase13DesktopAuditAcceptance:
    """Desktop acceptance tests for Phase 13 Audit Trail and Retention Purge."""

    def _seed(self, db_manager):
        org_id = generate_uuid()
        branch_id = generate_uuid()
        device_id = generate_uuid()
        user_id = generate_uuid()

        with db_manager.get_session() as db:
            db.add(Organization(id=org_id, name="Medix Pharmacy", code="MDX"))
            db.flush()
            db.add(Branch(id=branch_id, organization_id=org_id, name="Main Branch", code="MBR"))
            db.flush()
            db.add(Device(
                id=device_id,
                organization_id=org_id,
                branch_id=branch_id,
                name="POS 1",
                code="P01",
                device_identifier="DEV-AUDIT-01",
            ))
            db.flush()
            db.add(User(
                id=user_id,
                organization_id=org_id,
                username="auditor",
                full_name="Auditor User",
                is_org_admin=True,
            ))
            db.commit()

        session = Session(
            user_id=user_id,
            username="auditor",
            full_name="Auditor User",
            organization_id=org_id,
            organization_name="Medix Pharmacy",
            branch_id=branch_id,
            branch_name="Main Branch",
            device_id=device_id,
            device_code="P01",
            permissions=[PermissionCode.AUDIT_VIEW.value],
            roles=["Auditor"],
            is_offline=True,
            is_org_admin=True,
            access_token=None,
            refresh_token=None,
            logged_in_at=utc_now(),
        )

        return {
            'org_id': org_id,
            'branch_id': branch_id,
            'device_id': device_id,
            'user_id': user_id,
            'session': session,
        }

    def test_list_and_filter_audit_events(self, db_manager):
        data = self._seed(db_manager)
        service = AuditService(db_manager)
        org_id = data['org_id']
        branch_id = data['branch_id']
        user_id = data['user_id']
        dev_id = data['device_id']

        now_utc = datetime.now(timezone.utc).isoformat()
        e1_id = generate_uuid()
        e2_id = generate_uuid()
        e3_id = generate_uuid()

        with db_manager.get_session() as db:
            db.add(AuditEvent(
                id=e1_id,
                organization_id=org_id,
                branch_id=branch_id,
                user_id=user_id,
                device_id=dev_id,
                action=AuditAction.SALE_CREATED.value,
                entity_type="sale",
                entity_id=generate_uuid(),
                data_after=json.dumps({"total": 5000}),
                local_timestamp=now_utc,
                source=AuditSource.DESKTOP.value,
                created_at=now_utc,
            ))
            db.add(AuditEvent(
                id=e2_id,
                organization_id=org_id,
                branch_id=branch_id,
                user_id=user_id,
                device_id=dev_id,
                action=AuditAction.PRICE_CHANGED.value,
                entity_type="price",
                entity_id=generate_uuid(),
                data_before=json.dumps({"price": 100}),
                data_after=json.dumps({"price": 120}),
                local_timestamp=now_utc,
                source=AuditSource.DESKTOP.value,
                created_at=now_utc,
            ))
            db.add(AuditEvent(
                id=e3_id,
                organization_id=org_id,
                branch_id=branch_id,
                user_id=user_id,
                device_id=dev_id,
                action=AuditAction.EXPENSE_CREATED.value,
                entity_type="expense",
                entity_id=generate_uuid(),
                local_timestamp=now_utc,
                source=AuditSource.DESKTOP.value,
                created_at=now_utc,
            ))
            db.commit()

        # All events for org
        events = service.list_audit_events(org_id)
        assert len(events) == 3

        # Filter by action
        price_events = service.list_audit_events(org_id, action=AuditAction.PRICE_CHANGED.value)
        assert len(price_events) == 1
        assert price_events[0]['id'] == e2_id

        # Filter by entity_type
        sale_events = service.list_audit_events(org_id, entity_type="sale")
        assert len(sale_events) == 1
        assert sale_events[0]['id'] == e1_id

        # Get single event
        single = service.get_audit_event(e2_id)
        assert single is not None
        assert single['action'] == AuditAction.PRICE_CHANGED.value

    def test_purge_synced_audit_events_lifecycle(self, db_manager):
        data = self._seed(db_manager)
        service = AuditService(db_manager)
        org_id = data['org_id']
        branch_id = data['branch_id']
        user_id = data['user_id']
        dev_id = data['device_id']

        now = datetime.now(timezone.utc)
        old_date = (now - timedelta(days=95)).isoformat()
        recent_date = (now - timedelta(days=10)).isoformat()

        # 1. Old event, confirmed synced (status = SENT) -> SHOULD BE PURGED
        e_synced_old = generate_uuid()
        # 2. Old event, NOT synced (status = PENDING) -> MUST NOT BE PURGED
        e_unsynced_old = generate_uuid()
        # 3. Recent event, confirmed synced (status = SENT) -> MUST NOT BE PURGED (within retention window)
        e_synced_recent = generate_uuid()

        with db_manager.get_session() as db:
            db.add(AuditEvent(
                id=e_synced_old,
                organization_id=org_id,
                branch_id=branch_id,
                user_id=user_id,
                device_id=dev_id,
                action=AuditAction.SALE_CREATED.value,
                entity_type="sale",
                entity_id=generate_uuid(),
                local_timestamp=old_date,
                source=AuditSource.DESKTOP.value,
                created_at=old_date,
            ))
            db.add(SyncEvent(
                id=generate_uuid(),
                branch_id=branch_id,
                device_id=dev_id,
                entity_type="audit_event",
                entity_id=e_synced_old,
                operation="CREATE",
                payload="{}",
                status=SyncEventStatus.SENT.value,
            ))

            db.add(AuditEvent(
                id=e_unsynced_old,
                organization_id=org_id,
                branch_id=branch_id,
                user_id=user_id,
                device_id=dev_id,
                action=AuditAction.SALE_CREATED.value,
                entity_type="sale",
                entity_id=generate_uuid(),
                local_timestamp=old_date,
                source=AuditSource.DESKTOP.value,
                created_at=old_date,
            ))
            db.add(SyncEvent(
                id=generate_uuid(),
                branch_id=branch_id,
                device_id=dev_id,
                entity_type="audit_event",
                entity_id=e_unsynced_old,
                operation="CREATE",
                payload="{}",
                status=SyncEventStatus.PENDING.value,
            ))

            db.add(AuditEvent(
                id=e_synced_recent,
                organization_id=org_id,
                branch_id=branch_id,
                user_id=user_id,
                device_id=dev_id,
                action=AuditAction.SALE_CREATED.value,
                entity_type="sale",
                entity_id=generate_uuid(),
                local_timestamp=recent_date,
                source=AuditSource.DESKTOP.value,
                created_at=recent_date,
            ))
            db.add(SyncEvent(
                id=generate_uuid(),
                branch_id=branch_id,
                device_id=dev_id,
                entity_type="audit_event",
                entity_id=e_synced_recent,
                operation="CREATE",
                payload="{}",
                status=SyncEventStatus.SENT.value,
            ))
            db.commit()

        # Execute purge with 90-day retention
        purged_count = service.purge_synced_audit_events(org_id, retention_days=90)
        assert purged_count == 1

        # Check remaining events
        with db_manager.get_session() as db:
            remaining_ids = [e.id for e in db.query(AuditEvent).all()]
            assert e_synced_old not in remaining_ids
            assert e_unsynced_old in remaining_ids
            assert e_synced_recent in remaining_ids

    def test_audit_event_immutability_enforced_in_repository(self, db_manager):
        data = self._seed(db_manager)
        repo = BaseRepository(db_manager.session_factory)
        org_id = data['org_id']
        branch_id = data['branch_id']
        user_id = data['user_id']

        now_utc = utc_now()
        event = AuditEvent(
            id=generate_uuid(),
            organization_id=org_id,
            branch_id=branch_id,
            user_id=user_id,
            action=AuditAction.SALE_CREATED.value,
            entity_type="sale",
            entity_id=generate_uuid(),
            local_timestamp=now_utc,
            source=AuditSource.DESKTOP.value,
            created_at=now_utc,
        )
        repo.create(event)

        # Attempting update raises ValidationError
        with pytest.raises(ValidationError):
            repo.update(event, action="MODIFIED_ACTION")

        # Attempting soft_delete raises ValidationError
        with pytest.raises(ValidationError):
            repo.soft_delete(event)
