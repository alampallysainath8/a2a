"""Tests for Supervisor Task State Management, transitions, and A2A status mapping."""

import pytest

from phil.state.exceptions import InvalidStateTransitionError, TaskNotFoundError
from phil.state.machine import SupervisorTaskStateMachine
from phil.state.mapper import map_a2a_status_to_phil_state, map_a2a_status_to_trigger
from phil.state.models import ApprovalContext, PhilTask, TaskState
from phil.state.repository import InMemoryTaskRepository


@pytest.fixture
def state_machine():
    return SupervisorTaskStateMachine()


@pytest.fixture
def sample_task():
    return PhilTask(
        task_id="task-12345",
        correlation_id="corr-98765",
        agent_id="agent-compliance-01",
        intent="audit_records",
    )


# ---------------------------------------------------------------------------
# Test 1: Valid Transitions & Lifecycle Flow
# ---------------------------------------------------------------------------

def test_valid_lifecycle_transitions(state_machine, sample_task):
    assert sample_task.state == TaskState.RECEIVED
    assert len(sample_task.history) == 0

    # 1. RECEIVED -> IN_PROGRESS
    state_machine.transition(
        task=sample_task,
        to_state=TaskState.IN_PROGRESS,
        trigger="DISPATCH_ACCEPTED",
        actor="Supervisor",
        reason="Agent accepted dispatch",
    )
    assert sample_task.state == TaskState.IN_PROGRESS
    assert len(sample_task.history) == 1
    assert sample_task.history[0].from_state == TaskState.RECEIVED
    assert sample_task.history[0].to_state == TaskState.IN_PROGRESS
    assert sample_task.history[0].trigger == "DISPATCH_ACCEPTED"

    # 2. IN_PROGRESS -> AWAITING_APPROVAL
    approval_ctx = ApprovalContext(
        requested_by="agent-compliance-01",
        reason="Action requires manager sign-off",
        context_data={"amount": 50000},
    )
    state_machine.transition(
        task=sample_task,
        to_state=TaskState.AWAITING_APPROVAL,
        trigger="APPROVAL_REQUIRED",
        actor="DomainAgent",
        approval_context=approval_ctx,
    )
    assert sample_task.state == TaskState.AWAITING_APPROVAL
    assert sample_task.approval_context is not None
    assert sample_task.approval_context.reason == "Action requires manager sign-off"
    assert len(sample_task.history) == 2

    # 3. AWAITING_APPROVAL -> IN_PROGRESS (Approval Granted)
    state_machine.transition(
        task=sample_task,
        to_state=TaskState.IN_PROGRESS,
        trigger="APPROVAL_GRANTED",
        actor="ManagerUser",
        reason="APPROVED",
    )
    assert sample_task.state == TaskState.IN_PROGRESS
    assert sample_task.approval_context.decision == "APPROVED"
    assert sample_task.approval_context.approved_by == "ManagerUser"
    assert len(sample_task.history) == 3

    # 4. IN_PROGRESS -> COMPLETED (Terminal)
    state_machine.transition(
        task=sample_task,
        to_state=TaskState.COMPLETED,
        trigger="EXECUTION_COMPLETED",
        actor="DomainAgent",
        result_reference="phil://artifacts/reports/audit-2026.pdf",
    )
    assert sample_task.state == TaskState.COMPLETED
    assert sample_task.is_terminal is True
    assert sample_task.result_reference == "phil://artifacts/reports/audit-2026.pdf"
    assert len(sample_task.history) == 4


# ---------------------------------------------------------------------------
# Test 2: Failure Transitions
# ---------------------------------------------------------------------------

def test_transition_to_failure_from_in_progress(state_machine, sample_task):
    state_machine.transition(sample_task, TaskState.IN_PROGRESS, trigger="DISPATCH")
    
    error_payload = {"code": "LEDGER_CORRUPT", "message": "Checksum mismatch in ledger"}
    state_machine.transition(
        task=sample_task,
        to_state=TaskState.FAILED,
        trigger="EXECUTION_FAILED",
        actor="DomainAgent",
        error_info=error_payload,
    )
    assert sample_task.state == TaskState.FAILED
    assert sample_task.is_terminal is True
    assert sample_task.error_info == error_payload


def test_transition_to_failure_from_received(state_machine, sample_task):
    # E.g., Handshake failed or agent unreachable immediately after creation
    error_payload = {"code": "HANDSHAKE_TIMEOUT", "message": "Domain agent unreachable"}
    state_machine.transition(
        task=sample_task,
        to_state=TaskState.FAILED,
        trigger="DISPATCH_FAILED",
        actor="Supervisor",
        error_info=error_payload,
    )
    assert sample_task.state == TaskState.FAILED
    assert sample_task.is_terminal is True


def test_transition_to_failure_from_awaiting_approval(state_machine, sample_task):
    state_machine.transition(sample_task, TaskState.IN_PROGRESS, trigger="DISPATCH")
    state_machine.transition(sample_task, TaskState.AWAITING_APPROVAL, trigger="APPROVAL_REQUIRED")
    
    # Manager rejects
    state_machine.transition(
        task=sample_task,
        to_state=TaskState.FAILED,
        trigger="APPROVAL_REJECTED",
        actor="ComplianceOfficer",
        reason="REJECTED: Policy violation",
    )
    assert sample_task.state == TaskState.FAILED
    assert sample_task.is_terminal is True


# ---------------------------------------------------------------------------
# Test 3: Cancellation Transitions
# ---------------------------------------------------------------------------

def test_transition_to_cancelled_from_received(state_machine, sample_task):
    state_machine.transition(
        task=sample_task,
        to_state=TaskState.CANCELLED,
        trigger="USER_ABORT",
        actor="EndUser",
        reason="No longer required",
    )
    assert sample_task.state == TaskState.CANCELLED
    assert sample_task.is_terminal is True


def test_transition_to_cancelled_from_in_progress(state_machine, sample_task):
    state_machine.transition(sample_task, TaskState.IN_PROGRESS, trigger="DISPATCH")
    state_machine.transition(
        task=sample_task,
        to_state=TaskState.CANCELLED,
        trigger="USER_CANCEL",
        actor="EndUser",
    )
    assert sample_task.state == TaskState.CANCELLED
    assert sample_task.is_terminal is True


def test_transition_to_cancelled_from_awaiting_approval(state_machine, sample_task):
    state_machine.transition(sample_task, TaskState.IN_PROGRESS, trigger="DISPATCH")
    state_machine.transition(sample_task, TaskState.AWAITING_APPROVAL, trigger="APPROVAL_REQUIRED")
    state_machine.transition(
        task=sample_task,
        to_state=TaskState.CANCELLED,
        trigger="USER_CANCEL",
        actor="EndUser",
    )
    assert sample_task.state == TaskState.CANCELLED


# ---------------------------------------------------------------------------
# Test 4: Approval Direct Completion (Sign-off)
# ---------------------------------------------------------------------------

def test_transition_from_approval_directly_to_completed(state_machine, sample_task):
    state_machine.transition(sample_task, TaskState.IN_PROGRESS, trigger="DISPATCH")
    state_machine.transition(sample_task, TaskState.AWAITING_APPROVAL, trigger="APPROVAL_REQUIRED")
    
    # Sign-off completes the task immediately
    state_machine.transition(
        task=sample_task,
        to_state=TaskState.COMPLETED,
        trigger="APPROVAL_SIGN_OFF",
        actor="ExecutiveApprover",
        result_reference="phil://artifacts/approved/final_signoff.json",
    )
    assert sample_task.state == TaskState.COMPLETED
    assert sample_task.is_terminal is True


# ---------------------------------------------------------------------------
# Test 5: Invalid State Transitions
# ---------------------------------------------------------------------------

def test_invalid_transition_received_directly_to_completed(state_machine, sample_task):
    with pytest.raises(InvalidStateTransitionError, match="cannot transition from 'RECEIVED' to 'COMPLETED'"):
        state_machine.transition(
            sample_task,
            TaskState.COMPLETED,
            trigger="PREMATURE_COMPLETE",
        )


def test_invalid_transition_from_completed_terminal(state_machine, sample_task):
    state_machine.transition(sample_task, TaskState.IN_PROGRESS, trigger="START")
    state_machine.transition(sample_task, TaskState.COMPLETED, trigger="DONE", result_reference="ref1")

    with pytest.raises(InvalidStateTransitionError, match="Task is in terminal state 'COMPLETED'"):
        state_machine.transition(sample_task, TaskState.IN_PROGRESS, trigger="RESTART")

    with pytest.raises(InvalidStateTransitionError, match="Task is in terminal state 'COMPLETED'"):
        state_machine.transition(sample_task, TaskState.FAILED, trigger="FAIL_AFTER_DONE")


def test_invalid_transition_from_failed_terminal(state_machine, sample_task):
    state_machine.transition(sample_task, TaskState.FAILED, trigger="ABORT")

    with pytest.raises(InvalidStateTransitionError, match="Task is in terminal state 'FAILED'"):
        state_machine.transition(sample_task, TaskState.IN_PROGRESS, trigger="RETRY")


def test_invalid_transition_from_cancelled_terminal(state_machine, sample_task):
    state_machine.transition(sample_task, TaskState.CANCELLED, trigger="CANCEL")

    with pytest.raises(InvalidStateTransitionError, match="Task is in terminal state 'CANCELLED'"):
        state_machine.transition(sample_task, TaskState.COMPLETED, trigger="COMPLETE")


# ---------------------------------------------------------------------------
# Test 6: A2A Status Mapping
# ---------------------------------------------------------------------------

def test_a2a_status_mapping_to_phil_states():
    assert map_a2a_status_to_phil_state("submitted") == TaskState.RECEIVED
    assert map_a2a_status_to_phil_state("QUEUED") == TaskState.RECEIVED
    assert map_a2a_status_to_phil_state("working") == TaskState.IN_PROGRESS
    assert map_a2a_status_to_phil_state("in_progress") == TaskState.IN_PROGRESS
    assert map_a2a_status_to_phil_state("approval_required") == TaskState.AWAITING_APPROVAL
    assert map_a2a_status_to_phil_state("input_required") == TaskState.AWAITING_APPROVAL
    assert map_a2a_status_to_phil_state("completed") == TaskState.COMPLETED
    assert map_a2a_status_to_phil_state("success") == TaskState.COMPLETED
    assert map_a2a_status_to_phil_state("failed") == TaskState.FAILED
    assert map_a2a_status_to_phil_state("error") == TaskState.FAILED
    assert map_a2a_status_to_phil_state("cancelled") == TaskState.CANCELLED
    assert map_a2a_status_to_phil_state("canceled") == TaskState.CANCELLED

    # Check triggers
    assert map_a2a_status_to_trigger("completed") == "A2A_COMPLETED"
    assert map_a2a_status_to_trigger("failed") == "A2A_FAILED"

    # Invalid status raises ValueError
    with pytest.raises(ValueError, match="Unknown A2A task status 'unknown_status'"):
        map_a2a_status_to_phil_state("unknown_status")


# ---------------------------------------------------------------------------
# Test 7: State Persistence Interface (InMemoryTaskRepository)
# ---------------------------------------------------------------------------

def test_in_memory_task_repository(sample_task):
    repo = InMemoryTaskRepository()

    # Initial get non-existent
    assert repo.get("task-12345") is None
    assert repo.exists("task-12345") is False

    # Save
    repo.save(sample_task)
    assert repo.exists("task-12345") is True

    # Get
    retrieved = repo.get("task-12345")
    assert retrieved is not None
    assert retrieved.task_id == "task-12345"
    assert retrieved.correlation_id == "corr-98765"

    # Ensure deep copy mutation safety
    retrieved.state = TaskState.COMPLETED
    assert repo.get("task-12345").state == TaskState.RECEIVED

    # Update
    retrieved.state = TaskState.IN_PROGRESS
    repo.update(retrieved)
    assert repo.get("task-12345").state == TaskState.IN_PROGRESS

    # Update non-existent raises TaskNotFoundError
    non_existent = PhilTask(correlation_id="c", agent_id="a", intent="i")
    with pytest.raises(TaskNotFoundError):
        repo.update(non_existent)

    # List by correlation ID
    matched = repo.list_by_correlation_id("corr-98765")
    assert len(matched) == 1
    assert matched[0].task_id == "task-12345"

    assert len(repo.list_by_correlation_id("unknown-corr")) == 0

