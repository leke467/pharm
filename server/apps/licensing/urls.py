from django.urls import path
from rest_framework.routers import DefaultRouter
from .views import (
    SubscriptionViewSet,
    EntitlementViewSet,
    LicenseViewSet,
    SubscriptionStatusView,
    MonnifyInitiatePaymentView,
    MonnifyVerifyPaymentView,
    MonnifyWebhookView,
    MonnifyInteractiveCheckoutView,
)

router = DefaultRouter()
router.register(r'subscriptions', SubscriptionViewSet, basename='subscription')
router.register(r'entitlements', EntitlementViewSet, basename='entitlement')
router.register(r'licenses', LicenseViewSet, basename='license')

urlpatterns = [
    path('licensing/status/', SubscriptionStatusView.as_view(), name='licensing-status'),
    path('licensing/monnify/initiate/', MonnifyInitiatePaymentView.as_view(), name='monnify-initiate'),
    path('licensing/monnify/verify/', MonnifyVerifyPaymentView.as_view(), name='monnify-verify'),
    path('licensing/monnify/webhook/', MonnifyWebhookView.as_view(), name='monnify-webhook'),
    path(
        'licensing/monnify/checkout/<str:payment_reference>/',
        MonnifyInteractiveCheckoutView.as_view(),
        name='monnify-checkout',
    ),
] + router.urls
