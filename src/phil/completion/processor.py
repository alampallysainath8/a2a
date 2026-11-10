"""Idempotent processor for task completion and failure events."""

from datetime import datetime, timezone
import logging
from threading import RLock
from typing import Optional, Set, Union
from uuid import uuid4

from phil.completion.models import (
    AckStatus,
    CompletionAck,
    TaskCompletionEvent,
    TaskFailureEvent,
)
from phil.state.exceptions import InvalidStateTransitionError
from phil.state.machine import SupervisorTaskStateMachine
from phil.state.mapper import map_a2a_status_to_phil_state, map_a2a_status_to_trigger
from phil.state.models import PhilTask, TaskState
from phil.state.repository import TaskRepository

logger = logging.getLogger("phil.completion")


class CompletionProcessor:
    """Processes task completion and failure events with idempotency and duplicate deduplication."""

    def __init__(
        self,
        repository: TaskRepository,
        state_machine: Optional[SupervisorTaskStateMachine] = None,
    ) -> None:
        self.repository = repository
        self.state_machine = state_machine or SupervisorTaskStateMachine()
        self._lock = RLock()
        self._processed_event_ids: Set[str] = set()

    def is_event_processed(self, event_id: str) -> bool:
        """Check if an event ID has already been processed."""
        with self._lock:
            return event_id in self._processed_event_ids

    def process_completion(self, event: TaskCompletionEvent) -> CompletionAck:
        """Process a task completion event idempotently."""
        logger.info(
            "[COMPLETION-EVENT-RECEIVED] event_id=%s, task_id=%s, corr_id=%s, result_ref=%s",
            event.event_id, event.task_id, event.correlation_id, event.result_reference
        )

        with self._lock:
            # 1. Event ID Deduplication check
            if event.event_id in self._processed_event_ids:
                task = self.repository.get(event.task_id)
                current_state = task.state if task else None
                logger.warning(
                    "[COMPLETION-DUPLICATE-EVENT] event_id=%s already processed. Acknowledging with IGNORED_DUPLICATE.",
                    event.event_id
                )
                return CompletionAck(
                    event_id=event.event_id,
                    task_id=event.task_id,
                    status=AckStatus.IGNORED_DUPLICATE,
                    message=f"Event '{event.event_id}' has already been processed (duplicate delivery ignored).",
                    final_state=current_state,
                )

            # 2. Task existence check
            task = self.repository.get(event.task_id)
            if task is None:
                logger.error("[COMPLETION-TASK-NOT-FOUND] task_id=%s does not exist in store.", event.task_id)
                return CompletionAck(
                    event_id=event.event_id,
                    task_id=event.task_id,
                    status=AckStatus.TASK_NOT_FOUND,
                    message=f"Task '{event.task_id}' does not exist in state store.",
                )

            # 3. Correlation ID validation
            if task.correlation_id != event.correlation_id:
                logger.error(
                    "[COMPLETION-CORRELATION-MISMATCH] task_id=%s has correlation_id='%s', event provided '%s'",
                    task.task_id, task.correlation_id, event.correlation_id
                )
                return CompletionAck(
                    event_id=event.event_id,
                    task_id=event.task_id,
                    status=AckStatus.CORRELATION_MISMATCH,
                    message=(
                        f"Correlation ID mismatch: task has '{task.correlation_id}', "
                        f"event provided '{event.correlation_id}'."
                    ),
                    final_state=task.state,
                )

            # 4. Idempotency & Terminal State Checks
            if task.state == TaskState.COMPLETED:
                if task.result_reference == event.result_reference:
                    self._processed_event_ids.add(event.event_id)
                    logger.info(
                        "[COMPLETION-ALREADY-PROCESSED] task_id=%s is already COMPLETED with identical result.",
                        task.task_id
                    )
                    return CompletionAck(
                        event_id=event.event_id,
                        task_id=event.task_id,
                        status=AckStatus.ALREADY_PROCESSED,
                        message="Task is already in COMPLETED state with identical result reference.",
                        final_state=TaskState.COMPLETED,
                    )
                else:
                    logger.warning(
                        "[COMPLETION-CONFLICT] task_id=%s is COMPLETED but has different result reference.",
                        task.task_id
                    )
                    return CompletionAck(
                        event_id=event.event_id,
                        task_id=event.task_id,
                        status=AckStatus.INVALID_TRANSITION,
                        message="Task is already in COMPLETED state with a conflicting result reference.",
                        final_state=TaskState.COMPLETED,
                    )

            if task.state in {TaskState.FAILED, TaskState.CANCELLED}:
                logger.warning(
                    "[COMPLETION-INVALID-STATE] Cannot complete task_id=%s currently in terminal state '%s'.",
                    task.task_id, task.state.value
                )
                return CompletionAck(
                    event_id=event.event_id,
                    task_id=event.task_id,
                    status=AckStatus.INVALID_TRANSITION,
                    message=(
                        f"Cannot transition task '{task.task_id}' to COMPLETED: "
                        f"task is in terminal state '{task.state.value}'."
                    ),
                    final_state=task.state,
                )

            # 5. Execute state transition to COMPLETED
            try:
                self.state_machine.transition(
                    task=task,
                    to_state=TaskState.COMPLETED,
                    trigger="EXECUTION_COMPLETED",
                    actor="DomainAgent",
                    reason="Task successfully completed by domain agent",
                    result_reference=event.result_reference,
                    metadata={"event_id": event.event_id, **event.metadata},
                )
                self.repository.update(task)
                self._processed_event_ids.add(event.event_id)

                logger.info(
                    "[COMPLETION-SUCCESS] task_id=%s successfully marked COMPLETED. Emitting PROCESSED ack.",
                    task.task_id
                )
                return CompletionAck(
                    event_id=event.event_id,
                    task_id=event.task_id,
                    status=AckStatus.PROCESSED,
                    message="Task successfully transitioned to COMPLETED.",
                    final_state=TaskState.COMPLETED,
                )

            except InvalidStateTransitionError as e:
                logger.error("[COMPLETION-TRANSITION-ERROR] %s", str(e))
                return CompletionAck(
                    event_id=event.event_id,
                    task_id=event.task_id,
                    status=AckStatus.INVALID_TRANSITION,
                    message=str(e),
                    final_state=task.state,
                )

    def process_failure(self, event: TaskFailureEvent) -> CompletionAck:
        """Process a task failure event idempotently."""
        logger.info(
            "[FAILURE-EVENT-RECEIVED] event_id=%s, task_id=%s, error_code=%s, retryable=%s",
            event.event_id, event.task_id, event.error_code, event.retryable
        )

        with self._lock:
            # 1. Event ID Deduplication check
            if event.event_id in self._processed_event_ids:
                task = self.repository.get(event.task_id)
                current_state = task.state if task else None
                logger.warning(
                    "[FAILURE-DUPLICATE-EVENT] event_id=%s already processed. Acknowledging with IGNORED_DUPLICATE.",
                    event.event_id
                )
                return CompletionAck(
                    event_id=event.event_id,
                    task_id=event.task_id,
                    status=AckStatus.IGNORED_DUPLICATE,
                    message=f"Event '{event.event_id}' has already been processed (duplicate delivery ignored).",
                    final_state=current_state,
                )

            # 2. Task existence check
            task = self.repository.get(event.task_id)
            if task is None:
                logger.error("[FAILURE-TASK-NOT-FOUND] task_id=%s does not exist in store.", event.task_id)
                return CompletionAck(
                    event_id=event.event_id,
                    task_id=event.task_id,
                    status=AckStatus.TASK_NOT_FOUND,
                    message=f"Task '{event.task_id}' does not exist in state store.",
                )

            # 3. Correlation ID validation
            if task.correlation_id != event.correlation_id:
                logger.error(
                    "[FAILURE-CORRELATION-MISMATCH] task_id=%s has correlation_id='%s', event provided '%s'",
                    task.task_id, task.correlation_id, event.correlation_id
                )
                return CompletionAck(
                    event_id=event.event_id,
                    task_id=event.task_id,
                    status=AckStatus.CORRELATION_MISMATCH,
                    message=(
                        f"Correlation ID mismatch: task has '{task.correlation_id}', "
                        f"event provided '{event.correlation_id}'."
                    ),
                    final_state=task.state,
                )

            # 4. Idempotency & Terminal State Checks
            if task.state == TaskState.FAILED:
                self._processed_event_ids.add(event.event_id)
                logger.info("[FAILURE-ALREADY-PROCESSED] task_id=%s is already FAILED.", task.task_id)
                return CompletionAck(
                    event_id=event.event_id,
                    task_id=event.task_id,
                    status=AckStatus.ALREADY_PROCESSED,
                    message="Task is already in FAILED state.",
                    final_state=TaskState.FAILED,
                )

            if task.state in {TaskState.COMPLETED, TaskState.CANCELLED}:
                logger.warning(
                    "[FAILURE-INVALID-STATE] Cannot fail task_id=%s currently in terminal state '%s'.",
                    task.task_id, task.state.value
                )
                return CompletionAck(
                    event_id=event.event_id,
                    task_id=event.task_id,
                    status=AckStatus.INVALID_TRANSITION,
                    message=(
                        f"Cannot transition task '{task.task_id}' to FAILED: "
                        f"task is in terminal state '{task.state.value}'."
                    ),
                    final_state=task.state,
                )

            # 5. Execute state transition to FAILED
            error_payload = {
                "error_code": event.error_code,
                "error_message": event.error_message,
                "details": event.details,
                "retryable": event.retryable,
            }

            try:
                self.state_machine.transition(
                    task=task,
                    to_state=TaskState.FAILED,
                    trigger="EXECUTION_FAILED",
                    actor="DomainAgent",
                    reason=f"{event.error_code}: {event.error_message}",
                    error_info=error_payload,
                    metadata={"event_id": event.event_id, **event.metadata},
                )
                self.repository.update(task)
                self._processed_event_ids.add(event.event_id)

                logger.info(
                    "[FAILURE-SUCCESS] task_id=%s marked FAILED (code=%s). Emitting PROCESSED ack.",
                    task.task_id, event.error_code
                )
                return CompletionAck(
                    event_id=event.event_id,
                    task_id=event.task_id,
                    status=AckStatus.PROCESSED,
                    message="Task successfully transitioned to FAILED.",
                    final_state=TaskState.FAILED,
                )

            except InvalidStateTransitionError as e:
                logger.error("[FAILURE-TRANSITION-ERROR] %s", str(e))
                return CompletionAck(
                    event_id=event.event_id,
                    task_id=event.task_id,
                    status=AckStatus.INVALID_TRANSITION,
                    message=str(e),
                    final_state=task.state,
                )

    def process_event(
        self, event: Union[TaskCompletionEvent, TaskFailureEvent]
    ) -> CompletionAck:
        """Route and process either a completion or failure event."""
        if isinstance(event, TaskCompletionEvent):
            return self.process_completion(event)
        elif isinstance(event, TaskFailureEvent):
            return self.process_failure(event)
        else:
            raise TypeError(f"Unsupported event type: {type(event)}")

    def process_a2a_outcome(
        self,
        task_id: str,
        correlation_id: str,
        a2a_status: str,
        result_reference: Optional[str] = None,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
        event_id: Optional[str] = None,
    ) -> CompletionAck:
        """Bridge an incoming A2A terminal outcome directly into the formal contract flow."""
        mapped_state = map_a2a_status_to_phil_state(a2a_status)
        eid = event_id or str(uuid4())

        if mapped_state == TaskState.COMPLETED:
            if not result_reference:
                result_reference = f"phil://results/{task_id}"
            completion_event = TaskCompletionEvent(
                event_id=eid,
                task_id=task_id,
                correlation_id=correlation_id,
                result_reference=result_reference,
            )
            return self.process_completion(completion_event)

        elif mapped_state == TaskState.FAILED:
            failure_event = TaskFailureEvent(
                event_id=eid,
                task_id=task_id,
                correlation_id=correlation_id,
                error_code=error_code or "A2A_EXECUTION_ERROR",
                error_message=error_message or f"Agent reported status: {a2a_status}",
            )
            return self.process_failure(failure_event)

        else:
            raise ValueError(
                f"Status '{a2a_status}' maps to non-terminal state '{mapped_state.value}'. "
                f"process_a2a_outcome only handles terminal outcomes."
            )
