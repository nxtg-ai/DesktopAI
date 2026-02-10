"""Tests for chat history routes."""

import os

os.environ.setdefault("BACKEND_DB_PATH", ":memory:")

import pytest
from app.main import app, chat_memory
from httpx import ASGITransport, AsyncClient


@pytest.fixture(autouse=True)
async def _clean_chat_memory():
    """Ensure a fresh chat_memory state for each test."""
    yield
    # Clean up conversations created during test
    convs = await chat_memory.list_conversations(limit=100)
    for c in convs:
        await chat_memory.delete_conversation(c["conversation_id"])


async def _create_conversation_with_messages():
    cid = await chat_memory.create_conversation()
    await chat_memory.save_message(cid, "user", "Hello")
    await chat_memory.save_message(cid, "assistant", "Hi there!")
    return cid


@pytest.mark.asyncio
async def test_list_conversations_empty():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/api/chat/conversations")
    assert resp.status_code == 200
    data = resp.json()
    assert "conversations" in data
    assert isinstance(data["conversations"], list)


@pytest.mark.asyncio
async def test_list_conversations_with_data():
    cid = await _create_conversation_with_messages()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/api/chat/conversations")
    assert resp.status_code == 200
    convs = resp.json()["conversations"]
    assert len(convs) >= 1
    assert any(c["conversation_id"] == cid for c in convs)


@pytest.mark.asyncio
async def test_list_conversations_limit():
    for _ in range(3):
        await _create_conversation_with_messages()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/api/chat/conversations", params={"limit": 2})
    assert resp.status_code == 200
    assert len(resp.json()["conversations"]) == 2


@pytest.mark.asyncio
async def test_get_conversation():
    cid = await _create_conversation_with_messages()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get(f"/api/chat/conversations/{cid}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["conversation"]["conversation_id"] == cid
    assert len(data["messages"]) == 2


@pytest.mark.asyncio
async def test_get_conversation_not_found():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/api/chat/conversations/nonexistent-id")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_conversation():
    cid = await _create_conversation_with_messages()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.delete(f"/api/chat/conversations/{cid}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "deleted"
    # Verify it's gone
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get(f"/api/chat/conversations/{cid}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_conversation_not_found():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.delete("/api/chat/conversations/nonexistent-id")
    assert resp.status_code == 404
