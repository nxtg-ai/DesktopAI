from types import SimpleNamespace

from app.selftest import run_selftest


def test_selftest_accepts_memory_db_path(monkeypatch):
    monkeypatch.setattr(
        "app.selftest.settings",
        SimpleNamespace(db_path=":memory:", ollama_url="http://localhost:11434", ollama_model="llama"),
    )

    report = run_selftest()

    assert report["ok"] is True
    writable = report["checks"]["db_path_writable"]
    assert writable["ok"] is True
    assert writable["path"] == ":memory:"
    assert writable["mode"] == "memory"
    sqlite_probe = report["checks"]["sqlite_probe"]
    assert sqlite_probe["ok"] is True
    assert sqlite_probe["path"] == ":memory:"


def test_selftest_accepts_relative_db_file_without_directory(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "app.selftest.settings",
        SimpleNamespace(db_path="desktopai.db", ollama_url="http://localhost:11434", ollama_model="llama"),
    )

    report = run_selftest()

    assert report["ok"] is True
    writable = report["checks"]["db_path_writable"]
    assert writable["ok"] is True
    assert writable["path"] == "desktopai.db"
    assert writable["directory"] == "."
    sqlite_probe = report["checks"]["sqlite_probe"]
    assert sqlite_probe["ok"] is True
    assert sqlite_probe["path"] == "desktopai.db"


def test_selftest_reports_sqlite_probe_failure(monkeypatch):
    class _ExplodingConnect:
        def __call__(self, *_args, **_kwargs):
            raise OSError("boom")

    monkeypatch.setattr("app.selftest.sqlite3.connect", _ExplodingConnect())
    monkeypatch.setattr(
        "app.selftest.settings",
        SimpleNamespace(db_path="desktopai.db", ollama_url="http://localhost:11434", ollama_model="llama"),
    )

    report = run_selftest()

    assert report["ok"] is False
    sqlite_probe = report["checks"]["sqlite_probe"]
    assert sqlite_probe["ok"] is False
    assert sqlite_probe["path"] == "desktopai.db"
    assert "boom" in sqlite_probe["error"]
