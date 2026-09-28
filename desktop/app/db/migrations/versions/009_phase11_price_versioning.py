from datetime import datetime, timezone
from desktop.app.db.models import Base, SchemaVersion


def upgrade(session):
    """
    Phase 11 migration:
    Creates PriceHistory table.
    """
    Base.metadata.create_all(session.get_bind())
    if not session.query(SchemaVersion).filter_by(version=9).first():
        session.add(
            SchemaVersion(
                version=9,
                applied_at=datetime.now(timezone.utc).isoformat(),
                description="Phase 11 — Price Versioning & Sync (PriceHistory)",
            )
        )
        session.flush()
