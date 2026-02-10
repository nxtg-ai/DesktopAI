"""Tests for the ChatMemoryStore multi-turn conversation persistence."""

import os

os.environ.setdefault("BACKEND_DB_PATH", ":memory:")

import asyncio

import pytest
from app.chat_memory import ChatMemoryStore


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def store():
    return ChatMemoryStore(path=":memory:", max_conversations=50, max_messages_per_conversation=100)


@pytest.mark.anyio
async def test_create_conversation(store):
    cid = await store.create_conversation()
    assert isinstance(cid, str)
    assert len(cid) == 36  # UUID


@pytest.mark.anyio
async def test_save_and_get_messages(store):
    cid = await store.create_conversation()
    await store.save_message(cid, "user", "Hello")
    await store.save_message(cid, "assistant", "Hi there!")

    messages = await store.get_messages(cid)
    assert len(messages) == 2
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "Hello"
    assert messages[1]["role"] == "assistant"
    assert messages[1]["content"] == "Hi there!"


@pytest.mark.anyio
async def test_message_ordering(store):
    cid = await store.create_conversation()
    for i in range(5):
        await store.save_message(cid, "user", f"msg-{i}")

    messages = await store.get_messages(cid)
    assert len(messages) == 5
    for i, msg in enumerate(messages):
        assert msg["content"] == f"msg-{i}"


@pytest.mark.anyio
async def test_list_conversations_ordered_by_updated(store):
    cid1 = await store.create_conversation("First")
    cid2 = await store.create_conversation("Second")
    # Update first conversation so it becomes most recent
    await store.save_message(cid1, "user", "update")

    convos = await store.list_conversations()
    assert len(convos) == 2
    assert convos[0]["conversation_id"] == cid1  # most recently updated
    assert convos[1]["conversation_id"] == cid2


@pytest.mark.anyio
async def test_delete_conversation_cascades_messages(store):
    cid = await store.create_conversation()
    await store.save_message(cid, "user", "Hello")
    await store.save_message(cid, "assistant", "Hi")

    deleted = await store.delete_conversation(cid)
    assert deleted is True

    conv = await store.get_conversation(cid)
    assert conv is None

    messages = await store.get_messages(cid)
    assert messages == []


@pytest.mark.anyio
async def test_get_nonexistent_conversation(store):
    conv = await store.get_conversation("nonexistent-id")
    assert conv is None


@pytest.mark.anyio
async def test_retention_deletes_oldest(store):
    small_store = ChatMemoryStore(path=":memory:", max_conversations=2, max_messages_per_conversation=100)
    cid1 = await small_store.create_conversation("oldest")
    await small_store.save_message(cid1, "user", "a")
    cid2 = await small_store.create_conversation("middle")
    await small_store.save_message(cid2, "user", "b")
    cid3 = await small_store.create_conversation("newest")
    await small_store.save_message(cid3, "user", "c")

    convos = await small_store.list_conversations()
    assert len(convos) == 2
    ids = {c["conversation_id"] for c in convos}
    assert cid1 not in ids  # oldest should have been deleted


@pytest.mark.anyio
async def test_max_messages_per_conversation(store):
    small_store = ChatMemoryStore(path=":memory:", max_conversations=50, max_messages_per_conversation=3)
    cid = await small_store.create_conversation()
    for i in range(5):
        await small_store.save_message(cid, "user", f"msg-{i}")

    messages = await small_store.get_messages(cid)
    assert len(messages) == 3
    # Should keep the newest 3
    assert messages[0]["content"] == "msg-2"
    assert messages[2]["content"] == "msg-4"


@pytest.mark.anyio
async def test_desktop_context_stored(store):
    cid = await store.create_conversation()
    ctx = {"window_title": "Outlook", "process_exe": "OUTLOOK.EXE"}
    await store.save_message(cid, "user", "Hello", desktop_context=ctx)

    messages = await store.get_messages(cid)
    assert messages[0]["desktop_context"] == ctx


@pytest.mark.anyio
async def test_conversation_message_count_updated(store):
    cid = await store.create_conversation()
    await store.save_message(cid, "user", "one")
    await store.save_message(cid, "assistant", "two")

    conv = await store.get_conversation(cid)
    assert conv is not None
    assert conv["message_count"] == 2


@pytest.mark.anyio
async def test_empty_conversation_list(store):
    convos = await store.list_conversations()
    assert convos == []


@pytest.mark.anyio
async def test_concurrent_access(store):
    cid = await store.create_conversation()

    async def writer(n):
        await store.save_message(cid, "user", f"concurrent-{n}")

    await asyncio.gather(*[writer(i) for i in range(10)])

    messages = await store.get_messages(cid, limit=100)
    assert len(messages) == 10
