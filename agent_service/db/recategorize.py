"""Re-apply keyword rules to existing data after the rules change.

Categorisation normally happens once, at import. When keyword rules or their
priorities change, rows already in the database keep their old category — and
merchant memory may have *learned* a wrong mapping, so it would keep serving
that answer even after the rules are fixed.

This command re-runs keyword matching over rows that keyword matching produced.
Rows decided by a human ("user") or by the LLM are left alone, and no Gemini
call is ever made.

    uv run python -m db.recategorize
"""

import logging
import re

from sqlalchemy.orm import Session

from db.database import SessionLocal
from db.models import Merchant, Transaction
from db.queries import get_keywords, rebuild_monthly_summary

logger = logging.getLogger(__name__)


def _match(description: str, keywords: list[dict]) -> dict | None:
    """Return the highest-priority keyword rule matching a description."""
    upper = (description or "").upper()
    for kw in keywords:
        if re.search(rf"\b{re.escape(kw['keyword'])}\b", upper):
            return kw
    return None


def _fix_merchants(db: Session, keywords: list[dict]) -> int:
    """Correct merchant memory rows that keyword matching originally created."""
    fixed = 0
    for m in db.query(Merchant).filter(Merchant.match_type == "keyword").all():
        hit = _match(m.raw_name, keywords)
        if hit and hit["category_id"] != m.category_id:
            logger.info("merchant %r -> %s", m.raw_name, hit["category_name"])
            m.category_id = hit["category_id"]
            fixed += 1
    return fixed


def _fix_transactions(db: Session, keywords: list[dict]) -> set[tuple[int, int]]:
    """Recategorise keyword-derived transactions; return the periods touched."""
    periods: set[tuple[int, int]] = set()
    for t in db.query(Transaction).filter(Transaction.categorization_method == "keyword").all():
        hit = _match(t.raw_description, keywords)
        if hit and hit["category_id"] != t.category_id:
            logger.info("tx %d %r -> %s", t.id, t.raw_description, hit["category_name"])
            t.category_id = hit["category_id"]
            year, month = int(t.transaction_date[:4]), int(t.transaction_date[5:7])
            periods.add((month, year))
    return periods


def recategorize() -> None:
    """Re-apply current keyword rules to merchant memory and transactions."""
    db = SessionLocal()
    try:
        keywords = get_keywords(db)
        merchants = _fix_merchants(db, keywords)
        periods = _fix_transactions(db, keywords)
        # SessionLocal sets autoflush=False, so these pending updates are
        # invisible to the aggregate query inside rebuild_monthly_summary
        # unless we flush them first — the summary would keep the old totals.
        db.flush()
        for month, year in periods:
            rebuild_monthly_summary(db, month, year)
        db.commit()
        logger.info(
            "Done: %d merchant rows, %d period(s) rebuilt", merchants, len(periods)
        )
    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    recategorize()
