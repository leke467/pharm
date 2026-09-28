from rest_framework.permissions import IsAuthenticated
from .permissions import IsOrganizationMember


class OrganizationQuerysetMixin:
    """
    Enforces Three-Layer Tenant Security on ViewSets:
    - Layer 1: Queryset scoping by organization_id
    - Layer 2: Object-level organization check via IsOrganizationMember
    - Layer 3: Works with OrganizationScopeMiddleware + DRF initial() hook
    - Soft-delete enforcement on destroy (is_active = False)
    """

    permission_classes = [IsAuthenticated, IsOrganizationMember]

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if request.user and request.user.is_authenticated and hasattr(request.user, 'organization_id'):
            request.organization = request.user.organization
            request.organization_id = request.user.organization_id

    def get_organization_id(self):
        org_id = getattr(self.request, 'organization_id', None)
        if not org_id and self.request.user and self.request.user.is_authenticated:
            org_id = getattr(self.request.user, 'organization_id', None)
        return org_id

    def get_queryset(self):
        qs = super().get_queryset()
        org_id = self.get_organization_id()
        if org_id:
            return qs.filter(organization_id=org_id)
        return qs.none()

    def perform_create(self, serializer):
        serializer.save(organization_id=self.get_organization_id())

    def perform_destroy(self, instance):
        if hasattr(instance, 'is_active'):
            instance.is_active = False
            instance.save(update_fields=['is_active', 'updated_at'])
        else:
            super().perform_destroy(instance)
