import sys
from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.organizations.models import Organization
from apps.branches.models import Branch, Device
from apps.users.models import User, Role, UserRole
from apps.users.services import seed_permissions_and_roles
from apps.licensing.models import Subscription, Entitlement, License
from shared.enums import SubscriptionStatus, LicenseStatus


class Command(BaseCommand):
    help = "Initializes a new Pharmacy Organization, primary Branch, POS Device, and Admin Account."

    def add_arguments(self, parser):
        parser.add_argument("--org-name", type=str, default="Apex Pharmacy", help="Pharmacy / Organization Name")
        parser.add_argument("--org-code", type=str, default="APEX", help="Unique Organization Code (used in Sign In)")
        parser.add_argument("--branch-name", type=str, default="Main Branch", help="Name of primary branch")
        parser.add_argument("--branch-code", type=str, default="MAIN", help="Code of primary branch")
        parser.add_argument("--device-name", type=str, default="Terminal 1", help="First POS Terminal Name")
        parser.add_argument("--device-code", type=str, default="T01", help="First POS Terminal Code")
        parser.add_argument("--admin-username", type=str, default="admin", help="Admin username")
        parser.add_argument("--admin-password", type=str, default="Admin123!", help="Admin password")
        parser.add_argument("--admin-name", type=str, default="Pharmacy Administrator", help="Admin Full Name")
        parser.add_argument("--admin-email", type=str, default="admin@pharmacy.local", help="Admin Email")
        parser.add_argument("--currency", type=str, default="NGN", help="Default currency (e.g. NGN, USD, GBP)")
        parser.add_argument("--plan", type=str, default="enterprise", help="Subscription plan")
        parser.add_argument("--interactive", action="store_true", help="Prompt interactively for details")

    def handle(self, *args, **options):
        interactive = options["interactive"]

        if interactive:
            self.stdout.write(self.style.MIGRATE_HEADING("=== Create / Setup New Pharmacy ==="))
            org_name = input("Pharmacy / Organization Name [Apex Pharmacy]: ").strip() or "Apex Pharmacy"
            org_code = input("Organization Code (e.g. APEX) [APEX]: ").strip().upper() or "APEX"
            branch_name = input("Main Branch Name [Main Branch]: ").strip() or "Main Branch"
            branch_code = input("Main Branch Code [MAIN]: ").strip().upper() or "MAIN"
            admin_username = input("Admin Username [admin]: ").strip() or "admin"
            admin_password = input("Admin Password [Admin123!]: ").strip() or "Admin123!"
            admin_name = input("Admin Full Name [Pharmacy Administrator]: ").strip() or "Pharmacy Administrator"
            admin_email = input("Admin Email [admin@pharmacy.local]: ").strip() or "admin@pharmacy.local"
            currency = input("Default Currency [NGN]: ").strip().upper() or "NGN"
            device_name = "Terminal 1"
            device_code = "T01"
            plan = "enterprise"
        else:
            org_name = options["org_name"]
            org_code = options["org_code"].strip().upper()
            branch_name = options["branch_name"]
            branch_code = options["branch_code"].strip().upper()
            device_name = options["device_name"]
            device_code = options["device_code"].strip().upper()
            admin_username = options["admin_username"].strip()
            admin_password = options["admin_password"]
            admin_name = options["admin_name"]
            admin_email = options["admin_email"]
            currency = options["currency"].strip().upper()
            plan = options["plan"]

        self.stdout.write(f"Setting up pharmacy: '{org_name}' (Code: {org_code})...")

        # 1. Organization
        org, created = Organization.objects.get_or_create(
            code=org_code,
            defaults={
                "name": org_name,
                "settings": {"default_currency": currency, "audit_retention_days": 730},
            },
        )
        if not created and org.name != org_name:
            org.name = org_name
            org.save()

        # 2. Primary Branch
        branch, br_created = Branch.objects.get_or_create(
            organization=org,
            code=branch_code,
            defaults={
                "name": branch_name,
                "uses_storage_locations": True,
            },
        )

        # 3. First POS Terminal Device
        device, dev_created = Device.objects.get_or_create(
            organization=org,
            branch=branch,
            code=device_code,
            defaults={
                "name": device_name,
                "device_identifier": f"DEV-{org_code}-{branch_code}-{device_code}",
            },
        )

        # 4. Canonical Permissions & System Roles
        seed_permissions_and_roles(org)
        admin_role = Role.objects.filter(organization=org, name="Organization Admin").first()

        # 5. Admin User
        user = User.objects.filter(organization=org, username=admin_username).first()
        if not user:
            user = User.objects.create_user(
                username=admin_username,
                organization_id=org.id,
                password=admin_password,
                full_name=admin_name,
                email=admin_email,
                is_org_admin=True,
                default_branch=branch,
            )
            self.stdout.write(self.style.SUCCESS(f"Created Admin account: {admin_username}"))
        else:
            user.set_password(admin_password)
            user.full_name = admin_name
            user.email = admin_email
            user.is_org_admin = True
            user.default_branch = branch
            user.save()
            self.stdout.write(self.style.SUCCESS(f"Updated password for Admin account: {admin_username}"))

        if admin_role:
            UserRole.objects.get_or_create(user=user, role=admin_role, branch=None)

        # 6. Subscription & Entitlement & License
        now = timezone.now()
        sub, _ = Subscription.objects.get_or_create(
            organization=org,
            defaults={
                "plan": plan,
                "status": SubscriptionStatus.ACTIVE.value,
                "current_period_start": now,
                "current_period_end": now + timedelta(days=365),
                "grace_period_days": 14,
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
            license_key=f"LIC-{org_code}-{plan.upper()}",
            defaults={
                "status": LicenseStatus.ACTIVE.value,
                "issued_at": now,
                "expires_at": now + timedelta(days=365),
            },
        )

        # Beautiful Summary
        banner = "=" * 60
        self.stdout.write(self.style.SUCCESS(f"\n{banner}"))
        self.stdout.write(self.style.SUCCESS("  PHARMACY SETUP SUCCESSFUL!"))
        self.stdout.write(self.style.SUCCESS(banner))
        self.stdout.write(f" Pharmacy Name     : {org.name}")
        self.stdout.write(f" Organization Code : {self.style.WARNING(org.code)}")
        self.stdout.write(f" Branch Name       : {branch.name} ({branch.code})")
        self.stdout.write(f" POS Device        : {device.name} ({device.code})")
        self.stdout.write(f" Admin Username    : {self.style.WARNING(user.username)}")
        self.stdout.write(f" Admin Password    : {self.style.WARNING(admin_password)}")
        self.stdout.write(f" Subscription Plan : {plan.upper()} (Active)")
        self.stdout.write(self.style.SUCCESS(banner))
        self.stdout.write(self.style.NOTICE("\n[NEXT STEPS] Log in to your Desktop Application:"))
        self.stdout.write(f"   1. Enter Organization Code : {org.code}")
        self.stdout.write(f"   2. Enter Username          : {user.username}")
        self.stdout.write(f"   3. Enter Password          : {admin_password}")
        self.stdout.write(f"   4. Click 'Login'\n")
