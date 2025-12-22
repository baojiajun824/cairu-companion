"""
cAIru Orchestrator Service

Central brain of the system. Manages conversation state, user profile,
care plan context, and the proactive rules engine.

Simplified for Alpha: Single user, no event emission.
"""

import asyncio
import signal
from datetime import datetime
import uuid

from cairu_common.config import get_orchestrator_settings
from cairu_common.logging import setup_logging, get_logger
from cairu_common.redis_client import RedisStreamClient
from cairu_common.models import LLMRequest, TTSRequest
from cairu_common.metrics import set_service_info, set_component_health

from src.state import ConversationStateManager
from src.rules.engine import RulesEngine
from src.prompts.templates import PromptBuilder

settings = get_orchestrator_settings()
logger = get_logger()

# Single user for Alpha
DEFAULT_USER_ID = "user-001"


class OrchestratorService:
    """Central orchestration service."""

    def __init__(self):
        self.redis: RedisStreamClient | None = None
        self.state_manager: ConversationStateManager | None = None
        self.rules_engine: RulesEngine | None = None
        self.prompt_builder: PromptBuilder | None = None
        self._running = False

    async def start(self):
        """Initialize and start the orchestrator."""
        setup_logging(
            service_name="orchestrator",
            log_level=settings.log_level,
            json_format=not settings.is_development,
        )
        set_service_info(name="orchestrator", version="0.1.0", environment=settings.environment)

        logger.info("orchestrator_starting")

        # Initialize state manager
        self.state_manager = ConversationStateManager(settings.database_path)
        await self.state_manager.initialize()
        set_component_health("database", True)

        # Initialize rules engine (for proactive interactions)
        self.rules_engine = RulesEngine(settings.rules_config_path)
        await self.rules_engine.load_rules()

        # Initialize prompt builder
        self.prompt_builder = PromptBuilder()

        # Connect to Redis
        self.redis = RedisStreamClient(str(settings.redis_url))
        await self.redis.connect()
        set_component_health("redis", True)

        self._running = True
        logger.info("orchestrator_started")

        # Start processing loops
        await asyncio.gather(
            self._process_transcripts(),
            self._process_llm_responses(),
            self._run_proactive_rules(),
        )

    async def stop(self):
        """Gracefully stop the service."""
        logger.info("orchestrator_stopping")
        self._running = False
        if self.redis:
            await self.redis.disconnect()
        if self.state_manager:
            await self.state_manager.close()
        logger.info("orchestrator_stopped")

    async def _process_transcripts(self):
        """Process incoming transcripts from ASR."""
        if not self.redis:
            raise RuntimeError("Service not initialized")

        async for message_id, data in self.redis.consume(
            RedisStreamClient.STREAMS["transcripts"],
            consumer_group="orchestrator",
            consumer_name="orchestrator-main",
        ):
            if not self._running:
                break

            try:
                await self._handle_transcript(data)
            except Exception as e:
                logger.error("transcript_processing_error", message_id=message_id, error=str(e))

    async def _handle_transcript(self, data: dict):
        """Handle a transcript and prepare LLM request."""
        device_id = data.get("device_id", "unknown")
        session_id = data.get("session_id", "unknown")
        text = data.get("text", "")

        if not text.strip():
            return

        logger.info("processing_transcript", text=text[:50])

        # Get user profile and conversation history
        user_profile = await self.state_manager.get_user_profile(DEFAULT_USER_ID)
        history = await self.state_manager.get_conversation_history(session_id, limit=10)
        care_plan = await self.state_manager.get_care_plan(DEFAULT_USER_ID)

        # Build system prompt
        system_prompt = self.prompt_builder.build_system_prompt(
            user_profile=user_profile,
            care_plan=care_plan,
        )

        # Create LLM request (keep responses SHORT for natural conversation)
        request = LLMRequest(
            request_id=str(uuid.uuid4()),
            device_id=device_id,
            session_id=session_id,
            user_id=DEFAULT_USER_ID,
            user_message=text,
            conversation_history=history,
            user_profile=user_profile,
            care_plan_context=care_plan,
            system_prompt=system_prompt,
            max_tokens=60,  # Allow complete short sentences
            temperature=0.7,
        )

        # Store user turn
        await self.state_manager.add_turn(
            session_id=session_id,
            role="user",
            content=text,
        )

        # Send to LLM
        await self.redis.publish(
            RedisStreamClient.STREAMS["llm_requests"],
            request,
        )

        logger.debug("llm_request_sent", request_id=request.request_id)

    async def _process_llm_responses(self):
        """Process LLM responses and send to TTS."""
        if not self.redis:
            raise RuntimeError("Service not initialized")

        async for message_id, data in self.redis.consume(
            RedisStreamClient.STREAMS["llm_responses"],
            consumer_group="orchestrator-responses",
            consumer_name="orchestrator-resp",
        ):
            if not self._running:
                break

            try:
                await self._handle_llm_response(data)
            except Exception as e:
                logger.error("llm_response_error", message_id=message_id, error=str(e))

    async def _handle_llm_response(self, data: dict):
        """Handle LLM response and forward to TTS."""
        device_id = data.get("device_id", "unknown")
        session_id = data.get("session_id", "unknown")
        request_id = data.get("request_id", "unknown")
        text = data.get("text", "")

        logger.info("llm_response_received", text=text[:50])

        # Store assistant turn
        await self.state_manager.add_turn(
            session_id=session_id,
            role="assistant",
            content=text,
        )

        # Send to TTS
        tts_request = TTSRequest(
            request_id=request_id,
            device_id=device_id,
            session_id=session_id,
            text=text,
        )

        await self.redis.publish(
            RedisStreamClient.STREAMS["tts_requests"],
            tts_request,
        )

    async def _run_proactive_rules(self):
        """Run proactive rules engine for scheduled interactions."""
        if not settings.enable_proactive_rules:
            logger.info("proactive_rules_disabled")
            return

        logger.info("proactive_rules_engine_started")

        while self._running:
            try:
                # Check rules every minute
                await asyncio.sleep(60)

                if not self._running:
                    break

                # Single device - use default
                device_id = "companion-001"

                triggered_rules = await self.rules_engine.evaluate(
                    device_id=device_id,
                    state_manager=self.state_manager,
                )

                for rule in triggered_rules:
                    await self._execute_proactive_rule(device_id, rule)

            except Exception as e:
                logger.error("proactive_rules_error", error=str(e))

    async def _execute_proactive_rule(self, device_id: str, rule: dict):
        """Execute a triggered proactive rule."""
        logger.info("executing_proactive_rule", rule_name=rule.get("name"))

        # Get context
        user_profile = await self.state_manager.get_user_profile(DEFAULT_USER_ID)
        session_id = f"{device_id}-proactive-{datetime.utcnow().timestamp()}"

        # Build proactive message request
        request = LLMRequest(
            request_id=str(uuid.uuid4()),
            device_id=device_id,
            session_id=session_id,
            user_id=DEFAULT_USER_ID,
            user_message=f"[PROACTIVE:{rule.get('name')}] {rule.get('prompt', '')}",
            user_profile=user_profile,
            system_prompt=self.prompt_builder.build_proactive_prompt(
                user_profile=user_profile,
                rule=rule,
            ),
            max_tokens=100,
            temperature=0.8,
        )

        await self.redis.publish(
            RedisStreamClient.STREAMS["llm_requests"],
            request,
        )


async def main():
    """Entry point."""
    service = OrchestratorService()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(service.stop()))

    await service.start()


if __name__ == "__main__":
    asyncio.run(main())
