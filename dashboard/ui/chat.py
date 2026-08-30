"""Chat panel — talks to the FastAPI backend, which holds conversation memory."""

import logging
import uuid

import streamlit as st

from ui import api_client

logger = logging.getLogger(__name__)

# Shown as buttons before the first message — they teach the question format,
# which is what new users get wrong.
_STARTERS = [
    "What did I spend most on?",
    "How much did I earn?",
    "What are my bank fees costing me?",
]


def render(month: int, year: int) -> None:
    """Render the chat panel — message history, input box, and response loop."""
    if "chat_session_id" not in st.session_state:
        st.session_state.chat_session_id = str(uuid.uuid4())
    if "messages" not in st.session_state:
        st.session_state.messages = []

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # Starter questions, shown only before the first message. Users otherwise
    # have to type "hi" to discover what the agent can do — which costs an API
    # call to answer something the UI can show for free.
    picked = None
    if not st.session_state.messages:
        st.caption(f"Ask about your statements — showing {month:02d}/{year}. For example:")
        cols = st.columns(len(_STARTERS))
        for col, starter in zip(cols, _STARTERS):
            if col.button(starter, width="stretch"):
                picked = starter

    question = st.chat_input("Ask anything about your spending...") or picked

    if question:
        st.session_state.messages.append({"role": "user", "content": question})
        answer = _get_answer(question, month, year)
        st.session_state.messages.append({"role": "assistant", "content": answer})
        st.rerun()


def _get_answer(question: str, month: int, year: int) -> str:
    """Call the chat API and return a friendly error string on failure."""
    try:
        return api_client.send_chat(
            st.session_state.chat_session_id, question, month, year
        )
    except api_client.ApiError as exc:
        logger.exception("Chat API failed for question: %s", question)
        return f"Sorry, I ran into a problem answering that: {exc}"
