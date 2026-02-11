"""Pydantic models for API requests, responses, events, and task records."""

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class UiaElement(BaseModel):
    automation_id: str = ""
    name: str = ""
    control_type: str = ""
    class_name: str = ""
    bounding_rect: Optional[List[int]] = None  # [x, y, width, height]
    is_enabled: bool = True
    is_offscreen: bool = False
    patterns: List[str] = Field(default_factory=list)
    value: Optional[str] = None
    toggle_state: Optional[str] = None
    children: List["UiaElement"] = Field(default_factory=list)


UiaElement.model_rebuild()


class UiaSnapshot(BaseModel):
    focused_name: str = ""
    control_type: str = ""
    document_text: str = ""
    focused_element: Optional[UiaElement] = None
    window_tree: List[UiaElement] = Field(default_factory=list)


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

    model_config = ConfigDict(extra="allow")


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


class UiTelemetryEvent(BaseModel):
    session_id: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    message: str = ""
    timestamp: datetime
    data: Dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="allow")


class UiTelemetryIngestRequest(BaseModel):
    events: List[UiTelemetryEvent] = Field(default_factory=list, min_length=1, max_length=500)


TaskStatus = Literal[
    "created",
    "planned",
    "running",
    "waiting_approval",
    "paused",
    "completed",
    "failed",
    "cancelled",
]

TaskStepStatus = Literal["pending", "running", "succeeded", "failed", "blocked", "skipped"]
AutonomyRunStatus = Literal["running", "waiting_approval", "completed", "failed", "cancelled"]
AutonomyLevel = Literal["supervised", "guided", "autonomous"]


class TaskAction(BaseModel):
    action: str
    parameters: Dict[str, Any] = Field(default_factory=dict)
    description: str = ""
    irreversible: bool = False


class TaskStepPlan(BaseModel):
    action: TaskAction
    preconditions: List[str] = Field(default_factory=list)
    postconditions: List[str] = Field(default_factory=list)


class TaskStep(BaseModel):
    step_id: str
    index: int
    action: TaskAction
    preconditions: List[str] = Field(default_factory=list)
    postconditions: List[str] = Field(default_factory=list)
    status: TaskStepStatus = "pending"
    approved: bool = False
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class TaskRecord(BaseModel):
    task_id: str
    objective: str
    status: TaskStatus = "created"
    current_step_index: Optional[int] = None
    steps: List[TaskStep] = Field(default_factory=list)
    approval_token: Optional[str] = None
    last_error: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class TaskCreateRequest(BaseModel):
    objective: str = Field(min_length=1)


class TaskPlanRequest(BaseModel):
    steps: List[TaskStepPlan] = Field(default_factory=list)


class TaskApproveRequest(BaseModel):
    approval_token: str = Field(min_length=1)


class AutonomyStartRequest(BaseModel):
    objective: str = Field(min_length=1)
    max_iterations: int = Field(default=24, ge=1, le=500)
    parallel_agents: int = Field(default=3, ge=1, le=16)
    auto_approve_irreversible: bool = False
    autonomy_level: AutonomyLevel = "supervised"


class AutonomyApproveRequest(BaseModel):
    approval_token: str = Field(min_length=1)


class AutonomyPlannerModeRequest(BaseModel):
    mode: Literal["deterministic", "auto", "ollama_required"]


class OllamaModelRequest(BaseModel):
    model: str = Field(min_length=1)


class OllamaProbeRequest(BaseModel):
    prompt: str = Field(default="Respond with exactly: OK", min_length=1, max_length=4000)
    timeout_s: float = Field(default=8.0, ge=1.0, le=60.0)
    allow_fallback: bool = False


class ReadinessGateRequest(BaseModel):
    objective: str = Field(min_length=1)
    timeout_s: float = Field(default=30.0, ge=1.0, le=600.0)
    poll_interval_ms: int = Field(default=100, ge=20, le=5000)
    max_iterations: int = Field(default=24, ge=1, le=500)
    parallel_agents: int = Field(default=3, ge=1, le=16)
    auto_approve_irreversible: bool = True
    require_preflight_ok: bool = True
    cleanup_on_exit: bool = True


class ReadinessMatrixRequest(BaseModel):
    objectives: List[str] = Field(min_length=1, max_length=20)
    timeout_s: float = Field(default=30.0, ge=1.0, le=600.0)
    poll_interval_ms: int = Field(default=100, ge=20, le=5000)
    max_iterations: int = Field(default=24, ge=1, le=500)
    parallel_agents: int = Field(default=3, ge=1, le=16)
    auto_approve_irreversible: bool = True
    require_preflight_ok: bool = True
    cleanup_on_exit: bool = True
    stop_on_failure: bool = False


class AgentLogEntry(BaseModel):
    timestamp: datetime
    agent: str
    message: str


class AutonomyRunRecord(BaseModel):
    run_id: str
    task_id: str
    objective: str
    planner_mode: str = "deterministic"
    status: AutonomyRunStatus
    iteration: int = 0
    max_iterations: int
    parallel_agents: int = 3
    auto_approve_irreversible: bool = False
    autonomy_level: AutonomyLevel = "supervised"
    approval_token: Optional[str] = None
    last_error: Optional[str] = None
    started_at: datetime
    updated_at: datetime
    finished_at: Optional[datetime] = None
    agent_log: List[AgentLogEntry] = Field(default_factory=list)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    allow_actions: bool = True
    conversation_id: Optional[str] = None
