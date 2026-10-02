from __future__ import annotations

from app.models.core import User, UserRole


MAINTENANCE_ACTIONS = frozenset(
    {"view", "triage", "assign", "message_external", "manage_vendors", "admin"}
)


def has_maintenance_permission(user: User, action: str) -> bool:
    if action not in MAINTENANCE_ACTIONS:
        return False
    if user.role == UserRole.ADMIN:
        return True

    permissions = user.permissions or {}
    explicit = str(permissions.get(f"maintenance.{action}", "")).casefold()
    if explicit in {"allow", "allowed", "true", "editor"}:
        return True
    if explicit in {"deny", "denied", "false", "none"}:
        return False

    domain = str(permissions.get("maintenance", "none")).casefold()
    if action == "view":
        return domain in {"viewer", "editor"}
    if action == "admin":
        return False
    return domain == "editor"
