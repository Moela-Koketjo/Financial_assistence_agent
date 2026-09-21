"""Model-request tracing — a no-op unless Langfuse is configured.

Tracing is observability, never a precondition for the system working
(SPEC 10.1). Every function here is safe to call when tracing is disabled,
misconfigured, or the collector is unreachable: failures are swallowed and the
caller proceeds. An observability fault must never surface as an application
fault.

Trace data is sent to a self-hosted collector only (NFR-20) — prompts and
results carry transaction descriptions and amounts.
"""

import logging
from contextlib import contextmanager
from typing import Any, Iterator, Optional

from settings import settings

logger = logging.getLogger(__name__)

_client: Optional[Any] = None


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
                host=settings.LANGFUSE_HOST,
            )
            logger.info("Tracing enabled — sending to %s", settings.LANGFUSE_HOST)
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
    client = _get_client()
    if client is None:
        yield None
        return
    try:
        with client.start_as_current_observation(name=name, as_type=as_type, **fields) as obs:
            yield obs
    except Exception:
        logger.debug("Tracing failed for %r; continuing", name, exc_info=True)
        yield None


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
