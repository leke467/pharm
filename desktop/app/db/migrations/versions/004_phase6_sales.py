from desktop.app.db.models import Base, SchemaVersion


def upgrade(session):
    """Phase 6 migration: ensures sales, sale_items, payments, receipts, and receipt_sequences tables exist."""
    Base.metadata.create_all(session.get_bind())
    existing = session.query(SchemaVersion).filter_by(version=4).first()
    if not existing:
        session.add(
            SchemaVersion(
                version=4,
                description="Phase 6 Sales, SaleItems, Payments, Receipts, and ReceiptSequences",
            )
        )
