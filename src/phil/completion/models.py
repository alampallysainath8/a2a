"""Data models and event contracts for Task Completion and Failure processing."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator

from phil.state.models import TaskState


class AckStatus(str, Enum):
    """Status enumeration for completion acknowledgements."""
    PROCESSED = "PROCESSED"
    ALREADY_PROCESSED = "ALREADY_PROCESSED"
    IGNORED_DUPLICATE = "IGNORED_DUPLICATE"
    TASK_NOT_FOUND = "TASK_NOT_FOUND"
    CORRELATION_MISMATCH = "CORRELATION_MISMATCH"
    INVALID_TRANSITION = "INVALID_TRANSITION"
    ERROR = "ERROR"


class TaskCompletionEvent(BaseModel):
    """Contract schema for reporting successful task completion by a domain agent."""
    event_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="Unique identifier for this specific event delivery"
    )
    task_id: str = Field(description="Target PHIL task identifier")
    correlation_id: str = Field(description="Traceable correlation ID")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    result_reference: str = Field(
        description="URI or pointer to the registered output artifact"
    )
    output_payload: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional lightweight result summary payload"
    )
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("result_reference")
    @classmethod
    def validate_result_reference_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("result_reference cannot be empty")
        return v.strip()


class TaskFailureEvent(BaseModel):
    """Contract schema for reporting task execution failure by a domain agent."""
    event_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="Unique identifier for this specific event delivery"
    )
    task_id: str = Field(description="Target PHIL task identifier")
    correlation_id: str = Field(description="Traceable correlation ID")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    error_code: str = Field(description="Machine-readable error classification code")
    error_message: str = Field(description="Human-readable explanation of failure")
    details: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional stack trace, diagnostic context, or field errors"
    )
    retryable: bool = Field(
        default=False,
        description="Indicates whether the supervisor may safely retry this task"
    )
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("error_code")
    @classmethod
    def validate_error_code_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("error_code cannot be empty")
        return v.strip()


class CompletionAck(BaseModel):
    """Formal acknowledgement returned to the caller upon processing completion/failure."""
    ack_id: str = Field(default_factory=lambda: f"ack-{uuid4()}")
    event_id: str = Field(description="ID of the event being acknowledged")
    task_id: str = Field(description="Target PHIL task identifier")
    status: AckStatus = Field(description="Processing outcome status")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    message: str = Field(description="Descriptive acknowledgement message")
    final_state: Optional[TaskState] = Field(
        default=None,
        description="Current authoritative PHIL state of the task"
    )

