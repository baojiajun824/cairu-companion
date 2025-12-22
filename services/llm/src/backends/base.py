"""Base class for LLM backends."""

from abc import ABC, abstractmethod
from typing import Any


class LLMBackend(ABC):
    """Abstract base class for LLM backends."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Backend name identifier."""
        pass

    @abstractmethod
    async def generate(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 150,
        temperature: float = 0.7,
    ) -> dict[str, Any]:
        """
        Generate a response from the LLM.

        Args:
            messages: List of conversation messages
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature

        Returns:
            Dict with 'text', 'model', 'tokens_used'
        """
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if the backend is available."""
        pass

    async def close(self) -> None:
        """Clean up resources."""
        pass

