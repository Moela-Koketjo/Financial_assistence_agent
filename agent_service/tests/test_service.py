"""Statement period inference — which month a statement belongs to."""

from api.service import _infer_period, statement_period_of


def _dates(*pairs):
    return [{"date": d} for d, n in pairs for _ in range(n)]


def test_uses_the_majority_month_not_the_first_row():
    """A statement running 27 Jan - 27 Feb belongs to February, not January.

    Taking the first transaction's month would file the whole statement wrong.
    """
    txs = _dates(("27 Jan 2026", 3), ("15 Feb 2026", 40))
    assert _infer_period(txs) == (2, 2026)


def test_accepts_iso_dates_too():
    """The prompt asks for '09 Feb 2026' but the model sometimes returns ISO."""
    assert _infer_period([{"date": "2026-02-09"}]) == (2, 2026)


def test_ignores_unparseable_dates():
    txs = [{"date": "garbage"}, {"date": "05 Mar 2026"}, {"date": ""}]
    assert _infer_period(txs) == (3, 2026)


def test_returns_none_when_nothing_parses():
    assert _infer_period([{"date": "???"}, {}]) is None


def test_year_boundary_is_handled():
    txs = _dates(("28 Dec 2025", 2), ("10 Jan 2026", 30))
    assert _infer_period(txs) == (1, 2026)


def test_statement_period_of_parses_iso_only():
    assert statement_period_of(None, "2026-02-15") == (2, 2026)
    assert statement_period_of(None, "not a date") is None
