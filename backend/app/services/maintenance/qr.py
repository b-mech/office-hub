from __future__ import annotations

from datetime import datetime, timedelta, timezone
from io import BytesIO
from uuid import UUID

import qrcode
from reportlab.lib.pagesizes import inch
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.maintenance import MaintIntakeToken, MaintUnitToken
from app.models.rentals import RentalProperty, RentalUnit
from app.services.maintenance.tokens import generate_token, hash_token, rotate_unit_token, token_matches


CARD_SIZE = (4 * inch, 6 * inch)


def public_url(raw_token: str) -> str:
    if not settings.maintenance_enabled:
        raise RuntimeError("Maintenance is disabled until PUBLIC_BASE_URL is configured")
    return f"{settings.public_base_url.rstrip('/')}/r/{raw_token}"


async def resolve_intake_unit(db: AsyncSession, raw_token: str) -> tuple[RentalUnit, RentalProperty] | None:
    digest = hash_token(raw_token)
    now = datetime.now(timezone.utc)
    permanent = await db.scalar(
        select(MaintUnitToken).where(
            MaintUnitToken.token_hash == digest,
            MaintUnitToken.revoked_at.is_(None),
        )
    )
    unit_id = permanent.unit_id if permanent and token_matches(raw_token, permanent.token_hash) else None
    if unit_id is None:
        temporary = await db.scalar(
            select(MaintIntakeToken).where(
                MaintIntakeToken.token_hash == digest,
                MaintIntakeToken.expires_at > now,
            )
        )
        unit_id = temporary.unit_id if temporary and token_matches(raw_token, temporary.token_hash) else None
    if unit_id is None:
        return None
    row = (
        await db.execute(
            select(RentalUnit, RentalProperty)
            .join(RentalProperty, RentalProperty.id == RentalUnit.property_id)
            .where(RentalUnit.id == unit_id)
        )
    ).first()
    return (row[0], row[1]) if row else None


async def create_temporary_intake_link(db: AsyncSession, unit_id: int) -> str:
    raw = generate_token()
    db.add(
        MaintIntakeToken(
            unit_id=unit_id,
            token_hash=raw.digest,
            expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        )
    )
    await db.flush()
    return public_url(raw.value)


async def rotate_for_unit(
    db: AsyncSession, unit: RentalUnit, created_by: UUID | None
) -> tuple[str, RentalProperty]:
    _, raw = await rotate_unit_token(db, unit.id, created_by)
    unit.maintenance_qr_rotation_recommended_at = None
    prop = await db.get(RentalProperty, unit.property_id)
    if prop is None:
        raise ValueError("Rental property not found")
    return raw, prop


def verify_print_token(raw_token: str, record: MaintUnitToken | None) -> bool:
    return bool(record and record.revoked_at is None and token_matches(raw_token, record.token_hash))


def printable_pdf(cards: list[tuple[str, str, str]]) -> bytes:
    """Build cards from (raw token, property label, unit label); raw values are never stored."""
    output = BytesIO()
    canvas = Canvas(output, pagesize=CARD_SIZE)
    width, height = CARD_SIZE
    for raw_token, property_label, unit_label in cards:
        url = public_url(raw_token)
        qr_image = qrcode.make(url)
        qr_bytes = BytesIO()
        qr_image.save(qr_bytes, format="PNG")
        qr_bytes.seek(0)
        canvas.setFont("Helvetica-Bold", 18)
        canvas.drawCentredString(width / 2, height - 0.55 * inch, settings.public_brand_name)
        canvas.setFont("Helvetica-Bold", 13)
        canvas.drawCentredString(width / 2, height - 0.88 * inch, "Report a maintenance issue")
        canvas.drawImage(ImageReader(qr_bytes), 0.65 * inch, 2.1 * inch, 2.7 * inch, 2.7 * inch)
        canvas.setFont("Helvetica", 9)
        canvas.drawCentredString(width / 2, 1.78 * inch, property_label[:55])
        canvas.drawCentredString(width / 2, 1.57 * inch, unit_label[:55])
        canvas.setFont("Helvetica", 7)
        canvas.drawCentredString(width / 2, 1.27 * inch, url[:90])
        canvas.setFont("Helvetica-Bold", 9)
        emergency = settings.privi_emergency_phone or "Contact the property office"
        canvas.drawCentredString(width / 2, 0.78 * inch, f"Emergency: {emergency}")
        canvas.showPage()
    canvas.save()
    return output.getvalue()
