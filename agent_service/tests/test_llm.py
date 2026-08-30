"""Retry policy and error summarisation for Gemini calls."""

import pytest
from google.genai import errors

from agent.llm import _is_daily_quota, call_with_retry, describe_error


def _api_error(code, message):
    """Build a Gemini APIError without going near the network."""
    exc = errors.APIError.__new__(errors.APIError)
    exc.code = code
    exc._msg = message
    type(exc).__str__ = lambda self: self._msg
    return exc


OVERLOADED = lambda: _api_error(503, "503 UNAVAILABLE model is overloaded")
PER_MINUTE = lambda: _api_error(429, "429 {'quotaId': 'GenerateRequestsPerMinutePerProjectPerModel-FreeTier'} limit: 5, model: gemini-3.6-flash")
PER_DAY = lambda: _api_error(429, "429 {'quotaId': 'GenerateRequestsPerDayPerProjectPerModel-FreeTier'} limit: 20, model: gemini-3.6-flash")
GONE = lambda: _api_error(404, "404 NOT_FOUND models/gemini-2.5-flash no longer available")


def test_transient_overload_is_retried_until_it_succeeds(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda _: None)
    attempts = {"n": 0}

    def flaky():
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise OVERLOADED()
        return "recovered"

    assert call_with_retry(flaky, what="test") == "recovered"
    assert attempts["n"] == 3


def test_per_minute_quota_is_retried(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda _: None)
    attempts = {"n": 0}

    def flaky():
        attempts["n"] += 1
        if attempts["n"] < 2:
            raise PER_MINUTE()
        return "ok"

    assert call_with_retry(flaky, what="test") == "ok"


def test_daily_quota_is_not_retried(monkeypatch):
    """Waiting cannot clear a per-day cap, so fail fast instead of burning attempts."""
    monkeypatch.setattr("time.sleep", lambda _: None)
    attempts = {"n": 0}

    def always():
        attempts["n"] += 1
        raise PER_DAY()

    with pytest.raises(errors.APIError):
        call_with_retry(always, what="test")
    assert attempts["n"] == 1


def test_unknown_model_is_not_retried(monkeypatch):
    """A 404 means the model is wrong — retrying cannot fix that."""
    monkeypatch.setattr("time.sleep", lambda _: None)
    attempts = {"n": 0}

    def always():
        attempts["n"] += 1
        raise GONE()

    with pytest.raises(errors.APIError):
        call_with_retry(always, what="test")
    assert attempts["n"] == 1


def test_daily_and_per_minute_quota_are_distinguished():
    assert _is_daily_quota(PER_DAY()) is True
    assert _is_daily_quota(PER_MINUTE()) is False


@pytest.mark.parametrize("exc_factory,expected", [
    (PER_DAY, "20 per day"),
    (PER_MINUTE, "5 per minute"),
    (OVERLOADED, "overloaded"),
    (GONE, "gemini-2.5-flash"),
])
def test_errors_are_summarised_in_one_readable_line(exc_factory, expected):
    """Users and logs get a sentence, never a 40-line traceback."""
    summary = describe_error(exc_factory())
    assert expected in summary
    assert "\n" not in summary
