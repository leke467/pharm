import math
from decimal import Decimal
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from apps.core.models import BaseModel
from apps.organizations.models import Organization
from shared.enums import LicenseStatus, SubscriptionStatus


class Subscription(BaseModel):
    """
    Per-Pharmacy (Organization) Subscription record managed via Django Admin
    and renewed via Monnify (Monthly or Yearly).
    """
    organization = models.OneToOneField(
        Organization, on_delete=models.CASCADE, related_name='subscription'
    )
    plan = models.CharField(max_length=50, default='standard')
    status = models.CharField(
        max_length=20,
        choices=[(s.value, s.value) for s in SubscriptionStatus],
        default=SubscriptionStatus.ACTIVE.value,
    )
    monthly_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('25000.00'),
        help_text='Monthly subscription fee in NGN set manually for this pharmacy.',
    )
    yearly_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('250000.00'),
        help_text='Yearly subscription fee in NGN set manually for this pharmacy.',
    )
    currency = models.CharField(max_length=10, default='NGN')
    current_period_start = models.DateTimeField(default=timezone.now)
    current_period_end = models.DateTimeField()
    grace_period_days = models.IntegerField(default=0)
    auto_renew = models.BooleanField(default=True)

    # Dedicated Monnify Reserved Virtual Account per Pharmacy
    monnify_account_reference = models.CharField(max_length=100, blank=True, default='')
    monnify_account_number = models.CharField(max_length=30, blank=True, default='')
    monnify_account_name = models.CharField(max_length=255, blank=True, default='')
    monnify_bank_name = models.CharField(max_length=100, blank=True, default='')
    monnify_bank_code = models.CharField(max_length=20, blank=True, default='')

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Pharmacy Subscription'
        verbose_name_plural = 'Pharmacy Subscriptions'

    def __str__(self):
        return f"{self.organization.name} ({self.organization.code}) — {self.days_remaining()} days left"

    def is_expired(self) -> bool:
        if not self.current_period_end:
            return True
        return timezone.now() >= self.current_period_end

    def is_in_grace_period(self) -> bool:
        if not self.is_expired() or self.grace_period_days <= 0:
            return False
        grace_end = self.current_period_end + timezone.timedelta(days=self.grace_period_days)
        return timezone.now() <= grace_end

    def days_remaining(self) -> int:
        if self.status in (SubscriptionStatus.SUSPENDED.value, SubscriptionStatus.CANCELLED.value):
            return 0
        if not self.current_period_end:
            return 0
        diff_seconds = (self.current_period_end - timezone.now()).total_seconds()
        if diff_seconds <= 0:
            return 0
        return max(0, int(math.ceil(diff_seconds / 86400.0)))

    def effective_status(self) -> str:
        if self.status in (SubscriptionStatus.SUSPENDED.value, SubscriptionStatus.CANCELLED.value):
            return self.status
        if self.days_remaining() <= 0:
            return SubscriptionStatus.EXPIRED.value
        return self.status

    def extend_subscription(self, days: int):
        now = timezone.now()
        if self.current_period_end and self.current_period_end > now:
            self.current_period_end = self.current_period_end + timezone.timedelta(days=days)
        else:
            self.current_period_start = now
            self.current_period_end = now + timezone.timedelta(days=days)
        self.status = SubscriptionStatus.ACTIVE.value
        self.save()

    def to_sync_payload(self) -> dict:
        entitlements = {e.feature_code: e.feature_value for e in self.entitlements.all()}
        eff_status = self.effective_status()
        days_left = self.days_remaining()
        entitlements.update({
            "monthly_price": str(self.monthly_price),
            "yearly_price": str(self.yearly_price),
            "currency": self.currency,
            "days_remaining": days_left,
            "monnify_account_reference": self.monnify_account_reference or f"PHARM-{self.organization.code}",
            "monnify_account_number": self.monnify_account_number,
            "monnify_account_name": self.monnify_account_name or f"PharmaCare - {self.organization.name}",
            "monnify_bank_name": self.monnify_bank_name,
            "monnify_bank_code": self.monnify_bank_code,
        })
        return {
            "organization_id": str(self.organization_id),
            "organization_code": self.organization.code,
            "organization_name": self.organization.name,
            "status": eff_status,
            "plan": self.plan,
            "monthly_price": str(self.monthly_price),
            "yearly_price": str(self.yearly_price),
            "currency": self.currency,
            "current_period_start": self.current_period_start.isoformat() if self.current_period_start else None,
            "current_period_end": self.current_period_end.isoformat() if self.current_period_end else None,
            "days_remaining": days_left,
            "grace_period_days": self.grace_period_days,
            "monnify_account_reference": self.monnify_account_reference or f"PHARM-{self.organization.code}",
            "monnify_account_number": self.monnify_account_number,
            "monnify_account_name": self.monnify_account_name or f"PharmaCare - {self.organization.name}",
            "monnify_bank_name": self.monnify_bank_name,
            "monnify_bank_code": self.monnify_bank_code,
            "entitlements": entitlements,
            "checked_at": timezone.now().isoformat(),
        }


class SubscriptionPayment(BaseModel):
    """
    Tracks Monnify subscription payments (Monthly = 30 days, Yearly = 365 days)
    via online checkout or dedicated virtual account transfer.
    """
    BILLING_CYCLE_CHOICES = [
        ('MONTHLY', 'Monthly (30 Days)'),
        ('YEARLY', 'Yearly (365 Days)'),
    ]
    PAYMENT_STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('PAID', 'Paid / Confirmed'),
        ('FAILED', 'Failed'),
        ('CANCELLED', 'Cancelled'),
    ]

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name='subscription_payments'
    )
    subscription = models.ForeignKey(
        Subscription, on_delete=models.CASCADE, related_name='payments'
    )
    payment_reference = models.CharField(max_length=120, unique=True)
    monnify_transaction_reference = models.CharField(max_length=120, blank=True, default='')
    billing_cycle = models.CharField(max_length=20, choices=BILLING_CYCLE_CHOICES, default='MONTHLY')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=10, default='NGN')
    days_credited = models.IntegerField(default=30)
    status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default='PENDING')
    checkout_url = models.URLField(max_length=500, blank=True, default='')
    payment_method = models.CharField(max_length=50, blank=True, default='')
    paid_at = models.DateTimeField(null=True, blank=True)
    raw_response = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Subscription Payment'
        verbose_name_plural = 'Subscription Payments'

    def __str__(self):
        return f"{self.organization.code} — {self.billing_cycle} (₦{self.amount:,.2f}) [{self.status}]"

    def mark_paid_and_credit(self, transaction_ref: str = '', payment_method: str = '', raw_data: dict | None = None) -> bool:
        """
        Idempotently marks this payment as PAID and adds `days_credited` to the pharmacy's Subscription.
        Returns True if newly credited, False if already paid.
        """
        if self.status == 'PAID':
            return False
        self.status = 'PAID'
        if transaction_ref:
            self.monnify_transaction_reference = transaction_ref
        if payment_method:
            self.payment_method = payment_method
        self.paid_at = timezone.now()
        if raw_data:
            self.raw_response = raw_data
        self.save()
        self.subscription.extend_subscription(self.days_credited)
        return True


class Entitlement(BaseModel):
    """
    Granular subscription entitlement or limits (e.g., max_branches, max_devices).
    """
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name='entitlements'
    )
    subscription = models.ForeignKey(
        Subscription, on_delete=models.CASCADE, related_name='entitlements'
    )
    feature_code = models.CharField(max_length=100)
    feature_value = models.CharField(max_length=255)

    class Meta:
        unique_together = [('subscription', 'feature_code')]


class License(BaseModel):
    """
    Cryptographic / Tokenized activation key record for offline-capable deployments.
    """
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name='licenses'
    )
    license_key = models.CharField(max_length=255, unique=True)
    status = models.CharField(max_length=20, default=LicenseStatus.ACTIVE.value)
    issued_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()

