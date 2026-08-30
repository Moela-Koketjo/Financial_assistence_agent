"""Categorisation waterfall: merchant memory -> keywords -> direction -> LLM."""

from unittest.mock import patch

import pytest

import agent.categorizer as categorizer
from db.queries import get_categories, get_keywords, insert_merchant


def _categorize(db, description, direction="DR"):
    """Run one transaction through the waterfall without touching Gemini."""
    keywords = get_keywords(db)
    cat_by_name = {c["name"]: c["id"] for c in get_categories(db)}
    cat_by_id = {c["id"]: c["name"] for c in get_categories(db)}
    tx = {"raw_description": description, "amount": 100.0, "direction": direction}
    result = categorizer._categorize_one(db, tx, keywords, cat_by_name)
    return cat_by_id.get(result["category_id"]), result


# --- tier 2: keyword matching -------------------------------------------------

@pytest.mark.parametrize("description,expected", [
    ("POS PURCHASE CHECKERS HYPER RANDBURG", "Groceries"),
    ("PREPAID AIRTIME MTN", "Airtime & Data"),
    ("UBER TRIP PRETORIA", "Transport"),
    ("MONTHLY ACCOUNT FEE", "Bank Fees"),
    ("TAKEALOT ONLINE ORDER", "Shopping"),
])
def test_keyword_matches(db, description, expected):
    """A description containing a seeded keyword is categorised without the LLM."""
    category, result = _categorize(db, description)
    assert category == expected
    assert result["categorization_method"] == "keyword"
    assert result["llm_confidence"] is None  # no API call was made


def test_fee_does_not_match_coffee(db):
    """Word boundaries stop FEE matching COFFEE — a substring check would not."""
    with patch.object(categorizer, "_llm_categorize") as llm:
        llm.return_value = {"category_id": None, "categorization_method": "llm",
                            "user_confirmed": 0, "llm_confidence": 0.5}
        _categorize(db, "POS PURCHASE COFFEE ROASTERY")
    assert llm.called, "COFFEE should fall through to the LLM, not match FEE"


def test_uber_does_not_match_ubereats(db):
    """UBEREATS is Food & Takeout, not Transport — boundaries keep them apart."""
    assert _categorize(db, "UBEREATS ORDER")[0] == "Food & Takeout"


# --- priority collisions: the non-deterministic bug ---------------------------

@pytest.mark.parametrize("description,expected,loser", [
    ("PREPAID ELECTRICITY TSHWANE", "Utilities", "PREPAID"),
    ("MUNICIPAL WATER PAYMENT", "Utilities", None),
    ("TELKOM MOBILE DATA BUNDLE", "Airtime & Data", "BUNDLE"),
])
def test_specific_keyword_beats_generic(db, description, expected, loser):
    """When several keywords match, the higher-priority (more specific) one wins.

    Every rule used to share priority 0, so the winner depended on database row
    order and the same statement categorised differently on different machines.
    """
    assert _categorize(db, description)[0] == expected


def test_keyword_order_is_deterministic(db):
    """get_keywords must return a stable order, or matching is a coin toss."""
    first = [k["keyword"] for k in get_keywords(db)]
    assert first == [k["keyword"] for k in get_keywords(db)]
    priorities = [k["priority"] for k in get_keywords(db)]
    assert priorities == sorted(priorities, reverse=True)


# --- tiers 1 and 3 ------------------------------------------------------------

def test_merchant_memory_wins_over_keywords(db):
    """A learned merchant short-circuits the waterfall, even against a keyword."""
    cat_id = {c["name"]: c["id"] for c in get_categories(db)}
    insert_merchant(db, "POS PURCHASE CHECKERS HYPER", cat_id["Shopping"], "user")
    db.flush()
    category, result = _categorize(db, "POS PURCHASE CHECKERS HYPER")
    assert category == "Shopping"          # not Groceries, despite CHECKERS
    assert result["user_confirmed"] == 1


def test_unmatched_credit_is_income(db):
    """A credit with no keyword match is income — no LLM call needed."""
    category, result = _categorize(db, "UNKNOWN DEPOSIT REF 8891", direction="CR")
    assert category == "Income"
    assert result["llm_confidence"] is None


# --- tier 4: the LLM, and what is learned from it -----------------------------

def test_low_confidence_goes_to_review_and_is_not_learned(db, tx):
    """Below the threshold: flagged for review, and never written to memory."""
    fake = {"category": "Other", "confidence": 0.4, "reasoning": "unsure"}
    with patch.object(categorizer, "call_with_retry") as call:
        call.return_value = type("R", (), {"text": __import__("json").dumps(fake)})()
        out = categorizer.categorize(db, [tx("MYSTERY MERCHANT 001")])
    assert out[0]["user_confirmed"] == 0
    from db.queries import get_merchant_by_name
    assert get_merchant_by_name(db, "MYSTERY MERCHANT 001") is None


def test_repeated_unknown_costs_one_llm_call(db, tx):
    """The same description five times must hit the model once, not five times."""
    fake = {"category": "Other", "confidence": 0.95, "reasoning": "ok"}
    with patch.object(categorizer, "call_with_retry") as call:
        call.return_value = type("R", (), {"text": __import__("json").dumps(fake)})()
        categorizer.categorize(db, [tx("REPEATED UNKNOWN CO") for _ in range(5)])
    assert call.call_count == 1
