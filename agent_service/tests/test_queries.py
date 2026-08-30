"""Money formatting and the missing-data contract."""

import pytest

from db.queries import get_spending_by_category, money


@pytest.mark.parametrize("value,expected", [
    (5128.69, "R5,128.69"),
    (0, "R0.00"),
    (None, "R0.00"),
    (1234567.5, "R1,234,567.50"),
    (0.005, "R0.01"),
])
def test_money_formats_as_rand(value, expected):
    assert money(value) == expected


def test_missing_period_reports_no_data_and_omits_the_amount(db):
    """A month with no statement must not look like a month of zero spending.

    Returning 0.0 here made the agent answer "You spent R0.00 on Groceries in
    January 2026" for a month that was never imported.
    """
    result = get_spending_by_category(db, "Groceries", 1, 2026)
    assert result["has_data"] is False
    assert "total_spent" not in result
    assert "not zero" in result["note"]
