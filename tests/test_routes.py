import re


def test_empty_pages_render(client):
    for url in ("/", "/reports", "/add-income", "/add-expense"):
        assert client.get(url).status_code == 200
    for name in ("category", "trend", "income-expense"):
        resp = client.get(f"/charts/{name}.png")
        assert resp.status_code == 200 and resp.data.startswith(b"\x89PNG")
    assert client.get("/charts/nope.png").status_code == 404


def test_add_and_list(client):
    resp = client.add("Expense", "2026-01-05", "Food", "12.50", "Lunch")
    assert resp.status_code == 302
    html = client.get("/").get_data(as_text=True)
    assert "Lunch" in html and "12.50" in html


def test_invalid_input_rejected(client):
    for amount in ("0", "-3", "abc", "1.234"):
        assert client.add("Expense", "2026-01-05", "Food", amount).status_code == 400
    assert client.add("Expense", "2026-02-31", "Food", "5").status_code == 400
    assert client.add("Expense", "2026-01-05", "Salary", "5").status_code == 400
    assert "No transactions found" in client.get("/").get_data(as_text=True)


def test_csrf_required(client):
    resp = client.post("/add-expense", {"date": "2026-01-01", "category": "Food", "amount": "5"}, csrf=False)
    assert resp.status_code == 400
    client.add("Expense", "2026-01-01", "Food", "5")
    assert client.post("/transactions/1/delete", csrf=False).status_code == 400
    assert client.post("/transactions/1/delete", {"csrf_token": "wrong"}, csrf=False).status_code == 400
    assert "Food" in client.get("/").get_data(as_text=True)


def test_delete_requires_post_and_works(client):
    client.add("Expense", "2026-01-01", "Food", "5")
    assert client.get("/transactions/1/delete").status_code == 405
    assert client.post("/transactions/1/delete").status_code == 302
    assert client.post("/transactions/1/delete").status_code == 404


def test_edit(client):
    client.add("Expense", "2026-01-01", "Food", "5", "old")
    page = client.get("/transactions/1/edit").get_data(as_text=True)
    assert 'value="5.00"' in page and 'value="old"' in page
    resp = client.post("/transactions/1/edit", {"date": "2026-01-02", "category": "Bills", "amount": "7.25", "description": "new"})
    assert resp.status_code == 302
    html = client.get("/").get_data(as_text=True)
    assert "new" in html and "7.25" in html and "<td>old</td>" not in html
    assert client.post("/transactions/1/edit", {"date": "2026-01-02", "category": "Bills", "amount": "-1"}).status_code == 400
    assert client.get("/transactions/99/edit").status_code == 404


def test_xss_is_escaped(client):
    client.add("Expense", "2026-01-01", "Food", "5", "<script>alert(1)</script>")
    html = client.get("/").get_data(as_text=True)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_sql_injection_attempts_are_inert(client):
    client.add("Expense", "2026-01-01", "Food", "5", "Lunch")
    for url in ("/?search=' OR 1=1 --", "/?sort_by=amount;DROP TABLE transactions", "/?month=2026-01' OR '1'='1",
                "/?category=Food' OR '1'='1", "/export.csv?search=%25"):
        assert client.get(url).status_code == 200
    assert "Lunch" in client.get("/").get_data(as_text=True)
    assert "Lunch" not in client.get("/?search=' OR 1=1 --").get_data(as_text=True)


def test_filters(client):
    client.add("Expense", "2026-01-10", "Food", "10", "pizza")
    client.add("Expense", "2026-02-10", "Bills", "20", "power")
    client.add("Income", "2026-02-11", "Salary", "100", "pay")
    html = client.get("/?month=2026-02").get_data(as_text=True)
    assert "power" in html and "pizza" not in html
    html = client.get("/?category=Food").get_data(as_text=True)
    assert "pizza" in html and "power" not in html
    html = client.get("/?type=Income").get_data(as_text=True)
    assert "pay" in html and "pizza" not in html
    assert "pizza" in client.get("/?search=PIZ").get_data(as_text=True)
    assert "pizza" not in client.get("/?search=%25").get_data(as_text=True)  # literal %, not wildcard


def test_csv_export(client):
    client.add("Expense", "2026-01-10", "Food", "10.5", "=cmd()")
    resp = client.get("/export.csv")
    assert resp.mimetype == "text/csv"
    body = resp.get_data(as_text=True)
    assert "id,date,type,category,amount,description" in body
    assert "10.50" in body and "'=cmd()" in body


def test_security_headers_and_404(client):
    resp = client.get("/")
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert "default-src 'self'" in resp.headers["Content-Security-Policy"]
    assert client.get("/missing").status_code == 404


def test_reports_page_with_data(client):
    client.add("Income", "2026-01-01", "Salary", "1000")
    client.add("Expense", "2026-01-02", "Food", "250")
    html = client.get("/reports?month=2026-01").get_data(as_text=True)
    assert "75.0%" in html
    assert re.search(r"Food</td>\s*<td[^>]*>₹250.00", html)
    assert client.get("/charts/category.png?month=2026-01").data.startswith(b"\x89PNG")
