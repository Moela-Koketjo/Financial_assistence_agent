"""What the chat model is allowed to see in a tool result."""

from agent.tools import _describe_periods, _fmt_args, _for_model


def test_money_floats_are_replaced_by_rand_strings():
    """The model renders a bare float as dollars, so it never receives one."""
    out = _for_model({
        "category": "Groceries",
        "total_spent": 5128.69,
        "total_spent_display": "R5,128.69",
        "transaction_count": 13,
    })
    assert out["total_spent"] == "R5,128.69"
    assert "total_spent_display" not in out       # the duplicate is dropped
    assert out["transaction_count"] == 13         # counts stay numeric


def test_nested_lists_are_converted_too():
    rows = [{"merchant": "SPAR", "total_spent": 1.5, "total_spent_display": "R1.50"}]
    assert _for_model(rows)[0]["total_spent"] == "R1.50"


def test_fields_without_a_display_pair_are_untouched():
    assert _for_model({"month": 2, "year": 2026}) == {"month": 2, "year": 2026}


def test_has_data_false_carries_no_amount():
    """A period with no statement must not hand the model a zero to quote."""
    result = _for_model({"category": "Groceries", "has_data": False,
                         "note": "No statement imported for 01/2026."})
    assert result["has_data"] is False
    assert "total_spent" not in result


def test_periods_are_described_for_the_prompt():
    assert _describe_periods([]) == "none — no statements have been imported yet"
    got = _describe_periods([
        {"statement_month": 3, "statement_year": 2026},
        {"statement_month": 2, "statement_year": 2026},
    ])
    assert got == "03/2026, 02/2026"


def test_tool_arguments_are_logged_sorted_and_readable():
    assert _fmt_args({"year": 2026, "month": 2}) == "month=2, year=2026"
