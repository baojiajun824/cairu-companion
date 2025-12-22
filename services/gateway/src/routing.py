"""
Audio routing between Companion device and the processing pipeline.

Simplified for Alpha: Single device, streamlined routing.
"""

import asyncio
import base64
from datetime import datetime
from typing import Any

from cairu_common.redis_client import RedisStreamClient
from cairu_common.models import AudioSegment
from cairu_common.logging import get_logger
from cairu_common.metrics import AUDIO_SEGMENTS_RECEIVED, record_pipeline_latency

from src.websocket import ConnectionManager

logger = get_logger()


class AudioRouter:
    """
    Routes audio between Companion device and the processing pipeline.

    Responsibilities:
    - Publish incoming audio to the VAD service via Redis Streams
    - Listen for outgoing responses and route to the device
    - Track pipeline latency for observability
    """

    def __init__(self, redis_client: RedisStreamClient):
        self.redis = redis_client
        self._pending_requests: dict[str, datetime] = {}  # session_id -> start_time

    async def route_audio(
        self,
        device_id: str,
        audio_data: bytes,
        is_final: bool = False,
    ) -> str:
        """
        Route incoming audio from Companion device to the processing pipeline.

        Args:
            device_id: Source device ID
            audio_data: Raw audio bytes (expected: 16kHz, 16-bit PCM)
            is_final: Whether this is the final segment of an utterance

        Returns:
            Message ID from Redis
        """
        # Use consistent session ID for tracking
        session_id = f"{device_id}-session"

        segment = AudioSegment(
            device_id=device_id,
            session_id=session_id,
            audio_data=audio_data,
            duration_ms=len(audio_data) // 32,  # Rough estimate: 16kHz * 2 bytes = 32 bytes/ms
            is_final=is_final,
        )

        # Track when we started processing
        self._pending_requests[segment.session_id] = datetime.utcnow()

        # Publish to VAD service
        message_id = await self.redis.publish(
            RedisStreamClient.STREAMS["audio_inbound"],
            segment,
        )

        AUDIO_SEGMENTS_RECEIVED.labels(device_id=device_id).inc()

        logger.debug(
            "audio_routed",
            device_id=device_id,
            duration_ms=segment.duration_ms,
            message_id=message_id,
        )

        return message_id

    async def listen_for_responses(self, connection_manager: ConnectionManager) -> None:
        """
        Listen for processed responses and route them to the Companion device.

        This runs as a background task, consuming from the audio:outbound stream.
        """
        logger.info("response_listener_started")

        async for message_id, data in self.redis.consume(
            RedisStreamClient.STREAMS["audio_outbound"],
            consumer_group="gateway",
            consumer_name="gateway-main",
        ):
            try:
                await self._handle_response(data, connection_manager)
            except Exception as e:
                logger.error(
                    "response_handling_error",
                    message_id=message_id,
                    error=str(e),
                )

    async def _handle_response(
        self,
        data: dict[str, Any],
        connection_manager: ConnectionManager,
    ) -> None:
        """Handle a response from the pipeline and send to Companion device."""
        session_id = data.get("session_id")
        device_id = data.get("device_id")

        # Calculate pipeline latency
        if session_id and session_id in self._pending_requests:
            start_time = self._pending_requests.pop(session_id)
            latency_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
            record_pipeline_latency(device_id or "unknown", latency_ms)
            logger.info(
                "pipeline_complete",
                session_id=session_id,
                latency_ms=round(latency_ms, 2),
            )

        # Decode audio if present (stored as base64 in Redis)
        audio_data = None
        if "audio_data" in data:
            audio_b64 = data.pop("audio_data")
            if isinstance(audio_b64, str):
                audio_data = base64.b64decode(audio_b64)
            elif isinstance(audio_b64, bytes):
                audio_data = audio_b64

        # Build response message for Companion
        response_message = {
            "type": "response",
            "session_id": session_id,
            "text": data.get("text", ""),
            "ui_hints": data.get("ui_hints", {}),
            "timestamp": datetime.utcnow().isoformat(),
        }

        # Send to device
        success = await connection_manager.send_response(
            response_message,
            audio_data=audio_data,
        )

        if success:
            logger.debug(
                "response_sent",
                text_length=len(response_message.get("text", "")),
                has_audio=audio_data is not None,
            )
        else:
            logger.warning("response_send_failed", reason="device_not_connected")
