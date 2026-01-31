from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class WindowEvent(BaseModel):
    type: str = Field(default="foreground")
    hwnd: str
    title: str = ""
    process_exe: str = ""
    pid: int = 0
    timestamp: datetime
    source: str = "collector"

    class Config:
        extra = "allow"


class StateResponse(BaseModel):
    current: Optional[WindowEvent]
    event_count: int
