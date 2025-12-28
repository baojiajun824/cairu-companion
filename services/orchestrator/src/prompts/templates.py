"""
LLM prompt templates for cAIru companion interactions.

These templates create the persona and context for the AI companion.
"""

from typing import Any

from cairu_common.logging import get_logger

logger = get_logger()


class PromptBuilder:
    """Builds system prompts for LLM interactions."""

    # Base system prompt defining the companion persona
    BASE_PERSONA = """You are a friendly companion for {name}. Reply in ONE short sentence only.

RULES:
- Maximum 10 words
- One sentence only
- No filler phrases
- Be warm and direct

Example replies:
"I'm doing great, how about you?"
"That sounds lovely!"
"The weather looks nice today."
"""

    CARE_CONTEXT = """
## Care Information
{care_context}
"""

    PERSONAL_CONTEXT = """
## About {name}
{personal_details}
"""

    PROACTIVE_TEMPLATE = """You are initiating a check-in with {name}. This is a {rule_type} interaction.

Your goal: {goal}

Keep it natural and warm. Don't be overly formal or clinical. Just check in like a caring friend would.
"""

    def build_system_prompt(
        self,
        user_profile: dict[str, Any],
        care_plan: dict[str, Any] | None = None,
    ) -> str:
        """
        Build a complete system prompt for reactive conversations.

        Args:
            user_profile: User profile with name, preferences, life details
            care_plan: Optional care plan context

        Returns:
            Formatted system prompt
        """
        from datetime import datetime

        name = user_profile.get("preferred_name") or user_profile.get("name", "Friend")
        now = datetime.now()

        # Start with base persona
        prompt = self.BASE_PERSONA.format(
            name=name,
            current_time=now.strftime("%I:%M %p"),
            current_day=now.strftime("%A, %B %d"),
        )

        # Add personal context if available
        life_details = user_profile.get("life_details", {})
        if life_details:
            personal_str = self._format_life_details(life_details)
            prompt += self.PERSONAL_CONTEXT.format(
                name=name,
                personal_details=personal_str,
            )

        # Add care context if available
        if care_plan:
            care_str = self._format_care_plan(care_plan)
            if care_str:
                prompt += self.CARE_CONTEXT.format(care_context=care_str)

        return prompt.strip()

    def build_proactive_prompt(
        self,
        user_profile: dict[str, Any],
        rule: dict[str, Any],
    ) -> str:
        """
        Build a system prompt for proactive interactions.

        Args:
            user_profile: User profile
            rule: Triggered rule with type and prompt

        Returns:
            Formatted system prompt
        """
        name = user_profile.get("preferred_name") or user_profile.get("name", "Friend")

        # Map rule types to friendly descriptions
        rule_type_map = {
            "time_based": "scheduled check-in",
            "behavioral": "wellness check",
            "care_plan": "care reminder",
        }

        rule_type = rule_type_map.get(rule.get("type", ""), "friendly check-in")
        goal = rule.get("prompt", "Check in and see how they're doing")

        prompt = self.PROACTIVE_TEMPLATE.format(
            name=name,
            rule_type=rule_type,
            goal=goal,
        )

        # Add personal context
        life_details = user_profile.get("life_details", {})
        if life_details:
            personal_str = self._format_life_details(life_details)
            prompt += f"\n\n## About {name}\n{personal_str}"

        return prompt.strip()

    def _format_life_details(self, details: dict[str, Any]) -> str:
        """Format life details into readable string."""
        lines = []

        if details.get("family"):
            lines.append(f"Family: {details['family']}")

        if details.get("hobbies"):
            hobbies = ", ".join(details["hobbies"]) if isinstance(details["hobbies"], list) else details["hobbies"]
            lines.append(f"Enjoys: {hobbies}")

        if details.get("background"):
            lines.append(f"Background: {details['background']}")

        if details.get("important_memories"):
            lines.append(f"Important to them: {details['important_memories']}")

        return "\n".join(lines) if lines else "No personal details available yet."

    def _format_care_plan(self, plan: dict[str, Any]) -> str:
        """Format care plan into readable string."""
        lines = []

        medications = plan.get("medications", [])
        if medications:
            med_str = ", ".join(m.get("name", str(m)) for m in medications[:3])
            lines.append(f"Medications: {med_str}")

        routines = plan.get("routines", [])
        if routines:
            routine_str = ", ".join(r.get("name", str(r)) for r in routines[:3])
            lines.append(f"Daily routines: {routine_str}")

        return "\n".join(lines) if lines else ""

