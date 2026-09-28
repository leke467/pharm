import base64
import hashlib
import hmac
import json
import urllib.parse
import urllib.request
import uuid
from decimal import Decimal
from django.conf import settings
from django.utils import timezone
from apps.organizations.models import Organization
from shared.enums import SubscriptionStatus
from .models import Subscription, SubscriptionPayment


class MonnifyService:
    """
    Monnify Payment Gateway Integration for Per-Pharmacy Monthly & Yearly Subscriptions.
    Supports:
    - Live / Sandbox Monnify REST API (OAuth token, Reserved Virtual Accounts, Transaction Init & Verification, Webhooks).
    - Built-in interactive local/sandbox checkout & deterministic virtual account provisioning when MONNIFY_API_KEY is not configured.
    """

    def __init__(self):
        self.api_key = getattr(settings, 'MONNIFY_API_KEY', '') or ''
        self.secret_key = getattr(settings, 'MONNIFY_SECRET_KEY', '') or ''
        self.contract_code = getattr(settings, 'MONNIFY_CONTRACT_CODE', '') or ''
        self.base_url = (
            getattr(settings, 'MONNIFY_BASE_URL', '')
            or 'https://sandbox.monnify.com'
        ).rstrip('/')

    @property
    def is_live_configured(self) -> bool:
        return bool(self.api_key and self.secret_key and self.contract_code)

    def _get_access_token(self) -> str:
        credentials = f"{self.api_key}:{self.secret_key}".encode('utf-8')
        b64_auth = base64.b64encode(credentials).decode('ascii')
        req = urllib.request.Request(
            f"{self.base_url}/api/v1/auth/login",
            data=b"",
            headers={
                "Authorization": f"Basic {b64_auth}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read().decode('utf-8'))
            return body.get("responseBody", {}).get("accessToken", "")

    @staticmethod
    def get_or_create_subscription(org: Organization) -> Subscription:
        sub, _ = Subscription.objects.get_or_create(
            organization=org,
            defaults={
                'plan': 'standard',
                'status': SubscriptionStatus.ACTIVE.value,
                'monthly_price': Decimal('25000.00'),
                'yearly_price': Decimal('250000.00'),
                'current_period_start': timezone.now(),
                'current_period_end': timezone.now() + timezone.timedelta(days=30),
                'grace_period_days': 0,
                'monnify_account_reference': f"PHARM-{org.code}",
                'monnify_account_name': f"PharmaCare - {org.name}",
            },
        )
        if not sub.monnify_account_number:
            MonnifyService().ensure_reserved_account(sub)
        return sub

    def ensure_reserved_account(self, sub: Subscription) -> Subscription:
        """
        Provisions a dedicated Monnify Reserved Virtual Account for this pharmacy if not yet set.
        """
        org = sub.organization
        if not sub.monnify_account_reference:
            sub.monnify_account_reference = f"PHARM-{org.code}"
        if not sub.monnify_account_name:
            sub.monnify_account_name = f"PharmaCare - {org.name}"

        if sub.monnify_account_number and sub.monnify_bank_name:
            return sub

        if self.is_live_configured:
            try:
                token = self._get_access_token()
                payload = {
                    "accountReference": sub.monnify_account_reference,
                    "accountName": sub.monnify_account_name,
                    "currencyCode": sub.currency or "NGN",
                    "contractCode": self.contract_code,
                    "customerEmail": org.email or f"billing@{org.code.lower()}.pharmacare.ng",
                    "customerName": org.name,
                    "getAllAvailableBanks": True,
                }
                req = urllib.request.Request(
                    f"{self.base_url}/api/v2/bank-transfer/reserved-accounts",
                    data=json.dumps(payload).encode('utf-8'),
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                    },
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=15) as resp:
                    body = json.loads(resp.read().decode('utf-8'))
                    resp_body = body.get("responseBody") or {}
                    accounts = resp_body.get("accounts") or []
                    if accounts:
                        first_acc = accounts[0]
                        sub.monnify_account_number = first_acc.get("accountNumber", "")
                        sub.monnify_bank_name = first_acc.get("bankName", "Moniepoint MFB")
                        sub.monnify_bank_code = first_acc.get("bankCode", "50515")
                        sub.monnify_account_name = first_acc.get("accountName") or sub.monnify_account_name
                        sub.save()
                        return sub
            except Exception:
                pass

        # Deterministic fallback virtual account when Monnify keys are not yet set in .env
        if not sub.monnify_account_number:
            digest = hashlib.sha256(org.code.encode('utf-8')).hexdigest()
            numeric_suffix = str(int(digest[:10], 16))[-8:].zfill(8)
            sub.monnify_account_number = f"80{numeric_suffix}"
            sub.monnify_bank_name = "Moniepoint MFB (Monnify Reserved)"
            sub.monnify_bank_code = "50515"
            sub.save()
        return sub

    def initiate_payment(
        self,
        sub: Subscription,
        billing_cycle: str = "MONTHLY",
        server_base_url: str = "http://127.0.0.1:8001",
    ) -> SubscriptionPayment:
        """
        Creates a SubscriptionPayment record and initializes a Monnify checkout session
        for either MONTHLY (30 days) or YEARLY (365 days).
        """
        cycle = (billing_cycle or "MONTHLY").strip().upper()
        if cycle == "YEARLY":
            amount = sub.yearly_price if sub.yearly_price and sub.yearly_price > 0 else (sub.monthly_price * Decimal("12"))
            days_credited = 365
        else:
            cycle = "MONTHLY"
            amount = sub.monthly_price
            days_credited = 30

        org = sub.organization
        pay_ref = f"MNFY-{org.code}-{cycle[:1]}-{uuid.uuid4().hex[:10].upper()}"
        tx_ref = f"MNFY-TX-{uuid.uuid4().hex[:12].upper()}"
        redirect_url = f"{server_base_url.rstrip('/')}/api/v1/licensing/monnify/checkout/{pay_ref}/"
        checkout_url = redirect_url

        if self.is_live_configured:
            try:
                token = self._get_access_token()
                payload = {
                    "amount": float(amount),
                    "customerName": org.name,
                    "customerEmail": org.email or f"billing@{org.code.lower()}.pharmacare.ng",
                    "paymentReference": pay_ref,
                    "paymentDescription": f"PharmaCare {cycle.title()} Subscription ({days_credited} Days) - {org.name}",
                    "currencyCode": sub.currency or "NGN",
                    "contractCode": self.contract_code,
                    "redirectUrl": redirect_url,
                    "paymentMethods": ["CARD", "ACCOUNT_TRANSFER", "USSD"],
                }
                req = urllib.request.Request(
                    f"{self.base_url}/api/v1/merchant/transactions/init-transaction",
                    data=json.dumps(payload).encode('utf-8'),
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                    },
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=15) as resp:
                    body = json.loads(resp.read().decode('utf-8'))
                    resp_body = body.get("responseBody") or {}
                    if resp_body.get("checkoutUrl"):
                        checkout_url = resp_body["checkoutUrl"]
                    if resp_body.get("transactionReference"):
                        tx_ref = resp_body["transactionReference"]
            except Exception:
                pass

        payment = SubscriptionPayment.objects.create(
            organization=org,
            subscription=sub,
            payment_reference=pay_ref,
            monnify_transaction_reference=tx_ref,
            billing_cycle=cycle,
            amount=amount,
            currency=sub.currency or "NGN",
            days_credited=days_credited,
            status="PENDING",
            checkout_url=checkout_url,
        )
        return payment

    def verify_payment(self, payment: SubscriptionPayment) -> tuple[bool, str]:
        """
        Verifies a SubscriptionPayment against Monnify API (if configured) or checks its local status.
        Returns (is_paid, message).
        """
        if payment.status == "PAID":
            return True, f"Payment {payment.payment_reference} confirmed! +{payment.days_credited} days credited."

        if self.is_live_configured:
            try:
                token = self._get_access_token()
                encoded_ref = urllib.parse.quote(payment.payment_reference, safe='')
                req = urllib.request.Request(
                    f"{self.base_url}/api/v1/merchant/transactions/query?paymentReference={encoded_ref}",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                    },
                    method="GET",
                )
                with urllib.request.urlopen(req, timeout=15) as resp:
                    body = json.loads(resp.read().decode('utf-8'))
                    resp_body = body.get("responseBody") or {}
                    pay_status = (resp_body.get("paymentStatus") or "").upper()
                    if pay_status == "PAID":
                        payment.mark_paid_and_credit(
                            transaction_ref=resp_body.get("transactionReference", payment.monnify_transaction_reference),
                            payment_method=resp_body.get("paymentMethod", "MONNIFY"),
                            raw_data=resp_body,
                        )
                        return True, f"Monnify payment confirmed! Added {payment.days_credited} days."
                    elif pay_status in ("FAILED", "EXPIRED", "CANCELLED"):
                        payment.status = "FAILED"
                        payment.raw_response = resp_body
                        payment.save()
                        return False, f"Monnify transaction status: {pay_status}"
            except Exception as exc:
                return False, f"Could not verify with Monnify yet: {exc}"

        return False, "Payment is still pending confirmation."

    def verify_webhook_signature(self, raw_body: bytes, signature: str) -> bool:
        if not self.secret_key:
            return True
        if not signature:
            return False
        computed = hmac.new(
            self.secret_key.encode('utf-8'),
            raw_body,
            hashlib.sha512,
        ).hexdigest()
        return hmac.compare_digest(computed.lower(), signature.strip().lower())

    def process_webhook(self, payload: dict) -> dict:
        """
        Processes Monnify `SUCCESSFUL_TRANSACTION` webhooks for both online checkout
        and dedicated virtual account bank transfers.
        """
        event_type = payload.get("eventType") or ""
        event_data = payload.get("eventData") or payload
        payment_status = (event_data.get("paymentStatus") or "").upper()
        if event_type and event_type != "SUCCESSFUL_TRANSACTION" and payment_status != "PAID":
            return {"processed": False, "reason": f"Ignored event {event_type}"}

        pay_ref = event_data.get("paymentReference") or ""
        tx_ref = event_data.get("transactionReference") or ""
        amount_paid = Decimal(str(event_data.get("amountPaid") or event_data.get("totalPayable") or "0"))
        payment_method = event_data.get("paymentMethod") or "MONNIFY"

        # 1. Check if this matches an initiated SubscriptionPayment
        if pay_ref:
            payment = SubscriptionPayment.objects.filter(payment_reference=pay_ref).first()
            if payment:
                credited = payment.mark_paid_and_credit(
                    transaction_ref=tx_ref,
                    payment_method=payment_method,
                    raw_data=event_data,
                )
                return {
                    "processed": True,
                    "newly_credited": credited,
                    "organization_code": payment.organization.code,
                    "days_remaining": payment.subscription.days_remaining(),
                }

        # 2. Check if this is a Dedicated Reserved Account transfer (matched by product.reference or accountReference)
        product_info = event_data.get("product") or {}
        acc_ref = (
            product_info.get("reference")
            or event_data.get("accountReference")
            or ""
        )
        sub = None
        if acc_ref:
            sub = Subscription.objects.filter(monnify_account_reference=acc_ref).first()
            if not sub and acc_ref.startswith("PHARM-"):
                org_code = acc_ref.replace("PHARM-", "", 1)
                org = Organization.objects.filter(code__iexact=org_code).first()
                if org:
                    sub = self.get_or_create_subscription(org)

        if sub:
            # Determine if yearly or monthly based on amount paid
            if sub.yearly_price and sub.yearly_price > 0 and amount_paid >= sub.yearly_price:
                cycle = "YEARLY"
                days_to_add = 365
            else:
                cycle = "MONTHLY"
                days_to_add = 30

            ref_to_use = pay_ref or tx_ref or f"MNFY-VA-{uuid.uuid4().hex[:10].upper()}"
            existing = SubscriptionPayment.objects.filter(payment_reference=ref_to_use).first()
            if existing and existing.status == "PAID":
                return {"processed": True, "newly_credited": False, "days_remaining": sub.days_remaining()}

            payment = existing or SubscriptionPayment.objects.create(
                organization=sub.organization,
                subscription=sub,
                payment_reference=ref_to_use,
                monnify_transaction_reference=tx_ref,
                billing_cycle=cycle,
                amount=amount_paid if amount_paid > 0 else sub.monthly_price,
                currency=sub.currency or "NGN",
                days_credited=days_to_add,
                status="PENDING",
                payment_method="RESERVED_ACCOUNT",
            )
            payment.mark_paid_and_credit(
                transaction_ref=tx_ref,
                payment_method="RESERVED_ACCOUNT",
                raw_data=event_data,
            )
            return {
                "processed": True,
                "newly_credited": True,
                "organization_code": sub.organization.code,
                "days_remaining": sub.days_remaining(),
            }

        return {"processed": False, "reason": "No matching subscription or payment reference found."}
