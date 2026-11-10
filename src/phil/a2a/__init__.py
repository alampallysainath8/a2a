"""A2A Handshake and Protocol Validation module."""

from phil.a2a.client import A2AHandshakeClient
from phil.a2a.exceptions import (
    AgentCardMalformedError,
    AgentIdentityError,
    CapabilityMismatchError,
    HandshakeConnectionError,
    HandshakeError,
    HandshakeTimeoutError,
    ProtocolVersionIncompatibleError,
)
from phil.a2a.models import (
    AgentCapabilities,
    AgentCard,
    AgentSkill,
    HandshakeRequirements,
    HandshakeResult,
    HandshakeSession,
    HandshakeStatus,
    ProtocolBinding,
)

__all__ = [
    "A2AHandshakeClient",
    "AgentCard",
    "AgentSkill",
    "AgentCapabilities",
    "ProtocolBinding",
    "HandshakeRequirements",
    "HandshakeSession",
    "HandshakeResult",
    "HandshakeStatus",
    "HandshakeError",
    "HandshakeConnectionError",
    "HandshakeTimeoutError",
    "AgentCardMalformedError",
    "AgentIdentityError",
    "ProtocolVersionIncompatibleError",
    "CapabilityMismatchError",
]

