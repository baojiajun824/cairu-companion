"""
cAIru LLM Service

Handles language model inference using Ollama (local).
Consumes from llm:requests and publishes to llm:responses.

Simplified for Alpha: Local Ollama only, no event extraction.
Supports sentence-level streaming to TTS for lower latency.
"""

import asyncio
import signal
from datetime import datetime

from cairu_common.config import get_llm_settings
from cairu_common.logging import setup_logging, get_logger
from cairu_common.redis_client import RedisStreamClient
from cairu_common.models import LLMResponse, TTSRequest, Intent
from cairu_common.metrics import LLM_LATENCY, LLM_TOKENS_USED, LLM_FALLBACK_COUNT, set_service_info, set_component_health

from src.backends.ollama import OllamaBackend
from src.router import LLMRouter

settings = get_llm_settings()
logger = get_logger()


class LLMService:
    """LLM inference service."""

    def __init__(self):
        self.redis: RedisStreamClient | None = None
        self.router: LLMRouter | None = None
        self._running = False

    async def start(self):
        """Initialize and start the LLM service."""
        setup_logging(
            service_name="llm",
            log_level=settings.log_level,
            json_format=not settings.is_development,
        )
        set_service_info(name="llm", version="0.1.0", environment=settings.environment)

        logger.info(
            "llm_service_starting",
            backend=settings.llm_backend,
            model=settings.llm_model,
        )

        # Initialize Ollama backend
        backends = {}
        ollama = OllamaBackend(
            base_url=settings.ollama_url,
            model=settings.llm_model,
        )
        
        if await ollama.health_check():
            backends["ollama"] = ollama
            set_component_health("ollama", True)
            logger.info("ollama_connected", url=settings.ollama_url)
        else:
            set_component_health("ollama", False)
            logger.error("ollama_unavailable", url=settings.ollama_url)
            raise RuntimeError("Ollama is not available - cannot start LLM service")

        # Initialize router
        self.router = LLMRouter(backends, primary="ollama")

        # Connect to Redis
        self.redis = RedisStreamClient(str(settings.redis_url))
        await self.redis.connect()
        set_component_health("redis", True)

        self._running = True
        logger.info("llm_service_started")

        # Start processing loop
        await self._process_requests()

    async def stop(self):
        """Gracefully stop the service."""
        logger.info("llm_service_stopping")
        self._running = False
        if self.redis:
            await self.redis.disconnect()
        if self.router:
            await self.router.close()
        logger.info("llm_service_stopped")

    async def _process_requests(self):
        """Main processing loop - consume LLM requests."""
        if not self.redis or not self.router:
            raise RuntimeError("Service not initialized")

        async for message_id, data in self.redis.consume(
            RedisStreamClient.STREAMS["llm_requests"],
            consumer_group="llm",
            consumer_name="llm-main",
        ):
            if not self._running:
                break

            try:
                await self._handle_request(data)
            except Exception as e:
                logger.error("llm_processing_error", message_id=message_id, error=str(e))

    async def _handle_request(self, data: dict):
        """Handle an LLM request with sentence-level streaming to TTS."""
        start_time = datetime.utcnow()

        request_id = data.get("request_id", "unknown")
        device_id = data.get("device_id", "unknown")
        session_id = data.get("session_id", "unknown")
        user_message = data.get("user_message", "")
        system_prompt = data.get("system_prompt", "")
        conversation_history = data.get("conversation_history", [])
        max_tokens = data.get("max_tokens", 150)
        temperature = data.get("temperature", 0.7)

        logger.info(
            "processing_llm_request",
            request_id=request_id,
            message_preview=user_message[:50],
        )

        # Build messages for LLM
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.extend(conversation_history)
        messages.append({"role": "user", "content": user_message})

        # Get Ollama backend for streaming
        ollama_backend = self.router.backends.get("ollama")
        
        if ollama_backend is None:
            # Fallback to non-streaming
            result = await self.router.generate(
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            full_text = result.get("text", "I'm here for you.")
            tokens_used = result.get("tokens_used", 0)
            is_fallback = result.get("is_fallback", False)
            
            # Send single TTS request
            tts_request = TTSRequest(
                request_id=request_id,
                device_id=device_id,
                session_id=session_id,
                text=full_text,
            )
            await self.redis.publish(
                RedisStreamClient.STREAMS["tts_requests"],
                tts_request,
            )
        else:
            # Stream sentences - send each to TTS immediately
            full_text_parts = []
            tokens_used = 0
            is_fallback = False
            sentence_idx = 0
            
            async for chunk in ollama_backend.generate_streaming(
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
            ):
                sentence = chunk.get("sentence", "")
                is_final = chunk.get("is_final", False)
                
                if sentence:
                    full_text_parts.append(sentence)
                    
                    # Send sentence to TTS immediately
                    tts_request = TTSRequest(
                        request_id=f"{request_id}-{sentence_idx}",
                        device_id=device_id,
                        session_id=session_id,
                        text=sentence,
                    )
                    await self.redis.publish(
                        RedisStreamClient.STREAMS["tts_requests"],
                        tts_request,
                    )
                    logger.info("sentence_to_tts", idx=sentence_idx, text=sentence[:40])
                    sentence_idx += 1
                
                if is_final:
                    tokens_used = chunk.get("tokens_used", 0)
                    break
            
            full_text = " ".join(full_text_parts) if full_text_parts else "I'm here for you."

        # Calculate latency
        latency_ms = (datetime.utcnow() - start_time).total_seconds() * 1000

        # Record metrics
        LLM_LATENCY.labels(
            model=settings.llm_model,
            backend="ollama",
        ).observe(latency_ms)

        if tokens_used:
            LLM_TOKENS_USED.labels(
                model=settings.llm_model,
                type="completion",
            ).inc(tokens_used)

        if is_fallback:
            LLM_FALLBACK_COUNT.labels(reason="ollama_failed").inc()

        logger.info(
            "llm_complete",
            request_id=request_id,
            latency_ms=round(latency_ms, 2),
            sentences=len(full_text_parts) if 'full_text_parts' in dir() else 1,
        )

        # Publish full response for orchestrator (history tracking)
        response = LLMResponse(
            request_id=request_id,
            device_id=device_id,
            session_id=session_id,
            text=full_text,
            detected_intent=Intent.UNKNOWN,
            detected_events=[],
            model=settings.llm_model,
            latency_ms=int(latency_ms),
            tokens_used=tokens_used,
            is_fallback=is_fallback,
        )

        await self.redis.publish(
            RedisStreamClient.STREAMS["llm_responses"],
            response,
        )


async def main():
    """Entry point."""
    service = LLMService()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(service.stop()))

    await service.start()


if __name__ == "__main__":
    asyncio.run(main())
