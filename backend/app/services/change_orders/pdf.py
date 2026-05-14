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

    def add(
        text: str = "",
        *,
        size: int = 10,
        bold: bool = False,
        gap: Decimal = LINE_HEIGHT,
        x: Decimal = MARGIN,
    ) -> None:
        nonlocal y
        if text:
            lines.append(PdfLine(text=text, size=size, x=x, y=y, bold=bold))
        y -= gap

    charges = [item for item in change_order.line_items if not item.is_credit]
    credits = [item for item in change_order.line_items if item.is_credit]

    add(_format_change_order_title(change_order), size=16, bold=True, gap=Decimal("24"))
    lines.append(
        PdfLine(
            text=_format_date(change_order.date),
            size=10,
            x=Decimal("444"),
            y=PAGE_HEIGHT - MARGIN,
            bold=True,
        )
    )

    add("Address:", bold=True)
    add(change_order.address)
    add("Client Information:", bold=True, gap=Decimal("14"))
    add(change_order.client_name, gap=Decimal("26"))

    add("SUMMARY OF CHANGES", size=12, bold=True, gap=Decimal("20"))
    for item in charges:
        _add_line_item(add, item.description, abs(item.amount))

    if credits:
        add(gap=Decimal("8"))
        add("CREDITS", size=12, bold=True, gap=Decimal("20"))
        for item in credits:
            _add_line_item(add, item.description, abs(item.amount), credit=True)

    y = min(y, Decimal("238"))
    add(_format_payment_method(change_order.payment_method), bold=True, gap=Decimal("28"))

    total_label_x = Decimal("332")
    total_value_x = Decimal("430")
    add("SUB TOTAL :", bold=True, x=total_label_x)
    lines.append(
        PdfLine(
            text=_money(change_order.subtotal),
            size=10,
            x=total_value_x,
            y=y + LINE_HEIGHT,
            bold=True,
        )
    )
    add("GST (5%) :", bold=True, x=total_label_x)
    lines.append(
        PdfLine(
            text=_money(change_order.gst),
            size=10,
            x=total_value_x,
            y=y + LINE_HEIGHT,
            bold=True,
        )
    )
    add("GRAND TOTAL :", size=11, bold=True, x=total_label_x)
    lines.append(
        PdfLine(
            text=_money(change_order.total),
            size=11,
            x=total_value_x,
            y=y + LINE_HEIGHT,
            bold=True,
        )
    )

    y = Decimal("96")
    add("________________________________________", x=Decimal("80"))
    add("Purchaser Signature", size=9, x=Decimal("80"), gap=Decimal("26"))
    lines.append(PdfLine(text="____________________________", size=10, x=Decimal("392"), y=Decimal("96")))
    lines.append(PdfLine(text="Date", size=9, x=Decimal("392"), y=Decimal("76")))

    return lines


def _add_line_item(
    add,
    description: str,
    amount: Decimal,
    credit: bool = False,
) -> None:
    amount_text = f"({_money(amount)})" if credit else _money(amount)
    wrapped_description = _wrap_text(description, width=70)
    first_line = wrapped_description[0] if wrapped_description else ""
    add(f"- {amount_text:>12} - {first_line}", gap=Decimal("14"))
    for continuation in wrapped_description[1:]:
        add(f"                 {continuation}", gap=Decimal("14"))


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
    if value is None:
        return "Not set"
    return value.strftime("%B %-d, %Y")


def _format_payment_method(value: str) -> str:
    if value == "add_to_mortgage":
        return "Add to Mortgage"
    return "Due upon receipt"


def _format_change_order_title(change_order: ChangeOrder) -> str:
    if change_order.co_number:
        return f"CHANGE ORDER {change_order.co_number}"
    return "CHANGE ORDER"
