"""Tests for RuntimeLogStore and RuntimeLogHandler."""

import logging
import time

import pytest
from app.runtime_logs import RuntimeLogHandler, RuntimeLogStore


@pytest.fixture
def log_store():
    return RuntimeLogStore(max_entries=100)


def test_append_and_count(log_store):
    assert log_store.count() == 0
    log_store.append(level="INFO", logger_name="test", message="hello")
    assert log_store.count() == 1


def test_list_entries(log_store):
    log_store.append(level="INFO", logger_name="test", message="first")
    log_store.append(level="ERROR", logger_name="test", message="second")
    entries = log_store.list_entries()
    assert len(entries) == 2
    assert entries[0]["message"] == "first"
    assert entries[1]["message"] == "second"


def test_filter_by_level(log_store):
    log_store.append(level="INFO", logger_name="test", message="info msg")
    log_store.append(level="ERROR", logger_name="test", message="error msg")
    log_store.append(level="INFO", logger_name="test", message="info msg 2")

    errors = log_store.list_entries(level="ERROR")
    assert len(errors) == 1
    assert errors[0]["message"] == "error msg"


def test_filter_by_contains(log_store):
    log_store.append(level="INFO", logger_name="test", message="database connected")
    log_store.append(level="INFO", logger_name="test", message="server started")
    log_store.append(level="INFO", logger_name="test", message="database query slow")

    results = log_store.list_entries(contains="database")
    assert len(results) == 2


def test_filter_by_contains_in_logger(log_store):
    log_store.append(level="INFO", logger_name="app.ollama", message="something")
    log_store.append(level="INFO", logger_name="app.db", message="something")

    results = log_store.list_entries(contains="ollama")
    assert len(results) == 1


def test_list_entries_limit(log_store):
    for i in range(10):
        log_store.append(level="INFO", logger_name="test", message=f"msg-{i}")

    entries = log_store.list_entries(limit=3)
    assert len(entries) == 3
    # Should return last 3
    assert entries[0]["message"] == "msg-7"


def test_max_entries_ring_buffer():
    store = RuntimeLogStore(max_entries=5)
    for i in range(10):
        store.append(level="INFO", logger_name="test", message=f"msg-{i}")
    assert store.count() == 5
    entries = store.list_entries()
    assert entries[0]["message"] == "msg-5"
    assert entries[-1]["message"] == "msg-9"


def test_clear(log_store):
    log_store.append(level="INFO", logger_name="test", message="hello")
    log_store.append(level="INFO", logger_name="test", message="world")
    cleared = log_store.clear()
    assert cleared == 2
    assert log_store.count() == 0


def test_handler_emits_to_store(log_store):
    handler = RuntimeLogHandler(log_store)
    logger = logging.getLogger("test_handler_emits")
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    logger.info("test message from handler")
    assert log_store.count() == 1
    entry = log_store.list_entries()[0]
    assert entry["level"] == "INFO"
    assert "test message from handler" in entry["message"]
    logger.removeHandler(handler)


def test_timestamp_present(log_store):
    log_store.append(level="INFO", logger_name="test", message="hello")
    entry = log_store.list_entries()[0]
    assert "timestamp" in entry
    assert "T" in entry["timestamp"]  # ISO format


def test_filter_by_since(log_store):
    log_store.append(level="INFO", logger_name="test", message="old")
    time.sleep(0.05)
    # Get a timestamp after the first entry
    entries = log_store.list_entries()
    ts = entries[0]["timestamp"]
    log_store.append(level="INFO", logger_name="test", message="new")

    results = log_store.list_entries(since=ts)
    assert len(results) >= 1
    assert any(e["message"] == "new" for e in results)
