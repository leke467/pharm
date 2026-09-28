import httpx
from desktop.app.domain.exceptions import NetworkError, AuthenticationError, PermissionDeniedError, PharmacyError

class ApiClient:
    def __init__(self, config):
        self.config = config
        self.base_url = config.server_url.rstrip('/')
        self.timeout = config.http_timeout
        connect_timeout = min(2.0, float(self.timeout)) if self.timeout else 2.0
        self.client = httpx.Client(
            timeout=httpx.Timeout(timeout=float(self.timeout or 10.0), connect=connect_timeout)
        )
        self.access_token = None
        self.refresh_token_value = None

    def close(self):
        try:
            self.client.close()
        except Exception:
            pass

    def set_auth_token(self, access_token, refresh_token=None):
        self.access_token = access_token
        self.refresh_token_value = refresh_token
        if access_token:
            self.client.headers.update({"Authorization": f"Bearer {access_token}"})
        else:
            self.client.headers.pop("Authorization", None)

    def _parse_error_message(self, response) -> str:
        """Extract a clean, human-readable error message from an HTTP response, avoiding raw HTML."""
        try:
            data = response.json()
            if isinstance(data, dict):
                # Standard error format {"error": {"message": "...", "code": "..."}}
                err = data.get("error")
                if isinstance(err, dict) and "message" in err:
                    return str(err["message"])
                elif isinstance(err, str):
                    return err

                # DRF detail format {"detail": "..."}
                if "detail" in data:
                    return str(data["detail"])

                # Simple {"message": "..."}
                if "message" in data:
                    return str(data["message"])

                # Field validation errors {"username": ["This field is required."], ...}
                if data:
                    first_key = next(iter(data))
                    val = data[first_key]
                    if isinstance(val, list) and val:
                        return f"{first_key.replace('_', ' ').capitalize()}: {val[0]}"
                    elif isinstance(val, str):
                        return f"{first_key.replace('_', ' ').capitalize()}: {val}"
        except Exception:
            pass

        # Non-JSON responses (e.g. Django debug 404 / 500 HTML pages)
        status = response.status_code
        if status == 404:
            return f"Service endpoint not found (404) at {response.url.path}. Please verify the pharmacy server address."
        elif status == 500:
            return "Internal Server Error (500). Please check the backend server logs."
        elif status in (502, 503, 504):
            return f"Server is temporarily unavailable ({status}). Please verify your connection."

        text = response.text.strip()
        if text.startswith("<") or "<html" in text.lower():
            reason = getattr(response, "reason_phrase", "") or "Error"
            return f"Server returned error HTTP {status} ({reason})."
        
        return text[:200] if text else f"Server error HTTP {status}."

    def _handle_response(self, response):
        if response.status_code == 401:
            msg = self._parse_error_message(response)
            raise AuthenticationError(msg or "Authentication failed. Invalid username, password, or organization code.")
        elif response.status_code == 403:
            msg = self._parse_error_message(response)
            raise PermissionDeniedError(msg or "Permission denied.")
        elif response.status_code >= 400:
            msg = self._parse_error_message(response)
            raise PharmacyError(msg)
        return response.json()

    def _handle_request(self, method, *args, **kwargs):
        try:
            response = getattr(self.client, method)(*args, **kwargs)
            return self._handle_response(response)
        except httpx.ConnectError:
            raise NetworkError(f"Cannot connect to Pharmacy Server at {self.base_url}. Please ensure the server is running.")
        except httpx.TimeoutException:
            raise NetworkError(f"Request to Pharmacy Server timed out after {self.timeout}s. Please check your network connection.")
        except httpx.HTTPError as e:
            raise NetworkError(f"Network error: {str(e)}")

    def login(self, username: str, password: str, org_code: str,
              branch_id: str | None = None, device_id: str | None = None) -> dict:
        """
        Authenticate against the central server.

        Args:
            username: User's username.
            password: User's plaintext password (transmitted over HTTPS, never stored).
            org_code: Organization code for multi-tenant auth.
            branch_id: Optional branch UUID to set as active branch.
            device_id: Optional device UUID for device registration.

        Returns:
            Dict with access_token, refresh_token, and user profile data.
        """
        data = {
            "username": username,
            "password": password,
            "org_code": org_code,
            "branch_id": branch_id,
            "device_id": device_id,
        }
        res = self._handle_request("post", f"{self.base_url}/api/v1/auth/login/", json=data)
        self.set_auth_token(res.get('access_token'), res.get('refresh_token'))
        return res

    def refresh_token(self) -> dict:
        """Refresh the JWT access token using the stored refresh token."""
        if not self.refresh_token_value:
            raise AuthenticationError("No refresh token available.")
        res = self._handle_request(
            "post",
            f"{self.base_url}/api/v1/auth/refresh/",
            json={"refresh": self.refresh_token_value},
        )
        self.set_auth_token(res.get('access'), res.get('refresh', self.refresh_token_value))
        return res

    def get(self, endpoint: str, params: dict | None = None) -> dict:
        """Make an authenticated GET request to the API."""
        url = f"{self.base_url}/api/v1/{endpoint.lstrip('/')}"
        return self._handle_request("get", url, params=params)

    def post(self, endpoint: str, data: dict | None = None) -> dict:
        """Make an authenticated POST request to the API."""
        url = f"{self.base_url}/api/v1/{endpoint.lstrip('/')}"
        return self._handle_request("post", url, json=data)

    def patch(self, endpoint: str, data: dict | None = None) -> dict:
        """Make an authenticated PATCH request to the API."""
        url = f"{self.base_url}/api/v1/{endpoint.lstrip('/')}"
        return self._handle_request("patch", url, json=data)

    def health_check(self) -> bool:
        """Check if the central server is reachable."""
        try:
            response = self.client.get(f"{self.base_url}/api/v1/health/", timeout=1.5)
            return response.status_code == 200
        except Exception:
            return False

    def is_server_available(self):
        return self.health_check()

