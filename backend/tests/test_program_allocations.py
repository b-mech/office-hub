from decimal import Decimal

import pytest

from app.services.program_allocations import derive_basis


def test_derive_basis_uses_lesser_appraisal_and_estimate() -> None:
    basis, source = derive_basis(
        appraisal_value=Decimal("700000"),
        estimated_sale_price=Decimal("680000"),
        explicit_basis_value=Decimal("999999"),
    )

    assert basis == Decimal("680000.00")
    assert source == "lesser_of_appraisal_and_estimated_sale_price"


def test_derive_basis_uses_single_provenance_value() -> None:
    basis, source = derive_basis(
        appraisal_value=Decimal("562374"),
        estimated_sale_price=None,
        explicit_basis_value=None,
    )

    assert basis == Decimal("562374.00")
    assert source == "appraisal"


def test_derive_basis_accepts_explicit_historical_value() -> None:
    basis, source = derive_basis(
        appraisal_value=None,
        estimated_sale_price=None,
        explicit_basis_value=Decimal("107900"),
    )

    assert basis == Decimal("107900.00")
    assert source == "explicit_historical"


def test_derive_basis_requires_a_value() -> None:
    with pytest.raises(ValueError, match="Provide appraisal_value"):
        derive_basis(
            appraisal_value=None,
            estimated_sale_price=None,
            explicit_basis_value=None,
        )
