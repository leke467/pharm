import pytest
from django.urls import reverse
from rest_framework.test import APIClient

@pytest.mark.django_db
class TestAuth:
    def test_login_success(self, test_user, test_organization):
        client = APIClient()
        response = client.post(reverse('login'), {
            'username': 'testuser',
            'password': 'password123',
            'org_code': test_organization.code
        })
        assert response.status_code == 200
        assert 'access_token' in response.data
        assert 'refresh_token' in response.data
        assert 'user' in response.data
        assert 'password' not in response.data['user']
        assert 'password_hash' not in response.data['user']

    def test_login_invalid_creds(self, test_user, test_organization):
        client = APIClient()
        response = client.post(reverse('login'), {
            'username': 'testuser',
            'password': 'wrongpassword',
            'org_code': test_organization.code
        })
        assert response.status_code == 401

    def test_login_wrong_org(self, test_user, other_organization):
        client = APIClient()
        response = client.post(reverse('login'), {
            'username': 'testuser',
            'password': 'password123',
            'org_code': other_organization.code
        })
        assert response.status_code == 401

    def test_auth_me(self, authenticated_client):
        response = authenticated_client.get(reverse('current_user'))
        assert response.status_code == 200
        assert response.data['username'] == 'testuser'

    def test_unauthenticated_request(self):
        client = APIClient()
        response = client.get(reverse('current_user'))
        assert response.status_code == 401
