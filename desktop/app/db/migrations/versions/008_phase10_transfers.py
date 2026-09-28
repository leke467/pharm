from datetime import datetime, timezone
from desktop.app.db.models import Base, SchemaVersion


def upgrade(session):
    """
    Phase 10 migration:
    Creates StockTransfer and StockTransferItem tables.
    """
    Base.metadata.create_all(session.get_bind())
    if not session.query(SchemaVersion).filter_by(version=8).first():
        session.add(
            SchemaVersion(
                version=8,
                applied_at=datetime.now(timezone.utc).isoformat(),
                description="Phase 10 — Stock Transfers (StockTransfer, StockTransferItem)",
            )
        )
        session.flush()
