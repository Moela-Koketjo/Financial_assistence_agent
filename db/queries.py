import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from db.models import (
    BankStatement,
    Category,
    KeywordRule,
    Merchant,
    MonthlySummary,
    Transaction,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Insert helpers
# ---------------------------------------------------------------------------

def insert_statement(
    db: Session,
    month: int,
    year: int,
    bank_name: str = "FNB",
    opening_balance: Optional[float] = None,
    closing_balance: Optional[float] = None,
) -> dict:
    """Insert a new bank statement record and return it as a dict."""
    stmt = BankStatement(
        statement_month=month,
        statement_year=year,
        bank_name=bank_name,
        opening_balance=opening_balance,
        closing_balance=closing_balance,
        imported_at=datetime.now().isoformat(),
    )
    db.add(stmt)
    db.flush()
    return {
        "id": stmt.id,
        "statement_month": stmt.statement_month,
        "statement_year": stmt.statement_year,
        "bank_name": stmt.bank_name,
        "opening_balance": stmt.opening_balance,
        "closing_balance": stmt.closing_balance,
        "imported_at": stmt.imported_at,
    }


def insert_transaction(db: Session, statement_id: int, tx_dict: dict) -> dict:
    """Insert a parsed transaction dict and return it as a dict."""
    raw_date: str = tx_dict.get("date", "")
    try:
        iso_date = datetime.strptime(raw_date, "%d %b %Y").strftime("%Y-%m-%d")
    except ValueError:
        iso_date = raw_date  # pass through if already ISO or unparseable

    tx = Transaction(
        statement_id=statement_id,
        transaction_date=iso_date,
        raw_description=tx_dict.get("description", ""),
        service_fee=tx_dict.get("service_fee", 0.0),
        amount=tx_dict.get("amount", 0.0),
        direction=tx_dict.get("direction", "DR"),
        balance=tx_dict.get("balance"),
        category_id=tx_dict.get("category_id"),
        merchant_id=tx_dict.get("merchant_id"),
        categorization_method=tx_dict.get("categorization_method"),
        user_confirmed=tx_dict.get("user_confirmed", 0),
        llm_confidence=tx_dict.get("llm_confidence"),
    )
    db.add(tx)
    db.flush()
    return {
        "id": tx.id,
        "statement_id": tx.statement_id,
        "transaction_date": tx.transaction_date,
        "raw_description": tx.raw_description,
        "amount": tx.amount,
        "direction": tx.direction,
        "category_id": tx.category_id,
    }


def insert_merchant(
    db: Session,
    raw_name: str,
    category_id: int,
    match_type: str,
    clean_name: Optional[str] = None,
) -> dict:
    """Insert or update a merchant record and return it as a dict."""
    existing = db.query(Merchant).filter_by(raw_name=raw_name).first()
    if existing:
        existing.category_id = category_id
        existing.match_type = match_type
        if clean_name:
            existing.clean_name = clean_name
        db.flush()
        m = existing
    else:
        m = Merchant(
            raw_name=raw_name,
            clean_name=clean_name or raw_name,
            category_id=category_id,
            match_type=match_type,
        )
        db.add(m)
        db.flush()
    return {"id": m.id, "raw_name": m.raw_name, "category_id": m.category_id, "match_type": m.match_type}


# ---------------------------------------------------------------------------
# Merchant / keyword lookups
# ---------------------------------------------------------------------------

def get_merchant_by_name(db: Session, raw_name: str) -> Optional[dict]:
    """Return a merchant dict for the given raw name, or None if not found."""
    m = db.query(Merchant).filter_by(raw_name=raw_name).first()
    if not m:
        return None
    return {"id": m.id, "raw_name": m.raw_name, "category_id": m.category_id, "match_type": m.match_type}


def get_keywords(db: Session) -> list[dict]:
    """Return all keyword rules with their category names, ordered by priority desc."""
    rows = (
        db.query(KeywordRule, Category)
        .join(Category, KeywordRule.category_id == Category.id)
        .order_by(KeywordRule.priority.desc())
        .all()
    )
    return [
        {
            "id": kw.id,
            "keyword": kw.keyword,
            "category_id": kw.category_id,
            "category_name": cat.name,
            "priority": kw.priority,
        }
        for kw, cat in rows
    ]


def get_categories(db: Session) -> list[dict]:
    """Return all categories as a list of dicts."""
    return [
        {"id": c.id, "name": c.name, "type": c.type, "color_hex": c.color_hex}
        for c in db.query(Category).order_by(Category.id).all()
    ]


# ---------------------------------------------------------------------------
# Spending queries
# ---------------------------------------------------------------------------

def get_spending_by_category(db: Session, category: str, month: int, year: int) -> dict:
    """Return total spent, count, and average for one category in a given month."""
    row = (
        db.query(MonthlySummary)
        .join(Category, MonthlySummary.category_id == Category.id)
        .filter(
            Category.name == category,
            MonthlySummary.statement_month == month,
            MonthlySummary.statement_year == year,
        )
        .first()
    )
    if not row:
        return {"category": category, "month": month, "year": year, "total_spent": 0.0, "transaction_count": 0, "avg_transaction": 0.0}
    return {
        "category": category,
        "month": month,
        "year": year,
        "total_spent": row.total_spent,
        "transaction_count": row.transaction_count,
        "avg_transaction": row.avg_transaction,
    }


def get_monthly_trend(db: Session, category: str, months: int) -> list[dict]:
    """Return the last N months of spending for a category, oldest first."""
    rows = (
        db.query(MonthlySummary)
        .join(Category, MonthlySummary.category_id == Category.id)
        .filter(Category.name == category)
        .order_by(MonthlySummary.statement_year.desc(), MonthlySummary.statement_month.desc())
        .limit(months)
        .all()
    )
    return [
        {
            "year": r.statement_year,
            "month": r.statement_month,
            "total_spent": r.total_spent,
            "transaction_count": r.transaction_count,
        }
        for r in reversed(rows)
    ]


def compare_months(db: Session, month1: int, month2: int, year: int) -> dict:
    """Return a side-by-side spending breakdown for two months in the same year."""
    def _summary(month: int) -> dict:
        rows = (
            db.query(MonthlySummary, Category)
            .join(Category, MonthlySummary.category_id == Category.id)
            .filter(MonthlySummary.statement_month == month, MonthlySummary.statement_year == year)
            .all()
        )
        breakdown = [{"category": c.name, "total_spent": s.total_spent} for s, c in rows]
        total = sum(r["total_spent"] for r in breakdown)
        return {"month": month, "year": year, "total": total, "breakdown": breakdown}

    m1 = _summary(month1)
    m2 = _summary(month2)
    return {"month1": m1, "month2": m2, "difference": round(m2["total"] - m1["total"], 2)}


def get_top_merchants(db: Session, month: int, year: int, limit: int = 10) -> list[dict]:
    """Return the top merchants by total spend for a given month, as a list of dicts."""
    date_prefix = f"{year}-{month:02d}-%"
    rows = (
        db.query(
            Transaction.raw_description,
            func.sum(Transaction.amount).label("total"),
            func.count(Transaction.id).label("count"),
        )
        .filter(
            Transaction.transaction_date.like(date_prefix),
            Transaction.direction == "DR",
        )
        .group_by(Transaction.raw_description)
        .order_by(func.sum(Transaction.amount).desc())
        .limit(limit)
        .all()
    )
    return [{"merchant": r.raw_description, "total_spent": r.total, "transaction_count": r.count} for r in rows]


def get_bank_fees(db: Session, year: int) -> list[dict]:
    """Return monthly bank fee totals for a given year."""
    rows = (
        db.query(MonthlySummary)
        .join(Category, MonthlySummary.category_id == Category.id)
        .filter(Category.name == "Bank Fees", MonthlySummary.statement_year == year)
        .order_by(MonthlySummary.statement_month)
        .all()
    )
    return [
        {"month": r.statement_month, "year": r.statement_year, "total_spent": r.total_spent, "transaction_count": r.transaction_count}
        for r in rows
    ]


def get_transfers(db: Session, month: int, year: int) -> list[dict]:
    """Return all Personal Transfer transactions for a given month."""
    date_prefix = f"{year}-{month:02d}-%"
    rows = (
        db.query(Transaction)
        .join(Category, Transaction.category_id == Category.id)
        .filter(
            Category.name == "Personal Transfer",
            Transaction.transaction_date.like(date_prefix),
        )
        .order_by(Transaction.transaction_date)
        .all()
    )
    return [
        {
            "id": t.id,
            "date": t.transaction_date,
            "description": t.raw_description,
            "amount": t.amount,
            "direction": t.direction,
        }
        for t in rows
    ]


def get_income(db: Session, month: int, year: int) -> dict:
    """Return total income (CR transactions) for a given month."""
    date_prefix = f"{year}-{month:02d}-%"
    result = (
        db.query(
            func.sum(Transaction.amount).label("total"),
            func.count(Transaction.id).label("count"),
        )
        .filter(
            Transaction.transaction_date.like(date_prefix),
            Transaction.direction == "CR",
        )
        .first()
    )
    return {
        "month": month,
        "year": year,
        "total_income": float(result.total or 0.0),
        "transaction_count": result.count or 0,
    }


def get_summary(db: Session, month: int, year: int) -> list[dict]:
    """Return full monthly summary with category names for a given month."""
    rows = (
        db.query(MonthlySummary, Category)
        .join(Category, MonthlySummary.category_id == Category.id)
        .filter(
            MonthlySummary.statement_month == month,
            MonthlySummary.statement_year == year,
        )
        .order_by(MonthlySummary.total_spent.desc())
        .all()
    )
    return [
        {
            "category": cat.name,
            "type": cat.type,
            "color_hex": cat.color_hex,
            "total_spent": s.total_spent,
            "transaction_count": s.transaction_count,
            "avg_transaction": s.avg_transaction,
        }
        for s, cat in rows
    ]


# ---------------------------------------------------------------------------
# Statement and review queries
# ---------------------------------------------------------------------------

def get_statements_list(db: Session) -> list[dict]:
    """Return all imported bank statements ordered by year and month descending."""
    rows = db.query(BankStatement).order_by(
        BankStatement.statement_year.desc(),
        BankStatement.statement_month.desc(),
    ).all()
    return [
        {
            "id": s.id,
            "bank_name": s.bank_name,
            "statement_month": s.statement_month,
            "statement_year": s.statement_year,
            "opening_balance": s.opening_balance,
            "closing_balance": s.closing_balance,
            "imported_at": s.imported_at,
        }
        for s in rows
    ]


def get_transactions_needing_review(db: Session) -> list[dict]:
    """Return LLM-categorized transactions not yet confirmed by the user."""
    rows = (
        db.query(Transaction, Category)
        .outerjoin(Category, Transaction.category_id == Category.id)
        .filter(
            Transaction.categorization_method == "llm",
            Transaction.user_confirmed == 0,
        )
        .order_by(Transaction.llm_confidence)
        .all()
    )
    return [
        {
            "id": t.id,
            "date": t.transaction_date,
            "description": t.raw_description,
            "amount": t.amount,
            "direction": t.direction,
            "category": cat.name if cat else None,
            "llm_confidence": t.llm_confidence,
        }
        for t, cat in rows
    ]


# ---------------------------------------------------------------------------
# Mutation helpers
# ---------------------------------------------------------------------------

def confirm_transaction(db: Session, transaction_id: int) -> None:
    """Mark a transaction as user-confirmed."""
    db.query(Transaction).filter_by(id=transaction_id).update({"user_confirmed": 1})
    db.flush()


def update_transaction_category(db: Session, transaction_id: int, category_id: int) -> None:
    """Update a transaction's category and mark it as user-confirmed."""
    db.query(Transaction).filter_by(id=transaction_id).update(
        {"category_id": category_id, "categorization_method": "user", "user_confirmed": 1}
    )
    db.flush()


# ---------------------------------------------------------------------------
# Summary rebuild
# ---------------------------------------------------------------------------

def rebuild_monthly_summary(db: Session, month: int, year: int) -> None:
    """Delete and rebuild monthly_summary rows for the given month and year."""
    db.query(MonthlySummary).filter_by(statement_month=month, statement_year=year).delete()

    date_prefix = f"{year}-{month:02d}-%"
    rows = (
        db.query(
            Transaction.category_id,
            func.sum(Transaction.amount).label("total_spent"),
            func.count(Transaction.id).label("transaction_count"),
            func.avg(Transaction.amount).label("avg_transaction"),
        )
        .filter(
            Transaction.transaction_date.like(date_prefix),
            Transaction.category_id.isnot(None),
            Transaction.direction == "DR",
        )
        .group_by(Transaction.category_id)
        .all()
    )

    db.add_all([
        MonthlySummary(
            statement_year=year,
            statement_month=month,
            category_id=r.category_id,
            total_spent=round(float(r.total_spent), 2),
            transaction_count=r.transaction_count,
            avg_transaction=round(float(r.avg_transaction), 2),
        )
        for r in rows
    ])
    db.flush()
    logger.info("Rebuilt monthly summary for %d/%d — %d categories", month, year, len(rows))
