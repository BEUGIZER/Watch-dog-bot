"""
Database connection and query helpers for Discord Guard Bot.
All queries are async using asyncpg (PostgreSQL).
"""

import asyncpg
import asyncio
import os
from datetime import datetime, timezone
from typing import Optional

DATABASE_URL = os.environ.get("DATABASE_URL")

SCHEMA = """
CREATE TABLE IF NOT EXISTS strikes (
    guild_id BIGINT,
    user_id BIGINT,
    strike_count INTEGER DEFAULT 0,
    last_strike_at TIMESTAMPTZ,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS strike_log (
    id BIGSERIAL PRIMARY KEY,
    guild_id BIGINT,
    user_id BIGINT,
    reason TEXT,
    moderator_id BIGINT,
    created_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS guild_config (
    guild_id BIGINT PRIMARY KEY,
    log_channel_id BIGINT,
    timeout_1_minutes INTEGER DEFAULT 5,
    timeout_2_minutes INTEGER DEFAULT 30,
    timeout_3_minutes INTEGER DEFAULT 1440,
    action_after_strike_3 TEXT DEFAULT 'timeout',
    strike_decay_days INTEGER DEFAULT 30,
    join_rate_limit INTEGER DEFAULT 5,
    join_rate_window_seconds INTEGER DEFAULT 10,
    min_account_age_days INTEGER DEFAULT 7,
    lockdown_enabled BOOLEAN DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS whitelist (
    guild_id BIGINT,
    role_id BIGINT,
    PRIMARY KEY (guild_id, role_id)
);

CREATE TABLE IF NOT EXISTS banned_words (
    guild_id BIGINT,
    word TEXT,
    PRIMARY KEY (guild_id, word)
);

CREATE TABLE IF NOT EXISTS verification_config (
    guild_id BIGINT PRIMARY KEY,
    channel_id BIGINT,
    unverified_role_id BIGINT,
    verified_role_id BIGINT
);
"""

_pool: Optional[asyncpg.Pool] = None
_pool_init_lock = asyncio.Lock()


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is not None:
        return _pool
    async with _pool_init_lock:
        # Double-check after acquiring the lock
        if _pool is None:
            if not DATABASE_URL:
                raise RuntimeError(
                    "DATABASE_URL environment variable is not set. "
                    "Add a PostgreSQL database to your Railway project and link it."
                )
            _pool = await asyncpg.create_pool(DATABASE_URL)
            async with _pool.acquire() as conn:
                await conn.execute(SCHEMA)
    return _pool


# Alias kept so main.py's setup_hook works without changes
async def get_db():
    return await get_pool()


async def close_db():
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


# ---------------------------------------------------------------------------
# Guild config
# ---------------------------------------------------------------------------

async def get_guild_config(guild_id: int) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM guild_config WHERE guild_id = $1", guild_id
        )
        if row is None:
            await conn.execute(
                "INSERT INTO guild_config (guild_id) VALUES ($1) ON CONFLICT DO NOTHING",
                guild_id,
            )
            row = await conn.fetchrow(
                "SELECT * FROM guild_config WHERE guild_id = $1", guild_id
            )
    return dict(row) if row else {}


async def set_guild_config_field(guild_id: int, field: str, value) -> None:
    pool = await get_pool()
    await get_guild_config(guild_id)  # ensure row exists
    async with pool.acquire() as conn:
        # field is always an internal constant — not user input
        await conn.execute(
            f"UPDATE guild_config SET {field} = $1 WHERE guild_id = $2",
            value, guild_id,
        )


# ---------------------------------------------------------------------------
# Strikes
# ---------------------------------------------------------------------------

async def get_strikes(guild_id: int, user_id: int) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM strikes WHERE guild_id = $1 AND user_id = $2",
            guild_id, user_id,
        )
    return dict(row) if row else {
        "guild_id": guild_id, "user_id": user_id,
        "strike_count": 0, "last_strike_at": None,
    }


async def add_strike(
    guild_id: int, user_id: int, reason: str, moderator_id: Optional[int] = None
) -> int:
    """Increment strike count (with decay check). Returns new strike count."""
    pool = await get_pool()
    config = await get_guild_config(guild_id)
    decay_days = config.get("strike_decay_days", 30)
    now_dt = datetime.now(timezone.utc)

    async with pool.acquire() as conn:
        async with conn.transaction():
            # Lock the row for this user so concurrent calls are serialised at DB level
            row = await conn.fetchrow(
                """
                SELECT strike_count, last_strike_at FROM strikes
                WHERE guild_id = $1 AND user_id = $2
                FOR UPDATE
                """,
                guild_id, user_id,
            )
            current_count = (row["strike_count"] if row else 0) or 0
            last_strike_at = row["last_strike_at"] if row else None

            # Decay check — 0 means disabled
            if decay_days > 0 and last_strike_at and current_count > 0:
                try:
                    last_dt = (
                        last_strike_at
                        if last_strike_at.tzinfo
                        else last_strike_at.replace(tzinfo=timezone.utc)
                    )
                    if (now_dt - last_dt).days >= decay_days:
                        current_count = 0
                except Exception:
                    pass

            new_count = current_count + 1

            await conn.execute(
                """
                INSERT INTO strikes (guild_id, user_id, strike_count, last_strike_at)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (guild_id, user_id) DO UPDATE SET
                    strike_count = $3,
                    last_strike_at = $4
                """,
                guild_id, user_id, new_count, now_dt,
            )
            await conn.execute(
                """
                INSERT INTO strike_log (guild_id, user_id, reason, moderator_id, created_at)
                VALUES ($1, $2, $3, $4, $5)
                """,
                guild_id, user_id, reason, moderator_id, now_dt,
            )

    return new_count


async def remove_strike(guild_id: int, user_id: int) -> int:
    """Decrement strike count by 1 (min 0). Returns new count."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "SELECT strike_count FROM strikes WHERE guild_id = $1 AND user_id = $2 FOR UPDATE",
                guild_id, user_id,
            )
            new_count = max(0, ((row["strike_count"] if row else 0) or 0) - 1)
            await conn.execute(
                """
                INSERT INTO strikes (guild_id, user_id, strike_count, last_strike_at)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (guild_id, user_id) DO UPDATE SET strike_count = $3
                """,
                guild_id, user_id, new_count, datetime.now(timezone.utc),
            )
    return new_count


async def reset_strikes(guild_id: int, user_id: int) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                """
                INSERT INTO strikes (guild_id, user_id, strike_count, last_strike_at)
                VALUES ($1, $2, 0, $3)
                ON CONFLICT (guild_id, user_id) DO UPDATE SET strike_count = 0
                """,
                guild_id, user_id, datetime.now(timezone.utc),
            )


async def get_strike_log(guild_id: int, user_id: int, limit: int = 5) -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT * FROM strike_log
            WHERE guild_id = $1 AND user_id = $2
            ORDER BY created_at DESC LIMIT $3
            """,
            guild_id, user_id, limit,
        )
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Whitelist
# ---------------------------------------------------------------------------

async def get_whitelist(guild_id: int) -> list[int]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT role_id FROM whitelist WHERE guild_id = $1", guild_id
        )
    return [r["role_id"] for r in rows]


async def add_whitelist(guild_id: int, role_id: int) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO whitelist (guild_id, role_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
            guild_id, role_id,
        )


async def remove_whitelist(guild_id: int, role_id: int) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM whitelist WHERE guild_id = $1 AND role_id = $2",
            guild_id, role_id,
        )


# ---------------------------------------------------------------------------
# Banned words
# ---------------------------------------------------------------------------

async def get_banned_words(guild_id: int) -> list[str]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT word FROM banned_words WHERE guild_id = $1", guild_id
        )
    return [r["word"] for r in rows]


async def add_banned_word(guild_id: int, word: str) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO banned_words (guild_id, word) VALUES ($1, $2) ON CONFLICT DO NOTHING",
            guild_id, word.lower(),
        )


async def remove_banned_word(guild_id: int, word: str) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM banned_words WHERE guild_id = $1 AND word = $2",
            guild_id, word.lower(),
        )


# ---------------------------------------------------------------------------
# Verification config
# ---------------------------------------------------------------------------

async def get_verification_config(guild_id: int) -> Optional[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM verification_config WHERE guild_id = $1", guild_id
        )
    return dict(row) if row else None


async def set_verification_config(
    guild_id: int,
    channel_id: int,
    unverified_role_id: int,
    verified_role_id: int,
) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO verification_config (guild_id, channel_id, unverified_role_id, verified_role_id)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (guild_id) DO UPDATE SET
                channel_id = $2,
                unverified_role_id = $3,
                verified_role_id = $4
            """,
            guild_id, channel_id, unverified_role_id, verified_role_id,
        )
