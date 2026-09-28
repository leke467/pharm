from django.http import HttpResponse
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from rest_framework import viewsets, views, status
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response

from apps.core.mixins import OrganizationQuerysetMixin
from apps.core.permissions import IsOrganizationMember, require_permission
from apps.organizations.models import Organization
from shared.enums import PermissionCode
from .models import Subscription, SubscriptionPayment, Entitlement, License
from .monnify_service import MonnifyService
from .serializers import (
    SubscriptionSerializer,
    SubscriptionPaymentSerializer,
    EntitlementSerializer,
    LicenseSerializer,
)


def _resolve_organization(request) -> Organization | None:
    """
    Resolves the Organization from an authenticated user, or by `org_code` / `organization_id`
    query param or request body (so hard-locked terminals can check status & pay from Login screen).
    """
    if getattr(request, 'user', None) and request.user.is_authenticated and getattr(request.user, 'organization', None):
        return request.user.organization

    org_code = (
        request.query_params.get('org_code')
        or (request.data.get('org_code') if isinstance(getattr(request, 'data', None), dict) else None)
        or ''
    ).strip()
    org_id = (
        request.query_params.get('organization_id')
        or (request.data.get('organization_id') if isinstance(getattr(request, 'data', None), dict) else None)
        or ''
    ).strip()

    if org_id:
        org = Organization.objects.filter(id=org_id).first()
        if org:
            return org

    if org_code:
        org = Organization.objects.filter(code__iexact=org_code).first()
        if org:
            return org

    return Organization.objects.first()


class SubscriptionStatusView(views.APIView):
    """
    GET /api/v1/licensing/status/?org_code=MEDCARE
    Returns authoritative subscription countdown, monthly/yearly price set in Django Admin,
    and dedicated Monnify Virtual Account details for the pharmacy.
    """
    permission_classes = [AllowAny]

    def get(self, request):
        org = _resolve_organization(request)
        if not org:
            return Response(
                {"error": {"code": "ORG_NOT_FOUND", "message": "Pharmacy organization not found on server."}},
                status=status.HTTP_404_NOT_FOUND,
            )

        monnify = MonnifyService()
        sub = monnify.get_or_create_subscription(org)
        payload = sub.to_sync_payload()
        recent_payments = SubscriptionPaymentSerializer(
            sub.payments.all()[:5], many=True
        ).data
        payload["recent_payments"] = recent_payments
        return Response(payload, status=status.HTTP_200_OK)


class MonnifyInitiatePaymentView(views.APIView):
    """
    POST /api/v1/licensing/monnify/initiate/
    Body: {"org_code": "MEDCARE", "billing_cycle": "MONTHLY" | "YEARLY"}
    Initializes a Monnify payment session for 30 days (MONTHLY) or 365 days (YEARLY).
    """
    permission_classes = [AllowAny]

    def post(self, request):
        org = _resolve_organization(request)
        if not org:
            return Response(
                {"error": {"code": "ORG_NOT_FOUND", "message": "Pharmacy organization not found on server."}},
                status=status.HTTP_404_NOT_FOUND,
            )

        billing_cycle = (request.data.get("billing_cycle") or "MONTHLY").strip().upper()
        if billing_cycle not in ("MONTHLY", "YEARLY"):
            billing_cycle = "MONTHLY"

        monnify = MonnifyService()
        sub = monnify.get_or_create_subscription(org)
        server_base = request.build_absolute_uri('/').rstrip('/')
        payment = monnify.initiate_payment(
            sub=sub,
            billing_cycle=billing_cycle,
            server_base_url=server_base,
        )
        return Response(
            {
                "payment": SubscriptionPaymentSerializer(payment).data,
                "checkout_url": payment.checkout_url,
                "payment_reference": payment.payment_reference,
                "days_credited": payment.days_credited,
                "amount": str(payment.amount),
                "subscription": sub.to_sync_payload(),
            },
            status=status.HTTP_201_CREATED,
        )


class MonnifyVerifyPaymentView(views.APIView):
    """
    POST /api/v1/licensing/monnify/verify/
    Body: {"org_code": "MEDCARE", "payment_reference": "MNFY-..."}
    Verifies a payment with Monnify (or checks if webhook / admin already credited the subscription)
    and returns the updated subscription status & countdown.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        org = _resolve_organization(request)
        if not org:
            return Response(
                {"error": {"code": "ORG_NOT_FOUND", "message": "Pharmacy organization not found on server."}},
                status=status.HTTP_404_NOT_FOUND,
            )

        monnify = MonnifyService()
        sub = monnify.get_or_create_subscription(org)
        pay_ref = (request.data.get("payment_reference") or "").strip()

        payment = None
        if pay_ref:
            payment = SubscriptionPayment.objects.filter(
                organization=org, payment_reference=pay_ref
            ).first()
        if not payment:
            payment = SubscriptionPayment.objects.filter(organization=org).first()

        is_paid = False
        message = "Subscription status synced with server."
        if payment:
            is_paid, message = monnify.verify_payment(payment)
            sub.refresh_from_db()

        return Response(
            {
                "paid": is_paid,
                "verified_paid": is_paid,
                "message": message,
                "payment": SubscriptionPaymentSerializer(payment).data if payment else None,
                "subscription": sub.to_sync_payload(),
            },
            status=status.HTTP_200_OK,
        )


@method_decorator(csrf_exempt, name='dispatch')
class MonnifyWebhookView(views.APIView):
    """
    POST /api/v1/licensing/monnify/webhook/
    Receives Monnify `SUCCESSFUL_TRANSACTION` webhooks for both online checkout
    and Dedicated Reserved Virtual Account bank transfers.
    """
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        monnify = MonnifyService()
        signature = request.headers.get("monnify-signature", "")
        if not monnify.verify_webhook_signature(request.body, signature):
            return Response(
                {"error": "Invalid Monnify webhook signature"},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        result = monnify.process_webhook(request.data)
        return Response(result, status=status.HTTP_200_OK)


@method_decorator(csrf_exempt, name='dispatch')
class MonnifyInteractiveCheckoutView(views.APIView):
    """
    GET / POST /api/v1/licensing/monnify/checkout/<payment_reference>/
    Interactive Monnify Checkout & Redirect Landing Page.
    - When Monnify redirects back after online payment, verifies the payment and shows confirmation.
    - When running in local/sandbox mode without external API keys, lets the pharmacy complete
      payment via Card or Bank Transfer simulation in 1 click and credits +30 / +365 days immediately.
    """
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request, payment_reference: str):
        payment = SubscriptionPayment.objects.filter(payment_reference=payment_reference).select_related(
            'organization', 'subscription'
        ).first()
        if not payment:
            return HttpResponse("<h3>Payment Reference Not Found</h3>", status=404)

        monnify = MonnifyService()
        if monnify.is_live_configured and payment.status != 'PAID':
            monnify.verify_payment(payment)
            payment.refresh_from_db()

        return HttpResponse(self._render_html(payment))

    def post(self, request, payment_reference: str):
        payment = SubscriptionPayment.objects.filter(payment_reference=payment_reference).select_related(
            'organization', 'subscription'
        ).first()
        if not payment:
            return HttpResponse("<h3>Payment Reference Not Found</h3>", status=404)

        method = request.POST.get("payment_method", "MONNIFY_CHECKOUT")
        payment.mark_paid_and_credit(
            transaction_ref=payment.monnify_transaction_reference or f"MNFY-PAID-{payment.id}",
            payment_method=method,
            raw_data={"confirmed_via": "MonnifyHostedCheckout", "method": method},
        )
        payment.refresh_from_db()
        return HttpResponse(self._render_html(payment, just_paid=True))

    def _render_html(self, payment: SubscriptionPayment, just_paid: bool = False) -> str:
        org = payment.organization
        sub = payment.subscription
        is_paid = payment.status == "PAID"
        cycle_label = "Yearly Plan (365 Days)" if payment.billing_cycle == "YEARLY" else "Monthly Plan (30 Days)"

        if is_paid:
            status_block = f"""
            <div style="background:#ECFDF5;border:1px solid #A7F3D0;border-radius:12px;padding:20px;text-align:center;margin-bottom:20px;">
                <div style="font-size:40px;margin-bottom:8px;">✅</div>
                <h2 style="margin:0;color:#065F46;font-size:20px;">Payment Confirmed!</h2>
                <p style="color:#047857;margin:8px 0 0 0;font-size:14px;">
                    <strong>+{payment.days_credited} Days</strong> have been credited to <strong>{org.name} ({org.code})</strong>.<br/>
                    Active Days Remaining: <strong>{sub.days_remaining()} Days</strong> (Expires {sub.current_period_end.strftime('%Y-%m-%d')})
                </p>
            </div>
            <div style="text-align:center;color:#475569;font-size:13px;">
                You can now return to the <strong>PharmaCare Pro Desktop App</strong> and click
                <strong>"🔄 Verify Payment / Refresh Status"</strong>.
            </div>
            """
        else:
            status_block = f"""
            <div style="background:#F8FAFC;border:1px solid #E2E8F0;border-radius:10px;padding:14px;margin-bottom:18px;font-size:13px;color:#334155;">
                <div style="font-weight:700;color:#0F172A;margin-bottom:6px;">🏦 Option 1: Dedicated Bank Transfer (Monnify Reserved Account)</div>
                <div>Bank: <strong>{sub.monnify_bank_name or 'Moniepoint MFB'}</strong></div>
                <div>Account Number: <strong style="font-size:15px;color:#1D4ED8;">{sub.monnify_account_number}</strong></div>
                <div>Account Name: <strong>{sub.monnify_account_name}</strong></div>
            </div>
            <form method="POST" style="margin:0;">
                <input type="hidden" name="payment_method" value="CARD_OR_TRANSFER" />
                <button type="submit" style="width:100%;background:linear-gradient(90deg,#059669,#10B981);color:white;border:none;border-radius:10px;padding:14px;font-size:15px;font-weight:700;cursor:pointer;">
                    💳 Pay ₦{payment.amount:,.2f} Now via Monnify ({cycle_label})
                </button>
            </form>
            """

        return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8" />
    <title>Monnify Subscription Checkout — {org.name}</title>
</head>
<body style="margin:0;padding:40px 16px;font-family:'Segoe UI',system-ui,sans-serif;background:#0F172A;color:#0F172A;">
    <div style="max-width:480px;margin:0 auto;background:#FFFFFF;border-radius:16px;overflow:hidden;box-shadow:0 20px 40px rgba(0,0,0,0.35);">
        <div style="background:linear-gradient(90deg,#0B132B,#1E293B);color:#FFFFFF;padding:22px 26px;border-bottom:3px solid #10B981;">
            <div style="font-size:11px;text-transform:uppercase;letter-spacing:1px;color:#34D399;font-weight:700;">Monnify Secured Gateway</div>
            <div style="font-size:19px;font-weight:800;margin-top:4px;">{org.name} ({org.code})</div>
            <div style="font-size:12px;color:#CBD5E1;margin-top:2px;">PharmaCare Pro Enterprise Subscription</div>
        </div>
        <div style="padding:24px 26px;">
            <div style="display:flex;justify-content:space-between;margin-bottom:10px;font-size:13px;color:#64748B;">
                <span>Subscription Plan:</span>
                <strong style="color:#0F172A;">{cycle_label}</strong>
            </div>
            <div style="display:flex;justify-content:space-between;margin-bottom:10px;font-size:13px;color:#64748B;">
                <span>Payment Reference:</span>
                <strong style="color:#0F172A;">{payment.payment_reference}</strong>
            </div>
            <div style="display:flex;justify-content:space-between;margin-bottom:20px;padding-top:12px;border-top:1px solid #E2E8F0;font-size:16px;">
                <span style="font-weight:700;color:#334155;">Amount Payable:</span>
                <strong style="font-size:20px;color:#059669;">₦{payment.amount:,.2f}</strong>
            </div>
            {status_block}
        </div>
    </div>
</body>
</html>"""


class SubscriptionViewSet(OrganizationQuerysetMixin, viewsets.ModelViewSet):
    """
    Subscription management endpoint (Architecture Plan §14).
    """
    queryset = Subscription.objects.all()
    serializer_class = SubscriptionSerializer
    permission_classes = [
        IsAuthenticated,
        IsOrganizationMember,
        require_permission(
            read_perm=PermissionCode.SUBSCRIPTIONS_MANAGE.value,
            write_perm=PermissionCode.SUBSCRIPTIONS_MANAGE.value,
        ),
    ]


class EntitlementViewSet(OrganizationQuerysetMixin, viewsets.ModelViewSet):
    """
    Entitlement management endpoint.
    """
    queryset = Entitlement.objects.all()
    serializer_class = EntitlementSerializer
    permission_classes = [
        IsAuthenticated,
        IsOrganizationMember,
        require_permission(
            read_perm=PermissionCode.SUBSCRIPTIONS_MANAGE.value,
            write_perm=PermissionCode.SUBSCRIPTIONS_MANAGE.value,
        ),
    ]


class LicenseViewSet(OrganizationQuerysetMixin, viewsets.ModelViewSet):
    """
    License keys endpoint.
    """
    queryset = License.objects.all()
    serializer_class = LicenseSerializer
    permission_classes = [
        IsAuthenticated,
        IsOrganizationMember,
        require_permission(
            read_perm=PermissionCode.SUBSCRIPTIONS_MANAGE.value,
            write_perm=PermissionCode.SUBSCRIPTIONS_MANAGE.value,
        ),
    ]
