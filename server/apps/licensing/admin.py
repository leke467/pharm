from django import forms
from django.contrib import admin, messages
from django.utils import timezone
from django.utils.html import format_html
from shared.enums import SubscriptionStatus
from .models import Subscription, SubscriptionPayment, Entitlement, License
from .monnify_service import MonnifyService


class SubscriptionAdminForm(forms.ModelForm):
    set_days_remaining = forms.IntegerField(
        required=False,
        min_value=0,
        max_value=3650,
        label="Quick Set Days Remaining",
        help_text=(
            "Optional shortcut: Enter a number of days (e.g. 30, 365, or 0 to lock immediately) "
            "and click Save to automatically calculate 'Current period end' from today."
        ),
    )

    class Meta:
        model = Subscription
        fields = '__all__'

    def clean(self):
        cleaned = super().clean()
        quick_days = cleaned.get('set_days_remaining')
        if quick_days is not None:
            now = timezone.now()
            cleaned['current_period_start'] = now
            cleaned['current_period_end'] = now + timezone.timedelta(days=int(quick_days))
            if int(quick_days) <= 0:
                cleaned['status'] = SubscriptionStatus.EXPIRED.value
            elif cleaned.get('status') == SubscriptionStatus.EXPIRED.value:
                cleaned['status'] = SubscriptionStatus.ACTIVE.value
        return cleaned


class EntitlementInline(admin.TabularInline):
    model = Entitlement
    extra = 0
    fields = ('feature_code', 'feature_value')


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    form = SubscriptionAdminForm
    inlines = [EntitlementInline]
    list_display = (
        'pharmacy_display',
        'status',
        'days_left_badge',
        'monthly_price',
        'yearly_price',
        'current_period_end',
        'monnify_account_display',
    )
    list_editable = ('status', 'monthly_price', 'yearly_price')
    list_filter = ('status', 'plan', 'auto_renew')
    search_fields = (
        'organization__name',
        'organization__code',
        'monnify_account_number',
        'monnify_account_reference',
    )
    actions = [
        'action_add_30_days',
        'action_add_365_days',
        'action_expire_immediately',
        'action_provision_monnify_account',
    ]

    fieldsets = (
        (
            'Pharmacy & Subscription Status',
            {
                'fields': (
                    'organization',
                    'plan',
                    'status',
                    'set_days_remaining',
                    'current_period_start',
                    'current_period_end',
                    'grace_period_days',
                    'auto_renew',
                )
            },
        ),
        (
            'Custom Pharmacy Pricing (NGN)',
            {
                'description': 'Set the Monthly and Yearly subscription amounts specifically for this pharmacy.',
                'fields': ('monthly_price', 'yearly_price', 'currency'),
            },
        ),
        (
            'Monnify Dedicated Virtual Account',
            {
                'description': 'Dedicated bank transfer details displayed inside the pharmacy desktop app.',
                'fields': (
                    'monnify_account_reference',
                    'monnify_bank_name',
                    'monnify_account_number',
                    'monnify_account_name',
                    'monnify_bank_code',
                ),
            },
        ),
    )

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if not obj.monnify_account_number:
            MonnifyService().ensure_reserved_account(obj)

    @admin.display(description='Pharmacy (Code)', ordering='organization__name')
    def pharmacy_display(self, obj: Subscription):
        return f"{obj.organization.name} ({obj.organization.code})"

    @admin.display(description='Days Left')
    def days_left_badge(self, obj: Subscription):
        days = obj.days_remaining()
        if days <= 0 or obj.effective_status() != SubscriptionStatus.ACTIVE.value and obj.effective_status() != SubscriptionStatus.TRIAL.value:
            return format_html(
                '<span style="background:#FEE2E2;color:#991B1B;padding:3px 8px;border-radius:10px;font-weight:700;">0 Days (LOCKED)</span>'
            )
        elif days <= 7:
            return format_html(
                '<span style="background:#FEF3C7;color:#92400E;padding:3px 8px;border-radius:10px;font-weight:700;">{} Days Left</span>',
                days,
            )
        return format_html(
            '<span style="background:#DCFCE7;color:#166534;padding:3px 8px;border-radius:10px;font-weight:700;">{} Days Left</span>',
            days,
        )

    @admin.display(description='Monnify Virtual Account')
    def monnify_account_display(self, obj: Subscription):
        if obj.monnify_account_number:
            return f"{obj.monnify_bank_name or 'Moniepoint'}: {obj.monnify_account_number}"
        return "Not Provisioned"

    @admin.action(description="➕ Add 30 Days (1 Month Subscription)")
    def action_add_30_days(self, request, queryset):
        for sub in queryset:
            sub.extend_subscription(30)
        self.message_user(request, f"Added 30 days to {queryset.count()} pharmacy subscription(s).", messages.SUCCESS)

    @admin.action(description="➕ Add 365 Days (1 Year Subscription)")
    def action_add_365_days(self, request, queryset):
        for sub in queryset:
            sub.extend_subscription(365)
        self.message_user(request, f"Added 365 days to {queryset.count()} pharmacy subscription(s).", messages.SUCCESS)

    @admin.action(description="🚫 Set to 0 Days Left (Expire / Hard Lock Immediately)")
    def action_expire_immediately(self, request, queryset):
        now = timezone.now()
        for sub in queryset:
            sub.current_period_end = now - timezone.timedelta(seconds=10)
            sub.status = SubscriptionStatus.EXPIRED.value
            sub.grace_period_days = 0
            sub.save()
        self.message_user(request, f"Expired and locked {queryset.count()} pharmacy subscription(s).", messages.WARNING)

    @admin.action(description="🏦 Provision / Refresh Monnify Virtual Account")
    def action_provision_monnify_account(self, request, queryset):
        monnify = MonnifyService()
        for sub in queryset:
            monnify.ensure_reserved_account(sub)
        self.message_user(request, f"Provisioned Monnify virtual account for {queryset.count()} pharmacy(s).", messages.SUCCESS)


@admin.register(SubscriptionPayment)
class SubscriptionPaymentAdmin(admin.ModelAdmin):
    list_display = (
        'payment_reference',
        'organization',
        'billing_cycle',
        'amount',
        'days_credited',
        'status',
        'payment_method',
        'paid_at',
        'created_at',
    )
    list_filter = ('status', 'billing_cycle', 'payment_method')
    search_fields = ('payment_reference', 'monnify_transaction_reference', 'organization__name', 'organization__code')
    actions = ['action_confirm_payment_and_credit']

    @admin.action(description="✅ Confirm Payment & Credit Subscription Days (+30 / +365 days)")
    def action_confirm_payment_and_credit(self, request, queryset):
        credited_count = 0
        for payment in queryset:
            if payment.mark_paid_and_credit(
                transaction_ref=payment.monnify_transaction_reference or f"ADMIN-{payment.id}",
                payment_method="ADMIN_CONFIRMED",
            ):
                credited_count += 1
        self.message_user(
            request,
            f"Confirmed and credited {credited_count} payment(s).",
            messages.SUCCESS,
        )


@admin.register(License)
class LicenseAdmin(admin.ModelAdmin):
    list_display = ('license_key', 'organization', 'status', 'issued_at', 'expires_at')
    list_filter = ('status',)
    search_fields = ('license_key', 'organization__name', 'organization__code')
