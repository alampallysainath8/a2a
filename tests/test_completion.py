"""Tests for Completion and Failure Contracts, idempotency, duplicate handling, and acknowledgements."""

import pytest

from phil.completion.models import (
    AckStatus,
    CompletionAck,
    TaskCompletionEvent,
    TaskFailureEvent,
)
from phil.completion.processor import CompletionProcessor
from phil.state.machine import SupervisorTaskStateMachine
from phil.state.models import PhilTask, TaskState
from phil.state.repository import InMemoryTaskRepository


@pytest.fixture
def repo():
    return InMemoryTaskRepository()


@pytest.fixture
def state_machine():
    return SupervisorTaskStateMachine()


@pytest.fixture
def processor(repo, state_machine):
    return CompletionProcessor(repository=repo, state_machine=state_machine)


@pytest.fixture
def active_task(repo, state_machine):
    """Fixture providing a task in IN_PROGRESS state."""
    task = PhilTask(
        task_id="task-comp-001",
        correlation_id="corr-comp-999",
        agent_id="agent-worker-01",
        intent="generate_report",
    )
    state_machine.transition(task, TaskState.IN_PROGRESS, trigger="DISPATCH")
    repo.save(task)
    return task


# ---------------------------------------------------------------------------
# Test 1: Valid Completion Event
# ---------------------------------------------------------------------------

def test_valid_completion_event(processor, repo, active_task):
    event = TaskCompletionEvent(
        event_id="evt-101",
        task_id=active_task.task_id,
        correlation_id=active_task.correlation_id,
        result_reference="phil://artifacts/reports/2026-q4.csv",
        output_payload={"row_count": 1400},
    )

    ack = processor.process_completion(event)

    assert ack.status == AckStatus.PROCESSED
    assert ack.event_id == "evt-101"
    assert ack.task_id == active_task.task_id
    assert ack.final_state == TaskState.COMPLETED

    # Verify task in repository updated
    updated_task = repo.get(active_task.task_id)
    assert updated_task.state == TaskState.COMPLETED
    assert updated_task.result_reference == "phil://artifacts/reports/2026-q4.csv"
    assert updated_task.is_terminal is True
    assert updated_task.history[-1].to_state == TaskState.COMPLETED


# ---------------------------------------------------------------------------
# Test 2: Valid Failure Event
# ---------------------------------------------------------------------------

def test_valid_failure_event(processor, repo, active_task):
    event = TaskFailureEvent(
        event_id="evt-err-201",
        task_id=active_task.task_id,
        correlation_id=active_task.correlation_id,
        error_code="PARSING_FAILED",
        error_message="Invalid CSV format at line 42",
        retryable=False,
    )

    ack = processor.process_failure(event)

    assert ack.status == AckStatus.PROCESSED
    assert ack.event_id == "evt-err-201"
    assert ack.final_state == TaskState.FAILED

    updated_task = repo.get(active_task.task_id)
    assert updated_task.state == TaskState.FAILED
    assert updated_task.error_info["error_code"] == "PARSING_FAILED"
    assert updated_task.error_info["error_message"] == "Invalid CSV format at line 42"
    assert updated_task.is_terminal is True


# ---------------------------------------------------------------------------
# Test 3: Duplicate Event ID (Deduplication)
# ---------------------------------------------------------------------------

def test_duplicate_event_id_handling(processor, active_task):
    event = TaskCompletionEvent(
        event_id="evt-dedup-301",
        task_id=active_task.task_id,
        correlation_id=active_task.correlation_id,
        result_reference="phil://artifacts/out.json",
    )

    # First delivery
    ack1 = processor.process_completion(event)
    assert ack1.status == AckStatus.PROCESSED

    # Exact duplicate delivery with same event_id
    ack2 = processor.process_completion(event)
    assert ack2.status == AckStatus.IGNORED_DUPLICATE
    assert "already been processed" in ack2.message
    assert ack2.final_state == TaskState.COMPLETED


# ---------------------------------------------------------------------------
# Test 4: Idempotent Processing on Already Completed / Failed Task
# ---------------------------------------------------------------------------

def test_idempotent_completion_with_different_event_id(processor, active_task):
    event1 = TaskCompletionEvent(
        event_id="evt-idem-1",
        task_id=active_task.task_id,
        correlation_id=active_task.correlation_id,
        result_reference="phil://artifacts/common_result.json",
    )
    ack1 = processor.process_completion(event1)
    assert ack1.status == AckStatus.PROCESSED

    # Second completion event (different event_id) reporting identical result reference
    event2 = TaskCompletionEvent(
        event_id="evt-idem-2",
        task_id=active_task.task_id,
        correlation_id=active_task.correlation_id,
        result_reference="phil://artifacts/common_result.json",
    )
    ack2 = processor.process_completion(event2)
    assert ack2.status == AckStatus.ALREADY_PROCESSED
    assert ack2.final_state == TaskState.COMPLETED


def test_idempotent_failure_with_different_event_id(processor, active_task):
    fail_event1 = TaskFailureEvent(
        event_id="evt-f1",
        task_id=active_task.task_id,
        correlation_id=active_task.correlation_id,
        error_code="TIMEOUT",
        error_message="Downstream timed out",
    )
    processor.process_failure(fail_event1)

    # Second failure event
    fail_event2 = TaskFailureEvent(
        event_id="evt-f2",
        task_id=active_task.task_id,
        correlation_id=active_task.correlation_id,
        error_code="TIMEOUT",
        error_message="Downstream timed out retry",
    )
    ack2 = processor.process_failure(fail_event2)
    assert ack2.status == AckStatus.ALREADY_PROCESSED
    assert ack2.final_state == TaskState.FAILED


# ---------------------------------------------------------------------------
# Test 5: Invalid Task Reference (Task Not Found)
# ---------------------------------------------------------------------------

def test_completion_for_non_existent_task(processor):
    event = TaskCompletionEvent(
        event_id="evt-missing-404",
        task_id="task-non-existent-9999",
        correlation_id="corr-any",
        result_reference="phil://artifacts/none",
    )
    ack = processor.process_completion(event)
    assert ack.status == AckStatus.TASK_NOT_FOUND
    assert "does not exist" in ack.message


def test_failure_for_non_existent_task(processor):
    event = TaskFailureEvent(
        event_id="evt-missing-err",
        task_id="task-non-existent-9999",
        correlation_id="corr-any",
        error_code="FATAL",
        error_message="Nothing found",
    )
    ack = processor.process_failure(event)
    assert ack.status == AckStatus.TASK_NOT_FOUND


# ---------------------------------------------------------------------------
# Test 6: Correlation ID Mismatch
# ---------------------------------------------------------------------------

def test_correlation_id_mismatch(processor, active_task):
    event = TaskCompletionEvent(
        event_id="evt-mismatch",
        task_id=active_task.task_id,
        correlation_id="wrong-correlation-id",
        result_reference="phil://artifacts/test",
    )
    ack = processor.process_completion(event)
    assert ack.status == AckStatus.CORRELATION_MISMATCH
    assert "Correlation ID mismatch" in ack.message


# ---------------------------------------------------------------------------
# Test 7: Conflict / Invalid Transitions
# ---------------------------------------------------------------------------

def test_completion_attempt_on_cancelled_task(processor, repo, active_task, state_machine):
    state_machine.transition(active_task, TaskState.CANCELLED, trigger="CANCEL")
    repo.update(active_task)

    event = TaskCompletionEvent(
        event_id="evt-late-comp",
        task_id=active_task.task_id,
        correlation_id=active_task.correlation_id,
        result_reference="phil://artifacts/late.json",
    )
    ack = processor.process_completion(event)
    assert ack.status == AckStatus.INVALID_TRANSITION
    assert "terminal state 'CANCELLED'" in ack.message


def test_failure_attempt_on_completed_task(processor, repo, active_task, state_machine):
    state_machine.transition(active_task, TaskState.COMPLETED, trigger="DONE", result_reference="res1")
    repo.update(active_task)

    event = TaskFailureEvent(
        event_id="evt-late-fail",
        task_id=active_task.task_id,
        correlation_id=active_task.correlation_id,
        error_code="LATE_ERROR",
        error_message="Failed after success",
    )
    ack = processor.process_failure(event)
    assert ack.status == AckStatus.INVALID_TRANSITION
    assert "terminal state 'COMPLETED'" in ack.message


# ---------------------------------------------------------------------------
# Test 8: A2A Outcome Mapping Bridge
# ---------------------------------------------------------------------------

def test_process_a2a_outcome_success(processor, active_task):
    ack = processor.process_a2a_outcome(
        task_id=active_task.task_id,
        correlation_id=active_task.correlation_id,
        a2a_status="completed",
        result_reference="phil://artifacts/a2a_out.bin",
    )
    assert ack.status == AckStatus.PROCESSED
    assert ack.final_state == TaskState.COMPLETED


def test_process_a2a_outcome_failure(processor, active_task):
    ack = processor.process_a2a_outcome(
        task_id=active_task.task_id,
        correlation_id=active_task.correlation_id,
        a2a_status="error",
        error_code="REMOTE_TIMEOUT",
        error_message="Domain agent execution exceeded limits",
    )
    assert ack.status == AckStatus.PROCESSED
    assert ack.final_state == TaskState.FAILED


def test_process_a2a_outcome_rejects_non_terminal(processor, active_task):
    with pytest.raises(ValueError, match="maps to non-terminal state"):
        processor.process_a2a_outcome(
            task_id=active_task.task_id,
            correlation_id=active_task.correlation_id,
            a2a_status="in_progress",
        )


# ---------------------------------------------------------------------------
# Test 9: Event Schema Validation
# ---------------------------------------------------------------------------

def test_event_schema_empty_fields_fail():
    with pytest.raises(ValueError, match="result_reference cannot be empty"):
        TaskCompletionEvent(
            task_id="t1",
            correlation_id="c1",
            result_reference="   ",
        )

    with pytest.raises(ValueError, match="error_code cannot be empty"):
        TaskFailureEvent(
            task_id="t1",
            correlation_id="c1",
            error_code="   ",
            error_message="Something went wrong",
        )

