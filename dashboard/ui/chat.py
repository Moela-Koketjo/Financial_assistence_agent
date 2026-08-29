"""Chat panel — talks to the FastAPI backend, which holds conversation memory."""

import logging
import uuid

import streamlit as st

from ui import api_client

logger = logging.getLogger(__name__)


def render(month: int, year: int) -> None:
    """Render the chat panel — message history, input box, and response loop."""
    if "chat_session_id" not in st.session_state:
        st.session_state.chat_session_id = str(uuid.uuid4())
    if "messages" not in st.session_state:
        st.session_state.messages = []

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    question = st.chat_input("Ask anything about your spending...")

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
