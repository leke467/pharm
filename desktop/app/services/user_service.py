import json
import uuid
from datetime import datetime, timezone
from desktop.app.auth.offline_auth import OfflineAuthenticator
from desktop.app.db.models import (
    User,
    Role,
    Permission,
    RolePermission,
    UserRole,
    OfflineCredential,
)
from desktop.app.domain.exceptions import ValidationError
from desktop.app.services.base_service import BaseService
from shared.enums import PermissionCode, AuditAction, SyncOperation


class UserService(BaseService):
    """
    Service managing Users, Roles, Permissions, and UserRole assignments on the desktop.
    Enforces RBAC (`users.manage`) and records atomic AuditEvents and SyncEvents.
    """

    def seed_local_permissions(self) -> list[Permission]:
        """Ensure all canonical permission codes exist in local SQLite."""
        with self.transaction() as db:
            created = []
            for p in PermissionCode:
                code = p.value
                category = code.split(".")[0].replace("_", " ").title()
                name = code.replace(".", " - ").replace("_", " ").title()
                perm = db.query(Permission).filter_by(code=code).first()
                if not perm:
                    perm = Permission(
                        id=str(uuid.uuid4()),
                        code=code,
                        name=name,
                        category=category,
                    )
                    db.add(perm)
                    created.append(perm)
            db.flush()
            return created

    def list_users(self, organization_id: str, active_only: bool = True) -> list[User]:
        with self.transaction() as db:
            q = db.query(User).filter_by(organization_id=organization_id)
            if active_only:
                q = q.filter_by(is_active=True)
            return q.order_by(User.username.asc()).all()

    def list_roles(self, organization_id: str, active_only: bool = True) -> list[Role]:
        with self.transaction() as db:
            q = db.query(Role).filter_by(organization_id=organization_id)
            if active_only:
                q = q.filter_by(is_active=True)
            return q.order_by(Role.name.asc()).all()

    def get_user_roles_map(self, organization_id: str) -> dict[str, list[str]]:
        """Returns a mapping of user_id -> list of assigned role names."""
        with self.transaction() as db:
            user_roles = (
                db.query(UserRole.user_id, Role.name)
                .join(Role, UserRole.role_id == Role.id)
                .filter(Role.organization_id == organization_id, UserRole.is_active == True)
                .all()
            )
            res: dict[str, list[str]] = {}
            for uid, rname in user_roles:
                res.setdefault(uid, []).append(rname)
            return res

    def create_user(
        self,
        user_session,
        username: str,
        full_name: str,
        email: str = "",
        phone: str = "",
        is_org_admin: bool = False,
        default_branch_id: str | None = None,
        password: str = "",
        role_id: str | None = None,
    ) -> User:
        self.require_permission(user_session, PermissionCode.USERS_MANAGE.value)
        if not username or not full_name:
            raise ValidationError("Username and full name are required.")

        with self.transaction() as db:
            existing = (
                db.query(User)
                .filter_by(organization_id=user_session.organization_id, username=username)
                .first()
            )
            if existing:
                raise ValidationError(f"Username '{username}' already exists in this organization.")

            new_user = User(
                id=str(uuid.uuid4()),
                organization_id=user_session.organization_id,
                username=username,
                full_name=full_name,
                email=email,
                phone=phone,
                is_org_admin=is_org_admin,
                default_branch_id=default_branch_id,
                is_active=True,
            )
            db.add(new_user)
            db.flush()

            # Assign initial role if specified
            assigned_roles = []
            if role_id:
                role = db.query(Role).filter_by(id=role_id, organization_id=user_session.organization_id).first()
                if role:
                    ur = UserRole(
                        id=str(uuid.uuid4()),
                        user_id=new_user.id,
                        role_id=role.id,
                        branch_id=default_branch_id,
                        assigned_by_id=user_session.user_id,
                        is_active=True,
                    )
                    db.add(ur)
                    assigned_roles.append(role.name)
                    db.flush()

            # If password provided, store OfflineCredential so user can log in immediately
            if password:
                offline_auth = OfflineAuthenticator()
                offline_hash = offline_auth.create_offline_hash(password)
                now_utc = datetime.now(timezone.utc).isoformat()
                cred = OfflineCredential(
                    user_id=new_user.id,
                    offline_password_hash=offline_hash,
                    cached_permissions=json.dumps([]),
                    cached_roles=json.dumps(assigned_roles),
                    cached_user_profile=json.dumps({
                        "id": new_user.id,
                        "username": new_user.username,
                        "full_name": new_user.full_name,
                        "organization_id": new_user.organization_id,
                    }),
                    is_active=True,
                    last_online_login_at=now_utc,
                )
                db.add(cred)
                db.flush()

            payload = {
                "id": new_user.id,
                "organization_id": new_user.organization_id,
                "username": new_user.username,
                "full_name": new_user.full_name,
                "email": new_user.email,
                "phone": new_user.phone,
                "is_org_admin": new_user.is_org_admin,
                "default_branch_id": new_user.default_branch_id,
                "is_active": True,
            }
            self.record_audit_and_sync(
                db_session=db,
                user_session=user_session,
                action=AuditAction.PERMISSION_CHANGED.value,
                entity_type="user",
                entity_id=new_user.id,
                operation=SyncOperation.CREATE.value,
                payload=payload,
            )
            return new_user

    def reset_password(self, user_session, target_user_id: str, new_password: str) -> None:
        """Sets or resets the offline login password for a staff member."""
        self.require_permission(user_session, PermissionCode.USERS_MANAGE.value)
        if not new_password or len(new_password) < 4:
            raise ValidationError("Password must be at least 4 characters long.")

        with self.transaction() as db:
            user = (
                db.query(User)
                .filter_by(id=target_user_id, organization_id=user_session.organization_id)
                .first()
            )
            if not user:
                raise ValidationError("User not found.")

            offline_auth = OfflineAuthenticator()
            offline_hash = offline_auth.create_offline_hash(new_password)
            now_utc = datetime.now(timezone.utc).isoformat()

            cred = db.query(OfflineCredential).filter_by(user_id=target_user_id).first()
            if cred:
                cred.offline_password_hash = offline_hash
                cred.is_active = True
                cred.last_online_login_at = now_utc
            else:
                cred = OfflineCredential(
                    user_id=target_user_id,
                    offline_password_hash=offline_hash,
                    cached_permissions=json.dumps([]),
                    cached_roles=json.dumps([]),
                    cached_user_profile=json.dumps({
                        "id": user.id,
                        "username": user.username,
                        "full_name": user.full_name,
                        "organization_id": user.organization_id,
                    }),
                    is_active=True,
                    last_online_login_at=now_utc,
                )
                db.add(cred)
            db.flush()

            self.record_audit_and_sync(
                db_session=db,
                user_session=user_session,
                action=AuditAction.PERMISSION_CHANGED.value,
                entity_type="user",
                entity_id=user.id,
                operation=SyncOperation.UPDATE.value,
                payload={"id": user.id, "password_reset": True},
            )

    def create_role(
        self,
        user_session,
        name: str,
        description: str = "",
        permission_codes: list[str] | None = None,
        is_system: bool = False,
    ) -> Role:
        self.require_permission(user_session, PermissionCode.USERS_MANAGE.value)
        if not name:
            raise ValidationError("Role name is required.")

        self.seed_local_permissions()

        with self.transaction() as db:
            role = Role(
                id=str(uuid.uuid4()),
                organization_id=user_session.organization_id,
                name=name,
                description=description,
                is_system=is_system,
                is_active=True,
            )
            db.add(role)
            db.flush()

            granted_codes = []
            if permission_codes:
                unique_codes = list(dict.fromkeys(permission_codes))
                existing_perms = {
                    p.code: p
                    for p in db.query(Permission).filter(Permission.code.in_(unique_codes)).all()
                }
                for code in unique_codes:
                    perm = existing_perms.get(code)
                    if not perm and code.startswith("matrix."):
                        perm = Permission(
                            id=str(uuid.uuid4()),
                            code=code,
                            name=code.replace(".", " - ").title(),
                            category="Matrix",
                        )
                        db.add(perm)
                        db.flush()
                        existing_perms[code] = perm
                    if perm:
                        rp = RolePermission(
                            id=str(uuid.uuid4()),
                            role_id=role.id,
                            permission_id=perm.id,
                        )
                        db.add(rp)
                        granted_codes.append(perm.code)
                db.flush()

            payload = {
                "id": role.id,
                "organization_id": role.organization_id,
                "name": role.name,
                "description": role.description,
                "is_system": role.is_system,
                "permission_codes": granted_codes,
                "is_active": True,
            }
            self.record_audit_and_sync(
                db_session=db,
                user_session=user_session,
                action=AuditAction.PERMISSION_CHANGED.value,
                entity_type="role",
                entity_id=role.id,
                operation=SyncOperation.CREATE.value,
                payload=payload,
            )
            return role

    def get_role_permissions(self, role_id: str) -> list[str]:
        """Returns list of permission code strings assigned to the specified role."""
        with self.transaction() as db:
            perms = (
                db.query(Permission.code)
                .join(RolePermission, RolePermission.permission_id == Permission.id)
                .filter(RolePermission.role_id == role_id)
                .all()
            )
            return [p[0] for p in perms]

    def update_role_permissions(
        self,
        user_session,
        role_id: str,
        permission_codes: list[str],
        name: str | None = None,
        description: str | None = None,
    ) -> Role:
        """Updates a role's metadata and permission matrix assignments."""
        self.require_permission(user_session, PermissionCode.USERS_MANAGE.value)
        self.seed_local_permissions()

        with self.transaction() as db:
            role = db.query(Role).filter_by(id=role_id, organization_id=user_session.organization_id).first()
            if not role:
                raise ValidationError("Role not found.")

            if name and name.strip():
                role.name = name.strip()
            if description is not None:
                role.description = description.strip()

            # Clear old role permissions
            db.query(RolePermission).filter_by(role_id=role.id).delete()
            db.flush()

            granted_codes = []
            if permission_codes:
                unique_codes = list(dict.fromkeys(permission_codes))
                existing_perms = {
                    p.code: p
                    for p in db.query(Permission).filter(Permission.code.in_(unique_codes)).all()
                }
                for code in unique_codes:
                    perm = existing_perms.get(code)
                    if not perm and code.startswith("matrix."):
                        perm = Permission(
                            id=str(uuid.uuid4()),
                            code=code,
                            name=code.replace(".", " - ").title(),
                            category="Matrix",
                        )
                        db.add(perm)
                        db.flush()
                        existing_perms[code] = perm
                    if perm:
                        rp = RolePermission(
                            id=str(uuid.uuid4()),
                            role_id=role.id,
                            permission_id=perm.id,
                        )
                        db.add(rp)
                        granted_codes.append(perm.code)
                db.flush()

            # Refresh OfflineCredential.cached_permissions for all users assigned to this role
            affected_user_ids = [
                uid
                for (uid,) in db.query(UserRole.user_id)
                .filter_by(role_id=role.id, is_active=True)
                .all()
            ]
            for uid in affected_user_ids:
                user_role_ids = [
                    rid
                    for (rid,) in db.query(UserRole.role_id)
                    .filter_by(user_id=uid, is_active=True)
                    .all()
                ]
                user_perms = [
                    pcode
                    for (pcode,) in db.query(Permission.code)
                    .join(RolePermission, RolePermission.permission_id == Permission.id)
                    .filter(RolePermission.role_id.in_(user_role_ids))
                    .all()
                ]
                cred = db.query(OfflineCredential).filter_by(user_id=uid).first()
                if cred:
                    cred.cached_permissions = json.dumps(list(dict.fromkeys(user_perms)))
            db.flush()

            payload = {
                "id": role.id,
                "organization_id": role.organization_id,
                "name": role.name,
                "description": role.description,
                "is_system": role.is_system,
                "permission_codes": granted_codes,
                "is_active": True,
            }
            self.record_audit_and_sync(
                db_session=db,
                user_session=user_session,
                action=AuditAction.PERMISSION_CHANGED.value,
                entity_type="role",
                entity_id=role.id,
                operation=SyncOperation.UPDATE.value,
                payload=payload,
            )
            return role

    def ensure_default_roles(self, user_session) -> None:
        """Ensures standard default pharmacy roles exist in SQLite."""
        self.seed_local_permissions()
        default_roles = [
            (
                "Pharmacist",
                "Licensed pharmacist with catalog, sales, receiving, and stock count permissions",
                [
                    PermissionCode.PRODUCTS_VIEW.value,
                    PermissionCode.PRODUCTS_CREATE.value,
                    PermissionCode.PRODUCTS_EDIT.value,
                    PermissionCode.BATCHES_MANAGE.value,
                    PermissionCode.INVENTORY_VIEW.value,
                    PermissionCode.SALES_SELL.value,
                    PermissionCode.SALES_RETURN.value,
                    PermissionCode.PRICES_VIEW.value,
                    PermissionCode.PRICES_MANAGE.value,
                    PermissionCode.STOCK_RECEIVE.value,
                    PermissionCode.STOCK_COUNTS_PERFORM.value,
                    PermissionCode.STOCK_TRANSFER.value,
                ],
            ),
            (
                "Cashier",
                "Front-desk sales cashier with Point of Sale checkout and product viewing",
                [
                    PermissionCode.SALES_SELL.value,
                    PermissionCode.PRODUCTS_VIEW.value,
                    PermissionCode.PRICES_VIEW.value,
                ],
            ),
            (
                "Inventory Manager",
                "Manages stock balances, receiving purchase orders, transfers, and inventory counts",
                [
                    PermissionCode.INVENTORY_VIEW.value,
                    PermissionCode.INVENTORY_ADJUST.value,
                    PermissionCode.PRODUCTS_VIEW.value,
                    PermissionCode.PRODUCTS_CREATE.value,
                    PermissionCode.PRODUCTS_EDIT.value,
                    PermissionCode.BATCHES_MANAGE.value,
                    PermissionCode.PRICES_VIEW.value,
                    PermissionCode.PRICES_MANAGE.value,
                    PermissionCode.STOCK_RECEIVE.value,
                    PermissionCode.SUPPLIERS_MANAGE.value,
                    PermissionCode.STOCK_COUNTS_PERFORM.value,
                    PermissionCode.STOCK_COUNTS_APPROVE.value,
                    PermissionCode.STOCK_TRANSFER.value,
                ],
            ),
            (
                "Accountant",
                "Financial auditor and expense bookkeeper with reporting and expense voucher access",
                [
                    PermissionCode.REPORTS_VIEW.value,
                    PermissionCode.EXPENSES_CREATE.value,
                    PermissionCode.EXPENSES_APPROVE.value,
                    PermissionCode.AUDIT_VIEW.value,
                ],
            ),
        ]

        with self.transaction() as db:
            for rname, rdesc, rperms in default_roles:
                existing = db.query(Role).filter_by(organization_id=user_session.organization_id, name=rname).first()
                if not existing:
                    role = Role(
                        id=str(uuid.uuid4()),
                        organization_id=user_session.organization_id,
                        name=rname,
                        description=rdesc,
                        is_system=True,
                        is_active=True,
                    )
                    db.add(role)
                    db.flush()
                    perms = db.query(Permission).filter(Permission.code.in_(rperms)).all()
                    for p in perms:
                        rp = RolePermission(
                            id=str(uuid.uuid4()),
                            role_id=role.id,
                            permission_id=p.id,
                        )
                        db.add(rp)
                    db.flush()

    def assign_role(
        self,
        user_session,
        target_user_id: str,
        role_id: str,
        branch_id: str | None = None,
    ) -> UserRole:
        self.require_permission(user_session, PermissionCode.USERS_MANAGE.value)

        with self.transaction() as db:
            target_user = (
                db.query(User)
                .filter_by(id=target_user_id, organization_id=user_session.organization_id)
                .first()
            )
            role = (
                db.query(Role)
                .filter_by(id=role_id, organization_id=user_session.organization_id)
                .first()
            )
            if not target_user or not role:
                raise ValidationError("User and Role must belong to your organization.")

            assigner_exists = (
                db.query(User).filter_by(id=user_session.user_id).first() is not None
            )
            user_role = UserRole(
                id=str(uuid.uuid4()),
                user_id=target_user_id,
                role_id=role_id,
                branch_id=branch_id,
                assigned_by_id=user_session.user_id if assigner_exists else None,
                is_active=True,
            )
            db.add(user_role)
            db.flush()

            payload = {
                "id": user_role.id,
                "user_id": user_role.user_id,
                "role_id": user_role.role_id,
                "branch_id": user_role.branch_id,
                "assigned_by_id": user_session.user_id,
                "is_active": True,
            }
            self.record_audit_and_sync(
                db_session=db,
                user_session=user_session,
                action=AuditAction.PERMISSION_CHANGED.value,
                entity_type="user_role",
                entity_id=user_role.id,
                operation=SyncOperation.CREATE.value,
                payload=payload,
            )
            return user_role

    def deactivate_user(self, user_session, target_user_id: str) -> User:
        self.require_permission(user_session, PermissionCode.USERS_MANAGE.value)

        with self.transaction() as db:
            target_user = (
                db.query(User)
                .filter_by(id=target_user_id, organization_id=user_session.organization_id)
                .first()
            )
            if not target_user:
                raise ValidationError("User not found.")

            target_user.is_active = False
            cred = db.query(OfflineCredential).filter_by(user_id=target_user_id).first()
            if cred:
                cred.is_active = False
            db.flush()

            payload = {
                "id": target_user.id,
                "organization_id": target_user.organization_id,
                "username": target_user.username,
                "is_active": False,
            }
            self.record_audit_and_sync(
                db_session=db,
                user_session=user_session,
                action=AuditAction.PERMISSION_CHANGED.value,
                entity_type="user",
                entity_id=target_user.id,
                operation=SyncOperation.UPDATE.value,
                payload=payload,
                data_before={"is_active": True},
                data_after={"is_active": False},
            )
            return target_user

    def update_user(
        self,
        user_session,
        target_user_id: str,
        full_name: str | None = None,
        email: str | None = None,
        phone: str | None = None,
        is_org_admin: bool | None = None,
        is_active: bool | None = None,
        role_id: str | None = None,
    ) -> User:
        """Updates user details, admin status, active status, and role assignments."""
        self.require_permission(user_session, PermissionCode.USERS_MANAGE.value)
        with self.transaction() as db:
            user = db.query(User).filter_by(id=target_user_id, organization_id=user_session.organization_id).first()
            if not user:
                raise ValidationError("User not found.")
            data_before = {
                "full_name": user.full_name,
                "email": user.email,
                "phone": user.phone,
                "is_org_admin": user.is_org_admin,
                "is_active": user.is_active,
            }
            if full_name is not None and full_name.strip():
                user.full_name = full_name.strip()
            if email is not None:
                user.email = email.strip()
            if phone is not None:
                user.phone = phone.strip()
            if is_org_admin is not None:
                user.is_org_admin = is_org_admin
            if is_active is not None:
                user.is_active = is_active
                cred = db.query(OfflineCredential).filter_by(user_id=target_user_id).first()
                if cred:
                    cred.is_active = is_active

            # Update role assignment if role_id is provided
            if role_id is not None:
                db.query(UserRole).filter_by(user_id=user.id).update({"is_active": False})
                if role_id:
                    role = db.query(Role).filter_by(id=role_id, organization_id=user_session.organization_id).first()
                    if role:
                        ur = UserRole(
                            id=str(uuid.uuid4()),
                            user_id=user.id,
                            role_id=role.id,
                            branch_id=user.default_branch_id,
                            assigned_by_id=user_session.user_id,
                            is_active=True,
                        )
                        db.add(ur)
            db.flush()

            data_after = {
                "full_name": user.full_name,
                "email": user.email,
                "phone": user.phone,
                "is_org_admin": user.is_org_admin,
                "is_active": user.is_active,
            }
            self.record_audit_and_sync(
                db_session=db,
                user_session=user_session,
                action=AuditAction.PERMISSION_CHANGED.value,
                entity_type="user",
                entity_id=user.id,
                operation=SyncOperation.UPDATE.value,
                payload={"id": user.id, **data_after},
                data_before=data_before,
                data_after=data_after,
            )
            return user

