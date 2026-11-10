"""Supervisor Task State Machine enforcing permitted PHIL lifecycle transitions."""

from datetime import datetime, timezone
import logging
from typing import Any, Dict, FrozenSet, Mapping, Optional

from phil.state.exceptions import InvalidStateTransitionError
from phil.state.models import ApprovalContext, PhilTask, StateTransitionRecord, TaskState

logger = logging.getLogger("phil.state")


class SupervisorTaskStateMachine:
    """Authoritative state machine governing PHIL task lifecycle transitions."""

    # Explicit, immutable matrix of permitted state transitions
    PERMITTED_TRANSITIONS: Mapping[TaskState, FrozenSet[TaskState]] = {
        TaskState.RECEIVED: frozenset({
            TaskState.IN_PROGRESS,
            TaskState.CANCELLED,
            TaskState.FAILED,
        }),
        TaskState.IN_PROGRESS: frozenset({
            TaskState.AWAITING_APPROVAL,
            TaskState.COMPLETED,
            TaskState.FAILED,
            TaskState.CANCELLED,
        }),
        TaskState.AWAITING_APPROVAL: frozenset({
            TaskState.IN_PROGRESS,
            TaskState.COMPLETED,
            TaskState.FAILED,
            TaskState.CANCELLED,
        }),
        # Terminal states have no permitted outgoing transitions
        TaskState.COMPLETED: frozenset(),
        TaskState.FAILED: frozenset(),
        TaskState.CANCELLED: frozenset(),
    }

    @classmethod
    def is_permitted(cls, from_state: TaskState, to_state: TaskState) -> bool:
        """Check if a transition from from_state to to_state is valid."""
        allowed = cls.PERMITTED_TRANSITIONS.get(from_state, frozenset())
        return to_state in allowed

    @classmethod
    def get_permitted_destinations(cls, from_state: TaskState) -> FrozenSet[TaskState]:
        """Return all permitted target states from the given state."""
        return cls.PERMITTED_TRANSITIONS.get(from_state, frozenset())

    def transition(
        self,
        task: PhilTask,
        to_state: TaskState,
        trigger: str,
        actor: Optional[str] = None,
        reason: Optional[str] = None,
        result_reference: Optional[str] = None,
        error_info: Optional[Dict[str, Any]] = None,
        approval_context: Optional[ApprovalContext] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> PhilTask:
        """Execute and record a validated state transition on a PHIL task.

        Raises:
            InvalidStateTransitionError: If the transition is not allowed by the lifecycle matrix.
        """
        current_state = task.state
        actor_name = actor or "System"

        logger.debug(
            "[STATE-TRANSITION-ATTEMPT] Task '%s': %s -> %s (trigger: '%s', actor: '%s')",
            task.task_id, current_state.value, to_state.value, trigger, actor_name
        )

        # Validate transition against the lifecycle matrix
        if not self.is_permitted(current_state, to_state):
            allowed_targets = [s.value for s in self.get_permitted_destinations(current_state)]
            reason_msg = (
                f"Task is in terminal state '{current_state.value}'."
                if not allowed_targets
                else f"Allowed transitions from '{current_state.value}' are: {allowed_targets}."
            )
            logger.error(
                "[STATE-INVALID-TRANSITION] BLOCKED: Task '%s' cannot move from %s -> %s via trigger '%s'. %s",
                task.task_id, current_state.value, to_state.value, trigger, reason_msg
            )
            raise InvalidStateTransitionError(
                task_id=task.task_id,
                current_state=current_state.value,
                target_state=to_state.value,
                trigger=trigger,
                reason=reason_msg,
            )

        now = datetime.now(timezone.utc)

        # Create audit record
        record = StateTransitionRecord(
            from_state=current_state,
            to_state=to_state,
            trigger=trigger,
            timestamp=now,
            actor=actor,
            reason=reason,
            metadata=metadata or {},
        )

        # Apply state updates
        task.history.append(record)
        task.state = to_state
        task.updated_at = now

        # Update contextual payload fields based on destination state
        if to_state == TaskState.COMPLETED and result_reference is not None:
            task.result_reference = result_reference
        elif to_state == TaskState.FAILED and error_info is not None:
            task.error_info = error_info
        elif to_state == TaskState.AWAITING_APPROVAL and approval_context is not None:
            task.approval_context = approval_context
        elif current_state == TaskState.AWAITING_APPROVAL and task.approval_context is not None:
            if reason:
                task.approval_context.decision = reason
            task.approval_context.approved_by = actor
            task.approval_context.approved_at = now

        logger.info(
            "[STATE-TRANSITION-SUCCESS] Task '%s': %s -> %s | trigger: '%s' | actor: '%s' %s",
            task.task_id, current_state.value, to_state.value, trigger, actor_name,
            f"(reason: {reason})" if reason else ""
        )
        return task
