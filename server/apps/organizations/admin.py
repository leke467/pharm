from django.contrib import admin
from apps.licensing.models import Subscription
from apps.licensing.monnify_service import MonnifyService
from .models import Organization


class SubscriptionInline(admin.StackedInline):
    model = Subscription
    extra = 0
    max_num = 1
    can_delete = False
    fields = (
        'status',
        'plan',
        'monthly_price',
        'yearly_price',
        'current_period_start',
        'current_period_end',
        'grace_period_days',
        'monnify_bank_name',
        'monnify_account_number',
        'monnify_account_name',
    )


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    inlines = [SubscriptionInline]
    list_display = ('name', 'code', 'phone', 'email', 'subscription_summary', 'is_active', 'created_at')
    search_fields = ('name', 'code', 'email', 'phone')
    list_filter = ('is_active',)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        MonnifyService.get_or_create_subscription(obj)

    @admin.display(description='Subscription Status')
    def subscription_summary(self, obj: Organization):
        sub = getattr(obj, 'subscription', None)
        if not sub:
            return "No Subscription"
        return f"{sub.effective_status()} ({sub.days_remaining()}d left) — ₦{sub.monthly_price:,.0f}/mo | ₦{sub.yearly_price:,.0f}/yr"
