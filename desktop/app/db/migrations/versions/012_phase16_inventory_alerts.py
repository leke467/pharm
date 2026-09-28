from datetime import datetime, timezone
from desktop.app.db.models import Base, SchemaVersion


def upgrade(session):
    """
    Phase 16 migration:
    Creates InventoryAlert table for local anomaly & reconciliation mismatch tracking.
    """
    Base.metadata.create_all(session.get_bind())
    if not session.query(SchemaVersion).filter_by(version=12).first():
        session.add(
            SchemaVersion(
                version=12,
                applied_at=datetime.now(timezone.utc).isoformat(),
                description="Phase 16 — Hardening & Backup (InventoryAlert)",
            )
        )
        session.flush()
