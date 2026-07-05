"""
Anti-Nuke cog: detect and respond to rapid destructive permission abuse.
"""

import discord
from discord.ext import commands
from collections import defaultdict, deque
from datetime import datetime, timezone, timedelta

import db
import utils

# In-memory: { guild_id: { user_id: deque of (action_type, timestamp) } }
_actor_actions: dict[int, dict[int, deque]] = defaultdict(lambda: defaultdict(deque))

NUKE_WINDOW_SECONDS = 10
NUKE_THRESHOLD = 3


class AntiNuke(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _get_log_channel(self, guild: discord.Guild, config: dict) -> discord.TextChannel | None:
        cid = config.get("log_channel_id")
        if cid:
            return guild.get_channel(cid)
        return None

    async def _dm_owner(self, guild: discord.Guild, message: str) -> None:
        try:
            if guild.owner:
                await guild.owner.send(message)
        except Exception:
            pass

    async def _strip_dangerous_roles(self, member: discord.Member) -> list[str]:
        """Remove roles that carry dangerous permissions from the member."""
        stripped = []
        roles_to_remove = []
        for role in member.roles:
            if role.is_default():
                continue
            perms = role.permissions
            if any([
                perms.administrator,
                perms.manage_guild,
                perms.manage_channels,
                perms.manage_roles,
                perms.ban_members,
                perms.kick_members,
                perms.manage_webhooks,
            ]):
                roles_to_remove.append(role)
                stripped.append(role.name)
        if roles_to_remove:
            try:
                await member.remove_roles(*roles_to_remove, reason="Anti-nuke: dangerous permissions stripped")
            except Exception:
                pass
        return stripped

    async def _record_action(self, guild: discord.Guild, actor_id: int, action_type: str) -> bool:
        """Record action and return True if threshold is exceeded."""
        whitelist = await db.get_whitelist(guild.id)

        # Check if actor is whitelisted
        member = guild.get_member(actor_id)
        if member:
            if member.bot:
                return False
            for role in member.roles:
                if role.id in whitelist:
                    return False

        now = datetime.now(timezone.utc)
        actions = _actor_actions[guild.id][actor_id]

        # Prune old
        while actions and (now - actions[0][1]).total_seconds() > NUKE_WINDOW_SECONDS:
            actions.popleft()

        actions.append((action_type, now))

        return len(actions) >= NUKE_THRESHOLD

    async def _handle_nuke_attempt(self, guild: discord.Guild, actor_id: int) -> None:
        config = await db.get_guild_config(guild.id)
        member = guild.get_member(actor_id)

        actions = _actor_actions[guild.id][actor_id]
        action_list = [f"`{a[0]}`" for a in actions]

        stripped = []
        if member:
            stripped = await self._strip_dangerous_roles(member)

        # DM owner
        owner_msg = (
            f"**ANTI-NUKE ALERT in {guild.name}**\n"
            f"User: {member} (`{actor_id}`)\n"
            f"Rapid destructive actions detected: {', '.join(action_list)}\n"
            f"Roles stripped: {', '.join(stripped) if stripped else 'None'}"
        )
        await self._dm_owner(guild, owner_msg)

        # Log embed
        log_channel = await self._get_log_channel(guild, config)
        if log_channel and member:
            embed = utils.nuke_embed(member, action_list)
            if stripped:
                embed.add_field(name="Roles Stripped", value=", ".join(stripped) or "None", inline=False)
            try:
                await log_channel.send(embed=embed)
            except Exception:
                pass

        # Clear actions to prevent re-trigger
        _actor_actions[guild.id][actor_id].clear()

    async def _find_actor(
        self,
        guild: discord.Guild,
        action: discord.AuditLogAction,
        target_id: int,
    ) -> int | None:
        """
        Look through recent audit log entries (up to 5) for the given action,
        matching on target ID and a 15-second recency window.
        Returns the actor's user ID, or None if no valid match found.
        """
        now = datetime.now(timezone.utc)
        try:
            async for entry in guild.audit_logs(limit=5, action=action):
                # Recency guard: ignore stale entries
                age = (now - entry.created_at.replace(tzinfo=timezone.utc)).total_seconds()
                if age > 15:
                    break
                # Target match: entry.target is the deleted object
                entry_target_id = getattr(entry.target, "id", None)
                if entry_target_id != target_id:
                    continue
                if entry.user and entry.user.id != self.bot.user.id:
                    return entry.user.id
        except discord.Forbidden:
            pass
        except Exception:
            pass
        return None

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel):
        guild = channel.guild
        actor_id = await self._find_actor(guild, discord.AuditLogAction.channel_delete, channel.id)
        if actor_id:
            triggered = await self._record_action(guild, actor_id, f"channel_delete:{channel.name}")
            if triggered:
                await self._handle_nuke_attempt(guild, actor_id)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        guild = role.guild
        actor_id = await self._find_actor(guild, discord.AuditLogAction.role_delete, role.id)
        if actor_id:
            triggered = await self._record_action(guild, actor_id, f"role_delete:{role.name}")
            if triggered:
                await self._handle_nuke_attempt(guild, actor_id)

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User):
        actor_id = await self._find_actor(guild, discord.AuditLogAction.ban, user.id)
        if actor_id:
            triggered = await self._record_action(guild, actor_id, f"ban:{user.name}")
            if triggered:
                await self._handle_nuke_attempt(guild, actor_id)


async def setup(bot: commands.Bot):
    await bot.add_cog(AntiNuke(bot))
