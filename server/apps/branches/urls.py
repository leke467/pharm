from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import BranchViewSet, DeviceViewSet

router = DefaultRouter()
router.register(r'branches', BranchViewSet, basename='branch')
router.register(r'devices', DeviceViewSet, basename='device')

urlpatterns = [
    path('', include(router.urls)),
]
