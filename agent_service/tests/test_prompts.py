"""Contract tests for the chat system prompt.

These assert that rules we added in response to real misbehaviour are still
present. They cannot prove the model obeys them, but they stop a rule being
deleted or reworded away by accident.
"""

import pytest

from agent.prompts import NL_TO_SQL_PROMPT, TOOL_SYSTEM_PROMPT


@pytest.fixture
def rendered():
    """The chat system prompt as the agent actually sends it."""
    return TOOL_SYSTEM_PROMPT.format(
        month=3, year=2026, today="30 August 2026",
        periods="03/2026, 02/2026",
        categories="Groceries, Food & Takeout, Utilities",
    )


def test_carries_todays_date_and_the_viewed_month(rendered):
    assert "30 August 2026" in rendered
    assert "03/2026" in rendered


def test_relative_periods_resolve_against_today(rendered):
    """'this month' in August must mean August, not whatever month is on screen.

    The prompt once said to resolve against the dashboard selection instead,
    so 'how much did I spend this month?' answered about March in August.
    """
    assert "TODAY'S DATE" in rendered
    assert "never against the dashboard" in rendered.lower()


def test_forbids_stating_amounts_that_did_not_come_from_a_tool(rendered):
    """Told a period had no data, the model invented a breakdown for another
    month that summed correctly but used figures it had never retrieved."""
    assert "NEVER state an amount that did not come from a tool result" in rendered


def test_lists_the_real_categories(rendered):
    """Without them the model guesses 'Electricity' and burns a round trip."""
    assert "Groceries, Food & Takeout, Utilities" in rendered


def test_out_of_scope_does_not_route_to_sql(rendered):
    """Weather once cost 3 API calls and 30s via the SQL fallback."""
    assert "Do NOT reply NEED_SQL" in rendered


def test_sql_prompt_receives_real_category_names():
    sql = NL_TO_SQL_PROMPT.format(schema="...", question="?", categories="Groceries, Utilities")
    assert "Groceries, Utilities" in sql
    assert "Never invent a category name" in sql
