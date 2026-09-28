from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    BatchViewSet,
    StorageLocationViewSet,
    StorageLocationAssignmentViewSet,
    BranchInventoryViewSet,
    InventoryMovementViewSet,
    InventoryAlertViewSet,
    OpeningBalanceView,
    StockAdjustmentView,
    StockCountViewSet,
)

router = DefaultRouter()
router.register(r'batches', BatchViewSet, basename='batch')
router.register(r'storage-locations', StorageLocationViewSet, basename='storage-location')
router.register(
    r'storage-location-assignments',
    StorageLocationAssignmentViewSet,
    basename='storage-location-assignment',
)
router.register(r'inventory', BranchInventoryViewSet, basename='branch-inventory')
router.register(r'inventory-movements', InventoryMovementViewSet, basename='inventory-movement')
router.register(r'inventory-alerts', InventoryAlertViewSet, basename='inventory-alert')
router.register(r'stock-counts', StockCountViewSet, basename='stock-count')

urlpatterns = [
    path('inventory/opening-balance/', OpeningBalanceView.as_view(), name='opening-balance'),
    path('inventory/adjust/', StockAdjustmentView.as_view(), name='inventory-adjust'),
    path('', include(router.urls)),
]
