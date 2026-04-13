import logging
from datetime import datetime

import streamlit as st

from agent.categorizer import categorize
from agent.parser import parse
from db.database import SessionLocal
from db.queries import (
    confirm_transaction,
    get_categories,
    get_statements_list,
    get_summary,
    get_transactions_needing_review,
    insert_statement,
    insert_transaction,
    update_transaction_category,
)
from settings import settings
from ui.charts import category_donut, monthly_trend, spend_by_category_bar
from ui.chat import render

logger = logging.getLogger(__name__)

st.set_page_config(page_title=settings.APP_NAME, layout="wide")

# ---------------------------------------------------------------------------
# DB session — cached for the Streamlit app lifetime
# ---------------------------------------------------------------------------

@st.cache_resource
def _get_session():
    """Create a single SQLAlchemy session shared across all Streamlit reruns."""
    return SessionLocal()


db = _get_session()

# ---------------------------------------------------------------------------
# Session state defaults
# ---------------------------------------------------------------------------

if "selected_month" not in st.session_state:
    st.session_state.selected_month = datetime.now().month
if "selected_year" not in st.session_state:
    st.session_state.selected_year = datetime.now().year

month: int = st.session_state.selected_month
year: int = st.session_state.selected_year

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.title(settings.APP_NAME)
    st.subheader("Import Statement")

    uploaded = st.file_uploader(
        "Upload bank statement",
        type=["pdf", "png", "jpg", "jpeg"],
        label_visibility="collapsed",
    )

    if uploaded is not None:
        with st.spinner("Parsing statement…"):
            transactions = parse(uploaded)

        if transactions:
            with st.spinner("Categorizing and saving…"):
                infer_month = datetime.now().month
                infer_year = datetime.now().year

                # Normalise key before categorize so raw_description is available
                for tx in transactions:
                    tx["raw_description"] = tx.pop("description", tx.get("raw_description", ""))

                # 1 → 2: categorize enriches each dict with category_id etc.
                transactions = categorize(db, transactions, infer_month, infer_year)

                # 3: create the statement record
                stmt = insert_statement(db, infer_month, infer_year, "FNB", None, None)

                # 4: persist each enriched transaction
                for tx in transactions:
                    insert_transaction(db, stmt["id"], tx)

                # 5: commit everything
                db.commit()

            st.success(f"Imported {len(transactions)} transactions.")
            st.rerun()  # 6
        else:
            st.error("Could not parse statement. Please try another file.")

    st.divider()
    st.subheader("Statements")

    statements = get_statements_list(db)
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
# Main area header
# ---------------------------------------------------------------------------

st.header(f"{settings.APP_NAME} — {month:02d}/{year}")

summary = get_summary(db, month, year)
total_spent = sum(r["total_spent"] for r in summary if r["type"] == "expense")
top_cat = max((r for r in summary if r["type"] == "expense"), key=lambda r: r["total_spent"], default=None)

from db.queries import get_bank_fees, get_income  # noqa: E402 — inline to keep imports grouped

fees_rows = get_bank_fees(db, year)
fees_this_month = next((r["total_spent"] for r in fees_rows if r["month"] == month), 0.0)
income_data = get_income(db, month, year)

# ---------------------------------------------------------------------------
# Stat cards
# ---------------------------------------------------------------------------

col1, col2, col3, col4 = st.columns(4)
col1.metric("Total Spent", f"R{total_spent:,.2f}")
col2.metric("Top Category", top_cat["category"] if top_cat else "—")
col3.metric("Bank Fees", f"R{fees_this_month:,.2f}")
col4.metric("Income", f"R{income_data['total_income']:,.2f}")

st.divider()

# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------

ch1, ch2, ch3 = st.columns(3)
with ch1:
    st.plotly_chart(spend_by_category_bar(db, month, year), use_container_width=True)
with ch2:
    st.plotly_chart(category_donut(db, month, year), use_container_width=True)
with ch3:
    st.plotly_chart(monthly_trend(db), use_container_width=True)

st.divider()

# ---------------------------------------------------------------------------
# Needs-review expander
# ---------------------------------------------------------------------------

flagged = get_transactions_needing_review(db)
label = f"Transactions Needing Review ({len(flagged)})"

with st.expander(label, expanded=bool(flagged)):
    if not flagged:
        st.caption("All transactions have been reviewed.")
    else:
        categories = get_categories(db)
        cat_options = {c["name"]: c["id"] for c in categories}

        for tx in flagged:
            cols = st.columns([3, 2, 1, 1, 2])
            cols[0].write(tx["description"])
            cols[1].write(f"{tx['direction']} R{tx['amount']:,.2f}")
            cols[2].write(tx.get("category") or "—")
            cols[3].write(f"{(tx['llm_confidence'] or 0):.0%}")

            if cols[4].button("Confirm", key=f"confirm_{tx['id']}"):
                confirm_transaction(db, tx["id"])
                db.commit()
                st.rerun()

            new_cat = st.selectbox(
                "Change to",
                options=list(cat_options.keys()),
                index=list(cat_options.keys()).index(tx["category"]) if tx.get("category") in cat_options else 0,
                key=f"cat_{tx['id']}",
                label_visibility="collapsed",
            )
            if st.button("Apply", key=f"apply_{tx['id']}"):
                update_transaction_category(db, tx["id"], cat_options[new_cat])
                db.commit()
                st.rerun()

st.divider()

# ---------------------------------------------------------------------------
# Chat panel
# ---------------------------------------------------------------------------

render(db, month, year)
