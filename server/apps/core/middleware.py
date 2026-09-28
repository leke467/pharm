from rest_framework_simplejwt.authentication import JWTAuthentication


class OrganizationScopeMiddleware:
    """
    Layer 3 of the Three-Layer Tenant Security Model.
    Injects `request.organization` and `request.organization_id` from the authenticated user.
    Also resolves JWT bearer tokens early if session auth has not populated `request.user`.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self.jwt_authenticator = JWTAuthentication()

    def __call__(self, request):
        user = getattr(request, 'user', None)

        if (not user or not user.is_authenticated) and 'HTTP_AUTHORIZATION' in request.META:
            try:
                auth_result = self.jwt_authenticator.authenticate(request)
                if auth_result is not None:
                    user, _ = auth_result
                    request.user = user
            except Exception:
                pass

        if user and user.is_authenticated and hasattr(user, 'organization_id') and user.organization_id:
            request.organization = user.organization
            request.organization_id = user.organization_id
        else:
            request.organization = None
            request.organization_id = None

        response = self.get_response(request)
        return response
