"""Supervisor-side A2A Handshake client and validation engine."""

from datetime import datetime, timedelta, timezone
import logging
from typing import Any, Dict, Optional, Tuple
from uuid import uuid4

import httpx
from packaging.version import InvalidVersion, Version

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
    AgentCard,
    AgentSkill,
    HandshakeRequirements,
    HandshakeResult,
    HandshakeSession,
    HandshakeStatus,
)

logger = logging.getLogger("phil.a2a")


class A2AHandshakeClient:
    """Supervisor client for establishing and caching A2A handshake sessions with Domain Agents."""

    def __init__(
        self,
        default_cache_ttl_seconds: int = 300,
        transport: Optional[httpx.BaseTransport] = None,
    ) -> None:
        self.default_cache_ttl_seconds = default_cache_ttl_seconds
        self._transport = transport
        # Key: (normalized_agent_url, intent_id) -> HandshakeSession
        self._session_cache: Dict[Tuple[str, str], HandshakeSession] = {}

    def _normalize_endpoint(self, agent_url: str) -> str:
        """Ensure endpoint URL resolves to the agent card standard location."""
        url = agent_url.strip().rstrip("/")
        if not url.endswith("agent-card.json"):
            if not url.endswith("/.well-known"):
                url = f"{url}/.well-known/agent-card.json"
            else:
                url = f"{url}/agent-card.json"
        return url

    def _get_cache_key(self, agent_url: str, intent: str) -> Tuple[str, str]:
        return (agent_url.strip().rstrip("/"), intent.strip())

    def get_cached_session(
        self, agent_url: str, intent: str, current_time: Optional[datetime] = None
    ) -> Optional[HandshakeSession]:
        """Retrieve a non-expired cached handshake session if available."""
        key = self._get_cache_key(agent_url, intent)
        session = self._session_cache.get(key)
        if session:
            if session.is_expired(current_time):
                logger.info(
                    "[A2A-CACHE-EXPIRED] Handshake session %s for agent '%s' (intent: '%s') has expired.",
                    session.session_id, agent_url, intent
                )
                del self._session_cache[key]
                return None
            logger.info(
                "[A2A-CACHE-HIT] Reusing active cached handshake session %s for '%s' (intent: '%s').",
                session.session_id, agent_url, intent
            )
            return session
        logger.debug("[A2A-CACHE-MISS] No cached session for '%s' (intent: '%s').", agent_url, intent)
        return None

    def invalidate_cache(self, agent_url: Optional[str] = None) -> None:
        """Clear cached sessions completely or for a specific agent URL."""
        if agent_url is None:
            count = len(self._session_cache)
            self._session_cache.clear()
            logger.info("[A2A-CACHE-INVALIDATED] Cleared all %d cached sessions.", count)
        else:
            normalized = agent_url.strip().rstrip("/")
            keys_to_remove = [k for k in self._session_cache if k[0] == normalized]
            for k in keys_to_remove:
                del self._session_cache[k]
            logger.info(
                "[A2A-CACHE-INVALIDATED] Cleared %d cached sessions for '%s'.",
                len(keys_to_remove), agent_url
            )

    def fetch_agent_card(
        self, agent_url: str, timeout_seconds: float = 5.0
    ) -> AgentCard:
        """Fetch and parse Agent Card from domain agent endpoint."""
        endpoint = self._normalize_endpoint(agent_url)
        logger.info("[A2A-FETCH] Querying Agent Card from '%s' (timeout=%.1fs)", endpoint, timeout_seconds)

        try:
            with httpx.Client(
                transport=self._transport,
                timeout=httpx.Timeout(timeout_seconds),
                follow_redirects=True,
            ) as client:
                response = client.get(endpoint)

            if response.status_code != 200:
                logger.warning("[A2A-FETCH-FAIL] HTTP %d returned from '%s'", response.status_code, endpoint)
                raise HandshakeConnectionError(
                    f"Domain agent returned HTTP {response.status_code} for card at {endpoint}"
                )

            try:
                card_data = response.json()
            except Exception as e:
                logger.error("[A2A-PARSE-ERROR] Response from '%s' is not valid JSON: %s", endpoint, str(e))
                raise AgentCardMalformedError(
                    f"Agent Card payload is not valid JSON: {str(e)}"
                ) from e

            try:
                card = AgentCard.model_validate(card_data)
                logger.info("[A2A-PARSED] Successfully parsed Agent Card: '%s' (version: %s)", card.name, card.version)
                return card
            except Exception as e:
                logger.error("[A2A-SCHEMA-ERROR] Schema validation failed for card at '%s': %s", endpoint, str(e))
                raise AgentCardMalformedError(
                    f"Agent Card failed schema validation: {str(e)}"
                ) from e

        except httpx.TimeoutException as e:
            logger.error("[A2A-TIMEOUT] Handshake timed out after %.1fs for '%s'", timeout_seconds, endpoint)
            raise HandshakeTimeoutError(
                f"Handshake timed out after {timeout_seconds}s connecting to {endpoint}"
            ) from e
        except (httpx.ConnectError, httpx.NetworkError) as e:
            logger.error("[A2A-CONNECT-FAIL] Network connection failed to '%s': %s", endpoint, str(e))
            raise HandshakeConnectionError(
                f"Failed to establish network connection to {endpoint}: {str(e)}"
            ) from e
        except HandshakeError:
            raise
        except Exception as e:
            logger.error("[A2A-UNEXPECTED-ERROR] Unexpected error connecting to '%s': %s", endpoint, str(e))
            raise HandshakeConnectionError(
                f"Unexpected connection error querying {endpoint}: {str(e)}"
            ) from e

    def validate_agent_card(
        self, card: AgentCard, requirements: HandshakeRequirements
    ) -> AgentSkill:
        """Validate an Agent Card against Supervisor requirements."""
        logger.debug("[A2A-VALIDATE] Validating Agent Card '%s' against requirements...", card.name)

        # 1. Identity Validation
        if not card.name or not card.name.strip():
            logger.warning("[A2A-IDENTITY-FAIL] Agent Card name is empty.")
            raise AgentIdentityError("Agent identity validation failed: agent name is empty.")

        # 2. Protocol Version Compatibility Validation
        try:
            agent_ver = Version(card.protocol_version)
            min_ver = Version(requirements.min_protocol_version)
            max_ver = Version(requirements.max_protocol_version)
        except InvalidVersion as e:
            logger.warning("[A2A-VERSION-FAIL] Invalid A2A version format '%s': %s", card.protocol_version, str(e))
            raise ProtocolVersionIncompatibleError(
                f"Invalid A2A protocol semantic version '{card.protocol_version}': {str(e)}"
            ) from e

        if agent_ver < min_ver or agent_ver > max_ver:
            logger.warning(
                "[A2A-VERSION-FAIL] Protocol version %s incompatible. Required: [%s, %s]",
                card.protocol_version, requirements.min_protocol_version, requirements.max_protocol_version
            )
            raise ProtocolVersionIncompatibleError(
                f"A2A protocol version {card.protocol_version} is incompatible with required "
                f"range [{requirements.min_protocol_version}, {requirements.max_protocol_version}]"
            )

        # 3. Intent & Skill Validation
        matched_skill: Optional[AgentSkill] = None
        for skill in card.skills:
            if skill.id == requirements.required_intent:
                matched_skill = skill
                break

        if not matched_skill:
            available = [s.id for s in card.skills]
            logger.warning(
                "[A2A-SKILL-FAIL] Intent '%s' not found in agent skills: %s",
                requirements.required_intent, available
            )
            raise CapabilityMismatchError(
                f"Agent '{card.name}' does not support required intent '{requirements.required_intent}'. "
                f"Available skills: {available}"
            )

        # 4. Input & Output Mode Validation
        if requirements.required_input_mode not in matched_skill.input_modes:
            logger.warning(
                "[A2A-IOMODE-FAIL] Input mode '%s' unsupported by skill '%s'. Supported: %s",
                requirements.required_input_mode, matched_skill.id, matched_skill.input_modes
            )
            raise CapabilityMismatchError(
                f"Agent skill '{matched_skill.id}' does not support required input mode "
                f"'{requirements.required_input_mode}'. Supported: {matched_skill.input_modes}"
            )

        if requirements.required_output_mode not in matched_skill.output_modes:
            logger.warning(
                "[A2A-IOMODE-FAIL] Output mode '%s' unsupported by skill '%s'. Supported: %s",
                requirements.required_output_mode, matched_skill.id, matched_skill.output_modes
            )
            raise CapabilityMismatchError(
                f"Agent skill '{matched_skill.id}' does not support required output mode "
                f"'{requirements.required_output_mode}'. Supported: {matched_skill.output_modes}"
            )

        # 5. Capabilities Check
        if requirements.require_streaming and not card.capabilities.streaming:
            logger.warning("[A2A-STREAMING-FAIL] Agent '%s' lacks required streaming capability.", card.name)
            raise CapabilityMismatchError(
                f"Agent '{card.name}' does not support required streaming capability."
            )

        logger.info(
            "[A2A-VALIDATED] Card validated successfully: agent='%s', skill='%s', proto_ver=%s",
            card.name, matched_skill.id, card.protocol_version
        )
        return matched_skill

    def initiate_handshake(
        self,
        agent_url: str,
        requirements: HandshakeRequirements,
        bypass_cache: bool = False,
        raise_on_error: bool = False,
    ) -> HandshakeResult:
        """Execute the full handshake flow, with session caching and error isolation."""
        # 1. Check cache to avoid repeating handshake unnecessarily
        if not bypass_cache:
            cached = self.get_cached_session(agent_url, requirements.required_intent)
            if cached:
                return HandshakeResult(
                    status=HandshakeStatus.SUCCESS,
                    session=cached,
                    card=cached.agent_card,
                )

        try:
            # 2. Fetch Card
            card = self.fetch_agent_card(
                agent_url=agent_url,
                timeout_seconds=requirements.timeout_seconds,
            )

            # 3. Validate Card
            matched_skill = self.validate_agent_card(card, requirements)

            # 4. Construct Session & Cache
            agent_id = card.agent_id or card.name
            now = datetime.now(timezone.utc)
            session = HandshakeSession(
                session_id=str(uuid4()),
                agent_id=agent_id,
                agent_url=agent_url,
                agent_card=card,
                matched_skill=matched_skill,
                validated_at=now,
                expires_at=now + timedelta(seconds=self.default_cache_ttl_seconds),
            )

            cache_key = self._get_cache_key(agent_url, requirements.required_intent)
            self._session_cache[cache_key] = session
            logger.info(
                "[A2A-HANDSHAKE-SUCCESS] Session created: id=%s for agent='%s' (TTL=%ds)",
                session.session_id, agent_id, self.default_cache_ttl_seconds
            )

            return HandshakeResult(
                status=HandshakeStatus.SUCCESS,
                session=session,
                card=card,
            )

        except HandshakeError as e:
            logger.warning("[A2A-HANDSHAKE-FAILED] %s: %s", e.__class__.__name__, str(e))
            if raise_on_error:
                raise
            return HandshakeResult(
                status=HandshakeStatus.FAILED,
                error_type=e.__class__.__name__,
                error_message=str(e),
                card=getattr(e, "card", None),
            )
        except Exception as e:
            logger.error("[A2A-HANDSHAKE-ERROR] Unexpected error during handshake: %s", str(e), exc_info=True)
            if raise_on_error:
                raise HandshakeError(f"Unexpected handshake failure: {str(e)}") from e
            return HandshakeResult(
                status=HandshakeStatus.FAILED,
                error_type=e.__class__.__name__,
                error_message=str(e),
            )
