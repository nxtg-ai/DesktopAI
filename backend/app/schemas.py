from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class UiaSnapshot(BaseModel):
    focused_name: str = ""
    control_type: str = ""
    document_text: str = ""


class WindowEvent(BaseModel):
    type: str = Field(default="foreground")
    hwnd: str
    title: str = ""
    process_exe: str = ""
    pid: int = 0
    timestamp: datetime
    source: str = "collector"
    idle_ms: Optional[int] = None
    category: Optional[str] = None
    uia: Optional[UiaSnapshot] = None

    class Config:
        extra = "allow"


class StateResponse(BaseModel):
    current: Optional[WindowEvent]
    event_count: int
    idle: bool = False
    idle_since: Optional[datetime] = None
    category: Optional[str] = None


class ClassifyRequest(BaseModel):
    type: str = "foreground"
    title: str = ""
    process_exe: str = ""
    pid: int = 0
    uia: Optional[UiaSnapshot] = None
    use_ollama: Optional[bool] = None
