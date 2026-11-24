from app import create_app
from database import models


def test_render_and_demo_mode(tmp_path, monkeypatch):
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv("DEMO_DATA", "1")
    db = str(tmp_path / "demo.db")
    app = create_app({"TESTING": True, "DATABASE": db, "SECRET_KEY": "t"})
    assert app.config["SESSION_COOKIE_SECURE"] is True
    summary = models.get_summary(db)
    assert summary["income"] > 0 and summary["expense"] > 0
    html = app.test_client().get("/").get_data(as_text=True)
    assert "Public demo" in html
    assert app.test_client().get("/charts/category.png").data.startswith(b"\x89PNG")


def test_seed_only_when_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("DEMO_DATA", "1")
    db = str(tmp_path / "demo.db")
    create_app({"DATABASE": db, "SECRET_KEY": "t"})
    count = len(models.get_transactions(db))
    create_app({"DATABASE": db, "SECRET_KEY": "t"})  # restart: must not duplicate
    assert len(models.get_transactions(db)) == count > 0


def test_no_demo_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("DEMO_DATA", raising=False)
    monkeypatch.delenv("RENDER", raising=False)
    db = str(tmp_path / "plain.db")
    app = create_app({"DATABASE": db, "SECRET_KEY": "t"})
    assert models.get_transactions(db) == []
    assert "Public demo" not in app.test_client().get("/").get_data(as_text=True)
    assert not app.config.get("SESSION_COOKIE_SECURE")
