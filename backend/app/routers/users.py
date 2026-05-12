from __future__ import annotations

from typing import Literal
from uuid import uuid4

from fastapi import APIRouter
from fastapi import HTTPException
from pydantic import BaseModel
from pydantic import EmailStr
from pydantic import Field


router = APIRouter(prefix="/users", tags=["users"])

PermissionLevel = Literal["none", "viewer", "editor"]


class UserInvite(BaseModel):
    first_name: str = Field(min_length=1)
    last_name: str = Field(min_length=1)
    email: EmailStr
    role: Literal["admin", "member"]
    permissions: dict[str, PermissionLevel]


class UserInviteResponse(BaseModel):
    id: str
    email: str
    status: str = "invited"


class UserOut(UserInviteResponse):
    first_name: str
    last_name: str
    role: Literal["admin", "member"]
    permissions: dict[str, PermissionLevel]


_users: dict[str, UserOut] = {}


@router.post("/invite", response_model=UserInviteResponse)
async def invite_user(invite: UserInvite) -> UserInviteResponse:
    normalized_email = invite.email.lower()
    if any(user.email.lower() == normalized_email for user in _users.values()):
        raise HTTPException(status_code=400, detail="Email has already been invited")

    user_id = str(uuid4())
    _users[user_id] = UserOut(
        id=user_id,
        email=normalized_email,
        first_name=invite.first_name.strip(),
        last_name=invite.last_name.strip(),
        role=invite.role,
        permissions=invite.permissions,
    )
    # TODO: wire to SendGrid/SES for real invite emails.
    return UserInviteResponse(id=user_id, email=normalized_email)


@router.get("", response_model=list[UserOut])
async def list_users() -> list[UserOut]:
    return list(_users.values())
