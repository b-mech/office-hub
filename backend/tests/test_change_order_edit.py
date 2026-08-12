from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.routers.change_orders import ChangeOrderLineItem
from app.routers.change_orders import ChangeOrderUpdate
from app.routers.change_orders import _ensure_change_order_editable


def _line_item(
    description: str = "Upgrade",
    amount: str = "100.00",
    is_credit: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        description=description,
        amount=Decimal(amount),
        is_credit=is_credit,
    )


def _change_order(
    *,
    status: str = "draft",
    archived: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        status=status,
        archived_at=datetime.now() if archived else None,
        line_items=[_line_item()],
    )


def test_update_schema_accepts_all_editable_form_fields() -> None:
    update = ChangeOrderUpdate.model_validate(
        {
            "address": "12 Oak Street",
            "client_name": "Alex Client",
            "customer_email": "alex@example.com",
            "co_number": "CO-42",
            "date": "2026-07-30",
            "payment_method": "add_to_mortgage",
            "notes": "Confirmed",
            "line_items": [
                {"description": "Upgrade", "amount": "125.50", "is_credit": False},
            ],
        }
    )

    assert update.co_number == "CO-42"
    assert update.date == "2026-07-30"
    assert update.payment_method == "add_to_mortgage"
    assert update.line_items == [
        ChangeOrderLineItem(
            description="Upgrade",
            amount=Decimal("125.50"),
            is_credit=False,
        )
    ]


@pytest.mark.parametrize("status", ["signed", "complete"])
def test_signed_and_complete_change_orders_are_immutable(status: str) -> None:
    with pytest.raises(HTTPException, match="immutable") as exc_info:
        _ensure_change_order_editable(
            _change_order(status=status),
            updates={"notes": "changed"},
            incoming_line_items=None,
        )

    assert exc_info.value.status_code == 409


def test_archived_change_orders_are_immutable() -> None:
    with pytest.raises(HTTPException, match="Archived") as exc_info:
        _ensure_change_order_editable(
            _change_order(archived=True),
            updates={"notes": "changed"},
            incoming_line_items=None,
        )

    assert exc_info.value.status_code == 409


def test_sent_change_order_rejects_changed_line_items() -> None:
    with pytest.raises(HTTPException, match="Void and resend") as exc_info:
        _ensure_change_order_editable(
            _change_order(status="sent"),
            updates={"line_items": [{}]},
            incoming_line_items=[
                ChangeOrderLineItem(
                    description="Different upgrade",
                    amount=Decimal("100.00"),
                    is_credit=False,
                )
            ],
        )

    assert exc_info.value.status_code == 409


def test_sent_change_order_accepts_unchanged_line_items() -> None:
    _ensure_change_order_editable(
        _change_order(status="sent"),
        updates={"line_items": [{}]},
        incoming_line_items=[
            ChangeOrderLineItem(
                description=" Upgrade ",
                amount=Decimal("-100.00"),
                is_credit=False,
            )
        ],
    )


def test_draft_with_box_file_remains_editable() -> None:
    change_order = _change_order(status="draft")
    change_order.box_file_id = "box-file-123"

    _ensure_change_order_editable(
        change_order,
        updates={"notes": "updated after creating the PDF"},
        incoming_line_items=None,
    )
