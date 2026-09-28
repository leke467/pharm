import json
import uuid
from desktop.app.db.models import Organization, Branch, Device
from desktop.app.domain.exceptions import ValidationError
from desktop.app.services.base_service import BaseService
from shared.enums import PermissionCode, AuditAction, SyncOperation


class OrganizationService(BaseService):
    """
    Service managing Organization settings, Branches, and Devices on the desktop.
    Enforces permissions and records atomic AuditEvents and SyncEvents.
    """

    def get_organization(self, organization_id: str | None = None) -> Organization | None:
        with self.transaction() as db:
            if organization_id:
                return db.query(Organization).filter_by(id=organization_id).first()
            return db.query(Organization).first()

    def update_organization(
        self,
        user_session,
        name: str | None = None,
        code: str | None = None,
        address: str | None = None,
        phone: str | None = None,
        email: str | None = None,
        settings_updates: dict | None = None,
    ) -> Organization:
        self.require_permission(user_session, PermissionCode.SETTINGS_MANAGE.value)

        with self.transaction() as db:
            org = db.query(Organization).filter_by(id=user_session.organization_id).first()
            if not org:
                raise ValidationError("Organization not found.")

            current_settings = json.loads(org.settings or "{}")
            before_snapshot = {
                "name": org.name,
                "code": org.code,
                "address": org.address,
                "phone": org.phone,
                "email": org.email,
                "settings": current_settings.copy(),
            }

            if name is not None and name.strip():
                org.name = name.strip()
            if code is not None and code.strip():
                org.code = code.strip().upper()
            if address is not None:
                org.address = address.strip()
            if phone is not None:
                org.phone = phone.strip()
            if email is not None:
                org.email = email.strip()
            if settings_updates:
                current_settings.update(settings_updates)
                org.settings = json.dumps(current_settings)

            db.flush()
            payload = {
                "id": org.id,
                "name": org.name,
                "code": org.code,
                "address": org.address,
                "phone": org.phone,
                "email": org.email,
                "settings": current_settings,
            }
            self.record_audit_and_sync(
                db_session=db,
                user_session=user_session,
                action=AuditAction.SETTINGS_CHANGED.value,
                entity_type="organization",
                entity_id=org.id,
                operation=SyncOperation.UPDATE.value,
                payload=payload,
                data_before=before_snapshot,
                data_after=payload,
            )
            return org

    def setup_pharmacy_onboarding(
        self,
        pharmacy_name: str,
        org_code: str,
        branch_name: str,
        branch_code: str,
        admin_username: str = "admin",
        admin_full_name: str = "System Superuser (Admin)",
        admin_password: str = "admin123!",
        address: str = "",
        phone: str = "",
        cloud_server_url: str = "",
        device_code: str = "POS01",
    ) -> dict:
        """
        Initializes or reconfigures the local desktop installation for a new pharmacy
        or branch terminal (sets Organization name/code, Branch name/code, and Admin login).
        """
        from datetime import datetime, timezone
        from desktop.app.auth.offline_auth import OfflineAuthenticator
        from desktop.app.db.models import User, OfflineCredential

        pharmacy_name = (pharmacy_name or "").strip()
        org_code = (org_code or "").strip().upper()
        branch_name = (branch_name or "").strip()
        branch_code = (branch_code or "").strip().upper()
        admin_username = (admin_username or "admin").strip()
        admin_full_name = (admin_full_name or "System Superuser (Admin)").strip()
        admin_password = admin_password or "admin123!"
        device_code = (device_code or "POS01").strip().upper()[:5]

        if not pharmacy_name or not org_code:
            raise ValidationError("Pharmacy Name and Organization Code are required.")
        if not branch_name or not branch_code:
            raise ValidationError("Branch Name and Branch Code are required.")

        with self.transaction() as db:
            org = db.query(Organization).filter_by(code=org_code).first()
            if not org:
                org = db.query(Organization).first()
                if org:
                    org.name = pharmacy_name
                    org.code = org_code
                    org.address = address
                    org.phone = phone
                else:
                    org = Organization(
                        id=str(uuid.uuid4()),
                        name=pharmacy_name,
                        code=org_code,
                        address=address,
                        phone=phone,
                        settings=json.dumps({"cloud_server_url": cloud_server_url}),
                        is_active=True,
                    )
                    db.add(org)
            else:
                org.name = pharmacy_name
                if address:
                    org.address = address
                if phone:
                    org.phone = phone
            if cloud_server_url is not None:
                cur_s = json.loads(org.settings or "{}")
                cur_s["cloud_server_url"] = cloud_server_url.strip()
                cur_s["active_branch_code"] = branch_code
                org.settings = json.dumps(cur_s)
            db.flush()

            branch = db.query(Branch).filter_by(organization_id=org.id, code=branch_code).first()
            if not branch:
                branch = Branch(
                    id=str(uuid.uuid4()),
                    organization_id=org.id,
                    name=branch_name,
                    code=branch_code,
                    address=address,
                    phone=phone,
                    uses_storage_locations=True,
                    initial_stock_loaded=False,
                    is_active=True,
                )
                db.add(branch)
            else:
                branch.name = branch_name
                if address:
                    branch.address = address
                if phone:
                    branch.phone = phone
            db.flush()

            device = db.query(Device).filter_by(branch_id=branch.id).first()
            if not device:
                device = Device(
                    id=str(uuid.uuid4()),
                    organization_id=org.id,
                    branch_id=branch.id,
                    name=f"{branch_name} ({device_code})",
                    code=device_code,
                    device_identifier=f"DEV-{org_code}-{branch_code}-{device_code}",
                    is_active=True,
                )
                db.add(device)
            else:
                device.code = device_code
                device.name = f"{branch_name} ({device_code})"
            db.flush()

            user = db.query(User).filter_by(organization_id=org.id, username=admin_username).first()
            if not user:
                user = User(
                    id=str(uuid.uuid4()),
                    organization_id=org.id,
                    username=admin_username,
                    full_name=admin_full_name,
                    is_org_admin=True,
                    default_branch_id=branch.id,
                    is_active=True,
                )
                db.add(user)
            else:
                user.full_name = admin_full_name
                user.is_org_admin = True
                user.default_branch_id = branch.id
                user.is_active = True
            db.flush()

            offline_auth = OfflineAuthenticator()
            pwd_hash = offline_auth.create_offline_hash(admin_password)
            all_perms = [p.value for p in PermissionCode]
            now_utc = datetime.now(timezone.utc).isoformat()
            profile_dict = {
                "id": user.id,
                "username": user.username,
                "full_name": user.full_name,
                "organization_id": org.id,
                "organization_name": org.name,
                "branch_id": branch.id,
                "branch_name": branch.name,
                "device_id": device.id,
                "device_code": device.code,
                "is_org_admin": True,
            }

            cred = db.query(OfflineCredential).filter_by(user_id=user.id).first()
            if cred:
                cred.offline_password_hash = pwd_hash
                cred.cached_permissions = json.dumps(all_perms)
                cred.cached_roles = json.dumps([{"name": "Administrator"}])
                cred.cached_user_profile = json.dumps(profile_dict)
                cred.is_active = True
                cred.last_online_login_at = now_utc
            else:
                cred = OfflineCredential(
                    user_id=user.id,
                    offline_password_hash=pwd_hash,
                    cached_permissions=json.dumps(all_perms),
                    cached_roles=json.dumps([{"name": "Administrator"}]),
                    cached_user_profile=json.dumps(profile_dict),
                    is_active=True,
                    last_online_login_at=now_utc,
                )
                db.add(cred)
            db.flush()

            return {
                "organization_id": org.id,
                "organization_name": org.name,
                "organization_code": org.code,
                "branch_id": branch.id,
                "branch_name": branch.name,
                "branch_code": branch.code,
                "admin_username": user.username,
            }

    def create_branch(
        self,
        user_session,
        name: str,
        code: str,
        uses_storage_locations: bool = False,
        address: str = "",
        phone: str = "",
        email: str = "",
        settings: dict | None = None,
    ) -> Branch:
        self.require_permission(user_session, PermissionCode.BRANCHES_MANAGE.value)
        if not name or not code:
            raise ValidationError("Branch name and code are required.")

        with self.transaction() as db:
            existing = (
                db.query(Branch)
                .filter_by(organization_id=user_session.organization_id, code=code)
                .first()
            )
            if existing:
                raise ValidationError(f"Branch code '{code}' already exists in this organization.")

            branch = Branch(
                id=str(uuid.uuid4()),
                organization_id=user_session.organization_id,
                name=name,
                code=code,
                address=address,
                phone=phone,
                email=email,
                uses_storage_locations=uses_storage_locations,
                initial_stock_loaded=False,
                settings=json.dumps(settings or {}),
            )
            db.add(branch)
            db.flush()

            payload = {
                "id": branch.id,
                "organization_id": branch.organization_id,
                "name": branch.name,
                "code": branch.code,
                "address": branch.address,
                "phone": branch.phone,
                "email": branch.email,
                "uses_storage_locations": branch.uses_storage_locations,
                "initial_stock_loaded": branch.initial_stock_loaded,
                "settings": settings or {},
                "is_active": True,
            }
            self.record_audit_and_sync(
                db_session=db,
                user_session=user_session,
                action=AuditAction.SETTINGS_CHANGED.value,
                entity_type="branch",
                entity_id=branch.id,
                operation=SyncOperation.CREATE.value,
                payload=payload,
            )
            return branch

    def update_branch(
        self,
        user_session,
        branch_id: str,
        name: str | None = None,
        code: str | None = None,
        uses_storage_locations: bool | None = None,
        address: str | None = None,
        phone: str | None = None,
        email: str | None = None,
    ) -> Branch:
        """Updates branch name, code, storage locations setting, and contact information."""
        self.require_permission(user_session, PermissionCode.BRANCHES_MANAGE.value)
        with self.transaction() as db:
            branch = db.query(Branch).filter_by(id=branch_id, organization_id=user_session.organization_id).first()
            if not branch:
                raise ValidationError("Branch not found.")
            data_before = {
                "name": branch.name,
                "code": branch.code,
                "uses_storage_locations": branch.uses_storage_locations,
                "address": branch.address,
                "phone": branch.phone,
                "email": branch.email,
            }
            if name and name.strip():
                branch.name = name.strip()
            if code and code.strip():
                if code.strip() != branch.code:
                    exists = db.query(Branch).filter_by(organization_id=user_session.organization_id, code=code.strip()).first()
                    if exists:
                        raise ValidationError(f"Branch code '{code}' already exists.")
                    branch.code = code.strip()
            if uses_storage_locations is not None:
                branch.uses_storage_locations = uses_storage_locations
            if address is not None:
                branch.address = address.strip()
            if phone is not None:
                branch.phone = phone.strip()
            if email is not None:
                branch.email = email.strip()
            db.flush()

            data_after = {
                "name": branch.name,
                "code": branch.code,
                "uses_storage_locations": branch.uses_storage_locations,
                "address": branch.address,
                "phone": branch.phone,
                "email": branch.email,
            }
            self.record_audit_and_sync(
                db_session=db,
                user_session=user_session,
                action=AuditAction.SETTINGS_CHANGED.value,
                entity_type="branch",
                entity_id=branch.id,
                operation=SyncOperation.UPDATE.value,
                payload={"id": branch.id, **data_after},
                data_before=data_before,
                data_after=data_after,
            )
            return branch

    def list_branches(self, organization_id: str | None = None, active_only: bool = True) -> list[Branch]:
        with self.transaction() as db:
            q = db.query(Branch)
            if organization_id:
                q = q.filter_by(organization_id=organization_id)
            if active_only:
                q = q.filter_by(is_active=True)
            return q.order_by(Branch.name.asc()).all()

    def register_device(
        self,
        user_session,
        branch_id: str,
        name: str,
        code: str,
        device_identifier: str,
    ) -> Device:
        self.require_permission(user_session, PermissionCode.BRANCHES_MANAGE.value)
        if not name or not code or not device_identifier:
            raise ValidationError("Device name, short code, and identifier are required.")

        with self.transaction() as db:
            branch = (
                db.query(Branch)
                .filter_by(id=branch_id, organization_id=user_session.organization_id)
                .first()
            )
            if not branch:
                raise ValidationError("Branch does not belong to your organization.")

            existing_code = (
                db.query(Device)
                .filter_by(branch_id=branch_id, code=code)
                .first()
            )
            if existing_code:
                raise ValidationError(f"Device code '{code}' is already used in this branch.")

            device = Device(
                id=str(uuid.uuid4()),
                organization_id=user_session.organization_id,
                branch_id=branch_id,
                name=name,
                code=code,
                device_identifier=device_identifier,
                is_active=True,
            )
            db.add(device)
            db.flush()

            payload = {
                "id": device.id,
                "organization_id": device.organization_id,
                "branch_id": device.branch_id,
                "name": device.name,
                "code": device.code,
                "device_identifier": device.device_identifier,
                "is_active": True,
            }
            self.record_audit_and_sync(
                db_session=db,
                user_session=user_session,
                action=AuditAction.SETTINGS_CHANGED.value,
                entity_type="device",
                entity_id=device.id,
                operation=SyncOperation.CREATE.value,
                payload=payload,
            )
            return device
