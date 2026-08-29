import logging

from db.database import Base, SessionLocal, engine
from db.models import Category, KeywordRule  # noqa: F401 — registers all models with Base

logger = logging.getLogger(__name__)

_CATEGORIES = [
    {"name": "Groceries",         "type": "expense",  "color_hex": "#1D9E75"},
    {"name": "Airtime & Data",    "type": "expense",  "color_hex": "#378ADD"},
    {"name": "Food & Takeout",    "type": "expense",  "color_hex": "#D85A30"},
    {"name": "Transport",         "type": "expense",  "color_hex": "#BA7517"},
    {"name": "Bank Fees",         "type": "expense",  "color_hex": "#E24B4A"},
    {"name": "Utilities",         "type": "expense",  "color_hex": "#7F77DD"},
    {"name": "Personal Transfer", "type": "transfer", "color_hex": "#534AB7"},
    {"name": "Income",            "type": "income",   "color_hex": "#639922"},
    {"name": "Shopping",          "type": "expense",  "color_hex": "#D4537E"},
    {"name": "Other",             "type": "expense",  "color_hex": "#888780"},
]

# (keyword, category, priority) — HIGHER PRIORITY WINS when several keywords
# match one description. "PREPAID ELECTRICITY TSHWANE" contains both PREPAID
# (Airtime & Data) and ELECTRICITY (Utilities); without priorities the winner
# depended on row order, so the same statement could categorise differently on
# different machines. Specific services outrank brands, which outrank generic
# payment words like FEE and PREPAID.
_KEYWORDS = [
    ("CHECKERS",     "Groceries",          50),
    ("PNP",          "Groceries",          50),
    ("WOOLWORTHS",   "Groceries",          50),
    ("SPAR",         "Groceries",          50),
    ("CLICKS",       "Groceries",          50),
    ("SHOPRITE",     "Groceries",          50),
    ("AIRTIME",      "Airtime & Data",     10),
    ("PREPAID",      "Airtime & Data",     10),
    ("MTN",          "Airtime & Data",     50),
    ("VODACOM",      "Airtime & Data",     50),
    ("TELKOM",       "Airtime & Data",     50),
    ("OTT",          "Airtime & Data",     50),
    ("SMART-AP",     "Airtime & Data",     50),
    ("RESTAURANT",   "Food & Takeout",     10),
    ("KFC",          "Food & Takeout",     50),
    ("STEERS",       "Food & Takeout",     50),
    ("NANDOS",       "Food & Takeout",     50),
    ("UBEREATS",     "Food & Takeout",     50),
    ("MR D",         "Food & Takeout",     50),
    ("BOLT",         "Transport",          50),
    ("UBER",         "Transport",          50),
    ("FEE",          "Bank Fees",          0),
    ("BUNDLE",       "Bank Fees",          0),
    ("CHARGE",       "Bank Fees",          0),
    ("ELECTRICITY",  "Utilities",          100),
    ("WATER",        "Utilities",          100),
    ("SEND",         "Personal Transfer",  0),
    ("EFT",          "Personal Transfer",  0),
    ("TAKEALOT",     "Shopping",           50),
]


def seed() -> None:
    """Create all MySQL tables and insert seed categories and keyword rules."""
    logger.info("Creating tables...")
    Base.metadata.create_all(engine)
    logger.info("Tables created: %s", list(Base.metadata.tables.keys()))

    db = SessionLocal()
    try:
        _seed_categories(db)
        _seed_keywords(db)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Seed failed — rolled back")
        raise
    finally:
        db.close()


def _seed_categories(db) -> None:
    """Insert seed categories if the category table is empty."""
    if db.query(Category).count() > 0:
        logger.info("Categories already seeded — skipping")
        return
    db.add_all([Category(**row) for row in _CATEGORIES])
    db.flush()  # assign PKs so keyword seeding can look them up
    logger.info("Inserted %d categories", len(_CATEGORIES))


def _seed_keywords(db) -> None:
    """Insert seed keyword rules, and re-sync priorities on existing databases."""
    cat_index = {c.name: c.id for c in db.query(Category).all()}
    existing = {r.keyword: r for r in db.query(KeywordRule).all()}

    inserted = updated = 0
    for kw, cat_name, priority in _KEYWORDS:
        rule = existing.get(kw)
        if rule is None:
            db.add(KeywordRule(keyword=kw, category_id=cat_index[cat_name], priority=priority))
            inserted += 1
        elif rule.priority != priority:
            # Priorities are corrective: a database seeded before they existed
            # has every rule at 0, which is the ambiguity bug. Fix it in place.
            rule.priority = priority
            updated += 1
    if inserted or updated:
        logger.info("Keyword rules: %d inserted, %d priorities updated", inserted, updated)
    else:
        logger.info("Keyword rules already up to date")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    seed()
