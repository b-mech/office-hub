from __future__ import annotations

from app.financing.engines import pro


ENGINES = {
    "PRO": pro,
}


def get_engine(lender: str):
    return ENGINES.get(lender.upper())
