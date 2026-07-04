"""
Database connection and query helpers for Discord Guard Bot.
All queries are async using aiosqlite.
"""

import aiosqlite
import asyncio
from datetime import datetime, timezone
from typing import Optional

DB_PATH = "guard.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS strikes (
    guild_id INTEGER,
    user_id INTEGER,
    strike_count INTEGER DEFAULT 0,
    last_strike_at TIMESTAMP,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS strike_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER,
    user_id INTEGER,
    reason TEXT,
    moderator_id INTEGER,
    created_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS guild_config (
    guild_id INTEGER PRIMARY KEY,
    log_channel_id INTEGER,
    timeout_1_minutes INTEGER DEFAULT 5,
    timeout_2_minutes INTEGER DEFAULT 30,
    timeout_3_minutes INTEGER DEFAULT 1440,
    action_after_strike_3 TEXT DEFAULT 'timeout',
    strike_decay_days INTEGER DEFAULT 30,
    join_rate_limit INTEGER DEFAULT 5,
    join_rate_window_seconds INTEGER DEFAULT 10,
    min_account_age_days INTEGER DEFAULT 7,
    lockdown_enabled BOOLEAN DEFAULT 0
);

CREATE TABLE IF NOT EXISTS whitelist (
    guild_id INTEGER,
    role_id INTEGER,
    PRIMARY KEY (guild_id, role_id)
);

CREATE TABLE IF NOT EXISTS banned_words (
    guild_id INTEGER,
    word TEXT,
    PRIMARY KEY (guild_id, word)
);

CREATE TABLE IF NOT EXISTS verification_config (
    guild_id INTEGER PRIMARY KEY,
    channel_id INTEGER,
    unverified_role_id INTEGER,
    verified_role_id INTEGER
);
"""

_db: Optional[aiosqlite.Connection] = None
_lock = asyncio.Lock()


async def get_db() -> aiosqlite.Connection:
    global _db
    if _db is None:
        _db = await aiosqlite.connect(DB_PATH)
        _db.row_factory = aiosqlite.Row
        await _db.executescript(SCHEMA)
        await _db.commit()
    return _db


async def close_db():
    global _db
    if _db is not None:
        await _db.close()
        _db = None


# ---------------------------------------------------------------------------
# Guild config
# ---------------------------------------------------------------------------

async def get_guild_config(guild_id: int) -> dict:
    db = await get_db()
    async with db.execute(
        "SELECT * FROM guild_config WHERE guild_id = ?", (guild_id,)
    ) as cur:
        row = await cur.fetchone()
    if row is None:
        # Insert defaults and return them
        await db.execute(
            "INSERT OR IGNORE INTO guild_config (guild_id) VALUES (?)", (guild_id,)
        )
        await db.commit()
        async with db.execute(
            "SELECT * FROM guild_config WHERE guild_id = ?", (guild_id,)
        ) as cur:
            row = await cur.fetchone()
    return dict(row) if row else {}


async def set_guild_config_field(guild_id: int, field: str, value) -> None:
    db = await get_db()
    await get_guild_config(guild_id)  # ensure row exists
    await db.execute(
        f"UPDATE guild_config SET {field} = ? WHERE guild_id = ?", (value, guild_id)
    )
    await db.commit()


# ---------------------------------------------------------------------------
# Strikes
# ---------------------------------------------------------------------------

async def get_strikes(guild_id: int, user_id: int) -> dict:
    db = await get_db()
    async with db.execute(
        "SELECT * FROM strikes WHERE guild_id = ? AND user_id = ?",
        (guild_id, user_id),
    ) as cur:
        row = await cur.fetchone()
    return dict(row) if row else {"guild_id": guild_id, "user_id": user_id, "strike_count": 0, "last_strike_at": None}


async def add_strike(guild_id: int, user_id: int, reason: str, moderator_id: Optional[int] = None) -> int:
    """Increment strike count (with decay check). Returns new strike count."""
    db = await get_db()
    config = await get_guild_config(guild_id)
    decay_days = config.get("strike_decay_days", 30)

    async with _lock:
        row = await get_strikes(guild_id, user_id)
        current_count = row["strike_count"] or 0
        last_strike_at = row["last_strike_at"]

        # Decay check
        if last_strike_at and current_count > 0:
            try:
                last_dt = datetime.fromisoformat(str(last_strike_at)).replace(tzinfo=timezone.utc)
                now = datetime.now(timezone.utc)
                delta = now - last_dt
                if delta.days >= decay_days:
                    current_count = 0
            except Exception:
                pass

        new_count = current_count + 1
        now_str = datetime.now(timezone.utc).isoformat()

        await db.execute(
            """
            INSERT INTO strikes (guild_id, user_id, strike_count, last_strike_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(guild_id, user_id) DO UPDATE SET
                strike_count = ?,
                last_strike_at = ?
            """,
            (guild_id, user_id, new_count, now_str, new_count, now_str),
        )
        await db.execute(
            "INSERT INTO strike_log (guild_id, user_id, reason, moderator_id, created_at) VALUES (?, ?, ?, ?, ?)",
            (guild_id, user_id, reason, moderator_id, now_str),
        )
        await db.commit()

    return new_count


async def remove_strike(guild_id: int, user_id: int) -> int:
    """Decrement strike count by 1 (min 0). Returns new count."""
    db = await get_db()
    row = await get_strikes(guild_id, user_id)
    new_count = max(0, (row["strike_count"] or 0) - 1)
    await db.execute(
        "INSERT INTO strikes (guild_id, user_id, strike_count, last_strike_at) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(guild_id, user_id) DO UPDATE SET strike_count = ?",
        (guild_id, user_id, new_count, datetime.now(timezone.utc).isoformat(), new_count),
    )
    await db.commit()
    return new_count


async def reset_strikes(guild_id: int, user_id: int) -> None:
    db = await get_db()
    await db.execute(
        "INSERT INTO strikes (guild_id, user_id, strike_count, last_strike_at) VALUES (?, ?, 0, ?) "
        "ON CONFLICT(guild_id, user_id) DO UPDATE SET strike_count = 0",
        (guild_id, user_id, datetime.now(timezone.utc).isoformat()),
    )
    await db.commit()


async def get_strike_log(guild_id: int, user_id: int, limit: int = 5) -> list[dict]:
    db = await get_db()
    async with db.execute(
        "SELECT * FROM strike_log WHERE guild_id = ? AND user_id = ? ORDER BY created_at DESC LIMIT ?",
        (guild_id, user_id, limit),
    ) as cur:
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Whitelist
# ---------------------------------------------------------------------------

async def get_whitelist(guild_id: int) -> list[int]:
    db = await get_db()
    async with db.execute(
        "SELECT role_id FROM whitelist WHERE guild_id = ?", (guild_id,)
    ) as cur:
        rows = await cur.fetchall()
    return [r["role_id"] for r in rows]


async def add_whitelist(guild_id: int, role_id: int) -> None:
    db = await get_db()
    await db.execute(
        "INSERT OR IGNORE INTO whitelist (guild_id, role_id) VALUES (?, ?)",
        (guild_id, role_id),
    )
    await db.commit()


async def remove_whitelist(guild_id: int, role_id: int) -> None:
    db = await get_db()
    await db.execute(
        "DELETE FROM whitelist WHERE guild_id = ? AND role_id = ?",
        (guild_id, role_id),
    )
    await db.commit()


# ---------------------------------------------------------------------------
# Banned words
# ---------------------------------------------------------------------------

async def get_banned_words(guild_id: int) -> list[str]:
    db = await get_db()
    async with db.execute(
        "SELECT word FROM banned_words WHERE guild_id = ?", (guild_id,)
    ) as cur:
        rows = await cur.fetchall()
    return [r["word"] for r in rows]


async def add_banned_word(guild_id: int, word: str) -> None:
    db = await get_db()
    await db.execute(
        "INSERT OR IGNORE INTO banned_words (guild_id, word) VALUES (?, ?)",
        (guild_id, word.lower()),
    )
    await db.commit()


async def remove_banned_word(guild_id: int, word: str) -> None:
    db = await get_db()
    await db.execute(
        "DELETE FROM banned_words WHERE guild_id = ? AND word = ?",
        (guild_id, word.lower()),
    )
    await db.commit()


# ---------------------------------------------------------------------------
# Verification config
# ---------------------------------------------------------------------------

async def get_verification_config(guild_id: int) -> Optional[dict]:
    db = await get_db()
    async with db.execute(
        "SELECT * FROM verification_config WHERE guild_id = ?", (guild_id,)
    ) as cur:
        row = await cur.fetchone()
    return dict(row) if row else None


async def set_verification_config(
    guild_id: int, channel_id: int, unverified_role_id: int, verified_role_id: int
) -> None:
    db = await get_db()
    await db.execute(
        """
        INSERT INTO verification_config (guild_id, channel_id, unverified_role_id, verified_role_id)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(guild_id) DO UPDATE SET
            channel_id = ?,
            unverified_role_id = ?,
            verified_role_id = ?
        """,
        (guild_id, channel_id, unverified_role_id, verified_role_id,
         channel_id, unverified_role_id, verified_role_id),
    )
    await db.commit()
