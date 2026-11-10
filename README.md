# PHIL Sprint 3 – Supervisor Handshake and State/Completion Contract

Implementation of the **PHIL AI Governance Platform** Sprint 3 deliverables:
1. **Supervisor–Agent Handshake using A2A protocol**
2. **Supervisor Task State Management**
3. **Completion and Failure Contracts**

---

## 1. Quick Start & Verification

### Prerequisites
* Python 3.11+ / Python 3.14+
* Dependencies: `pydantic >= 2.10`, `httpx >= 0.28`, `pytest >= 8.0`, `packaging >= 24.0`

### Running the Interactive Visual Simulation
To run the full visual simulation displaying all 5 lifecycle and security scenarios with colorized logs:

```powershell
.venv\Scripts\python simulation\visual_runner.py
```

### Running the Test Suite
To run all 45 unit and integration tests inside the `uv` virtual environment:

```powershell
.venv\Scripts\python -m pytest tests/ -v
```

Output summary:
```text
============================= test session starts =============================
tests/test_completion.py    14 passed
tests/test_handshake.py     17 passed
tests/test_state_machine.py 14 passed
============================= 45 passed in 0.38s ==============================
```

---

## 2. Component Architecture

```
                  +----------------------------------------------+
                  |         Upstream Platform / User Auth        |
                  +----------------------------------------------+
                                         |
                                (Authenticated Task)
                                         v
   +--------------------------------------------------------------------------+
   |                     PHIL SUPERVISOR (Sprint 3 Scope)                     |
   |                                                                          |
   |  +--------------------+   Validated Session    +-----------------------+ |
   |  | A2AHandshakeClient | ---------------------> | Task State Machine    | |
   |  | - Agent Card parse |                        | - Permitted matrix    | |
   |  | - Protocol compat  |                        | - Audit trail         | |
   |  | - Capability check |                        | - State: RECEIVED ... | |
   |  | - Session cache    |                        +-----------------------+ |
   |  +--------------------+                                    ^             |
   |            |                                               |             |
   |     (HTTP / A2A)                                  (Outcome Transition)   |
   |            |                                               |             |
   |            v                                   +-----------------------+ |
   |   Domain Agent Card Endpoint                   |  CompletionProcessor  | |
   |   (/.well-known/agent-card.json)               |  - Idempotent dedup   | |
   |                                                |  - Completion / Fail  | |
   |                                                |  - CompletionAck      | |
   |                                                +-----------------------+ |
   |                                                            ^             |
   |                                                            |             |
   +------------------------------------------------------------|-------------+
                                                                |
                                             (A2A Completion / Failure Event)
                                                                |
                                                  +---------------------------+
                                                  |    Domain Agent Outcome   |
                                                  +---------------------------+
```

### Module Layout
* `phil.a2a`: A2A client integration, Agent Card retrieval, protocol version checking, capability validation, and session caching.
* `phil.state`: Authoritative PHIL task state machine, permitted transition rules, audit trail records, in-memory repository interface, and A2A status mapper.
* `phil.completion`: Contract models for `TaskCompletionEvent`, `TaskFailureEvent`, idempotent processing logic, duplicate event deduplication, and `CompletionAck`.
* `simulation`: Dummy domain agents, mock certification authority, HITL policy approval engine, mock artifact registry, and interactive visual runner.

---

## 3. End-to-End Usage Example

```python
from phil.a2a import A2AHandshakeClient, HandshakeRequirements
from phil.state import (
    PhilTask,
    SupervisorTaskStateMachine,
    InMemoryTaskRepository,
    TaskState,
)
from phil.completion import (
    CompletionProcessor,
    TaskCompletionEvent,
    TaskFailureEvent,
)

# 1. Initialize State Repository & State Machine
repo = InMemoryTaskRepository()
sm = SupervisorTaskStateMachine()
completion_proc = CompletionProcessor(repository=repo, state_machine=sm)

# 2. Perform A2A Handshake with Domain Agent
client = A2AHandshakeClient(default_cache_ttl_seconds=300)
req = HandshakeRequirements(
    required_intent="financial_audit",
    min_protocol_version="1.0.0",
    max_protocol_version="1.99.99",
)

result = client.initiate_handshake("https://agents.internal/finance", req)
if result.status == "SUCCESS":
    print(f"Handshake successful! Session ID: {result.session.session_id}")

# 3. Create and Register Authoritative Task
task = PhilTask(
    correlation_id="corr-9921",
    agent_id=result.session.agent_id,
    intent="financial_audit",
)
repo.save(task)
print(f"Task created: {task.task_id} [State: {task.state.value}]")

# 4. Dispatch and Transition to IN_PROGRESS
sm.transition(task, TaskState.IN_PROGRESS, trigger="DISPATCH_ACCEPTED")
repo.update(task)

# 5. Receive Domain Agent Completion Event
completion_event = TaskCompletionEvent(
    task_id=task.task_id,
    correlation_id="corr-9921",
    result_reference="phil://artifacts/reports/ledger-audit.json",
    output_payload={"status": "clean", "records_reviewed": 5000},
)

ack = completion_proc.process_completion(completion_event)
print(f"Acknowledgement: {ack.status.value} - {ack.message}")

# 6. Verify Final Authoritative Task State
final_task = repo.get(task.task_id)
print(f"Final Task State: {final_task.state.value}")
print(f"Result Reference: {final_task.result_reference}")
```

---

## 4. Documentation
For comprehensive architectural specifications, contract schemas, integration assumptions, and future considerations, see [docs/architecture_handover.md](docs/architecture_handover.md).

