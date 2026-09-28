from datetime import datetime, timezone
from desktop.app.db.models import Base, SchemaVersion


def upgrade(session):
    """
    Phase 15 migration:
    Creates LicenseState table for subscription & licensing cache.
    """
    Base.metadata.create_all(session.get_bind())
    if not session.query(SchemaVersion).filter_by(version=11).first():
        session.add(
            SchemaVersion(
                version=11,
                applied_at=datetime.now(timezone.utc).isoformat(),
                description="Phase 15 — Subscription & Licensing (LicenseState)",
            )
        )
        session.flush()
