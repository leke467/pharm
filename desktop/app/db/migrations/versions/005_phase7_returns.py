from datetime import datetime, timezone
from desktop.app.db.models import Base, SchemaVersion


def upgrade(session):
    """
    Phase 7 migration:
    Creates SaleReturn and SaleReturnItem tables.
    """
    Base.metadata.create_all(session.get_bind())
    if not session.query(SchemaVersion).filter_by(version=5).first():
        session.add(
            SchemaVersion(
                version=5,
                applied_at=datetime.now(timezone.utc).isoformat(),
                description="Phase 7 — Sale Returns & Voids (SaleReturn, SaleReturnItem)",
            )
        )
        session.flush()
