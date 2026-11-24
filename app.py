"""Expense Tracker: a small Flask app (SQLite, matplotlib charts rendered in memory)."""
import csv
import hmac
import io
import os
import secrets

from werkzeug.middleware.proxy_fix import ProxyFix
from flask import (Flask, Response, abort, flash, redirect, render_template, request, session, url_for)

import charts
import demo_data
import importers
from database import models
from validation import (ALL_CATEGORIES, CATEGORIES, TYPES, ValidationError, clean_month, format_money,
                        paise_to_input, savings_rate, validate_transaction)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def create_app(config=None):
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY") or secrets.token_hex(32),  # random per run if unset
        DATABASE=os.environ.get("EXPENSE_DB") or os.path.join(BASE_DIR, "instance", "expense_tracker.db"),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        MAX_CONTENT_LENGTH=importers.MAX_UPLOAD_BYTES + 1024 * 1024,
        MAX_FORM_MEMORY_SIZE=4 * 1024 * 1024,   # preview/commit forms carry up to MAX_ROWS rows
        MAX_FORM_PARTS=10_000,
    )
    if config:
        app.config.update(config)

    os.makedirs(os.path.dirname(os.path.abspath(app.config["DATABASE"])), exist_ok=True)
    models.init_db(app.config["DATABASE"])
    models.seed_rules(app.config["DATABASE"], importers.DEFAULT_RULES)

    # Hosted demo support (Render): trust the proxy headers, use secure cookies, seed fake data.
    if os.environ.get("RENDER"):
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
        app.config["SESSION_COOKIE_SECURE"] = True
    if app.config.get("DEMO_DATA") is None:
        app.config["DEMO_DATA"] = os.environ.get("DEMO_DATA") == "1"
    if app.config["DEMO_DATA"]:
        demo_data.seed_demo_data(app.config["DATABASE"])

    def db():
        return app.config["DATABASE"]

    # ---- CSRF protection -------------------------------------------------
    def csrf_token():
        if "csrf" not in session:
            session["csrf"] = secrets.token_hex(16)
        return session["csrf"]

    @app.before_request
    def check_csrf():
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            sent = request.form.get("csrf_token", "").encode()
            expected = session.get("csrf", "").encode()
            if not sent or not hmac.compare_digest(sent, expected):
                abort(400, "Invalid or missing CSRF token.")

    @app.after_request
    def security_headers(resp):
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "same-origin"
        resp.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'"
        return resp

    app.jinja_env.globals.update(csrf_token=csrf_token, money=format_money)

    @app.context_processor
    def inject_demo():
        return {"demo_mode": app.config["DEMO_DATA"]}

    @app.errorhandler(400)
    @app.errorhandler(404)
    @app.errorhandler(413)
    def client_error(err):
        return render_template("error.html", error=err), err.code

    # ---- helpers ---------------------------------------------------------
    def read_filters():
        trans_type = request.args.get("type")
        category = request.args.get("category")
        return {
            "month": clean_month(request.args.get("month")),
            "category": category if category in ALL_CATEGORIES else None,
            "trans_type": trans_type if trans_type in TYPES else None,
            "search": (request.args.get("search") or "").strip()[:100] or None,
        }

    def render_form(template_type, values=None, editing=None, status=200):
        return render_template(
            "form.html", trans_type=template_type, categories=CATEGORIES[template_type],
            values=values or {}, editing=editing,
        ), status

    # ---- routes ----------------------------------------------------------
    @app.route("/")
    def dashboard():
        filters = read_filters()
        sort_by = request.args.get("sort_by", "date")
        sort_order = request.args.get("sort_order", "desc")
        rows = models.get_transactions(db(), sort_by=sort_by, sort_order=sort_order, **filters)
        summary = models.get_summary(db(), **filters)
        return render_template(
            "index.html", transactions=rows, summary=summary, filters=filters,
            months=models.get_months(db()), categories=ALL_CATEGORIES, types=TYPES,
            sort_by=sort_by, sort_order=sort_order,
            rate=savings_rate(summary["income"], summary["expense"]),
        )

    def handle_new(trans_type):
        if request.method == "POST":
            try:
                data = validate_transaction(request.form, trans_type)
            except ValidationError as exc:
                flash(str(exc), "danger")
                return render_form(trans_type, request.form, status=400)
            models.add_transaction(db(), **data)
            flash(f"{trans_type} added.", "success")
            return redirect(url_for("dashboard"))
        return render_form(trans_type)

    @app.route("/add-income", methods=["GET", "POST"])
    def add_income():
        return handle_new("Income")

    @app.route("/add-expense", methods=["GET", "POST"])
    def add_expense():
        return handle_new("Expense")

    @app.route("/transactions/<int:transaction_id>/edit", methods=["GET", "POST"])
    def edit(transaction_id):
        row = models.get_transaction(db(), transaction_id)
        if row is None:
            abort(404)
        trans_type = row["type"]
        if request.method == "POST":
            try:
                data = validate_transaction(request.form, trans_type)
            except ValidationError as exc:
                flash(str(exc), "danger")
                return render_form(trans_type, request.form, editing=row, status=400)
            models.update_transaction(db(), transaction_id, **data)
            flash("Transaction updated.", "success")
            return redirect(url_for("dashboard"))
        values = {"date": row["date"], "category": row["category"],
                  "amount": paise_to_input(row["amount_paise"]), "description": row["description"]}
        return render_form(trans_type, values, editing=row)

    @app.route("/transactions/<int:transaction_id>/delete", methods=["POST"])
    def delete(transaction_id):
        if models.delete_transaction(db(), transaction_id):
            flash("Transaction deleted.", "success")
        else:
            abort(404)
        return redirect(url_for("dashboard"))

    @app.route("/export.csv")
    def export_csv():
        rows = models.get_transactions(db(), **read_filters())
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["id", "date", "type", "category", "amount", "description"])
        for r in rows:
            desc = r["description"]
            if desc[:1] in ("=", "+", "-", "@", "\t", "\r"):  # neutralise spreadsheet formula injection
                desc = "'" + desc
            writer.writerow([r["id"], r["date"], r["type"], r["category"], paise_to_input(r["amount_paise"]), desc])
        return Response(buf.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": "attachment; filename=transactions.csv"})

    # ---- import (Google Takeout / bank CSV) ---------------------------------
    def import_error(message, status=400):
        flash(message, "danger")
        return render_template("import.html"), status

    def preview_page(rows, skipped, source):
        """Annotate parsed rows with a suggested category and a duplicate flag, then render the preview."""
        rules = [(r["keyword"], r["type"], r["category"]) for r in models.get_rules(db())]
        seen = models.existing_keys(db())
        truncated = len(rows) > importers.MAX_ROWS
        rows = rows[: importers.MAX_ROWS]
        for row in rows:
            row["category"] = importers.categorise(row["description"], row["type"], rules)
            key = (row["date"], row["amount_paise"], row["description"])
            row["duplicate"] = key in seen
            seen.add(key)
            row["amount"] = paise_to_input(row["amount_paise"])
        return render_template("import_preview.html", rows=rows, skipped=skipped, source=source,
                               truncated=truncated, categories=CATEGORIES,
                               new_count=sum(1 for r in rows if not r["duplicate"]))

    @app.route("/import")
    def import_page():
        return render_template("import.html")

    @app.route("/import/preview", methods=["POST"])
    def import_preview():
        source = request.form.get("source")
        if "csv_text" in request.form:  # second step of the bank CSV flow: the user mapped columns
            text = request.form["csv_text"]
            table = importers.read_csv_table(text)
            try:
                header_row = int(request.form.get("header_row", "0"))
                mapping = {}
                for field in importers.FIELDS:
                    value = request.form.get(f"map_{field}", "")
                    if value != "":
                        index = int(value)
                        if not 0 <= index < max(len(r) for r in table):
                            raise ValueError
                        mapping[field] = index
                if not 0 <= header_row < len(table):
                    raise ValueError
            except (ValueError, IndexError):
                return import_error("Invalid column mapping.")
            if not importers.mapping_is_valid(mapping):
                flash("Choose the date, description and an amount (or debit/credit) column.", "danger")
                return render_template("import_mapping.html", table=table, header_row=header_row,
                                       text=text, fields=importers.FIELDS, selected=mapping), 400
            rows, skipped = importers.parse_bank_rows(table, header_row, mapping)
            return preview_page(rows, skipped, "bank statement") if rows else import_error(
                "No transactions were found with that mapping.")

        upload = request.files.get("file")
        if source not in ("googlepay", "bank") or not upload or not upload.filename:
            return import_error("Choose a source and a file to upload.")
        data = upload.read(importers.MAX_UPLOAD_BYTES + 1)
        if len(data) > importers.MAX_UPLOAD_BYTES:
            return import_error("That file is too large (10 MB maximum).", 413)
        try:
            if source == "googlepay":
                rows, skipped = importers.parse_google_pay(upload.filename, data)
                label = "Google Pay"
            else:
                if upload.filename.lower().endswith(".zip"):
                    raise importers.ImportFileError("Bank statements must be uploaded as a .csv file.")
                text = importers.decode_text(data)
                table = importers.read_csv_table(text)
                if not table:
                    raise importers.ImportFileError("The CSV file is empty.")
                header_row, mapping = importers.detect_bank_layout(table)
                if mapping is None:
                    flash("Could not detect the columns automatically. Please map them below.", "danger")
                    return render_template("import_mapping.html", table=table, header_row=header_row,
                                           text=text, fields=importers.FIELDS, selected={}), 200
                rows, skipped = importers.parse_bank_rows(table, header_row, mapping)
                label = "bank statement"
        except importers.ImportFileError as exc:
            return import_error(str(exc))
        if not rows:
            return import_error("No importable transactions were found in that file.")
        return preview_page(rows, skipped, label)

    @app.route("/import/commit", methods=["POST"])
    def import_commit():
        try:
            count = min(int(request.form.get("count", "0")), importers.MAX_ROWS)
        except ValueError:
            abort(400, "Invalid import form.")
        known = models.existing_keys(db())
        accepted, duplicates, invalid = [], 0, 0
        for i in range(count):
            if f"include-{i}" not in request.form:
                continue
            fields = {name: request.form.get(f"{name}-{i}", "") for name in
                      ("date", "type", "category", "amount", "description")}
            try:
                data = validate_transaction(fields, fields["type"])
            except ValidationError:
                invalid += 1
                continue
            key = (data["date"], data["amount_paise"], data["description"])
            if key in known:
                duplicates += 1
                continue
            known.add(key)
            accepted.append(data)
        if accepted:
            models.add_transactions(db(), accepted)
        message = f"Imported {len(accepted)} transaction(s)."
        if duplicates:
            message += f" Skipped {duplicates} duplicate(s)."
        if invalid:
            message += f" {invalid} row(s) were invalid and skipped."
        flash(message, "success" if accepted else "danger")
        return redirect(url_for("dashboard" if accepted else "import_page"))

    @app.route("/import/rules", methods=["GET", "POST"])
    def import_rules():
        if request.method == "POST":
            keyword = " ".join((request.form.get("keyword") or "").lower().split())
            trans_type = request.form.get("type")
            category = request.form.get("category")
            if not 2 <= len(keyword) <= 40 or trans_type not in TYPES or category not in CATEGORIES[trans_type]:
                flash("Enter a keyword (2-40 characters), a type and a category valid for that type.", "danger")
                return render_template("rules.html", rules=models.get_rules(db()), categories=CATEGORIES,
                                       types=TYPES), 400
            models.add_rule(db(), keyword, trans_type, category)
            flash("Rule saved.", "success")
            return redirect(url_for("import_rules"))
        return render_template("rules.html", rules=models.get_rules(db()), categories=CATEGORIES, types=TYPES)

    @app.route("/import/rules/<int:rule_id>/delete", methods=["POST"])
    def delete_rule(rule_id):
        if not models.delete_rule(db(), rule_id):
            abort(404)
        flash("Rule deleted.", "success")
        return redirect(url_for("import_rules"))

    @app.route("/reports")
    def reports():
        month = clean_month(request.args.get("month"))
        summary = models.get_summary(db(), month=month)
        expense_cats = models.get_category_totals(db(), "Expense", month)
        total_exp = sum(p for _, p in expense_cats)
        breakdown = [{"category": c, "amount": p, "pct": round(p * 100 / total_exp, 1)} for c, p in expense_cats]
        return render_template(
            "reports.html", month=month, months=models.get_months(db()), summary=summary,
            rate=savings_rate(summary["income"], summary["expense"]), breakdown=breakdown,
            monthly=models.get_monthly_totals(db()),
        )

    @app.route("/charts/<name>.png")
    def chart(name):
        month = clean_month(request.args.get("month"))
        if name == "category":
            png = charts.category_chart(models.get_category_totals(db(), "Expense", month))
        elif name == "trend":
            png = charts.trend_chart(models.get_monthly_totals(db()))
        elif name == "income-expense":
            png = charts.income_expense_chart(models.get_monthly_totals(db()))
        else:
            abort(404)
        return Response(png, mimetype="image/png", headers={"Cache-Control": "no-store"})

    return app


if __name__ == "__main__":
    # Local use only: bound to loopback; debug is opt-in via FLASK_DEBUG=1.
    create_app().run(host="127.0.0.1", port=5000, debug=os.environ.get("FLASK_DEBUG") == "1")
