"""
cAIru ASR Service

Transcribes audio segments using Faster-Whisper.
Consumes from audio:segments and publishes to text:transcripts.
"""

import asyncio
import signal
from datetime import datetime

from cairu_common.config import get_asr_settings
from cairu_common.logging import setup_logging, get_logger
from cairu_common.redis_client import RedisStreamClient
from cairu_common.models import Transcript
from cairu_common.metrics import ASR_LATENCY, ASR_CONFIDENCE, set_service_info, set_component_health

from src.transcriber import WhisperTranscriber

settings = get_asr_settings()
logger = get_logger()


class ASRService:
    """Automatic Speech Recognition service."""

    def __init__(self):
        self.redis: RedisStreamClient | None = None
        self.transcriber: WhisperTranscriber | None = None
        self._running = False

    async def start(self):
        """Initialize and start the ASR service."""
        setup_logging(
            service_name="asr",
            log_level=settings.log_level,
            json_format=not settings.is_development,
        )
        set_service_info(name="asr", version="0.1.0", environment=settings.environment)

        logger.info("asr_service_starting", model=settings.whisper_model)

        # Initialize Whisper model
        self.transcriber = WhisperTranscriber(
            model_size=settings.whisper_model,
            device=settings.whisper_device,
        )
        await self.transcriber.load_model()
        set_component_health("whisper_model", True)

        # Connect to Redis
        self.redis = RedisStreamClient(str(settings.redis_url))
        await self.redis.connect()
        set_component_health("redis", True)

        self._running = True
        logger.info("asr_service_started")

        # Start processing loop
        await self._process_audio_stream()

    async def stop(self):
        """Gracefully stop the service."""
        logger.info("asr_service_stopping")
        self._running = False
        if self.redis:
            await self.redis.disconnect()
        logger.info("asr_service_stopped")

    async def _process_audio_stream(self):
        """Main processing loop - consume audio and transcribe."""
        if not self.redis or not self.transcriber:
            raise RuntimeError("Service not initialized")

        async for message_id, data in self.redis.consume(
            RedisStreamClient.STREAMS["audio_segments"],
            consumer_group="asr",
            consumer_name="asr-main",
        ):
            if not self._running:
                break

            try:
                await self._transcribe_segment(data)
            except Exception as e:
                logger.error("asr_processing_error", message_id=message_id, error=str(e))

    async def _transcribe_segment(self, data: dict):
        """Transcribe a single audio segment."""
        start_time = datetime.utcnow()

        device_id = data.get("device_id", "unknown")
        session_id = data.get("session_id", "unknown")
        audio_data = data.get("audio_data")

        if not audio_data:
            logger.warning("empty_audio_segment", device_id=device_id)
            return

        # Convert from base64 if needed
        if isinstance(audio_data, str):
            import base64
            audio_data = base64.b64decode(audio_data)

        # Transcribe
        text, confidence = await self.transcriber.transcribe(audio_data)

        # Calculate latency
        latency_ms = (datetime.utcnow() - start_time).total_seconds() * 1000

        # Record metrics
        ASR_LATENCY.observe(latency_ms)
        ASR_CONFIDENCE.observe(confidence)

        logger.info(
            "transcription_complete",
            device_id=device_id,
            text=text[:50] + "..." if len(text) > 50 else text,
            confidence=round(confidence, 3),
            latency_ms=round(latency_ms, 2),
        )

        # Skip empty transcriptions
        if not text.strip():
            logger.debug("empty_transcription", device_id=device_id)
            return

        # Publish transcript
        transcript = Transcript(
            device_id=device_id,
            session_id=session_id,
            text=text,
            confidence=confidence,
            duration_ms=int(latency_ms),
        )

        await self.redis.publish(
            RedisStreamClient.STREAMS["transcripts"],
            transcript,
        )


async def main():
    """Entry point."""
    service = ASRService()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(service.stop()))

    await service.start()


if __name__ == "__main__":
    asyncio.run(main())

