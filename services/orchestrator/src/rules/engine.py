"""
Proactive rules engine for scheduled and context-triggered interactions.

Implements Aaron's 26 rule contexts for proactive companion behavior.
"""

from datetime import datetime, time
from typing import Any

import yaml

from cairu_common.logging import get_logger

logger = get_logger()


class RulesEngine:
    """
    Evaluates proactive rules and triggers appropriate interactions.

    Rules can be triggered by:
    - Time of day (morning check-in, evening wind-down)
    - Scheduled events (medication times, appointments)
    - Behavioral signals (extended silence, distress detection)
    - Care plan events (meal times, activity reminders)
    """

    def __init__(self, config_path: str):
        self.config_path = config_path
        self.rules: list[dict[str, Any]] = []

    async def load_rules(self):
        """Load rules from configuration file."""
        try:
            with open(self.config_path, "r") as f:
                config = yaml.safe_load(f)
                self.rules = config.get("rules", [])
            logger.info("rules_loaded", count=len(self.rules))
        except FileNotFoundError:
            logger.warning("rules_config_not_found", path=self.config_path)
            self.rules = self._get_default_rules()
            logger.info("using_default_rules", count=len(self.rules))

    def _get_default_rules(self) -> list[dict[str, Any]]:
        """Get default rules when config file is not found."""
        return [
            {
                "name": "morning_greeting",
                "type": "time_based",
                "trigger": {"time_range": {"start": "07:00", "end": "09:00"}},
                "frequency": "daily",
                "prompt": "Good morning! How are you feeling today?",
                "priority": 1,
            },
            {
                "name": "afternoon_checkin",
                "type": "time_based",
                "trigger": {"time_range": {"start": "14:00", "end": "15:00"}},
                "frequency": "daily",
                "prompt": "How is your afternoon going? Have you had lunch?",
                "priority": 2,
            },
            {
                "name": "evening_winddown",
                "type": "time_based",
                "trigger": {"time_range": {"start": "19:00", "end": "20:00"}},
                "frequency": "daily",
                "prompt": "The evening is here. How was your day?",
                "priority": 2,
            },
            {
                "name": "extended_silence",
                "type": "behavioral",
                "trigger": {"silence_duration_minutes": 120},
                "prompt": "I haven't heard from you in a while. Is everything okay?",
                "priority": 3,
            },
            {
                "name": "medication_reminder",
                "type": "care_plan",
                "trigger": {"event": "medication_due"},
                "prompt": "It's time for your medication. Would you like me to remind you what to take?",
                "priority": 1,
            },
        ]

    async def evaluate(
        self,
        device_id: str,
        state_manager: Any,
    ) -> list[dict[str, Any]]:
        """
        Evaluate all rules for a device and return triggered ones.

        Args:
            device_id: Device to evaluate rules for
            state_manager: ConversationStateManager instance

        Returns:
            List of triggered rules to execute
        """
        triggered = []
        now = datetime.now()
        current_time = now.time()

        for rule in self.rules:
            try:
                if await self._should_trigger(rule, device_id, state_manager, current_time):
                    triggered.append(rule)
                    logger.debug(
                        "rule_triggered",
                        device_id=device_id,
                        rule_name=rule.get("name"),
                    )
            except Exception as e:
                logger.error(
                    "rule_evaluation_error",
                    rule_name=rule.get("name"),
                    error=str(e),
                )

        # Sort by priority (lower = higher priority)
        triggered.sort(key=lambda r: r.get("priority", 10))

        return triggered

    async def _should_trigger(
        self,
        rule: dict[str, Any],
        device_id: str,
        state_manager: Any,
        current_time: time,
    ) -> bool:
        """Check if a rule should trigger."""
        rule_type = rule.get("type")
        trigger = rule.get("trigger", {})

        if rule_type == "time_based":
            return self._check_time_trigger(trigger, current_time)

        elif rule_type == "behavioral":
            return await self._check_behavioral_trigger(trigger, device_id, state_manager)

        elif rule_type == "care_plan":
            return await self._check_care_plan_trigger(trigger, device_id, state_manager)

        return False

    def _check_time_trigger(self, trigger: dict, current_time: time) -> bool:
        """Check if current time falls within trigger range."""
        time_range = trigger.get("time_range", {})
        start_str = time_range.get("start", "00:00")
        end_str = time_range.get("end", "23:59")

        start = time.fromisoformat(start_str)
        end = time.fromisoformat(end_str)

        return start <= current_time <= end

    async def _check_behavioral_trigger(
        self,
        trigger: dict,
        device_id: str,
        state_manager: Any,
    ) -> bool:
        """Check behavioral triggers like extended silence."""
        silence_threshold = trigger.get("silence_duration_minutes")

        if silence_threshold:
            # Check last activity time
            # This would need to be implemented in state_manager
            pass

        return False

    async def _check_care_plan_trigger(
        self,
        trigger: dict,
        device_id: str,
        state_manager: Any,
    ) -> bool:
        """Check care plan event triggers."""
        event = trigger.get("event")

        if event == "medication_due":
            # Check if any medication is due
            # This would check against the care plan schedule
            pass

        return False

