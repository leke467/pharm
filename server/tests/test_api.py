import pytest
from django.urls import reverse

@pytest.mark.django_db
class TestAPI:
    def test_health_endpoint(self, authenticated_client):
        response = authenticated_client.get(reverse('health'))
        assert response.status_code == 200
        assert response.data['status'] == 'ok'

    def test_branch_crud(self, authenticated_client, test_organization):
        response = authenticated_client.post(reverse('branch-list'), {
            'name': 'New Branch',
            'code': 'NEWB',
        })
        assert response.status_code == 201
        assert response.data['name'] == 'New Branch'
        assert response.data['organization'] == str(test_organization.id)
