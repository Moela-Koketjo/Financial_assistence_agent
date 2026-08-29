import logging

from sqlalchemy import text
from sqlalchemy.orm import Session

from agent.llm import call_with_retry, client, describe_error
from agent.prompts import FORMAT_TOOL_RESULT_PROMPT, NL_TO_SQL_PROMPT
from db.queries import get_categories, money
from db.models import (
    BankStatement,
    Category,
    KeywordRule,
    Merchant,
    MonthlySummary,
    Transaction,
)
from settings import settings

logger = logging.getLogger(__name__)

# This module runs SQL WRITTEN BY THE LLM AT RUNTIME — the only place in the
# app where that happens. Everywhere else uses the ORM, which parameterises
# values for free. Here the query itself is untrusted, hence the allowlist
# below, the SELECT-only rule, and the forced LIMIT.
_DANGEROUS = {"DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "CREATE"}

_MODELS = [Category, KeywordRule, BankStatement, Transaction, Merchant, MonthlySummary]


def _build_schema_string() -> str:
    """Return a human-readable schema string with table and column types from ORM models."""
    blocks: list[str] = []
    for model in _MODELS:
        lines = [f"Table: {model.__tablename__}"]
        for col in model.__table__.columns:
            lines.append(f"  - {col.name}: {col.type}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _strip_fences(text: str) -> str:
    """Strip markdown code fences from a Gemini response string."""
    return text.strip().removeprefix("```sql").removeprefix("```").removesuffix("```").strip()


def _validate(sql: str) -> bool:
    """Return True if sql is a safe SELECT query, False otherwise."""
    upper = sql.upper()
    # Allowlist, not blocklist: anything that is not a plain SELECT is refused
    # rather than sanitised, because sanitising generated SQL is a losing game.
    if not upper.lstrip().startswith("SELECT"):
        return False
    for keyword in _DANGEROUS:
        if keyword in upper:
            return False
    return True


def _ensure_limit(sql: str) -> str:
    """Append LIMIT clause if the query does not already contain one."""
    # A missing LIMIT on a question like "show me everything" would stream the
    # whole table into the prompt, so one is forced on.
    if "LIMIT" not in sql.upper():
        return f"{sql.rstrip().rstrip(';')} LIMIT {settings.MAX_SQL_ROWS}"
    return sql


def _generate_sql(question: str, schema: str, categories: str) -> str:
    """Ask Gemini to write a SELECT query for the given question."""
    prompt = NL_TO_SQL_PROMPT.format(schema=schema, question=question, categories=categories)
    response = call_with_retry(
        lambda: client.models.generate_content(model=settings.CHAT_MODEL, contents=prompt),
        what="nl->sql generate",
    )
    return _strip_fences(response.text)


_MONEY_HINTS = ("amount", "total", "spent", "balance", "fee", "income", "avg")


def _rows_to_dicts(rows) -> list[dict]:
    """Convert result rows to dicts, rendering money columns as Rand strings.

    The model renders a bare float as dollars, so numeric columns that look
    like money are formatted here before they ever reach it.
    """
    out: list[dict] = []
    for row in rows:
        item = {}
        for key, value in dict(row._mapping).items():
            if isinstance(value, (int, float)) and not isinstance(value, bool)                     and any(h in key.lower() for h in _MONEY_HINTS):
                item[key] = money(float(value))
            else:
                item[key] = value
        out.append(item)
    return out


def _plain_english(question: str, result: list[dict]) -> str:
    """Ask Gemini to summarise the query result in plain English."""
    prompt = FORMAT_TOOL_RESULT_PROMPT.format(question=question, result=result)
    response = call_with_retry(
        lambda: client.models.generate_content(model=settings.CHAT_MODEL, contents=prompt),
        what="nl->sql phrase answer",
    )
    return response.text.strip()


def run(db: Session, question: str, month: int, year: int) -> str:  # noqa: ARG001
    """Translate a natural language question to SQL, run it, and return a plain English answer."""
    schema = _build_schema_string()
    categories = ", ".join(c["name"] for c in get_categories(db)) or "none"
    try:
        sql = _generate_sql(question, schema, categories)
        logger.info("Generated SQL: %s", sql)

        if not _validate(sql):
            logger.warning("SQL failed validation: %s", sql)
            return "I could not answer that safely."

        sql = _ensure_limit(sql)
        rows = db.execute(text(sql)).fetchall()
        result = _rows_to_dicts(rows)
        logger.info("Query returned %d rows", len(result))

        return _plain_english(question, result)
    except Exception:
        logger.exception("NL query failed for: %s", question)
        return "I could not answer that safely."


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    logger.info("agent.nl_query imported OK — model: %s", settings.CHAT_MODEL)
    schema = _build_schema_string()
    logger.info("Schema:\n%s", schema)
