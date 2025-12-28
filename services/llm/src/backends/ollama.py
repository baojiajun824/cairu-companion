"""Ollama backend for local LLM inference."""

import json
import re
import time
from typing import Any, AsyncIterator

import httpx

from src.backends.base import LLMBackend
from cairu_common.logging import get_logger

logger = get_logger()

# Sentence boundary pattern - matches sentence ending punctuation followed by space or end
SENTENCE_SPLIT = re.compile(r'([.!?])\s+')


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
                timeout=httpx.Timeout(60.0, connect=10.0),
            )
        return self._client

    async def generate(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 150,
        temperature: float = 0.7,
    ) -> dict[str, Any]:
        """Generate response using Ollama chat API with streaming."""
        client = await self._get_client()
        
        start_time = time.time()
        first_token_time = None
        full_text = []
        tokens_used = 0

        try:
            async with client.stream(
                "POST",
                "/api/chat",
                json={
                    "model": self.model,
                    "messages": messages,
                    "stream": True,
                    "options": {
                        "num_predict": max_tokens,
                        "temperature": temperature,
                    },
                },
            ) as response:
                response.raise_for_status()
                
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    
                    # Track time to first token
                    if first_token_time is None:
                        first_token_time = time.time()
                        ttft_ms = (first_token_time - start_time) * 1000
                        logger.info("llm_first_token", ttft_ms=round(ttft_ms, 2))
                    
                    # Extract content from chunk
                    content = chunk.get("message", {}).get("content", "")
                    if content:
                        full_text.append(content)
                    
                    # Check if done
                    if chunk.get("done", False):
                        tokens_used = chunk.get("eval_count", 0)
                        break

            return {
                "text": "".join(full_text),
                "model": self.model,
                "backend": self.name,
                "tokens_used": tokens_used,
            }

        except httpx.HTTPError as e:
            logger.error("ollama_request_failed", error=str(e))
            raise

    async def generate_streaming(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 150,
        temperature: float = 0.7,
    ) -> AsyncIterator[dict[str, Any]]:
        """
        Generate response with sentence-level streaming.
        
        Yields sentences as they complete, enabling faster TTS processing.
        Each yield contains: {"sentence": str, "is_final": bool, "tokens_used": int}
        """
        client = await self._get_client()
        
        start_time = time.time()
        first_token_time = None
        buffer = ""
        tokens_used = 0

        try:
            async with client.stream(
                "POST",
                "/api/chat",
                json={
                    "model": self.model,
                    "messages": messages,
                    "stream": True,
                    "options": {
                        "num_predict": max_tokens,
                        "temperature": temperature,
                    },
                },
            ) as response:
                response.raise_for_status()
                
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    
                    # Track time to first token
                    if first_token_time is None:
                        first_token_time = time.time()
                        ttft_ms = (first_token_time - start_time) * 1000
                        logger.info("llm_first_token", ttft_ms=round(ttft_ms, 2))
                    
                    # Extract content from chunk
                    content = chunk.get("message", {}).get("content", "")
                    if content:
                        buffer += content
                        
                        # Check for complete sentences in buffer
                        # Split on sentence-ending punctuation followed by space
                        parts = SENTENCE_SPLIT.split(buffer)
                        
                        # parts will be like: ["Hello", ".", " How are you", "?", " I'm fine"]
                        # We need to reconstruct sentences
                        if len(parts) > 1:
                            sentences = []
                            i = 0
                            while i < len(parts) - 1:
                                if parts[i+1] in '.!?':
                                    sentences.append(parts[i] + parts[i+1])
                                    i += 2
                                else:
                                    i += 1
                            
                            # Keep incomplete part in buffer
                            buffer = parts[-1] if len(parts) % 2 == 1 else ""
                            
                            for sentence in sentences:
                                sentence = sentence.strip()
                                if sentence:
                                    logger.info("llm_sentence_complete", sentence=sentence[:50])
                                    yield {
                                        "sentence": sentence,
                                        "is_final": False,
                                        "tokens_used": 0,
                                    }
                    
                    # Check if done
                    if chunk.get("done", False):
                        tokens_used = chunk.get("eval_count", 0)
                        break
            
            # Yield any remaining content
            if buffer.strip():
                logger.info("llm_final_fragment", fragment=buffer.strip()[:50])
                yield {
                    "sentence": buffer.strip(),
                    "is_final": True,
                    "tokens_used": tokens_used,
                }
            else:
                # Send empty final marker
                yield {
                    "sentence": "",
                    "is_final": True,
                    "tokens_used": tokens_used,
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

