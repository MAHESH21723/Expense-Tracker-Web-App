"""In-memory chart rendering (matplotlib, Agg backend). Returns PNG bytes."""
import io

import matplotlib

matplotlib.use("Agg")
from matplotlib.figure import Figure  # noqa: E402

PALETTE = ["#2563eb", "#f59e0b", "#10b981", "#ef4444", "#8b5cf6", "#06b6d4", "#ec4899", "#6b7280"]
INCOME_COLOR, EXPENSE_COLOR = "#10b981", "#ef4444"
TEXT = "#1f2937"


def _png(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight", facecolor="white")
    return buf.getvalue()


def _empty(title):
    fig = Figure(figsize=(6, 4))
    ax = fig.subplots()
    ax.axis("off")
    ax.text(0.5, 0.5, "No data yet", ha="center", va="center", fontsize=14, color="#6b7280")
    ax.set_title(title, color=TEXT, fontweight="bold")
    return _png(fig)


def _style(ax, title):
    ax.set_title(title, color=TEXT, fontweight="bold", pad=12)
    ax.grid(axis="y", color="#e5e7eb")
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.tick_params(colors=TEXT, labelsize=9)
    ax.set_ylabel("Amount (₹)", color=TEXT)


def category_chart(category_totals):
    """Donut chart of [(category, paise)]."""
    title = "Expenses by category"
    if not category_totals:
        return _empty(title)
    labels = [c for c, _ in category_totals]
    values = [p / 100 for _, p in category_totals]
    fig = Figure(figsize=(6, 4.5))
    ax = fig.subplots()
    ax.pie(
        values, labels=labels, colors=PALETTE[: len(values)] if len(values) <= len(PALETTE) else None,
        autopct="%1.0f%%", startangle=90, counterclock=False, pctdistance=0.78,
        wedgeprops={"width": 0.45, "edgecolor": "white"}, textprops={"color": TEXT, "fontsize": 9},
    )
    ax.set_title(title, color=TEXT, fontweight="bold")
    return _png(fig)


def trend_chart(monthly):
    """Line chart of monthly expense from get_monthly_totals()."""
    title = "Monthly expense trend"
    if not monthly:
        return _empty(title)
    fig = Figure(figsize=(6, 4))
    ax = fig.subplots()
    ax.plot([m["month"] for m in monthly], [m["expense"] / 100 for m in monthly],
            marker="o", linewidth=2.5, color=EXPENSE_COLOR)
    _style(ax, title)
    fig.autofmt_xdate()
    return _png(fig)


def income_expense_chart(monthly):
    """Grouped bars of income vs expense per month."""
    title = "Income vs expense by month"
    if not monthly:
        return _empty(title)
    fig = Figure(figsize=(6, 4))
    ax = fig.subplots()
    xs = range(len(monthly))
    width = 0.38
    ax.bar([x - width / 2 for x in xs], [m["income"] / 100 for m in monthly], width, label="Income", color=INCOME_COLOR)
    ax.bar([x + width / 2 for x in xs], [m["expense"] / 100 for m in monthly], width, label="Expense", color=EXPENSE_COLOR)
    ax.set_xticks(list(xs))
    ax.set_xticklabels([m["month"] for m in monthly])
    _style(ax, title)
    ax.legend(frameon=False)
    fig.autofmt_xdate()
    return _png(fig)
