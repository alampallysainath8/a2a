"""Data models for PHIL Task Lifecycle, State Machine, and Transition History."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


class TaskState(str, Enum):
    """Authoritative PHIL task lifecycle states."""
    RECEIVED = "RECEIVED"
    IN_PROGRESS = "IN_PROGRESS"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class StateTransitionRecord(BaseModel):
    """Audit record capturing an individual state transition."""
    from_state: TaskState
    to_state: TaskState
    trigger: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    actor: Optional[str] = Field(default=None, description="Supervisor, domain agent, or human approver")
    reason: Optional[str] = Field(default=None, description="Contextual reason for transition")
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ApprovalContext(BaseModel):
    """Contextual metadata when task transitions into or out of AWAITING_APPROVAL."""
    approval_id: str = Field(default_factory=lambda: f"appr-{uuid4()}")
    requested_by: str = Field(description="Agent or system component requesting governance approval")
    reason: str = Field(description="Policy or human approval reason")
    context_data: Dict[str, Any] = Field(default_factory=dict)
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None
    decision: Optional[str] = None  # e.g., "APPROVED", "REJECTED"


class PhilTask(BaseModel):
    """Authoritative PHIL-level task model owned by the Supervisor."""
    task_id: str = Field(default_factory=lambda: str(uuid4()))
    correlation_id: str = Field(description="Traceable correlation ID across multi-agent calls")
    agent_id: str = Field(description="Identifier of assigned domain agent")
    intent: str = Field(description="Target skill or intent to execute")
    state: TaskState = Field(default=TaskState.RECEIVED)
    history: List[StateTransitionRecord] = Field(default_factory=list)
    result_reference: Optional[str] = Field(
        default=None,
        description="URI reference to registered output artifact upon completion"
    )
    error_info: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Failure details, error code, and diagnostic message"
    )
    approval_context: Optional[ApprovalContext] = Field(
        default=None,
        description="Active or historic approval context"
    )
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def is_terminal(self) -> bool:
        """Return True if task has reached a terminal state."""
        return self.state in {TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED}

