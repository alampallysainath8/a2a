"""Exceptions for PHIL Task State Management."""

from typing import Optional


class TaskStateError(Exception):
    """Base exception for task state management errors."""
    pass


class InvalidStateTransitionError(TaskStateError):
    """Raised when an illegal or unpermitted state transition is attempted."""

    def __init__(
        self,
        task_id: str,
        current_state: str,
        target_state: str,
        trigger: str,
        reason: Optional[str] = None,
    ) -> None:
        self.task_id = task_id
        self.current_state = current_state
        self.target_state = target_state
        self.trigger = trigger
        self.reason = reason or "Transition is not permitted by PHIL lifecycle matrix."
        super().__init__(
            f"Invalid state transition for task '{task_id}': cannot transition from "
            f"'{current_state}' to '{target_state}' via trigger '{trigger}'. {self.reason}"
        )


class TaskNotFoundError(TaskStateError):
    """Raised when a referenced task does not exist in the state repository."""
    pass


class CorrelationMismatchError(TaskStateError):
    """Raised when correlation ID does not match the task's authoritative correlation ID."""
    pass

