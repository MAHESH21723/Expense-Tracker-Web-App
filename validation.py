"""Input validation and money helpers (pure functions, easy to test)."""
import re
from datetime import date as _date
from decimal import Decimal, InvalidOperation

TYPES = ("Income", "Expense")
CATEGORIES = {
    "Expense": ("Food", "Transport", "Shopping", "Bills", "Entertainment", "Education", "Healthcare", "Others"),
    "Income": ("Salary", "Freelancing", "Bonus", "Investment Returns", "Others"),
}
ALL_CATEGORIES = tuple(dict.fromkeys(c for cats in CATEGORIES.values() for c in cats))

MAX_AMOUNT_PAISE = 100_000_000_00  # 100 million rupees
MAX_DESCRIPTION = 200
MIN_YEAR = 2000
_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


class ValidationError(ValueError):
    pass


def parse_amount(raw):
    """Parse a user-entered amount into integer paise (exact, no floats)."""
    text = (raw or "").strip().replace(",", "")
    if not text:
        raise ValidationError("Amount is required.")
    try:
        value = Decimal(text)
    except InvalidOperation:
        raise ValidationError("Amount must be a valid number.") from None
    if not value.is_finite():
        raise ValidationError("Amount must be a valid number.")
    if value <= 0:
        raise ValidationError("Amount must be greater than zero.")
    paise = value * 100
    if paise != paise.to_integral_value():
        raise ValidationError("Amount can have at most 2 decimal places.")
    paise = int(paise)
    if paise > MAX_AMOUNT_PAISE:
        raise ValidationError("Amount is too large.")
    return paise


def parse_date(raw):
    text = (raw or "").strip()
    try:
        parsed = _date.fromisoformat(text)
    except ValueError:
        raise ValidationError("Date must be a valid date (YYYY-MM-DD).") from None
    if len(text) != 10 or parsed.year < MIN_YEAR:
        raise ValidationError(f"Date must be YYYY-MM-DD and no earlier than {MIN_YEAR}.")
    return parsed.isoformat()


def validate_transaction(form, trans_type=None):
    """Validate a submitted form. Returns a clean dict or raises ValidationError."""
    trans_type = trans_type or form.get("type")
    if trans_type not in TYPES:
        raise ValidationError("Type must be Income or Expense.")
    category = (form.get("category") or "").strip()
    if category not in CATEGORIES[trans_type]:
        raise ValidationError(f"Choose a valid {trans_type.lower()} category.")
    description = (form.get("description") or "").strip()
    if len(description) > MAX_DESCRIPTION:
        raise ValidationError(f"Description must be at most {MAX_DESCRIPTION} characters.")
    return {
        "date": parse_date(form.get("date")),
        "trans_type": trans_type,
        "category": category,
        "amount_paise": parse_amount(form.get("amount")),
        "description": description,
    }


def clean_month(raw):
    """Return 'YYYY-MM' if valid, else None."""
    raw = (raw or "").strip()
    return raw if _MONTH_RE.match(raw) else None


def format_money(paise):
    sign = "-" if paise < 0 else ""
    paise = abs(int(paise))
    return f"{sign}₹{paise // 100:,}.{paise % 100:02d}"


def paise_to_input(paise):
    return f"{paise // 100}.{paise % 100:02d}"


def savings_rate(income, expense):
    """Percentage of income saved (may be negative); None when there is no income."""
    if income <= 0:
        return None
    return round((income - expense) * 100 / income, 1)
