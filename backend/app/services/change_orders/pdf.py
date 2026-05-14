from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from io import BytesIO
from textwrap import wrap
from typing import Iterable

from app.models.sales import ChangeOrder


PAGE_WIDTH = Decimal("612")
PAGE_HEIGHT = Decimal("792")
MARGIN = Decimal("54")
LINE_HEIGHT = Decimal("15")


@dataclass(slots=True)
class PdfLine:
    text: str
    size: int = 10
    x: Decimal = MARGIN
    y: Decimal = Decimal("0")
    bold: bool = False


def render_change_order_pdf(change_order: ChangeOrder) -> bytes:
    """Render a simple one-page change order PDF.

    This is intentionally self-contained until the final branded template asset
    is added to the repo.
    """

    lines = _build_lines(change_order)
    return _render_pdf(lines)


def _build_lines(change_order: ChangeOrder) -> list[PdfLine]:
    y = PAGE_HEIGHT - MARGIN
    lines: list[PdfLine] = []

    def add(text: str = "", *, size: int = 10, bold: bool = False, gap: Decimal = LINE_HEIGHT) -> None:
        nonlocal y
        if text:
            lines.append(PdfLine(text=text, size=size, y=y, bold=bold))
        y -= gap

    co_number = change_order.co_number or "Draft"
    add("CHANGE ORDER", size=18, bold=True, gap=Decimal("22"))
    add(f"Change Order: {co_number}", size=11, bold=True)
    add(f"Date: {_format_date(change_order.date)}")
    add(f"Project / Address: {change_order.address}", bold=True)
    add(f"Client: {change_order.client_name}")
    add(f"Payment Method: {_format_payment_method(change_order.payment_method)}")
    add(gap=Decimal("10"))

    add("Scope / Line Items", size=12, bold=True, gap=Decimal("18"))
    add("Description                                                        Amount", bold=True)
    add("-" * 86, gap=Decimal("12"))

    for item in change_order.line_items:
        amount = -abs(item.amount) if item.is_credit else abs(item.amount)
        description_lines = _wrap_text(item.description or "", width=68)
        for index, description in enumerate(description_lines or [""]):
            if index == 0:
                add(f"{description:<68} {_money(amount):>12}")
            else:
                add(description)

    add(gap=Decimal("10"))
    add(f"{'Subtotal:':>68} {_money(change_order.subtotal):>12}", bold=True)
    add(f"{'GST:':>68} {_money(change_order.gst):>12}")
    add(f"{'Total:':>68} {_money(change_order.total):>12}", size=12, bold=True)
    add(gap=Decimal("18"))

    if change_order.notes:
        add("Notes", size=12, bold=True)
        for line in _wrap_text(change_order.notes, width=90):
            add(line)
        add(gap=Decimal("12"))

    add("Approval", size=12, bold=True, gap=Decimal("22"))
    add("Client Signature: ____________________________________    Date: __________________")
    add("Connection Homes: ___________________________________    Date: __________________")

    return lines


def _render_pdf(lines: Iterable[PdfLine]) -> bytes:
    stream = "\n".join(_line_operator(line) for line in lines)
    stream_bytes = stream.encode("latin-1", errors="replace")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 4 0 R /F2 5 0 R >> >> /Contents 6 0 R >>"
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>",
        b"<< /Length " + str(len(stream_bytes)).encode("ascii") + b" >>\nstream\n" + stream_bytes + b"\nendstream",
    ]

    buffer = BytesIO()
    buffer.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets: list[int] = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(buffer.tell())
        buffer.write(f"{index} 0 obj\n".encode("ascii"))
        buffer.write(obj)
        buffer.write(b"\nendobj\n")

    xref_offset = buffer.tell()
    buffer.write(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    buffer.write(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        buffer.write(f"{offset:010d} 00000 n \n".encode("ascii"))
    buffer.write(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
    )
    return buffer.getvalue()


def _line_operator(line: PdfLine) -> str:
    font = "F2" if line.bold else "F1"
    return f"BT /{font} {line.size} Tf {line.x} {line.y} Td ({_escape_pdf_text(line.text)}) Tj ET"


def _escape_pdf_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _wrap_text(value: str, width: int) -> list[str]:
    return wrap(" ".join(value.split()), width=width) or [""]


def _money(value: Decimal) -> str:
    return f"${value:,.2f}"


def _format_date(value: date | None) -> str:
    return value.isoformat() if value is not None else "Not set"


def _format_payment_method(value: str) -> str:
    if value == "add_to_mortgage":
        return "Add to mortgage"
    return "Due upon receipt"
