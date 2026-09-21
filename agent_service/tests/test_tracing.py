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
