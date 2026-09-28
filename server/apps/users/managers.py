from django.contrib.auth.models import BaseUserManager

class UserManager(BaseUserManager):
    def create_user(self, username, organization_id, password=None, **extra_fields):
        if not username:
            raise ValueError('Users must have a username')
        if not organization_id:
            raise ValueError('Users must belong to an organization')
        user = self.model(username=username, organization_id=organization_id, **extra_fields)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(self, username, password, **extra_fields):
        # For django admin, we might need a default org or handle it specially
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        from apps.organizations.models import Organization
        org, _ = Organization.objects.get_or_create(code='system', defaults={'name': 'System'})
        return self.create_user(username, org.id, password, **extra_fields)
