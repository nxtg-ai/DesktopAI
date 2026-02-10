"""Tests for the NotificationStore."""

import os

os.environ.setdefault("BACKEND_DB_PATH", ":memory:")

from datetime import datetime, timedelta, timezone

import pytest
from app.notifications import NotificationStore


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def store():
    return NotificationStore(path=":memory:", max_notifications=200)


@pytest.mark.anyio
async def test_create_notification(store):
    n = await store.create(type="info", title="Test", message="Hello", rule="test_rule")
    assert n["notification_id"]
    assert n["type"] == "info"
    assert n["title"] == "Test"
    assert n["read_at"] is None


@pytest.mark.anyio
async def test_list_notifications(store):
    await store.create(type="info", title="A", message="a", rule="r1")
    await store.create(type="warning", title="B", message="b", rule="r2")

    items = await store.list_notifications()
    assert len(items) == 2
    # Most recent first
    assert items[0]["title"] == "B"


@pytest.mark.anyio
async def test_unread_count(store):
    await store.create(type="info", title="A", message="a", rule="r")
    await store.create(type="info", title="B", message="b", rule="r")

    assert await store.unread_count() == 2

    items = await store.list_notifications()
    await store.mark_read(items[0]["notification_id"])
    assert await store.unread_count() == 1


@pytest.mark.anyio
async def test_mark_read(store):
    n = await store.create(type="info", title="T", message="m", rule="r")
    assert await store.mark_read(n["notification_id"]) is True
    # Double mark returns False
    assert await store.mark_read(n["notification_id"]) is False

    items = await store.list_notifications()
    assert items[0]["read_at"] is not None


@pytest.mark.anyio
async def test_delete_notification(store):
    n = await store.create(type="info", title="T", message="m", rule="r")
    assert await store.delete(n["notification_id"]) is True
    assert await store.delete(n["notification_id"]) is False

    items = await store.list_notifications()
    assert len(items) == 0


@pytest.mark.anyio
async def test_retention(store):
    small_store = NotificationStore(path=":memory:", max_notifications=2)
    await small_store.create(type="info", title="A", message="a", rule="r")
    await small_store.create(type="info", title="B", message="b", rule="r")
    await small_store.create(type="info", title="C", message="c", rule="r")

    items = await small_store.list_notifications()
    assert len(items) == 2
    titles = {n["title"] for n in items}
    assert "A" not in titles  # oldest should be gone


@pytest.mark.anyio
async def test_expired_notifications_cleaned(store):
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    await store.create(type="info", title="Expired", message="gone", rule="r", expires_at=past)
    await store.create(type="info", title="Valid", message="stays", rule="r")

    items = await store.list_notifications()
    assert len(items) == 1
    assert items[0]["title"] == "Valid"


@pytest.mark.anyio
async def test_list_unread_only(store):
    n1 = await store.create(type="info", title="Read", message="r", rule="r")
    await store.create(type="info", title="Unread", message="u", rule="r")
    await store.mark_read(n1["notification_id"])

    unread = await store.list_notifications(unread_only=True)
    assert len(unread) == 1
    assert unread[0]["title"] == "Unread"
