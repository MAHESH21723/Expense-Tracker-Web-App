import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import create_app  # noqa: E402


class Client:
    """Test client wrapper that handles the CSRF token."""

    def __init__(self, app):
        self.app = app
        self.http = app.test_client()

    def token(self):
        html = self.http.get("/add-expense").get_data(as_text=True)
        return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)

    def post(self, url, data=None, csrf=True, **kw):
        data = dict(data or {})
        if csrf:
            data["csrf_token"] = self.token()
        return self.http.post(url, data=data, **kw)

    def add(self, kind, date, category, amount, description=""):
        url = "/add-income" if kind == "Income" else "/add-expense"
        return self.post(url, {"date": date, "category": category, "amount": amount, "description": description})

    def get(self, *a, **kw):
        return self.http.get(*a, **kw)


@pytest.fixture
def app(tmp_path):
    return create_app({"TESTING": True, "DATABASE": str(tmp_path / "test.db"), "SECRET_KEY": "test"})


@pytest.fixture
def client(app):
    return Client(app)
