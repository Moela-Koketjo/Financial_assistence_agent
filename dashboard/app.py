"""Streamlit dashboard — a thin client over the FastAPI finance agent."""

import logging
import time
from datetime import datetime

import streamlit as st

from settings import settings
from ui import api_client
from ui.api_client import ApiError
from ui.charts import category_donut, monthly_trend, spend_by_category_bar
from ui.chat import render

logger = logging.getLogger(__name__)

st.set_page_config(page_title=settings.APP_NAME, layout="wide")

# ---------------------------------------------------------------------------
# Session state defaults
# ---------------------------------------------------------------------------

def _default_period() -> tuple[int, int]:
    """Open on the most recent imported statement, falling back to today."""
    now = datetime.now()
    try:
        statements = api_client.list_statements()
    except ApiError:
        return now.month, now.year
    if not statements:
        return now.month, now.year
    latest = statements[0]  # API returns newest first
    return latest["statement_month"], latest["statement_year"]


if "selected_month" not in st.session_state or "selected_year" not in st.session_state:
    default_month, default_year = _default_period()
    st.session_state.selected_month = default_month
    st.session_state.selected_year = default_year
if "processed_upload" not in st.session_state:
    st.session_state.processed_upload = None

month: int = st.session_state.selected_month
year: int = st.session_state.selected_year


def _submit_import(data: bytes, filename: str) -> dict | None:
    """Submit a statement and poll the agent until the background import finishes."""
    try:
        accepted = api_client.upload_statement(data, filename)
    except ApiError as exc:
        st.error(str(exc))
        return None

    job_id = accepted["job_id"]
    job = accepted
    status_box = st.empty()
    deadline = time.monotonic() + settings.IMPORT_POLL_TIMEOUT

    while job["status"] == "processing" and time.monotonic() < deadline:
        status_box.caption("Parsing and categorising… this can take up to a minute.")
        time.sleep(settings.IMPORT_POLL_INTERVAL)
        try:
            job = api_client.get_job(job_id)
        except ApiError as exc:
            status_box.empty()
            st.error(str(exc))
            return None

    status_box.empty()
    if job["status"] == "done":
        return job
    if job["status"] == "failed":
        st.error(job.get("error") or "The import failed.")
    else:
        st.warning("The import is still running — reload the page shortly to see it.")
    return None

# ---------------------------------------------------------------------------
# Sidebar — upload and statement list
# ---------------------------------------------------------------------------

with st.sidebar:
    st.title(settings.APP_NAME)
    st.subheader("Import Statement")

    uploaded = st.file_uploader(
        "Upload bank statement",
        type=["pdf", "png", "jpg", "jpeg"],
        label_visibility="collapsed",
    )

    upload_key = (uploaded.name, uploaded.size) if uploaded is not None else None
    if uploaded is not None and upload_key != st.session_state.processed_upload:
        st.session_state.processed_upload = upload_key  # never re-import on rerun
        job = _submit_import(uploaded.getvalue(), uploaded.name)
        if job and job["status"] == "done":
            result = job["result"]
            st.session_state.selected_month = result["month"]
            st.session_state.selected_year = result["year"]
            st.success(
                f"Imported {result['transaction_count']} transactions "
                f"for {result['month']:02d}/{result['year']}."
            )
            st.rerun()

    st.divider()
    st.subheader("Statements")

    try:
        statements = api_client.list_statements()
    except ApiError as exc:
        st.error(str(exc))
        st.stop()

    if statements:
        for s in statements:
            label = f"{s['statement_month']:02d}/{s['statement_year']}"
            if st.button(label, key=f"stmt_{s['id']}", use_container_width=True):
                st.session_state.selected_month = s["statement_month"]
                st.session_state.selected_year = s["statement_year"]
                st.rerun()
    else:
        st.caption("No statements imported yet.")

# ---------------------------------------------------------------------------
# Main area — header and stat cards
# ---------------------------------------------------------------------------

st.header(f"{settings.APP_NAME} — {month:02d}/{year}")

summary = api_client.get_summary(month, year)
total_spent = sum(r["total_spent"] for r in summary if r["type"] == "expense")
top_cat = max(
    (r for r in summary if r["type"] == "expense"),
    key=lambda r: r["total_spent"],
    default=None,
)
fees_rows = api_client.get_bank_fees(year)
fees_this_month = next((r["total_spent"] for r in fees_rows if r["month"] == month), 0.0)
income_data = api_client.get_income(month, year)

col1, col2, col3, col4 = st.columns(4)
col1.metric("Total Spent", f"R{total_spent:,.2f}")
col2.metric("Top Category", top_cat["category"] if top_cat else "—")
col3.metric("Bank Fees", f"R{fees_this_month:,.2f}")
col4.metric("Income", f"R{income_data['total_income']:,.2f}")

st.divider()

# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------

trend_data = api_client.get_trend()

ch1, ch2, ch3 = st.columns(3)
with ch1:
    st.plotly_chart(spend_by_category_bar(summary, month, year), use_container_width=True)
with ch2:
    st.plotly_chart(category_donut(summary, month, year), use_container_width=True)
with ch3:
    st.plotly_chart(monthly_trend(trend_data), use_container_width=True)

st.divider()

# ---------------------------------------------------------------------------
# Needs-review expander
# ---------------------------------------------------------------------------

flagged = api_client.get_review_queue()
label = f"Transactions Needing Review ({len(flagged)})"

with st.expander(label, expanded=bool(flagged)):
    if not flagged:
        st.caption("All transactions have been reviewed.")
    else:
        categories = api_client.list_categories()
        cat_options = {c["name"]: c["id"] for c in categories}

        for tx in flagged:
            cols = st.columns([3, 2, 1, 1, 2])
            cols[0].write(tx["description"])
            cols[1].write(f"{tx['direction']} R{tx['amount']:,.2f}")
            cols[2].write(tx.get("category") or "—")
            cols[3].write(f"{(tx['llm_confidence'] or 0):.0%}")

            if cols[4].button("Confirm", key=f"confirm_{tx['id']}"):
                api_client.confirm_transaction(tx["id"])
                st.rerun()

            new_cat = st.selectbox(
                "Change to",
                options=list(cat_options.keys()),
                index=list(cat_options.keys()).index(tx["category"]) if tx.get("category") in cat_options else 0,
                key=f"cat_{tx['id']}",
                label_visibility="collapsed",
            )
            if st.button("Apply", key=f"apply_{tx['id']}"):
                api_client.update_category(tx["id"], cat_options[new_cat])
                st.rerun()

st.divider()

# ---------------------------------------------------------------------------
# Chat panel
# ---------------------------------------------------------------------------

render(month, year)
