from contextlib import contextmanager
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import scoped_session, sessionmaker
from .models import Base, SchemaVersion


FTS5_DDL_STATEMENTS = [
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS products_fts USING fts5(
        product_id UNINDEXED,
        organization_id UNINDEXED,
        name,
        generic_name,
        brand_name,
        sku,
        barcode
    );
    """,
    """
    CREATE TRIGGER IF NOT EXISTS trg_products_fts_insert AFTER INSERT ON products BEGIN
        INSERT INTO products_fts(product_id, organization_id, name, generic_name, brand_name, sku, barcode)
        VALUES (new.id, new.organization_id, coalesce(new.name, ''), coalesce(new.generic_name, ''), coalesce(new.brand_name, ''), coalesce(new.sku, ''), coalesce(new.barcode, ''));
    END;
    """,
    """
    CREATE TRIGGER IF NOT EXISTS trg_products_fts_update AFTER UPDATE ON products BEGIN
        DELETE FROM products_fts WHERE product_id = old.id;
        INSERT INTO products_fts(product_id, organization_id, name, generic_name, brand_name, sku, barcode)
        VALUES (new.id, new.organization_id, coalesce(new.name, ''), coalesce(new.generic_name, ''), coalesce(new.brand_name, ''), coalesce(new.sku, ''), coalesce(new.barcode, ''));
    END;
    """,
    """
    CREATE TRIGGER IF NOT EXISTS trg_products_fts_delete AFTER DELETE ON products BEGIN
        DELETE FROM products_fts WHERE product_id = old.id;
    END;
    """,
]


class DatabaseManager:
    """
    Manages the local SQLite database with WAL mode, foreign key enforcement,
    FTS5 full-text product search index, and automatic initial schema registration.
    """

    def __init__(self, config):
        self.config = config
        db_url = f"sqlite:///{self.config.db_path}"
        self.engine = create_engine(db_url, connect_args={"check_same_thread": False})

        def set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.execute("PRAGMA optimize")
            cursor.close()

        event.listen(self.engine, 'connect', set_sqlite_pragma)

        self.session_factory = scoped_session(
            sessionmaker(bind=self.engine, expire_on_commit=False)
        )
        Base.metadata.create_all(self.engine)
        self._ensure_fts_and_schema_version()

    def _ensure_fts_and_schema_version(self):
        with self.engine.begin() as conn:
            for stmt in FTS5_DDL_STATEMENTS:
                conn.execute(text(stmt))

        with self.get_session() as session:
            existing = session.query(SchemaVersion).filter_by(version=1).first()
            if not existing:
                session.add(SchemaVersion(version=1, description="Initial schema"))

    @contextmanager
    def get_session(self):
        session = self.session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def close(self):
        self.session_factory.remove()
        self.engine.dispose()
