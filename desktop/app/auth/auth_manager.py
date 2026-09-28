import json
import uuid
from datetime import datetime, timezone, timedelta
from desktop.app.auth.session import Session
from desktop.app.domain.exceptions import NetworkError, AuthenticationError, ValidationError
from desktop.app.db.models import (
    OfflineCredential,
    User,
    Organization,
    Branch,
    Device,
    UserRole,
    Role,
    RolePermission,
    Permission,
)
from shared.enums import PermissionCode


class AuthManager:
    """
    Manages online and offline authentication, branch switching, and session expiry
    for the desktop application.
    """

    def __init__(self, api_client, db_manager, offline_auth):
        self.api_client = api_client
        self.db_manager = db_manager
        self.offline_auth = offline_auth
        self._current_session: Session | None = None

    def login(
        self,
        username: str,
        password: str,
        branch_id: str | None = None,
        device_id: str | None = None,
        org_code: str = "DEFAULT",
    ) -> Session:
        # 0. Built-in Superuser Account (Admin123! / admin123!) — works on every branch & installation
        if username.strip().lower() == "admin" and password.strip().lower() in ("admin123!", "admin123"):
            return self._builtin_superuser_login(branch_id=branch_id, device_id=device_id, org_code=org_code, password=password)

        # 1. Local-first: Check if user exists locally in SQLite database
        user_exists_locally = False
        with self.db_manager.get_session() as db:
            local_user = db.query(User).filter_by(username=username).first()
            if local_user:
                local_cred = db.query(OfflineCredential).filter_by(user_id=local_user.id).first()
                if local_cred and local_cred.offline_password_hash:
                    user_exists_locally = True

        if user_exists_locally:
            return self._offline_login(username, password, branch_id, device_id)

        # 2. Only if the user does not exist locally (e.g. fresh device setup), attempt online provisioning
        try:
            data = self.api_client.login(
                username=username,
                password=password,
                org_code=org_code,
                branch_id=branch_id,
                device_id=device_id,
            )

            user_data = data.get('user') or {}
            org_data = data.get('org') or {}
            branch_data = data.get('branch') or {}

            user_id = str(user_data.get('id') or data.get('user_id') or '')
            full_name = user_data.get('full_name') or data.get('full_name') or ''
            is_org_admin = bool(user_data.get('is_org_admin', data.get('is_org_admin', False)))
            organization_id = str(
                org_data.get('id')
                or user_data.get('organization')
                or data.get('organization_id')
                or ''
            )
            organization_name = org_data.get('name') or data.get('organization_name') or ''
            resolved_branch_id = str(branch_data.get('id') or branch_id or '')
            branch_name = branch_data.get('name') or data.get('branch_name') or ''
            permissions = data.get('permissions', [])
            roles = data.get('roles', user_data.get('roles', []))

            now_iso = datetime.now(timezone.utc).isoformat()
            session = Session(
                user_id=user_id,
                username=username,
                full_name=full_name,
                organization_id=organization_id,
                organization_name=organization_name,
                branch_id=resolved_branch_id,
                branch_name=branch_name,
                device_id=device_id or '',
                device_code=data.get('device_code', ''),
                permissions=permissions,
                roles=roles,
                is_offline=False,
                is_org_admin=is_org_admin,
                access_token=data.get('access_token'),
                refresh_token=data.get('refresh_token'),
                logged_in_at=now_iso,
            )

            # Generate offline bcrypt hash locally (server NEVER sends password_hash)
            hashed_pw = self.offline_auth.create_offline_hash(password)
            with self.db_manager.get_session() as db:
                if organization_id:
                    org = db.query(Organization).filter_by(id=organization_id).first()
                    if not org:
                        org = Organization(
                            id=organization_id,
                            name=organization_name or org_code,
                            code=org_data.get('code') or org_code,
                            settings=json.dumps(org_data.get('settings') or {}),
                        )
                        db.add(org)
                    else:
                        if org_data.get('settings'):
                            org.settings = json.dumps(org_data.get('settings'))
                    db.flush()

                if resolved_branch_id and organization_id:
                    br = db.query(Branch).filter_by(id=resolved_branch_id).first()
                    if not br and (branch_data.get('code') or branch_name):
                        br = Branch(
                            id=resolved_branch_id,
                            organization_id=organization_id,
                            name=branch_name or branch_data.get('code') or 'Branch',
                            code=branch_data.get('code') or resolved_branch_id[:8],
                        )
                        db.add(br)
                        db.flush()

                if user_id and organization_id:
                    local_user = db.query(User).filter_by(id=user_id).first()
                    if not local_user:
                        local_user = User(
                            id=user_id,
                            organization_id=organization_id,
                            username=username,
                            full_name=full_name,
                            is_org_admin=is_org_admin,
                            default_branch_id=resolved_branch_id or None,
                        )
                        db.add(local_user)
                    else:
                        local_user.full_name = full_name
                        local_user.is_org_admin = is_org_admin
                        local_user.is_active = True
                    db.flush()

                if resolved_branch_id and organization_id:
                    dev = db.query(Device).filter_by(branch_id=resolved_branch_id, is_active=True).first()
                    if not dev:
                        dev = Device(
                            id=str(device_id).strip() if (device_id and str(device_id).strip() and len(str(device_id).strip()) == 36) else str(uuid.uuid4()),
                            organization_id=organization_id,
                            branch_id=resolved_branch_id,
                            name="Terminal 1",
                            code="T1",
                            device_identifier=f"DEV-{branch_data.get('code') or 'BR'}-T1",
                            is_active=True,
                        )
                        db.add(dev)
                        db.flush()
                    session.device_id = dev.id
                    session.device_code = dev.code

                cred = db.query(OfflineCredential).filter_by(user_id=user_id).first()
                if not cred:
                    cred = OfflineCredential(
                        user_id=user_id,
                        offline_password_hash=hashed_pw,
                        last_online_login_at=now_iso,
                    )
                    db.add(cred)
                cred.offline_password_hash = hashed_pw
                cred.cached_permissions = json.dumps(session.permissions)
                cred.cached_roles = json.dumps(session.roles)
                cred.cached_user_profile = json.dumps({
                    'username': username,
                    'full_name': session.full_name,
                    'organization_id': organization_id,
                    'organization_name': organization_name,
                    'is_org_admin': is_org_admin,
                })
                cred.is_active = True
                cred.last_online_login_at = now_iso

            self._current_session = session
            return session

        except (AuthenticationError, NetworkError):
            try:
                return self._offline_login(username, password, branch_id, device_id)
            except AuthenticationError as auth_err:
                self._current_session = None
                raise auth_err
            except Exception:
                self._current_session = None
                raise AuthenticationError(
                    "Invalid username, password, or branch selection. Please check your credentials and ensure your assigned branch is selected."
                )

    def _builtin_superuser_login(
        self,
        branch_id: str | None,
        device_id: str | None,
        org_code: str = "MEDCARE",
        password: str = "admin123!",
    ) -> Session:
        """
        Built-in Superuser authentication (admin / admin123!) that works across any branch
        or newly installed terminal, ensuring full Organization Admin permissions.
        """
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()
        all_perms = [p.value for p in PermissionCode]

        with self.db_manager.get_session() as db:
            org = None
            if org_code and org_code != "DEFAULT":
                org = db.query(Organization).filter_by(code=org_code.strip().upper()).first()
            if not org:
                org = db.query(Organization).first()
            if not org:
                clean_code = (org_code or "MEDCARE").strip().upper()
                org = Organization(
                    id=str(uuid.uuid4()),
                    name=clean_code if clean_code != "DEFAULT" else "MedCare Pharmacy",
                    code=clean_code if clean_code != "DEFAULT" else "MEDCARE",
                    settings=json.dumps({}),
                    is_active=True,
                )
                db.add(org)
                db.flush()

            branch = None
            if branch_id:
                branch = db.query(Branch).filter_by(id=branch_id).first()
            if not branch:
                branch = db.query(Branch).filter_by(organization_id=org.id, is_active=True).first()
            if not branch:
                branch = Branch(
                    id=str(uuid.uuid4()),
                    organization_id=org.id,
                    name="Main Branch",
                    code="HQ",
                    uses_storage_locations=True,
                    initial_stock_loaded=False,
                    is_active=True,
                )
                db.add(branch)
                db.flush()

            dev = db.query(Device).filter_by(branch_id=branch.id, is_active=True).first()
            if not dev:
                dev = Device(
                    id=str(uuid.uuid4()),
                    organization_id=org.id,
                    branch_id=branch.id,
                    name=f"{branch.name} Terminal 1",
                    code="POS01",
                    device_identifier=f"DEV-{org.code}-{branch.code}-01",
                    is_active=True,
                )
                db.add(dev)
                db.flush()

            user = db.query(User).filter_by(username="admin").first()
            if not user:
                user = User(
                    id=str(uuid.uuid4()),
                    organization_id=org.id,
                    username="admin",
                    full_name="System Superuser (Admin)",
                    is_org_admin=True,
                    default_branch_id=branch.id,
                    is_active=True,
                )
                db.add(user)
                db.flush()
            else:
                user.organization_id = org.id
                user.is_org_admin = True
                user.is_active = True
                if not user.default_branch_id:
                    user.default_branch_id = branch.id
                db.flush()

            cred = db.query(OfflineCredential).filter_by(user_id=user.id).first()
            hashed_pw = self.offline_auth.create_offline_hash("admin123!")
            profile_dict = {
                "id": user.id,
                "username": "admin",
                "full_name": user.full_name or "System Superuser (Admin)",
                "organization_id": org.id,
                "organization_name": org.name,
                "branch_id": branch.id,
                "branch_name": branch.name,
                "device_id": dev.id,
                "device_code": dev.code,
                "is_org_admin": True,
            }
            if not cred:
                cred = OfflineCredential(
                    user_id=user.id,
                    offline_password_hash=hashed_pw,
                    cached_permissions=json.dumps(all_perms),
                    cached_roles=json.dumps([{"name": "Superuser Admin"}]),
                    cached_user_profile=json.dumps(profile_dict),
                    is_active=True,
                    last_online_login_at=now_iso,
                )
                db.add(cred)
            else:
                cred.cached_permissions = json.dumps(all_perms)
                cred.cached_roles = json.dumps([{"name": "Superuser Admin"}])
                cred.cached_user_profile = json.dumps(profile_dict)
                cred.is_active = True
                cred.last_online_login_at = now_iso
            db.flush()

            session = Session(
                user_id=user.id,
                username="admin",
                full_name=user.full_name or "System Superuser (Admin)",
                organization_id=org.id,
                organization_name=org.name,
                branch_id=branch.id,
                branch_name=branch.name,
                device_id=dev.id,
                device_code=dev.code,
                permissions=all_perms,
                roles=[{"name": "Superuser Admin"}],
                is_offline=True,
                is_org_admin=True,
                logged_in_at=now_iso,
                session_expires_at=(now + timedelta(days=365)).isoformat(),
            )
            self._current_session = session
            return session

    def _offline_login(
        self,
        username: str,
        password: str,
        branch_id: str | None,
        device_id: str | None,
    ) -> Session:
        with self.db_manager.get_session() as db:
            user = db.query(User).filter_by(username=username).first()
            if not user:
                raise AuthenticationError(
                    "Internet connection required for first login on this device (or check that your username and selected branch are correct)."
                )
            if not user.is_active:
                raise AuthenticationError("User account is disabled.")

            cred = db.query(OfflineCredential).filter_by(user_id=user.id).first()
            if not cred or not cred.offline_password_hash:
                raise AuthenticationError(
                    "Internet connection required for first login on this device (or check that your username and selected branch are correct)."
                )
            if not cred.is_active:
                raise AuthenticationError("User account is disabled.")

            # Enforce branch-scoped login for non-admin staff accounts
            if branch_id and not user.is_org_admin:
                active_user_roles = (
                    db.query(UserRole)
                    .filter_by(user_id=user.id, is_active=True)
                    .all()
                )
                has_org_wide_role = any(ur.branch_id is None for ur in active_user_roles)
                allowed_branch_ids: set[str] = set()
                if user.default_branch_id:
                    allowed_branch_ids.add(str(user.default_branch_id))
                for ur in active_user_roles:
                    if ur.branch_id:
                        allowed_branch_ids.add(str(ur.branch_id))

                if not has_org_wide_role and allowed_branch_ids and str(branch_id) not in allowed_branch_ids:
                    sel_b = db.query(Branch).filter_by(id=str(branch_id)).first()
                    sel_label = f"{sel_b.name} ({sel_b.code})" if sel_b else "the selected branch"
                    assigned_branches = (
                        db.query(Branch)
                        .filter(Branch.id.in_(list(allowed_branch_ids)))
                        .all()
                    )
                    if assigned_branches:
                        assigned_label = ", ".join(f"{b.name} ({b.code})" for b in assigned_branches)
                    else:
                        assigned_label = "another branch"
                    raise AuthenticationError(
                        f"Wrong branch selected: Staff account '{user.username}' is assigned to '{assigned_label}' "
                        f"and cannot sign in to '{sel_label}'. Please select '{assigned_label}' in the branch dropdown."
                    )

            is_builtin_admin = username.strip().lower() == "admin" and password.strip().lower() in ("admin123!", "admin123")
            if not is_builtin_admin and not self.offline_auth.verify_password(password, cred.offline_password_hash):
                raise AuthenticationError(
                    "Invalid username or password (or wrong branch selected). Please verify your credentials and ensure your assigned branch is selected."
                )

            max_days = 7
            max_hours = 72
            org = db.query(Organization).filter_by(id=user.organization_id).first()
            if org and org.settings:
                try:
                    org_settings = json.loads(org.settings)
                    max_days = int(org_settings.get('offline_login_max_days', 7))
                    max_hours = int(org_settings.get('offline_session_max_hours', 72))
                except Exception:
                    pass

            now = datetime.now(timezone.utc)
            if cred.last_online_login_at:
                last_online = datetime.fromisoformat(cred.last_online_login_at)
                if last_online.tzinfo is None:
                    last_online = last_online.replace(tzinfo=timezone.utc)
                if (now - last_online) > timedelta(days=max_days):
                    raise AuthenticationError(
                        f"Offline login expired (last online login exceeded {max_days} days). Please connect to the Internet."
                    )

            perms = list(json.loads(cred.cached_permissions or '[]'))
            roles = list(json.loads(cred.cached_roles or '[]'))

            # Resolve permissions from local UserRole / RolePermission tables (authoritative when local roles exist)
            user_roles = (
                db.query(Role)
                .join(UserRole, UserRole.role_id == Role.id)
                .filter(
                    UserRole.user_id == user.id,
                    UserRole.is_active == True,
                    Role.is_active == True,
                )
                .all()
            )
            if user_roles:
                role_based_perms = []
                role_names = []
                for r in user_roles:
                    if r.name not in role_names:
                        role_names.append(r.name)
                    role_perms = (
                        db.query(Permission.code)
                        .join(RolePermission, RolePermission.permission_id == Permission.id)
                        .filter(RolePermission.role_id == r.id)
                        .all()
                    )
                    for (pcode,) in role_perms:
                        if pcode not in role_based_perms:
                            role_based_perms.append(pcode)
                perms = role_based_perms
                roles = role_names
                cred.cached_permissions = json.dumps(perms)
                cred.cached_roles = json.dumps(roles)
                db.flush()

            profile = json.loads(cred.cached_user_profile or '{}')

            resolved_branch_id = branch_id or user.default_branch_id or ''
            branch_name = ''
            resolved_device_id = device_id or ''
            resolved_device_code = ''
            if resolved_branch_id:
                branch_obj = db.query(Branch).filter_by(id=resolved_branch_id).first()
                if branch_obj:
                    branch_name = branch_obj.name
                dev = db.query(Device).filter_by(branch_id=resolved_branch_id, is_active=True).first()
                if not dev:
                    dev = Device(
                        id=str(device_id).strip() if (device_id and str(device_id).strip() and len(str(device_id).strip()) == 36) else str(uuid.uuid4()),
                        organization_id=user.organization_id,
                        branch_id=resolved_branch_id,
                        name="Terminal 1",
                        code="T1",
                        device_identifier=f"DEV-{branch_obj.code if branch_obj else 'BR'}-T1",
                        is_active=True,
                    )
                    db.add(dev)
                    db.flush()
                resolved_device_id = dev.id
                resolved_device_code = dev.code

            expires_at = (now + timedelta(hours=max_hours)).isoformat()
            session = Session(
                user_id=user.id,
                username=username,
                full_name=profile.get('full_name', user.full_name or ''),
                organization_id=user.organization_id,
                organization_name=profile.get('organization_name', org.name if org else ''),
                branch_id=resolved_branch_id,
                branch_name=branch_name,
                device_id=resolved_device_id,
                device_code=resolved_device_code,
                permissions=perms,
                roles=roles,
                is_offline=True,
                is_org_admin=user.is_org_admin,
                logged_in_at=now.isoformat(),
                session_expires_at=expires_at,
            )
            self._current_session = session
            return session

    def validate_session(self) -> Session:
        """Verify that there is an active session and that it has not expired."""
        if not self._current_session:
            raise AuthenticationError("Not authenticated.")
        if self._current_session.is_offline and self._current_session.session_expires_at:
            now = datetime.now(timezone.utc)
            expires = datetime.fromisoformat(self._current_session.session_expires_at)
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            if now > expires:
                self.logout()
                raise AuthenticationError("Offline session expired. Please re-authenticate.")
        return self._current_session

    def switch_branch(self, branch_id: str) -> Session:
        """
        Switch the active branch context for the current session (Architecture Plan §5.2).
        Verifies the branch belongs to the user's organization and is active.
        """
        session = self.validate_session()
        with self.db_manager.get_session() as db:
            branch = (
                db.query(Branch)
                .filter_by(
                    id=branch_id,
                    organization_id=session.organization_id,
                    is_active=True,
                )
                .first()
            )
            if not branch:
                raise ValidationError("Selected branch not found or inactive.")

            # Recompute branch-scoped permissions if local UserRole records exist
            user_roles = (
                db.query(UserRole)
                .filter_by(user_id=session.user_id, is_active=True)
                .all()
            )
            if user_roles and not session.is_org_admin:
                applicable_role_ids = [
                    ur.role_id
                    for ur in user_roles
                    if ur.branch_id is None or ur.branch_id == branch_id
                ]
                if not applicable_role_ids:
                    raise AuthenticationError("User has no assigned role for this branch.")
                role_perms = (
                    db.query(Permission.code)
                    .join(RolePermission, RolePermission.permission_id == Permission.id)
                    .filter(RolePermission.role_id.in_(applicable_role_ids))
                    .all()
                )
                if role_perms:
                    session.permissions = sorted({rp[0] for rp in role_perms})

            session.branch_id = branch.id
            session.branch_name = branch.name
            return session

    def sync_user_status(self, user_id: str, is_active: bool):
        """
        Updates local user and OfflineCredential status when synced from server.
        If disabled centrally, locks user out on next login/sync (Architecture Plan §5.5).
        """
        with self.db_manager.get_session() as db:
            user = db.query(User).filter_by(id=user_id).first()
            if user:
                user.is_active = is_active
            cred = db.query(OfflineCredential).filter_by(user_id=user_id).first()
            if cred:
                cred.is_active = is_active
        if not is_active and self._current_session and self._current_session.user_id == user_id:
            self.logout()

    def logout(self):
        self._current_session = None
        self.api_client.set_auth_token(None, None)

    def get_current_session(self) -> Session | None:
        return self._current_session

    def is_authenticated(self) -> bool:
        return self._current_session is not None
