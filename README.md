# Expense Tracker

A personal expense and income tracker built with **Python and Flask**. It stores data in SQLite, keeps all money as exact integer paise, renders its charts on the fly with matplotlib, and can import Google Pay (Google Takeout) and bank-statement CSV exports.

## Live demo

**Live demo: [https://expense-tracker-06au.onrender.com](https://expense-tracker-06au.onrender.com)** (free hosting: the first visit after a quiet spell can take up to a minute to wake up)

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/MAHESH21723/Expense-Tracker-Web-App)

The hosted demo runs on Render's free plan with fake sample data. It is shared by every visitor, sleeps when idle, and its database resets on restart, so please don't enter real data there.

## Features

- Dashboard with income, expenses, balance and savings rate, all recalculated for the active filters.
- Add, edit and delete transactions, with a confirmation step before delete.
- Filter by month, category, type or text search; sort by date, amount, category or type.
- CSV export of the filtered list.
- Reports page with a category donut chart, monthly expense trend, income vs expense bars, an expense breakdown and a month-by-month table, for all time or a single month.
- **Import** from Google Pay (Google Takeout) and bank CSV statements, with a preview step, duplicate detection and keyword-based auto-categorisation (see below).
- Charts are drawn in memory on each request (matplotlib, Agg backend); nothing is written to disk. Empty data shows a "No data yet" chart.
- Responsive layout with light and dark themes and flash messages.

## Engineering notes

- **Exact money**: amounts are parsed with `Decimal` and stored as integer paise; no floating point in totals.
- **Validation**: amount greater than zero with at most 2 decimals and a sane maximum, real calendar dates, categories whitelisted per transaction type, description length limit.
- **Security**: CSRF token on every POST form (including delete), parameterised SQL with a whitelist for `ORDER BY`, Jinja auto-escaping, `LIKE` wildcards escaped, CSV-injection guard on export, security headers with a strict Content-Security-Policy, random per-run `SECRET_KEY` unless one is provided, debug mode off unless `FLASK_DEBUG=1`, server bound to `127.0.0.1` for local runs.
- **Structure**: app factory (`create_app`), a small data-access package, pure functions for validation and parsing so they are easy to test.

## Importing transactions

Open **Import**, choose a source and a file. You get a preview where you can untick rows, edit descriptions and change categories; nothing is saved until you press **Save selected**. A transaction with the same date, amount and description as an existing one is flagged as a duplicate and left unticked, and duplicates are skipped again on save. Account and phone numbers in descriptions are masked, keeping the last 4 digits. Uploaded files are processed in memory and never stored.

### Google Pay

Google Pay offers **no public API** for personal transaction history, which is why this app imports an export you download yourself:

1. Go to [takeout.google.com](https://takeout.google.com).
2. Click **Deselect all**, then select **Google Pay** (and/or **My Activity** with Google Pay selected).
3. Create the export and download the `.zip` when it is ready.
4. In the app, choose **Import**, source **Google Pay**, and upload the `.zip`. You can also upload an extracted `My Activity.html`, `My Activity.json` or the Google Pay transactions `.csv`.

"Paid ... to" and "Sent ... to" entries become expenses, "Received ... from" entries become income, and failed, cancelled or pending entries are skipped. For a `.zip`, only the Google Pay activity/transaction files are read, in memory, with limits on file count, size and compression ratio (zip-bomb guard); nothing is extracted to disk.

### Bank statement CSV

Upload a CSV with columns such as Date, Narration/Description, Debit/Withdrawal and Credit/Deposit, or a single Amount column with a Dr/Cr marker (a negative amount counts as a debit). Dates like `05/11/2026`, `05-11-26`, `2026-11-05` and `5 Nov 2026` are understood (numeric dates are day-first). If the columns cannot be detected, a mapping screen lets you choose them.

### Category rules

Imported transactions are categorised by keyword (for example Swiggy and Zomato map to Food, Uber and IRCTC to Transport, Amazon to Shopping, electricity and recharge to Bills). Edit the table under **Import > Category rules**; the longest matching keyword wins, and anything unmatched becomes "Others". You can also change any category in the preview.

## Tech stack

Python 3.12+, Flask, SQLite (standard library), matplotlib, pytest, gunicorn (for the hosted demo only).

## Setup and run (local)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000. The database is created automatically at `instance/expense_tracker.db`.

Optional environment variables (see `.env.example`):

| Variable | Purpose |
|---|---|
| `SECRET_KEY` | Session/CSRF signing key. A random one is generated on each start if unset. |
| `FLASK_DEBUG` | Set to `1` for debug mode (local development only). |
| `EXPENSE_DB` | Path of the SQLite file. |
| `DEMO_DATA` | `1` seeds fake sample data into an empty database and shows a demo banner. |
| `RENDER` | Set automatically on Render: enables proxy headers and secure cookies. |

## Deploying the demo to Render

`render.yaml` defines one free web service (gunicorn, `DEMO_DATA=1`, a generated `SECRET_KEY`). Use the Deploy to Render button above, or create a Blueprint from this repository in the Render dashboard. The free plan has an ephemeral filesystem, so data resets on restart.

## Tests

```powershell
pip install -r requirements-dev.txt
python -m pytest -q
```

The suite covers routes, validation, aggregation math, importers (using only made-up files in `tests/fixtures/`) and demo mode.

## Project structure

```
app.py                # create_app() factory, routes, CSRF, security headers
validation.py         # input validation and money/date helpers
importers.py          # Google Pay / bank CSV parsers, masking, auto-categorisation
charts.py             # in-memory matplotlib charts (PNG bytes)
demo_data.py          # fake sample data for the public demo
database/models.py    # SQLite schema and queries
templates/, static/   # Jinja templates, CSS, tiny JS (delete confirmation)
tests/                # pytest suite; tests/fixtures/ holds made-up sample files
render.yaml           # Render blueprint for the demo
```

## Author

Created by **Maheshwaran** ([MAHESH21723](https://github.com/MAHESH21723), kmaheshwaran9965@gmail.com).

## License

MIT, see [LICENSE](LICENSE).
