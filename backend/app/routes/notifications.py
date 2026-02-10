"""Notification routes for proactive alerts."""

from fastapi import APIRouter, HTTPException

from ..deps import notification_store

router = APIRouter()


@router.get("/api/notifications")
async def list_notifications(unread_only: bool = False, limit: int = 50) -> dict:
    items = await notification_store.list_notifications(unread_only=unread_only, limit=limit)
    return {"notifications": items}


@router.get("/api/notifications/count")
async def notification_count() -> dict:
    count = await notification_store.unread_count()
    return {"unread_count": count}


@router.post("/api/notifications/{notification_id}/read")
async def mark_notification_read(notification_id: str) -> dict:
    updated = await notification_store.mark_read(notification_id)
    if not updated:
        raise HTTPException(status_code=404, detail="Notification not found or already read")
    return {"status": "read"}


@router.delete("/api/notifications/{notification_id}")
async def delete_notification(notification_id: str) -> dict:
    deleted = await notification_store.delete(notification_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Notification not found")
    return {"status": "deleted"}
