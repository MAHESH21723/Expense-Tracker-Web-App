"""Parsers for imported transaction files (pure functions: no Flask, no database).

Two sources are supported:

* Google Pay history exported with Google Takeout ("My Activity" HTML/JSON,
  a transactions CSV, or the whole Takeout .zip).
* Generic bank statement CSV files with auto-detected (or user-mapped) columns.

Every parser returns plain dicts: ``{"date", "type", "amount_paise", "description"}``.
Account/phone numbers inside descriptions are masked, keeping the last 4 digits.
"""
import csv
import io
import json
import re
import zipfile
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from html.parser import HTMLParser

from validation import MAX_AMOUNT_PAISE, MAX_DESCRIPTION, MIN_YEAR

MAX_ROWS = 1000                      # transactions accepted per import
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # uploaded file
ZIP_MAX_MEMBERS = 10_000             # entries inspected in a zip
ZIP_MAX_MEMBER_BYTES = 25 * 1024 * 1024
ZIP_MAX_TOTAL_BYTES = 50 * 1024 * 1024
ZIP_MAX_RATIO = 200                  # uncompressed / compressed

IST = timezone(timedelta(hours=5, minutes=30))

# Starter keyword rules: (keyword, type, category). Users can edit them in the app.
DEFAULT_RULES = [
    ("swiggy", "Expense", "Food"), ("zomato", "Expense", "Food"), ("restaurant", "Expense", "Food"),
    ("cafe", "Expense", "Food"), ("dominos", "Expense", "Food"), ("mcdonald", "Expense", "Food"),
    ("kfc", "Expense", "Food"), ("blinkit", "Expense", "Food"), ("bigbasket", "Expense", "Food"),
    ("uber", "Expense", "Transport"), ("ola", "Expense", "Transport"), ("rapido", "Expense", "Transport"),
    ("irctc", "Expense", "Transport"), ("redbus", "Expense", "Transport"), ("metro", "Expense", "Transport"),
    ("petrol", "Expense", "Transport"), ("fuel", "Expense", "Transport"),
    ("amazon", "Expense", "Shopping"), ("flipkart", "Expense", "Shopping"), ("myntra", "Expense", "Shopping"),
    ("ajio", "Expense", "Shopping"), ("meesho", "Expense", "Shopping"),
    ("electricity", "Expense", "Bills"), ("recharge", "Expense", "Bills"), ("jio", "Expense", "Bills"),
    ("airtel", "Expense", "Bills"), ("vodafone", "Expense", "Bills"), ("broadband", "Expense", "Bills"),
    ("insurance", "Expense", "Bills"), ("gas", "Expense", "Bills"),
    ("netflix", "Expense", "Entertainment"), ("spotify", "Expense", "Entertainment"),
    ("bookmyshow", "Expense", "Entertainment"), ("hotstar", "Expense", "Entertainment"),
    ("udemy", "Expense", "Education"), ("coursera", "Expense", "Education"), ("tuition", "Expense", "Education"),
    ("pharmacy", "Expense", "Healthcare"), ("apollo", "Expense", "Healthcare"),
    ("hospital", "Expense", "Healthcare"), ("clinic", "Expense", "Healthcare"),
    ("salary", "Income", "Salary"), ("bonus", "Income", "Bonus"),
    ("interest", "Income", "Investment Returns"), ("dividend", "Income", "Investment Returns"),
]


class ImportFileError(ValueError):
    """The uploaded file cannot be imported (message is safe to show to the user)."""


# --------------------------------------------------------------------- helpers
_ACCOUNT_RE = re.compile(r"(?<![\w.])[Xx*\d]{6,}(?!\w)")


def mask_accounts(text):
    """Mask long digit/X runs (account, card, phone numbers), keeping the last 4 digits."""
    def repl(match):
        tail = match.group()[-4:]
        return "XXXX" + tail if tail.isdigit() else match.group()
    return _ACCOUNT_RE.sub(repl, text)


def clean_description(text, fallback=""):
    text = re.sub(r"\s+", " ", (text or "").replace("\xa0", " ")).strip()
    text = mask_accounts(text)[:MAX_DESCRIPTION].strip()
    return text or fallback


_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def _year(text):
    year = int(text)
    return year + 2000 if year < 100 else year


def _safe_date(year, month, day):
    try:
        parsed = date(year, month, day)
    except ValueError:
        return None
    return parsed.isoformat() if parsed.year >= MIN_YEAR else None


def parse_date_flexible(text):
    """Find a date in text and return ISO 'YYYY-MM-DD' (day-first for numeric dates), or None.

    Handles 2026-11-12, 12/11/2026, 12-11-26, 12 Nov 2026, 12-Nov-26, Nov 12, 2026
    and ignores any trailing time or time zone.
    """
    t = (text or "").strip()
    m = re.search(r"(?<!\d)(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?!\d)", t)
    if m:
        return _safe_date(int(m[1]), int(m[2]), int(m[3]))
    m = re.search(r"(?<!\d)(\d{1,2})[-/.](\d{1,2})[-/.](\d{4}|\d{2})(?!\d)", t)
    if m:
        return _safe_date(_year(m[3]), int(m[2]), int(m[1]))
    m = re.search(r"(?<!\d)(\d{1,2})(?:st|nd|rd|th)?[\s\-/]+([A-Za-z]{3,9})\.?,?[\s\-/]+(\d{4}|\d{2})(?!\d)", t)
    if m and m[2][:3].lower() in _MONTHS:
        return _safe_date(_year(m[3]), _MONTHS[m[2][:3].lower()], int(m[1]))
    m = re.search(r"([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})(?!\d)", t)
    if m and m[1][:3].lower() in _MONTHS:
        return _safe_date(int(m[3]), _MONTHS[m[1][:3].lower()], int(m[2]))
    return None


def parse_money(text):
    """Parse '1,234.50', '₹250', 'Rs. 99.5 Dr', '(40.00)', '-12'.

    Returns (paise, hint) with hint 'dr', 'cr' or None; None for blank/zero/invalid values.
    """
    t = (text or "").strip()
    if not t:
        return None
    hint = None
    m = re.search(r"\b(dr|cr|debit|credit)\.?\s*$", t, re.I)
    if m:
        hint = "dr" if m[1].lower().startswith("d") else "cr"
        t = t[:m.start()]
    negative = t.lstrip().startswith("-") or (t.strip().startswith("(") and t.strip().endswith(")"))
    t = re.sub(r"(?i)\b(rs|inr)\b\.?", "", t)
    t = re.sub(r"[^\d.]", "", t).strip(".")
    try:
        value = Decimal(t)
    except InvalidOperation:
        return None
    paise = int((value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) * 100).to_integral_value())
    if paise <= 0 or paise > MAX_AMOUNT_PAISE:
        return None
    if negative and hint is None:
        hint = "dr"
    return paise, hint


def decode_text(data):
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def categorise(description, trans_type, rules):
    """First match of the longest matching keyword; falls back to 'Others'."""
    text = (description or "").lower()
    for keyword, rule_type, category in sorted(rules, key=lambda r: -len(r[0])):
        if rule_type == trans_type and keyword.lower() in text:
            return category
    return "Others"


# ------------------------------------------------------------------ Google Pay
_VERB_RE = re.compile(r"^\s*(paid|sent|received)\b", re.I)
_AMT_RE = re.compile(r"(?:₹|rs\.?|inr)\s*([\d,]+(?:\.\d+)?)", re.I)
_PARTY_RE = re.compile(r"\b(to|from)\s+(.+?)(?:\s+(?:using|via|through)\b.*)?$", re.I | re.S)
_FAILED_RE = re.compile(r"\b(fail(?:ed|ure)?|cancel+ed|declined|pending|rejected|expired|reversed|unsuccessful)\b", re.I)


def _gpay_type_and_description(text):
    """'Paid to X using ...' -> ('Expense', 'Paid to X'); None when it is not a payment line."""
    m = _VERB_RE.match(text)
    if not m:
        return None, None, ""
    verb = m[1].lower()
    rest = text[m.end():]
    amount = _AMT_RE.search(rest)
    remainder = rest[amount.end():] if amount else rest
    party = _PARTY_RE.search(remainder)
    trans_type = "Income" if verb == "received" else "Expense"
    if party:
        description = f"{verb.capitalize()} {party[1].lower()} {party[2]}"
    else:
        description = f"{verb.capitalize()} via Google Pay"
    return trans_type, clean_description(description), rest


def parse_gpay_title(title, when=None):
    """Parse one 'My Activity' title line. Returns a transaction dict, 'skipped' or None (not a payment)."""
    trans_type, description, rest = _gpay_type_and_description(title)
    if trans_type is None:
        return None
    amount = _AMT_RE.search(rest)
    iso = parse_date_flexible(when) if when else None
    if _FAILED_RE.search(title) or not amount or not iso:
        return "skipped"
    money = parse_money(amount.group(0))
    if not money:
        return "skipped"
    return {"date": iso, "type": trans_type, "amount_paise": money[0], "description": description}


class _ActivityParser(HTMLParser):
    """Collects the text of every Takeout 'content-cell' div, with <br> as line breaks."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.cells, self._buf, self._depth = [], None, 0

    def handle_starttag(self, tag, attrs):
        if tag == "div":
            if self._buf is not None:
                self._depth += 1
            elif "content-cell" in (dict(attrs).get("class") or ""):
                self._buf, self._depth = [], 1
        elif tag == "br" and self._buf is not None:
            self._buf.append("\n")

    def handle_endtag(self, tag):
        if tag == "div" and self._buf is not None:
            self._depth -= 1
            if self._depth <= 0:
                self.cells.append("".join(self._buf))
                self._buf = None

    def handle_data(self, data):
        if self._buf is not None:
            self._buf.append(data)


def _parse_gpay_html(text):
    parser = _ActivityParser()
    parser.feed(text)
    parser.close()
    if parser._buf is not None:  # unterminated final cell
        parser.cells.append("".join(parser._buf))
    rows, skipped = [], 0
    for cell in parser.cells:
        lines = [ln.strip() for ln in cell.replace("\xa0", " ").split("\n") if ln.strip()]
        if not lines or not _VERB_RE.match(lines[0]):
            continue
        when = next((ln for ln in lines[1:] if parse_date_flexible(ln)), None)
        result = parse_gpay_title(" ".join(lines) if _FAILED_RE.search(" ".join(lines)) else lines[0], when)
        if isinstance(result, dict):
            rows.append(result)
        elif result == "skipped":
            skipped += 1
    return rows, skipped


def _json_when(value):
    """ISO timestamps in Takeout JSON are UTC; convert to IST so the date matches the app."""
    if not isinstance(value, str):
        return None
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    if stamp.tzinfo:
        stamp = stamp.astimezone(IST)
    return stamp.strftime("%Y-%m-%d")


def _parse_gpay_json(text):
    try:
        data = json.loads(text)
    except ValueError:
        raise ImportFileError("This JSON file could not be read.") from None
    if isinstance(data, dict):
        data = next((v for v in data.values() if isinstance(v, list)), [])
    if not isinstance(data, list):
        raise ImportFileError("Unrecognised JSON layout for Google Pay activity.")
    rows, skipped = [], 0
    for item in data:
        if not isinstance(item, dict):
            continue
        title = item.get("title") or item.get("description") or ""
        if not isinstance(title, str) or not _VERB_RE.match(title):
            continue
        result = parse_gpay_title(title, _json_when(item.get("time")))
        if isinstance(result, dict):
            rows.append(result)
        elif result == "skipped":
            skipped += 1
    return rows, skipped


def _parse_gpay_csv(text):
    reader = csv.DictReader(io.StringIO(text))
    rows, skipped = [], 0
    for raw in reader:
        rec = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items() if isinstance(v, str) or v is None}
        description = rec.get("description", "")
        trans_type, desc, _ = _gpay_type_and_description(description)
        money = parse_money(rec.get("amount", ""))
        iso = parse_date_flexible(rec.get("time") or rec.get("date") or "")
        status = rec.get("status", "")
        if trans_type is None and money and money[1] == "dr":
            trans_type, desc = "Expense", clean_description(description, "Google Pay payment")
        if trans_type is None:
            if description or money:
                skipped += 1
            continue
        if not money or not iso or _FAILED_RE.search(status) or _FAILED_RE.search(description):
            skipped += 1
            continue
        rows.append({"date": iso, "type": trans_type, "amount_paise": money[0], "description": desc})
    return rows, skipped


def _gpay_zip_members(data):
    """Read only the relevant Google Pay files of a Takeout zip, in memory and with limits."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ImportFileError("This is not a valid zip file.") from None
    members, total = [], 0
    with zf:
        infos = zf.infolist()
        if len(infos) > ZIP_MAX_MEMBERS:
            raise ImportFileError("The zip contains too many files.")
        for info in infos:
            name = info.filename.replace("\\", "/")
            if info.is_dir() or name.startswith("/") or ".." in name.split("/"):
                continue  # nothing is ever written to disk, but ignore odd paths anyway
            norm = re.sub(r"[\s_]", "", name.lower())
            base = norm.rsplit("/", 1)[-1]
            if not norm.endswith((".html", ".htm", ".json", ".csv")):
                continue
            if "googlepay" not in norm or not ("myactivity" in base or "transaction" in base):
                continue
            if info.file_size > ZIP_MAX_MEMBER_BYTES or (
                    info.compress_size and info.file_size > 1_000_000
                    and info.file_size / info.compress_size > ZIP_MAX_RATIO):
                raise ImportFileError("The zip contains a file that is too large or suspiciously compressed.")
            with zf.open(info) as fh:
                blob = fh.read(ZIP_MAX_MEMBER_BYTES + 1)  # do not trust the declared size
            total += len(blob)
            if len(blob) > ZIP_MAX_MEMBER_BYTES or total > ZIP_MAX_TOTAL_BYTES:
                raise ImportFileError("The zip contents are too large.")
            members.append((name, blob))
    if not members:
        raise ImportFileError("No Google Pay 'My Activity' or transactions file was found in the zip.")
    return members


def parse_google_pay(filename, data):
    """Parse a Takeout file (.html/.json/.csv) or the Takeout .zip. Returns (rows, skipped_count)."""
    name = (filename or "").lower()
    files = _gpay_zip_members(data) if name.endswith(".zip") else [(name, data)]
    merged, skipped, best = [], 0, Counter()
    for fname, blob in files:
        text = decode_text(blob)
        lower = fname.lower()
        if lower.endswith((".html", ".htm")):
            rows, skip = _parse_gpay_html(text)
        elif lower.endswith(".json"):
            rows, skip = _parse_gpay_json(text)
        elif lower.endswith(".csv"):
            rows, skip = _parse_gpay_csv(text)
        else:
            raise ImportFileError("Upload a .html, .json, .csv or Takeout .zip file.")
        skipped += skip
        # The same activity can appear in several exported formats: keep the largest count per entry.
        groups = defaultdict(list)
        for row in rows:
            groups[(row["date"], row["amount_paise"], row["type"], row["description"])].append(row)
        for key, items in groups.items():
            extra = len(items) - best[key]
            if extra > 0:
                merged.extend(items[:extra])
                best[key] = len(items)
    merged.sort(key=lambda r: r["date"])
    return merged, skipped


# ------------------------------------------------------------------- bank CSV
FIELDS = ("date", "description", "debit", "credit", "amount", "drcr")
_SYNONYMS = {
    "date": ["transaction date", "txn date", "tran date", "trans date", "value date", "posting date", "date"],
    "description": ["narration", "transaction remarks", "transaction details", "description", "particulars",
                    "details", "remarks"],
    "debit": ["withdrawal amt", "withdrawal amount", "debit amount", "withdrawals", "withdrawal", "debit",
              "dr amount", "paid out", "money out"],
    "credit": ["deposit amt", "deposit amount", "credit amount", "deposits", "deposit", "credit",
               "cr amount", "paid in", "money in"],
    "amount": ["transaction amount", "txn amount", "amount"],
    "drcr": ["dr cr", "cr dr", "drcr", "debit credit", "transaction type", "txn type", "type"],
}


def _norm(cell):
    return re.sub(r"[^a-z0-9]+", " ", (cell or "").lower()).strip()


def read_csv_table(text):
    """Parse CSV text (delimiter auto-detected) into a list of rows of strings."""
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    rows = [row for row in csv.reader(io.StringIO(text), dialect)]
    return [row for row in rows if any(cell.strip() for cell in row)]


def _match_columns(header):
    cells = [_norm(c) for c in header]
    mapping, used = {}, set()
    for exact in (True, False):  # exact names for every field first, then whole-word containment
        for field in FIELDS:
            if field in mapping:
                continue
            for synonym in _SYNONYMS[field]:
                for idx, cell in enumerate(cells):
                    if idx in used or not cell:
                        continue
                    hit = cell == synonym if exact else re.search(rf"\b{re.escape(synonym)}\b", cell)
                    if hit:
                        mapping[field] = idx
                        used.add(idx)
                        break
                if field in mapping:
                    break
    return mapping


def mapping_is_valid(mapping):
    return ("date" in mapping and "description" in mapping
            and any(f in mapping for f in ("debit", "credit", "amount")))


def detect_bank_layout(table):
    """Return (header_row_index, mapping). mapping is None when auto-detect fails."""
    best = (0, None)
    for idx, row in enumerate(table[:40]):
        mapping = _match_columns(row)
        if mapping_is_valid(mapping):
            return idx, mapping
        if "date" in mapping and best[1] is None:
            best = (idx, None)
    return best


def parse_bank_rows(table, header_row, mapping):
    """Turn a CSV table into transactions using a column mapping. Returns (rows, skipped_count)."""
    if not mapping_is_valid(mapping):
        raise ImportFileError("Choose at least the date, description and an amount (or debit/credit) column.")

    def cell(row, field):
        idx = mapping.get(field)
        return row[idx].strip() if idx is not None and idx < len(row) else ""

    rows, skipped = [], 0
    for row in table[header_row + 1:]:
        iso = parse_date_flexible(cell(row, "date"))
        if not iso:
            skipped += 1
            continue
        debit, credit = parse_money(cell(row, "debit")), parse_money(cell(row, "credit"))
        trans_type, paise = None, None
        if debit or credit:
            net = (credit[0] if credit else 0) - (debit[0] if debit else 0)
            if net:
                trans_type, paise = ("Income", net) if net > 0 else ("Expense", -net)
        else:
            single = parse_money(cell(row, "amount"))
            if single:
                paise, hint = single
                marker = _norm(cell(row, "drcr"))
                if marker[:1] == "d" or (not marker and hint == "dr"):
                    trans_type = "Expense"
                elif marker[:1] == "c" or (not marker and hint == "cr"):
                    trans_type = "Income"
                elif hint == "dr":
                    trans_type = "Expense"
                else:
                    trans_type = "Income"  # unsigned amount without Dr/Cr marker: treated as money in
        if trans_type is None or paise is None:
            skipped += 1
            continue
        rows.append({"date": iso, "type": trans_type, "amount_paise": paise,
                     "description": clean_description(cell(row, "description"), "Bank transaction")})
    return rows, skipped
