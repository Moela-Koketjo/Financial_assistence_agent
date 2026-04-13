import logging

from google import genai
from google.genai import types
from sqlalchemy.orm import Session

from agent.prompts import FORMAT_TOOL_RESULT_PROMPT, TOOL_SYSTEM_PROMPT
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

client = genai.Client(api_key=settings.GOOGLE_API_KEY)

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
            description="Get the top merchants by spend for a given month.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "month": types.Schema(type=types.Type.INTEGER, description="Month number 1-12"),
                    "year":  types.Schema(type=types.Type.INTEGER, description="4-digit year"),
                    "limit": types.Schema(type=types.Type.INTEGER, description="Maximum number of merchants to return"),
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

def ask(db: Session, question: str, month: int, year: int) -> str:
    """Send a question to Gemini with tools; return a plain English answer."""
    system = TOOL_SYSTEM_PROMPT.format(month=month, year=year)
    chat = client.chats.create(
        model=settings.PRO_MODEL,
        config=types.GenerateContentConfig(
            tools=[TOOLS],
            system_instruction=system,
        ),
    )

    response = chat.send_message(question)

    if not response.function_calls:
        # No tool selected — fall back to NL → SQL
        from agent.nl_query import run as nl_run  # deferred to avoid circular import
        return nl_run(db, question, month, year)

    # Resolve all function calls in this turn
    result_parts = _resolve_function_calls(db, response.function_calls)
    response = chat.send_message(result_parts)
    return response.text


def _resolve_function_calls(
    db: Session,
    function_calls: list,
) -> list:
    """Execute each function call and return a list of FunctionResponse parts."""
    parts = []
    for fc in function_calls:
        try:
            result = _call_tool(db, fc.name, dict(fc.args))
            logger.info("Tool %s returned %d item(s)", fc.name, len(result) if isinstance(result, list) else 1)
        except Exception:
            logger.exception("Tool %s failed", fc.name)
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
    logger.info("agent.tools imported OK — model: %s", settings.PRO_MODEL)
    logger.info("TOOLS has %d function declarations", len(TOOLS.function_declarations))
    for fd in TOOLS.function_declarations:
        logger.info("  - %s(%s)", fd.name, ", ".join(fd.parameters.required or []))
