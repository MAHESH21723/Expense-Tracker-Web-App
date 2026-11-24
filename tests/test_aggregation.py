from database import models


def seed(path):
    models.init_db(path)
    rows = [
        ("2026-01-05", "Income", "Salary", 100000_00, ""),
        ("2026-01-10", "Expense", "Food", 10, ""),
        ("2026-01-11", "Expense", "Food", 20, ""),   # 0.10 + 0.20 must equal exactly 0.30
        ("2026-01-31", "Expense", "Bills", 50_00, ""),
        ("2026-02-01", "Income", "Bonus", 2_000_00, ""),
        ("2026-02-28", "Expense", "Food", 1_500_00, ""),
        ("2026-03-15", "Expense", "Transport", 99, ""),
    ]
    for r in rows:
        models.add_transaction(path, *(r[0], r[1], r[2], r[3], r[4]))


def test_summary_all_time(tmp_path):
    p = str(tmp_path / "a.db"); seed(p)
    s = models.get_summary(p)
    assert s["income"] == 102_000_00
    assert s["expense"] == 10 + 20 + 50_00 + 1_500_00 + 99
    assert s["balance"] == s["income"] - s["expense"]


def test_summary_filtered_by_month(tmp_path):
    p = str(tmp_path / "a.db"); seed(p)
    jan = models.get_summary(p, month="2026-01")
    assert jan == {"income": 100000_00, "expense": 50_30, "balance": 100000_00 - 50_30}
    assert models.get_summary(p, month="2026-04") == {"income": 0, "expense": 0, "balance": 0}
    assert models.get_summary(p, month="2026-02", category="Food")["expense"] == 1_500_00


def test_month_boundaries(tmp_path):
    p = str(tmp_path / "a.db"); seed(p)
    assert models.get_summary(p, month="2026-01")["expense"] == 50_30  # includes the 31st
    assert models.get_summary(p, month="2026-02")["expense"] == 1_500_00  # includes the 28th


def test_monthly_totals_chronological(tmp_path):
    p = str(tmp_path / "a.db"); seed(p)
    monthly = models.get_monthly_totals(p)
    assert [m["month"] for m in monthly] == ["2026-01", "2026-02", "2026-03"]
    assert monthly[0] == {"month": "2026-01", "income": 100000_00, "expense": 50_30, "balance": 100000_00 - 50_30}
    assert monthly[2]["income"] == 0 and monthly[2]["expense"] == 99
    assert sum(m["balance"] for m in monthly) == models.get_summary(p)["balance"]


def test_category_totals(tmp_path):
    p = str(tmp_path / "a.db"); seed(p)
    assert models.get_category_totals(p, "Expense") == [("Food", 1_500_30), ("Bills", 50_00), ("Transport", 99)]
    assert models.get_category_totals(p, "Expense", "2026-01") == [("Bills", 50_00), ("Food", 30)]
    assert models.get_category_totals(p, "Income") == [("Salary", 100000_00), ("Bonus", 2_000_00)]


def test_empty_database(tmp_path):
    p = str(tmp_path / "e.db"); models.init_db(p)
    assert models.get_summary(p) == {"income": 0, "expense": 0, "balance": 0}
    assert models.get_monthly_totals(p) == []
    assert models.get_category_totals(p) == []
    assert models.get_months(p) == []


def test_report_percentages_sum_to_100(client):
    for cat, amt in (("Food", "33.33"), ("Bills", "33.33"), ("Others", "33.34")):
        client.add("Expense", "2026-01-01", cat, amt)
    html = client.get("/reports").get_data(as_text=True)
    assert "33.3%" in html and "₹100.00" in html
