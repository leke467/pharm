from contextlib import contextmanager
from desktop.app.db.models import (
    AuditEvent,
    InventoryMovement,
    Sale,
    SaleItem,
    SaleReturn,
    SaleReturnItem,
)
from desktop.app.domain.exceptions import ValidationError


class BaseRepository:
    """
    Base repository encapsulating SQLite CRUD operations via SQLAlchemy.
    Enforces soft-delete (is_active=False) and AuditEvent / InventoryMovement / SaleItem immutability.
    Supports both standalone operations (auto-committing) and participating
    in an explicit service-layer transaction when `session` is passed.
    """

    def __init__(self, session_factory):
        self.session_factory = session_factory

    @contextmanager
    def _session_scope(self, session=None):
        if session is not None:
            yield session
        else:
            local_session = self.session_factory()
            try:
                yield local_session
                local_session.commit()
            except Exception:
                local_session.rollback()
                raise
            finally:
                local_session.close()

    def get_by_id(self, model_class, id, session=None):
        with self._session_scope(session) as db:
            return db.query(model_class).filter_by(id=id).first()

    def get_all(self, model_class, filters=None, limit=None, offset=None, session=None):
        with self._session_scope(session) as db:
            query = db.query(model_class)
            if filters:
                for k, v in filters.items():
                    query = query.filter(getattr(model_class, k) == v)
            if limit is not None:
                query = query.limit(limit)
            if offset is not None:
                query = query.offset(offset)
            return query.all()

    def create(self, instance, session=None):
        with self._session_scope(session) as db:
            db.add(instance)
            db.flush()
            return instance

    def update(self, instance, session=None, **kwargs):
        if isinstance(instance, (AuditEvent, InventoryMovement, SaleItem, SaleReturnItem)):
            raise ValidationError(
                f"{instance.__class__.__name__} records are immutable and cannot be updated."
            )
        with self._session_scope(session) as db:
            merged = db.merge(instance)
            for k, v in kwargs.items():
                setattr(merged, k, v)
            db.flush()
            return merged

    def soft_delete(self, instance, session=None):
        if isinstance(instance, (AuditEvent, InventoryMovement, SaleItem, Sale, SaleReturn, SaleReturnItem)):
            raise ValidationError(
                f"{instance.__class__.__name__} records are immutable and cannot be deleted."
            )
        with self._session_scope(session) as db:
            merged = db.merge(instance)
            merged.is_active = False
            db.flush()
            return merged

    def count(self, model_class, filters=None, session=None):
        with self._session_scope(session) as db:
            query = db.query(model_class)
            if filters:
                for k, v in filters.items():
                    query = query.filter(getattr(model_class, k) == v)
            return query.count()
