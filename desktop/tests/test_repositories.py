from desktop.app.repositories.base_repository import BaseRepository
from desktop.app.db.models import Organization, Branch

def test_base_repository(db_manager):
    repo = BaseRepository(db_manager.session_factory)
    
    org = Organization(name="Org", code="O1")
    created = repo.create(org)
    assert created.id
    
    fetched = repo.get_by_id(Organization, created.id)
    assert fetched.name == "Org"
    
    deleted = repo.soft_delete(fetched)
    assert not deleted.is_active
    
    count = repo.count(Organization, {"name": "Org"})
    assert count == 1

