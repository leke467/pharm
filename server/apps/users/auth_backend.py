from django.contrib.auth.backends import ModelBackend
from .models import User


class CustomAuthBackend(ModelBackend):
    """
    Organization-scoped authentication backend.
    Requires organization_id for tenant user logins.
    Allows superuser fallback without organization_id for Django admin only.
    """

    def authenticate(self, request, username=None, password=None, organization_id=None, **kwargs):
        if not username or not password:
            return None

        try:
            if organization_id is not None:
                user = User.objects.get(username=username, organization_id=organization_id)
                if user.check_password(password) and self.user_can_authenticate(user):
                    return user
            else:
                candidates = User.objects.filter(username=username, is_staff=True)
                for user in candidates:
                    if (user.is_superuser or user.is_staff) and user.check_password(password) and self.user_can_authenticate(user):
                        return user
        except (User.DoesNotExist, User.MultipleObjectsReturned):
            return None
        return None
