"""SQLite data access layer.

All money is stored as integer paise (1 rupee = 100 paise) so that sums are
exact; floats are never used for amounts.
"""
import sqlite3
from contextlib import closing

SORT_COLUMNS = {"date": "date", "amount": "amount_paise", "category": "category", "type": "type"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS transactions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    date         TEXT    NOT NULL,                      -- ISO YYYY-MM-DD
    type         TEXT    NOT NULL CHECK (type IN ('Income', 'Expense')),
    category     TEXT    NOT NULL,
    amount_paise INTEGER NOT NULL CHECK (amount_paise > 0),
    description  TEXT    NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_transactions_date ON transactions (date);
CREATE TABLE IF NOT EXISTS category_rules (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword  TEXT NOT NULL,                              -- lower-case substring of the description
    type     TEXT NOT NULL CHECK (type IN ('Income', 'Expense')),
    category TEXT NOT NULL,
    UNIQUE (keyword, type)
);
"""


def connect(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path):
    with closing(connect(db_path)) as conn:
        conn.executescript(SCHEMA)
        conn.commit()


def _where(month=None, category=None, trans_type=None, search=None):
    clauses, params = [], []
    if month:
        clauses.append("substr(date, 1, 7) = ?")
        params.append(month)
    if category:
        clauses.append("category = ?")
        params.append(category)
    if trans_type:
        clauses.append("type = ?")
        params.append(trans_type)
    if search:
        escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        clauses.append("(description LIKE ? ESCAPE '\\' OR category LIKE ? ESCAPE '\\')")
        params += [f"%{escaped}%", f"%{escaped}%"]
    return (" WHERE " + " AND ".join(clauses)) if clauses else "", params


def add_transaction(db_path, date, trans_type, category, amount_paise, description=""):
    with closing(connect(db_path)) as conn:
        cur = conn.execute(
            "INSERT INTO transactions (date, type, category, amount_paise, description) "
            "VALUES (?, ?, ?, ?, ?)",
            (date, trans_type, category, amount_paise, description),
        )
        conn.commit()
        return cur.lastrowid


def update_transaction(db_path, transaction_id, date, trans_type, category, amount_paise, description=""):
    with closing(connect(db_path)) as conn:
        cur = conn.execute(
            "UPDATE transactions SET date=?, type=?, category=?, amount_paise=?, description=? WHERE id=?",
            (date, trans_type, category, amount_paise, description, transaction_id),
        )
        conn.commit()
        return cur.rowcount > 0


def delete_transaction(db_path, transaction_id):
    with closing(connect(db_path)) as conn:
        cur = conn.execute("DELETE FROM transactions WHERE id = ?", (transaction_id,))
        conn.commit()
        return cur.rowcount > 0


def get_transaction(db_path, transaction_id):
    with closing(connect(db_path)) as conn:
        return conn.execute("SELECT * FROM transactions WHERE id = ?", (transaction_id,)).fetchone()


def get_transactions(db_path, sort_by="date", sort_order="desc", **filters):
    column = SORT_COLUMNS.get(sort_by, "date")  # whitelist: never interpolate user input
    direction = "ASC" if str(sort_order).lower() == "asc" else "DESC"
    where, params = _where(**filters)
    sql = f"SELECT * FROM transactions{where} ORDER BY {column} {direction}, id {direction}"
    with closing(connect(db_path)) as conn:
        return conn.execute(sql, params).fetchall()


def get_summary(db_path, **filters):
    """Totals in paise for the filtered set: income, expense and balance."""
    where, params = _where(**filters)
    sql = (
        "SELECT COALESCE(SUM(CASE WHEN type='Income'  THEN amount_paise END), 0) AS income, "
        "       COALESCE(SUM(CASE WHEN type='Expense' THEN amount_paise END), 0) AS expense "
        f"FROM transactions{where}"
    )
    with closing(connect(db_path)) as conn:
        row = conn.execute(sql, params).fetchone()
    income, expense = row["income"], row["expense"]
    return {"income": income, "expense": expense, "balance": income - expense}


def get_category_totals(db_path, trans_type="Expense", month=None):
    """[(category, paise)] sorted by amount descending."""
    where, params = _where(month=month, trans_type=trans_type)
    sql = f"SELECT category, SUM(amount_paise) AS total FROM transactions{where} GROUP BY category ORDER BY total DESC, category"
    with closing(connect(db_path)) as conn:
        return [(r["category"], r["total"]) for r in conn.execute(sql, params)]


def get_monthly_totals(db_path):
    """[{month, income, expense, balance}] in chronological order (paise)."""
    sql = (
        "SELECT substr(date, 1, 7) AS month, "
        "       COALESCE(SUM(CASE WHEN type='Income'  THEN amount_paise END), 0) AS income, "
        "       COALESCE(SUM(CASE WHEN type='Expense' THEN amount_paise END), 0) AS expense "
        "FROM transactions GROUP BY month ORDER BY month"
    )
    with closing(connect(db_path)) as conn:
        rows = conn.execute(sql).fetchall()
    return [
        {"month": r["month"], "income": r["income"], "expense": r["expense"], "balance": r["income"] - r["expense"]}
        for r in rows
    ]


def existing_keys(db_path):
    """Set of (date, amount_paise, description) used to detect duplicate imports."""
    with closing(connect(db_path)) as conn:
        return {(r[0], r[1], r[2]) for r in conn.execute("SELECT date, amount_paise, description FROM transactions")}


def add_transactions(db_path, rows):
    """Insert many validated rows in one transaction; returns the count."""
    data = [(r["date"], r["trans_type"], r["category"], r["amount_paise"], r["description"]) for r in rows]
    with closing(connect(db_path)) as conn:
        conn.executemany(
            "INSERT INTO transactions (date, type, category, amount_paise, description) VALUES (?, ?, ?, ?, ?)", data)
        conn.commit()
    return len(data)


def seed_rules(db_path, rules):
    """Insert the default keyword rules when the rules table is empty."""
    with closing(connect(db_path)) as conn:
        if conn.execute("SELECT COUNT(*) FROM category_rules").fetchone()[0] == 0:
            conn.executemany("INSERT OR IGNORE INTO category_rules (keyword, type, category) VALUES (?, ?, ?)", rules)
            conn.commit()


def get_rules(db_path):
    with closing(connect(db_path)) as conn:
        return conn.execute("SELECT * FROM category_rules ORDER BY type DESC, category, keyword").fetchall()


def add_rule(db_path, keyword, trans_type, category):
    with closing(connect(db_path)) as conn:
        conn.execute(
            "INSERT INTO category_rules (keyword, type, category) VALUES (?, ?, ?) "
            "ON CONFLICT (keyword, type) DO UPDATE SET category = excluded.category",
            (keyword, trans_type, category))
        conn.commit()


def delete_rule(db_path, rule_id):
    with closing(connect(db_path)) as conn:
        cur = conn.execute("DELETE FROM category_rules WHERE id = ?", (rule_id,))
        conn.commit()
        return cur.rowcount > 0


def get_months(db_path):
    with closing(connect(db_path)) as conn:
        return [r[0] for r in conn.execute("SELECT DISTINCT substr(date, 1, 7) FROM transactions ORDER BY 1 DESC")]
