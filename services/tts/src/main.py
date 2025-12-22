"""
cAIru TTS Service

Synthesizes speech from text using Piper TTS.
Consumes from tts:requests and publishes to audio:outbound.
"""

import asyncio
import base64
import signal
from datetime import datetime

from cairu_common.config import get_tts_settings
from cairu_common.logging import setup_logging, get_logger
from cairu_common.redis_client import RedisStreamClient
from cairu_common.metrics import TTS_LATENCY, set_service_info, set_component_health

from src.synthesizer import PiperSynthesizer

settings = get_tts_settings()
logger = get_logger()


class TTSService:
    """Text-to-Speech service."""

    def __init__(self):
        self.redis: RedisStreamClient | None = None
        self.synthesizer: PiperSynthesizer | None = None
        self._running = False

    async def start(self):
        """Initialize and start the TTS service."""
        setup_logging(
            service_name="tts",
            log_level=settings.log_level,
            json_format=not settings.is_development,
        )
        set_service_info(name="tts", version="0.1.0", environment=settings.environment)

        logger.info("tts_service_starting", voice=settings.piper_voice)

        # Initialize synthesizer
        self.synthesizer = PiperSynthesizer(
            voice=settings.piper_voice,
            model_path=settings.piper_model_path,
        )
        await self.synthesizer.load_model()
        set_component_health("piper_model", True)

        # Connect to Redis
        self.redis = RedisStreamClient(str(settings.redis_url))
        await self.redis.connect()
        set_component_health("redis", True)

        self._running = True
        logger.info("tts_service_started")

        # Start processing loop
        await self._process_requests()

    async def stop(self):
        """Gracefully stop the service."""
        logger.info("tts_service_stopping")
        self._running = False
        if self.redis:
            await self.redis.disconnect()
        logger.info("tts_service_stopped")

    async def _process_requests(self):
        """Main processing loop - consume TTS requests."""
        if not self.redis or not self.synthesizer:
            raise RuntimeError("Service not initialized")

        async for message_id, data in self.redis.consume(
            RedisStreamClient.STREAMS["tts_requests"],
            consumer_group="tts",
            consumer_name="tts-main",
        ):
            if not self._running:
                break

            try:
                await self._handle_request(data)
            except Exception as e:
                logger.error("tts_processing_error", message_id=message_id, error=str(e))

    async def _handle_request(self, data: dict):
        """Handle a TTS request and synthesize speech."""
        start_time = datetime.utcnow()

        request_id = data.get("request_id", "unknown")
        device_id = data.get("device_id", "unknown")
        session_id = data.get("session_id", "unknown")
        text = data.get("text", "")

        if not text.strip():
            logger.warning("empty_tts_request", request_id=request_id)
            return

        logger.info(
            "synthesizing_speech",
            request_id=request_id,
            text_length=len(text),
        )

        # Synthesize speech
        audio_data, duration_ms = await self.synthesizer.synthesize(text)

        # Calculate latency
        latency_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        TTS_LATENCY.observe(latency_ms)

        logger.info(
            "speech_synthesized",
            request_id=request_id,
            audio_duration_ms=duration_ms,
            latency_ms=round(latency_ms, 2),
        )

        # Publish to outbound stream
        # Encode audio as base64 for Redis transport
        await self.redis.publish(
            RedisStreamClient.STREAMS["audio_outbound"],
            {
                "request_id": request_id,
                "device_id": device_id,
                "session_id": session_id,
                "audio_data": base64.b64encode(audio_data).decode("utf-8"),
                "duration_ms": duration_ms,
                "latency_ms": int(latency_ms),
                "text": text,
                "ui_hints": {
                    "show_text": True,
                    "mood": "neutral",
                },
            },
        )


async def main():
    """Entry point."""
    service = TTSService()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(service.stop()))

    await service.start()


if __name__ == "__main__":
    asyncio.run(main())

