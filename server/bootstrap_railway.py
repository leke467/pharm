"""
Idempotent startup bootstrap for Railway / Production deployments.
Ensures canonical permissions, roles, primary organization (OFRED Pharmacy),
branches, devices, active subscription, and superuser account exist on first boot.
"""
import os
import sys
from pathlib import Path
from datetime import timedelta

BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parent
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.production")

import django  # noqa: E402
django.setup()

from django.utils import timezone  # noqa: E402
from apps.organizations.models import Organization  # noqa: E402
from apps.branches.models import Branch, Device  # noqa: E402
from apps.users.models import User, Role, UserRole  # noqa: E402
from apps.users.services import seed_permissions_and_roles  # noqa: E402
from apps.licensing.models import Subscription, Entitlement, License  # noqa: E402
from shared.enums import SubscriptionStatus, LicenseStatus  # noqa: E402


def bootstrap():
    org_id = "c153d0e9-9fa6-4139-84b2-35bedcb50a8e"
    org = Organization.objects.filter(code="OFRED").first() or Organization.objects.filter(id=org_id).first()
    if not org:
        org = Organization.objects.create(
            id=org_id,
            name="OFRED Pharmacy",
            code="OFRED",
            settings={"default_currency": "NGN", "audit_retention_days": 730},
        )
        print(f"[Bootstrap] Created Organization: {org.name} ({org.code})")

    # Primary Branches
    main_branch_id = "296cdace-8f75-461c-b332-acc738b25643"
    main_branch = Branch.objects.filter(id=main_branch_id).first() or Branch.objects.filter(organization=org, code="MAIN").first()
    if not main_branch:
        main_branch = Branch.objects.create(
            id=main_branch_id,
            organization=org,
            name="Main Branch",
            code="MAIN",
            uses_storage_locations=True,
        )
        print(f"[Bootstrap] Created Branch: {main_branch.name} ({main_branch.code})")

    aye_branch_id = "7499dd8f-5aff-4132-ae75-c8cb260ff798"
    aye_branch = Branch.objects.filter(id=aye_branch_id).first() or Branch.objects.filter(organization=org, code="BR-Aye").first()
    if not aye_branch:
        aye_branch = Branch.objects.create(
            id=aye_branch_id,
            organization=org,
            name="ayetoro",
            code="BR-Aye",
            uses_storage_locations=True,
        )
        print(f"[Bootstrap] Created Branch: {aye_branch.name} ({aye_branch.code})")

    # Devices
    Device.objects.get_or_create(
        id="ef992b22-2bd2-464c-8a8c-763f3e583efc",
        defaults={
            "organization": org,
            "branch": main_branch,
            "name": "POS Terminal 1",
            "code": "POS1",
            "device_identifier": "DEV-MAIN-POS1",
        },
    )
    Device.objects.get_or_create(
        id="b1097538-8e8c-42a7-ab39-020dfbf486e3",
        defaults={
            "organization": org,
            "branch": aye_branch,
            "name": "ayetoro Terminal 1",
            "code": "POS01",
            "device_identifier": "DEV-OFRED-BR-Aye-01",
        },
    )

    # Seed permissions and system roles
    seed_permissions_and_roles(org)
    admin_role = Role.objects.filter(organization=org, name="Organization Admin").first()

    # Admin user (preserving exact UUID and password hash)
    admin_id = "9d862f6d-b42e-4405-b2ea-48851ee26879"
    admin_user = User.objects.filter(id=admin_id).first() or User.objects.filter(organization=org, username="admin").first()
    if not admin_user:
        admin_user = User(
            id=admin_id,
            organization=org,
            username="admin",
            full_name="Pharmacy Administrator",
            email="admin@pharmacy.local",
            is_org_admin=True,
            is_staff=True,
            is_superuser=True,
            default_branch=main_branch,
            password="pbkdf2_sha256$870000$ApJxIRRLASWP1vO8Ntk5TH$oMRSBop9TRhzVc42CHDxzuKNlgUKDfNKbAhvkIWlmDA=",
        )
        admin_user.save()
        print("[Bootstrap] Created Admin Superuser: admin")
    else:
        if not admin_user.is_staff or not admin_user.is_superuser:
            admin_user.is_staff = True
            admin_user.is_superuser = True
            admin_user.save(update_fields=["is_staff", "is_superuser"])

    if admin_role:
        UserRole.objects.get_or_create(user=admin_user, role=admin_role, branch=None)

    # Subscription & License
    now = timezone.now()
    sub, _ = Subscription.objects.get_or_create(
        organization=org,
        defaults={
            "plan": "enterprise",
            "status": SubscriptionStatus.ACTIVE.value,
            "current_period_start": now,
            "current_period_end": now + timedelta(days=30),
            "grace_period_days": 7,
        },
    )
    Entitlement.objects.get_or_create(
        organization=org,
        subscription=sub,
        feature_code="max_branches",
        defaults={"feature_value": "50"},
    )
    License.objects.get_or_create(
        organization=org,
        license_key="LIC-OFRED-ENTERPRISE",
        defaults={
            "status": LicenseStatus.ACTIVE.value,
            "issued_at": now,
            "expires_at": now + timedelta(days=30),
        },
    )
    print("[Bootstrap] Production database bootstrap complete.")


if __name__ == "__main__":
    bootstrap()
