"""
Idempotent startup bootstrap for Railway / Production deployments.
Only ensures the platform Django Admin superuser (admin / admin123!) exists.
Does NOT seed test pharmacies or branches.
"""
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parent
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(ROOT_DIR))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.production")

import django  # noqa: E402
django.setup()

from apps.organizations.models import Organization  # noqa: E402
from apps.users.models import User  # noqa: E402


def bootstrap():
    # Ensure platform superuser exists without requiring a pre-seeded pharmacy
    admin_user = User.objects.filter(username="admin").first()
    if not admin_user:
        admin_user = User(
            username="admin",
            full_name="Platform Superuser",
            email="admin@pharmacarepro.com",
            organization=None,
            default_branch=None,
            is_org_admin=True,
            is_staff=True,
            is_superuser=True,
            is_active=True,
        )
        admin_user.set_password("admin123!")
        admin_user.save()
        print("[Bootstrap] Created Platform Superuser: admin (password: admin123!)")
    else:
        admin_user.is_org_admin = True
        admin_user.is_staff = True
        admin_user.is_superuser = True
        admin_user.is_active = True
        if admin_user.organization_id == "c153d0e9-9fa6-4139-84b2-35bedcb50a8e" or str(admin_user.organization_id) == "c153d0e9-9fa6-4139-84b2-35bedcb50a8e":
            admin_user.organization = None
            admin_user.default_branch = None
        if not admin_user.check_password("admin123!"):
            admin_user.set_password("admin123!")
        admin_user.save()
        print("[Bootstrap] Verified Platform Superuser: admin (password: admin123!)")

    # Clean up the auto-seeded test organization (c153d0e9-9fa6-4139-84b2-35bedcb50a8e) if present
    seeded_org = Organization.objects.filter(id="c153d0e9-9fa6-4139-84b2-35bedcb50a8e").first()
    if seeded_org:
        seeded_org.delete()
        print("[Bootstrap] Removed auto-seeded test organization and branches.")

    print("[Bootstrap] Production database bootstrap complete.")


if __name__ == "__main__":
    bootstrap()
