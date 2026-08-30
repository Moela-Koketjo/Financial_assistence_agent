"""Shared test fixtures.

Two rules for this suite:

1. No network. Gemini is never called — the API key below is a placeholder and
   every LLM call site is mocked. Tests must pass with no key and no quota.
2. No MySQL. Schema-level tests run against in-memory SQLite built from the
   same ORM models, so `pytest` works on a fresh clone with nothing installed
   but the dev dependencies.

The environment variables are set before any project import, because
settings.py requires them at import time.
"""

import os

os.environ.setdefault("GOOGLE_API_KEY", "test-key-never-used")
os.environ.setdefault("DB_USER", "test")
os.environ.setdefault("DB_PASSWORD", "test")
os.environ.setdefault("DB_NAME", "test")

import pytest  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from db.models import Base, Category, KeywordRule  # noqa: E402
from db.seed import _CATEGORIES, _KEYWORDS  # noqa: E402


@pytest.fixture
def db():
    """An empty in-memory database with the real schema, seeded like production."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    session.add_all([Category(**row) for row in _CATEGORIES])
    session.flush()
    cat_id = {c.name: c.id for c in session.query(Category).all()}
    session.add_all([
        KeywordRule(keyword=kw, category_id=cat_id[cat], priority=priority)
        for kw, cat, priority in _KEYWORDS
    ])
    session.commit()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def tx():
    """Factory for a parsed-transaction dict as the parser would produce it."""
    def _make(description: str, amount: float = 100.0, direction: str = "DR") -> dict:
        return {"raw_description": description, "amount": amount, "direction": direction}
    return _make
