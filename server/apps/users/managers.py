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
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        organization_id = extra_fields.pop('organization_id', None)
        user = self.model(username=username, organization_id=organization_id, **extra_fields)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user
