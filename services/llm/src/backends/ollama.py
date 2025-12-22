"""Ollama backend for local LLM inference."""

from typing import Any

import httpx

from src.backends.base import LLMBackend
from cairu_common.logging import get_logger

logger = get_logger()


class OllamaBackend(LLMBackend):
    """
    Ollama backend for local LLM inference.

    Ollama provides easy model management and a simple API for running
    LLMs locally on CPU or GPU.
    """

    def __init__(self, base_url: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._client: httpx.AsyncClient | None = None

    @property
    def name(self) -> str:
        return "ollama"

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=60.0,  # LLM inference can be slow
            )
        return self._client

    async def generate(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 150,
        temperature: float = 0.7,
    ) -> dict[str, Any]:
        """Generate response using Ollama chat API."""
        client = await self._get_client()

        try:
            response = await client.post(
                "/api/chat",
                json={
                    "model": self.model,
                    "messages": messages,
                    "stream": False,
                    "options": {
                        "num_predict": max_tokens,
                        "temperature": temperature,
                    },
                },
            )
            response.raise_for_status()
            data = response.json()

            return {
                "text": data.get("message", {}).get("content", ""),
                "model": self.model,
                "backend": self.name,
                "tokens_used": data.get("eval_count", 0),
            }

        except httpx.HTTPError as e:
            logger.error("ollama_request_failed", error=str(e))
            raise

    async def health_check(self) -> bool:
        """Check if Ollama is available and model is loaded."""
        try:
            client = await self._get_client()
            response = await client.get("/api/tags")
            response.raise_for_status()

            # Check if our model is available
            data = response.json()
            models = [m.get("name", "") for m in data.get("models", [])]

            if self.model in models or any(self.model in m for m in models):
                return True

            # Try to pull the model if not available
            logger.info("pulling_ollama_model", model=self.model)
            pull_response = await client.post(
                "/api/pull",
                json={"name": self.model},
                timeout=300.0,  # Model download can take a while
            )
            return pull_response.status_code == 200

        except Exception as e:
            logger.warning("ollama_health_check_failed", error=str(e))
            return False

    async def close(self) -> None:
        """Close HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

