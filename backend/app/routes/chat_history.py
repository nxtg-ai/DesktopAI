"""Chat conversation history routes."""

from fastapi import APIRouter, HTTPException

from ..deps import chat_memory

router = APIRouter()


@router.get("/api/chat/conversations")
async def list_conversations(limit: int = 20) -> dict:
    """List chat conversations ordered by most recent activity."""
    conversations = await chat_memory.list_conversations(limit=limit)
    return {"conversations": conversations}


@router.get("/api/chat/conversations/{conversation_id}")
async def get_conversation(conversation_id: str, message_limit: int = 50) -> dict:
    """Get a conversation with its messages."""
    conv = await chat_memory.get_conversation(conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    messages = await chat_memory.get_messages(conversation_id, limit=message_limit)
    return {"conversation": conv, "messages": messages}


@router.delete("/api/chat/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str) -> dict:
    """Delete a conversation and all its messages."""
    deleted = await chat_memory.delete_conversation(conversation_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"status": "deleted"}
