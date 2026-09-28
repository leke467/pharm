from datetime import datetime, timezone
from desktop.app.db.models import Base, SchemaVersion


def upgrade(session):
    """
    Phase 8 migration:
    Creates Purchase, PurchaseItem, and PurchasePayment tables.
    """
    Base.metadata.create_all(session.get_bind())
    if not session.query(SchemaVersion).filter_by(version=6).first():
        session.add(
            SchemaVersion(
                version=6,
                applied_at=datetime.now(timezone.utc).isoformat(),
                description="Phase 8 — Purchasing & Inventory Receiving (Purchase, PurchaseItem, PurchasePayment)",
            )
        )
        session.flush()
