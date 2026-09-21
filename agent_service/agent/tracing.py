"""Model-request tracing — a no-op unless Langfuse is configured.

Tracing is observability, never a precondition for the system working
(SPEC 10.1). Every function here is safe to call when tracing is disabled,
misconfigured, or the collector is unreachable: failures are swallowed and the
caller proceeds. An observability fault must never surface as an application
fault.

Financial detail is redacted before anything leaves the process (NFR-20).
Prompts and results carry transaction descriptions and monetary amounts; what
is transmitted is structure, timing, token usage, and which queries ran — which
is all that measuring cost ever required.
"""

import logging
import re
from contextlib import contextmanager
from typing import Any, Iterator, Optional

from settings import settings

logger = logging.getLogger(__name__)

_client: Optional[Any] = None

# Anything that looks like money, in any of the forms this system produces:
# "R5,128.69", "R 5128.69", a bare 5128.69, or "5,128.69".
_MONEY = re.compile(r"(?:R\s?)?\d{1,3}(?:[,\s]\d{3})*(?:\.\d{2})|(?:R\s?)\d+(?:\.\d+)?")

# Description fields are merchant names verbatim — always removed, never parsed.
_DESCRIPTION_KEYS = {
    "raw_description", "description", "merchant", "raw_name", "clean_name",
    "input", "output", "contents", "text", "answer", "question", "message",
    "note", "reasoning",
}

_REDACTED = "[redacted]"


def redact(*, data: Any, **_: Any) -> Any:
    """Remove financial detail before a trace is transmitted.

    Fails closed: anything that cannot be handled is replaced rather than sent.
    Retains structure, counts, periods, categories, and model names — the
    quantities bounded cost is measured in.
    """
    try:
        return _redact(data)
    except Exception:
        logger.debug("Redaction failed; dropping value", exc_info=True)
        return _REDACTED


def _redact(value: Any, depth: int = 0) -> Any:
    """Recursively strip amounts and free text from a value."""
    if depth > 12:
        return _REDACTED
    if isinstance(value, str):
        return _MONEY.sub(_REDACTED, value)
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int,)):
        return value          # counts, months, years, ids
    if isinstance(value, float):
        return _REDACTED      # every float in this system is money
    if isinstance(value, dict):
        return {
            k: (_REDACTED if k in _DESCRIPTION_KEYS else _redact(v, depth + 1))
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact(v, depth + 1) for v in value]
    return _REDACTED          # unknown type — do not risk it


def _get_client() -> Optional[Any]:
    """Return the Langfuse client, or None when tracing is off or unavailable."""
    global _client
    if not settings.TRACING_ENABLED:
        return None
    if _client is None:
        try:
            from langfuse import Langfuse

            _client = Langfuse(
                public_key=settings.LANGFUSE_PUBLIC_KEY,
                secret_key=settings.LANGFUSE_SECRET_KEY,
                host=settings.LANGFUSE_URL,
                mask=redact,
            )
            logger.info("Tracing enabled — sending to %s", settings.LANGFUSE_URL)
        except Exception:
            # Import or construction failed. Disable rather than fail the request.
            logger.warning("Tracing unavailable; continuing without it", exc_info=True)
            _client = False  # sentinel: tried and failed, do not retry
    return _client or None


@contextmanager
def observe(name: str, as_type: str = "span", **fields: Any) -> Iterator[Optional[Any]]:
    """Record one observation, yielding a handle to update — or None when off.

    Swallows every tracing error: the caller's work must complete regardless.
    """
    cm = None
    obs = None
    client = _get_client()
    if client is not None:
        try:
            cm = client.start_as_current_observation(name=name, as_type=as_type, **fields)
            obs = cm.__enter__()
        except Exception:
            logger.debug("Tracing failed to start %r; continuing", name, exc_info=True)
            cm = obs = None

    # The observation is entered and exited around the yield rather than with a
    # `with` block, because a generator-based context manager may yield only
    # once. Catching the caller's exception here and yielding again raises
    # "generator didn't stop after throw()" and REPLACES the caller's exception
    # — which silently broke the daily-quota and unknown-model paths.
    try:
        yield obs
    finally:
        if cm is not None:
            try:
                cm.__exit__(None, None, None)
            except Exception:
                logger.debug("Tracing failed to close %r", name, exc_info=True)


def update(observation: Optional[Any], **fields: Any) -> None:
    """Attach fields to an observation, ignoring any failure."""
    if observation is None:
        return
    try:
        observation.update(**fields)
    except Exception:
        logger.debug("Could not update observation", exc_info=True)


def flush() -> None:
    """Flush pending traces — used at shutdown so nothing is lost."""
    client = _get_client()
    if client is None:
        return
    try:
        client.flush()
    except Exception:
        logger.debug("Could not flush traces", exc_info=True)
