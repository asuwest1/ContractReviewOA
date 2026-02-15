import os
from dataclasses import dataclass


@dataclass
class Identity:
    user: str
    roles: set[str]


class AuthResolver:
    def __init__(self):
        self.allow_dev_headers = os.environ.get("ALLOW_DEV_HEADERS", "true").lower() == "true"
        self.default_roles = {r.strip() for r in os.environ.get("DEFAULT_ROLES", "").split(",") if r.strip()}

    def resolve(self, headers) -> Identity:
        # IIS/Windows Integrated Auth surfaces these in CGI/server vars.
        user = (
            os.environ.get("REMOTE_USER")
            or os.environ.get("LOGON_USER")
            or os.environ.get("AUTH_USER")
            or ""
        )
        roles = set(self.default_roles)

        env_groups = os.environ.get("REMOTE_GROUPS", "")
        if env_groups:
            roles.update({r.strip() for r in env_groups.replace(";", ",").split(",") if r.strip()})

        if not user and self.allow_dev_headers:
            user = headers.get("X-Remote-User", "")
        if self.allow_dev_headers:
            roles.update({r.strip() for r in headers.get("X-User-Roles", "").split(",") if r.strip()})

        if not user:
            user = "anonymous"

        return Identity(user=user, roles=roles)
