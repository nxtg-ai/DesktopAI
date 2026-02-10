"""Tests for the selftest module."""

import os

os.environ.setdefault("BACKEND_DB_PATH", ":memory:")

from app.selftest import _is_memory_db_path, run_selftest


def test_is_memory_db_path_memory():
    assert _is_memory_db_path(":memory:") is True


def test_is_memory_db_path_file_memory():
    assert _is_memory_db_path("file::memory:") is True


def test_is_memory_db_path_file_memory_shared():
    assert _is_memory_db_path("file::memory:?cache=shared") is True


def test_is_memory_db_path_regular():
    assert _is_memory_db_path("/tmp/test.db") is False


def test_is_memory_db_path_empty():
    assert _is_memory_db_path("") is False


def test_run_selftest_returns_ok():
    result = run_selftest()
    assert result["ok"] is True
    assert "checks" in result
    assert "ts" in result
    assert "notes" in result


def test_run_selftest_checks_present():
    result = run_selftest()
    checks = result["checks"]
    assert "db_path_writable" in checks
    assert "sqlite_probe" in checks
    assert "ollama_config" in checks
    assert "action_executor" in checks


def test_run_selftest_db_writable():
    result = run_selftest()
    assert result["checks"]["db_path_writable"]["ok"] is True


def test_run_selftest_sqlite_probe():
    result = run_selftest()
    assert result["checks"]["sqlite_probe"]["ok"] is True


def test_run_selftest_executor_available():
    result = run_selftest()
    executor = result["checks"]["action_executor"]
    assert executor["ok"] is True
    assert executor["mode"] == "simulated"
