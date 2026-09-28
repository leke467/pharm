import pytest
from rest_framework.test import APIClient
from django.urls import reverse
from apps.branches.models import Branch
from apps.users.models import User

@pytest.mark.django_db
class TestTenantIsolation:
    def test_cannot_see_other_org_branches(self, authenticated_client, test_organization, other_organization):
        Branch.objects.create(organization=other_organization, name='Other Branch', code='OTH')
        response = authenticated_client.get(reverse('branch-list'))
        assert response.status_code == 200
        assert len(response.data['results']) == 0

    def test_cannot_see_other_org_users(self, authenticated_client, test_organization, other_organization):
        User.objects.create_user(username='otheruser', organization_id=other_organization.id, password='123')
        response = authenticated_client.get(reverse('user-list'))
        assert response.status_code == 200
        assert len(response.data['results']) == 1  # only test_user

    def test_cannot_retrieve_other_org_branch(self, authenticated_client, other_organization):
        other_branch = Branch.objects.create(organization=other_organization, name='Other', code='OTH')
        response = authenticated_client.get(reverse('branch-detail', kwargs={'pk': other_branch.pk}))
        assert response.status_code == 404
