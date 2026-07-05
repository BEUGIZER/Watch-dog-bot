"""
Config cog: server configuration and emergency commands.
"""

import discord
from discord import app_commands
from discord.ext import commands
from typing import Optional

import db
import utils

# In-memory store of pre-lockdown state so we can restore accurately
# { guild_id: {"verification_level": ..., "send_messages": bool | None} }
_pre_lockdown_state: dict[int, dict] = {}


class Config(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ------------------------------------------------------------------
    # /config group
    # ------------------------------------------------------------------
    config_group = app_commands.Group(name="config", description="Configure Guard Bot settings.")

    @config_group.command(name="log-channel", description="Set the channel for bot logs.")
    @app_commands.describe(channel="The text channel to send logs to")
    @utils.is_mod()
    async def config_log_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        await db.set_guild_config_field(interaction.guild.id, "log_channel_id", channel.id)
        await interaction.response.send_message(
            f"Log channel set to {channel.mention}.", ephemeral=True
        )

    @config_group.command(name="timeout", description="Set timeout duration for a specific strike number.")
    @app_commands.describe(strike="Strike number (1, 2, or 3)", minutes="Timeout duration in minutes")
    @app_commands.choices(strike=[
        app_commands.Choice(name="Strike 1", value=1),
        app_commands.Choice(name="Strike 2", value=2),
        app_commands.Choice(name="Strike 3", value=3),
    ])
    @utils.is_mod()
    async def config_timeout(self, interaction: discord.Interaction, strike: int, minutes: int):
        if minutes < 1:
            await interaction.response.send_message("Minutes must be at least 1.", ephemeral=True)
            return
        field_map = {1: "timeout_1_minutes", 2: "timeout_2_minutes", 3: "timeout_3_minutes"}
        await db.set_guild_config_field(interaction.guild.id, field_map[strike], minutes)
        await interaction.response.send_message(
            f"Strike {strike} timeout set to **{utils.minutes_to_str(minutes)}**.", ephemeral=True
        )

    @config_group.command(name="strike3-action", description="Set what happens on strike 3.")
    @app_commands.describe(action="Action to take on the 3rd strike")
    @app_commands.choices(action=[
        app_commands.Choice(name="Timeout", value="timeout"),
        app_commands.Choice(name="Kick", value="kick"),
        app_commands.Choice(name="Ban", value="ban"),
    ])
    @utils.is_mod()
    async def config_strike3_action(self, interaction: discord.Interaction, action: str):
        await db.set_guild_config_field(interaction.guild.id, "action_after_strike_3", action)
        await interaction.response.send_message(
            f"Strike 3 action set to **{action}**.", ephemeral=True
        )

    @config_group.command(name="decay", description="Set the number of days before strikes decay.")
    @app_commands.describe(days="Days after which strikes reset (0 to disable decay)")
    @utils.is_mod()
    async def config_decay(self, interaction: discord.Interaction, days: int):
        if days < 0:
            await interaction.response.send_message("Days must be 0 or greater.", ephemeral=True)
            return
        await db.set_guild_config_field(interaction.guild.id, "strike_decay_days", days)
        if days == 0:
            await interaction.response.send_message("Strike decay disabled.", ephemeral=True)
        else:
            await interaction.response.send_message(
                f"Strike decay set to **{days} day{'s' if days != 1 else ''}**.", ephemeral=True
            )

    @config_group.command(name="join-limit", description="Set the anti-raid join rate limit.")
    @app_commands.describe(count="Max joins allowed", window="Time window in seconds")
    @utils.is_mod()
    async def config_join_limit(self, interaction: discord.Interaction, count: int, window: int):
        if count < 2 or window < 5:
            await interaction.response.send_message("Count must be ≥2 and window ≥5 seconds.", ephemeral=True)
            return
        await db.set_guild_config_field(interaction.guild.id, "join_rate_limit", count)
        await db.set_guild_config_field(interaction.guild.id, "join_rate_window_seconds", window)
        await interaction.response.send_message(
            f"Join rate limit set: **{count}** joins in **{window}s** triggers lockdown.", ephemeral=True
        )

    @config_group.command(name="min-account-age", description="Set minimum account age for new members.")
    @app_commands.describe(days="Minimum account age in days to avoid flagging")
    @utils.is_mod()
    async def config_min_account_age(self, interaction: discord.Interaction, days: int):
        if days < 0:
            await interaction.response.send_message("Days must be 0 or greater.", ephemeral=True)
            return
        await db.set_guild_config_field(interaction.guild.id, "min_account_age_days", days)
        await interaction.response.send_message(
            f"Minimum account age set to **{days} day{'s' if days != 1 else ''}**.", ephemeral=True
        )

    # ------------------------------------------------------------------
    # Whitelist
    # ------------------------------------------------------------------
    @app_commands.command(name="whitelist-add", description="Add a role to the moderation whitelist.")
    @app_commands.describe(role="Role to whitelist (exempt from AutoMod and Anti-Nuke)")
    @utils.is_mod()
    async def whitelist_add(self, interaction: discord.Interaction, role: discord.Role):
        await db.add_whitelist(interaction.guild.id, role.id)
        await interaction.response.send_message(
            f"{role.mention} added to the whitelist.", ephemeral=True
        )

    @app_commands.command(name="whitelist-remove", description="Remove a role from the moderation whitelist.")
    @app_commands.describe(role="Role to remove from the whitelist")
    @utils.is_mod()
    async def whitelist_remove(self, interaction: discord.Interaction, role: discord.Role):
        await db.remove_whitelist(interaction.guild.id, role.id)
        await interaction.response.send_message(
            f"{role.mention} removed from the whitelist.", ephemeral=True
        )

    # ------------------------------------------------------------------
    # Banned words
    # ------------------------------------------------------------------
    @app_commands.command(name="bannedword-add", description="Add a word/phrase to the AutoMod block list.")
    @app_commands.describe(word="Word or phrase to block (case-insensitive)")
    @utils.is_mod()
    async def bannedword_add(self, interaction: discord.Interaction, word: str):
        await db.add_banned_word(interaction.guild.id, word)
        await interaction.response.send_message(
            f"Added `{word.lower()}` to the banned word list.", ephemeral=True
        )

    @app_commands.command(name="bannedword-remove", description="Remove a word/phrase from the AutoMod block list.")
    @app_commands.describe(word="Word or phrase to remove")
    @utils.is_mod()
    async def bannedword_remove(self, interaction: discord.Interaction, word: str):
        await db.remove_banned_word(interaction.guild.id, word)
        await interaction.response.send_message(
            f"Removed `{word.lower()}` from the banned word list.", ephemeral=True
        )

    # ------------------------------------------------------------------
    # /lockdown
    # ------------------------------------------------------------------
    @app_commands.command(name="lockdown", description="Manually enable or disable server lockdown.")
    @app_commands.describe(state="on to lock, off to unlock")
    @app_commands.choices(state=[
        app_commands.Choice(name="On", value="on"),
        app_commands.Choice(name="Off", value="off"),
    ])
    @utils.is_mod()
    async def lockdown(self, interaction: discord.Interaction, state: str):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        everyone = guild.default_role

        if state == "on":
            # Snapshot current state before changing anything
            _pre_lockdown_state[guild.id] = {
                "verification_level": guild.verification_level,
                "send_messages": everyone.permissions.send_messages,
            }
            await db.set_guild_config_field(guild.id, "lockdown_enabled", True)
            try:
                await guild.edit(verification_level=discord.VerificationLevel.highest)
            except discord.Forbidden:
                pass
            try:
                perms = discord.Permissions(everyone.permissions.value)
                perms.update(send_messages=False)
                await everyone.edit(permissions=perms, reason="Manual lockdown")
            except Exception:
                pass
            config = await db.get_guild_config(guild.id)
            log_cid = config.get("log_channel_id")
            if log_cid:
                ch = guild.get_channel(log_cid)
                if ch:
                    try:
                        await ch.send(embed=utils.raid_embed(
                            "Manual Lockdown Activated",
                            f"Lockdown enabled by {interaction.user.mention}."
                        ))
                    except Exception:
                        pass
            await interaction.followup.send("Lockdown **enabled**. Server is now restricted.", ephemeral=True)
        else:
            await db.set_guild_config_field(guild.id, "lockdown_enabled", False)
            # Restore pre-lockdown state if available, otherwise use safe defaults
            prior = _pre_lockdown_state.pop(guild.id, None)
            restore_level = prior["verification_level"] if prior else discord.VerificationLevel.low
            restore_send = prior["send_messages"] if prior else True
            try:
                await guild.edit(verification_level=restore_level)
            except discord.Forbidden:
                pass
            try:
                perms = discord.Permissions(everyone.permissions.value)
                perms.update(send_messages=restore_send)
                await everyone.edit(permissions=perms, reason="Lockdown lifted")
            except Exception:
                pass
            await interaction.followup.send("Lockdown **disabled**. Server restored to previous state.", ephemeral=True)

    # ------------------------------------------------------------------
    # /panic
    # ------------------------------------------------------------------
    @app_commands.command(name="panic", description="EMERGENCY: Instant full lockdown and revoke all invites.")
    @utils.is_mod()
    async def panic(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        everyone = guild.default_role

        # Snapshot state before locking (for safe restore later)
        if guild.id not in _pre_lockdown_state:
            _pre_lockdown_state[guild.id] = {
                "verification_level": guild.verification_level,
                "send_messages": everyone.permissions.send_messages,
            }

        # Enable lockdown
        await db.set_guild_config_field(guild.id, "lockdown_enabled", 1)

        try:
            await guild.edit(verification_level=discord.VerificationLevel.highest)
        except Exception:
            pass

        try:
            perms = discord.Permissions(everyone.permissions.value)
            perms.update(send_messages=False)
            await everyone.edit(permissions=perms, reason="PANIC lockdown")
        except Exception:
            pass

        # Revoke all invites
        revoked = 0
        try:
            invites = await guild.invites()
            for invite in invites:
                try:
                    await invite.delete(reason="PANIC: all invites revoked")
                    revoked += 1
                except Exception:
                    pass
        except Exception:
            pass

        # DM owner
        try:
            if guild.owner:
                await guild.owner.send(
                    f"**PANIC activated in {guild.name}** by {interaction.user}\n"
                    f"- Server locked down (verification level: HIGHEST)\n"
                    f"- @everyone send_messages disabled\n"
                    f"- {revoked} invite(s) revoked"
                )
        except Exception:
            pass

        # Log embed
        config = await db.get_guild_config(guild.id)
        log_cid = config.get("log_channel_id")
        if log_cid:
            ch = guild.get_channel(log_cid)
            if ch:
                embed = utils.raid_embed(
                    "PANIC ACTIVATED",
                    f"Full lockdown by {interaction.user.mention}\n"
                    f"- Verification level raised to `HIGHEST`\n"
                    f"- @everyone send_messages disabled\n"
                    f"- **{revoked}** invite(s) revoked",
                )
                try:
                    await ch.send(embed=embed)
                except Exception:
                    pass

        await interaction.followup.send(
            f"PANIC activated. Lockdown enabled. {revoked} invite(s) revoked. Owner notified.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Config(bot))
