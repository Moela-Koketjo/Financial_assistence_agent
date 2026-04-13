import logging

from google import genai
from sqlalchemy import text
from sqlalchemy.orm import Session

from agent.prompts import FORMAT_TOOL_RESULT_PROMPT, NL_TO_SQL_PROMPT
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

client = genai.Client(api_key=settings.GOOGLE_API_KEY)

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
    if not upper.lstrip().startswith("SELECT"):
        return False
    for keyword in _DANGEROUS:
        if keyword in upper:
            return False
    return True


def _ensure_limit(sql: str) -> str:
    """Append LIMIT clause if the query does not already contain one."""
    if "LIMIT" not in sql.upper():
        return f"{sql.rstrip().rstrip(';')} LIMIT {settings.MAX_SQL_ROWS}"
    return sql


def _generate_sql(question: str, schema: str) -> str:
    """Ask Gemini to write a SELECT query for the given question."""
    prompt = NL_TO_SQL_PROMPT.format(schema=schema, question=question)
    response = client.models.generate_content(
        model=settings.FLASH_MODEL,
        contents=prompt,
    )
    return _strip_fences(response.text)


def _rows_to_dicts(rows) -> list[dict]:
    """Convert SQLAlchemy result rows to plain dicts."""
    return [dict(row._mapping) for row in rows]


def _plain_english(question: str, result: list[dict]) -> str:
    """Ask Gemini to summarise the query result in plain English."""
    prompt = FORMAT_TOOL_RESULT_PROMPT.format(result=result)
    response = client.models.generate_content(
        model=settings.FLASH_MODEL,
        contents=prompt,
    )
    return response.text.strip()


def run(db: Session, question: str, month: int, year: int) -> str:  # noqa: ARG001
    """Translate a natural language question to SQL, run it, and return a plain English answer."""
    schema = _build_schema_string()
    try:
        sql = _generate_sql(question, schema)
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
    logger.info("agent.nl_query imported OK — model: %s", settings.FLASH_MODEL)
    schema = _build_schema_string()
    logger.info("Schema:\n%s", schema)
