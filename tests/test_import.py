import io
import re
import zipfile
from pathlib import Path

import pytest

import importers
from database import models

FIX = Path(__file__).parent / "fixtures"


def fx(name):
    return (FIX / name).read_bytes()


# ---- parsers -----------------------------------------------------------------
def test_gpay_html():
    rows, skipped = importers.parse_google_pay("MyActivity.html", fx("gpay_my_activity.html"))
    assert skipped == 1  # the failed payment; "Cancelled payment..." is not a Paid/Sent/Received line
    by_desc = {r["description"]: r for r in rows}
    assert by_desc["Paid to Sample Cafe"] == {"date": "2026-11-12", "type": "Expense", "amount_paise": 25000,
                                              "description": "Paid to Sample Cafe"}
    assert by_desc["Received from Alice Example"]["type"] == "Income"
    assert by_desc["Received from Alice Example"]["amount_paise"] == 150050
    assert by_desc["Sent to Demo Auto Ride"]["date"] == "2026-11-10"
    assert "Paid to Demo Broadband XXXX3210" in by_desc  # phone number masked
    assert len(rows) == 4


def test_gpay_json_uses_ist_dates():
    rows, skipped = importers.parse_google_pay("My Activity.json", fx("gpay_my_activity.json"))
    assert skipped == 1
    assert [(r["date"], r["amount_paise"], r["type"]) for r in rows] == [
        ("2026-11-11", 150050, "Income"), ("2026-11-12", 25000, "Expense")]


def test_gpay_csv():
    rows, skipped = importers.parse_google_pay("transactions.csv", fx("gpay_transactions.csv"))
    assert skipped == 1
    assert len(rows) == 2 and {r["type"] for r in rows} == {"Income", "Expense"}


def make_zip(members):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buf.getvalue()


def test_zip_only_reads_relevant_files_and_dedupes_formats():
    data = make_zip({
        "Takeout/Google Pay/My Activity/My Activity.html": fx("gpay_my_activity.html"),
        "Takeout/Google Pay/My Activity/My Activity.json": fx("gpay_my_activity.json"),
        "Takeout/Google Pay/other.json": b"not relevant, not even json",
        "Takeout/Gmail/My Activity.html": b"<div class='content-cell'>Paid \xe2\x82\xb91 to Wrong</div>",
        "../evil/My Activity.html": b"x",
    })
    rows, _ = importers.parse_google_pay("takeout.zip", data)
    assert len(rows) == 4  # same entries in both formats are not doubled
    assert all("Wrong" not in r["description"] for r in rows)


def test_zip_errors():
    with pytest.raises(importers.ImportFileError):
        importers.parse_google_pay("x.zip", b"not a zip")
    with pytest.raises(importers.ImportFileError):
        importers.parse_google_pay("x.zip", make_zip({"readme.txt": b"hi"}))


def test_zip_bomb_rejected():
    bomb = make_zip({"Takeout/Google Pay/My Activity/My Activity.html": b"0" * (30 * 1024 * 1024)})
    with pytest.raises(importers.ImportFileError):
        importers.parse_google_pay("bomb.zip", bomb)


def test_bank_debit_credit_layout():
    table = importers.read_csv_table(importers.decode_text(fx("bank_debit_credit.csv")))
    header, mapping = importers.detect_bank_layout(table)
    assert header == 2 and set(mapping) >= {"date", "description", "debit", "credit"}
    rows, skipped = importers.parse_bank_rows(table, header, mapping)
    assert skipped == 1  # trailing "Opening balance" line
    assert [(r["date"], r["type"], r["amount_paise"]) for r in rows] == [
        ("2026-11-05", "Expense", 125000), ("2026-11-06", "Income", 5000000), ("2026-11-07", "Expense", 210050)]
    assert "XXXX5432" in rows[0]["description"]  # long reference number masked


def test_bank_amount_with_drcr_and_date_formats():
    table = importers.read_csv_table(importers.decode_text(fx("bank_amount_drcr.csv")))  # ';' delimited
    header, mapping = importers.detect_bank_layout(table)
    rows, _ = importers.parse_bank_rows(table, header, mapping)
    assert [(r["date"], r["type"], r["amount_paise"]) for r in rows] == [
        ("2026-11-01", "Expense", 31000), ("2026-11-02", "Income", 1240), ("2026-11-03", "Expense", 199900)]


def test_bank_unknown_headers_need_mapping():
    table = importers.read_csv_table(importers.decode_text(fx("bank_unknown_headers.csv")))
    assert importers.detect_bank_layout(table)[1] is None
    rows, _ = importers.parse_bank_rows(table, 0, {"date": 0, "description": 1, "debit": 2, "credit": 3})
    assert [(r["type"], r["amount_paise"]) for r in rows] == [("Expense", 50000), ("Income", 250000)]


@pytest.mark.parametrize("text,expected", [
    ("12/11/2026", "2026-11-12"), ("12-11-26", "2026-11-12"), ("2026-11-12", "2026-11-12"),
    ("12 Nov 2026", "2026-11-12"), ("12-Nov-26", "2026-11-12"), ("Nov 12, 2026, 7:42 PM IST", "2026-11-12"),
    ("31/02/2026", None), ("garbage", None)])
def test_parse_date_flexible(text, expected):
    assert importers.parse_date_flexible(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("₹1,234.50", (123450, None)), ("Rs. 99.5 Dr", (9950, "dr")), ("(40.00)", (4000, "dr")),
    ("-12", (1200, "dr")), ("250 Cr", (25000, "cr")), ("0.00", None), ("", None), ("abc", None)])
def test_parse_money(text, expected):
    assert importers.parse_money(text) == expected


def test_masking_and_categorise():
    assert importers.mask_accounts("A/c XXXXXXXX1234 and 9876543210") == "A/c XXXX1234 and XXXX3210"
    rules = [("swiggy", "Expense", "Food"), ("uber eats", "Expense", "Food"), ("uber", "Expense", "Transport")]
    assert importers.categorise("UPI SWIGGY 123", "Expense", rules) == "Food"
    assert importers.categorise("Uber Eats order", "Expense", rules) == "Food"  # longest keyword wins
    assert importers.categorise("UBER trip", "Expense", rules) == "Transport"
    assert importers.categorise("swiggy", "Income", rules) == "Others"
    assert importers.categorise("unknown", "Expense", rules) == "Others"


# ---- routes ------------------------------------------------------------------
def upload(client, source, name, data):
    return client.post("/import/preview", {"source": source, "file": (io.BytesIO(data), name)},
                       content_type="multipart/form-data")


def commit_fields(html):
    """Turn the preview form's inputs into a commit submission (as a browser would)."""
    data = {}
    for m in re.finditer(r'<input[^>]*name="([^"]+)"[^>]*value="([^"]*)"', html):
        if m[1] != "csrf_token":
            data[m[1]] = m[2]
    for m in re.finditer(r'<select name="(category-\d+)">(.*?)</select>', html, re.S):
        data[m[1]] = re.search(r'value="([^"]+)" selected', m[2])[1]
    for m in re.finditer(r'name="(include-\d+)"[^>]*?(checked)?\s*aria', html):
        if m[2]:
            data[m[1]] = "1"
    return data


def test_import_page_and_csrf(client):
    assert client.get("/import").status_code == 200
    assert client.get("/import/rules").status_code == 200
    resp = client.post("/import/preview", {"source": "bank"}, csrf=False)
    assert resp.status_code == 400


def test_preview_commit_and_duplicates(client, app):
    resp = upload(client, "googlepay", "My Activity.html", fx("gpay_my_activity.html"))
    html = resp.get_data(as_text=True)
    assert resp.status_code == 200 and "Sample Cafe" in html and "duplicate" not in html
    assert 'value="Food" selected' in html or "Food</option>" in html
    assert models.get_transactions(app.config["DATABASE"]) == []  # nothing saved by previewing

    fields = commit_fields(html)
    resp = client.post("/import/commit", fields)
    assert resp.status_code == 302
    saved = models.get_transactions(app.config["DATABASE"])
    assert len(saved) == 4
    assert {t["category"] for t in saved if t["description"] == "Paid to Sample Cafe"} == {"Food"}

    # importing the same file again: everything is flagged and nothing is added
    html = upload(client, "googlepay", "My Activity.html", fx("gpay_my_activity.html")).get_data(as_text=True)
    assert html.count("duplicate</span>") == 4
    client.post("/import/commit", {**fields})  # even a forced commit skips duplicates
    assert len(models.get_transactions(app.config["DATABASE"])) == 4


def test_commit_validates_rows(client, app):
    bad = {"count": "2", "include-0": "1", "date-0": "2026-02-31", "type-0": "Expense", "category-0": "Food",
           "amount-0": "5", "description-0": "x",
           "include-1": "1", "date-1": "2026-01-01", "type-1": "Expense", "category-1": "Salary",
           "amount-1": "5", "description-1": "wrong category"}
    client.post("/import/commit", bad)
    assert models.get_transactions(app.config["DATABASE"]) == []


def test_bank_auto_and_manual_mapping(client, app):
    html = upload(client, "bank", "stmt.csv", fx("bank_debit_credit.csv")).get_data(as_text=True)
    assert "Review bank statement import" in html and "Food" in html
    resp = upload(client, "bank", "odd.csv", fx("bank_unknown_headers.csv"))
    page = resp.get_data(as_text=True)
    assert "Map the columns" in page
    csv_text = re.search(r"<textarea[^>]*>(.*?)</textarea>", page, re.S)[1]
    import html as htmllib
    resp = client.post("/import/preview", {"source": "bank", "csv_text": htmllib.unescape(csv_text), "header_row": "0",
                                           "map_date": "0", "map_description": "1", "map_debit": "2", "map_credit": "3"})
    assert resp.status_code == 200 and "Demo grocery store" in resp.get_data(as_text=True)
    resp = client.post("/import/preview", {"source": "bank", "csv_text": htmllib.unescape(csv_text), "header_row": "0",
                                           "map_date": "0"})
    assert resp.status_code == 400


def test_bad_uploads(client):
    assert upload(client, "googlepay", "x.txt", b"hello").status_code == 400
    assert upload(client, "bank", "x.zip", b"PK").status_code == 400
    assert upload(client, "googlepay", "x.html", b"<html></html>").status_code == 400


def test_rules_crud_and_used_in_import(client, app):
    assert client.post("/import/rules", {"keyword": "sample cafe", "type": "Expense", "category": "Entertainment"}).status_code == 302
    assert client.post("/import/rules", {"keyword": "x", "type": "Expense", "category": "Food"}).status_code == 400
    assert client.post("/import/rules", {"keyword": "abc", "type": "Expense", "category": "Salary"}).status_code == 400
    html = upload(client, "googlepay", "a.html", fx("gpay_my_activity.html")).get_data(as_text=True)
    cafe_row = re.search(r"Paid to Sample Cafe.*?</tr>", html, re.S)[0]
    assert 'value="Entertainment" selected' in cafe_row
    rule = next(r for r in models.get_rules(app.config["DATABASE"]) if r["keyword"] == "sample cafe")
    assert client.post(f"/import/rules/{rule['id']}/delete").status_code == 302
    assert client.post(f"/import/rules/{rule['id']}/delete").status_code == 404
