import base64
import uuid
import zlib
from django.db.models import Q, Min
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import views, status
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response

from apps.branches.models import Branch
from apps.core.permissions import IsOrganizationMember
from apps.organizations.models import Organization
from apps.users.models import User
from shared.enums import SyncTargetScope, LicenseStatus
from .models import SyncDelivery, BranchBackup
from .serializers import SyncUploadRequestSerializer, SyncDeliverySerializer, BranchBackupSerializer
from .services import process_sync_upload_batch


def _resolve_sync_org(request) -> Organization | None:
    if request.user and request.user.is_authenticated and getattr(request.user, 'organization_id', None):
        return request.user.organization
    org_code = (
        request.query_params.get('org_code')
        or request.data.get('org_code')
        or ''
    ).strip().upper()
    org_id = (
        request.query_params.get('organization_id')
        or request.data.get('organization_id')
        or ''
    ).strip()
    org_name = (
        request.data.get('organization_name')
        or org_code
        or 'MedCare Pharmacy'
    ).strip()

    if org_id:
        try:
            org = Organization.objects.filter(id=uuid.UUID(org_id)).first()
            if org:
                return org
        except Exception:
            pass
    if org_code:
        org = Organization.objects.filter(code__iexact=org_code).first()
        if not org:
            org = Organization.objects.create(
                code=org_code,
                name=org_name,
            )
        return org
    return Organization.objects.first()


class SyncUploadView(views.APIView):
    """
    POST /api/v1/sync/upload/
    Accepts batched outbox events from a desktop device, groups correlated events
    by correlation_id, processes each group atomically with ProcessedEvent idempotency,
    and generates SyncDelivery rows for downstream devices.
    """

    permission_classes = [IsAuthenticated, IsOrganizationMember]

    def post(self, request):
        serializer = SyncUploadRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        results = process_sync_upload_batch(
            organization=request.user.organization,
            branch_id=data['branch_id'],
            device_id=data['device_id'],
            request_user=request.user,
            events=data['events'],
        )
        return Response(
            {
                "device_id": str(data['device_id']),
                "branch_id": str(data['branch_id']),
                "results": results,
            },
            status=status.HTTP_200_OK,
        )


class SyncDownloadView(views.APIView):
    """
    GET /api/v1/sync/download/?branch_id=...&device_id=...&last_sequence=0&limit=100
    Returns monotonic SyncDelivery records for the organization/branch, excluding
    deliveries originating from the requesting `device_id` (device-level echo suppression).
    Also piggybacks `license_status` and `disabled_user_ids`.
    """

    permission_classes = [IsAuthenticated, IsOrganizationMember]

    def get(self, request):
        branch_id_str = request.query_params.get('branch_id')
        device_id_str = request.query_params.get('device_id')
        if not branch_id_str or not device_id_str:
            raise DRFValidationError(
                {"detail": "Both 'branch_id' and 'device_id' query parameters are required."}
            )

        try:
            branch_id = uuid.UUID(str(branch_id_str))
            device_id = uuid.UUID(str(device_id_str))
            last_sequence = int(request.query_params.get('last_sequence', 0))
            limit = min(int(request.query_params.get('limit', 100)), 500)
        except ValueError as exc:
            raise DRFValidationError({"detail": f"Invalid parameter: {exc}"})

        org = request.user.organization

        # Check for sequence gap (if retention purged old SyncDelivery rows before last_sequence)
        org_deliveries = SyncDelivery.objects.filter(organization=org)
        min_seq = org_deliveries.aggregate(min_id=Min('id'))['min_id']
        needs_full_resync = False
        if last_sequence > 0 and min_seq is not None and last_sequence < (min_seq - 1):
            needs_full_resync = True

        # Filter relevant deliveries for this branch, excluding events from the same device_id
        qs = (
            org_deliveries.filter(id__gt=last_sequence)
            .filter(
                Q(target_scope__in=[SyncTargetScope.ALL_BRANCHES.value, SyncTargetScope.ORGANIZATION.value])
                | Q(target_scope=SyncTargetScope.SPECIFIC_BRANCH.value, target_branch_id=branch_id)
            )
            .exclude(source_device_id=device_id)
            .order_by('id')
        )

        deliveries_plus_one = list(qs[: limit + 1])
        has_more = len(deliveries_plus_one) > limit
        deliveries = deliveries_plus_one[:limit]

        new_last_sequence = deliveries[-1].id if deliveries else last_sequence

        # Piggyback disabled user IDs for immediate local lockout
        disabled_user_ids = [
            str(uid)
            for uid in User.objects.filter(organization=org, is_active=False).values_list('id', flat=True)
        ]

        # Piggyback license_status from Subscription (Phase 15) or org.settings fallback
        try:
            from apps.licensing.models import Subscription
            sub = Subscription.objects.filter(organization=org).first()
            if sub:
                license_status = sub.to_sync_payload()
            else:
                org_settings = org.settings or {}
                license_status = org_settings.get('license_status', {
                    "status": LicenseStatus.ACTIVE.value,
                    "plan": "professional",
                    "current_period_end": (timezone.now() + timezone.timedelta(days=365)).isoformat(),
                    "grace_period_days": 14,
                    "entitlements": {"max_branches": "10", "max_devices": "20"},
                    "checked_at": timezone.now().isoformat(),
                })
        except Exception:
            org_settings = org.settings or {}
            license_status = org_settings.get('license_status', {
                "status": LicenseStatus.ACTIVE.value,
                "checked_at": timezone.now().isoformat(),
            })

        return Response(
            {
                "deliveries": SyncDeliverySerializer(deliveries, many=True).data,
                "last_sequence": new_last_sequence,
                "has_more": has_more,
                "needs_full_resync": needs_full_resync,
                "disabled_user_ids": disabled_user_ids,
                "license_status": license_status,
            },
            status=status.HTTP_200_OK,
        )


class BranchBackupUploadView(views.APIView):
    """
    POST /api/v1/sync/backups/upload/
    Uploads a compressed SQLite branch backup snapshot whenever a branch syncs.
    Enforces a strict 4-backup FILO/LIFO stack per branch:
    - Keeps at most 4 backups per branch (ordered newest-first so the last backup in is the first one out).
    - If the latest backup for the branch has the exact same SHA-256 checksum (no DB changes since last sync),
      overrides/updates that top slot in-place; when changes occur, pushes a new slot and prunes beyond 4.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        org = _resolve_sync_org(request)
        if not org:
            return Response(
                {"error": "Organization not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        branch_code = (request.data.get('branch_code') or 'HQ').strip().upper()
        branch_name = (request.data.get('branch_name') or 'Main Branch').strip()
        branch_id_str = (request.data.get('branch_id') or '').strip()
        device_code = (request.data.get('device_code') or 'POS01').strip().upper()
        filename = (request.data.get('filename') or f"branch_{branch_code}_backup.db").strip()
        checksum = (request.data.get('checksum_sha256') or '').strip()
        size_bytes = int(request.data.get('size_bytes') or 0)
        note = (request.data.get('note') or 'Auto-Sync Cloud Backup').strip()
        force_new_slot = bool(request.data.get('force_new_slot', False))
        compressed_b64 = request.data.get('compressed_b64') or ''

        if not compressed_b64:
            return Response(
                {"error": "Missing 'compressed_b64' backup payload."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            compressed_bytes = base64.b64decode(compressed_b64)
        except Exception as exc:
            return Response(
                {"error": f"Invalid base64 backup payload: {exc}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Resolve or create the Branch record on the server
        branch_obj = None
        if branch_id_str:
            try:
                branch_obj = Branch.objects.filter(id=uuid.UUID(branch_id_str), organization=org).first()
            except Exception:
                pass
        if not branch_obj:
            branch_obj = Branch.objects.filter(organization=org, code__iexact=branch_code).first()
        if not branch_obj:
            branch_obj = Branch.objects.create(
                organization=org,
                code=branch_code,
                name=branch_name,
            )

        existing_qs = BranchBackup.objects.filter(
            organization=org,
            branch_code__iexact=branch_code,
        ).order_by('-created_at', '-updated_at')
        latest = existing_qs.first()

        # If the database checksum is unchanged from the top slot (and not forced), override top slot in-place
        if latest and not force_new_slot and checksum and latest.checksum_sha256 == checksum:
            latest.branch = branch_obj
            latest.branch_name = branch_name
            latest.device_code = device_code
            latest.filename = filename
            latest.size_bytes = size_bytes
            latest.compressed_payload = compressed_bytes
            latest.note = note
            latest.created_at = timezone.now()
            latest.save()
            backup_obj = latest
        else:
            backup_obj = BranchBackup.objects.create(
                organization=org,
                branch=branch_obj,
                branch_code=branch_code,
                branch_name=branch_name,
                device_code=device_code,
                filename=filename,
                size_bytes=size_bytes,
                checksum_sha256=checksum,
                compressed_payload=compressed_bytes,
                note=note,
            )

        # Enforce max 4 backups per branch (FILO/LIFO stack)
        BranchBackup.enforce_branch_retention(org, branch_code, max_retain=BranchBackup.MAX_BACKUPS_PER_BRANCH)

        retained = BranchBackup.objects.filter(
            organization=org,
            branch_code__iexact=branch_code,
        ).order_by('-created_at')[:BranchBackup.MAX_BACKUPS_PER_BRANCH]

        return Response(
            {
                "backup": BranchBackupSerializer(backup_obj).data,
                "branch_backups": BranchBackupSerializer(retained, many=True).data,
                "max_backups_per_branch": BranchBackup.MAX_BACKUPS_PER_BRANCH,
            },
            status=status.HTTP_201_CREATED,
        )


class BranchBackupListView(views.APIView):
    """
    GET /api/v1/sync/backups/?org_code=MEDCARE&branch_code=HQ
    Lists up to 4 cloud backups per branch in FILO/LIFO order (newest first).
    Also returns a summary of all branches that have cloud backups for the pharmacy.
    """
    permission_classes = [AllowAny]

    def get(self, request):
        org = _resolve_sync_org(request)
        if not org:
            return Response(
                {"branches": [], "backups": [], "max_backups_per_branch": BranchBackup.MAX_BACKUPS_PER_BRANCH},
                status=status.HTTP_200_OK,
            )

        branch_code = (request.query_params.get('branch_code') or '').strip().upper()

        all_org_backups = BranchBackup.objects.filter(organization=org).order_by('-created_at')
        branches_map = {}
        for b in all_org_backups:
            bcode = b.branch_code.upper()
            if bcode not in branches_map:
                branches_map[bcode] = {
                    "branch_code": bcode,
                    "branch_name": b.branch_name,
                    "backup_count": 0,
                    "latest_backup_at": b.created_at.isoformat(),
                    "latest_backup_id": str(b.id),
                }
            if branches_map[bcode]["backup_count"] < BranchBackup.MAX_BACKUPS_PER_BRANCH:
                branches_map[bcode]["backup_count"] += 1

        if branch_code:
            BranchBackup.enforce_branch_retention(org, branch_code, max_retain=BranchBackup.MAX_BACKUPS_PER_BRANCH)
            qs = all_org_backups.filter(branch_code__iexact=branch_code)[:BranchBackup.MAX_BACKUPS_PER_BRANCH]
        else:
            # Return up to 4 per branch across the organization
            kept_ids = []
            per_branch_counts = {}
            for b in all_org_backups:
                bcode = b.branch_code.upper()
                cnt = per_branch_counts.get(bcode, 0)
                if cnt < BranchBackup.MAX_BACKUPS_PER_BRANCH:
                    kept_ids.append(b.id)
                    per_branch_counts[bcode] = cnt + 1
            qs = BranchBackup.objects.filter(id__in=kept_ids).order_by('-created_at')

        return Response(
            {
                "organization_code": org.code,
                "organization_name": org.name,
                "branches": list(branches_map.values()),
                "backups": BranchBackupSerializer(qs, many=True).data,
                "max_backups_per_branch": BranchBackup.MAX_BACKUPS_PER_BRANCH,
            },
            status=status.HTTP_200_OK,
        )


class BranchBackupDownloadView(views.APIView):
    """
    GET /api/v1/sync/backups/<uuid:backup_id>/download/
    Downloads a specific branch backup (or if ?raw=1, serves the decompressed .db file directly).
    """
    permission_classes = [AllowAny]

    def get(self, request, backup_id):
        bck = BranchBackup.objects.filter(id=backup_id).select_related('organization').first()
        if not bck:
            return Response(
                {"error": "Branch backup not found on server."},
                status=status.HTTP_404_NOT_FOUND,
            )

        raw_bytes = bytes(bck.compressed_payload)
        if request.query_params.get('raw') == '1':
            try:
                sqlite_bytes = zlib.decompress(raw_bytes)
            except Exception:
                sqlite_bytes = raw_bytes
            response = HttpResponse(sqlite_bytes, content_type='application/x-sqlite3')
            response['Content-Disposition'] = f'attachment; filename="{bck.filename}"'
            return response

        return Response(
            {
                "backup": BranchBackupSerializer(bck).data,
                "compressed_b64": base64.b64encode(raw_bytes).decode('ascii'),
            },
            status=status.HTTP_200_OK,
        )

