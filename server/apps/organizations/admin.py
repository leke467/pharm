from django.contrib import admin
from apps.licensing.models import Subscription
from apps.licensing.monnify_service import MonnifyService
from apps.users.services import seed_permissions_and_roles
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


DEFAULT_CATEGORIES = [
    "Analgesics & Antipyretics",
    "Antibiotics & Antifungals",
    "Antimalarials",
    "Cardiovascular",
    "Central Nervous System",
    "Dermatological",
    "Diabetes & Endocrine",
    "Gastrointestinal",
    "Medical Supplies",
    "Ophthalmic & ENT",
    "Respiratory & Allergy",
    "Vitamins & Supplements",
    "General / Uncategorized",
]


def seed_default_categories(org: Organization):
    import uuid
    from apps.products.models import Category
    for cat_name in DEFAULT_CATEGORIES:
        cat_id = uuid.uuid5(uuid.NAMESPACE_DNS, f"{org.id}:category:{cat_name}")
        Category.objects.get_or_create(
            organization=org,
            name=cat_name,
            defaults={'id': cat_id, 'is_active': True},
        )


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    inlines = [SubscriptionInline]
    list_display = ('name', 'code', 'phone', 'email', 'subscription_summary', 'is_active', 'created_at')
    search_fields = ('name', 'code', 'email', 'phone')
    list_filter = ('is_active',)

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        org = form.instance
        sub = MonnifyService.get_or_create_subscription(org)
        if sub and not sub.monnify_account_number:
            MonnifyService().ensure_reserved_account(sub)
        try:
            seed_permissions_and_roles(org)
        except Exception:
            pass
        try:
            seed_default_categories(org)
        except Exception:
            pass

    @admin.display(description='Subscription Status')
    def subscription_summary(self, obj: Organization):
        sub = getattr(obj, 'subscription', None)
        if not sub:
            return "No Subscription"
        return f"{sub.effective_status()} ({sub.days_remaining()}d left) — ₦{sub.monthly_price:,.0f}/mo | ₦{sub.yearly_price:,.0f}/yr"
