"""Tracing must never become an application failure.

Observability is not on the critical path (SPEC 10.1). Every test here asserts
that the system works regardless of whether tracing is on, off, misconfigured,
or pointed at something unreachable.
"""

from unittest.mock import patch

import pytest

from agent import tracing


@pytest.fixture(autouse=True)
def _reset_client():
    """Each test starts with no cached client."""
    tracing._client = None
    yield
    tracing._client = None


def test_disabled_by_default(monkeypatch):
    """Absent keys mean tracing is off — nobody has to opt out."""
    monkeypatch.setattr(tracing.settings, "LANGFUSE_PUBLIC_KEY", "")
    monkeypatch.setattr(tracing.settings, "LANGFUSE_SECRET_KEY", "")
    assert tracing._get_client() is None


def test_one_key_is_not_enough(monkeypatch):
    """A half-configured deployment is treated as off, not as an error."""
    monkeypatch.setattr(tracing.settings, "LANGFUSE_PUBLIC_KEY", "pk-only")
    monkeypatch.setattr(tracing.settings, "LANGFUSE_SECRET_KEY", "")
    assert tracing._get_client() is None


def test_observe_yields_none_when_disabled(monkeypatch):
    """Callers can use the context manager unconditionally."""
    monkeypatch.setattr(tracing.settings, "LANGFUSE_PUBLIC_KEY", "")
    with tracing.observe("anything", as_type="generation") as obs:
        assert obs is None


def test_client_construction_failure_does_not_raise(monkeypatch):
    """A bad host or version mismatch must not break the request."""
    monkeypatch.setattr(tracing.settings, "LANGFUSE_PUBLIC_KEY", "pk")
    monkeypatch.setattr(tracing.settings, "LANGFUSE_SECRET_KEY", "sk")
    with patch("langfuse.Langfuse", side_effect=RuntimeError("collector unreachable")):
        assert tracing._get_client() is None
        with tracing.observe("q") as obs:
            assert obs is None


def test_failure_is_not_retried_on_every_call(monkeypatch):
    """One failed construction must not cost an attempt per request."""
    monkeypatch.setattr(tracing.settings, "LANGFUSE_PUBLIC_KEY", "pk")
    monkeypatch.setattr(tracing.settings, "LANGFUSE_SECRET_KEY", "sk")
    with patch("langfuse.Langfuse", side_effect=RuntimeError("down")) as ctor:
        for _ in range(5):
            tracing._get_client()
        assert ctor.call_count == 1


def test_observe_swallows_errors_from_the_tracer(monkeypatch):
    """If the tracer throws mid-observation, the caller still proceeds."""
    monkeypatch.setattr(tracing.settings, "LANGFUSE_PUBLIC_KEY", "pk")
    monkeypatch.setattr(tracing.settings, "LANGFUSE_SECRET_KEY", "sk")

    class Broken:
        def start_as_current_observation(self, **_):
            raise RuntimeError("exporter died")

    tracing._client = Broken()
    with tracing.observe("q") as obs:
        assert obs is None


def test_update_and_flush_are_safe_when_off(monkeypatch):
    monkeypatch.setattr(tracing.settings, "LANGFUSE_PUBLIC_KEY", "")
    tracing.update(None, output="x")   # must not raise
    tracing.flush()                    # must not raise


def test_update_swallows_a_broken_observation():
    """A failing observation must not surface to the caller."""
    class Broken:
        def update(self, **_):
            raise RuntimeError("no")

    tracing.update(Broken(), output="x")


def test_model_calls_still_work_when_tracing_breaks(monkeypatch):
    """The gateway keeps working even if every tracing operation fails."""
    from agent import llm

    monkeypatch.setattr(tracing.settings, "LANGFUSE_PUBLIC_KEY", "pk")
    monkeypatch.setattr(tracing.settings, "LANGFUSE_SECRET_KEY", "sk")

    class Broken:
        def start_as_current_observation(self, **_):
            raise RuntimeError("exporter died")

    tracing._client = Broken()
    assert llm.call_with_retry(lambda: "answer", what="test", model="m") == "answer"


# --- redaction: nothing financial may leave the process (NFR-20, AC-27) ------


@pytest.mark.parametrize("text,leaked", [
    ("You spent R5,128.69 on Groceries", "5,128.69"),
    ("R 1234.50 total", "1234.50"),
    ("total was 4913.90", "4913.90"),
    ("R69.00 fee and R2.25 charge", "69.00"),
    ("balance 23,880.42 after", "23,880.42"),
])
def test_amounts_are_removed_from_text(text, leaked):
    """Any money-shaped string is redacted, with or without the R prefix."""
    assert leaked not in tracing.redact(data=text)


@pytest.mark.parametrize("key", [
    "raw_description", "description", "merchant", "raw_name",
    "input", "output", "answer", "question", "message",
])
def test_free_text_fields_are_removed_wholesale(key):
    """Merchant names and prose are never parsed — they are dropped."""
    out = tracing.redact(data={key: "POS PURCHASE CHECKERS HYPER RANDBURG"})
    assert out[key] == "[redacted]"
    assert "CHECKERS" not in str(out)


def test_every_float_is_treated_as_money():
    """Floats in this system are amounts; none should survive."""
    out = tracing.redact(data={"total_spent": 5128.69, "avg_transaction": 394.51})
    assert "5128.69" not in str(out)
    assert "394.51" not in str(out)


def test_the_useful_parts_survive():
    """What cost measurement needs is retained (BR-8, NFR-9)."""
    out = tracing.redact(data={
        "category": "Groceries", "month": 2, "year": 2026,
        "transaction_count": 13, "has_data": True, "total_spent": 5128.69,
    })
    assert out["category"] == "Groceries"
    assert out["month"] == 2 and out["year"] == 2026
    assert out["transaction_count"] == 13
    assert out["has_data"] is True


def test_nested_structures_are_redacted():
    """Amounts hidden inside lists of dicts are still removed."""
    out = tracing.redact(data={"rows": [{"merchant": "SPAR", "total_spent": "R1,234.50"}]})
    assert "SPAR" not in str(out)
    assert "1,234.50" not in str(out)


def test_unknown_types_are_dropped_not_stringified():
    """Fails closed: anything unrecognised is replaced rather than risked."""
    class Weird:
        def __repr__(self): return "R9,999.99 secret"

    assert "9,999.99" not in str(tracing.redact(data=Weird()))


def test_redaction_failure_drops_the_value():
    """If redaction itself raises, nothing is transmitted for that value."""
    class Exploding(dict):
        def items(self): raise RuntimeError("boom")

    assert tracing.redact(data=Exploding()) == "[redacted]"


def test_deep_nesting_is_bounded():
    """A pathological structure cannot cause unbounded recursion."""
    deep = current = {}
    for _ in range(50):
        current["next"] = {}
        current = current["next"]
    current["total_spent"] = 5128.69
    assert "5128.69" not in str(tracing.redact(data=deep))


def test_client_is_constructed_with_the_mask(monkeypatch):
    """The redactor must actually be wired in, or none of the above matters."""
    monkeypatch.setattr(tracing.settings, "LANGFUSE_PUBLIC_KEY", "pk")
    monkeypatch.setattr(tracing.settings, "LANGFUSE_SECRET_KEY", "sk")
    with patch("langfuse.Langfuse") as ctor:
        tracing._get_client()
    assert ctor.call_args.kwargs["mask"] is tracing.redact
