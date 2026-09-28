from sqlalchemy import text
from desktop.app.db.models import Base, SchemaVersion
from desktop.app.db.database import FTS5_DDL_STATEMENTS


def upgrade(session):
    """Phase 3 migration: ensures product catalog tables and FTS5 index exist."""
    Base.metadata.create_all(session.get_bind())
    for stmt in FTS5_DDL_STATEMENTS:
        session.execute(text(stmt))
    existing = session.query(SchemaVersion).filter_by(version=2).first()
    if not existing:
        session.add(
            SchemaVersion(
                version=2,
                description="Phase 3 Product Catalog, Categories, Suppliers & FTS5",
            )
        )
