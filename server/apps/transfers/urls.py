from rest_framework.routers import DefaultRouter
from apps.transfers.views import StockTransferViewSet

router = DefaultRouter()
router.register(r'transfers', StockTransferViewSet, basename='stock-transfer')

urlpatterns = router.urls
