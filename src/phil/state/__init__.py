"""PHIL Task State Management module."""

from phil.state.exceptions import (
    CorrelationMismatchError,
    InvalidStateTransitionError,
    TaskNotFoundError,
    TaskStateError,
)
from phil.state.machine import SupervisorTaskStateMachine
from phil.state.mapper import map_a2a_status_to_phil_state, map_a2a_status_to_trigger
from phil.state.models import (
    ApprovalContext,
    PhilTask,
    StateTransitionRecord,
    TaskState,
)
from phil.state.repository import InMemoryTaskRepository, TaskRepository

__all__ = [
    "TaskState",
    "StateTransitionRecord",
    "ApprovalContext",
    "PhilTask",
    "SupervisorTaskStateMachine",
    "TaskRepository",
    "InMemoryTaskRepository",
    "map_a2a_status_to_phil_state",
    "map_a2a_status_to_trigger",
    "TaskStateError",
    "InvalidStateTransitionError",
    "TaskNotFoundError",
    "CorrelationMismatchError",
]

