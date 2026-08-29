"""In-process short-term chat memory — one Gemini chat session per session_id."""

import logging
import threading
from dataclasses import dataclass, field

from agent.tools import create_chat
from settings import settings

logger = logging.getLogger(__name__)


@dataclass
class _ChatSession:
    """Holds one live Gemini chat plus the number of turns used."""

    chat: object
    turns: int = field(default=0)


# In-process and deliberately so: this is SHORT-TERM memory. Durable knowledge
# (merchants, categories, transactions) lives in MySQL where it can be
# corrected; a conversation transcript would only go stale. The consequence is
# that chat history dies with the process, and that scaling to more than one
# worker would need session affinity or a shared store like Redis.
_sessions: dict[str, _ChatSession] = {}
_lock = threading.Lock()  # FastAPI serves sync routes on a threadpool


def get_chat(
    session_id: str,
    month: int,
    year: int,
    periods: list[dict] | None = None,
    categories: list[dict] | None = None,
):
    """Return the chat for a session, creating or resetting it when needed."""
    with _lock:
        session = _sessions.get(session_id)
        # Reset past the turn cap: Gemini chats accumulate full history, so an
        # unbounded session grows the prompt (and cost) with every question.
        if session is None or session.turns >= settings.CHAT_HISTORY_MAX_TURNS:
            if session is not None:
                logger.info("Resetting chat history for session %s", session_id)
            session = _ChatSession(chat=create_chat(month, year, periods, categories))
            _sessions[session_id] = session
        session.turns += 1
        return session.chat


def clear(session_id: str) -> None:
    """Drop a session's chat history entirely."""
    with _lock:
        _sessions.pop(session_id, None)
