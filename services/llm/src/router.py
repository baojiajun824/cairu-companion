"""LLM routing with fallback to static responses."""

from typing import Any

from src.backends.base import LLMBackend
from cairu_common.logging import get_logger

logger = get_logger()


# Fallback responses for when Ollama fails
FALLBACK_RESPONSES = [
    "I'm here with you.",
    "I'm listening.",
    "Tell me more about that.",
    "I understand.",
    "That sounds important.",
]


class LLMRouter:
    """
    Routes LLM requests to Ollama with static fallback.

    Simplified for Alpha: Single backend (Ollama), static fallback if it fails.
    """

    def __init__(
        self,
        backends: dict[str, LLMBackend],
        primary: str = "ollama",
    ):
        self.backends = backends
        self.primary = primary
        self._fallback_index = 0

    async def generate(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 150,
        temperature: float = 0.7,
    ) -> dict[str, Any]:
        """
        Generate a response using Ollama.

        Returns:
            Dict with text, model, backend, and fallback info
        """
        # Try Ollama
        if self.primary in self.backends:
            try:
                result = await self.backends[self.primary].generate(
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
                result["is_fallback"] = False
                return result
            except Exception as e:
                logger.error("ollama_failed", error=str(e))

        # Ollama failed - use static fallback
        logger.warning("using_static_fallback")
        return self._get_static_fallback()

    def _get_static_fallback(self) -> dict[str, Any]:
        """Get a static fallback response when Ollama fails."""
        response = FALLBACK_RESPONSES[self._fallback_index]
        self._fallback_index = (self._fallback_index + 1) % len(FALLBACK_RESPONSES)

        return {
            "text": response,
            "model": "static_fallback",
            "backend": "fallback",
            "tokens_used": 0,
            "is_fallback": True,
            "fallback_reason": "ollama_failed",
        }

    async def close(self) -> None:
        """Close all backends."""
        for backend in self.backends.values():
            await backend.close()
