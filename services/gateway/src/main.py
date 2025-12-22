"""
cAIru Gateway Service

Entry point for the Companion device. Handles WebSocket audio streaming
and routes messages to/from the processing pipeline via Redis Streams.

Simplified for Alpha: Single device, no authentication.
"""

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

from cairu_common.config import get_gateway_settings
from cairu_common.logging import setup_logging, get_logger
from cairu_common.redis_client import RedisStreamClient
from cairu_common.metrics import (
    ACTIVE_SESSIONS,
    set_service_info,
    set_component_health,
)

from src.websocket import ConnectionManager
from src.routing import AudioRouter

settings = get_gateway_settings()
logger = get_logger()

# Single device ID for Alpha
DEFAULT_DEVICE_ID = "companion-001"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan manager."""
    # Startup
    setup_logging(
        service_name=settings.service_name,
        log_level=settings.log_level,
        json_format=not settings.is_development,
    )
    set_service_info(
        name=settings.service_name,
        version="0.1.0",
        environment=settings.environment,
    )

    logger.info("gateway_starting", host=settings.gateway_host, port=settings.gateway_port)

    # Initialize Redis client
    redis_client = RedisStreamClient(str(settings.redis_url))
    await redis_client.connect()
    set_component_health("redis", True)

    # Initialize managers
    app.state.redis = redis_client
    app.state.connection_manager = ConnectionManager()
    app.state.audio_router = AudioRouter(redis_client)

    # Start response listener
    response_task = asyncio.create_task(
        app.state.audio_router.listen_for_responses(app.state.connection_manager)
    )

    logger.info("gateway_started")

    yield

    # Shutdown
    logger.info("gateway_stopping")
    response_task.cancel()
    try:
        await response_task
    except asyncio.CancelledError:
        pass

    await app.state.connection_manager.disconnect_all()
    await redis_client.disconnect()
    logger.info("gateway_stopped")


app = FastAPI(
    title="cAIru Gateway",
    description="WebSocket gateway for Companion device",
    version="0.1.0",
    lifespan=lifespan,
)


# =============================================================================
# Health & Metrics Endpoints
# =============================================================================


@app.get("/health")
async def health_check() -> JSONResponse:
    """Health check endpoint."""
    redis_healthy = await app.state.redis.health_check()
    manager: ConnectionManager = app.state.connection_manager
    
    return JSONResponse(
        status_code=200 if redis_healthy else 503,
        content={
            "status": "healthy" if redis_healthy else "degraded",
            "service": "gateway",
            "redis": "connected" if redis_healthy else "disconnected",
            "device_connected": manager.is_connected(),
        },
    )


@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint."""
    return JSONResponse(
        content=generate_latest().decode("utf-8"),
        media_type=CONTENT_TYPE_LATEST,
    )


# =============================================================================
# WebSocket Endpoint (Single Device)
# =============================================================================


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for the Companion device.
    
    Simplified for Alpha: No device_id in URL, single device assumed.

    Protocol:
    - Client sends binary audio frames
    - Server sends JSON messages with audio (base64) and metadata
    """
    manager: ConnectionManager = app.state.connection_manager
    router: AudioRouter = app.state.audio_router

    # Use default device ID for Alpha
    device_id = DEFAULT_DEVICE_ID

    await manager.connect(device_id, websocket)
    ACTIVE_SESSIONS.set(1)

    logger.info("companion_connected", device_id=device_id)

    try:
        while True:
            # Receive audio data from Companion
            data = await websocket.receive_bytes()

            # Route to processing pipeline
            await router.route_audio(device_id, data)

    except WebSocketDisconnect:
        logger.info("companion_disconnected", device_id=device_id)
    except Exception as e:
        logger.error("websocket_error", device_id=device_id, error=str(e))
    finally:
        manager.disconnect(device_id)
        ACTIVE_SESSIONS.set(0)


# =============================================================================
# REST API (for testing/debugging)
# =============================================================================


@app.get("/")
async def root():
    """Root endpoint."""
    manager: ConnectionManager = app.state.connection_manager
    return {
        "service": "cAIru Gateway",
        "version": "0.1.0",
        "status": "running",
        "device_connected": manager.is_connected(),
    }
