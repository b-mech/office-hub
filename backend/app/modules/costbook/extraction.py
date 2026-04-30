"""
costbook/extraction.py
Claude-powered invoice extraction.
Accepts a PDF or image (bytes), calls the Anthropic API,
returns a structured InvoiceExtractionResult.
"""
import base64
import json
import logging
from typing import Optional

import anthropic

from app.modules.costbook.schemas import InvoiceExtractionResult, InvoiceLineItem

logger = logging.getLogger(__name__)

# Full PO category list injected into the system prompt so Claude can suggest
# which budget line an invoice belongs to.
PO_CATEGORIES_SUMMARY = """
PERMITS & FEES: 1010 Building Permits, 1020 New Home Warranty, 1030 Construction Insurance, 1040 Property Tax
ARCHITECTURAL & ENGINEERING: 1110 Drafting, 1120 Engineer, 1130 Surveys, 1140 Estimating/Budgeting
SITE WORK: 1210 Fill Dirt, 1220 Toilet, 1230 Fence, 1240 Garbage, 1250 Tree Removal
DEMOLITION: 1310 Demolition, 1320 Asbestos Testing
UTILITY CONNECTIONS: 1410 Water and Sewer, 1420 Manitoba Hydro, 1430 Water Bill
EXCAVATION: 2010 Excavation & Backfill, 2020 Earth Hauling
FOUNDATION & CONCRETE: 2110 Foundation Materials, 2120 Concrete, 2130 Gravel/Sand, 2140 Rebar Package, 2150 Labor Piles/Walls, 2160 Concrete Pump, 2170 Pile Driller, 2180 Steel Beam/Craning, 2190 Labor B Slab, 2200 Labor G Slab, 2210 Labor Front Step, 2220 Rough Grade, 2230 Foundation Extras
FRAMING: 3110 Framing Materials, 3120 Trusses, 3121 Craning Trusses, 3130 Framing Labor, 3140 Stairs, 3150 Roofing Labor, 3160 Framing Extras
PLUMBING: 3210 Plumbing
ELECTRICAL: 3310 Electrical, 3320 Data, 3330 Central Vac, 3340 Client Extras/Heaters
HVAC: 3810 HVAC, 3820 AC
WINDOWS: 4510 Windows, 4520 Window Extras, 4530 Window Wells
GARAGE DOORS: 4610 Garage Doors/Openers, 4620 Garage Door Extras
EXTERIOR FINISHING: 4805 Metal Cladding, 4810 Soffit/Fascia/Gutters, 4820 Conventional Stucco, 4830 Acrylic Stucco, 4840 Stone, 4850 Window Trim, 4860 Siding Labor, 4861 Siding Material, 4870 Front Step Railing
INSULATION & DRYWALL: 5010 Supply & Install Insulation/Drywall, 5020 Spray Foam Joist
FLOORING: 5110 Base Flooring, 5120 Extra Flooring
INTERIOR FINISHING: 5210 Painting, 5220 Interior Finishing/Hardware, 5230 Closet Shelving, 5240 Interior Trim/Door Labor, 5250 Mirrors, 5260 Shower Doors, 5270 Interior Railing, 5280 Tile Backsplash, 5290 Designer/Staging, 5310 Fireplace, 5320 Tile Shower
CABINETRY: 5402 Kitchen & Bath Cabinets, 5404 Counters, 5406 Labor, 5408 Extras
APPLIANCES: 5502 Appliance Installation, 5504 Kitchen & Laundry Appliances, 5506 Appliance Extras
PLUMBING FIXTURES: 5610 Tub-Shower, 5620 Plumbing Fixtures, 5621 Fixture Extras
ELECTRICAL FIXTURES: 5710 Finish Electrical Fixtures, 5720 Fixture Extras
BUILDING CLEAN-UP: 6010 Final Grade, 6020 Building Clean-up, 6030 Duct Cleaning
LANDSCAPING: 6110 Top Soil, 6120 Trees, 6130 Sod, 6140 Seed, 6150 Deck/Patio, 6160 Fence, 6180 Driveway
OTHER: 6200 Contingency, 6330 Land, 6340 Land Holding Costs, 6350 Realtor, 6360 Legal, 6800 Warranty, 6850 Other
"""

SYSTEM_PROMPT = f"""You are an invoice extraction assistant for a residential home builder.
Extract structured data from the provided invoice image or PDF.

You must respond ONLY with a valid JSON object — no preamble, no markdown, no explanation.

Use this PO category list to suggest which budget line the invoice belongs to:
{PO_CATEGORIES_SUMMARY}

Return this exact structure:
{{
  "vendor_name": "string or null",
  "invoice_number": "string or null",
  "invoice_date": "YYYY-MM-DD or null",
  "amount_total": number or null,
  "line_items": [
    {{
      "description": "string",
      "quantity": number or null,
      "unit_price": number or null,
      "amount": number
    }}
  ],
  "suggested_po_number": "4-digit PO number string or null",
  "confidence": 0.0 to 1.0
}}

Confidence guide:
- 0.9–1.0: All fields clearly visible, totals match line items
- 0.7–0.9: Most fields visible, minor ambiguity
- 0.5–0.7: Partial data, some fields inferred
- Below 0.5: Poor quality scan, significant uncertainty
"""


def _encode_file(file_bytes: bytes, media_type: str) -> str:
    return base64.standard_b64encode(file_bytes).decode("utf-8")


def _get_media_type(filename: str) -> str:
    ext = filename.lower().split(".")[-1]
    mapping = {
        "pdf":  "application/pdf",
        "png":  "image/png",
        "jpg":  "image/jpeg",
        "jpeg": "image/jpeg",
        "webp": "image/webp",
    }
    return mapping.get(ext, "application/octet-stream")


async def extract_invoice(
    file_bytes: bytes,
    filename: str,
    client: Optional[anthropic.AsyncAnthropic] = None,
) -> InvoiceExtractionResult:
    """
    Send invoice file to Claude and return structured extraction result.
    Raises ValueError if extraction fails or response cannot be parsed.
    """
    if client is None:
        client = anthropic.AsyncAnthropic()

    media_type = _get_media_type(filename)
    encoded    = _encode_file(file_bytes, media_type)

    if media_type == "application/pdf":
        content_block = {
            "type": "document",
            "source": {
                "type":       "base64",
                "media_type": media_type,
                "data":       encoded,
            },
        }
    else:
        content_block = {
            "type": "image",
            "source": {
                "type":       "base64",
                "media_type": media_type,
                "data":       encoded,
            },
        }

    response = await client.messages.create(
        model="claude-opus-4-5",
        max_tokens=1500,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": [
                    content_block,
                    {"type": "text", "text": "Extract the invoice data from this document."},
                ],
            }
        ],
    )

    raw_text = response.content[0].text.strip()

    # Strip markdown fences if present
    if raw_text.startswith("```"):
        raw_text = raw_text.split("\n", 1)[-1]
        raw_text = raw_text.rsplit("```", 1)[0].strip()

    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as e:
        logger.error("Invoice extraction JSON parse error: %s\nRaw: %s", e, raw_text)
        raise ValueError(f"Claude returned invalid JSON: {e}") from e

    line_items = [
        InvoiceLineItem(
            description=item.get("description", ""),
            quantity=item.get("quantity"),
            unit_price=item.get("unit_price"),
            amount=item.get("amount", 0.0),
        )
        for item in data.get("line_items", [])
    ]

    return InvoiceExtractionResult(
        vendor_name=data.get("vendor_name"),
        invoice_number=data.get("invoice_number"),
        invoice_date=data.get("invoice_date"),
        amount_total=data.get("amount_total"),
        line_items=line_items,
        suggested_po_number=data.get("suggested_po_number"),
        confidence=float(data.get("confidence", 0.5)),
    )
