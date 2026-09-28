from desktop.app.db.models import Base, SchemaVersion


def upgrade(session):
    """Phase 4 migration: ensures batches, inventory, storage locations, movements, and prices tables exist."""
    Base.metadata.create_all(session.get_bind())
    existing = session.query(SchemaVersion).filter_by(version=3).first()
    if not existing:
        session.add(
            SchemaVersion(
                version=3,
                description="Phase 4 Batches, Inventory, Storage Locations & Basic Pricing",
            )
        )
