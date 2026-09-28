import uuid
from datetime import datetime, timedelta
from django.utils import timezone
import pytest

from apps.audit.models import AuditEvent
from apps.audit.services import archive_old_audit_events
from apps.branches.models import Branch, Device
from apps.inventory.models import (
    Batch,
    BranchInventory,
    InventoryAlert,
    InventoryMovement,
)
from apps.inventory.services import reconcile_branch_inventory
from apps.organizations.models import Organization
from apps.users.models import User
from apps.products.models import Category, Product
from apps.sync.models import SyncDelivery
from apps.sync.services import cleanup_expired_sync_deliveries
from shared.enums import (
    AuditAction,
    AuditSource,
    BatchStatus,
    InventoryAlertType,
    MovementType,
    SyncTargetScope,
)


@pytest.mark.django_db
class TestPhase16ServerHardeningAcceptance:
    """
    Phase 16 Acceptance Tests: Server Hardening, Retention Pruning & Inventory Reconciliation (Architecture Plan §3.3, §4, §15, §16).
    Validates:
    1. Automated SyncDelivery retention pruning (expired rows deleted, unexpired retained).
    2. AuditEvent retention archival based on organization configuration.
    3. Ledger reconciliation invariant (BranchInventory.quantity == SUM(InventoryMovement))
       flagging mismatches via InventoryAlert(RECONCILIATION_MISMATCH) without auto-fixing.
    """

    def test_sync_delivery_retention_pruning(self):
        org = Organization.objects.create(name="Pruning Org", code="PRUN-01")
        now = timezone.now()

        # Expired delivery (expires_at in past)
        expired_delivery = SyncDelivery.objects.create(
            organization=org,
            entity_type="Product",
            entity_id=uuid.uuid4(),
            operation="CREATE",
            payload={"name": "Old Product"},
            target_scope=SyncTargetScope.ORGANIZATION.value,
            expires_at=now - timedelta(days=1),
        )

        # Active delivery (expires_at in future)
        active_delivery = SyncDelivery.objects.create(
            organization=org,
            entity_type="Product",
            entity_id=uuid.uuid4(),
            operation="CREATE",
            payload={"name": "Active Product"},
            target_scope=SyncTargetScope.ORGANIZATION.value,
            expires_at=now + timedelta(days=89),
        )

        deleted = cleanup_expired_sync_deliveries(organization_id=org.id)
        assert deleted == 1
        assert not SyncDelivery.objects.filter(id=expired_delivery.id).exists()
        assert SyncDelivery.objects.filter(id=active_delivery.id).exists()

    def test_audit_event_retention_archival(self):
        org = Organization.objects.create(
            name="Audit Archival Org",
            code="AUD-ARC-01",
            settings={"audit_retention_days": 365},
        )
        now = timezone.now()

        # Old audit event
        old_audit = AuditEvent.objects.create(
            organization=org,
            branch_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            action=AuditAction.PRODUCT_UPDATED.value,
            entity_type="Organization",
            entity_id=org.id,
            source=AuditSource.SERVER.value,
            local_timestamp=now - timedelta(days=400),
        )
        AuditEvent.objects.filter(id=old_audit.id).update(created_at=now - timedelta(days=400))

        # Recent audit event
        recent_audit = AuditEvent.objects.create(
            organization=org,
            branch_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            action=AuditAction.USER_LOGIN.value,
            entity_type="User",
            entity_id=uuid.uuid4(),
            source=AuditSource.SERVER.value,
            local_timestamp=now - timedelta(days=10),
        )

        pruned = archive_old_audit_events(organization_id=org.id)
        assert pruned == 1
        assert not AuditEvent.objects.filter(id=old_audit.id).exists()
        assert AuditEvent.objects.filter(id=recent_audit.id).exists()

    def test_inventory_ledger_reconciliation_detects_mismatch_without_auto_fix(self):
        org = Organization.objects.create(name="Reconcile Org", code="REC-01")
        branch = Branch.objects.create(organization=org, name="Reconcile Branch", code="RBR")
        cat = Category.objects.create(organization=org, name="General")
        prod = Product.objects.create(organization=org, name="Paracetamol", category=cat)

        batch_matched = Batch.objects.create(
            organization=org,
            product=prod,
            batch_number="BATCH-OK",
            purchase_price="10.00",
            received_date=timezone.now().date(),
            expiry_date=timezone.now().date() + timedelta(days=365),
            status=BatchStatus.ACTIVE.value,
        )
        batch_mismatch = Batch.objects.create(
            organization=org,
            product=prod,
            batch_number="BATCH-DISCREPANCY",
            purchase_price="10.00",
            received_date=timezone.now().date(),
            expiry_date=timezone.now().date() + timedelta(days=365),
            status=BatchStatus.ACTIVE.value,
        )

        user = User.objects.create(
            organization=org,
            username="recuser",
            full_name="Reconcile User",
        )

        # 1. Matched Inventory (Recorded = 20, Movement sum = 20)
        bi_matched = BranchInventory.objects.create(
            organization=org,
            branch=branch,
            batch=batch_matched,
            quantity=20,
        )
        InventoryMovement.objects.create(
            organization=org,
            branch=branch,
            batch=batch_matched,
            movement_type=MovementType.STOCK_RECEIVED.value,
            quantity_before=0,
            quantity_change=20,
            quantity_after=20,
            reference_type="STOCK_RECEIVE",
            reference_id=uuid.uuid4(),
            user=user,
            local_timestamp=timezone.now(),
        )

        # 2. Mismatched Inventory (Recorded = 50, but Movement sum = 35 -> Discrepancy of 15)
        bi_mismatch = BranchInventory.objects.create(
            organization=org,
            branch=branch,
            batch=batch_mismatch,
            quantity=50,
        )
        InventoryMovement.objects.create(
            organization=org,
            branch=branch,
            batch=batch_mismatch,
            movement_type=MovementType.STOCK_RECEIVED.value,
            quantity_before=0,
            quantity_change=35,
            quantity_after=35,
            reference_type="STOCK_RECEIVE",
            reference_id=uuid.uuid4(),
            user=user,
            local_timestamp=timezone.now(),
        )

        # Run automated reconciliation job
        discrepancies = reconcile_branch_inventory(organization_id=org.id, branch_id=branch.id)

        assert len(discrepancies) == 1
        alert = discrepancies[0]
        assert alert.alert_type == InventoryAlertType.RECONCILIATION_MISMATCH.value
        assert alert.batch == batch_mismatch
        assert alert.details["recorded_quantity"] == 50
        assert alert.details["movement_sum"] == 35
        assert alert.details["discrepancy"] == 15

        # Crucial architectural invariant: recorded quantity must NOT be auto-fixed!
        bi_mismatch.refresh_from_db()
        assert bi_mismatch.quantity == 50

    def test_cloud_branch_backup_filo_retention_and_download(self):
        import base64
        import zlib
        from rest_framework.test import APIClient
        from apps.sync.models import BranchBackup

        client = APIClient()
        org = Organization.objects.create(name="Cloud Backup Org", code="CBK-01")

        # Upload 6 distinct backups for branch HQ -> only the 4 most recent should be retained in FILO order
        for i in range(1, 7):
            raw_db = f"SQLite format 3 backup snapshot #{i}".encode("utf-8")
            comp_b64 = base64.b64encode(zlib.compress(raw_db)).decode("ascii")
            res = client.post(
                "/api/v1/sync/backups/upload/",
                {
                    "org_code": org.code,
                    "branch_code": "HQ",
                    "branch_name": "Main Branch",
                    "device_code": "POS01",
                    "filename": f"backup_{i}.db",
                    "size_bytes": len(raw_db),
                    "checksum_sha256": f"hash_{i}",
                    "compressed_b64": comp_b64,
                    "note": f"Sync #{i}",
                    "force_new_slot": True,
                },
                format="json",
            )
            assert res.status_code == 201

        hq_backups = list(BranchBackup.objects.filter(organization=org, branch_code="HQ").order_by("-created_at"))
        assert len(hq_backups) == 4
        # FILO/LIFO: newest (#6) is first, followed by #5, #4, #3 (#1 and #2 were pruned)
        assert [b.note for b in hq_backups] == ["Sync #6", "Sync #5", "Sync #4", "Sync #3"]

        # List endpoint returns the 4 FILO backups
        list_res = client.get(f"/api/v1/sync/backups/?org_code={org.code}&branch_code=HQ")
        assert list_res.status_code == 200
        assert len(list_res.data["backups"]) == 4
        latest_id = list_res.data["backups"][0]["id"]
        assert list_res.data["backups"][0]["note"] == "Sync #6"

        # Download endpoint returns the exact compressed payload for the latest backup
        dl_res = client.get(f"/api/v1/sync/backups/{latest_id}/download/")
        assert dl_res.status_code == 200
        restored_bytes = zlib.decompress(base64.b64decode(dl_res.data["compressed_b64"]))
        assert restored_bytes == b"SQLite format 3 backup snapshot #6"

