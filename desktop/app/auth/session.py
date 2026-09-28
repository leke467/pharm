from dataclasses import dataclass, field
from typing import List, Dict, Optional


@dataclass
class Session:
    user_id: str
    username: str
    full_name: str
    organization_id: str
    organization_name: str
    branch_id: str
    branch_name: str
    device_id: str
    device_code: str
    permissions: List[str] = field(default_factory=list)
    roles: List[Dict] = field(default_factory=list)
    is_offline: bool = False
    is_org_admin: bool = False
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    logged_in_at: Optional[str] = None
    session_expires_at: Optional[str] = None

    def has_permission(self, permission_code: str) -> bool:
        """Check whether the active session grants the given permission code."""
        if self.username and self.username.strip().lower() == "admin":
            return True
        if "matrix.configured" in (self.permissions or []):
            return permission_code in self.permissions
        if self.is_org_admin:
            return True
        return permission_code in (self.permissions or [])

