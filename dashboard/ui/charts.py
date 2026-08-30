"""Plotly figure builders — pure functions over data returned by the API."""

import logging

import plotly.graph_objects as go

logger = logging.getLogger(__name__)

_TRANSPARENT = "rgba(0,0,0,0)"
_FALLBACK_COLOR = "#888780"
_LAYOUT_DEFAULTS = dict(
    paper_bgcolor=_TRANSPARENT,
    plot_bgcolor=_TRANSPARENT,
    font=dict(color="#e0e0e0"),
    margin=dict(l=20, r=20, t=40, b=20),
)


def spend_by_category_bar(summary_rows: list[dict], month: int, year: int) -> go.Figure:
    """Return a horizontal bar chart of spending per category for a given month."""
    rows = [r for r in summary_rows if r["type"] != "income"]
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
        title=f"Spending by Category — {month:02d}/{year}",
        xaxis_title="Amount (R)",
        yaxis_title=None,
    )
    return fig


def category_donut(summary_rows: list[dict], month: int, year: int) -> go.Figure:
    """Return a donut chart showing percentage split of spending by category."""
    rows = [r for r in summary_rows if r["total_spent"] > 0]

    fig = go.Figure(go.Pie(
        labels=[r["category"] for r in rows],
        values=[r["total_spent"] for r in rows],
        marker_colors=[r["color_hex"] for r in rows],
        hole=0.45,
        hovertemplate="%{label}: R%{value:,.2f} (%{percent})<extra></extra>",
    ))
    fig.update_layout(
        **_LAYOUT_DEFAULTS,
        title=f"Category Split — {month:02d}/{year}",
    )
    return fig


def monthly_trend(trend_data: list[dict]) -> go.Figure:
    """Return a grouped bar chart of spending per category across months.

    trend_data is a list of {"month", "year", "rows"} dicts, oldest first.
    """
    if not trend_data:
        return go.Figure(layout=go.Layout(**_LAYOUT_DEFAULTS, title="No data yet"))

    month_labels = [f"{m['month']:02d}/{m['year']}" for m in trend_data]

    # Collect every category (with its colour) across all months
    cat_color: dict[str, str] = {}
    for m in trend_data:
        for r in m["rows"]:
            cat_color.setdefault(r["category"], r.get("color_hex", _FALLBACK_COLOR))

    # Zero-filled series: one value per month for every category
    series: dict[str, list[float]] = {cat: [] for cat in cat_color}
    for m in trend_data:
        totals = {r["category"]: r["total_spent"] for r in m["rows"]}
        for cat in series:
            series[cat].append(totals.get(cat, 0.0))

    fig = go.Figure()
    for cat_name, values in series.items():
        fig.add_trace(go.Bar(
            name=cat_name,
            x=month_labels,
            y=values,
            marker_color=cat_color[cat_name],
            hovertemplate=f"{cat_name}: R%{{y:,.2f}}<extra></extra>",
        ))

    fig.update_layout(
        **_LAYOUT_DEFAULTS,
        title=f"Monthly Spending Trend — last {len(trend_data)} months",
        # Stacked, not grouped: with ~10 categories, side-by-side bars are a
        # forest of thin slivers. Stacking makes each month's TOTAL readable at
        # a glance — which is what "trend" means — while keeping the breakdown.
        barmode="stack",
        # No x-axis title: the tick labels already read "02/2026", and the
        # title collided with the legend sitting underneath.
        yaxis_title="Amount (R)",
        legend=dict(orientation="h", yanchor="top", y=-0.15, font=dict(size=10)),
    )
    return fig
