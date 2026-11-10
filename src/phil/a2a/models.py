"""Data models for A2A protocol, Agent Card parsing, and Handshake negotiation."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


class ProtocolBinding(BaseModel):
    """Specification of an interface binding supported by an A2A agent."""
    protocol: str = Field(default="http", description="Protocol type, e.g. 'http', 'json-rpc', 'grpc'")
    url: str = Field(description="Endpoint URL for this protocol binding")


class AgentSkill(BaseModel):
    """Specific skill or intent supported by an A2A domain agent."""
    id: str = Field(description="Unique skill/intent identifier")
    name: str = Field(description="Human readable name of the skill")
    description: str = Field(default="", description="Detailed description of skill capability")
    input_modes: List[str] = Field(
        default_factory=lambda: ["text/plain"],
        description="Supported MIME types for task inputs"
    )
    output_modes: List[str] = Field(
        default_factory=lambda: ["text/plain"],
        description="Supported MIME types for task outputs"
    )
    tags: List[str] = Field(default_factory=list, description="Categorization tags")
    examples: List[str] = Field(default_factory=list, description="Example prompt/invocation patterns")


class AgentCapabilities(BaseModel):
    """Protocol capabilities supported by the agent."""
    streaming: bool = Field(default=False, description="Whether agent supports streaming responses")
    push_notifications: bool = Field(default=False, description="Whether agent supports async push callbacks")
    state_recovery: bool = Field(default=False, description="Whether agent supports state recovery")


class AgentCard(BaseModel):
    """Machine-readable metadata manifest for an A2A domain agent."""
    name: str = Field(description="Agent name")
    description: str = Field(default="", description="Agent description")
    version: str = Field(default="1.0.0", description="Agent implementation version")
    protocol_version: str = Field(default="1.0.0", description="A2A protocol specification version")
    agent_id: Optional[str] = Field(default=None, description="Optional distinct agent identifier")
    skills: List[AgentSkill] = Field(default_factory=list, description="List of supported skills/intents")
    capabilities: AgentCapabilities = Field(default_factory=AgentCapabilities, description="Agent capabilities")
    supported_interfaces: List[ProtocolBinding] = Field(
        default_factory=list,
        description="Endpoints where the agent accepts tasks"
    )
    certification_id: Optional[str] = Field(default=None, description="PHIL governance certification reference")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Arbitrary additional metadata")

    @field_validator("name")
    @classmethod
    def validate_name_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Agent name cannot be empty")
        return v.strip()


class HandshakeRequirements(BaseModel):
    """Requirements specified by Supervisor to validate a candidate Domain Agent."""
    required_intent: str = Field(description="Required skill/intent identifier")
    min_protocol_version: str = Field(default="1.0.0", description="Minimum supported A2A protocol version")
    max_protocol_version: str = Field(default="1.99.99", description="Maximum supported A2A protocol version")
    required_input_mode: str = Field(default="text/plain", description="Required input MIME type")
    required_output_mode: str = Field(default="text/plain", description="Required output MIME type")
    require_streaming: bool = Field(default=False, description="Whether streaming capability is strictly required")
    timeout_seconds: float = Field(default=5.0, description="Network timeout in seconds for handshake operations")


class HandshakeStatus(str, Enum):
    """Outcome status of a handshake negotiation."""
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class HandshakeSession(BaseModel):
    """Active validated session established between Supervisor and Domain Agent."""
    session_id: str = Field(default_factory=lambda: str(uuid4()))
    agent_id: str
    agent_url: str
    agent_card: AgentCard
    matched_skill: AgentSkill
    validated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime

    def is_expired(self, current_time: Optional[datetime] = None) -> bool:
        now = current_time or datetime.now(timezone.utc)
        return now >= self.expires_at


class HandshakeResult(BaseModel):
    """Result object returned from an A2A handshake attempt."""
    status: HandshakeStatus
    session: Optional[HandshakeSession] = None
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    card: Optional[AgentCard] = None

