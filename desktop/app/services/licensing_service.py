import hashlib
import json
import math
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from desktop.app.db.models import LicenseState, Organization
from desktop.app.services.base_service import BaseService
from desktop.app.utils.date_utils import parse_iso, utc_now
from shared.enums import LicenseStatus, SubscriptionStatus


class LicensingService(BaseService):
    """
    Offline-Capable Subscription Countdown & Monnify Licensing Service (Architecture Plan §14).
    - Every time the desktop connects to the internet, it syncs the authoritative subscription
      state (`current_period_end`, `monthly_price`, `yearly_price`, `status`, and Monnify virtual account)
      from the Django server and saves it locally in SQLite (`LicenseState`).
    - Continuously counts down `days_remaining` locally even while offline.
    - Enforces hard-lock at 0 days left until renewed via Monnify or extended in Django Admin.
    """

    def _resolve_local_org(self, db, organization_id: str | None = None, org_code: str | None = None) -> Organization | None:
        if organization_id:
            org = db.query(Organization).filter_by(id=organization_id).first()
            if org:
                return org
        if org_code:
            org = db.query(Organization).filter(Organization.code.ilike(org_code.strip())).first()
            if org:
                return org
        return db.query(Organization).first()

    def cache_license_status(self, organization_id: str, payload: dict) -> LicenseState:
        now_iso = utc_now()
        raw_entitlements = payload.get("entitlements", {})
        if isinstance(raw_entitlements, str):
            try:
                ent_dict = json.loads(raw_entitlements)
            except Exception:
                ent_dict = {}
        elif isinstance(raw_entitlements, dict):
            ent_dict = dict(raw_entitlements)
        else:
            ent_dict = {}

        # Persist Monnify & pricing metadata inside entitlements JSON so it survives offline restarts
        for extra_key in (
            "monthly_price",
            "yearly_price",
            "currency",
            "days_remaining",
            "monnify_account_reference",
            "monnify_account_number",
            "monnify_account_name",
            "monnify_bank_name",
            "monnify_bank_code",
            "organization_code",
            "organization_name",
        ):
            if payload.get(extra_key) is not None:
                ent_dict[extra_key] = payload[extra_key]

        entitlements_str = json.dumps(ent_dict)

        with self.transaction() as db:
            target_org_id = organization_id
            if not target_org_id:
                org = self._resolve_local_org(db, org_code=payload.get("organization_code"))
                if org:
                    target_org_id = org.id

            state = db.query(LicenseState).filter_by(organization_id=target_org_id).first()
            if not state:
                state = LicenseState(
                    organization_id=target_org_id,
                    status=payload.get("status", LicenseStatus.ACTIVE.value),
                    plan=payload.get("plan", "standard"),
                    current_period_end=payload.get("current_period_end"),
                    grace_period_days=int(payload.get("grace_period_days", 0)),
                    entitlements=entitlements_str,
                    last_checked_at=now_iso,
                    updated_at=now_iso,
                )
                db.add(state)
            else:
                state.status = payload.get("status", state.status)
                state.plan = payload.get("plan", state.plan)
                if payload.get("current_period_end"):
                    state.current_period_end = payload["current_period_end"]
                if "grace_period_days" in payload:
                    state.grace_period_days = int(payload["grace_period_days"])
                state.entitlements = entitlements_str
                state.last_checked_at = now_iso
                state.updated_at = now_iso

            db.flush()
            return state

    def get_license_state(self, organization_id: str | None = None, org_code: str | None = None) -> dict | None:
        with self.transaction() as db:
            state = None
            if organization_id:
                state = db.query(LicenseState).filter_by(organization_id=organization_id).first()
            if not state and org_code:
                org = self._resolve_local_org(db, org_code=org_code)
                if org:
                    state = db.query(LicenseState).filter_by(organization_id=org.id).first()
            if not state and not organization_id:
                state = db.query(LicenseState).first()
            if not state:
                return None

            ent_dict = {}
            if state.entitlements:
                try:
                    ent_dict = json.loads(state.entitlements)
                except Exception:
                    ent_dict = {}

            days_left = 0
            if state.status not in (
                LicenseStatus.SUSPENDED.value,
                LicenseStatus.CANCELLED.value,
                SubscriptionStatus.CANCELLED.value,
            ):
                if state.current_period_end:
                    try:
                        end_dt = parse_iso(state.current_period_end)
                        diff_sec = (end_dt - datetime.now(timezone.utc)).total_seconds()
                        if diff_sec > 0:
                            days_left = max(0, int(math.ceil(diff_sec / 86400.0)))
                    except Exception:
                        days_left = 0

            effective_status = state.status
            if state.status in (LicenseStatus.SUSPENDED.value, LicenseStatus.CANCELLED.value):
                effective_status = state.status
            elif days_left <= 0:
                effective_status = SubscriptionStatus.EXPIRED.value

            monthly_price = Decimal(str(ent_dict.get("monthly_price") or "25000.00"))
            yearly_price = Decimal(str(ent_dict.get("yearly_price") or "250000.00"))

            return {
                "organization_id": state.organization_id,
                "organization_code": ent_dict.get("organization_code", org_code or "MEDCARE"),
                "organization_name": ent_dict.get("organization_name", "MedCare Pharmacy"),
                "status": state.status,
                "effective_status": effective_status,
                "plan": state.plan,
                "current_period_end": state.current_period_end,
                "days_remaining": days_left,
                "grace_period_days": state.grace_period_days,
                "monthly_price": monthly_price,
                "yearly_price": yearly_price,
                "currency": ent_dict.get("currency", "NGN"),
                "monnify_account_reference": ent_dict.get("monnify_account_reference", ""),
                "monnify_account_number": ent_dict.get("monnify_account_number", ""),
                "monnify_account_name": ent_dict.get("monnify_account_name", ""),
                "monnify_bank_name": ent_dict.get("monnify_bank_name", "Moniepoint MFB (Monnify Reserved)"),
                "monnify_bank_code": ent_dict.get("monnify_bank_code", "50515"),
                "entitlements": ent_dict,
                "last_checked_at": state.last_checked_at,
            }

    def ensure_or_get_subscription_state(
        self,
        organization_id: str | None = None,
        org_code: str = "MEDCARE",
        org_name: str = "MedCare Pharmacy",
    ) -> dict:
        with self.transaction() as db:
            org = self._resolve_local_org(db, organization_id=organization_id, org_code=org_code)
            resolved_org_id = org.id if org else (organization_id or "default-org")
            resolved_code = (org.code if org else org_code or "MEDCARE").strip().upper()
            resolved_name = (org.name if org else org_name or "MedCare Pharmacy").strip()

        existing = self.get_license_state(organization_id=resolved_org_id, org_code=resolved_code)
        if existing:
            if not existing.get("monnify_account_number"):
                digest = hashlib.sha256(resolved_code.encode("utf-8")).hexdigest()
                acc_no = f"80{str(int(digest[:10], 16))[-8:].zfill(8)}"
                existing["monnify_account_number"] = acc_no
                existing["monnify_account_name"] = f"PharmaCare - {resolved_name}"
                existing["monnify_bank_name"] = "Moniepoint MFB (Monnify Reserved)"
            return existing

        digest = hashlib.sha256(resolved_code.encode("utf-8")).hexdigest()
        acc_no = f"80{str(int(digest[:10], 16))[-8:].zfill(8)}"
        default_end = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
        payload = {
            "status": SubscriptionStatus.ACTIVE.value,
            "plan": "standard",
            "current_period_end": default_end,
            "grace_period_days": 0,
            "monthly_price": "25000.00",
            "yearly_price": "250000.00",
            "currency": "NGN",
            "organization_code": resolved_code,
            "organization_name": resolved_name,
            "monnify_account_reference": f"PHARM-{resolved_code}",
            "monnify_account_number": acc_no,
            "monnify_account_name": f"PharmaCare - {resolved_name}",
            "monnify_bank_name": "Moniepoint MFB (Monnify Reserved)",
            "monnify_bank_code": "50515",
        }
        self.cache_license_status(resolved_org_id, payload)
        return self.get_license_state(organization_id=resolved_org_id, org_code=resolved_code)

    def sync_subscription_from_server(
        self,
        api_client,
        organization_id: str | None = None,
        org_code: str = "MEDCARE",
    ) -> dict | None:
        """
        Contacts the Django server (`/api/v1/licensing/status/`) to fetch the latest
        subscription days left, monthly/yearly pricing, and Monnify virtual account details,
        and saves them locally into SQLite (`LicenseState`).
        """
        if not api_client:
            return self.get_license_state(organization_id=organization_id, org_code=org_code)

        with self.transaction() as db:
            org = self._resolve_local_org(db, organization_id=organization_id, org_code=org_code)
            local_org_id = org.id if org else (organization_id or "")
            resolved_code = (org.code if org else org_code or "MEDCARE").strip().upper()

        try:
            data = api_client.get(
                "licensing/status/",
                params={"org_code": resolved_code},
            )
            if isinstance(data, dict) and "status" in data:
                target_id = local_org_id or str(data.get("organization_id") or "default-org")
                self.cache_license_status(target_id, data)
                return self.get_license_state(organization_id=target_id, org_code=resolved_code)
        except Exception:
            pass
        return self.get_license_state(organization_id=local_org_id, org_code=resolved_code)

    def initiate_monnify_payment(
        self,
        api_client,
        organization_id: str | None = None,
        org_code: str = "MEDCARE",
        billing_cycle: str = "MONTHLY",
    ) -> dict:
        with self.transaction() as db:
            org = self._resolve_local_org(db, organization_id=organization_id, org_code=org_code)
            local_org_id = org.id if org else (organization_id or "")
            resolved_code = (org.code if org else org_code or "MEDCARE").strip().upper()

        resp = api_client.post(
            "licensing/monnify/initiate/",
            data={
                "org_code": resolved_code,
                "billing_cycle": billing_cycle.upper(),
            },
        )
        if isinstance(resp, dict) and resp.get("subscription"):
            self.cache_license_status(local_org_id or resp["subscription"].get("organization_id", ""), resp["subscription"])
        return resp

    def verify_monnify_payment(
        self,
        api_client,
        organization_id: str | None = None,
        org_code: str = "MEDCARE",
        payment_reference: str = "",
    ) -> dict:
        with self.transaction() as db:
            org = self._resolve_local_org(db, organization_id=organization_id, org_code=org_code)
            local_org_id = org.id if org else (organization_id or "")
            resolved_code = (org.code if org else org_code or "MEDCARE").strip().upper()

        resp = api_client.post(
            "licensing/monnify/verify/",
            data={
                "org_code": resolved_code,
                "payment_reference": payment_reference,
            },
        )
        if isinstance(resp, dict) and resp.get("subscription"):
            target_id = local_org_id or resp["subscription"].get("organization_id", "")
            self.cache_license_status(target_id, resp["subscription"])
            resp["local_state"] = self.get_license_state(organization_id=target_id, org_code=resolved_code)
        return resp

    def is_subscription_locked(
        self,
        organization_id: str | None = None,
        org_code: str = "MEDCARE",
    ) -> tuple[bool, dict]:
        """
        Hard lock check: returns (True, state) immediately when days_remaining <= 0
        or status is EXPIRED / SUSPENDED / CANCELLED.
        """
        state = self.ensure_or_get_subscription_state(organization_id=organization_id, org_code=org_code)
        eff = state.get("effective_status", "ACTIVE")
        days = int(state.get("days_remaining", 0))
        if days <= 0 or eff in (
            LicenseStatus.EXPIRED.value,
            SubscriptionStatus.EXPIRED.value,
            LicenseStatus.SUSPENDED.value,
            LicenseStatus.CANCELLED.value,
            SubscriptionStatus.CANCELLED.value,
        ):
            return True, state
        return False, state

    def check_operation_allowed(
        self, organization_id: str, operation: str = "WRITE"
    ) -> tuple[bool, str]:
        """
        Evaluates whether an operation is permitted according to Architecture Plan §14.3.
        - TRIAL or ACTIVE: Full functionality indefinitely while offline.
        - EXPIRED (within grace period): Warning banner, full functionality.
        - EXPIRED (beyond grace period): Read-only mode.
        - SUSPENDED: Read-only mode.
        - Unknown/missing: Read-only mode (requires online login).
        """
        if operation == "READ":
            return True, ""

        state = self.get_license_state(organization_id)
        if not state:
            return False, "No valid license cached. Internet connection required to verify license."

        status_val = state.get("status")

        if status_val in [LicenseStatus.TRIAL.value, LicenseStatus.ACTIVE.value, SubscriptionStatus.ACTIVE.value]:
            return True, ""

        if status_val in [LicenseStatus.EXPIRED.value, SubscriptionStatus.EXPIRED.value]:
            period_end_str = state.get("current_period_end")
            grace_days = state.get("grace_period_days", 14)
            if period_end_str:
                try:
                    end_dt = parse_iso(period_end_str)
                    now_dt = datetime.now(timezone.utc)
                    if now_dt <= end_dt:
                        return True, ""
                    days_overdue = (now_dt - end_dt).days
                    if days_overdue <= grace_days and grace_days > 0:
                        remaining = max(0, grace_days - days_overdue)
                        return True, f"Subscription expired. Renew within {remaining} days."
                    else:
                        return False, "Subscription expired and grace period ended. System is in read-only mode."
                except Exception:
                    pass
            return False, "Subscription expired and grace period ended. System is in read-only mode."

        if status_val in [LicenseStatus.SUSPENDED.value, LicenseStatus.CANCELLED.value, SubscriptionStatus.CANCELLED.value]:
            return False, f"Subscription is {status_val.lower()}. System is in read-only mode."

        return False, "Unknown license status. System is in read-only mode."
