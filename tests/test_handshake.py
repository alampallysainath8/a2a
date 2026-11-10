"""Tests for A2A Handshake, Agent Card validation, and session negotiation."""

from datetime import datetime, timedelta, timezone
import pytest
import httpx

from phil.a2a.client import A2AHandshakeClient
from phil.a2a.exceptions import (
    AgentCardMalformedError,
    AgentIdentityError,
    CapabilityMismatchError,
    HandshakeConnectionError,
    HandshakeTimeoutError,
    ProtocolVersionIncompatibleError,
)
from phil.a2a.models import (
    AgentCard,
    HandshakeRequirements,
    HandshakeStatus,
)


@pytest.fixture
def sample_valid_card_data():
    return {
        "name": "Finance Analysis Domain Agent",
        "description": "Performs financial ledger audit and analysis",
        "version": "1.2.0",
        "protocol_version": "1.0.0",
        "agent_id": "agent-finance-001",
        "skills": [
            {
                "id": "financial_audit",
                "name": "Financial Audit",
                "description": "Audits ledger entries for compliance",
                "input_modes": ["text/plain", "application/json"],
                "output_modes": ["text/plain", "application/json"],
                "tags": ["finance", "audit"],
                "examples": ["Audit Q3 2026 expense report"],
            }
        ],
        "capabilities": {
            "streaming": True,
            "push_notifications": False,
            "state_recovery": True,
        },
        "supported_interfaces": [
            {"protocol": "http", "url": "https://agents.internal/finance/tasks"}
        ],
        "certification_id": "PHIL-CERT-2026-9921",
    }


@pytest.fixture
def default_requirements():
    return HandshakeRequirements(
        required_intent="financial_audit",
        min_protocol_version="1.0.0",
        max_protocol_version="1.99.99",
        required_input_mode="text/plain",
        required_output_mode="text/plain",
        timeout_seconds=2.0,
    )


# ---------------------------------------------------------------------------
# Test 1: Valid Agent Card Retrieval & Successful Handshake
# ---------------------------------------------------------------------------

def test_successful_handshake_with_valid_agent_card(sample_valid_card_data, default_requirements):
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://agents.internal/finance/.well-known/agent-card.json"
        return httpx.Response(200, json=sample_valid_card_data)

    transport = httpx.MockTransport(handler)
    client = A2AHandshakeClient(transport=transport)

    result = client.initiate_handshake(
        agent_url="https://agents.internal/finance",
        requirements=default_requirements,
    )

    assert result.status == HandshakeStatus.SUCCESS
    assert result.session is not None
    assert result.session.agent_id == "agent-finance-001"
    assert result.session.matched_skill.id == "financial_audit"
    assert result.card.name == "Finance Analysis Domain Agent"
    assert not result.session.is_expired()


# ---------------------------------------------------------------------------
# Test 2: Invalid / Malformed Agent Card (Non-JSON and Schema Mismatches)
# ---------------------------------------------------------------------------

def test_handshake_fails_on_malformed_json(default_requirements):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="NOT_VALID_JSON{:::<xml>")

    client = A2AHandshakeClient(transport=httpx.MockTransport(handler))

    # Test safe result return
    result = client.initiate_handshake(
        agent_url="https://agents.internal/bad",
        requirements=default_requirements,
        raise_on_error=False,
    )
    assert result.status == HandshakeStatus.FAILED
    assert result.error_type == "AgentCardMalformedError"

    # Test raise_on_error=True
    with pytest.raises(AgentCardMalformedError, match="not valid JSON"):
        client.initiate_handshake(
            agent_url="https://agents.internal/bad",
            requirements=default_requirements,
            raise_on_error=True,
        )


def test_handshake_fails_on_schema_validation_error(default_requirements):
    bad_payload = {"name": "Incomplete Agent", "skills": "NOT_A_LIST"}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=bad_payload)

    client = A2AHandshakeClient(transport=httpx.MockTransport(handler))

    with pytest.raises(AgentCardMalformedError, match="schema validation"):
        client.initiate_handshake(
            agent_url="https://agents.internal/bad",
            requirements=default_requirements,
            raise_on_error=True,
        )


# ---------------------------------------------------------------------------
# Test 3: Agent Identity Validation
# ---------------------------------------------------------------------------

def test_agent_identity_empty_name_fails():
    with pytest.raises(ValueError, match="Agent name cannot be empty"):
        AgentCard(name="   ", skills=[])


# ---------------------------------------------------------------------------
# Test 4: Protocol Version Incompatibility
# ---------------------------------------------------------------------------

def test_protocol_version_incompatible_upper_bound(sample_valid_card_data, default_requirements):
    sample_valid_card_data["protocol_version"] = "2.0.0"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=sample_valid_card_data)

    client = A2AHandshakeClient(transport=httpx.MockTransport(handler))

    with pytest.raises(ProtocolVersionIncompatibleError, match="is incompatible with required range"):
        client.initiate_handshake(
            agent_url="https://agents.internal/finance",
            requirements=default_requirements,
            raise_on_error=True,
        )


def test_protocol_version_incompatible_lower_bound(sample_valid_card_data, default_requirements):
    sample_valid_card_data["protocol_version"] = "0.9.0"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=sample_valid_card_data)

    client = A2AHandshakeClient(transport=httpx.MockTransport(handler))

    with pytest.raises(ProtocolVersionIncompatibleError, match="is incompatible with required range"):
        client.initiate_handshake(
            agent_url="https://agents.internal/finance",
            requirements=default_requirements,
            raise_on_error=True,
        )


def test_protocol_version_invalid_format(sample_valid_card_data, default_requirements):
    sample_valid_card_data["protocol_version"] = "v-invalid-format"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=sample_valid_card_data)

    client = A2AHandshakeClient(transport=httpx.MockTransport(handler))

    with pytest.raises(ProtocolVersionIncompatibleError, match="Invalid A2A protocol semantic version"):
        client.initiate_handshake(
            agent_url="https://agents.internal/finance",
            requirements=default_requirements,
            raise_on_error=True,
        )


# ---------------------------------------------------------------------------
# Test 5: Capability & Intent Mismatch
# ---------------------------------------------------------------------------

def test_capability_mismatch_missing_intent(sample_valid_card_data):
    req = HandshakeRequirements(required_intent="non_existent_skill")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=sample_valid_card_data)

    client = A2AHandshakeClient(transport=httpx.MockTransport(handler))

    with pytest.raises(CapabilityMismatchError, match="does not support required intent 'non_existent_skill'"):
        client.initiate_handshake(
            agent_url="https://agents.internal/finance",
            requirements=req,
            raise_on_error=True,
        )


def test_capability_mismatch_unsupported_input_mode(sample_valid_card_data):
    req = HandshakeRequirements(
        required_intent="financial_audit",
        required_input_mode="application/pdf",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=sample_valid_card_data)

    client = A2AHandshakeClient(transport=httpx.MockTransport(handler))

    with pytest.raises(CapabilityMismatchError, match="does not support required input mode 'application/pdf'"):
        client.initiate_handshake(
            agent_url="https://agents.internal/finance",
            requirements=req,
            raise_on_error=True,
        )


def test_capability_mismatch_unsupported_output_mode(sample_valid_card_data):
    req = HandshakeRequirements(
        required_intent="financial_audit",
        required_output_mode="image/png",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=sample_valid_card_data)

    client = A2AHandshakeClient(transport=httpx.MockTransport(handler))

    with pytest.raises(CapabilityMismatchError, match="does not support required output mode 'image/png'"):
        client.initiate_handshake(
            agent_url="https://agents.internal/finance",
            requirements=req,
            raise_on_error=True,
        )


def test_capability_mismatch_streaming_required_but_unsupported(sample_valid_card_data):
    sample_valid_card_data["capabilities"]["streaming"] = False
    req = HandshakeRequirements(
        required_intent="financial_audit",
        require_streaming=True,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=sample_valid_card_data)

    client = A2AHandshakeClient(transport=httpx.MockTransport(handler))

    with pytest.raises(CapabilityMismatchError, match="does not support required streaming capability"):
        client.initiate_handshake(
            agent_url="https://agents.internal/finance",
            requirements=req,
            raise_on_error=True,
        )


# ---------------------------------------------------------------------------
# Test 6: Communication Timeout & Network Failures
# ---------------------------------------------------------------------------

def test_handshake_timeout_handling(default_requirements):
    def timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("Timed out reading data")

    client = A2AHandshakeClient(transport=httpx.MockTransport(timeout_handler))

    with pytest.raises(HandshakeTimeoutError, match="timed out"):
        client.initiate_handshake(
            agent_url="https://agents.internal/slow",
            requirements=default_requirements,
            raise_on_error=True,
        )


def test_handshake_connection_error(default_requirements):
    def connection_error_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused by peer")

    client = A2AHandshakeClient(transport=httpx.MockTransport(connection_error_handler))

    with pytest.raises(HandshakeConnectionError, match="Failed to establish network connection"):
        client.initiate_handshake(
            agent_url="https://agents.internal/down",
            requirements=default_requirements,
            raise_on_error=True,
        )


def test_handshake_http_error_status(default_requirements):
    def error_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="Service Unavailable")

    client = A2AHandshakeClient(transport=httpx.MockTransport(error_handler))

    with pytest.raises(HandshakeConnectionError, match="HTTP 503"):
        client.initiate_handshake(
            agent_url="https://agents.internal/unavailable",
            requirements=default_requirements,
            raise_on_error=True,
        )


# ---------------------------------------------------------------------------
# Test 7: Handshake Session Caching & Expiration
# ---------------------------------------------------------------------------

def test_handshake_session_caching_avoids_repeated_requests(sample_valid_card_data, default_requirements):
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, json=sample_valid_card_data)

    client = A2AHandshakeClient(default_cache_ttl_seconds=300, transport=httpx.MockTransport(handler))

    # First call: hits the endpoint
    result1 = client.initiate_handshake("https://agents.internal/finance", default_requirements)
    assert result1.status == HandshakeStatus.SUCCESS
    assert call_count == 1
    session_id_1 = result1.session.session_id

    # Second call for the same agent & intent: must hit the cache, not the endpoint
    result2 = client.initiate_handshake("https://agents.internal/finance", default_requirements)
    assert result2.status == HandshakeStatus.SUCCESS
    assert call_count == 1  # No second HTTP call made!
    assert result2.session.session_id == session_id_1

    # Bypassing cache forces re-handshake
    result3 = client.initiate_handshake(
        "https://agents.internal/finance", default_requirements, bypass_cache=True
    )
    assert result3.status == HandshakeStatus.SUCCESS
    assert call_count == 2
    assert result3.session.session_id != session_id_1


def test_handshake_session_cache_ttl_expiration(sample_valid_card_data, default_requirements):
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, json=sample_valid_card_data)

    client = A2AHandshakeClient(default_cache_ttl_seconds=10, transport=httpx.MockTransport(handler))

    # Initial handshake
    result = client.initiate_handshake("https://agents.internal/finance", default_requirements)
    assert call_count == 1

    # Simulate time advance past TTL
    future_time = datetime.now(timezone.utc) + timedelta(seconds=15)
    cached = client.get_cached_session("https://agents.internal/finance", "financial_audit", current_time=future_time)
    assert cached is None  # Cache expired

    # Subsequent handshake re-queries endpoint
    result.session.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    result_after_expiry = client.initiate_handshake("https://agents.internal/finance", default_requirements)
    assert call_count == 2
    assert result_after_expiry.status == HandshakeStatus.SUCCESS


def test_handshake_cache_invalidation(sample_valid_card_data, default_requirements):
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, json=sample_valid_card_data)

    client = A2AHandshakeClient(transport=httpx.MockTransport(handler))

    client.initiate_handshake("https://agents.internal/finance", default_requirements)
    assert call_count == 1

    # Invalidate specific agent
    client.invalidate_cache("https://agents.internal/finance")
    client.initiate_handshake("https://agents.internal/finance", default_requirements)
    assert call_count == 2

    # Invalidate all
    client.invalidate_cache()
    client.initiate_handshake("https://agents.internal/finance", default_requirements)
    assert call_count == 3
