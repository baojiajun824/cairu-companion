"""
cAIru VAD Service

Listens for audio segments and detects voice activity using Silero VAD.
Only forwards audio with detected speech to the ASR service.
"""

import asyncio
import signal
from datetime import datetime

from cairu_common.config import get_settings
from cairu_common.logging import setup_logging, get_logger
from cairu_common.redis_client import RedisStreamClient
from cairu_common.models import AudioSegment, VADResult
from cairu_common.metrics import VAD_LATENCY, set_service_info, set_component_health

from src.detector import SileroVAD

settings = get_settings()
logger = get_logger()


class VADService:
    """Voice Activity Detection service."""

    def __init__(self):
        self.redis: RedisStreamClient | None = None
        self.vad: SileroVAD | None = None
        self._running = False

    async def start(self):
        """Initialize and start the VAD service."""
        setup_logging(
            service_name="vad",
            log_level=settings.log_level,
            json_format=not settings.is_development,
        )
        set_service_info(name="vad", version="0.1.0", environment=settings.environment)

        logger.info("vad_service_starting")

        # Initialize VAD model
        self.vad = SileroVAD()
        await self.vad.load_model()
        set_component_health("vad_model", True)

        # Connect to Redis
        self.redis = RedisStreamClient(str(settings.redis_url))
        await self.redis.connect()
        set_component_health("redis", True)

        self._running = True
        logger.info("vad_service_started")

        # Start processing loop
        await self._process_audio_stream()

    async def stop(self):
        """Gracefully stop the service."""
        logger.info("vad_service_stopping")
        self._running = False
        if self.redis:
            await self.redis.disconnect()
        logger.info("vad_service_stopped")

    async def _process_audio_stream(self):
        """Main processing loop - consume audio and detect speech."""
        if not self.redis or not self.vad:
            raise RuntimeError("Service not initialized")

        async for message_id, data in self.redis.consume(
            RedisStreamClient.STREAMS["audio_inbound"],
            consumer_group="vad",
            consumer_name="vad-main",
        ):
            if not self._running:
                break

            try:
                await self._process_segment(data)
            except Exception as e:
                logger.error("vad_processing_error", message_id=message_id, error=str(e))

    async def _process_segment(self, data: dict):
        """Process a single audio segment."""
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

        # Run VAD
        has_speech, probability = await self.vad.detect(audio_data)

        # Record latency
        latency_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
        VAD_LATENCY.observe(latency_ms)

        logger.debug(
            "vad_result",
            device_id=device_id,
            has_speech=has_speech,
            probability=round(probability, 3),
            latency_ms=round(latency_ms, 2),
        )

        # Only forward if speech detected
        if has_speech:
            result = VADResult(
                device_id=device_id,
                session_id=session_id,
                has_speech=True,
                speech_probability=probability,
                audio_data=audio_data,
                duration_ms=len(audio_data) // 32,
            )

            await self.redis.publish(
                RedisStreamClient.STREAMS["audio_segments"],
                result,
            )

            logger.debug("speech_forwarded_to_asr", device_id=device_id)


async def main():
    """Entry point."""
    service = VADService()

    # Handle shutdown signals
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(service.stop()))

    await service.start()


if __name__ == "__main__":
    asyncio.run(main())

