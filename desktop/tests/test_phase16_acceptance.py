import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
import pytest
from desktop.app.db.models import (
    Branch,
    BranchInventory,
    Category,
    InventoryAlert,
    InventoryMovement,
    Organization,
    Product,
    Batch,
    Role,
)
from desktop.app.services.backup_service import BackupService
from desktop.app.services.maintenance_service import MaintenanceService
from desktop.app.services.reconciliation_service import ReconciliationService
from shared.enums import InventoryAlertType, MovementType


class TestPhase16DesktopHardeningAcceptance:
    """
    Phase 16 Acceptance Tests: Desktop Hardening, SQLite Backups & Inventory Reconciliation (Architecture Plan §3.3, §15.1, §16).
    Validates:
    1. Zero-corruption SQLite online backups & 30-backup retention pruning.
    2. Disaster recovery restore from backup restoring database snapshot.
    3. Routine SQLite maintenance (PRAGMA optimize, WAL truncation, VACUUM, and integrity check).
    4. Local inventory ledger reconciliation detecting discrepancies and raising InventoryAlert without auto-fixing.
    """

    def test_backup_creation_listing_and_retention_pruning(self, db_manager, app_config):
        service = BackupService(db_manager, app_config)

        # 1. Create a backup
        meta = service.create_backup(note="test_initial")
        assert meta["filename"].startswith("pharmacy_backup_")
        assert Path(meta["path"]).exists()
        assert meta["size_bytes"] > 0

        # 2. Verify list_backups returns it
        backups = service.list_backups()
        assert len(backups) >= 1
        assert backups[0]["filename"] == meta["filename"]

        # 3. Test retention pruning: create 35 mock daily backups
        for i in range(35):
            dummy_file = service.backup_dir / f"pharmacy_backup_202601{i+1:02d}_000000.db"
            dummy_file.write_text("sqlite dummy content")

        # Create one more backup to trigger pruning
        service.create_backup(note="after_batch")

        remaining = [f for f in service.backup_dir.glob("pharmacy_backup*.db") if "prerestore" not in f.name]
        assert len(remaining) <= 4

    def test_backup_restore_restores_data(self, db_manager, app_config):
        backup_service = BackupService(db_manager, app_config)
        org_id = str(uuid.uuid4())

        # 1. Add baseline organization
        with db_manager.get_session() as db:
            org = Organization(id=org_id, name="Baseline Org", code="BASE-01")
            db.add(org)

        # 2. Take backup of baseline state
        backup_meta = backup_service.create_backup(note="baseline")
        bck_path = backup_meta["path"]

        # 3. Add mutated data after backup
        post_backup_org_id = str(uuid.uuid4())
        with db_manager.get_session() as db:
            mutated = Organization(id=post_backup_org_id, name="Post Backup Org", code="POST-01")
            db.add(mutated)

        # Verify mutated org exists
        with db_manager.get_session() as db:
            assert db.query(Organization).filter_by(id=post_backup_org_id).first() is not None

        # 4. Restore from baseline backup
        success = backup_service.restore_backup(bck_path)
        assert success is True

        # 5. Verify restored state: baseline org exists, post-backup org is gone
        with db_manager.get_session() as db:
            assert db.query(Organization).filter_by(id=org_id).first() is not None
            assert db.query(Organization).filter_by(id=post_backup_org_id).first() is None

    def test_database_maintenance_and_integrity_check(self, db_manager):
        maint_service = MaintenanceService(db_manager)

        # 1. Optimize database
        res = maint_service.optimize_database()
        assert res["status"] == "ok"
        assert res["optimized"] is True
        assert res["vacuumed"] is True

        # 2. Check integrity
        ok, msg = maint_service.check_integrity()
        assert ok is True
        assert "passed" in msg.lower() or "ok" in msg.lower()

    def test_local_inventory_ledger_reconciliation_detects_mismatch(self, db_manager):
        reconcile_service = ReconciliationService(db_manager)
        org_id = str(uuid.uuid4())
        branch_id = str(uuid.uuid4())
        cat_id = str(uuid.uuid4())
        prod_id = str(uuid.uuid4())
        batch_matched_id = str(uuid.uuid4())
        batch_mismatch_id = str(uuid.uuid4())

        with db_manager.get_session() as db:
            org = Organization(id=org_id, name="Reconcile Org", code="REC-01")
            branch = Branch(id=branch_id, organization_id=org_id, name="Branch 1", code="BR1")
            cat = Category(id=cat_id, organization_id=org_id, name="Medications")
            prod = Product(
                id=prod_id,
                organization_id=org_id,
                category_id=cat_id,
                sku="SKU-AMOX-01",
                name="Amoxicillin",
            )

            batch_matched = Batch(
                id=batch_matched_id,
                organization_id=org_id,
                product_id=prod_id,
                batch_number="B-MATCHED",
                purchase_price="12.00",
                received_date="2026-09-01",
                expiry_date="2027-09-01",
            )
            batch_mismatch = Batch(
                id=batch_mismatch_id,
                organization_id=org_id,
                product_id=prod_id,
                batch_number="B-MISMATCH",
                purchase_price="12.00",
                received_date="2026-09-01",
                expiry_date="2027-09-01",
            )

            db.add(org)
            db.flush()
            db.add_all([branch, cat])
            db.flush()
            db.add(prod)
            db.flush()
            db.add_all([batch_matched, batch_mismatch])
            db.flush()

            # Matched: Recorded = 20, Movement sum = 20
            bi_matched = BranchInventory(
                organization_id=org_id,
                branch_id=branch_id,
                batch_id=batch_matched_id,
                quantity=20,
            )
            mov_matched = InventoryMovement(
                organization_id=org_id,
                branch_id=branch_id,
                batch_id=batch_matched_id,
                movement_type=MovementType.STOCK_RECEIVED.value,
                quantity_before=0,
                quantity_change=20,
                quantity_after=20,
                reference_type="STOCK_RECEIVE",
                reference_id=str(uuid.uuid4()),
                user_id=str(uuid.uuid4()),
                local_timestamp=datetime.now(timezone.utc).isoformat(),
            )

            # Mismatched: Recorded = 40, Movement sum = 25 -> Discrepancy of 15
            bi_mismatch = BranchInventory(
                organization_id=org_id,
                branch_id=branch_id,
                batch_id=batch_mismatch_id,
                quantity=40,
            )
            mov_mismatch = InventoryMovement(
                organization_id=org_id,
                branch_id=branch_id,
                batch_id=batch_mismatch_id,
                movement_type=MovementType.STOCK_RECEIVED.value,
                quantity_before=0,
                quantity_change=25,
                quantity_after=25,
                reference_type="STOCK_RECEIVE",
                reference_id=str(uuid.uuid4()),
                user_id=str(uuid.uuid4()),
                local_timestamp=datetime.now(timezone.utc).isoformat(),
            )

            db.add_all([bi_matched, mov_matched, bi_mismatch, mov_mismatch])
            db.flush()

        # Run local inventory reconciliation
        discrepancies = reconcile_service.reconcile_branch_inventory(branch_id=branch_id)

        assert len(discrepancies) == 1
        d = discrepancies[0]
        assert d["recorded_quantity"] == 40
        assert d["movement_sum"] == 25
        assert d["discrepancy"] == 15

        # Verify InventoryAlert was created locally in database
        with db_manager.get_session() as db:
            alerts = db.query(InventoryAlert).filter_by(branch_id=branch_id).all()
            assert len(alerts) == 1
            assert alerts[0].alert_type == InventoryAlertType.RECONCILIATION_MISMATCH.value
            alert_details = json.loads(alerts[0].details)
            assert alert_details["recorded_quantity"] == 40
            assert alert_details["movement_sum"] == 25

            # Invariant check: Recorded quantity must NOT be auto-fixed!
            bi_check = db.query(BranchInventory).filter_by(batch_id=batch_mismatch_id).first()
            assert bi_check.quantity == 40

    def test_dashboard_rbac_unchecked_and_cloud_branch_restore_roundtrip(self, db_manager, app_config):
        import base64
        import zlib
        from desktop.app.auth.session import Session
        from desktop.app.services.user_service import UserService
        from shared.enums import PermissionCode

        user_service = UserService(db_manager)
        org_id = str(uuid.uuid4())
        branch_id = str(uuid.uuid4())

        with db_manager.get_session() as db:
            org = Organization(id=org_id, name="RBAC Pharmacy", code="RBAC-01")
            db.add(org)
            db.flush()
            branch = Branch(id=branch_id, organization_id=org_id, name="Main Branch", code="BR-MAIN")
            db.add(branch)
            db.flush()

        admin_session = Session(
            user_id=str(uuid.uuid4()),
            username="admin",
            full_name="System Admin",
            organization_id=org_id,
            organization_name="RBAC Pharmacy",
            branch_id=branch_id,
            branch_name="Main Branch",
            device_id=str(uuid.uuid4()),
            device_code="D01",
            permissions=[PermissionCode.USERS_MANAGE.value],
            roles=[{"id": "admin-role", "name": "Admin"}],
            is_offline=True,
            is_org_admin=True,
        )

        # Create role with POS checked and Dashboard UNCHECKED (matrix.configured present)
        role_obj = user_service.create_role(
            user_session=admin_session,
            name="Cashier No Dashboard",
            description="Cashier role without Dashboard checked",
            permission_codes=[
                "matrix.configured",
                PermissionCode.SALES_SELL.value,
                "matrix.r3.view",
            ],
        )
        role_id = role_obj.id
        role_perms = user_service.get_role_permissions(role_id)

        # Verify Session.has_permission strictly denies DASHBOARD_VIEW even if is_org_admin is True
        session = Session(
            user_id=str(uuid.uuid4()),
            username="cashier1",
            full_name="Cashier One",
            organization_id=org_id,
            organization_name="RBAC Pharmacy",
            branch_id=branch_id,
            branch_name="Main Branch",
            device_id=str(uuid.uuid4()),
            device_code="D01",
            permissions=role_perms,
            roles=[{"id": role_id, "name": "Cashier No Dashboard"}],
            is_offline=True,
            is_org_admin=True,
        )
        assert session.has_permission(PermissionCode.DASHBOARD_VIEW.value) is False
        assert session.has_permission("matrix.r0.view") is False
        assert session.has_permission(PermissionCode.SALES_SELL.value) is True

        # Test Cloud Branch Backup upload & New PC Restore roundtrip via mocked API client
        backup_service = BackupService(db_manager, app_config)
        uploaded_payloads = []

        class DummyCloudApiClient:
            def post(self, endpoint, data=None):
                uploaded_payloads.append((endpoint, data))
                return {
                    "id": "cloud-bck-1",
                    "branch_code": data["branch_code"],
                    "retained_count_for_branch": 1,
                    "max_backups_per_branch": 4,
                    "overrode_latest": False,
                }

            def get(self, endpoint, params=None):
                last_upload = uploaded_payloads[-1][1]
                return {
                    "backup": {
                        "id": "cloud-bck-1",
                        "organization_code": last_upload["org_code"],
                        "organization_name": last_upload["organization_name"],
                        "branch_code": last_upload["branch_code"],
                        "branch_name": last_upload["branch_name"],
                        "filename": last_upload["filename"],
                        "checksum_sha256": last_upload["checksum_sha256"],
                    },
                    "compressed_b64": last_upload["compressed_b64"],
                }

        dummy_api = DummyCloudApiClient()
        res = backup_service.upload_branch_backup_to_cloud(
            dummy_api,
            org_code="RBAC-01",
            org_name="RBAC Pharmacy",
            branch_id=branch_id,
            branch_code="BR-MAIN",
            branch_name="Main Branch",
            note="sync_backup",
        )
        assert res["branch_code"] == "BR-MAIN"
        assert res["max_backups_per_branch"] == 4
        assert len(uploaded_payloads) == 1

        # Simulate Laptop Spoiled / New PC by mutating local DB
        from desktop.app.db.models import RolePermission
        with db_manager.get_session() as db:
            db.query(RolePermission).filter_by(role_id=role_id).delete()
            db.query(Role).filter_by(id=role_id).delete()

        # Restore from Cloud Backup
        restored = backup_service.restore_branch_from_cloud(dummy_api, "cloud-bck-1")
        assert restored["branch_code"] == "BR-MAIN"

        # Verify role is restored on the New PC
        with db_manager.get_session() as db:
            restored_role = db.query(Role).filter_by(id=role_id).first()
            assert restored_role is not None
            assert restored_role.name == "Cashier No Dashboard"

