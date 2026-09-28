from django.core.management.base import BaseCommand, CommandError
from apps.organizations.models import Organization
from apps.branches.models import Branch
from apps.users.models import User, Role, UserRole


class Command(BaseCommand):
    help = "Creates a new staff user (Cashier, Pharmacist, Branch Manager, etc.) under an Organization."

    def add_arguments(self, parser):
        parser.add_argument("--org-code", type=str, required=True, help="Organization Code (e.g. MEDCARE)")
        parser.add_argument("--username", type=str, required=True, help="Staff username")
        parser.add_argument("--password", type=str, required=True, help="Staff password")
        parser.add_argument("--full-name", type=str, default="Pharmacy Staff", help="Full name")
        parser.add_argument("--role", type=str, default="Cashier", help="Role name: Cashier, Pharmacist, Branch Manager, Organization Admin")
        parser.add_argument("--branch-code", type=str, default=None, help="Branch code (e.g. MAIN). If omitted, uses default branch")
        parser.add_argument("--email", type=str, default="", help="Staff email")
        parser.add_argument("--phone", type=str, default="", help="Staff phone")

    def handle(self, *args, **options):
        org_code = options["org_code"].strip().upper()
        username = options["username"].strip()
        password = options["password"]
        full_name = options["full_name"]
        role_name = options["role"].strip()
        branch_code = options["branch_code"]
        email = options["email"]
        phone = options["phone"]

        org = Organization.objects.filter(code=org_code).first()
        if not org:
            raise CommandError(f"Organization with code '{org_code}' does not exist.")

        branch = None
        if branch_code:
            branch = Branch.objects.filter(organization=org, code=branch_code.strip().upper()).first()
            if not branch:
                raise CommandError(f"Branch with code '{branch_code}' does not exist in organization '{org_code}'.")
        else:
            branch = Branch.objects.filter(organization=org).first()

        # Check existing user
        user = User.objects.filter(organization=org, username=username).first()
        is_admin_role = (role_name.lower() in ["organization admin", "org admin", "admin"])

        if user:
            user.set_password(password)
            user.full_name = full_name
            user.email = email
            user.phone = phone
            user.is_org_admin = is_admin_role
            if branch:
                user.default_branch = branch
            user.save()
            self.stdout.write(self.style.SUCCESS(f"Updated existing user '{username}'."))
        else:
            user = User.objects.create_user(
                username=username,
                organization_id=org.id,
                password=password,
                full_name=full_name,
                email=email,
                phone=phone,
                is_org_admin=is_admin_role,
                default_branch=branch,
            )
            self.stdout.write(self.style.SUCCESS(f"Created new staff user '{username}'."))

        # Assign Role
        role = Role.objects.filter(organization=org, name__iexact=role_name).first()
        if not role:
            # Fallback search
            role = Role.objects.filter(organization=org, name__icontains=role_name).first()

        if role:
            UserRole.objects.get_or_create(
                user=user,
                role=role,
                branch=branch if not is_admin_role else None,
            )
            self.stdout.write(self.style.SUCCESS(f"Assigned role '{role.name}' to '{username}'."))
        else:
            available_roles = list(Role.objects.filter(organization=org).values_list("name", flat=True))
            self.stdout.write(self.style.WARNING(f"Role '{role_name}' not found. Available roles: {available_roles}"))

        self.stdout.write(f"\nAccount ready:")
        self.stdout.write(f"  Organization Code : {org.code}")
        self.stdout.write(f"  Username          : {user.username}")
        self.stdout.write(f"  Password          : {password}")
        self.stdout.write(f"  Branch            : {branch.name if branch else 'None'}\n")
