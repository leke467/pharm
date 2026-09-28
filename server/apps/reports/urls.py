from django.urls import path
from .views import (
    SalesReportView,
    InventoryReportView,
    ExpenseReportView,
    ProfitLossReportView,
    CashierShiftReportView,
)

urlpatterns = [
    path('reports/sales/', SalesReportView.as_view(), name='report-sales'),
    path('reports/inventory/', InventoryReportView.as_view(), name='report-inventory'),
    path('reports/expenses/', ExpenseReportView.as_view(), name='report-expenses'),
    path('reports/profit-loss/', ProfitLossReportView.as_view(), name='report-profit-loss'),
    path('reports/shifts/', CashierShiftReportView.as_view(), name='report-shifts'),
]
