from __future__ import annotations

from datetime import date
from decimal import Decimal
from io import BytesIO
from pathlib import Path
import re
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import HRFlowable
from reportlab.platypus import Image
from reportlab.platypus import Paragraph
from reportlab.platypus import SimpleDocTemplate
from reportlab.platypus import Spacer
from reportlab.platypus import Table
from reportlab.platypus import TableStyle

from app.models.sales import ChangeOrder


COMPANY_NAME = "Connection Homes"
COMPANY_PHONE = "Tel: 1-204-261-1717"
COMPANY_EMAIL = "accounts@connectionhomes.ca"
COMPANY_ADDRESS_LINE_1 = "162-2025 Corydon Ave"
COMPANY_ADDRESS_LINE_2 = "Winnipeg, MB R3P 0N5"

LOGO_PATH = Path(__file__).parent.parent / "templates" / "connection_homes_logo.jpg"
APP_TEMPLATE_LOGO_PATH = Path(__file__).resolve().parents[2] / "templates" / "connection_homes_logo.jpg"

PAGE_SIZE = LETTER
PAGE_MARGIN = 0.72 * inch
BRAND_BLUE = colors.HexColor("#1B5C9B")
BODY_GREY = colors.HexColor("#404040")
RULE_GREY = colors.HexColor("#A7A7A7")
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
        _header_table(content_width, styles),
        Spacer(1, 8),
        HRFlowable(width="100%", thickness=0.5, color=RULE_GREY, spaceBefore=0, spaceAfter=0),
        Spacer(1, 20),
        _title_table(change_order, content_width, styles),
        Spacer(1, 18),
        _address_client_table(change_order, content_width, styles),
        Spacer(1, 16),
        Paragraph("SUMMARY OF CHANGES", styles["section_heading"]),
        Spacer(1, 8),
    ]

    story.extend(_line_item_rows(charges, credit=False, content_width=content_width, styles=styles))

    if credits:
        story.extend(
            [
                Spacer(1, 10),
                Paragraph("CREDITS", styles["section_heading"]),
                Spacer(1, 8),
                *_line_item_rows(credits, credit=True, content_width=content_width, styles=styles),
            ]
        )

    story.extend(
        [
            Spacer(1, 14),
            _payment_method_flowable(change_order.payment_method, styles),
            Spacer(1, 14),
            _totals_table(change_order, content_width, styles),
            Spacer(1, 36),
            _signature_table(content_width, styles),
        ]
    )
    return story


def _header_table(content_width: float, styles: dict[str, ParagraphStyle]) -> Table:
    logo = _logo_image(width=160)
    left_cell: Any = logo if logo is not None else Paragraph(COMPANY_NAME, styles["header_fallback_logo"])
    contact = [
        Paragraph(COMPANY_NAME, styles["header_company"]),
        Paragraph(COMPANY_PHONE, styles["header_line"]),
        Paragraph(f'<u><font color="#1B5C9B">{COMPANY_EMAIL}</font></u>', styles["header_line"]),
        Spacer(1, 6),
        Paragraph(COMPANY_ADDRESS_LINE_1, styles["header_line"]),
        Paragraph(COMPANY_ADDRESS_LINE_2, styles["header_line"]),
    ]
    table = Table(
        [[left_cell, contact]],
        colWidths=[content_width * 0.48, content_width * 0.52],
        hAlign="LEFT",
    )
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    return table


def _title_table(change_order: ChangeOrder, content_width: float, styles: dict[str, ParagraphStyle]) -> Table:
    table = Table(
        [
            [
                Paragraph(_format_change_order_title(change_order), styles["title"]),
                Paragraph(_format_date(change_order.date), styles["title_date"]),
            ]
        ],
        colWidths=[content_width * 0.58, content_width * 0.42],
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
        colWidths=[110, content_width - 110],
        hAlign="LEFT",
    )
    table.setStyle(
        TableStyle(
            [
                ("LINEBELOW", (0, 0), (-1, 0), 0.5, RULE_GREY),
                ("LINEBELOW", (0, 1), (-1, 1), 0.5, RULE_GREY),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return table


def _line_item_rows(
    items: list[Any],
    credit: bool,
    content_width: float,
    styles: dict[str, ParagraphStyle],
) -> list[Any]:
    rows: list[Any] = []
    description_width = content_width - 130
    for item in items:
        amount = abs(item.amount)
        table = Table(
            [
                [
                    Paragraph("▪", styles["item_bullet"]),
                    Paragraph(_format_amount(amount, credit=credit), styles["item_amount"]),
                    Paragraph("–", styles["item_dash"]),
                    Paragraph(_escape(item.description or ""), styles["item_description"]),
                ]
            ],
            colWidths=[14, 92, 14, description_width],
            hAlign="LEFT",
        )
        table.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 2),
                    ("TOPPADDING", (0, 0), (-1, -1), 0),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                ]
            )
        )
        rows.extend([table, Spacer(1, 10)])
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
    table_width = content_width * 0.45
    table = Table(
        [
            [
                Paragraph("SUB TOTAL :", styles["total_label"]),
                Paragraph(_format_total(change_order.subtotal), styles["total_value"]),
            ],
            [
                Paragraph("GST (5%) :", styles["total_label"]),
                Paragraph(_format_total(change_order.gst), styles["total_value"]),
            ],
            [
                Paragraph("GRAND TOTAL :", styles["total_label"]),
                Paragraph(_format_total(change_order.total), styles["total_value"]),
            ],
        ],
        colWidths=[table_width * 0.54, table_width * 0.46],
        hAlign="RIGHT",
    )
    table.setStyle(
        TableStyle(
            [
                ("LINEBELOW", (0, 0), (-1, 0), 0.5, RULE_GREY),
                ("LINEBELOW", (0, 1), (-1, 1), 0.5, RULE_GREY),
                ("LINEBELOW", (0, 2), (-1, 2), 0.5, RULE_GREY),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return table


def _signature_table(content_width: float, styles: dict[str, ParagraphStyle]) -> Table:
    table = Table(
        [
            [
                Paragraph("______________________________", styles["signature_line"]),
                Paragraph("______________________________", styles["signature_line"]),
            ],
            [
                Paragraph("Purchaser Signature", styles["signature_label"]),
                Paragraph("Date", styles["signature_date_label"]),
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
        "header_fallback_logo": ParagraphStyle(
            "HeaderFallbackLogo",
            fontName="Helvetica-Bold",
            fontSize=18,
            leading=21,
            textColor=BRAND_BLUE,
            alignment=TA_LEFT,
        ),
        "header_company": ParagraphStyle(
            "HeaderCompany",
            fontName="Helvetica-Bold",
            fontSize=10,
            leading=12,
            textColor=BODY_GREY,
            alignment=TA_RIGHT,
        ),
        "header_line": ParagraphStyle(
            "HeaderLine",
            fontName="Helvetica",
            fontSize=9,
            leading=11,
            textColor=BODY_GREY,
            alignment=TA_RIGHT,
        ),
        "title": ParagraphStyle(
            "Title",
            fontName="Helvetica-BoldOblique",
            fontSize=22,
            leading=26,
            textColor=BRAND_BLUE,
            alignment=TA_LEFT,
        ),
        "title_date": ParagraphStyle(
            "TitleDate",
            fontName="Helvetica-BoldOblique",
            fontSize=22,
            leading=26,
            textColor=BRAND_BLUE,
            alignment=TA_RIGHT,
        ),
        "label": ParagraphStyle(
            "Label",
            fontName="Helvetica-Bold",
            fontSize=10,
            leading=12,
            textColor=BODY_GREY,
        ),
        "body": ParagraphStyle(
            "Body",
            fontName="Helvetica",
            fontSize=10,
            leading=12,
            textColor=BODY_GREY,
        ),
        "section_heading": ParagraphStyle(
            "SectionHeading",
            fontName="Helvetica-Bold",
            fontSize=11,
            leading=14,
            textColor=BODY_GREY,
        ),
        "item_bullet": ParagraphStyle(
            "ItemBullet",
            fontName="Helvetica-Bold",
            fontSize=11,
            leading=13,
            textColor=BRAND_BLUE,
        ),
        "item_dash": ParagraphStyle(
            "ItemDash",
            fontName="Helvetica",
            fontSize=10,
            leading=13,
            textColor=BODY_GREY,
            alignment=TA_RIGHT,
        ),
        "item_amount": ParagraphStyle(
            "ItemAmount",
            fontName="Courier",
            fontSize=10,
            leading=13,
            textColor=BODY_GREY,
            alignment=TA_RIGHT,
        ),
        "item_description": ParagraphStyle(
            "ItemDescription",
            fontName="Helvetica",
            fontSize=10,
            leading=13,
            textColor=BODY_GREY,
            alignment=TA_LEFT,
        ),
        "payment_mortgage": ParagraphStyle(
            "PaymentMortgage",
            fontName="Helvetica-BoldOblique",
            fontSize=18,
            leading=22,
            textColor=BRAND_BLUE,
        ),
        "payment_due": ParagraphStyle(
            "PaymentDue",
            fontName="Helvetica",
            fontSize=10,
            leading=13,
            textColor=BODY_GREY,
        ),
        "total_label": ParagraphStyle(
            "TotalLabel",
            fontName="Helvetica-Bold",
            fontSize=10,
            leading=12,
            textColor=BODY_GREY,
            alignment=TA_RIGHT,
        ),
        "total_value": ParagraphStyle(
            "TotalValue",
            fontName="Courier-Bold",
            fontSize=10,
            leading=12,
            textColor=BODY_GREY,
            alignment=TA_RIGHT,
        ),
        "signature_line": ParagraphStyle(
            "SignatureLine",
            fontName="Helvetica",
            fontSize=10,
            leading=12,
            textColor=BODY_GREY,
        ),
        "signature_label": ParagraphStyle(
            "SignatureLabel",
            fontName="Helvetica",
            fontSize=9,
            leading=11,
            textColor=BODY_GREY,
        ),
        "signature_date_label": ParagraphStyle(
            "SignatureDateLabel",
            fontName="Helvetica-Bold",
            fontSize=10,
            leading=12,
            textColor=BODY_GREY,
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
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self._draw_footer()
            super().showPage()
        super().save()

    def _draw_footer(self) -> None:
        footer_y = 0.38 * inch
        self.setFillColor(BODY_GREY)
        self.setFont("Helvetica", 9)
        self.drawString(PAGE_MARGIN, footer_y, str(self._pageNumber))

        logo_path = _resolved_logo_path()
        if logo_path is None:
            return

        try:
            reader = ImageReader(str(logo_path))
            width, height = reader.getSize()
            logo_width = 40
            logo_height = logo_width * height / width
            self.drawImage(
                reader,
                PAGE_SIZE[0] - PAGE_MARGIN - logo_width,
                footer_y - 4,
                width=logo_width,
                height=logo_height,
                preserveAspectRatio=True,
                mask="auto",
            )
        except Exception:
            return


def _logo_image(width: float) -> Image | None:
    logo_path = _resolved_logo_path()
    if logo_path is None:
        return None

    try:
        reader = ImageReader(str(logo_path))
        image_width, image_height = reader.getSize()
        height = width * image_height / image_width
        return Image(str(logo_path), width=width, height=height)
    except Exception:
        return None


def _resolved_logo_path() -> Path | None:
    if LOGO_PATH.exists():
        return LOGO_PATH
    if APP_TEMPLATE_LOGO_PATH.exists():
        return APP_TEMPLATE_LOGO_PATH
    return None


def _format_change_order_title(change_order: ChangeOrder) -> str:
    if change_order.co_number:
        return f"CHANGE ORDER #{_co_number(change_order.co_number)}".upper()
    return "CHANGE ORDER DRAFT"


def _co_number(value: str) -> str:
    cleaned = value.strip()
    if cleaned.startswith("#"):
        cleaned = cleaned[1:].strip()

    generated_match = re.fullmatch(r"CO-\d{8}-(\d+)", cleaned, flags=re.IGNORECASE)
    if generated_match:
        return str(int(generated_match.group(1)))

    if cleaned.lower().startswith("co-"):
        return cleaned[3:]
    return cleaned


def _format_date(value: date | None) -> str:
    if value is None:
        return ""
    return value.strftime("%B %-d, %Y")


def _format_amount(value: Decimal, credit: bool = False) -> str:
    if credit:
        return f"($ {value:>8,.2f})"
    return f"$ {value:>8,.2f}"


def _format_total(value: Decimal) -> str:
    return f"$ {value:>8,.2f}"


def _escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\n", "<br/>")
    )
