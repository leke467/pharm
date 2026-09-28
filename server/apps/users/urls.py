from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import LoginView, TokenRefreshView, CurrentUserView, LogoutView, UserViewSet, RoleViewSet, PermissionViewSet, UserRoleViewSet

router = DefaultRouter()
router.register(r'users', UserViewSet, basename='user')
router.register(r'roles', RoleViewSet, basename='role')
router.register(r'permissions', PermissionViewSet, basename='permission')
router.register(r'user-roles', UserRoleViewSet, basename='user-role')

urlpatterns = [
    path('auth/login/', LoginView.as_view(), name='login'),
    path('auth/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('auth/me/', CurrentUserView.as_view(), name='current_user'),
    path('auth/logout/', LogoutView.as_view(), name='logout'),
    path('', include(router.urls)),
]
