import json
import logging
import re

from sqlalchemy.orm import Session

from agent.llm import call_with_retry, client
from agent.prompts import CATEGORIZE_TRANSACTION_PROMPT
from db.queries import (
    get_categories,
    get_keywords,
    get_merchant_by_name,
    insert_merchant,
)
from settings import settings

logger = logging.getLogger(__name__)

def categorize(db: Session, transactions: list[dict]) -> list[dict]:
    """Enrich each transaction dict with categorization fields; caller commits."""
    keywords = get_keywords(db)
    categories = get_categories(db)
    cat_by_name = {c["name"]: c["id"] for c in categories}

    for tx in transactions:
        result = _categorize_one(db, tx, keywords, cat_by_name)
        tx.update(result)
        _save_merchant(db, tx)

    logger.info("Categorized %d transactions", len(transactions))
    return transactions


def _categorize_one(
    db: Session,
    tx: dict,
    keywords: list[dict],
    cat_by_name: dict,
) -> dict:
    """Return category_id, categorization_method, user_confirmed, llm_confidence for one tx."""
    description: str = tx.get("raw_description") or tx.get("description", "")

    # 1 — merchant memory
    merchant = get_merchant_by_name(db, description)
    if merchant and merchant["category_id"]:
        logger.debug("Merchant hit: %s", description)
        return {
            "category_id": merchant["category_id"],
            "categorization_method": merchant.get("match_type") or "user",
            "user_confirmed": 1,
            "llm_confidence": None,
        }

    # 2 — keyword match on whole words only (avoids FEE matching COFFEE)
    upper = description.upper()
    for kw in keywords:
        if re.search(rf"\b{re.escape(kw['keyword'])}\b", upper):
            logger.debug("Keyword hit '%s': %s", kw["keyword"], description)
            return {
                "category_id": kw["category_id"],
                "categorization_method": "keyword",
                "user_confirmed": 1,
                "llm_confidence": None,
            }

    # 3 — CR direction → Income
    if tx.get("direction") == "CR":
        return {
            "category_id": cat_by_name.get("Income"),
            "categorization_method": "keyword",
            "user_confirmed": 1,
            "llm_confidence": None,
        }

    # 4 — LLM fallback
    return _llm_categorize(description, tx.get("amount", 0), tx.get("direction", "DR"), cat_by_name)


def _llm_categorize(
    description: str,
    amount: float,
    direction: str,
    cat_by_name: dict,
) -> dict:
    """Call Gemini to categorize a transaction and return result dict."""
    prompt = CATEGORIZE_TRANSACTION_PROMPT.format(
        description=description,
        amount=amount,
        direction=direction,
    )
    try:
        response = call_with_retry(
            lambda: client.models.generate_content(
                model=settings.CATEGORIZE_MODEL,
                contents=prompt,
            ),
            what="categorize transaction",
        )
        text = (
            response.text
            .strip()
            .removeprefix("```json")
            .removesuffix("```")
            .strip()
        )
        data = json.loads(text)
        category_name: str = data.get("category", "Other")
        confidence: float = float(data.get("confidence", 0.0))
        category_id = cat_by_name.get(category_name) or cat_by_name.get("Other")
        user_confirmed = 0 if confidence < settings.LLM_CONFIDENCE_THRESHOLD else 1
        logger.debug("LLM: %s → %s (%.2f)", description, category_name, confidence)
        return {
            "category_id": category_id,
            "categorization_method": "llm",
            "user_confirmed": user_confirmed,
            "llm_confidence": confidence,
        }
    except Exception:
        logger.exception("LLM categorization failed for: %s", description)
        return {
            "category_id": cat_by_name.get("Other"),
            "categorization_method": "llm",
            "user_confirmed": 0,
            "llm_confidence": None,
        }


def _save_merchant(db: Session, tx: dict) -> None:
    """Persist confirmed categorizations to merchant memory — never unreviewed guesses."""
    # Merchant memory is the app's long-term learning: a merchant seen once is
    # never sent to the LLM again. That only works if what we store is right,
    # so low-confidence guesses are withheld until a human confirms them.
    description: str = tx.get("raw_description") or tx.get("description", "")
    category_id = tx.get("category_id")
    method: str = tx.get("categorization_method", "llm")
    if description and category_id and tx.get("user_confirmed") == 1:
        insert_merchant(db, raw_name=description, category_id=category_id, match_type=method)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    logger.info("agent.categorizer imported OK — model: %s", settings.CATEGORIZE_MODEL)
    logger.info(
        "LLM_CONFIDENCE_THRESHOLD: %s", settings.LLM_CONFIDENCE_THRESHOLD
    )
