"""Mapping between A2A protocol task lifecycle statuses and authoritative PHIL states."""

from typing import Dict, Tuple

from phil.state.models import TaskState

# Mapping of normalized A2A task statuses to PHIL TaskState and canonical trigger name
_A2A_TO_PHIL_MAP: Dict[str, Tuple[TaskState, str]] = {
    # Submitted / Queued phase
    "submitted": (TaskState.RECEIVED, "A2A_SUBMITTED"),
    "queued": (TaskState.RECEIVED, "A2A_QUEUED"),
    "pending": (TaskState.RECEIVED, "A2A_PENDING"),

    # Working phase
    "working": (TaskState.IN_PROGRESS, "A2A_WORKING"),
    "in_progress": (TaskState.IN_PROGRESS, "A2A_IN_PROGRESS"),
    "running": (TaskState.IN_PROGRESS, "A2A_RUNNING"),

    # Approval / Human in the loop phase
    "input_required": (TaskState.AWAITING_APPROVAL, "A2A_INPUT_REQUIRED"),
    "approval_required": (TaskState.AWAITING_APPROVAL, "A2A_APPROVAL_REQUIRED"),
    "human_in_the_loop": (TaskState.AWAITING_APPROVAL, "A2A_HITL_PAUSE"),

    # Successful completion phase
    "completed": (TaskState.COMPLETED, "A2A_COMPLETED"),
    "success": (TaskState.COMPLETED, "A2A_SUCCESS"),
    "done": (TaskState.COMPLETED, "A2A_DONE"),

    # Failure phase
    "failed": (TaskState.FAILED, "A2A_FAILED"),
    "error": (TaskState.FAILED, "A2A_ERROR"),

    # Cancellation phase
    "cancelled": (TaskState.CANCELLED, "A2A_CANCELLED"),
    "canceled": (TaskState.CANCELLED, "A2A_CANCELED"),
    "aborted": (TaskState.CANCELLED, "A2A_ABORTED"),
}


def map_a2a_status_to_phil_state(a2a_status: str) -> TaskState:
    """Map an incoming A2A domain agent status to the corresponding PHIL TaskState.

    Args:
        a2a_status: String status from A2A event or polling response.

    Returns:
        The mapped TaskState enum.

    Raises:
        ValueError: If the status string cannot be mapped to any known PHIL state.
    """
    normalized = a2a_status.strip().lower()
    entry = _A2A_TO_PHIL_MAP.get(normalized)
    if entry is None:
        raise ValueError(
            f"Unknown A2A task status '{a2a_status}'. Cannot map to PHIL lifecycle state. "
            f"Supported statuses: {list(_A2A_TO_PHIL_MAP.keys())}"
        )
    return entry[0]


def map_a2a_status_to_trigger(a2a_status: str) -> str:
    """Map an A2A status string to a standard PHIL audit trigger label."""
    normalized = a2a_status.strip().lower()
    entry = _A2A_TO_PHIL_MAP.get(normalized)
    if entry is None:
        return f"A2A_UPDATE_{normalized.upper()}"
    return entry[1]

