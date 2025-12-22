"""
cAIru Common Library

Shared utilities, models, and configuration for all cAIru services.
Simplified for Alpha: Single device, single user.
"""

from cairu_common.config import Settings, get_settings
from cairu_common.logging import setup_logging, get_logger
from cairu_common.models import (
    AudioSegment,
    Transcript,
    LLMRequest,
    LLMResponse,
    TTSRequest,
    TTSResponse,
    ConversationTurn,
    UserProfile,
)
from cairu_common.redis_client import RedisStreamClient

__version__ = "0.1.0"

__all__ = [
    # Config
    "Settings",
    "get_settings",
    # Logging
    "setup_logging",
    "get_logger",
    # Models
    "AudioSegment",
    "Transcript",
    "LLMRequest",
    "LLMResponse",
    "TTSRequest",
    "TTSResponse",
    "ConversationTurn",
    "UserProfile",
    # Redis
    "RedisStreamClient",
]
