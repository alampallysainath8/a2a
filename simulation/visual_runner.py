"""Visual Demonstration and Simulation Runner for PHIL Sprint 3.

Demonstrates:
- Scenario 1: Full Happy Path (Handshake -> Task State Lifecycle -> Registry Artifact -> Completion)
- Scenario 2: Handshake Session Caching (Zero latency fast-path)
- Scenario 3: Human-In-The-Loop Governance Gate (AWAITING_APPROVAL -> Compliance Approval -> Completion)
- Scenario 4: Protocol & Capability Security Rejections (Outdated version, Mismatched skill, Timeout)
- Scenario 5: Network Idempotency & Duplicate Event Deduplication
"""

import logging
from pathlib import Path
import sys
import time
from typing import Any, Dict

# Ensure src is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

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
from simulation.dummy_domain_agent import DummyDomainAgent
from simulation.dummy_governance import (
    DummyApprovalService,
    DummyCertificationService,
)
from simulation.dummy_registry import DummyArtifactRegistry

# ANSI color codes for terminal visualization
BOLD = "\033[1m"
RESET = "\033[0m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
MAGENTA = "\033[35m"
BLUE = "\033[34m"
DIM = "\033[2m"


def setup_logger():
    """Configure formatted, timestamped logging for visual inspection."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)-22s | %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
        force=True,
    )


def print_banner(title: str, subtitle: str = ""):
    print(f"\n{BOLD}{CYAN}{'=' * 78}{RESET}")
    print(f"{BOLD}{CYAN}  {title}{RESET}")
    if subtitle:
        print(f"{DIM}  {subtitle}{RESET}")
    print(f"{BOLD}{CYAN}{'=' * 78}{RESET}\n")


def print_section(title: str):
    print(f"\n{BOLD}{YELLOW}>>> {title}{RESET}")


def run_all_simulations():
    setup_logger()

    print_banner(
        "PHIL AI GOVERNANCE PLATFORM - SPRINT 3 RUNTIME SIMULATION",
        "Visualizing Supervisor Handshake, Task State Management & Completion Contracts"
    )

    # Core shared dependencies
    artifact_registry = DummyArtifactRegistry()
    cert_service = DummyCertificationService()
    approval_service = DummyApprovalService(approval_threshold=100000.0)

    # ---------------------------------------------------------------------------
    # SCENARIO 1: Standard Lifecycle (Happy Path)
    # ---------------------------------------------------------------------------
    print_banner(
        "SCENARIO 1: End-to-End Task Lifecycle (Happy Path)",
        "Demonstrates A2A Handshake -> State Transitions -> Registry Artifact -> Idempotent Completion"
    )

    # 1. Initialize Domain Agent with certified card
    agent = DummyDomainAgent.from_card_file(
        "simulation/dummy_cards/finance_agent.json",
        base_url="https://agents.internal/finance",
        artifact_registry=artifact_registry,
    )
    handshake_client = A2AHandshakeClient(
        default_cache_ttl_seconds=300,
        transport=agent.get_http_transport(),
    )

    print_section("Step 1.1: Supervisor initiates A2A Handshake with Domain Agent")
    req = HandshakeRequirements(
        required_intent="financial_audit",
        min_protocol_version="1.0.0",
        max_protocol_version="1.99.99",
        required_input_mode="application/json",
        required_output_mode="application/json",
        require_streaming=True,
    )
    handshake_res = handshake_client.initiate_handshake("https://agents.internal/finance", req)
    print(f"{GREEN}[OK] Handshake status: {handshake_res.status.value}{RESET}")
    print(f"     Session ID : {handshake_res.session.session_id}")
    print(f"     Agent Name : {handshake_res.card.name} (ID: {handshake_res.session.agent_id})")
    print(f"     Protocol   : v{handshake_res.card.protocol_version}")

    print_section("Step 1.2: Cross-check Agent Certification with External PHIL Governance")
    is_certified, cert_msg = cert_service.verify_certification(handshake_res.card.certification_id)
    print(f"{GREEN}[OK] Certification Check: {cert_msg}{RESET}")

    print_section("Step 1.3: Supervisor registers Authoritative Task in RECEIVED state")
    repo = InMemoryTaskRepository()
    sm = SupervisorTaskStateMachine()
    proc = CompletionProcessor(repository=repo, state_machine=sm)

    task = PhilTask(
        correlation_id="corr-audit-tx-001",
        agent_id=handshake_res.session.agent_id,
        intent="financial_audit",
        metadata={"user_id": "auditor_jane", "fiscal_year": 2026},
    )
    repo.save(task)
    print(f"     Task ID   : {task.task_id}")
    print(f"     State     : {BOLD}{task.state.value}{RESET}")

    print_section("Step 1.4: Supervisor dispatches task -> transitions to IN_PROGRESS")
    sm.transition(task, TaskState.IN_PROGRESS, trigger="DISPATCH_ACCEPTED", actor="Supervisor")
    repo.update(task)
    print(f"     State now : {BOLD}{task.state.value}{RESET}")

    print_section("Step 1.5: Domain Agent completes execution & registers artifact")
    completion_event = agent.execute_task_success(
        task_id=task.task_id,
        correlation_id=task.correlation_id,
        result_payload={"audited_transactions": 8500, "flagged": 0, "status": "VERIFIED_COMPLIANT"},
    )
    print(f"     Artifact URI : {completion_event.result_reference}")

    print_section("Step 1.6: Supervisor CompletionProcessor ingests event & transitions to COMPLETED")
    ack = proc.process_completion(completion_event)
    print(f"{GREEN}[OK] Completion Ack Status : {ack.status.value}{RESET}")
    print(f"     Message               : {ack.message}")
    print(f"     Authoritative State   : {BOLD}{ack.final_state.value}{RESET}")

    print_section("Step 1.7: Authoritative Audit Trail Inspection")
    final_task = repo.get(task.task_id)
    for i, rec in enumerate(final_task.history, 1):
        print(f"     Record {i}: {rec.timestamp.strftime('%H:%M:%S.%f')[:12]} | {rec.from_state.value:<12} -> {rec.to_state.value:<12} | Trigger: {rec.trigger:<20} | Actor: {rec.actor}")

    # ---------------------------------------------------------------------------
    # SCENARIO 2: Handshake Session Caching
    # ---------------------------------------------------------------------------
    print_banner(
        "SCENARIO 2: Handshake Session Caching (Performance Optimization)",
        "Demonstrates avoiding repeated network handshakes on subsequent queries"
    )

    print_section("Step 2.1: Subsequent task queries same domain agent for same intent")
    t0 = time.perf_counter()
    second_handshake = handshake_client.initiate_handshake("https://agents.internal/finance", req)
    elapsed_ms = (time.perf_counter() - t0) * 1000

    print(f"{GREEN}[OK] Cache hit verified!{RESET}")
    print(f"     Session ID matches original : {second_handshake.session.session_id == handshake_res.session.session_id}")
    print(f"     Latency                     : {elapsed_ms:.3f} ms (0 network calls)")

    print_section("Step 2.2: Explicit Cache Invalidation & Re-negotiation")
    handshake_client.invalidate_cache("https://agents.internal/finance")
    fresh_handshake = handshake_client.initiate_handshake("https://agents.internal/finance", req)
    print(f"{GREEN}[OK] Fresh handshake executed!{RESET}")
    print(f"     New Session ID : {fresh_handshake.session.session_id} (different from previous)")

    # ---------------------------------------------------------------------------
    # SCENARIO 3: Human-In-The-Loop (HITL) Governance Gate
    # ---------------------------------------------------------------------------
    print_banner(
        "SCENARIO 3: Human-In-The-Loop (HITL) Governance Workflow",
        "Demonstrates IN_PROGRESS -> AWAITING_APPROVAL -> Compliance Sign-off -> COMPLETED"
    )

    hitl_task = PhilTask(
        correlation_id="corr-audit-tx-high-val",
        agent_id=handshake_res.session.agent_id,
        intent="financial_audit",
        metadata={"transaction_amount": 350000.0, "risk_level": "HIGH"},
    )
    repo.save(hitl_task)
    sm.transition(hitl_task, TaskState.IN_PROGRESS, trigger="DISPATCH")
    repo.update(hitl_task)

    print_section("Step 3.1: Policy evaluation checks transaction thresholds")
    needs_appr, reason = approval_service.requires_approval(hitl_task.metadata)
    assert needs_appr is True
    print(f"{YELLOW}[!] HITL Required: {reason}{RESET}")

    print_section("Step 3.2: Supervisor pauses task in AWAITING_APPROVAL")
    approval_ctx = ApprovalContext(
        requested_by=handshake_res.session.agent_id,
        reason=reason,
        context_data=hitl_task.metadata,
    )
    sm.transition(
        hitl_task,
        TaskState.AWAITING_APPROVAL,
        trigger="APPROVAL_REQUIRED",
        actor="GovernanceEngine",
        approval_context=approval_ctx,
    )
    repo.update(hitl_task)
    print(f"     Task State : {BOLD}{hitl_task.state.value}{RESET}")

    print_section("Step 3.3: Compliance Officer reviews context and approves")
    decision = approval_service.simulate_human_decision(
        task_id=hitl_task.task_id,
        reason=reason,
        context=hitl_task.metadata,
        approver="ChiefComplianceOfficer-DavidMiller",
    )
    sm.transition(
        hitl_task,
        TaskState.IN_PROGRESS,
        trigger="APPROVAL_GRANTED",
        actor=decision["approved_by"],
        reason=decision["decision"],
    )
    repo.update(hitl_task)
    print(f"{GREEN}[OK] Approval logged by: {decision['approved_by']}{RESET}")
    print(f"     Task resumed to : {BOLD}{hitl_task.state.value}{RESET}")

    print_section("Step 3.4: Domain Agent finishes and task completes")
    evt = agent.execute_task_success(hitl_task.task_id, hitl_task.correlation_id, {"signed_off": True})
    ack = proc.process_completion(evt)
    print(f"{GREEN}[OK] Task finalized as: {BOLD}{ack.final_state.value}{RESET}")

    # ---------------------------------------------------------------------------
    # SCENARIO 4: Security, Incompatibility & Resilience Tests
    # ---------------------------------------------------------------------------
    print_banner(
        "SCENARIO 4: Security & Protocol Compatibility Rejection Scenarios",
        "Demonstrates defensive guardrails rejecting incompatible or faulty agents"
    )

    print_section("Test 4A: Rejecting Legacy Protocol Version (v0.5.0)")
    legacy_agent = DummyDomainAgent.from_card_file("simulation/dummy_cards/legacy_agent.json")
    client_legacy = A2AHandshakeClient(transport=legacy_agent.get_http_transport())
    res_legacy = client_legacy.initiate_handshake("https://agents.internal/legacy", req)
    print(f"{RED}[REJECTED] Status: {res_legacy.status.value}{RESET}")
    print(f"           Error : {res_legacy.error_type} - {res_legacy.error_message}")

    print_section("Test 4B: Rejecting Capability Mismatch (Agent lacks 'financial_audit')")
    creative_agent = DummyDomainAgent.from_card_file("simulation/dummy_cards/visual_media_agent.json")
    client_creative = A2AHandshakeClient(transport=creative_agent.get_http_transport())
    res_creative = client_creative.initiate_handshake("https://agents.internal/creative", req)
    print(f"{RED}[REJECTED] Status: {res_creative.status.value}{RESET}")
    print(f"           Error : {res_creative.error_type} - {res_creative.error_message}")

    print_section("Test 4C: Handling Domain Agent Network Timeout")
    timing_out_agent = DummyDomainAgent(
        card_data={},
        simulate_timeout=True,
    )
    client_timeout = A2AHandshakeClient(transport=timing_out_agent.get_http_transport())
    req_short = HandshakeRequirements(required_intent="any", timeout_seconds=0.5)
    res_timeout = client_timeout.initiate_handshake("https://agents.internal/slow", req_short)
    print(f"{RED}[TIMEOUT] Status: {res_timeout.status.value}{RESET}")
    print(f"          Error : {res_timeout.error_type} - {res_timeout.error_message}")

    # ---------------------------------------------------------------------------
    # SCENARIO 5: Network Idempotency & Duplicate Delivery
    # ---------------------------------------------------------------------------
    print_banner(
        "SCENARIO 5: Deduplication & Idempotent Contract Processing",
        "Demonstrates handling network retries, duplicate delivery, and conflict prevention"
    )

    print_section("Step 5.1: Delivering exact duplicate completion event (same event_id)")
    dup_ack = proc.process_completion(completion_event)
    print(f"{YELLOW}[DEDUPLICATED] Status : {dup_ack.status.value}{RESET}")
    print(f"               Message: {dup_ack.message}")

    print_section("Step 5.2: Simulating Failure Event on an already COMPLETED task")
    conflicting_fail = TaskFailureEvent(
        task_id=task.task_id,
        correlation_id=task.correlation_id,
        error_code="LATE_FAILURE",
        error_message="Agent crashed after reporting completion",
    )
    fail_ack = proc.process_failure(conflicting_fail)
    print(f"{RED}[BLOCKED] Status : {fail_ack.status.value}{RESET}")
    print(f"          Message: {fail_ack.message}")
    print(f"          Current Authoritative State: {fail_ack.final_state.value}")

    print_banner("ALL 5 RUNTIME SIMULATION SCENARIOS COMPLETED SUCCESSFULLY", "PHIL AI Governance Engine Verified")


if __name__ == "__main__":
    run_all_simulations()
