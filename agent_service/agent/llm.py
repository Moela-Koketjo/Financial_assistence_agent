"""Shared Gemini client, retry policy, and error summarisation.

Every Gemini call in this service goes through call_with_retry() so that
transient upstream failures (503 overload, per-minute rate limits, network
resets) are retried instead of surfacing as errors, and so that quota
problems are logged as one readable line rather than a 40-line traceback.
"""

import logging
import random
import re
import time
from typing import Callable, Optional, TypeVar

from google import genai
from google.genai import errors

from settings import settings

logger = logging.getLogger(__name__)

client = genai.Client(api_key=settings.GOOGLE_API_KEY)

T = TypeVar("T")

# Transient: worth retrying. 404/400 are not — the model or request is wrong.
_RETRYABLE_CODES = {429, 500, 502, 503, 504}


def _status_code(exc: Exception) -> Optional[int]:
    """Return the HTTP status code carried by a Gemini API error, if any."""
    code = getattr(exc, "code", None)
    if isinstance(code, int):
        return code
    match = re.search(r"\b(4\d{2}|5\d{2})\b", str(exc))
    return int(match.group(1)) if match else None


def _suggested_delay(exc: Exception) -> Optional[float]:
    """Return Google's own retryDelay hint in seconds, if the error carries one."""
    match = re.search(r"retryDelay'?:\s*'?(\d+(?:\.\d+)?)s", str(exc))
    return float(match.group(1)) if match else None


def _is_daily_quota(exc: Exception) -> bool:
    """True when the error is a per-DAY quota cap, which retrying cannot clear."""
    return "PerDay" in str(exc)


def describe_error(exc: Exception) -> str:
    """Summarise a Gemini API error in one line suitable for a log or a user."""
    text = str(exc)
    code = _status_code(exc)
    if code == 429:
        model = re.search(r"model:\s*([\w.-]+)", text)
        limit = re.search(r"limit:\s*(\d+)", text)
        period = "per day" if _is_daily_quota(exc) else "per minute"
        retry = _suggested_delay(exc)
        parts = [f"quota exhausted ({limit.group(1) if limit else '?'} {period}"]
        parts.append(f", model {model.group(1)})" if model else ")")
        if retry:
            parts.append(f" — retry in {retry:.0f}s")
        return "".join(parts)
    if code == 503:
        return "model temporarily overloaded (503) — Google capacity, not your quota"
    if code == 404:
        model = re.search(r"models/([\w.-]+)", text)
        return f"model unavailable to this API key: {model.group(1) if model else 'unknown'}"
    return f"{type(exc).__name__}: {text[:160]}"


def call_with_retry(fn: Callable[[], T], *, what: str) -> T:
    """Run a Gemini call, retrying transient failures with exponential backoff."""
    attempts = max(1, settings.LLM_MAX_ATTEMPTS)
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except Exception as exc:
            code = _status_code(exc)
            transient = isinstance(exc, errors.APIError) and code in _RETRYABLE_CODES
            network = isinstance(exc, (ConnectionError, OSError)) or "10054" in str(exc)

            if _is_daily_quota(exc):
                logger.error("%s failed — %s (daily cap; not retrying)", what, describe_error(exc))
                raise
            if not (transient or network) or attempt == attempts:
                logger.error("%s failed — %s", what, describe_error(exc))
                raise

            delay = _backoff_delay(attempt, _suggested_delay(exc))
            logger.warning(
                "%s failed (attempt %d/%d) — %s; retrying in %.1fs",
                what, attempt, attempts, describe_error(exc), delay,
            )
            time.sleep(delay)
    raise RuntimeError("unreachable")  # pragma: no cover


def _backoff_delay(attempt: int, suggested: Optional[float]) -> float:
    """Exponential backoff with jitter, honouring Google's hint when it is short."""
    base = settings.LLM_RETRY_BASE_DELAY * (2 ** (attempt - 1))
    delay = max(base, suggested or 0.0)
    return min(delay, settings.LLM_MAX_RETRY_DELAY) + random.uniform(0, 0.5)
