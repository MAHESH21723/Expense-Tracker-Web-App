import pytest

from validation import (ValidationError, clean_month, format_money, parse_amount, parse_date, savings_rate,
                        validate_transaction)


@pytest.mark.parametrize("raw,paise", [("10", 1000), ("10.5", 1050), ("0.01", 1), ("1,234.56", 123456), (" 7.00 ", 700)])
def test_parse_amount_ok(raw, paise):
    assert parse_amount(raw) == paise


@pytest.mark.parametrize("raw", ["", None, "abc", "0", "-5", "1.005", "NaN", "Infinity", "1e999", "999999999999"])
def test_parse_amount_rejected(raw):
    with pytest.raises(ValidationError):
        parse_amount(raw)


def test_decimal_exactness():
    # 0.1 + 0.2 style float errors must not occur
    assert parse_amount("0.1") + parse_amount("0.2") == parse_amount("0.3")


@pytest.mark.parametrize("raw", ["2026-02-30", "2026-13-01", "", "yesterday", "1999-12-31", "20260105"])
def test_parse_date_rejected(raw):
    with pytest.raises(ValidationError):
        parse_date(raw)


def test_parse_date_ok():
    assert parse_date("2024-02-29") == "2024-02-29"


def test_category_whitelist_per_type():
    form = {"date": "2026-01-01", "category": "Salary", "amount": "5"}
    assert validate_transaction(form, "Income")["category"] == "Salary"
    with pytest.raises(ValidationError):
        validate_transaction(form, "Expense")
    with pytest.raises(ValidationError):
        validate_transaction({**form, "category": "Hacking"}, "Income")


def test_description_limit_and_type():
    form = {"date": "2026-01-01", "category": "Food", "amount": "5", "description": "x" * 201}
    with pytest.raises(ValidationError):
        validate_transaction(form, "Expense")
    with pytest.raises(ValidationError):
        validate_transaction(form, "Gift")


def test_helpers():
    assert clean_month("2026-03") == "2026-03"
    assert clean_month("2026-13") is None and clean_month("x'; DROP") is None
    assert format_money(123456) == "₹1,234.56"
    assert format_money(-5) == "-₹0.05"
    assert savings_rate(0, 100) is None
    assert savings_rate(1000, 250) == 75.0
    assert savings_rate(1000, 1500) == -50.0
