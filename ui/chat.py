import logging

import streamlit as st
from sqlalchemy.orm import Session

from agent.tools import ask

logger = logging.getLogger(__name__)


def render(db: Session, month: int, year: int) -> None:
    """Render the chat panel — message history, input box, and response loop."""
    if "messages" not in st.session_state:
        st.session_state.messages = []

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    question = st.chat_input("Ask anything about your spending...")

    if question:
        st.session_state.messages.append({"role": "user", "content": question})

        answer = _get_answer(db, question, month, year)

        st.session_state.messages.append({"role": "assistant", "content": answer})
        st.rerun()


def _get_answer(db: Session, question: str, month: int, year: int) -> str:
    """Call ask() and return a friendly error string on failure."""
    try:
        return ask(db, question, month, year)
    except Exception:
        logger.exception("ask() failed for question: %s", question)
        return "Sorry, I ran into a problem answering that. Please try again."
