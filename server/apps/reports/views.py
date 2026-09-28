from datetime import date, timedelta
from decimal import Decimal
from django.db.models import Sum, Count, F, Q, DecimalField
from django.db.models.functions import Coalesce
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from apps.core.permissions import IsOrganizationMember, require_permission
from apps.sales.models import Sale, SaleItem, Payment
from apps.inventory.models import BranchInventory, Batch
from apps.expenses.models import Expense
from shared.enums import PermissionCode, SaleStatus, ExpenseStatus


class SalesReportView(APIView):
    """
    Comprehensive sales report endpoint (Architecture Plan §14).
    Calculates revenue, tax, discount, COGS, gross profit, and payment breakdowns.
    """
    permission_classes = [
        IsAuthenticated,
        IsOrganizationMember,
        require_permission(read_perm=PermissionCode.REPORTS_VIEW.value),
    ]

    def get(self, request):
        org = request.user.organization
        branch_id = request.query_params.get('branch_id')
        user_id = request.query_params.get('user_id')
        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')

        sales_qs = Sale.objects.filter(
            organization=org,
            status__in=[SaleStatus.COMPLETED.value, SaleStatus.PARTIALLY_RETURNED.value],
        )
        if branch_id:
            sales_qs = sales_qs.filter(branch_id=branch_id)
        if user_id:
            sales_qs = sales_qs.filter(user_id=user_id)
        if start_date:
            sales_qs = sales_qs.filter(sale_date__date__gte=start_date)
        if end_date:
            sales_qs = sales_qs.filter(sale_date__date__lte=end_date)

        summary = sales_qs.aggregate(
            total_count=Count('id'),
            total_revenue=Coalesce(Sum('total'), Decimal('0.00'), output_field=DecimalField()),
            total_tax=Coalesce(Sum('tax_amount'), Decimal('0.00'), output_field=DecimalField()),
            total_discount=Coalesce(Sum('discount_amount'), Decimal('0.00'), output_field=DecimalField()),
        )

        sale_ids = sales_qs.values_list('id', flat=True)

        # Payment methods breakdown
        payments = (
            Payment.objects.filter(sale_id__in=sale_ids)
            .values('payment_method')
            .annotate(total=Sum('amount'), count=Count('id'))
            .order_by('-total')
        )
        payments_data = [
            {'method': p['payment_method'], 'total': str(p['total']), 'count': p['count']}
            for p in payments
        ]

        # COGS calculation
        items = SaleItem.objects.filter(sale_id__in=sale_ids)
        cogs = Decimal('0.00')
        items_sold_count = 0
        for item in items.select_related('batch'):
            cost_per_unit = item.batch.purchase_price if item.batch else Decimal('0.00')
            cogs += cost_per_unit * item.quantity
            items_sold_count += item.quantity

        revenue = summary['total_revenue']
        gross_profit = revenue - cogs

        return Response({
            'total_sales_count': summary['total_count'],
            'total_revenue': str(revenue),
            'total_tax': str(summary['total_tax']),
            'total_discount': str(summary['total_discount']),
            'total_items_sold': items_sold_count,
            'cost_of_goods_sold': str(cogs),
            'gross_profit': str(gross_profit),
            'payment_breakdown': payments_data,
        })


class InventoryReportView(APIView):
    """
    Inventory valuation, low stock alerts, and expiry analysis (Architecture Plan §14).
    """
    permission_classes = [
        IsAuthenticated,
        IsOrganizationMember,
        require_permission(read_perm=PermissionCode.REPORTS_VIEW.value),
    ]

    def get(self, request):
        org = request.user.organization
        branch_id = request.query_params.get('branch_id')

        inv_qs = BranchInventory.objects.filter(organization=org, quantity__gt=0)
        if branch_id:
            inv_qs = inv_qs.filter(branch_id=branch_id)

        total_units = 0
        total_cost_valuation = Decimal('0.00')
        low_stock_count = 0
        low_stock_items = []

        for inv in inv_qs.select_related('batch', 'batch__product'):
            total_units += inv.quantity
            cost = inv.batch.purchase_price if inv.batch else Decimal('0.00')
            total_cost_valuation += cost * inv.quantity
            reorder = inv.reorder_level or 10
            if inv.quantity <= reorder:
                low_stock_count += 1
                if len(low_stock_items) < 20:
                    low_stock_items.append({
                        'product_name': inv.batch.product.name if inv.batch else "",
                        'batch_number': inv.batch.batch_number if inv.batch else "",
                        'current_quantity': inv.quantity,
                        'reorder_level': reorder,
                    })

        today = date.today()
        ninety_days = today + timedelta(days=90)

        batch_qs = Batch.objects.filter(organization=org)
        if branch_id:
            batch_qs = batch_qs.filter(branch_inventories__branch_id=branch_id, branch_inventories__quantity__gt=0).distinct()
        else:
            batch_qs = batch_qs.filter(branch_inventories__quantity__gt=0).distinct()

        expired_count = batch_qs.filter(expiry_date__lt=today).count()
        expiring_soon_count = batch_qs.filter(expiry_date__gte=today, expiry_date__lte=ninety_days).count()

        return Response({
            'total_batches_in_stock': inv_qs.count(),
            'total_units_in_stock': total_units,
            'total_cost_valuation': str(total_cost_valuation),
            'low_stock_count': low_stock_count,
            'low_stock_items': low_stock_items,
            'expired_batches_count': expired_count,
            'expiring_soon_batches_count': expiring_soon_count,
        })


class ExpenseReportView(APIView):
    """
    Expense analysis and category breakdown (Architecture Plan §14).
    """
    permission_classes = [
        IsAuthenticated,
        IsOrganizationMember,
        require_permission(read_perm=PermissionCode.REPORTS_VIEW.value),
    ]

    def get(self, request):
        org = request.user.organization
        branch_id = request.query_params.get('branch_id')
        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')
        status_filter = request.query_params.get('status', ExpenseStatus.APPROVED.value)

        exp_qs = Expense.objects.filter(organization=org)
        if status_filter:
            exp_qs = exp_qs.filter(status=status_filter)
        if branch_id:
            exp_qs = exp_qs.filter(branch_id=branch_id)
        if start_date:
            exp_qs = exp_qs.filter(expense_date__gte=start_date)
        if end_date:
            exp_qs = exp_qs.filter(expense_date__lte=end_date)

        summary = exp_qs.aggregate(
            total_amount=Coalesce(Sum('amount'), Decimal('0.00'), output_field=DecimalField()),
            total_count=Count('id'),
        )

        categories = (
            exp_qs.values('expense_category__name')
            .annotate(total=Sum('amount'), count=Count('id'))
            .order_by('-total')
        )
        category_breakdown = [
            {'category': c['expense_category__name'] or 'Uncategorized', 'total': str(c['total']), 'count': c['count']}
            for c in categories
        ]

        methods = (
            exp_qs.values('payment_method')
            .annotate(total=Sum('amount'), count=Count('id'))
            .order_by('-total')
        )
        payment_breakdown = [
            {'method': m['payment_method'], 'total': str(m['total']), 'count': m['count']}
            for m in methods
        ]

        return Response({
            'total_expenses': str(summary['total_amount']),
            'total_count': summary['total_count'],
            'category_breakdown': category_breakdown,
            'payment_breakdown': payment_breakdown,
        })


class ProfitLossReportView(APIView):
    """
    Consolidated Profit & Loss statement (Architecture Plan §14).
    Revenue - COGS = Gross Profit
    Gross Profit - Operating Expenses = Net Profit
    """
    permission_classes = [
        IsAuthenticated,
        IsOrganizationMember,
        require_permission(read_perm=PermissionCode.REPORTS_VIEW.value),
    ]

    def get(self, request):
        org = request.user.organization
        branch_id = request.query_params.get('branch_id')
        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')

        # 1. Sales
        sales_qs = Sale.objects.filter(
            organization=org,
            status__in=[SaleStatus.COMPLETED.value, SaleStatus.PARTIALLY_RETURNED.value],
        )
        if branch_id:
            sales_qs = sales_qs.filter(branch_id=branch_id)
        if start_date:
            sales_qs = sales_qs.filter(sale_date__date__gte=start_date)
        if end_date:
            sales_qs = sales_qs.filter(sale_date__date__lte=end_date)

        rev_agg = sales_qs.aggregate(
            revenue=Coalesce(Sum('total'), Decimal('0.00'), output_field=DecimalField()),
            sales_count=Count('id'),
        )
        revenue = rev_agg['revenue']

        sale_ids = sales_qs.values_list('id', flat=True)
        items = SaleItem.objects.filter(sale_id__in=sale_ids).select_related('batch')
        cogs = Decimal('0.00')
        for item in items:
            cost = item.batch.purchase_price if item.batch else Decimal('0.00')
            cogs += cost * item.quantity

        gross_profit = revenue - cogs

        # 2. Operating Expenses
        exp_qs = Expense.objects.filter(
            organization=org,
            status=ExpenseStatus.APPROVED.value,
        )
        if branch_id:
            exp_qs = exp_qs.filter(branch_id=branch_id)
        if start_date:
            exp_qs = exp_qs.filter(expense_date__gte=start_date)
        if end_date:
            exp_qs = exp_qs.filter(expense_date__lte=end_date)

        exp_agg = exp_qs.aggregate(
            expenses=Coalesce(Sum('amount'), Decimal('0.00'), output_field=DecimalField()),
        )
        expenses = exp_agg['expenses']
        net_profit = gross_profit - expenses

        return Response({
            'revenue': str(revenue),
            'cost_of_goods_sold': str(cogs),
            'gross_profit': str(gross_profit),
            'operating_expenses': str(expenses),
            'net_profit': str(net_profit),
            'sales_count': rev_agg['sales_count'],
        })


class CashierShiftReportView(APIView):
    """
    Cashier Shift Reconciliation endpoint (Architecture Plan §14).
    Aggregates sales and payment methods per user/cashier.
    """
    permission_classes = [
        IsAuthenticated,
        IsOrganizationMember,
        require_permission(read_perm=PermissionCode.REPORTS_VIEW.value),
    ]

    def get(self, request):
        org = request.user.organization
        branch_id = request.query_params.get('branch_id')
        shift_date = request.query_params.get('date', date.today().isoformat())

        sales_qs = Sale.objects.filter(
            organization=org,
            status__in=[SaleStatus.COMPLETED.value, SaleStatus.PARTIALLY_RETURNED.value],
            sale_date__date=shift_date,
        )
        if branch_id:
            sales_qs = sales_qs.filter(branch_id=branch_id)

        user_shifts = (
            sales_qs.values('user__id', 'user__username', 'user__full_name')
            .annotate(
                sales_count=Count('id'),
                total_collected=Coalesce(Sum('total'), Decimal('0.00'), output_field=DecimalField()),
            )
            .order_by('user__username')
        )

        shifts_data = []
        for u in user_shifts:
            uid = u['user__id']
            user_sales = sales_qs.filter(user_id=uid)
            payments = (
                Payment.objects.filter(sale__in=user_sales)
                .values('payment_method')
                .annotate(amount=Sum('amount'))
            )
            shifts_data.append({
                'user_id': str(uid),
                'username': u['user__username'],
                'full_name': u['user__full_name'],
                'sales_count': u['sales_count'],
                'total_collected': str(u['total_collected']),
                'payments': {p['payment_method']: f"{Decimal(str(p['amount'])):.2f}" for p in payments},
            })

        return Response({
            'date': shift_date,
            'shifts': shifts_data,
        })
