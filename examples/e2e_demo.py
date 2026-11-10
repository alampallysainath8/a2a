"""End-to-End Demonstration of PHIL Sprint 3 Components.

Demonstrates:
1. Live A2A Handshake with Domain Agent (and session caching).
2. Supervisor Task lifecycle management & audit logging.
3. Governance approval pause and sign-off.
4. Idempotent Completion and Failure processing.
"""

import httpx

from phil.a2a import (
    A2AHandshakeClient,
    HandshakeRequirements,
    HandshakeStatus,
)
from phil.completion import (
    AckStatus,
    CompletionProcessor,
    TaskCompletionEvent,
    TaskFailureEvent,
)
from phil.state import (
    ApprovalContext,
    InMemoryTaskRepository,
    PhilTask,
    SupervisorTaskStateMachine,
    TaskState,
)


def run_demo():
    print("=" * 70)
    print("PHIL Sprint 3: Supervisor Handshake & Lifecycle Contracts Demo")
    print("=" * 70)

    # -----------------------------------------------------------------------
    # Setup: Mock Domain Agent Server Transport
    # -----------------------------------------------------------------------
    mock_agent_card = {
        "name": "Finance Audit Domain Agent",
        "description": "Performs corporate financial auditing and compliance checks",
        "version": "1.4.0",
        "protocol_version": "1.0.0",
        "agent_id": "agent-finance-prod-01",
        "skills": [
            {
                "id": "financial_audit",
                "name": "Financial Audit",
                "description": "Audits ledger records against financial policies",
                "input_modes": ["text/plain", "application/json"],
                "output_modes": ["text/plain", "application/json"],
            }
        ],
        "capabilities": {
            "streaming": True,
            "push_notifications": False,
            "state_recovery": True,
        },
        "certification_id": "PHIL-CERT-2026-4412",
    }

    def agent_http_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("agent-card.json"):
            return httpx.Response(200, json=mock_agent_card)
        return httpx.Response(404, text="Not Found")

    transport = httpx.MockTransport(agent_http_handler)

    # -----------------------------------------------------------------------
    # 1. A2A Handshake & Session Caching
    # -----------------------------------------------------------------------
    print("\n[Step 1] Initiating Supervisor-side A2A Handshake...")
    client = A2AHandshakeClient(default_cache_ttl_seconds=300, transport=transport)
    requirements = HandshakeRequirements(
        required_intent="financial_audit",
        min_protocol_version="1.0.0",
        max_protocol_version="1.99.99",
        required_input_mode="application/json",
        required_output_mode="application/json",
    )

    result = client.initiate_handshake("https://domain-agent.internal/finance", requirements)
    assert result.status == HandshakeStatus.SUCCESS
    print(f"  Handshake Status: {result.status.value}")
    print(f"  Agent Identity   : {result.card.name} (ID: {result.session.agent_id})")
    print(f"  Protocol Version : {result.card.protocol_version}")
    print(f"  Matched Skill    : {result.session.matched_skill.name}")
    print(f"  Session ID       : {result.session.session_id}")
    print(f"  Session Expiry   : {result.session.expires_at.isoformat()}")

    # Test cache fast-path
    cached_result = client.initiate_handshake("https://domain-agent.internal/finance", requirements)
    print(f"  Fast-path Cache Reused: Session IDs match = {cached_result.session.session_id == result.session.session_id}")

    # -----------------------------------------------------------------------
    # 2. Authoritative Task Creation & State Machine Lifecycle
    # -----------------------------------------------------------------------
    print("\n[Step 2] Initializing Authoritative PHIL Task...")
    repo = InMemoryTaskRepository()
    sm = SupervisorTaskStateMachine()
    proc = CompletionProcessor(repository=repo, state_machine=sm)

    task = PhilTask(
        correlation_id="corr-audit-txn-8819",
        agent_id=result.session.agent_id,
        intent="financial_audit",
        metadata={"requester": "CorporateAuditor-01", "quarter": "Q4-2026"},
    )
    repo.save(task)
    print(f"  Task Created: {task.task_id}")
    print(f"  Initial State: {task.state.value}")

    # Dispatch to Domain Agent -> IN_PROGRESS
    sm.transition(task, TaskState.IN_PROGRESS, trigger="DISPATCH_ACCEPTED", actor="Supervisor")
    repo.update(task)
    print(f"  Transitioned to : {task.state.value}")

    # -----------------------------------------------------------------------
    # 3. Governance Approval Gate (AWAITING_APPROVAL -> IN_PROGRESS)
    # -----------------------------------------------------------------------
    print("\n[Step 3] Domain Agent triggers Governance HITL gate...")
    approval_ctx = ApprovalContext(
        requested_by=result.session.agent_id,
        reason="Transaction exceeds $100,000 threshold; requires Finance Director approval",
        context_data={"variance_amount": 145000.0, "account_id": "ACC-9921"},
    )
    sm.transition(
        task,
        TaskState.AWAITING_APPROVAL,
        trigger="APPROVAL_REQUIRED",
        actor="DomainAgent",
        approval_context=approval_ctx,
    )
    repo.update(task)
    print(f"  Task State: {task.state.value}")
    print(f"  Approval Reason: {task.approval_context.reason}")

    # Human Approver signs off
    sm.transition(
        task,
        TaskState.IN_PROGRESS,
        trigger="APPROVAL_GRANTED",
        actor="FinanceDirector-JaneDoe",
        reason="Variance verified against approved budget line item #84.",
    )
    repo.update(task)
    print(f"  Approval granted by: {task.approval_context.approved_by}")
    print(f"  Task resumed to    : {task.state.value}")

    # -----------------------------------------------------------------------
    # 4. Completion Event Processing & Idempotency
    # -----------------------------------------------------------------------
    print("\n[Step 4] Processing Domain Agent Completion Event...")
    completion_evt = TaskCompletionEvent(
        event_id="evt-delivery-001",
        task_id=task.task_id,
        correlation_id=task.correlation_id,
        result_reference="phil://artifacts/audit-reports/2026-q4-verified.json",
        output_payload={"status": "APPROVED", "adjustments_made": 0},
    )

    ack = proc.process_completion(completion_evt)
    print(f"  Acknowledgement ID: {ack.ack_id}")
    print(f"  Ack Status        : {ack.status.value}")
    print(f"  Message           : {ack.message}")
    print(f"  Final Task State  : {ack.final_state.value}")

    # Test Duplicate Delivery
    print("\n[Step 5] Simulating Duplicate Event Delivery (Idempotency Check)...")
    duplicate_ack = proc.process_completion(completion_evt)
    print(f"  Duplicate Delivery Ack Status: {duplicate_ack.status.value}")
    print(f"  Message                      : {duplicate_ack.message}")

    # -----------------------------------------------------------------------
    # 5. Audit Trail Verification
    # -----------------------------------------------------------------------
    print("\n[Step 6] Audit Trail (State Transition Records):")
    final_task = repo.get(task.task_id)
    for idx, rec in enumerate(final_task.history, 1):
        print(f"  [{idx}] {rec.timestamp.strftime('%H:%M:%S')} | {rec.from_state.value:<17} -> {rec.to_state.value:<17} | Trigger: {rec.trigger:<20} | Actor: {rec.actor or 'N/A'}")

    print("\n" + "=" * 70)
    print("Demo execution completed successfully.")
    print("=" * 70)


if __name__ == "__main__":
    run_demo()

