"""State persistence interface and in-memory implementation for PHIL tasks."""

from abc import ABC, abstractmethod
import copy
from threading import RLock
from typing import Dict, List, Optional

from phil.state.exceptions import TaskNotFoundError
from phil.state.models import PhilTask


class TaskRepository(ABC):
    """Abstract interface defining the state persistence contract for PHIL tasks."""

    @abstractmethod
    def get(self, task_id: str) -> Optional[PhilTask]:
        """Retrieve a task by its unique task_id."""
        pass

    @abstractmethod
    def save(self, task: PhilTask) -> None:
        """Persist a new task or overwrite an existing task."""
        pass

    @abstractmethod
    def update(self, task: PhilTask) -> None:
        """Update an existing task in the store."""
        pass

    @abstractmethod
    def exists(self, task_id: str) -> bool:
        """Check whether a task exists by task_id."""
        pass

    @abstractmethod
    def list_by_correlation_id(self, correlation_id: str) -> List[PhilTask]:
        """List all tasks associated with a given correlation ID."""
        pass


class InMemoryTaskRepository(TaskRepository):
    """Thread-safe in-memory task repository for local execution and testing."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._store: Dict[str, PhilTask] = {}

    def get(self, task_id: str) -> Optional[PhilTask]:
        with self._lock:
            task = self._store.get(task_id)
            if task is None:
                return None
            # Return deepcopy to prevent unmanaged in-place mutation outside state machine
            return copy.deepcopy(task)

    def save(self, task: PhilTask) -> None:
        with self._lock:
            self._store[task.task_id] = copy.deepcopy(task)

    def update(self, task: PhilTask) -> None:
        with self._lock:
            if task.task_id not in self._store:
                raise TaskNotFoundError(f"Cannot update non-existent task '{task.task_id}'")
            self._store[task.task_id] = copy.deepcopy(task)

    def exists(self, task_id: str) -> bool:
        with self._lock:
            return task_id in self._store

    def list_by_correlation_id(self, correlation_id: str) -> List[PhilTask]:
        with self._lock:
            return [
                copy.deepcopy(t)
                for t in self._store.values()
                if t.correlation_id == correlation_id
            ]

    def clear(self) -> None:
        """Clear all tasks from the store."""
        with self._lock:
            self._store.clear()

