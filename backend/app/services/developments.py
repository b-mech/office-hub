from __future__ import annotations

import re
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.core import Development
from app.models.core import DevelopmentType


_WHITESPACE_RE = re.compile(r"\s+")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
_RM_PREFIX_RE = re.compile(r"^(?:the\s+)?(?:rural\s+municipality|r\.?m\.?)\s+of\s+", re.IGNORECASE)


def normalize_development_name(value: str) -> str:
    return _WHITESPACE_RE.sub(" ", value.strip()).casefold()


def municipality_key(value: str) -> str:
    without_prefix = _RM_PREFIX_RE.sub("", value.strip())
    return _NON_ALNUM_RE.sub(" ", without_prefix.casefold()).strip()


def municipality_display_name(value: str) -> str:
    cleaned = _WHITESPACE_RE.sub(" ", value.strip())
    if _RM_PREFIX_RE.match(cleaned):
        return cleaned
    return f"RM of {cleaned}"


@dataclass(frozen=True, slots=True)
class DevelopmentResolution:
    development: Development
    created: bool


class DevelopmentService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_with_paths(self, org_id: UUID) -> list[tuple[Development, str]]:
        developments = list(
            (
                await self.db.scalars(
                    select(Development)
                    .where(Development.org_id == org_id)
                    .order_by(Development.name)
                )
            ).all()
        )
        by_id = {development.id: development for development in developments}

        def full_path(development: Development) -> str:
            names = [development.name]
            seen = {development.id}
            parent_id = development.parent_id
            while parent_id is not None:
                if parent_id in seen:
                    raise ValueError("Development hierarchy contains a cycle")
                seen.add(parent_id)
                parent = by_id.get(parent_id)
                if parent is None:
                    break
                names.append(parent.name)
                parent_id = parent.parent_id
            return " → ".join(reversed(names))

        return [(development, full_path(development)) for development in developments]

    async def create(
        self,
        *,
        org_id: UUID,
        name: str,
        development_type: DevelopmentType,
        parent_id: UUID | None,
        municipality: str | None = None,
        province: str | None = None,
        developer_contact_id: UUID | None = None,
        metadata: dict[str, object] | None = None,
    ) -> Development:
        normalized = normalize_development_name(name)
        if not normalized:
            raise ValueError("Development name is required")
        parent = await self._validate_parent(
            org_id=org_id,
            parent_id=parent_id,
            development_type=development_type,
        )
        await self._assert_unique_sibling(org_id, parent_id, normalized)
        development = Development(
            org_id=org_id,
            parent_id=parent_id,
            developer_contact_id=developer_contact_id,
            name=name.strip(),
            name_normalized=normalized,
            development_type=development_type,
            municipality=municipality or (parent.municipality if parent is not None else None),
            province=province or (parent.province if parent is not None else None),
            metadata_=metadata or {},
        )
        self.db.add(development)
        await self.db.flush()
        return development

    async def update(
        self,
        development_id: UUID,
        *,
        name: str | None = None,
        development_type: DevelopmentType | None = None,
        parent_id: UUID | None = None,
        parent_supplied: bool = False,
        municipality: str | None = None,
        province: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> Development:
        development = await self.db.scalar(
            select(Development).where(Development.id == development_id).with_for_update()
        )
        if development is None:
            raise ValueError("Development not found")
        target_parent_id = parent_id if parent_supplied else development.parent_id
        target_type = development_type or development.development_type
        if target_parent_id == development.id:
            raise ValueError("A development cannot be its own parent")
        await self._assert_not_descendant(development.id, target_parent_id)
        await self._validate_parent(
            org_id=development.org_id,
            parent_id=target_parent_id,
            development_type=target_type,
        )
        target_name = name.strip() if name is not None else development.name
        normalized = normalize_development_name(target_name)
        await self._assert_unique_sibling(
            development.org_id,
            target_parent_id,
            normalized,
            exclude_id=development.id,
        )
        development.name = target_name
        development.name_normalized = normalized
        development.development_type = target_type
        development.parent_id = target_parent_id
        if municipality is not None:
            development.municipality = municipality
        if province is not None:
            development.province = province
        if metadata is not None:
            development.metadata_ = metadata
        await self.db.flush()
        return development

    async def resolve_municipality(self, *, org_id: UUID, name: str) -> DevelopmentResolution:
        key = municipality_key(name)
        if not key:
            raise ValueError("Municipality is required for development resolution")
        municipalities = list(
            (
                await self.db.scalars(
                    select(Development).where(
                        Development.org_id == org_id,
                        Development.development_type == DevelopmentType.MUNICIPALITY,
                    )
                )
            ).all()
        )
        for municipality in municipalities:
            if municipality_key(municipality.name) == key:
                return DevelopmentResolution(municipality, False)
        created = await self.create(
            org_id=org_id,
            name=municipality_display_name(name),
            development_type=DevelopmentType.MUNICIPALITY,
            parent_id=None,
            municipality=municipality_display_name(name),
        )
        return DevelopmentResolution(created, True)

    async def resolve_for_promotion(
        self,
        *,
        org_id: UUID,
        development_name: str,
        municipality_name: str,
        developer_contact_id: UUID | None,
    ) -> DevelopmentResolution:
        municipality_resolution = await self.resolve_municipality(org_id=org_id, name=municipality_name)
        municipality = municipality_resolution.development
        if municipality_key(development_name) == municipality_key(municipality.name):
            return municipality_resolution

        normalized = normalize_development_name(development_name)
        existing = await self.db.scalar(
            select(Development).where(
                Development.org_id == org_id,
                Development.parent_id == municipality.id,
                Development.name_normalized == normalized,
            )
        )
        if existing is not None:
            return DevelopmentResolution(existing, False)
        created = await self.create(
            org_id=org_id,
            name=development_name,
            development_type=DevelopmentType.SUBDIVISION,
            parent_id=municipality.id,
            municipality=municipality.name,
            developer_contact_id=developer_contact_id,
        )
        return DevelopmentResolution(created, True)

    async def _validate_parent(
        self,
        *,
        org_id: UUID,
        parent_id: UUID | None,
        development_type: DevelopmentType,
    ) -> Development | None:
        if development_type == DevelopmentType.MUNICIPALITY:
            if parent_id is not None:
                raise ValueError("Municipalities cannot have a parent")
            return None
        if parent_id is None:
            raise ValueError(f"{development_type.value.capitalize()} developments require a parent")
        parent = await self.db.get(Development, parent_id)
        if parent is None or parent.org_id != org_id:
            raise ValueError("Development parent was not found in the same organization")
        if development_type == DevelopmentType.COMMUNITY and parent.development_type != DevelopmentType.MUNICIPALITY:
            raise ValueError("Communities must be children of municipalities")
        if development_type == DevelopmentType.SUBDIVISION and parent.development_type not in {
            DevelopmentType.MUNICIPALITY,
            DevelopmentType.COMMUNITY,
        }:
            raise ValueError("Subdivisions must be children of a municipality or community")
        return parent

    async def _assert_not_descendant(self, development_id: UUID, parent_id: UUID | None) -> None:
        current_id = parent_id
        seen: set[UUID] = set()
        while current_id is not None:
            if current_id == development_id:
                raise ValueError("Development hierarchy cannot contain a cycle")
            if current_id in seen:
                raise ValueError("Development hierarchy contains a cycle")
            seen.add(current_id)
            current = await self.db.get(Development, current_id)
            if current is None:
                return
            current_id = current.parent_id

    async def _assert_unique_sibling(
        self,
        org_id: UUID,
        parent_id: UUID | None,
        normalized: str,
        *,
        exclude_id: UUID | None = None,
    ) -> None:
        query = select(func.count(Development.id)).where(
            Development.org_id == org_id,
            Development.parent_id.is_(parent_id) if parent_id is None else Development.parent_id == parent_id,
            Development.name_normalized == normalized,
        )
        if exclude_id is not None:
            query = query.where(Development.id != exclude_id)
        if await self.db.scalar(query):
            raise ValueError("A sibling development with this name already exists")
