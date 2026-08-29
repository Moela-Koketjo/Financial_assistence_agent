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

_KEYWORDS = [
    ("CHECKERS",     "Groceries"),
    ("PNP",          "Groceries"),
    ("WOOLWORTHS",   "Groceries"),
    ("SPAR",         "Groceries"),
    ("CLICKS",       "Groceries"),
    ("SHOPRITE",     "Groceries"),
    ("AIRTIME",      "Airtime & Data"),
    ("PREPAID",      "Airtime & Data"),
    ("MTN",          "Airtime & Data"),
    ("VODACOM",      "Airtime & Data"),
    ("TELKOM",       "Airtime & Data"),
    ("OTT",          "Airtime & Data"),
    ("SMART-AP",     "Airtime & Data"),
    ("RESTAURANT",   "Food & Takeout"),
    ("KFC",          "Food & Takeout"),
    ("STEERS",       "Food & Takeout"),
    ("NANDOS",       "Food & Takeout"),
    ("UBEREATS",     "Food & Takeout"),
    ("MR D",         "Food & Takeout"),
    ("BOLT",         "Transport"),
    ("UBER",         "Transport"),
    ("FEE",          "Bank Fees"),
    ("BUNDLE",       "Bank Fees"),
    ("CHARGE",       "Bank Fees"),
    ("ELECTRICITY",  "Utilities"),
    ("WATER",        "Utilities"),
    ("SEND",         "Personal Transfer"),
    ("EFT",          "Personal Transfer"),
    ("TAKEALOT",     "Shopping"),
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
    """Insert seed keyword rules if the keyword_rule table is empty."""
    if db.query(KeywordRule).count() > 0:
        logger.info("Keywords already seeded — skipping")
        return
    cat_index = {c.name: c.id for c in db.query(Category).all()}
    rules = [
        KeywordRule(keyword=kw, category_id=cat_index[cat_name])
        for kw, cat_name in _KEYWORDS
    ]
    db.add_all(rules)
    logger.info("Inserted %d keyword rules", len(rules))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    seed()
