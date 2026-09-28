from django.urls import path, include
from .views import HealthCheckView

urlpatterns = [
    path('health/', HealthCheckView.as_view(), name='health'),
    path('', include('apps.organizations.urls')),
    path('', include('apps.branches.urls')),
    path('', include('apps.users.urls')),
    path('', include('apps.products.urls')),
    path('', include('apps.inventory.urls')),
    path('', include('apps.pricing.urls')),
    path('', include('apps.sales.urls')),
    path('', include('apps.purchases.urls')),
    path('', include('apps.transfers.urls')),
    path('', include('apps.expenses.urls')),
    path('', include('apps.audit.urls')),
    path('', include('apps.reports.urls')),
    path('', include('apps.licensing.urls')),
    path('', include('apps.sync.urls')),
]
