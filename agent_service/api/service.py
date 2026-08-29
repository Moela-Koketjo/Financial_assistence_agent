"""Statement import orchestration — parse, infer period, categorize, persist."""

import logging
from collections import Counter
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from agent.categorizer import categorize
from agent.parser import parse
from db.queries import (
    get_statement_by_month_year,
    insert_statement,
    insert_transaction,
    rebuild_monthly_summary,
)

logger = logging.getLogger(__name__)


class DuplicateStatementError(Exception):
    """Raised when a statement for the same month/year already exists."""


class ParseError(Exception):
    """Raised when the statement could not be parsed into transactions."""


def _infer_period(transactions: list[dict]) -> Optional[tuple[int, int]]:
    """Return the most common (month, year) among parsed transaction dates."""
    periods: list[tuple[int, int]] = []
    for tx in transactions:
        raw = tx.get("date", "")
        # Two formats: the prompt asks for "09 Feb 2026", but the model
        # sometimes answers in ISO. Accept both rather than losing the row.
        for fmt in ("%d %b %Y", "%Y-%m-%d"):
            try:
                d = datetime.strptime(raw, fmt)
                periods.append((d.month, d.year))
                break
            except ValueError:
                continue
    if not periods:
        return None
    # The MODE, not the first date. Statements straddle month boundaries — a
    # real FNB statement ran 27 Jan to 27 Feb — so the first row would file the
    # whole statement under the wrong month. The majority month is the period.
    return Counter(periods).most_common(1)[0][0]


def import_statement(db: Session, data: bytes, filename: str) -> dict:
    """Run the full import pipeline and return a summary of what was saved."""
    transactions = parse(data, filename)
    if not transactions:
        # parse() returns [] on any failure, including a Gemini error — the
        # traceback is already logged there, so treat it as unparseable here.
        raise ParseError("Could not parse any transactions from the statement.")

    period = _infer_period(transactions)
    if period is None:
        raise ParseError("Could not determine the statement month from transaction dates.")
    month, year = period

    if get_statement_by_month_year(db, month, year):
        raise DuplicateStatementError(
            f"A statement for {month:02d}/{year} has already been imported."
        )

    # The parser speaks the model's language ("description"); the database
    # column is raw_description. This rename is the contract between them.
    for tx in transactions:
        tx["raw_description"] = tx.pop("description", tx.get("raw_description", ""))

    # Order matters below. categorize() is pure enrichment — it adds category_id
    # to each dict and commits nothing; this layer owns all persistence.
    transactions = categorize(db, transactions)

    # Balances are None: the parser extracts transactions, not statement totals.
    stmt = insert_statement(db, month, year, "FNB", None, None)
    for tx in transactions:
        insert_transaction(db, stmt["id"], tx)

    # Summary must be rebuilt after the rows exist — it aggregates over them.
    rebuild_monthly_summary(db, month, year)
    db.commit()  # one commit for the whole import, so a failure leaves nothing

    logger.info("Imported %d transactions for %02d/%d", len(transactions), month, year)
    return {
        "statement_id": stmt["id"],
        "month": month,
        "year": year,
        "transaction_count": len(transactions),
    }


def statement_period_of(db: Session, transaction_date: str) -> Optional[tuple[int, int]]:
    """Return (month, year) parsed from an ISO transaction date, or None."""
    try:
        d = datetime.strptime(transaction_date, "%Y-%m-%d")
        return (d.month, d.year)
    except (ValueError, TypeError):
        return None
