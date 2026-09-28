from desktop.app.db.models import Base
from desktop.app.db.models import SchemaVersion

def upgrade(session):
    # Tables are created by Base.metadata.create_all in DatabaseManager
    # This migration explicitly logs the version 1
    existing = session.query(SchemaVersion).filter_by(version=1).first()
    if not existing:
        sv = SchemaVersion(version=1, description='Initial schema')
        session.add(sv)

