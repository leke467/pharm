from datetime import datetime, timezone
from desktop.app.db.models import Base, SchemaVersion


def upgrade(session):
    """
    Phase 9 migration:
    Creates StockCount and StockCountItem tables.
    """
    Base.metadata.create_all(session.get_bind())
    if not session.query(SchemaVersion).filter_by(version=7).first():
        session.add(
            SchemaVersion(
                version=7,
                applied_at=datetime.now(timezone.utc).isoformat(),
                description="Phase 9 — Stock Counts & Approval (StockCount, StockCountItem)",
            )
        )
        session.flush()
