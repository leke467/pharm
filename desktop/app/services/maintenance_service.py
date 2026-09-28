from sqlalchemy import text
from desktop.app.services.base_service import BaseService


class MaintenanceService(BaseService):
    """
    SQLite Database Maintenance Service (Architecture Plan §16).
    Performs routine VACUUM, PRAGMA optimize, WAL truncation, and integrity checks.
    """

    def optimize_database(self) -> dict:
        """Runs PRAGMA optimize, checkpoints WAL log, and runs VACUUM."""
        with self.db_manager.engine.connect() as conn:
            # WAL checkpoint truncate to keep file sizes tidy
            conn.execute(text("PRAGMA wal_checkpoint(TRUNCATE)"))
            # SQLite query optimizer statistics update
            conn.execute(text("PRAGMA optimize"))

        # VACUUM cannot run within a multi-statement transaction, run on raw connection
        raw_conn = self.db_manager.engine.raw_connection()
        try:
            cur = raw_conn.cursor()
            cur.execute("VACUUM")
            cur.close()
        finally:
            raw_conn.close()

        return {"status": "ok", "optimized": True, "vacuumed": True}

    def check_integrity(self) -> tuple[bool, str]:
        """Runs PRAGMA integrity_check and returns (is_healthy, message)."""
        with self.db_manager.engine.connect() as conn:
            res = conn.execute(text("PRAGMA integrity_check")).fetchone()
            if res and res[0] == "ok":
                return True, "Database integrity check passed (ok)."
            else:
                return False, f"Integrity check failed: {res[0] if res else 'Unknown error'}"
