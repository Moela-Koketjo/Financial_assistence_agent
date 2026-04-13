import logging

import plotly.graph_objects as go
from sqlalchemy.orm import Session

from db.queries import get_categories, get_statements_list, get_summary
from settings import settings

logger = logging.getLogger(__name__)

_TRANSPARENT = "rgba(0,0,0,0)"
_LAYOUT_DEFAULTS = dict(
    paper_bgcolor=_TRANSPARENT,
    plot_bgcolor=_TRANSPARENT,
    font=dict(color="#e0e0e0"),
    margin=dict(l=20, r=20, t=40, b=20),
)


def spend_by_category_bar(db: Session, month: int, year: int) -> go.Figure:
    """Return a horizontal bar chart of DR spending per category for a given month."""
    rows = [r for r in get_summary(db, month, year) if r["type"] != "income"]
    rows.sort(key=lambda r: r["total_spent"])

    fig = go.Figure(go.Bar(
        x=[r["total_spent"] for r in rows],
        y=[r["category"] for r in rows],
        orientation="h",
        marker_color=[r["color_hex"] for r in rows],
        hovertemplate="%{y}: R%{x:,.2f}<extra></extra>",
    ))
    fig.update_layout(
        **_LAYOUT_DEFAULTS,
        title=f"Spending by Category — {month}/{year}",
        xaxis_title="Amount (R)",
        yaxis_title=None,
    )
    return fig


def category_donut(db: Session, month: int, year: int) -> go.Figure:
    """Return a donut chart showing percentage split of spending by category."""
    rows = [r for r in get_summary(db, month, year) if r["total_spent"] > 0]

    fig = go.Figure(go.Pie(
        labels=[r["category"] for r in rows],
        values=[r["total_spent"] for r in rows],
        marker_colors=[r["color_hex"] for r in rows],
        hole=0.45,
        hovertemplate="%{label}: R%{value:,.2f} (%{percent})<extra></extra>",
    ))
    fig.update_layout(
        **_LAYOUT_DEFAULTS,
        title=f"Category Split — {month}/{year}",
    )
    return fig


def monthly_trend(
    db: Session,
    num_months: int = settings.DEFAULT_MONTHS_TREND,
) -> go.Figure:
    """Return a grouped bar chart of total spending per category for the last N months."""
    statements = get_statements_list(db)[:num_months]
    statements = list(reversed(statements))   # oldest → newest left to right

    if not statements:
        return go.Figure(layout=go.Layout(**_LAYOUT_DEFAULTS, title="No data yet"))

    categories = get_categories(db)
    cat_color = {c["name"]: c["color_hex"] for c in categories}

    # Build a dict: category_name → [total_spent per month]
    month_labels = [f"{s['statement_month']:02d}/{s['statement_year']}" for s in statements]
    series: dict[str, list[float]] = {}

    for stmt in statements:
        rows = get_summary(db, stmt["statement_month"], stmt["statement_year"])
        seen = {r["category"] for r in rows}
        for r in rows:
            series.setdefault(r["category"], []).append(r["total_spent"])
        # Fill zeros for categories not present this month
        for cat in series:
            if cat not in seen:
                series[cat].append(0.0)

    fig = go.Figure()
    for cat_name, values in series.items():
        fig.add_trace(go.Bar(
            name=cat_name,
            x=month_labels,
            y=values,
            marker_color=cat_color.get(cat_name, "#888780"),
            hovertemplate=f"{cat_name}: R%{{y:,.2f}}<extra></extra>",
        ))

    fig.update_layout(
        **_LAYOUT_DEFAULTS,
        title=f"Monthly Spending Trend — last {num_months} months",
        barmode="group",
        xaxis_title="Month",
        yaxis_title="Amount (R)",
        legend=dict(orientation="h", yanchor="bottom", y=-0.35),
    )
    return fig


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    logger.info("ui.charts imported OK")
    logger.info(
        "Functions: spend_by_category_bar, category_donut, monthly_trend(default %d months)",
        settings.DEFAULT_MONTHS_TREND,
    )
