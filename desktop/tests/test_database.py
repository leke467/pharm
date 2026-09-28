from desktop.app.db.models import Organization, SchemaVersion
from sqlalchemy import text

def test_database_initialization(db_manager):
    with db_manager.engine.connect() as conn:
        journal_mode = conn.execute(text("PRAGMA journal_mode")).scalar()
        assert journal_mode.lower() == "wal"
        
        fk = conn.execute(text("PRAGMA foreign_keys")).scalar()
        assert fk == 1
        
    with db_manager.get_session() as session:
        org = Organization(name="Test Org", code="TEST")
        session.add(org)
        session.commit()
        assert isinstance(org.id, str)
        assert len(org.id) == 36
        assert "T" in org.created_at # ISO 8601

