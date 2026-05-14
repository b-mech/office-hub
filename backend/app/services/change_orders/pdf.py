from __future__ import annotations

from datetime import date
from decimal import Decimal
from io import BytesIO
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Paragraph
from reportlab.platypus import SimpleDocTemplate
from reportlab.platypus import Spacer
from reportlab.platypus import Table
from reportlab.platypus import TableStyle

from app.models.sales import ChangeOrder


COMPANY_NAME = "Connection Homes"
COMPANY_PHONE = "Tel: 1-204-261-1717"
COMPANY_EMAIL = "accounts@connectionhomes.ca"
COMPANY_ADDRESS = "162-2025 Corydon Ave, Winnipeg, MB R3P 0N5"

PAGE_SIZE = LETTER
PAGE_MARGIN = 0.72 * inch
GREY_BORDER = colors.HexColor("#A8A8A8")
LABEL_BACKGROUND = colors.HexColor("#F5F5F5")
DUE_UPON_RECEIPT_TEXT = (
    "Due upon receipt. We accept payment via e-transfers "
    "(accounts@connectionhomes.ca) or by cheque. Thank You!"
)


def render_change_order_pdf(change_order: ChangeOrder) -> bytes:
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=PAGE_SIZE,
        leftMargin=PAGE_MARGIN,
        rightMargin=PAGE_MARGIN,
        topMargin=PAGE_MARGIN,
        bottomMargin=PAGE_MARGIN,
    )
    story = _build_story(change_order, document.width)
    document.build(story, canvasmaker=NumberedCanvas)
    return buffer.getvalue()


def _build_story(change_order: ChangeOrder, content_width: float) -> list[Any]:
    styles = _styles()
    charges = [item for item in change_order.line_items if not item.is_credit]
    credits = [item for item in change_order.line_items if item.is_credit]

    story: list[Any] = [
        Paragraph(COMPANY_NAME, styles["company_name"]),
        Paragraph(COMPANY_PHONE, styles["company_line"]),
        Paragraph(COMPANY_EMAIL, styles["company_line"]),
        Paragraph(COMPANY_ADDRESS, styles["company_line"]),
        Spacer(1, 12),
        _title_table(change_order, content_width, styles),
        Spacer(1, 10),
        _address_client_table(change_order, content_width, styles),
        Spacer(1, 14),
        Paragraph("SUMMARY OF CHANGES", styles["section_heading"]),
        Spacer(1, 6),
    ]

    story.extend(_line_item_rows(charges, credit=False, styles=styles))

    if credits:
        story.extend(
            [
                Spacer(1, 8),
                Paragraph("CREDITS", styles["section_heading"]),
                Spacer(1, 6),
                *_line_item_rows(credits, credit=True, styles=styles),
            ]
        )

    story.extend(
        [
            Spacer(1, 10),
            _payment_method_flowable(change_order.payment_method, styles),
            Spacer(1, 12),
            _totals_table(change_order, content_width, styles),
            Spacer(1, 30),
            _signature_table(content_width, styles),
        ]
    )
    return story


def _title_table(change_order: ChangeOrder, content_width: float, styles: dict[str, ParagraphStyle]) -> Table:
    table = Table(
        [
            [
                Paragraph(_format_change_order_title(change_order), styles["title"]),
                Paragraph(_format_date(change_order.date), styles["title_date"]),
            ]
        ],
        colWidths=[content_width * 0.65, content_width * 0.35],
        hAlign="LEFT",
    )
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    return table


def _address_client_table(
    change_order: ChangeOrder,
    content_width: float,
    styles: dict[str, ParagraphStyle],
) -> Table:
    table = Table(
        [
            [
                Paragraph("Address:", styles["label"]),
                Paragraph(_escape(change_order.address), styles["body"]),
            ],
            [
                Paragraph("Client Information:", styles["label"]),
                Paragraph(_escape(change_order.client_name), styles["body"]),
            ],
        ],
        colWidths=[content_width * 0.28, content_width * 0.72],
        hAlign="LEFT",
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), LABEL_BACKGROUND),
                ("BOX", (0, 0), (-1, -1), 0.5, GREY_BORDER),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, GREY_BORDER),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return table


def _line_item_rows(items: list[Any], credit: bool, styles: dict[str, ParagraphStyle]) -> list[Table]:
    rows: list[Table] = []
    for item in items:
        amount = abs(item.amount)
        table = Table(
            [
                [
                    Paragraph("-", styles["item_dash"]),
                    Paragraph(_format_amount(amount, credit=credit), styles["item_amount"]),
                    Paragraph("–", styles["item_dash"]),
                    Paragraph(_escape(item.description or ""), styles["item_description"]),
                ]
            ],
            colWidths=[12, 78, 12, 360],
            hAlign="LEFT",
        )
        table.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 2),
                    ("TOPPADDING", (0, 0), (-1, -1), 1),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ]
            )
        )
        rows.append(table)
    return rows


def _payment_method_flowable(payment_method: str, styles: dict[str, ParagraphStyle]) -> Paragraph:
    if payment_method == "add_to_mortgage":
        return Paragraph("Add to Mortgage", styles["payment_mortgage"])
    return Paragraph(DUE_UPON_RECEIPT_TEXT, styles["payment_due"])


def _totals_table(
    change_order: ChangeOrder,
    content_width: float,
    styles: dict[str, ParagraphStyle],
) -> Table:
    table_width = content_width * 0.5
    table = Table(
        [
            [
                Paragraph("SUB TOTAL :", styles["total_label"]),
                Paragraph(_format_total(change_order.subtotal), styles["total_value_bold"]),
            ],
            [
                Paragraph("GST (5%) :", styles["total_label"]),
                Paragraph(_format_total(change_order.gst), styles["total_value"]),
            ],
            [
                Paragraph("GRAND TOTAL :", styles["grand_total_label"]),
                Paragraph(_format_total(change_order.total), styles["grand_total_value"]),
            ],
        ],
        colWidths=[table_width * 0.52, table_width * 0.48],
        hAlign="RIGHT",
    )
    table.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 0.5, GREY_BORDER),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, GREY_BORDER),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return table


def _signature_table(content_width: float, styles: dict[str, ParagraphStyle]) -> Table:
    table = Table(
        [
            [
                Paragraph("____________________________", styles["signature_line"]),
                Paragraph("____________________________", styles["signature_line"]),
            ],
            [
                Paragraph("Purchaser Signature", styles["signature_label"]),
                Paragraph("Date", styles["signature_label"]),
            ],
        ],
        colWidths=[content_width * 0.55, content_width * 0.45],
        hAlign="LEFT",
    )
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )
    return table


def _styles() -> dict[str, ParagraphStyle]:
    return {
        "company_name": ParagraphStyle(
            "CompanyName",
            fontName="Helvetica-Bold",
            fontSize=13,
            leading=16,
            alignment=TA_LEFT,
        ),
        "company_line": ParagraphStyle(
            "CompanyLine",
            fontName="Helvetica",
            fontSize=9,
            leading=11,
            alignment=TA_LEFT,
        ),
        "title": ParagraphStyle(
            "Title",
            fontName="Helvetica-Bold",
            fontSize=14,
            leading=17,
            alignment=TA_LEFT,
        ),
        "title_date": ParagraphStyle(
            "TitleDate",
            fontName="Helvetica",
            fontSize=10,
            leading=13,
            alignment=TA_RIGHT,
        ),
        "label": ParagraphStyle("Label", fontName="Helvetica-Bold", fontSize=10, leading=12),
        "body": ParagraphStyle("Body", fontName="Helvetica", fontSize=10, leading=12),
        "section_heading": ParagraphStyle(
            "SectionHeading",
            fontName="Helvetica-Bold",
            fontSize=11,
            leading=14,
        ),
        "item_dash": ParagraphStyle("ItemDash", fontName="Helvetica", fontSize=10, leading=12),
        "item_amount": ParagraphStyle(
            "ItemAmount",
            fontName="Courier",
            fontSize=10,
            leading=12,
            alignment=TA_RIGHT,
        ),
        "item_description": ParagraphStyle(
            "ItemDescription",
            fontName="Helvetica",
            fontSize=10,
            leading=12,
            alignment=TA_LEFT,
        ),
        "payment_mortgage": ParagraphStyle(
            "PaymentMortgage",
            fontName="Helvetica-BoldOblique",
            fontSize=11,
            leading=14,
        ),
        "payment_due": ParagraphStyle("PaymentDue", fontName="Helvetica", fontSize=10, leading=13),
        "total_label": ParagraphStyle(
            "TotalLabel",
            fontName="Helvetica-Bold",
            fontSize=10,
            leading=12,
            alignment=TA_RIGHT,
        ),
        "total_value": ParagraphStyle(
            "TotalValue",
            fontName="Helvetica",
            fontSize=10,
            leading=12,
            alignment=TA_RIGHT,
        ),
        "total_value_bold": ParagraphStyle(
            "TotalValueBold",
            fontName="Helvetica-Bold",
            fontSize=10,
            leading=12,
            alignment=TA_RIGHT,
        ),
        "grand_total_label": ParagraphStyle(
            "GrandTotalLabel",
            fontName="Helvetica-Bold",
            fontSize=11,
            leading=13,
            alignment=TA_RIGHT,
        ),
        "grand_total_value": ParagraphStyle(
            "GrandTotalValue",
            fontName="Helvetica-Bold",
            fontSize=11,
            leading=13,
            alignment=TA_RIGHT,
        ),
        "signature_line": ParagraphStyle(
            "SignatureLine",
            fontName="Helvetica",
            fontSize=10,
            leading=12,
        ),
        "signature_label": ParagraphStyle(
            "SignatureLabel",
            fontName="Helvetica",
            fontSize=9,
            leading=11,
        ),
        "footer": ParagraphStyle(
            "Footer",
            fontName="Helvetica",
            fontSize=8,
            leading=10,
            alignment=TA_CENTER,
        ),
    }


class NumberedCanvas(Canvas):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._saved_page_states: list[dict[str, Any]] = []

    def showPage(self) -> None:
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self) -> None:
        page_count = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self._draw_page_number(page_count)
            super().showPage()
        super().save()

    def _draw_page_number(self, page_count: int) -> None:
        self.setFont("Helvetica", 8)
        self.drawCentredString(PAGE_SIZE[0] / 2, 0.38 * inch, f"Page {self._pageNumber} of {page_count}")


def _format_change_order_title(change_order: ChangeOrder) -> str:
    if change_order.co_number:
        return f"CHANGE ORDER #{_co_number(change_order.co_number)}".upper()
    return "CHANGE ORDER DRAFT"


def _co_number(value: str) -> str:
    cleaned = value.strip()
    if cleaned.lower().startswith("co-"):
        return cleaned
    if cleaned.startswith("#"):
        return cleaned[1:]
    return cleaned


def _format_date(value: date | None) -> str:
    if value is None:
        return "Not set"
    return value.strftime("%B %-d, %Y")


def _format_amount(value: Decimal, credit: bool = False) -> str:
    amount = f"$ {value:,.2f}"
    return f"({amount:>10})" if credit else f"{amount:>12}"


def _format_total(value: Decimal) -> str:
    return f"$ {value:,.2f}"


def _escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\n", "<br/>")
    )
