"""Tests for CommandHistoryStore and _compute_undo reversibility logic."""

import os

os.environ.setdefault("BACKEND_DB_PATH", ":memory:")

import pytest
from app.command_history import CommandHistoryStore, _compute_undo


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def store():
    return CommandHistoryStore(path=":memory:", max_entries=500)


# ── _compute_undo unit tests ──────────────────────────────────────────────────


def test_compute_undo_focus_window():
    """focus_window with a previous window returns a focus to that window."""
    reversible, undo_action, undo_params = _compute_undo(
        "focus_window", {"title": "Chrome"}, prev_window="Untitled - Notepad"
    )
    assert reversible is True
    assert undo_action == "focus_window"
    assert undo_params == {"title": "Untitled - Notepad"}


def test_compute_undo_focus_window_no_prev():
    """focus_window without a previous window is not reversible."""
    reversible, undo_action, undo_params = _compute_undo(
        "focus_window", {"title": "Chrome"}, prev_window=None
    )
    assert reversible is False
    assert undo_action is None
    assert undo_params is None


def test_compute_undo_type_text():
    """type_text is reversed by sending ctrl+z."""
    reversible, undo_action, undo_params = _compute_undo(
        "type_text", {"text": "hello world"}
    )
    assert reversible is True
    assert undo_action == "send_keys"
    assert undo_params == {"keys": "ctrl+z"}


def test_compute_undo_scroll_down():
    """scroll down is reversed by scroll up with the same amount."""
    reversible, undo_action, undo_params = _compute_undo(
        "scroll", {"direction": "down", "amount": 5}
    )
    assert reversible is True
    assert undo_action == "scroll"
    assert undo_params == {"direction": "up", "amount": 5}


def test_compute_undo_scroll_up():
    """scroll up is reversed by scroll down with the same amount."""
    reversible, undo_action, undo_params = _compute_undo(
        "scroll", {"direction": "up", "amount": 2}
    )
    assert reversible is True
    assert undo_action == "scroll"
    assert undo_params == {"direction": "down", "amount": 2}


def test_compute_undo_send_keys_not_reversible():
    """send_keys is not reversible."""
    reversible, undo_action, undo_params = _compute_undo(
        "send_keys", {"keys": "ctrl+c"}
    )
    assert reversible is False
    assert undo_action is None
    assert undo_params is None


def test_compute_undo_click_not_reversible():
    """click is not reversible."""
    reversible, undo_action, undo_params = _compute_undo(
        "click", {"name": "Save"}
    )
    assert reversible is False
    assert undo_action is None


def test_compute_undo_type_in_window():
    """_type_in_window with a window is reversed by focus + ctrl+z."""
    reversible, undo_action, undo_params = _compute_undo(
        "_type_in_window", {"text": "hello", "window": "Notepad"}
    )
    assert reversible is True
    assert undo_action == "_undo_type_in_window"
    assert undo_params == {"window": "Notepad"}


def test_compute_undo_type_in_window_no_window():
    """_type_in_window without a window falls back to send_keys ctrl+z."""
    reversible, undo_action, undo_params = _compute_undo(
        "_type_in_window", {"text": "hello", "window": ""}
    )
    assert reversible is True
    assert undo_action == "send_keys"
    assert undo_params == {"keys": "ctrl+z"}


def test_compute_undo_scroll_in_window():
    """_scroll_in_window is reversed by focusing same window and scrolling opposite."""
    reversible, undo_action, undo_params = _compute_undo(
        "_scroll_in_window", {"direction": "down", "amount": 3, "window": "Notepad"}
    )
    assert reversible is True
    assert undo_action == "_scroll_in_window"
    assert undo_params == {"window": "Notepad", "direction": "up", "amount": 3}


def test_compute_undo_open_application_not_reversible():
    """open_application is not reversible."""
    reversible, undo_action, undo_params = _compute_undo(
        "open_application", {"application": "notepad"}
    )
    assert reversible is False
    assert undo_action is None
    assert undo_params is None


# ── CommandHistoryStore async tests ──────────────────────────────────────────


@pytest.mark.anyio
async def test_record_returns_entry_id(store):
    """record() returns a UUID string entry_id."""
    entry_id = await store.record("type_text", {"text": "hello"})
    assert isinstance(entry_id, str)
    assert len(entry_id) == 36  # UUID


@pytest.mark.anyio
async def test_record_and_retrieve(store):
    """Recorded entry appears in recent() with correct fields."""
    await store.record("type_text", {"text": "hello"})
    entries = await store.recent()
    assert len(entries) == 1
    entry = entries[0]
    assert entry["action"] == "type_text"
    assert entry["parameters"] == {"text": "hello"}
    assert entry["reversible"] is True
    assert entry["undone"] is False


@pytest.mark.anyio
async def test_last_undoable_returns_most_recent_reversible(store):
    """last_undoable() returns the most recent reversible, not-yet-undone entry."""
    # open_application is not reversible
    await store.record("open_application", {"application": "notepad"})
    # type_text is reversible — should be the last undoable
    await store.record("type_text", {"text": "hello"})

    entry = await store.last_undoable()
    assert entry is not None
    assert entry["action"] == "type_text"
    assert entry["undo_action"] == "send_keys"
    assert entry["undo_parameters"] == {"keys": "ctrl+z"}


@pytest.mark.anyio
async def test_last_undoable_returns_none_when_empty(store):
    """last_undoable() returns None when there are no undoable entries."""
    entry = await store.last_undoable()
    assert entry is None


@pytest.mark.anyio
async def test_last_undoable_skips_non_reversible(store):
    """last_undoable() skips non-reversible entries and returns None if none exist."""
    await store.record("open_application", {"application": "notepad"})
    await store.record("click", {"name": "Save"})
    await store.record("send_keys", {"keys": "ctrl+c"})
    entry = await store.last_undoable()
    assert entry is None


@pytest.mark.anyio
async def test_mark_undone_excludes_from_last_undoable(store):
    """After marking an entry as undone, last_undoable() no longer returns it."""
    entry_id = await store.record("type_text", {"text": "hello"})
    await store.mark_undone(entry_id)

    entry = await store.last_undoable()
    assert entry is None


@pytest.mark.anyio
async def test_mark_undone_sets_flag(store):
    """mark_undone() sets undone=True on the entry visible in recent()."""
    entry_id = await store.record("type_text", {"text": "hello"})
    await store.mark_undone(entry_id)

    entries = await store.recent()
    assert entries[0]["undone"] is True


@pytest.mark.anyio
async def test_max_entries_pruning(store):
    """Entries beyond max_entries are pruned (oldest removed)."""
    small_store = CommandHistoryStore(path=":memory:", max_entries=3)
    for i in range(5):
        await small_store.record("type_text", {"text": f"msg-{i}"})

    entries = await small_store.recent(limit=10)
    assert len(entries) == 3
    # Should keep the newest 3 (msg-4, msg-3, msg-2 in desc order)
    texts = [e["parameters"]["text"] for e in entries]
    assert "msg-0" not in texts
    assert "msg-1" not in texts


@pytest.mark.anyio
async def test_clear_removes_all(store):
    """clear() deletes all entries from the store."""
    await store.record("type_text", {"text": "hello"})
    await store.record("scroll", {"direction": "down", "amount": 3})
    await store.clear()

    entries = await store.recent()
    assert entries == []

    entry = await store.last_undoable()
    assert entry is None


@pytest.mark.anyio
async def test_multi_step_group_recording(store):
    """Entries with the same multi_step_group are stored and retrievable."""
    group_id = "test-group-uuid"
    await store.record("open_application", {"application": "notepad"}, multi_step_group=group_id)
    await store.record("type_text", {"text": "hello"}, multi_step_group=group_id)

    entries = await store.recent()
    assert len(entries) == 2
    groups = {e["multi_step_group"] for e in entries}
    assert group_id in groups


@pytest.mark.anyio
async def test_recent_limit_respected(store):
    """recent(limit=N) returns at most N entries."""
    for i in range(10):
        await store.record("type_text", {"text": f"msg-{i}"})

    entries = await store.recent(limit=5)
    assert len(entries) == 5


@pytest.mark.anyio
async def test_recent_ordering_newest_first(store):
    """recent() returns entries newest-first."""
    await store.record("type_text", {"text": "first"})
    await store.record("type_text", {"text": "second"})

    entries = await store.recent()
    # Newest should be first
    assert entries[0]["parameters"]["text"] == "second"
    assert entries[1]["parameters"]["text"] == "first"


@pytest.mark.anyio
async def test_result_stored_and_retrieved(store):
    """result dict is stored and retrieved correctly."""
    result = {"status": "ok", "output": "done"}
    await store.record("type_text", {"text": "hello"}, result=result)

    entries = await store.recent()
    assert entries[0]["result"] == result


@pytest.mark.anyio
async def test_prev_window_used_for_focus_window_undo(store):
    """focus_window undo uses prev_window from record call."""
    await store.record(
        "focus_window",
        {"title": "Chrome"},
        prev_window="Untitled - Notepad",
    )

    entry = await store.last_undoable()
    assert entry is not None
    assert entry["undo_action"] == "focus_window"
    assert entry["undo_parameters"] == {"title": "Untitled - Notepad"}
