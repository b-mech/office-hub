from __future__ import annotations

import logging
from datetime import datetime
from datetime import timezone
from typing import Literal

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from pydantic import BaseModel
from pydantic import EmailStr
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.authorization import require_roles
from app.core.database import get_db
from app.models.core import User
from app.models.core import UserRole
from app.services.user_invites import send_user_invite


router = APIRouter(
    prefix="/users",
    tags=["users"],
    dependencies=[Depends(require_roles(UserRole.ADMIN))],
)
logger = logging.getLogger(__name__)

PermissionLevel = Literal["none", "viewer", "editor"]


class UserInvite(BaseModel):
    first_name: str = Field(min_length=1)
    last_name: str = Field(min_length=1)
    email: EmailStr
    role: Literal["admin", "staff", "readonly"]
    permissions: dict[str, PermissionLevel]


class UserInviteResponse(BaseModel):
    id: str
    email: str
    status: str = "invited"


class UserOut(UserInviteResponse):
    first_name: str
    last_name: str
    role: Literal["admin", "staff", "readonly"]
    permissions: dict[str, PermissionLevel]


@router.post("/invite", response_model=UserInviteResponse)
async def invite_user(
    invite: UserInvite,
    db: AsyncSession = Depends(get_db),
) -> UserInviteResponse:
    normalized_email = str(invite.email).strip().casefold()
    if await db.scalar(select(User.id).where(User.email == normalized_email)) is not None:
        raise HTTPException(status_code=409, detail="Email has already been invited")

    full_name = " ".join((invite.first_name.strip(), invite.last_name.strip()))
    user = User(
        org_id=settings.default_org_id,
        email=normalized_email,
        full_name=full_name,
        role=UserRole(invite.role),
        permissions=invite.permissions,
        is_active=False,
        invited_at=datetime.now(timezone.utc),
    )
    db.add(user)
    try:
        await db.flush()
        await send_user_invite(recipient=normalized_email, full_name=full_name)
        user.invite_sent_at = datetime.now(timezone.utc)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Email has already been invited") from exc
    except Exception as exc:
        await db.rollback()
        logger.exception("User invite email failed for %s", normalized_email)
        raise HTTPException(status_code=502, detail=f"Invite email could not be sent: {exc}") from exc

    return UserInviteResponse(id=str(user.id), email=user.email)


@router.get("", response_model=list[UserOut])
async def list_users(db: AsyncSession = Depends(get_db)) -> list[UserOut]:
    users = list((await db.scalars(select(User).order_by(User.created_at))).all())
    return [_user_out(user) for user in users]


def _user_out(user: User) -> UserOut:
    first_name, _, last_name = user.full_name.partition(" ")
    return UserOut(
        id=str(user.id),
        email=user.email,
        status="active" if user.is_active else "invited",
        first_name=first_name,
        last_name=last_name,
        role=user.role.value,
        permissions=user.permissions,
    )
