import logging
import time
from datetime import date

from google.genai import types
from sqlalchemy.orm import Session

from agent.llm import call_with_retry, client
from agent.prompts import TOOL_SYSTEM_PROMPT
from db.queries import (
    compare_months,
    get_bank_fees,
    get_income,
    get_monthly_trend,
    get_spending_by_category,
    get_summary,
    get_top_merchants,
    get_transfers,
)
from settings import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

TOOLS = types.Tool(
    function_declarations=[
        types.FunctionDeclaration(
            name="get_spending_by_category",
            description="Get total spending for a specific category in a given month and year.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "category": types.Schema(type=types.Type.STRING, description="Category name e.g. Groceries"),
                    "month":    types.Schema(type=types.Type.INTEGER, description="Month number 1-12"),
                    "year":     types.Schema(type=types.Type.INTEGER, description="4-digit year"),
                },
                required=["category", "month", "year"],
            ),
        ),
        types.FunctionDeclaration(
            name="get_monthly_trend",
            description="Get spending trend for a category over the last N months.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "category": types.Schema(type=types.Type.STRING, description="Category name"),
                    "months":   types.Schema(type=types.Type.INTEGER, description="Number of months to look back"),
                },
                required=["category", "months"],
            ),
        ),
        types.FunctionDeclaration(
            name="compare_months",
            description="Compare total spending between two months in the same year.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "month1": types.Schema(type=types.Type.INTEGER, description="First month 1-12"),
                    "month2": types.Schema(type=types.Type.INTEGER, description="Second month 1-12"),
                    "year":   types.Schema(type=types.Type.INTEGER, description="4-digit year"),
                },
                required=["month1", "month2", "year"],
            ),
        ),
        types.FunctionDeclaration(
            name="get_top_merchants",
            description=(
                "Get the top merchants by spend for a given month. Pass `category` to find "
                "the biggest merchants within one category — use this for questions like "
                "'which shop do I spend most on food/groceries?'."
            ),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "month": types.Schema(type=types.Type.INTEGER, description="Month number 1-12"),
                    "year":  types.Schema(type=types.Type.INTEGER, description="4-digit year"),
                    "limit": types.Schema(type=types.Type.INTEGER, description="Maximum number of merchants to return"),
                    "category": types.Schema(
                        type=types.Type.STRING,
                        description="Optional exact category name to filter by, e.g. 'Groceries' or 'Food & Takeout'",
                    ),
                },
                required=["month", "year", "limit"],
            ),
        ),
        types.FunctionDeclaration(
            name="get_bank_fees",
            description="Get monthly bank fee totals for a given year.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "year": types.Schema(type=types.Type.INTEGER, description="4-digit year"),
                },
                required=["year"],
            ),
        ),
        types.FunctionDeclaration(
            name="get_transfers",
            description="Get all personal transfer transactions for a given month.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "month": types.Schema(type=types.Type.INTEGER, description="Month number 1-12"),
                    "year":  types.Schema(type=types.Type.INTEGER, description="4-digit year"),
                },
                required=["month", "year"],
            ),
        ),
        types.FunctionDeclaration(
            name="get_income",
            description="Get total income (CR transactions) for a given month.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "month": types.Schema(type=types.Type.INTEGER, description="Month number 1-12"),
                    "year":  types.Schema(type=types.Type.INTEGER, description="4-digit year"),
                },
                required=["month", "year"],
            ),
        ),
        types.FunctionDeclaration(
            name="get_summary",
            description="Get a full spending breakdown by category for a given month.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "month": types.Schema(type=types.Type.INTEGER, description="Month number 1-12"),
                    "year":  types.Schema(type=types.Type.INTEGER, description="4-digit year"),
                },
                required=["month", "year"],
            ),
        ),
    ]
)

# ---------------------------------------------------------------------------
# Python wrappers — each accepts db as first arg, forwards to db.queries
# ---------------------------------------------------------------------------

def _call_tool(db: Session, name: str, args: dict) -> object:
    """Dispatch a function call name + args to the matching query function."""
    dispatch = {
        "get_spending_by_category": lambda: get_spending_by_category(db, **args),
        "get_monthly_trend":        lambda: get_monthly_trend(db, **args),
        "compare_months":           lambda: compare_months(db, **args),
        "get_top_merchants":        lambda: get_top_merchants(db, **args),
        "get_bank_fees":            lambda: get_bank_fees(db, **args),
        "get_transfers":            lambda: get_transfers(db, **args),
        "get_income":               lambda: get_income(db, **args),
        "get_summary":              lambda: get_summary(db, **args),
    }
    fn = dispatch.get(name)
    if fn is None:
        raise ValueError(f"Unknown tool: {name}")
    return fn()


# ---------------------------------------------------------------------------
# ask()
# ---------------------------------------------------------------------------

_MAX_TOOL_ROUNDS = 3


def _describe_periods(periods: list[dict]) -> str:
    """Render available statement periods as a compact, human-readable list."""
    if not periods:
        return "none — no statements have been imported yet"
    return ", ".join(
        f"{p['statement_month']:02d}/{p['statement_year']}" for p in periods
    )


def create_chat(
    month: int,
    year: int,
    periods: list[dict] | None = None,
    categories: list[dict] | None = None,
):
    """Create a Gemini chat session that accumulates conversation history."""
    # The model cannot guess category names. Without this list it tries
    # plausible-but-wrong ones ("Electricity"), wasting a round trip per guess.
    names = ", ".join(c["name"] for c in (categories or [])) or "unknown"
    system = TOOL_SYSTEM_PROMPT.format(
        month=month,
        year=year,
        today=date.today().strftime("%d %B %Y"),
        periods=_describe_periods(periods or []),
        categories=names,
    )
    return client.chats.create(
        model=settings.CHAT_MODEL,
        config=types.GenerateContentConfig(
            tools=[TOOLS],
            system_instruction=system,
        ),
    )


def ask(db: Session, chat, question: str, month: int, year: int, trace_id: str = "") -> str:
    """Send a question on an existing chat session; return a plain English answer."""
    trace = f"[{trace_id[:8]}]" if trace_id else ""
    started = time.monotonic()
    logger.info("%s Q: %r (context %02d/%d)", trace, question[:120], month, year)

    # This prefix sits right next to the question, so it outweighs the system
    # prompt when the two disagree. It previously read "month=3, year=2026",
    # which the model took to mean "this month is March" — even in August.
    # State today first, and label the dashboard month as a view, not a date.
    message = (
        f"[Today is {date.today():%d %B %Y}. "
        f"The dashboard is displaying {month:02d}/{year} — that is the view "
        f'the user is looking at, NOT the meaning of "this month".]'
        + chr(10)
        + question
    )
    response = call_with_retry(lambda: chat.send_message(message), what="chat send")

    rounds = 0
    while response.function_calls and rounds < _MAX_TOOL_ROUNDS:
        parts = _resolve_function_calls(db, response.function_calls, trace)
        response = call_with_retry(lambda: chat.send_message(parts), what="chat tool reply")
        rounds += 1
    if rounds == _MAX_TOOL_ROUNDS and response.function_calls:
        logger.warning("%s hit the %d-round tool limit", trace, _MAX_TOOL_ROUNDS)

    text = (response.text or "").strip()
    if not text or "NEED_SQL" in text:
        # No tool fits — a recurring fallback here means a tool is missing
        logger.warning("%s no tool matched -> NL->SQL fallback (consider adding a tool)", trace)
        from agent.nl_query import run as nl_run  # deferred to avoid circular import
        answer = nl_run(db, question, month, year)
        logger.info("%s path=nl_sql rounds=%d total=%.1fs", trace, rounds, time.monotonic() - started)
        return answer

    logger.info("%s path=tools rounds=%d total=%.1fs", trace, rounds, time.monotonic() - started)
    logger.debug("%s answer: %s", trace, text)
    return text


def _for_model(value):
    """Replace raw money numbers with their preformatted Rand strings.

    The model reliably echoes a string like "R5,128.69" but will happily
    re-render a bare float as "$5128.69", so it never sees the bare float.
    """
    if isinstance(value, list):
        return [_for_model(v) for v in value]
    if not isinstance(value, dict):
        return value
    out = {}
    for key, val in value.items():
        if key.endswith("_display"):
            continue
        display = value.get(f"{key}_display")
        out[key] = display if display is not None else _for_model(val)
    return out


def _fmt_args(args: dict) -> str:
    """Render tool arguments compactly for a log line."""
    return ", ".join(f"{k}={v!r}" for k, v in sorted(args.items()))


def _resolve_function_calls(
    db: Session,
    function_calls: list,
    trace: str = "",
) -> list:
    """Execute each function call and return a list of FunctionResponse parts."""
    parts = []
    for fc in function_calls:
        args = dict(fc.args)
        started = time.monotonic()
        try:
            result = _for_model(_call_tool(db, fc.name, args))
            rows = len(result) if isinstance(result, list) else 1
            logger.info(
                "%s tool %s(%s) -> %d row(s) in %dms",
                trace, fc.name, _fmt_args(args), rows, (time.monotonic() - started) * 1000,
            )
            logger.debug("%s tool %s payload: %s", trace, fc.name, result)
        except Exception:
            logger.exception("%s tool %s(%s) FAILED", trace, fc.name, _fmt_args(args))
            result = {"error": f"Tool {fc.name} failed"}
        parts.append(
            types.Part.from_function_response(
                name=fc.name,
                response={"result": result},
            )
        )
    return parts


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    logger.info("agent.tools imported OK — model: %s", settings.CHAT_MODEL)
    logger.info("TOOLS has %d function declarations", len(TOOLS.function_declarations))
    for fd in TOOLS.function_declarations:
        logger.info("  - %s(%s)", fd.name, ", ".join(fd.parameters.required or []))
