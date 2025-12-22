"""
Conversation state management and persistence.
"""

import json
from datetime import datetime
from typing import Any

import aiosqlite

from cairu_common.logging import get_logger

logger = get_logger()


class ConversationStateManager:
    """
    Manages conversation state, user profiles, and care plans.

    Uses SQLite for local-first persistence that works offline.
    """

    def __init__(self, database_path: str):
        self.database_path = database_path
        self.db: aiosqlite.Connection | None = None

    async def initialize(self):
        """Initialize database connection and schema."""
        self.db = await aiosqlite.connect(self.database_path)
        await self._create_schema()
        logger.info("state_manager_initialized", database=self.database_path)

    async def close(self):
        """Close database connection."""
        if self.db:
            await self.db.close()

    async def _create_schema(self):
        """Create database tables if they don't exist."""
        await self.db.executescript("""
            -- User profiles
            CREATE TABLE IF NOT EXISTS user_profiles (
                user_id TEXT PRIMARY KEY,
                device_id TEXT NOT NULL,
                name TEXT,
                preferred_name TEXT,
                timezone TEXT DEFAULT 'America/Los_Angeles',
                life_details TEXT DEFAULT '{}',
                preferences TEXT DEFAULT '{}',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            -- Conversation history
            CREATE TABLE IF NOT EXISTS conversation_turns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                user_id TEXT,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                intent TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_turns_session ON conversation_turns(session_id);

            -- Care plans
            CREATE TABLE IF NOT EXISTS care_plans (
                user_id TEXT PRIMARY KEY,
                medications TEXT DEFAULT '[]',
                routines TEXT DEFAULT '[]',
                contacts TEXT DEFAULT '[]',
                notes TEXT,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            -- Device sessions
            CREATE TABLE IF NOT EXISTS device_sessions (
                device_id TEXT PRIMARY KEY,
                user_id TEXT,
                last_activity TEXT,
                session_count INTEGER DEFAULT 0
            );

            -- Learned facts (memory)
            CREATE TABLE IF NOT EXISTS learned_facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                fact_type TEXT,
                fact_key TEXT,
                fact_value TEXT,
                confidence REAL DEFAULT 1.0,
                source TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_facts_user ON learned_facts(user_id);
        """)
        await self.db.commit()

    async def get_user_profile(self, device_id: str) -> dict[str, Any]:
        """Get or create user profile for a device."""
        async with self.db.execute(
            "SELECT * FROM user_profiles WHERE device_id = ?",
            (device_id,)
        ) as cursor:
            row = await cursor.fetchone()

        if row:
            columns = [desc[0] for desc in cursor.description]
            profile = dict(zip(columns, row))
            profile["life_details"] = json.loads(profile.get("life_details", "{}"))
            profile["preferences"] = json.loads(profile.get("preferences", "{}"))
            return profile

        # Create default profile
        user_id = f"user_{device_id}"
        await self.db.execute(
            "INSERT INTO user_profiles (user_id, device_id, name) VALUES (?, ?, ?)",
            (user_id, device_id, "Friend")
        )
        await self.db.commit()

        return {
            "user_id": user_id,
            "device_id": device_id,
            "name": "Friend",
            "life_details": {},
            "preferences": {},
        }

    async def update_user_profile(self, user_id: str, updates: dict[str, Any]):
        """Update user profile fields."""
        # Handle JSON fields
        if "life_details" in updates:
            updates["life_details"] = json.dumps(updates["life_details"])
        if "preferences" in updates:
            updates["preferences"] = json.dumps(updates["preferences"])

        updates["updated_at"] = datetime.utcnow().isoformat()

        set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
        values = list(updates.values()) + [user_id]

        await self.db.execute(
            f"UPDATE user_profiles SET {set_clause} WHERE user_id = ?",
            values
        )
        await self.db.commit()

    async def get_conversation_history(
        self,
        session_id: str,
        limit: int = 10,
    ) -> list[dict[str, str]]:
        """Get recent conversation turns for a session."""
        async with self.db.execute(
            """
            SELECT role, content FROM conversation_turns
            WHERE session_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (session_id, limit)
        ) as cursor:
            rows = await cursor.fetchall()

        # Return in chronological order
        return [{"role": row[0], "content": row[1]} for row in reversed(rows)]

    async def add_turn(
        self,
        session_id: str,
        role: str,
        content: str,
        user_id: str | None = None,
        intent: str | None = None,
    ):
        """Add a conversation turn."""
        await self.db.execute(
            """
            INSERT INTO conversation_turns (session_id, user_id, role, content, intent)
            VALUES (?, ?, ?, ?, ?)
            """,
            (session_id, user_id, role, content, intent)
        )
        await self.db.commit()

    async def get_care_plan(self, user_id: str) -> dict[str, Any]:
        """Get care plan for a user."""
        async with self.db.execute(
            "SELECT * FROM care_plans WHERE user_id = ?",
            (user_id,)
        ) as cursor:
            row = await cursor.fetchone()

        if row:
            columns = [desc[0] for desc in cursor.description]
            plan = dict(zip(columns, row))
            plan["medications"] = json.loads(plan.get("medications", "[]"))
            plan["routines"] = json.loads(plan.get("routines", "[]"))
            plan["contacts"] = json.loads(plan.get("contacts", "[]"))
            return plan

        return {
            "user_id": user_id,
            "medications": [],
            "routines": [],
            "contacts": [],
        }

    async def get_active_devices(self) -> list[str]:
        """Get list of recently active devices."""
        async with self.db.execute(
            """
            SELECT device_id FROM device_sessions
            WHERE datetime(last_activity) > datetime('now', '-1 hour')
            """
        ) as cursor:
            rows = await cursor.fetchall()

        return [row[0] for row in rows]

    async def update_device_activity(self, device_id: str, user_id: str | None = None):
        """Update device last activity timestamp."""
        await self.db.execute(
            """
            INSERT INTO device_sessions (device_id, user_id, last_activity, session_count)
            VALUES (?, ?, ?, 1)
            ON CONFLICT(device_id) DO UPDATE SET
                last_activity = excluded.last_activity,
                session_count = session_count + 1
            """,
            (device_id, user_id, datetime.utcnow().isoformat())
        )
        await self.db.commit()

    async def add_learned_fact(
        self,
        user_id: str,
        fact_type: str,
        fact_key: str,
        fact_value: str,
        source: str = "conversation",
    ):
        """Store a learned fact about the user."""
        await self.db.execute(
            """
            INSERT INTO learned_facts (user_id, fact_type, fact_key, fact_value, source)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, fact_type, fact_key, fact_value, source)
        )
        await self.db.commit()
        logger.debug("fact_learned", user_id=user_id, fact_type=fact_type, fact_key=fact_key)

    async def get_learned_facts(self, user_id: str) -> list[dict[str, Any]]:
        """Get all learned facts for a user."""
        async with self.db.execute(
            """
            SELECT fact_type, fact_key, fact_value, confidence
            FROM learned_facts
            WHERE user_id = ?
            ORDER BY created_at DESC
            """,
            (user_id,)
        ) as cursor:
            rows = await cursor.fetchall()

        return [
            {
                "type": row[0],
                "key": row[1],
                "value": row[2],
                "confidence": row[3],
            }
            for row in rows
        ]

