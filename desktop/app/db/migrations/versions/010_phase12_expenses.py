from datetime import datetime, timezone
from desktop.app.db.models import Base, SchemaVersion


def upgrade(session):
    """
    Phase 12 migration:
    Creates ExpenseCategory and Expense tables.
    """
    Base.metadata.create_all(session.get_bind())
    if not session.query(SchemaVersion).filter_by(version=10).first():
        session.add(
            SchemaVersion(
                version=10,
                applied_at=datetime.now(timezone.utc).isoformat(),
                description="Phase 12 — Expenses (ExpenseCategory, Expense)",
            )
        )
        session.flush()
