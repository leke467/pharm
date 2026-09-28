import json
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from desktop.app.db.models import AuditEvent, SyncEvent
from desktop.app.domain.exceptions import AuthenticationError, PermissionDeniedError
from shared.enums import SYNC_DEPENDENCY_LEVELS, SYNC_SCHEMA_VERSION, AuditSource


class BaseService:
    """
    Base service class providing transactional session management,
    service-layer permission enforcement, and atomic AuditEvent + SyncEvent recording.
    """

    def __init__(self, db_manager):
        self.db_manager = db_manager

    @contextmanager
    def transaction(self):
        with self.db_manager.get_session() as session:
            yield session

    def require_permission(self, user_session, permission_code: str):
        """
        Enforces permission checks and offline session expiration in the service layer
        (Architecture Plan §5.4 & §5.7).
        """
        if user_session is None:
            raise AuthenticationError("Authentication required.")

        if user_session.is_offline and user_session.session_expires_at:
            now = datetime.now(timezone.utc)
            expires = datetime.fromisoformat(user_session.session_expires_at)
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            if now > expires:
                raise AuthenticationError(
                    "Offline session has expired. Please re-authenticate."
                )

        if not user_session.has_permission(permission_code):
            raise PermissionDeniedError(
                f"Permission denied: '{permission_code}' is required."
            )

    def record_audit_and_sync(
        self,
        db_session,
        user_session,
        action: str,
        entity_type: str,
        entity_id: str,
        operation: str,
        payload: dict,
        data_before: dict | None = None,
        data_after: dict | None = None,
        reason: str = "",
        correlation_id: str | None = None,
        transaction_id: str | None = None,
    ):
        """
        Atomically appends an immutable AuditEvent and SyncEvent(s) within the active
        SQLite transaction (`db_session`).
        """
        corr_id = correlation_id or str(uuid.uuid4())
        now_utc = datetime.now(timezone.utc).isoformat()
        now_local = datetime.now().astimezone().isoformat()
        branch_id = user_session.branch_id or "00000000-0000-0000-0000-000000000000"
        device_id = user_session.device_id or "00000000-0000-0000-0000-000000000000"

        audit = AuditEvent(
            id=str(uuid.uuid4()),
            organization_id=user_session.organization_id,
            branch_id=branch_id,
            user_id=user_session.user_id,
            device_id=device_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            data_before=json.dumps(data_before) if data_before is not None else None,
            data_after=json.dumps(data_after if data_after is not None else payload),
            reason=reason,
            correlation_id=corr_id,
            transaction_id=transaction_id or entity_id,
            local_timestamp=now_local,
            is_offline=user_session.is_offline,
            source=AuditSource.DESKTOP.value,
            created_at=now_utc,
        )
        db_session.add(audit)

        dep_level = SYNC_DEPENDENCY_LEVELS.get(entity_type, 5)
        entity_sync = SyncEvent(
            id=str(uuid.uuid4()),
            branch_id=branch_id,
            device_id=device_id,
            entity_type=entity_type,
            entity_id=entity_id,
            operation=operation,
            payload=json.dumps(payload),
            correlation_id=corr_id,
            dependency_level=dep_level,
            schema_version=SYNC_SCHEMA_VERSION,
            local_created_at=now_local,
            max_retries=10,
            status="PENDING",
        )
        db_session.add(entity_sync)

        audit_sync = SyncEvent(
            id=str(uuid.uuid4()),
            branch_id=branch_id,
            device_id=device_id,
            entity_type="audit_event",
            entity_id=audit.id,
            operation="CREATE",
            payload=json.dumps({
                "id": audit.id,
                "organization_id": audit.organization_id,
                "branch_id": audit.branch_id,
                "user_id": audit.user_id,
                "device_id": audit.device_id,
                "action": audit.action,
                "entity_type": audit.entity_type,
                "entity_id": audit.entity_id,
                "data_before": data_before,
                "data_after": data_after if data_after is not None else payload,
                "reason": reason,
                "correlation_id": corr_id,
                "transaction_id": audit.transaction_id,
                "local_timestamp": now_local,
                "is_offline": user_session.is_offline,
                "source": AuditSource.DESKTOP.value,
            }),
            correlation_id=corr_id,
            dependency_level=SYNC_DEPENDENCY_LEVELS["audit_event"],
            schema_version=SYNC_SCHEMA_VERSION,
            local_created_at=now_local,
            max_retries=50,  # Architecture Decision: 50 retries for audit events
            status="PENDING",
        )
        db_session.add(audit_sync)
        db_session.flush()
        return audit, entity_sync, audit_sync

    def resolve_device(self, db, branch_id: str | None, device_id: str | None = None):
        """
        Resolves or creates a valid Device row for the given branch_id so foreign key
        constraints are always satisfied.
        """
        if not branch_id or not str(branch_id).strip():
            return None
        from desktop.app.db.models import Branch, Device
        branch = db.query(Branch).filter_by(id=str(branch_id).strip()).first()
        if not branch:
            return None

        device = None
        if device_id and str(device_id).strip():
            device = db.query(Device).filter_by(id=str(device_id).strip()).first()
        if not device:
            device = db.query(Device).filter_by(branch_id=branch.id, is_active=True).first()
        if not device:
            new_id = (
                str(device_id).strip()
                if (device_id and str(device_id).strip() and len(str(device_id).strip()) == 36)
                else str(uuid.uuid4())
            )
            device = Device(
                id=new_id,
                organization_id=branch.organization_id,
                branch_id=branch.id,
                name="Terminal 1",
                code="T1",
                device_identifier=f"DEV-{branch.code or 'BR'}-T1",
                is_active=True,
            )
            db.add(device)
            db.flush()
        return device
