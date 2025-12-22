"""
Shared Pydantic models for inter-service communication.

These models define the contract between services via Redis Streams.
Simplified for Alpha: Single device, single user.
"""

import base64
from datetime import datetime
from enum import Enum
from typing import Annotated, Any

from pydantic import BaseModel, Field, PlainSerializer, BeforeValidator


def _encode_bytes(v: bytes) -> str:
    """Encode bytes to base64 string for JSON serialization."""
    return base64.b64encode(v).decode("utf-8")


def _decode_bytes(v: Any) -> bytes:
    """Decode base64 string or pass through bytes."""
    if isinstance(v, bytes):
        return v
    if isinstance(v, str):
        return base64.b64decode(v)
    raise ValueError(f"Cannot decode bytes from {type(v)}")


# Custom type for bytes that serializes as base64
Base64Bytes = Annotated[
    bytes,
    BeforeValidator(_decode_bytes),
    PlainSerializer(_encode_bytes, return_type=str, when_used="json"),
]


# =============================================================================
# Enums
# =============================================================================


class Intent(str, Enum):
    """Detected intents from user speech."""

    GREETING = "greeting"
    FAREWELL = "farewell"
    QUESTION = "question"
    REQUEST = "request"
    ACKNOWLEDGMENT = "acknowledgment"
    UNKNOWN = "unknown"


# =============================================================================
# Audio Models
# =============================================================================


class AudioSegment(BaseModel):
    """Audio segment from Companion device."""

    device_id: str = Field(default="companion-001", description="Device identifier")
    session_id: str = Field(..., description="Current conversation session ID")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    audio_data: Base64Bytes = Field(..., description="Raw audio bytes (16kHz, 16-bit PCM)")
    duration_ms: int = Field(..., description="Duration of audio segment in milliseconds")
    is_final: bool = Field(default=False, description="Whether this is the final segment")


class VADResult(BaseModel):
    """Result from Voice Activity Detection."""

    device_id: str = Field(default="companion-001")
    session_id: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    has_speech: bool
    speech_probability: float = Field(ge=0.0, le=1.0)
    audio_data: Base64Bytes | None = Field(default=None, description="Audio if speech detected")
    duration_ms: int = 0


# =============================================================================
# Transcription Models
# =============================================================================


class Transcript(BaseModel):
    """Transcription result from ASR."""

    device_id: str = Field(default="companion-001")
    session_id: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    text: str = Field(..., description="Transcribed text")
    confidence: float = Field(ge=0.0, le=1.0, description="Transcription confidence")
    language: str = Field(default="en")
    duration_ms: int = Field(..., description="Processing time in milliseconds")
    is_partial: bool = Field(default=False, description="Whether this is a partial result")


# =============================================================================
# LLM Models
# =============================================================================


class LLMRequest(BaseModel):
    """Request to the LLM service."""

    request_id: str = Field(..., description="Unique request identifier")
    device_id: str = Field(default="companion-001")
    session_id: str
    user_id: str = Field(default="user-001")
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    # Context
    user_message: str = Field(..., description="The user's transcribed message")
    conversation_history: list[dict[str, str]] = Field(
        default_factory=list,
        description="Recent conversation turns [{'role': 'user'|'assistant', 'content': ...}]",
    )
    user_profile: dict[str, Any] = Field(
        default_factory=dict,
        description="User profile and preferences",
    )
    care_plan_context: dict[str, Any] = Field(
        default_factory=dict,
        description="Relevant care plan information",
    )
    system_prompt: str = Field(
        default="",
        description="System prompt with persona and instructions",
    )

    # Generation parameters
    max_tokens: int = Field(default=150, description="Maximum response tokens")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)


class LLMResponse(BaseModel):
    """Response from the LLM service."""

    request_id: str
    device_id: str = Field(default="companion-001")
    session_id: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    # Response content
    text: str = Field(..., description="Generated response text")
    detected_intent: Intent = Field(default=Intent.UNKNOWN)
    detected_events: list[dict[str, Any]] = Field(default_factory=list)

    # Metadata
    model: str = Field(..., description="Model used for generation")
    latency_ms: int = Field(..., description="Generation time in milliseconds")
    tokens_used: int = Field(default=0)
    is_fallback: bool = Field(default=False)


# =============================================================================
# TTS Models
# =============================================================================


class TTSRequest(BaseModel):
    """Request to the TTS service."""

    request_id: str
    device_id: str = Field(default="companion-001")
    session_id: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    text: str = Field(..., description="Text to synthesize")
    voice_id: str | None = Field(default=None, description="Voice to use (optional)")
    speed: float = Field(default=1.0, ge=0.5, le=2.0, description="Speech speed")


class TTSResponse(BaseModel):
    """Response from the TTS service."""

    request_id: str
    device_id: str = Field(default="companion-001")
    session_id: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    audio_data: Base64Bytes = Field(..., description="Synthesized audio (WAV format)")
    duration_ms: int = Field(..., description="Audio duration in milliseconds")
    latency_ms: int = Field(..., description="Synthesis time in milliseconds")
    text: str = Field(..., description="Original text for display")

    # UI hints for Companion display
    ui_hints: dict[str, Any] = Field(
        default_factory=dict,
        description="Hints for Companion UI",
    )


# =============================================================================
# Conversation Models
# =============================================================================


class ConversationTurn(BaseModel):
    """A single turn in a conversation."""

    turn_id: str
    session_id: str
    user_id: str = Field(default="user-001")
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    role: str = Field(..., description="'user' or 'assistant'")
    content: str
    intent: Intent | None = None

    # Timing
    asr_latency_ms: int | None = None
    llm_latency_ms: int | None = None
    tts_latency_ms: int | None = None
    total_latency_ms: int | None = None


# =============================================================================
# User Profile Models
# =============================================================================


class UserProfile(BaseModel):
    """User profile for personalization."""

    user_id: str = Field(default="user-001")
    device_id: str = Field(default="companion-001")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    # Basic info
    name: str = Field(default="Friend")
    preferred_name: str | None = None
    timezone: str = "America/Los_Angeles"

    # Personalization
    life_details: dict[str, Any] = Field(
        default_factory=dict,
        description="Personal details for conversation (family, hobbies, etc.)",
    )
    preferences: dict[str, Any] = Field(
        default_factory=dict,
        description="Interaction preferences",
    )
