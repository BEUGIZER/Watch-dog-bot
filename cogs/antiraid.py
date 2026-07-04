"""
Anti-Raid cog: mass join detection and lockdown.
"""

import discord
from discord.ext import commands
from collections import defaultdict, deque
from datetime import datetime, timezone, timedelta

import db
import utils


# In-memory: { guild_id: deque of join timestamps }
_join_times: dict[int, deque] = defaultdict(deque)


class AntiRaid(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _get_log_channel(self, guild: discord.Guild, config: dict) -> discord.TextChannel | None:
        cid = config.get("log_channel_id")
        if cid:
            return guild.get_channel(cid)
        return None

    async def _apply_lockdown(self, guild: discord.Guild, config: dict) -> None:
        """Set lockdown in DB and restrict the server."""
        await db.set_guild_config_field(guild.id, "lockdown_enabled", 1)

        # Try raising verification level
        try:
            await guild.edit(verification_level=discord.VerificationLevel.highest)
        except discord.Forbidden:
            pass

        # Also restrict @everyone from sending messages as a belt-and-suspenders fallback
        everyone = guild.default_role
        try:
            current_perms = everyone.permissions
            new_perms = discord.Permissions(current_perms.value)
            new_perms.update(send_messages=False)
            await everyone.edit(permissions=new_perms, reason="Anti-raid lockdown")
        except Exception:
            pass

    async def _dm_owner(self, guild: discord.Guild, message: str) -> None:
        try:
            owner = guild.owner
            if owner:
                await owner.send(message)
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        guild = member.guild
        config = await db.get_guild_config(guild.id)
        now = datetime.now(timezone.utc)

        # ----- Account age check -----
        min_age = config.get("min_account_age_days", 7)
        account_age = (now - member.created_at.replace(tzinfo=timezone.utc)).total_seconds() / 86400
        if account_age < min_age:
            log_channel = await self._get_log_channel(guild, config)
            if log_channel:
                embed = utils.new_account_embed(member, account_age)
                try:
                    await log_channel.send(embed=embed)
                except Exception:
                    pass

        # ----- Assign Unverified role if verification is configured -----
        vcfg = await db.get_verification_config(guild.id)
        if vcfg and vcfg.get("unverified_role_id"):
            unverified_role = guild.get_role(vcfg["unverified_role_id"])
            if unverified_role:
                try:
                    await member.add_roles(unverified_role, reason="Verification gate")
                except Exception:
                    pass

        # ----- Join rate tracking -----
        rate_limit = config.get("join_rate_limit", 5)
        rate_window = config.get("join_rate_window_seconds", 10)

        times = _join_times[guild.id]
        # Prune old timestamps
        while times and (now - times[0]).total_seconds() > rate_window:
            times.popleft()
        times.append(now)

        if len(times) >= rate_limit:
            # Check if already locked
            if not config.get("lockdown_enabled"):
                await self._apply_lockdown(guild, config)

                alert = (
                    f"**RAID ALERT** in **{guild.name}**\n"
                    f"{len(times)} members joined within {rate_window}s.\n"
                    "Lockdown has been automatically activated."
                )

                log_channel = await self._get_log_channel(guild, config)
                if log_channel:
                    embed = utils.raid_embed(
                        "Mass Join Detected",
                        f"{len(times)} members joined within **{rate_window}s**.\n"
                        "Lockdown activated: verification level raised to `HIGHEST` and @everyone send_messages restricted.",
                    )
                    try:
                        await log_channel.send(embed=embed)
                    except Exception:
                        pass

                await self._dm_owner(guild, alert)


async def setup(bot: commands.Bot):
    await bot.add_cog(AntiRaid(bot))
