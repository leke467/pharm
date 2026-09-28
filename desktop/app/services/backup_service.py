import base64
import hashlib
import os
import shutil
import sqlite3
import zlib
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy import text
from desktop.app.domain.exceptions import PharmacyError


class BackupService:
    """
    Automated and manual SQLite backup, retention pruning, and cloud branch recovery service.
    Maintains up to 4 backups per branch in FILO/LIFO manner (newest first, max 4 retained)
    both locally and on the Django cloud server so a spoiled laptop can be restored on a new PC.
    """

    MAX_BACKUPS_PER_BRANCH = 4

    def __init__(self, db_manager, config):
        self.db_manager = db_manager
        self.config = config
        self.backup_dir = Path(config.backup_dir)
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self._last_uploaded_checksum: dict[str, str] = {}

    def create_backup(self, note: str = "", branch_code: str = "") -> dict:
        """
        Creates a consistent, zero-corruption SQLite backup using the SQLite Online Backup API.
        Applies FILO retention policy keeping up to 4 backups per branch.
        """
        db_path = Path(self.config.db_path)
        if not db_path.exists():
            raise PharmacyError("Database file does not exist to back up.")

        # Checkpoint WAL log first
        try:
            with self.db_manager.engine.connect() as conn:
                conn.execute(text("PRAGMA wal_checkpoint(TRUNCATE)"))
        except Exception:
            pass

        now = datetime.now(timezone.utc)
        timestamp = now.strftime("%Y%m%d_%H%M%S")
        clean_branch = branch_code.strip().upper() if branch_code else ""
        branch_tag = f"_{clean_branch}" if clean_branch else ""
        suffix = f"_{note}" if note else ""
        filename = f"pharmacy_backup{branch_tag}_{timestamp}{suffix}.db"
        dest_path = self.backup_dir / filename

        src = sqlite3.connect(str(db_path))
        dst = sqlite3.connect(str(dest_path))
        try:
            with dst:
                src.backup(dst)
        finally:
            dst.close()
            src.close()

        raw_bytes = dest_path.read_bytes()
        checksum = hashlib.sha256(raw_bytes).hexdigest()

        # Enforce FILO retention policy: keep at most 4 backups
        self._prune_backups(max_retain=self.MAX_BACKUPS_PER_BRANCH)

        return {
            "path": str(dest_path),
            "filename": filename,
            "size_bytes": len(raw_bytes),
            "checksum_sha256": checksum,
            "created_at": now.isoformat(),
        }

    def upload_branch_backup_to_cloud(
        self,
        api_client,
        org_code: str = "MEDCARE",
        org_name: str = "MedCare Pharmacy",
        branch_id: str = "",
        branch_code: str = "HQ",
        branch_name: str = "Main Branch",
        device_code: str = "POS01",
        note: str = "Auto-Sync Cloud Backup",
        force_new_slot: bool = False,
    ) -> dict | None:
        """
        Creates a consistent SQLite snapshot of the current branch and uploads it to the
        Django server (`POST /api/v1/sync/backups/upload/`).
        - Server keeps at most 4 backups per branch in FILO/LIFO order (newest first).
        - During background syncs (`force_new_slot=False`), skips re-uploading if the
          SQLite database SHA-256 checksum has not changed since the last upload in this session.
        """
        if not api_client:
            return None

        clean_branch = (branch_code or "HQ").strip().upper()
        clean_org = (org_code or "MEDCARE").strip().upper()

        local_info = self.create_backup(note="cloud_sync", branch_code=clean_branch)
        bck_path = Path(local_info["path"])
        checksum = local_info["checksum_sha256"]

        # Skip redundant network transfer on background ticks if nothing changed in SQLite
        if not force_new_slot and self._last_uploaded_checksum.get(clean_branch) == checksum:
            return None

        raw_bytes = bck_path.read_bytes()
        compressed_bytes = zlib.compress(raw_bytes, level=6)
        compressed_b64 = base64.b64encode(compressed_bytes).decode("ascii")

        resp = api_client.post(
            "sync/backups/upload/",
            data={
                "org_code": clean_org,
                "organization_name": org_name,
                "branch_id": str(branch_id or ""),
                "branch_code": clean_branch,
                "branch_name": branch_name or clean_branch,
                "device_code": device_code or "POS01",
                "filename": local_info["filename"],
                "size_bytes": local_info["size_bytes"],
                "checksum_sha256": checksum,
                "compressed_b64": compressed_b64,
                "note": note,
                "force_new_slot": force_new_slot,
            },
        )
        self._last_uploaded_checksum[clean_branch] = checksum
        return resp

    def list_cloud_branch_backups(
        self,
        api_client,
        org_code: str = "MEDCARE",
        branch_code: str = "",
    ) -> dict:
        """
        Fetches the up to 4 cloud backups per branch from the Django server in FILO/LIFO order (newest first).
        """
        if not api_client:
            return {"branches": [], "backups": [], "max_backups_per_branch": self.MAX_BACKUPS_PER_BRANCH}
        params = {"org_code": (org_code or "MEDCARE").strip().upper()}
        if branch_code:
            params["branch_code"] = branch_code.strip().upper()
        return api_client.get("sync/backups/", params=params)

    def restore_branch_from_cloud(
        self,
        api_client,
        backup_id: str,
    ) -> dict:
        """
        Downloads a branch backup from the Django server (`GET /api/v1/sync/backups/<id>/download/`),
        decompresses and verifies its SQLite integrity, and restores the local database so a new PC
        can immediately continue where the old PC left off.
        """
        if not api_client:
            raise PharmacyError("Cloud API client is not configured.")

        resp = api_client.get(f"sync/backups/{backup_id}/download/")
        if not isinstance(resp, dict) or not resp.get("compressed_b64"):
            raise PharmacyError("Failed to download branch backup payload from server.")

        bck_meta = resp.get("backup") or {}
        compressed_bytes = base64.b64decode(resp["compressed_b64"])
        try:
            sqlite_bytes = zlib.decompress(compressed_bytes)
        except Exception:
            sqlite_bytes = compressed_bytes

        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        bcode = bck_meta.get("branch_code", "HQ")
        staging_file = self.backup_dir / f"cloud_restore_{bcode}_{ts}.db"
        staging_file.write_bytes(sqlite_bytes)

        # Perform full verified restore into active pharmacy.db
        self.restore_backup(staging_file)

        # Sync QSettings with the restored organization and branch so a brand-new PC is ready to sign in
        try:
            from PySide6.QtCore import QSettings
            settings = QSettings("PharmaCare", "PharmaCareEnterprise")
            if bck_meta.get("organization_code"):
                settings.setValue("saved_org_code", bck_meta["organization_code"])
            if bck_meta.get("organization_name"):
                settings.setValue("saved_pharmacy_name", bck_meta["organization_name"])
            if bck_meta.get("branch_code"):
                settings.setValue("saved_branch_code", bck_meta["branch_code"])
        except Exception:
            pass

        return bck_meta

    def list_backups(self) -> list[dict]:
        """Returns up to 4 local backups ordered newest first (FILO/LIFO)."""
        if not self.backup_dir.exists():
            return []

        self._prune_backups(max_retain=self.MAX_BACKUPS_PER_BRANCH)

        backups = []
        for f in self.backup_dir.glob("pharmacy_backup*.db"):
            if "prerestore" in f.name:
                continue
            stat = f.stat()
            backups.append({
                "path": str(f),
                "filename": f.name,
                "size_bytes": stat.st_size,
                "created_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
            })

        backups.sort(key=lambda x: x["created_at"], reverse=True)
        return backups[: self.MAX_BACKUPS_PER_BRANCH]

    def restore_backup(self, backup_path: str | Path) -> bool:
        """
        Restores SQLite database from a selected backup file.
        1. Validates source backup integrity.
        2. Creates a pre-restore safety copy of the current active database.
        3. Disposes active connection pool.
        4. Overwrites/restores database via SQLite backup API.
        5. Verifies integrity check on restored database.
        """
        bck = Path(backup_path)
        if not bck.exists():
            raise PharmacyError(f"Backup file not found at {backup_path}")

        # 1. Validate backup file integrity
        try:
            test_conn = sqlite3.connect(str(bck))
            cursor = test_conn.cursor()
            cursor.execute("PRAGMA quick_check")
            result = cursor.fetchone()
            test_conn.close()
            if not result or result[0] != "ok":
                raise PharmacyError(f"Corrupt backup file: {result}")
        except Exception as e:
            raise PharmacyError(f"Invalid backup file: {e}")

        # 2. Safety snapshot of current database
        db_path = Path(self.config.db_path)
        if db_path.exists():
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            pre_restore_file = self.backup_dir / f"pharmacy_prerestore_safety_{ts}.db"
            shutil.copy2(db_path, pre_restore_file)

        # 3. Dispose engine pool
        self.db_manager.close()

        # 4. Perform restore
        src = sqlite3.connect(str(bck))
        dst = sqlite3.connect(str(db_path))
        try:
            with dst:
                src.backup(dst)
        finally:
            dst.close()
            src.close()

        # 5. Check integrity on restored db
        check_conn = sqlite3.connect(str(db_path))
        try:
            cur = check_conn.cursor()
            cur.execute("PRAGMA integrity_check")
            res = cur.fetchone()
            if not res or res[0] != "ok":
                raise PharmacyError(f"Restored database failed integrity check: {res}")
        finally:
            check_conn.close()

        return True

    def _prune_backups(self, max_retain: int = 4):
        all_backups = list(self.backup_dir.glob("pharmacy_backup*.db"))
        # Exclude pre-restore safety backups from count
        daily_backups = [f for f in all_backups if "prerestore" not in f.name]
        daily_backups.sort(key=lambda f: f.stat().st_mtime, reverse=True)

        if len(daily_backups) > max_retain:
            for old_file in daily_backups[max_retain:]:
                try:
                    old_file.unlink()
                except OSError:
                    pass

