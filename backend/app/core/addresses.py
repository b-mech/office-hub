from __future__ import annotations

import re
from dataclasses import dataclass


MUNICIPALITIES = (
    "ILE DES CHENES",
    "WEST ST PAUL",
    "LANDMARK",
    "OAKBANK",
    "NIVERVILLE",
    "WINNIPEG",
)

SUFFIXES = {
    "STREET": "ST",
    "ST": "ST",
    "DRIVE": "DR",
    "DR": "DR",
    "AVENUE": "AVE",
    "AVE": "AVE",
    "WAY": "WAY",
    "ROW": "ROW",
    "LANE": "LANE",
    "LN": "LANE",
    "CRESCENT": "CRES",
    "CRESENT": "CRES",
    "CRES": "CRES",
    "ROAD": "RD",
    "RD": "RD",
    "BOULEVARD": "BLVD",
    "BLVD": "BLVD",
}

STREET_MUNICIPALITY_HINTS = {
    "CHAMPAGNE ST": "WINNIPEG",
    "CARDINAL WAY": "LANDMARK",
    "OAK MEADOW DR": "OAKBANK",
    "WOODLAND WAY": "WEST ST PAUL",
    "GLENEAGLES ST": "NIVERVILLE",
    "CHAMPAGNE ST": "WINNIPEG",
    "RAMONA GALLOS WAY": "WINNIPEG",
    "ROSYBLOOM LANE": "ILE DES CHENES",
}

STREET_SUFFIX_HINTS = {
    "BLOSSOM": "WAY",
    "CHAMPAGNE": "ST",
    "GRANDE POINTE MEADOWS": "BLVD",
    "RAMONA GALLOS": "WAY",
}

STREET_NAME_ALIASES = {
    "LYNE": "LYNNE",
}

BORROWER_PREFIXES = (
    r"CONNECTION\s+HOMES\s+INC\s*-\s*",
    r"CONNECTION\s+HOMES\s*-\s*",
    r"CONNECTION\s+HOMES\s+INC\s+PROMISSORY\s+NOTE\s*",
    r"CONNECTION\s+HOMES\s+PROMISSORY\s+NOTE\s*",
    r"CONNECTION\s+HOMES\s+INC\.?\s*",
)

ANNOTATION_PATTERNS = (
    r"\bSPEC\b",
    r"\bSHOW\s*HOME\b",
    r"\bSHOWHOME\b",
    r"\bFULL\s+\d{4}\b",
    r"\bFALL\s+\d{4}\b",
    r"\bPROMISSORY\s+NOTE\b",
    r"\bON\s+HOLD\b",
    r"\bBOUGHT\s+FROM\s+GS\s+HOMES\b",
)


@dataclass(frozen=True)
class NormalizedAddress:
    canonical_key: str
    street_number: str | None
    street_name: str | None
    street_suffix: str | None
    municipality: str | None
    province: str | None
    annotations: list[str]
    raw: str


def normalize_address(raw: str) -> NormalizedAddress:
    value = raw.strip()
    cleaned = _clean_base(value)
    annotations, cleaned = _strip_annotations(cleaned)
    municipality, cleaned = _strip_municipality(cleaned)
    province = "MB" if re.search(r"\bMB\b", cleaned) else None
    cleaned = re.sub(r"\bMB\b", " ", cleaned)
    cleaned = _squash(cleaned)
    cleaned = _reorder_street_first_number(cleaned)

    if _is_development(cleaned):
        key = f"DEV:{cleaned}"
        return NormalizedAddress(key, None, None, None, municipality, province, annotations, raw)

    street_number, street_name, street_suffix = _street_parts(cleaned)
    if street_name and street_suffix is None:
        street_suffix = STREET_SUFFIX_HINTS.get(street_name)
    if municipality is None and street_name and street_suffix:
        municipality = STREET_MUNICIPALITY_HINTS.get(f"{street_name} {street_suffix}")
    key_body = " ".join(part for part in (street_number, street_name, street_suffix, municipality) if part)
    canonical_key = _squash(key_body or cleaned)
    return NormalizedAddress(
        canonical_key=canonical_key,
        street_number=street_number,
        street_name=street_name,
        street_suffix=street_suffix,
        municipality=municipality,
        province=province,
        annotations=annotations,
        raw=raw,
    )


def _clean_base(value: str) -> str:
    cleaned = value.casefold().upper()
    cleaned = re.sub(r"[–—−]", "-", cleaned)
    for pattern in BORROWER_PREFIXES:
        cleaned = re.sub(rf"^{pattern}", "", cleaned)
    cleaned = re.sub(r"[()]", " ", cleaned)
    cleaned = re.sub(r"[.,:;]", " ", cleaned)
    cleaned = re.sub(r"\s*/\s*", "-", cleaned)
    cleaned = re.sub(r"\s+-\s+", " - ", cleaned)
    return _squash(cleaned)


def _strip_annotations(value: str) -> tuple[list[str], str]:
    annotations: list[str] = []
    cleaned = value
    for pattern in ANNOTATION_PATTERNS:
        match = re.search(pattern, cleaned)
        if match:
            annotations.append(_squash(match.group(0)))
            cleaned = re.sub(pattern, " ", cleaned)
    cleaned = re.sub(r"\s*-\s*$", " ", cleaned)
    return annotations, _squash(cleaned)


def _strip_municipality(value: str) -> tuple[str | None, str]:
    municipality = None
    cleaned = value
    for candidate in MUNICIPALITIES:
        if re.search(rf"\b{re.escape(candidate)}\b", cleaned):
            municipality = candidate
            cleaned = re.sub(rf"\b{re.escape(candidate)}\b", " ", cleaned)
            break
    return municipality, _squash(cleaned)


def _street_parts(value: str) -> tuple[str | None, str | None, str | None]:
    tokens = value.split()
    if not tokens:
        return None, None, None

    number_tokens: list[str] = []
    while tokens and re.fullmatch(r"\d+(?:-\d+)*", tokens[0]):
        number_tokens.append(tokens.pop(0))
    street_number = "-".join(number_tokens) if number_tokens else None

    street_suffix = None
    if tokens and tokens[-1] in SUFFIXES:
        street_suffix = SUFFIXES[tokens.pop()]

    street_name = _normalize_street_name(" ".join(tokens)) if tokens else None
    return street_number, street_name, street_suffix


def _reorder_street_first_number(value: str) -> str:
    """Canonicalize inventory-style addresses such as ``Woodland Way, 49``."""
    match = re.fullmatch(r"(.+?)\s+(\d+[A-Z]?(?:-\d+[A-Z]?)*)", value)
    if match is None:
        return value
    street_text, street_number = match.groups()
    tokens = street_text.split()
    if not tokens or "LOT" in tokens:
        return value
    has_suffix = tokens[-1] in SUFFIXES
    normalized_name = _normalize_street_name(
        " ".join(tokens[:-1] if has_suffix else tokens)
    )
    if not has_suffix and normalized_name not in STREET_SUFFIX_HINTS:
        return value
    return f"{street_number} {street_text}"


def _normalize_street_name(value: str) -> str:
    tokens = value.split()
    return " ".join(STREET_NAME_ALIASES.get(token, token) for token in tokens)


def _is_development(value: str) -> bool:
    return not re.match(r"^\d", value) or bool(re.search(r"\b(DEV|DEPOSIT|DEVELOPMENT|PROMISSORY NOTE)\b", value))


def _squash(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()
