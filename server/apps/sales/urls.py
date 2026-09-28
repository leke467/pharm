from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import SaleViewSet, SaleReturnViewSet, ReceiptViewSet

router = DefaultRouter()
router.register(r'sales', SaleViewSet, basename='sale')
router.register(r'sale-returns', SaleReturnViewSet, basename='sale-return')
router.register(r'receipts', ReceiptViewSet, basename='receipt')

urlpatterns = [
    path('', include(router.urls)),
]
