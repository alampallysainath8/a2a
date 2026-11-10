# PHIL Sprint 3 – Supervisor Handshake and State/Completion Contract

**Story Points: 3**

Act as a Senior Python Engineer working on the PHIL AI Governance Platform.

Your task is to implement only the assigned Sprint 3 activity.

## 1. Strict implementation scope

Implement exactly these three areas:

1. Supervisor–Agent handshake using A2A.
2. Supervisor task state management.
3. Completion and failure contracts.

Do not expand the implementation beyond these requirements.

## 2. Existing architecture assumptions

- Artifact Registry already exists and is owned by another team.
- Certification is handled by the existing PHIL governance process.
- User authentication and authorization are handled by their respective platform components.
- Supervisor is responsible for PHIL-level task lifecycle management.
- A2A is the communication protocol for Supervisor–Domain Agent interaction.

Do not implement Artifact Registry, certification, user authentication or authorization services.

Consume existing interfaces or use clearly identified mocks where integration specifications are unavailable.

## 3. Implementation A: A2A handshake

Implement the Supervisor-side A2A integration required for establishing communication with a Domain Agent.

Requirements:

- A2A client integration.
- Agent Card retrieval and parsing.
- Agent identity validation.
- Protocol version compatibility validation.
- Supported intents and capabilities validation.
- Handshake success and failure handling.
- Communication timeout handling.

Do not create a custom agent communication protocol.

Reuse A2A specifications and existing SDK functionality wherever appropriate.

Do not repeat full handshake validation for every user query unnecessarily.

Keep the handshake implementation limited to the assigned task.

## 4. Implementation B: Supervisor task state management

Define and implement the PHIL-level task lifecycle.

Proposed states:

- RECEIVED
- IN_PROGRESS
- AWAITING_APPROVAL
- COMPLETED
- FAILED
- CANCELLED

Requirements:

- Task model.
- Task ID.
- Correlation ID.
- State definitions.
- Permitted transitions.
- Transition validation.
- Invalid transition handling.
- State persistence interface.

Supervisor must own the authoritative PHIL task state.

Map relevant A2A task lifecycle updates to PHIL task states.

Do not implement a complete Supervisor orchestration engine or domain-agent workflow.

## 5. Implementation C: Completion and failure contract

Define completion and failure contracts.

Requirements:

- Completion event model.
- Failure event model.
- Event ID.
- Task ID.
- Correlation ID.
- Result reference.
- Error information.
- Timestamp.
- Event validation.
- A2A outcome-to-PHIL state mapping.
- Duplicate completion handling.
- Idempotent logical processing.
- Completion acknowledgement.

Do not introduce a new messaging infrastructure.

## 6. Technology and implementation standards

Use:

- Python.
- Pydantic where appropriate.
- Existing A2A SDK or supported A2A implementation.
- Pytest.

Keep components modular and easy to integrate with the existing PHIL platform.

Do not introduce unnecessary frameworks, services or dependencies.

## 7. Testing

Write focused tests for:

**Handshake**
- Valid Agent Card.
- Invalid Agent Card.
- Protocol incompatibility.
- Capability mismatch.
- Handshake timeout.
- Successful and failed handshake.

**State management**
- Valid transitions.
- Invalid transitions.
- Completion.
- Failure.
- Cancellation.
- Approval-related transition.

**Completion**
- Valid completion.
- Failure event.
- Duplicate completion.
- Invalid task reference.
- Idempotent processing.

Use mocks where external services are not available.

## 8. Documentation

Document:

- Architecture and component responsibilities.
- A2A handshake flow.
- Registry and certification integration assumptions.
- User authorization context.
- Agent discovery and routing context.
- Task lifecycle and state mapping.
- Completion and failure contracts.
- Error handling and timeout behaviour.
- Integration examples and execution commands.
- Future considerations, clearly separated from current implementation.

Documentation may explain broader PHIL architecture, but do not implement additional functionality simply because it appears in the documentation.

## 9. Development workflow

Follow these stages:

**Stage 1 – Design**
- Present architecture.
- Define handshake contract.
- Define task state transition matrix.
- Define completion/failure schemas.
- Identify A2A SDK and integration requirements.
- Wait for approval.

**Stage 2 – Handshake**
- Implement A2A integration and validation.
- Write tests.

**Stage 3 – State management**
- Implement task models and state machine.
- Write tests.

**Stage 4 – Completion**
- Implement completion/failure processing.
- Write tests.

**Stage 5 – Handover**
- Provide documentation, examples and test results.

## 10. Strict exclusions

Do not implement:

- Artifact Registry.
- Certification service.
- User authentication/authorization.
- Agent routing engine.
- Full Supervisor Agent.
- Domain-agent business logic.
- LangGraph orchestration.
- MCP integration.
- New messaging infrastructure.
- Production database infrastructure.
- Additional governance services.

Do not add work beyond the three assigned Sprint 3 areas.

**First action: Complete Stage 1 design only. Do not write code until the design is reviewed and approved.**