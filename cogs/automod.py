"""
AutoMod cog: message scanning + strike system.
"""

import re
import asyncio
import discord
from discord.ext import commands
from collections import defaultdict, deque
from datetime import datetime, timezone, timedelta
from typing import Optional

import db
import utils


# ---------------------------------------------------------------------------
# Scam / phishing patterns
# ---------------------------------------------------------------------------
SCAM_PATTERNS = [
    re.compile(r"discord[\-_\.]?nitro", re.I),
    re.compile(r"steamcommunit[yi]", re.I),
    re.compile(r"free[\-_\s]?nitro", re.I),
    re.compile(r"discordapp\.com/gifts", re.I),
    re.compile(r"gift\.discord", re.I),
    re.compile(r"dlscord\.", re.I),
    re.compile(r"discordgift\.", re.I),
    re.compile(r"discord\.gift(?!\.com)", re.I),
    re.compile(r"nitro[\-_\.]?discord", re.I),
    re.compile(r"bit\.ly/\S+nitro", re.I),
    re.compile(r"steamgift\.", re.I),
]

INVITE_PATTERN = re.compile(r"discord(?:\.gg|app\.com/invite|\.com/invite)/(\S+)", re.I)

# Spam tracking: per-guild per-user rolling windows
# { guild_id: { user_id: deque of timestamps } }
_message_times: dict[int, dict[int, deque]] = defaultdict(lambda: defaultdict(deque))
# { guild_id: { user_id: list of (content, timestamp) } }
_recent_content: dict[int, dict[int, list]] = defaultdict(lambda: defaultdict(list))


class AutoMod(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ------------------------------------------------------------------
    # Helper: check if member is whitelisted
    # ------------------------------------------------------------------
    async def _is_whitelisted(self, member: discord.Member) -> bool:
        if member.bot:
            return True
        whitelist = await db.get_whitelist(member.guild.id)
        for role in member.roles:
            if role.id in whitelist:
                return True
        return False

    # ------------------------------------------------------------------
    # Helper: fetch server invite codes for comparison
    # ------------------------------------------------------------------
    async def _get_guild_invite_codes(self, guild: discord.Guild) -> set[str]:
        try:
            invites = await guild.invites()
            return {inv.code for inv in invites}
        except Exception:
            return set()

    # ------------------------------------------------------------------
    # Helper: apply punishment based on strike count
    # ------------------------------------------------------------------
    async def _apply_punishment(
        self,
        member: discord.Member,
        strike_count: int,
        config: dict,
        reason: str,
    ) -> str:
        action_taken = "None"
        try:
            if strike_count == 1:
                minutes = config.get("timeout_1_minutes", 5)
                until = datetime.now(timezone.utc) + timedelta(minutes=minutes)
                await member.timeout(until, reason=reason)
                action_taken = f"Timeout {utils.minutes_to_str(minutes)}"
            elif strike_count == 2:
                minutes = config.get("timeout_2_minutes", 30)
                until = datetime.now(timezone.utc) + timedelta(minutes=minutes)
                await member.timeout(until, reason=reason)
                action_taken = f"Timeout {utils.minutes_to_str(minutes)}"
            elif strike_count >= 3:
                action_type = config.get("action_after_strike_3", "timeout")
                if action_type == "ban":
                    await member.ban(reason=reason)
                    action_taken = "Banned"
                elif action_type == "kick":
                    await member.kick(reason=reason)
                    action_taken = "Kicked"
                else:
                    minutes = config.get("timeout_3_minutes", 1440)
                    until = datetime.now(timezone.utc) + timedelta(minutes=minutes)
                    await member.timeout(until, reason=reason)
                    action_taken = f"Timeout {utils.minutes_to_str(minutes)}"
        except discord.Forbidden:
            action_taken = "Failed (missing permissions)"
        except Exception as e:
            action_taken = f"Failed ({e})"
        return action_taken

    # ------------------------------------------------------------------
    # Helper: DM user about violation
    # ------------------------------------------------------------------
    async def _dm_user(
        self,
        member: discord.Member,
        violation: str,
        strike_count: int,
        action: str,
    ) -> None:
        try:
            await member.send(
                f"**You received a strike in {member.guild.name}**\n"
                f"**Violation:** {violation}\n"
                f"**Strike #{strike_count}**\n"
                f"**Action:** {action}\n\n"
                "Please review the server rules to avoid further penalties."
            )
        except Exception:
            pass  # DMs closed or blocked

    # ------------------------------------------------------------------
    # Helper: post to log channel
    # ------------------------------------------------------------------
    async def _log(
        self,
        guild: discord.Guild,
        config: dict,
        embed: discord.Embed,
    ) -> None:
        log_channel_id = config.get("log_channel_id")
        if not log_channel_id:
            return
        channel = guild.get_channel(log_channel_id)
        if channel:
            try:
                await channel.send(embed=embed)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Helper: process violation (delete, strike, punish, log)
    # ------------------------------------------------------------------
    async def _handle_violation(
        self,
        message: discord.Message,
        violation: str,
    ) -> None:
        member = message.author
        guild = message.guild
        config = await db.get_guild_config(guild.id)

        # Delete message
        try:
            await message.delete()
        except Exception:
            pass

        # Add strike
        strike_count = await db.add_strike(guild.id, member.id, violation)

        # Punish
        action = await self._apply_punishment(member, strike_count, config, violation)

        # DM user
        await self._dm_user(member, violation, strike_count, action)

        # Log embed
        embed = utils.automod_embed(
            member=member,
            violation=violation,
            message_content=message.content or "[no text content]",
            strike_count=strike_count,
            action=action,
        )
        await self._log(guild, config, embed)

    # ------------------------------------------------------------------
    # Main message listener
    # ------------------------------------------------------------------
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.guild is None:
            return
        if await self._is_whitelisted(message.author):
            return
        # Must be a member
        if not isinstance(message.author, discord.Member):
            return

        content = message.content or ""
        guild_id = message.guild.id
        user_id = message.author.id
        now = datetime.now(timezone.utc)

        # 1. Banned words
        banned_words = await db.get_banned_words(guild_id)
        content_lower = content.lower()
        for word in banned_words:
            if word in content_lower:
                await self._handle_violation(message, f"Banned word: `{word}`")
                return

        # 2. Scam / phishing links
        for pattern in SCAM_PATTERNS:
            if pattern.search(content):
                await self._handle_violation(message, "Phishing/scam link detected")
                return

        # 3. Unauthorized Discord invite
        invite_matches = INVITE_PATTERN.findall(content)
        if invite_matches:
            own_codes = await self._get_guild_invite_codes(message.guild)
            for code in invite_matches:
                code_clean = code.split("?")[0].strip()
                if code_clean not in own_codes:
                    await self._handle_violation(message, "Unauthorized Discord invite link")
                    return

        # 4. Mass mentions (5+ users or roles)
        mention_count = len(message.mentions) + len(message.role_mentions)
        if mention_count >= 5:
            await self._handle_violation(message, f"Mass mention ({mention_count} targets)")
            return

        # 5. Spam detection
        guild_times = _message_times[guild_id]
        guild_content = _recent_content[guild_id]

        # Prune old timestamps
        times = guild_times[user_id]
        while times and (now - times[0]).total_seconds() > 10:
            times.popleft()
        times.append(now)

        # 5a. 5+ messages in 3 seconds
        recent_3s = sum(1 for t in times if (now - t).total_seconds() <= 3)
        if recent_3s >= 5:
            await self._handle_violation(message, "Message spam (5+ messages in 3s)")
            return

        # 5b. Same message 3+ times in 5 seconds
        content_list = guild_content[user_id]
        content_list = [(c, t) for c, t in content_list if (now - t).total_seconds() <= 5]
        content_list.append((content, now))
        guild_content[user_id] = content_list
        repeat_count = sum(1 for c, _ in content_list if c == content)
        if repeat_count >= 3 and content.strip():
            await self._handle_violation(message, "Repeated message spam (3+ identical in 5s)")
            return


async def setup(bot: commands.Bot):
    await bot.add_cog(AutoMod(bot))
