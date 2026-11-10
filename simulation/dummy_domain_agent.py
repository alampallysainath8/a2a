"""Dummy Domain Agent implementing A2A server endpoint simulation."""

import json
import logging
from pathlib import Path
from typing import Any, Callable, Dict, Optional
from uuid import uuid4

import httpx

from phil.completion.models import TaskCompletionEvent, TaskFailureEvent
from simulation.dummy_registry import DummyArtifactRegistry

logger = logging.getLogger("simulation.domain_agent")


class DummyDomainAgent:
    """Simulates an external Domain Agent supporting the A2A communication protocol."""

    def __init__(
        self,
        card_data: Dict[str, Any],
        base_url: str = "https://agents.internal/finance",
        artifact_registry: Optional[DummyArtifactRegistry] = None,
        simulate_timeout: bool = False,
        simulate_server_error: bool = False,
    ) -> None:
        self.card_data = card_data
        self.base_url = base_url.rstrip("/")
        self.registry = artifact_registry or DummyArtifactRegistry()
        self.simulate_timeout = simulate_timeout
        self.simulate_server_error = simulate_server_error

    @classmethod
    def from_card_file(
        cls,
        card_path: str,
        base_url: str = "https://agents.internal/finance",
        artifact_registry: Optional[DummyArtifactRegistry] = None,
        **kwargs: Any,
    ) -> "DummyDomainAgent":
        """Factory creating an agent from a JSON card file."""
        path = Path(card_path)
        with open(path, "r", encoding="utf-8") as f:
            card_data = json.load(f)
        return cls(card_data=card_data, base_url=base_url, artifact_registry=artifact_registry, **kwargs)

    def get_http_transport(self) -> httpx.MockTransport:
        """Create an HTTP mock transport simulating the agent's web server."""
        def handler(request: httpx.Request) -> httpx.Response:
            url_str = str(request.url)
            logger.debug("[DOMAIN-AGENT-HTTP] Received %s request to %s", request.method, url_str)

            if self.simulate_timeout:
                logger.warning("[DOMAIN-AGENT-HTTP] Simulating network timeout for %s", url_str)
                raise httpx.ReadTimeout(f"Timed out waiting for response from {url_str}")

            if self.simulate_server_error:
                logger.warning("[DOMAIN-AGENT-HTTP] Simulating HTTP 500 error for %s", url_str)
                return httpx.Response(500, text="Internal Agent Execution Error")

            # Route 1: A2A Agent Card endpoint
            if url_str.endswith("/.well-known/agent-card.json") or url_str.endswith("/agent-card.json"):
                logger.info("[DOMAIN-AGENT-HTTP] Serving Agent Card for '%s'", self.card_data.get("name"))
                return httpx.Response(200, json=self.card_data)

            # Route 2: Health check
            if url_str.endswith("/health"):
                return httpx.Response(200, json={"status": "UP", "agent": self.card_data.get("name")})

            return httpx.Response(404, text=f"Endpoint '{url_str}' not found on Domain Agent.")

        return httpx.MockTransport(handler)

    def execute_task_success(
        self,
        task_id: str,
        correlation_id: str,
        result_payload: Dict[str, Any],
    ) -> TaskCompletionEvent:
        """Simulate task execution culminating in an artifact and completion event."""
        logger.info(
            "[DOMAIN-AGENT-EXEC] Agent '%s' executing task '%s' (Corr: %s)...",
            self.card_data.get("name"), task_id, correlation_id
        )

        # Register artifact in external registry
        artifact_uri = self.registry.register_artifact(
            task_id=task_id,
            artifact_name="audit_verified_ledger.json",
            content=result_payload,
        )

        event = TaskCompletionEvent(
            event_id=f"evt-comp-{uuid4().hex[:8]}",
            task_id=task_id,
            correlation_id=correlation_id,
            result_reference=artifact_uri,
            output_payload={"summary": "Ledger verified with zero non-compliance exceptions."},
            metadata={"processed_by": self.card_data.get("agent_id")},
        )
        logger.info("[DOMAIN-AGENT-EXEC] Emitting TaskCompletionEvent: %s (Result: %s)", event.event_id, artifact_uri)
        return event

    def execute_task_failure(
        self,
        task_id: str,
        correlation_id: str,
        error_code: str,
        error_message: str,
        retryable: bool = False,
    ) -> TaskFailureEvent:
        """Simulate task execution failure producing a failure event."""
        logger.warning(
            "[DOMAIN-AGENT-EXEC] Agent '%s' execution failed on task '%s': %s - %s",
            self.card_data.get("name"), task_id, error_code, error_message
        )
        event = TaskFailureEvent(
            event_id=f"evt-fail-{uuid4().hex[:8]}",
            task_id=task_id,
            correlation_id=correlation_id,
            error_code=error_code,
            error_message=error_message,
            retryable=retryable,
            metadata={"reported_by": self.card_data.get("agent_id")},
        )
        return event

