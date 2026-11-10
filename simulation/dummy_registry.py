"""Dummy Artifact Registry simulating the external PHIL Artifact Registry."""

from datetime import datetime, timezone
import hashlib
import json
import logging
from typing import Any, Dict, Optional
from uuid import uuid4

logger = logging.getLogger("simulation.registry")


class DummyArtifactRegistry:
    """Simulates the enterprise Artifact Registry where domain agent outputs are registered."""

    def __init__(self) -> None:
        self._artifacts: Dict[str, Dict[str, Any]] = {}

    def register_artifact(
        self,
        task_id: str,
        artifact_name: str,
        content: Any,
        content_type: str = "application/json",
    ) -> str:
        """Register a new task outcome artifact and return a persistent URI reference."""
        raw_bytes = json.dumps(content, default=str).encode("utf-8")
        checksum = hashlib.sha256(raw_bytes).hexdigest()
        artifact_id = f"art-{uuid4().hex[:12]}"
        uri = f"phil://artifacts/{task_id}/{artifact_name}"

        record = {
            "artifact_id": artifact_id,
            "uri": uri,
            "task_id": task_id,
            "artifact_name": artifact_name,
            "content_type": content_type,
            "checksum_sha256": checksum,
            "size_bytes": len(raw_bytes),
            "created_at": datetime.now(timezone.utc),
            "payload": content,
        }

        self._artifacts[uri] = record
        logger.info(
            "[REGISTRY-REGISTER] Registered artifact at '%s' (size=%d bytes, sha256=%s...)",
            uri, len(raw_bytes), checksum[:10]
        )
        return uri

    def get_artifact(self, uri: str) -> Optional[Dict[str, Any]]:
        """Retrieve registered artifact metadata by URI."""
        artifact = self._artifacts.get(uri)
        if artifact:
            logger.info("[REGISTRY-LOOKUP] Artifact '%s' found (Task: %s)", uri, artifact["task_id"])
            return artifact
        logger.warning("[REGISTRY-LOOKUP-MISS] Artifact '%s' does not exist.", uri)
        return None

