from __future__ import annotations

import asyncio
import math
from typing import Any
from uuid import UUID
from uuid import uuid4

import fitz
from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tendering import TenderDocument
from app.models.tendering import TenderDocumentMarkup
from app.schemas.tendering import TenderDocumentMarkupCreate
from app.services.minio_financing import delete_financing_document
from app.services.minio_financing import financing_key
from app.services.minio_financing import get_financing_document
from app.services.minio_financing import upload_financing_document


MAX_MARKUP_VERSIONS = 5


async def list_markups(db: AsyncSession, document_id: UUID) -> list[TenderDocumentMarkup]:
    return list(
        (
            await db.execute(
                select(TenderDocumentMarkup)
                .where(TenderDocumentMarkup.tender_document_id == document_id)
                .order_by(TenderDocumentMarkup.version_number.desc())
            )
        ).scalars()
    )


async def create_markup(
    db: AsyncSession,
    document: TenderDocument,
    data: TenderDocumentMarkupCreate,
) -> TenderDocumentMarkup:
    # Serialize version allocation for this document so concurrent saves cannot
    # produce the same version number.
    await db.execute(
        select(TenderDocument.id).where(TenderDocument.id == document.id).with_for_update()
    )
    latest = (
        await db.execute(
            select(func.max(TenderDocumentMarkup.version_number)).where(
                TenderDocumentMarkup.tender_document_id == document.id
            )
        )
    ).scalar_one()
    version_number = (latest or 0) + 1

    original = await asyncio.to_thread(get_financing_document, key=document.file_path)
    flattened = await asyncio.to_thread(flatten_pdf, original, data.annotation_data)
    key = financing_key(
        "tender-markups",
        f"{document.id}-v{version_number}-{uuid4()}.pdf",
    )
    await asyncio.to_thread(
        upload_financing_document,
        key=key,
        content=flattened,
        content_type="application/pdf",
    )

    markup = TenderDocumentMarkup(
        tender_document_id=document.id,
        version_number=version_number,
        annotation_data=data.annotation_data,
        calibration=data.calibration.model_dump() if data.calibration else None,
        flattened_pdf_path=key,
    )
    db.add(markup)
    try:
        await db.flush()
        versions = list(
            (
                await db.execute(
                    select(TenderDocumentMarkup)
                    .where(TenderDocumentMarkup.tender_document_id == document.id)
                    .order_by(TenderDocumentMarkup.version_number.desc())
                )
            ).scalars()
        )
        pruned = versions[MAX_MARKUP_VERSIONS:]
        for old in pruned:
            await db.delete(old)
        await db.commit()
        await db.refresh(markup)
    except Exception:
        await db.rollback()
        await asyncio.to_thread(delete_financing_document, key=key)
        raise

    # The database is authoritative. Remove derived files only after the row
    # pruning commits so a storage failure cannot roll back version metadata.
    for old in pruned:
        await asyncio.to_thread(delete_financing_document, key=old.flattened_pdf_path)
    return markup


async def get_flattened_pdf(markup: TenderDocumentMarkup) -> bytes:
    return await asyncio.to_thread(get_financing_document, key=markup.flattened_pdf_path)


def flatten_pdf(original: bytes, annotation_data: dict[str, object]) -> bytes:
    pdf = fitz.open(stream=original, filetype="pdf")
    pages = annotation_data.get("pages", {})
    if not isinstance(pages, dict):
        raise ValueError("annotation_data.pages must be an object")
    for page_key, state in pages.items():
        if not isinstance(state, dict):
            continue
        page_index = int(page_key) - 1
        if page_index < 0 or page_index >= pdf.page_count:
            continue
        page = pdf[page_index]
        source_width = _number(state.get("width"))
        source_height = _number(state.get("height"))
        objects = state.get("objects", [])
        if source_width <= 0 or source_height <= 0 or not isinstance(objects, list):
            continue
        sx = page.rect.width / source_width
        sy = page.rect.height / source_height
        for item in objects:
            if isinstance(item, dict):
                _draw_object(page, item, sx, sy)
    output = pdf.tobytes(garbage=4, deflate=True)
    pdf.close()
    return output


def _draw_object(page: fitz.Page, item: dict[str, Any], sx: float, sy: float) -> None:
    kind = str(item.get("type", "")).lower()
    stroke = _color(item.get("stroke"), (0.9, 0.1, 0.1))
    fill = _color(item.get("fill"), None)
    width = max(_number(item.get("strokeWidth"), 2) * (sx + sy) / 2, 0.5)
    left = _number(item.get("left")) * sx
    top = _number(item.get("top")) * sy
    scale_x = _number(item.get("scaleX"), 1)
    scale_y = _number(item.get("scaleY"), 1)

    if kind == "rect":
        rect = fitz.Rect(left, top, left + _number(item.get("width")) * scale_x * sx, top + _number(item.get("height")) * scale_y * sy)
        page.draw_rect(rect, color=stroke, fill=fill, width=width, overlay=True)
    elif kind == "ellipse":
        rect = fitz.Rect(left, top, left + _number(item.get("width")) * scale_x * sx, top + _number(item.get("height")) * scale_y * sy)
        page.draw_oval(rect, color=stroke, fill=fill, width=width, overlay=True)
    elif kind == "line":
        x1 = left + _number(item.get("x1")) * scale_x * sx
        y1 = top + _number(item.get("y1")) * scale_y * sy
        x2 = left + _number(item.get("x2")) * scale_x * sx
        y2 = top + _number(item.get("y2")) * scale_y * sy
        page.draw_line((x1, y1), (x2, y2), color=stroke, width=width, overlay=True)
        if item.get("annotationKind") == "arrow":
            _draw_arrow_head(page, x1, y1, x2, y2, stroke, width)
    elif kind in {"i-text", "itext", "textbox", "text"}:
        text_value = str(item.get("text", ""))
        size = max(_number(item.get("fontSize"), 18) * sy * scale_y, 5)
        page.insert_text((left, top + size), text_value, fontsize=size, color=fill or stroke, overlay=True)
    elif kind == "path":
        _draw_path(page, item, sx, sy, stroke, width)


def _draw_path(page: fitz.Page, item: dict[str, Any], sx: float, sy: float, color: tuple[float, float, float], width: float) -> None:
    path = item.get("path")
    if not isinstance(path, list):
        return
    left = _number(item.get("left")) * sx
    top = _number(item.get("top")) * sy
    scale_x = _number(item.get("scaleX"), 1) * sx
    scale_y = _number(item.get("scaleY"), 1) * sy
    offset = item.get("pathOffset") if isinstance(item.get("pathOffset"), dict) else {}
    ox = _number(offset.get("x"))
    oy = _number(offset.get("y"))
    previous: tuple[float, float] | None = None
    for command in path:
        if not isinstance(command, list) or len(command) < 3:
            continue
        op = str(command[0]).upper()
        if op in {"M", "L"}:
            point = (left + (_number(command[1]) - ox) * scale_x, top + (_number(command[2]) - oy) * scale_y)
        elif op in {"Q", "C"}:
            point = (left + (_number(command[-2]) - ox) * scale_x, top + (_number(command[-1]) - oy) * scale_y)
        else:
            continue
        if previous is not None:
            page.draw_line(previous, point, color=color, width=width, overlay=True)
        previous = point


def _draw_arrow_head(page: fitz.Page, x1: float, y1: float, x2: float, y2: float, color: tuple[float, float, float], width: float) -> None:
    angle = math.atan2(y2 - y1, x2 - x1)
    length = max(8, width * 4)
    for delta in (math.pi * 0.8, -math.pi * 0.8):
        page.draw_line(
            (x2, y2),
            (x2 + length * math.cos(angle + delta), y2 + length * math.sin(angle + delta)),
            color=color,
            width=width,
            overlay=True,
        )


def _number(value: object, default: float = 0) -> float:
    return float(value) if isinstance(value, int | float) else default


def _color(value: object, default: tuple[float, float, float] | None) -> tuple[float, float, float] | None:
    if not isinstance(value, str) or value in {"", "transparent"}:
        return default
    if value.startswith("#") and len(value) in {4, 7}:
        text = value[1:]
        if len(text) == 3:
            text = "".join(char * 2 for char in text)
        try:
            return tuple(int(text[index:index + 2], 16) / 255 for index in (0, 2, 4))  # type: ignore[return-value]
        except ValueError:
            return default
    return default
