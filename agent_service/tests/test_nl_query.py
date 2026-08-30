"""Guardrails on the NL -> SQL fallback — the only place the LLM writes SQL."""

import pytest

from agent.nl_query import _ensure_limit, _rows_to_dicts, _strip_fences, _validate


@pytest.mark.parametrize("sql", [
    "SELECT * FROM transaction",
    "  select id from category  ",
    "SELECT SUM(amount) FROM transaction WHERE direction = 'DR'",
])
def test_accepts_plain_selects(sql):
    assert _validate(sql) is True


@pytest.mark.parametrize("sql", [
    "DROP TABLE transaction",
    "DELETE FROM transaction WHERE id = 1",
    "UPDATE transaction SET amount = 0",
    "INSERT INTO category VALUES (1, 'x', 'y', 'z')",
    "ALTER TABLE transaction ADD COLUMN x INT",
    "CREATE TABLE evil (id INT)",
    "SELECT 1; DROP TABLE transaction",   # piggybacked statement
    "WITH x AS (SELECT 1) SELECT * FROM x",  # must START with SELECT
])
def test_rejects_anything_that_is_not_a_plain_select(sql):
    assert _validate(sql) is False


def test_limit_is_forced_when_absent():
    assert "LIMIT" in _ensure_limit("SELECT * FROM transaction")


def test_existing_limit_is_respected():
    assert _ensure_limit("SELECT * FROM transaction LIMIT 5").count("LIMIT") == 1


def test_strips_markdown_fences():
    assert _strip_fences("```sql\nSELECT 1\n```") == "SELECT 1"


def test_money_columns_become_rand_strings():
    """Raw SQL rows are formatted before the model sees them, or it says $."""
    class Row:
        def __init__(self, m): self._mapping = m
    out = _rows_to_dicts([Row({"merchant": "SPAR", "total_spent": 1234.5, "transaction_count": 3})])
    assert out[0]["total_spent"] == "R1,234.50"
    assert out[0]["transaction_count"] == 3        # counts are not money
    assert out[0]["merchant"] == "SPAR"
