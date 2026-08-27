from __future__ import annotations

from collections.abc import Callable

from fastapi import HTTPException
from fastapi import Request

from app.models.core import User
from app.models.core import UserRole


def current_user(request: Request) -> User:
    user: User | None = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication is required")
    return user


def require_roles(*roles: UserRole) -> Callable[[Request], User]:
    def dependency(request: Request) -> User:
        user = current_user(request)
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="You do not have permission for this action")
        return user

    return dependency
