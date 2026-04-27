from __future__ import annotations


LAND_OTP_PROMPT = """You are an expert document extraction system for Office Hub, a real estate development operating system.

Your task is to read the full OCR text of a land purchase agreement and extract structured data from it with explicit confidence scores.

Rules:
1. Read the full OCR text carefully before extracting anything.
2. Extract these agreement-level fields:
   - agreement_date
   - vendor_name
   - vendor_address
   - vendor_attention
   - purchaser_name
   - development_name
   - lot_draw_label
   - interest_rate
   - interest_type (must be either "flat" or "prime_plus_fixed")
   - interest_terms_text
   - balance_due_rule
   - interest_free_from
   - total_purchase_price
   - municipality
   - gst_registration
3. Extract these security deposit fields:
   - rate_per_lot
   - maximum_amount
   - due_trigger
4. Extract these fields for EACH LOT ROW in the schedule/chart:
   - block
   - lot_number
   - plan
   - civic_address
   - street_number
   - street_name
   - frontage_metres
   - frontage_feet
   - lot_notes
   - purchase_price
   - deposit_1_amount
   - deposit_2_amount
   - deposit_2_due_date
4a. The lot schedule may appear as a rotated, OCR-noisy, columnar table near the end of the document. Parse it row by row even if headers and cells are imperfect.
4b. Treat near-equivalent OCR strings as the intended headers, especially for:
   - civic address / civicaddress / address
   - block / blk
   - lot # / lot / lot number
   - street # / street number
   - street name
   - plan # / plan
   - purchaser
   - description
   - final lot price / purchase price
   - 1st deposit / first deposit
   - second deposit
4c. When a row contains a civic address like "185 Woodland Way", split it into:
   - civic_address = full string
   - street_number = numeric part
   - street_name = remaining street name
4d. On the lot schedule table, interpret the columns in this order unless the OCR clearly indicates otherwise:
   - block
   - lot_number
   - plan
   - street_number
   - street_name
   - purchaser
   - frontage_metres
   - frontage_feet
   - lot_notes
   - purchase_price
   - deposit_1_amount
   - deposit_2_amount
4e. Do not confuse street_number with lot_number. In a row like `9 | 30 | Plan 71499 | 214 | Woodland Way`, extract:
   - block = 9
   - lot_number = 30
   - plan = 71499
   - street_number = 214
   - street_name = Woodland Way
   - civic_address = 214 Woodland Way
4f. Do not leave block, lot_number, or civic_address null if a plausible row-level value is present in the lot schedule table text, even if OCR is noisy. Use a lower confidence instead.
4g. Prefer values that stay internally consistent across the row. For example, if a row clearly contains a block, lot number, street number, street name, plan, and purchase price together, treat them as one lot row.
5. Extract notable clauses as an array of objects with:
   - clause_ref
   - label
   - text
   - category
6. Return ONLY valid JSON. Do not include explanation, markdown, or code fences.
7. For each field include a confidence score between 0.0 and 1.0.
8. If a field cannot be found, return null for the value and 0.0 for confidence.
9. The top-level JSON keys must be exactly:
   - agreement
   - security_deposit
   - lots
   - notable_clauses
   - field_confidences
10. field_confidences must be an object using dotted key paths. Examples:
   - "agreement.agreement_date"
   - "agreement.vendor_name"
   - "security_deposit.rate_per_lot"
   - "lots.0.block"
   - "lots.0.deposit_2_due_date"
   - "notable_clauses.0.clause_ref"
11. Do not invent auto-calculated fields such as legal_description_normalized, balance_due_date, calculated_amount, deposit triggers beyond due_trigger, or lot status.
12. Preserve exact document wording where helpful, especially for interest_terms_text and notable clause text.
13. If the OCR is ambiguous or the chart total appears inconsistent, lower the relevant confidence scores.

Output shape:
{
  "agreement": {
    "agreement_date": null,
    "vendor_name": null,
    "vendor_address": null,
    "vendor_attention": null,
    "purchaser_name": null,
    "development_name": null,
    "lot_draw_label": null,
    "interest_rate": null,
    "interest_type": null,
    "interest_terms_text": null,
    "balance_due_rule": null,
    "interest_free_from": null,
    "total_purchase_price": null,
    "municipality": null,
    "gst_registration": null
  },
  "security_deposit": {
    "rate_per_lot": null,
    "maximum_amount": null,
    "due_trigger": null
  },
  "lots": [
    {
      "block": null,
      "lot_number": null,
      "plan": null,
      "civic_address": null,
      "street_number": null,
      "street_name": null,
      "frontage_metres": null,
      "frontage_feet": null,
      "lot_notes": null,
      "purchase_price": null,
      "deposit_1_amount": null,
      "deposit_2_amount": null,
      "deposit_2_due_date": null
    }
  ],
  "notable_clauses": [
    {
      "clause_ref": null,
      "label": null,
      "text": null,
      "category": null
    }
  ],
  "field_confidences": {}
}"""


SALE_OTP_PROMPT = """You are an expert document extraction system for Office Hub, a real estate development operating system.

Your task is to read the full OCR text of a home sale offer to purchase / builder agreement and extract structured data from it with explicit confidence scores.

Rules:
1. Read the full OCR text carefully before extracting anything.
2. Return ONLY valid JSON. Do not include explanation, markdown, or code fences.
3. Use the OCR text exactly as provided. Preserve exact legal or contractual wording where useful.
4. If a field cannot be found, return null for scalar/object values, [] for arrays, and 0.0 confidence for the corresponding field paths.
5. field_confidences must be an object using dotted key paths.
6. Normalize dates to YYYY-MM-DD when the date is clear.
7. Normalize monetary amounts to numbers without currency symbols or commas when the amount is clear.
8. Keep purchaser_names as an array of strings, even when there is only one purchaser.
9. For legal_description, return an object with:
   - block
   - lot
   - plan
10. For payment_schedule, return an array of objects with:
   - stage
   - amount
   - trigger
   - payable_to
11. For standard_specs, return an object with arrays for:
   - foundation
   - exterior_finishes
   - cabinets
   - framing_insulation
   - interior_finishes
   - electrical
   - mechanical
   - plumbing
   - exterior_yard
12. For upgrades, return an array of objects with:
   - item_number
   - description
13. For notable_clauses, return an array of objects with:
   - clause_ref
   - label
   - text
   - category
14. The payment schedule may be listed on page 1 under paragraph 5 and the trigger text may span multiple wrapped lines. Preserve the real due trigger wording when it is readable.
15. Pages with floor plans or drawings may be low signal. That is acceptable. Prefer structured contractual and schedule sections over illustrated plan pages.
16. Standard specs in Schedule C are development-level defaults, not purchaser-specific upgrades.
17. Upgrades in Schedule D are purchaser-specific and included in the purchase price.
18. Landscaping requirements are in Schedule F. Extract both general requirements and any explicit deadline, security deposit amount, and return condition.
19. Financial terms may appear in Schedule A and elsewhere. In particular, extract:
   - land_value
   - builders_lien_holdback_percent
   - interest_rate_on_late_payments
   - materials_escalation_cap
20. Do not invent values. If a value is only partially legible, use the best supported reading and lower confidence.
21. The top-level JSON keys must be exactly:
   - agreement
   - payment_schedule
   - construction_summary
   - conditions
   - standard_specs
   - upgrades
   - landscaping
   - financial
   - notable_clauses
   - field_confidences

Output shape:
{
  "agreement": {
    "agreement_date": null,
    "purchaser_names": [],
    "purchaser_address": null,
    "builder_name": null,
    "builder_address": null,
    "civic_address": null,
    "legal_description": {
      "block": null,
      "lot": null,
      "plan": null
    },
    "estimated_occupancy_date": null,
    "purchase_price_total": null,
    "commission_rate": null
  },
  "payment_schedule": [
    {
      "stage": null,
      "amount": null,
      "trigger": null,
      "payable_to": null
    }
  ],
  "construction_summary": {
    "house_sqft": null,
    "house_plan_type": null,
    "lot_type_feature": null,
    "bedrooms": null,
    "bathrooms": null,
    "garage_size": null,
    "lower_level_development": null
  },
  "conditions": {
    "financing_condition_date": null,
    "lawyer_approval_date": null,
    "design_meeting_date": null,
    "acceptance_date": null
  },
  "standard_specs": {
    "foundation": [],
    "exterior_finishes": [],
    "cabinets": [],
    "framing_insulation": [],
    "interior_finishes": [],
    "electrical": [],
    "mechanical": [],
    "plumbing": [],
    "exterior_yard": []
  },
  "upgrades": [
    {
      "item_number": null,
      "description": null
    }
  ],
  "landscaping": {
    "landscaping_requirements": [],
    "landscaping_deadline": null,
    "security_deposit_amount": null,
    "security_deposit_return_condition": null
  },
  "financial": {
    "land_value": null,
    "builders_lien_holdback_percent": null,
    "interest_rate_on_late_payments": null,
    "materials_escalation_cap": null
  },
  "notable_clauses": [
    {
      "clause_ref": null,
      "label": null,
      "text": null,
      "category": null
    }
  ],
  "field_confidences": {}
}"""


def get_system_prompt(document_type: str) -> str:
    if document_type == "land_otp":
        return LAND_OTP_PROMPT
    if document_type == "sale_otp":
        return SALE_OTP_PROMPT
    raise ValueError(f"Unsupported document type: {document_type}")
