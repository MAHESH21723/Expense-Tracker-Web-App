"""Clearly fake sample data for the public demo (DEMO_DATA=1)."""
from datetime import date

from database import models

# (months_ago, day, type, category, amount_paise, description)
SAMPLE = [
    (0, 1, "Income", "Salary", 55_000_00, "Demo salary"),
    (0, 2, "Expense", "Bills", 12_000_00, "Demo rent"),
    (0, 3, "Expense", "Food", 450_00, "Sample cafe lunch"),
    (0, 5, "Expense", "Transport", 220_00, "Sample cab ride"),
    (0, 8, "Expense", "Shopping", 1_899_00, "Sample online order"),
    (1, 1, "Income", "Salary", 55_000_00, "Demo salary"),
    (1, 4, "Income", "Freelancing", 8_000_00, "Sample freelance project"),
    (1, 2, "Expense", "Bills", 12_000_00, "Demo rent"),
    (1, 6, "Expense", "Food", 2_350_75, "Sample groceries"),
    (1, 12, "Expense", "Entertainment", 650_00, "Sample movie night"),
    (1, 18, "Expense", "Healthcare", 780_50, "Sample pharmacy"),
    (2, 1, "Income", "Salary", 55_000_00, "Demo salary"),
    (2, 2, "Expense", "Bills", 12_000_00, "Demo rent"),
    (2, 9, "Expense", "Education", 3_499_00, "Sample online course"),
    (2, 14, "Expense", "Food", 1_820_25, "Sample groceries"),
    (2, 20, "Expense", "Transport", 960_00, "Sample fuel"),
    (2, 25, "Income", "Investment Returns", 1_250_00, "Sample interest"),
]


def _shift(today, months_ago, day):
    index = today.year * 12 + today.month - 1 - months_ago
    year, month = divmod(index, 12)
    return date(year, month + 1, min(day, 28))


def seed_demo_data(db_path, today=None):
    """Insert sample rows when the database has no transactions. Returns the number inserted."""
    if models.get_months(db_path):
        return 0
    today = today or date.today()
    rows = [
        {"date": _shift(today, ago, day).isoformat(), "trans_type": kind, "category": cat,
         "amount_paise": paise, "description": desc}
        for ago, day, kind, cat, paise, desc in SAMPLE
    ]
    return models.add_transactions(db_path, rows)
