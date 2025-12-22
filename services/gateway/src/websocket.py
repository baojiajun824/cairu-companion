"""
WebSocket connection management for the Companion device.

Simplified for Alpha: Single device, no multi-device tracking.
"""

import asyncio
import base64
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from fastapi import WebSocket

from cairu_common.logging import get_logger

logger = get_logger()


@dataclass
class DeviceSession:
    """Represents the active Companion device session."""

    device_id: str
    websocket: WebSocket
    session_id: str
    connected_at: datetime = field(default_factory=datetime.utcnow)
    last_activity: datetime = field(default_factory=datetime.utcnow)
    message_count: int = 0


class ConnectionManager:
    """
    Manages the WebSocket connection from the Companion device.

    Simplified for Alpha: Single device only.
    """

    def __init__(self):
        self._session: DeviceSession | None = None
        self._lock = asyncio.Lock()

    def is_connected(self) -> bool:
        """Check if a device is currently connected."""
        return self._session is not None

    async def connect(self, device_id: str, websocket: WebSocket) -> DeviceSession:
        """
        Accept a new WebSocket connection.

        Args:
            device_id: Device identifier
            websocket: FastAPI WebSocket instance

        Returns:
            DeviceSession for the connected device
        """
        await websocket.accept()

        # Generate session ID
        session_id = f"{device_id}-{datetime.utcnow().timestamp()}"

        session = DeviceSession(
            device_id=device_id,
            websocket=websocket,
            session_id=session_id,
        )

        async with self._lock:
            # Close existing connection if any
            if self._session is not None:
                try:
                    await self._session.websocket.close()
                except Exception:
                    pass
                logger.warning("replaced_existing_connection")

            self._session = session

        logger.info(
            "connection_established",
            device_id=device_id,
            session_id=session_id,
        )

        return session

    def disconnect(self, device_id: str) -> None:
        """Remove the device connection."""
        if self._session and self._session.device_id == device_id:
            self._session = None
            logger.info("connection_removed", device_id=device_id)

    async def disconnect_all(self) -> None:
        """Close the active connection (used during shutdown)."""
        async with self._lock:
            if self._session:
                try:
                    await self._session.websocket.close()
                except Exception:
                    pass
                self._session = None

        logger.info("connection_closed")

    async def send_response(
        self,
        message: dict[str, Any],
        audio_data: bytes | None = None,
    ) -> bool:
        """
        Send a message to the Companion device.

        Args:
            message: JSON-serializable message data
            audio_data: Optional audio bytes to include

        Returns:
            True if sent successfully, False otherwise
        """
        if not self._session:
            logger.warning("no_device_connected")
            return False

        try:
            # Include audio as base64 if provided
            if audio_data:
                message["audio"] = base64.b64encode(audio_data).decode("utf-8")

            await self._session.websocket.send_json(message)
            self._session.last_activity = datetime.utcnow()
            self._session.message_count += 1

            logger.debug(
                "message_sent",
                has_audio=audio_data is not None,
            )
            return True

        except Exception as e:
            logger.error("send_failed", error=str(e))
            return False

    def get_session(self) -> DeviceSession | None:
        """Get the current session."""
        return self._session

    def get_session_id(self) -> str | None:
        """Get current session ID if connected."""
        return self._session.session_id if self._session else None
