"""Exceptions for the A2A Handshake and Protocol Validation."""

class HandshakeError(Exception):
    """Base exception for all A2A handshake and negotiation failures."""
    pass


class HandshakeConnectionError(HandshakeError):
    """Raised when establishing a connection to the domain agent fails."""
    pass


class HandshakeTimeoutError(HandshakeError):
    """Raised when communication with the domain agent times out."""
    pass


class AgentCardMalformedError(HandshakeError):
    """Raised when the Agent Card cannot be parsed or fails schema validation."""
    pass


class AgentIdentityError(HandshakeError):
    """Raised when agent identity is missing, malformed, or unauthorized."""
    pass


class ProtocolVersionIncompatibleError(HandshakeError):
    """Raised when domain agent protocol version is incompatible with supervisor."""
    pass


class CapabilityMismatchError(HandshakeError):
    """Raised when domain agent does not support the requested intent or capabilities."""
    pass

