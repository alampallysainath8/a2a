"""Dummy Governance and Certification services simulating external PHIL governance."""

from datetime import datetime, timezone
import logging
from typing import Any, Dict, Optional, Tuple
from uuid import uuid4

logger = logging.getLogger("simulation.governance")


class DummyCertificationService:
    """Simulates the external PHIL Governance Certification Authority."""

    def __init__(self) -> None:
        # Registry of certified agent IDs and their validity status
        self._certified_registry: Dict[str, Dict[str, Any]] = {
            "PHIL-CERT-2026-9921": {
                "agent_name": "Corporate Finance Ledger Agent",
                "tier": "Tier-1-Enterprise",
                "valid_until": "2027-12-31",
                "status": "ACTIVE",
            },
            "PHIL-CERT-2026-MEDIA": {
                "agent_name": "Creative Image Synthesizer Agent",
                "tier": "Tier-3-Sandboxed",
                "valid_until": "2026-12-31",
                "status": "ACTIVE",
            },
            "PHIL-CERT-2023-EXPIRED": {
                "agent_name": "Legacy Payroll Agent",
                "tier": "Tier-2-Internal",
                "valid_until": "2024-01-01",
                "status": "REVOKED",
            },
        }

    def verify_certification(self, certification_id: Optional[str]) -> Tuple[bool, str]:
        """Verify whether an agent card's certification ID is active and authorized."""
        if not certification_id:
            logger.warning("[GOV-CERT] Agent Card does not provide a certification_id.")
            return False, "Agent lacks certification claim."

        cert = self._certified_registry.get(certification_id)
        if not cert:
            logger.warning("[GOV-CERT] Unknown certification_id '%s'.", certification_id)
            return False, f"Certification ID '{certification_id}' not found in PHIL registry."

        if cert["status"] != "ACTIVE":
            logger.warning(
                "[GOV-CERT] Certification '%s' is not active (status: %s).",
                certification_id, cert["status"]
            )
            return False, f"Certification '{certification_id}' is {cert['status']}."

        logger.info(
            "[GOV-CERT] Verified certification '%s' for '%s' (Tier: %s).",
            certification_id, cert["agent_name"], cert["tier"]
        )
        return True, f"Valid certification (Tier: {cert['tier']})."


class DummyApprovalService:
    """Simulates Human-In-The-Loop (HITL) and Policy Approval evaluation."""

    def __init__(self, approval_threshold: float = 100000.0) -> None:
        self.approval_threshold = approval_threshold

    def requires_approval(self, task_metadata: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """Determine if a task requires Human-In-The-Loop governance sign-off."""
        amount = task_metadata.get("transaction_amount", 0.0)
        if amount >= self.approval_threshold:
            reason = f"Transaction amount ${amount:,.2f} exceeds policy threshold of ${self.approval_threshold:,.2f}."
            logger.info("[GOV-POLICY] Governance gate triggered: %s", reason)
            return True, reason
        return False, None

    def simulate_human_decision(
        self,
        task_id: str,
        reason: str,
        context: Dict[str, Any],
        decision: str = "APPROVED",
        approver: str = "ComplianceOfficer-SarahChen",
    ) -> Dict[str, Any]:
        """Simulate a compliance officer review and sign-off."""
        logger.info(
            "[GOV-HITL-DECISION] %s reviewed task '%s': Decision=%s (Reason: %s)",
            approver, task_id, decision, reason
        )
        return {
            "approval_id": f"appr-{uuid4()}",
            "decision": decision,
            "approved_by": approver,
            "approved_at": datetime.now(timezone.utc),
            "review_notes": f"Reviewed context: {context}. Compliance approval granted.",
        }

