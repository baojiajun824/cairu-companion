"""
Redis Streams client wrapper for inter-service communication.

Provides a clean API for publishing and consuming messages via Redis Streams.
"""

import asyncio
import json
from datetime import datetime
from typing import Any, AsyncIterator, Callable

import redis.asyncio as redis
from pydantic import BaseModel

from cairu_common.logging import get_logger

logger = get_logger()


class RedisStreamClient:
    """
    Client for Redis Streams pub/sub messaging.

    Usage:
        client = RedisStreamClient("redis://localhost:6379")
        await client.connect()

        # Publish
        await client.publish("audio:segments", {"device_id": "abc", "data": "..."})

        # Consume
        async for message in client.consume("audio:segments", "asr-service"):
            process(message)
    """

    # Stream names used in the pipeline
    STREAMS = {
        "audio_inbound": "cairu:audio:inbound",
        "audio_segments": "cairu:audio:segments",
        "transcripts": "cairu:text:transcripts",
        "llm_requests": "cairu:llm:requests",
        "llm_responses": "cairu:llm:responses",
        "tts_requests": "cairu:tts:requests",
        "audio_outbound": "cairu:audio:outbound",
        "events": "cairu:events:caregiver",
    }

    def __init__(self, redis_url: str):
        self.redis_url = redis_url
        self._redis: redis.Redis | None = None
        self._consumer_tasks: list[asyncio.Task] = []

    async def connect(self) -> None:
        """Establish connection to Redis."""
        self._redis = redis.from_url(
            self.redis_url,
            encoding="utf-8",
            decode_responses=False,  # We handle encoding ourselves
        )
        # Test connection
        await self._redis.ping()
        logger.info("redis_connected", url=self.redis_url)

    async def disconnect(self) -> None:
        """Close Redis connection."""
        # Cancel any running consumer tasks
        for task in self._consumer_tasks:
            task.cancel()
        self._consumer_tasks.clear()

        if self._redis:
            await self._redis.close()
            self._redis = None
            logger.info("redis_disconnected")

    async def publish(
        self,
        stream: str,
        message: dict[str, Any] | BaseModel,
        maxlen: int = 10000,
    ) -> str:
        """
        Publish a message to a Redis Stream.

        Args:
            stream: Stream name (use STREAMS constants)
            message: Message to publish (dict or Pydantic model)
            maxlen: Maximum stream length (older messages trimmed)

        Returns:
            Message ID assigned by Redis
        """
        if self._redis is None:
            raise RuntimeError("Not connected to Redis")

        # Convert Pydantic model to dict
        if isinstance(message, BaseModel):
            data = message.model_dump(mode="json")
        else:
            data = message

        # Serialize to JSON bytes
        payload = {"data": json.dumps(data, default=str)}

        message_id = await self._redis.xadd(
            stream,
            payload,
            maxlen=maxlen,
            approximate=True,
        )

        logger.debug(
            "message_published",
            stream=stream,
            message_id=message_id,
        )

        return message_id.decode() if isinstance(message_id, bytes) else message_id

    async def consume(
        self,
        stream: str,
        consumer_group: str,
        consumer_name: str | None = None,
        batch_size: int = 1,
        block_ms: int = 1000,
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        """
        Consume messages from a Redis Stream using consumer groups.

        Args:
            stream: Stream name to consume from
            consumer_group: Consumer group name
            consumer_name: Unique consumer identifier (defaults to random)
            batch_size: Number of messages to read at once
            block_ms: How long to block waiting for messages

        Yields:
            Tuple of (message_id, message_data)
        """
        if self._redis is None:
            raise RuntimeError("Not connected to Redis")

        consumer_name = consumer_name or f"consumer-{id(self)}"

        # Create consumer group if it doesn't exist
        try:
            await self._redis.xgroup_create(
                stream,
                consumer_group,
                id="0",
                mkstream=True,
            )
            logger.info(
                "consumer_group_created",
                stream=stream,
                group=consumer_group,
            )
        except redis.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise

        logger.info(
            "consumer_started",
            stream=stream,
            group=consumer_group,
            consumer=consumer_name,
        )

        while True:
            try:
                # Read new messages
                messages = await self._redis.xreadgroup(
                    consumer_group,
                    consumer_name,
                    {stream: ">"},
                    count=batch_size,
                    block=block_ms,
                )

                if not messages:
                    continue

                for stream_name, stream_messages in messages:
                    for message_id, fields in stream_messages:
                        try:
                            # Decode message
                            msg_id = (
                                message_id.decode()
                                if isinstance(message_id, bytes)
                                else message_id
                            )
                            data_bytes = fields.get(b"data") or fields.get("data")
                            if data_bytes:
                                if isinstance(data_bytes, bytes):
                                    data_bytes = data_bytes.decode()
                                data = json.loads(data_bytes)
                            else:
                                data = {}

                            yield msg_id, data

                            # Acknowledge message
                            await self._redis.xack(stream, consumer_group, message_id)

                        except json.JSONDecodeError as e:
                            logger.error(
                                "message_decode_error",
                                stream=stream,
                                message_id=msg_id,
                                error=str(e),
                            )
                            # Acknowledge to prevent reprocessing bad messages
                            await self._redis.xack(stream, consumer_group, message_id)

            except asyncio.CancelledError:
                logger.info("consumer_cancelled", stream=stream)
                break
            except Exception as e:
                logger.error("consumer_error", stream=stream, error=str(e))
                await asyncio.sleep(1)  # Back off on errors

    async def consume_callback(
        self,
        stream: str,
        consumer_group: str,
        callback: Callable[[str, dict[str, Any]], Any],
        consumer_name: str | None = None,
    ) -> asyncio.Task:
        """
        Start a background task that consumes messages and calls a callback.

        Args:
            stream: Stream to consume from
            consumer_group: Consumer group name
            callback: Async function to call for each message
            consumer_name: Unique consumer identifier

        Returns:
            The background task (can be cancelled)
        """

        async def _consume():
            async for message_id, data in self.consume(
                stream, consumer_group, consumer_name
            ):
                try:
                    result = callback(message_id, data)
                    if asyncio.iscoroutine(result):
                        await result
                except Exception as e:
                    logger.error(
                        "callback_error",
                        stream=stream,
                        message_id=message_id,
                        error=str(e),
                    )

        task = asyncio.create_task(_consume())
        self._consumer_tasks.append(task)
        return task

    async def get_stream_info(self, stream: str) -> dict[str, Any]:
        """Get information about a stream."""
        if self._redis is None:
            raise RuntimeError("Not connected to Redis")

        info = await self._redis.xinfo_stream(stream)
        return {
            "length": info.get("length", 0),
            "first_entry": info.get("first-entry"),
            "last_entry": info.get("last-entry"),
            "groups": info.get("groups", 0),
        }

    async def health_check(self) -> bool:
        """Check if Redis connection is healthy."""
        try:
            if self._redis:
                await self._redis.ping()
                return True
        except Exception:
            pass
        return False

