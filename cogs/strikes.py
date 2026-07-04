"""
Strikes cog: slash commands for viewing and managing member strikes.
"""

import discord
from discord import app_commands
from discord.ext import commands

import db
import utils


class Strikes(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="strikes", description="Show a user's current strike count and recent history.")
    @app_commands.describe(user="The member to look up")
    @utils.is_mod()
    async def strikes(self, interaction: discord.Interaction, user: discord.Member):
        row = await db.get_strikes(interaction.guild.id, user.id)
        logs = await db.get_strike_log(interaction.guild.id, user.id, limit=5)
        embed = utils.strike_info_embed(user, row.get("strike_count", 0), logs)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="strike-add", description="Manually add a strike to a user.")
    @app_commands.describe(user="The member to strike", reason="Reason for the strike")
    @utils.is_mod()
    async def strike_add(self, interaction: discord.Interaction, user: discord.Member, reason: str):
        await interaction.response.defer(ephemeral=True)

        new_count = await db.add_strike(
            interaction.guild.id,
            user.id,
            reason,
            moderator_id=interaction.user.id,
        )

        config = await db.get_guild_config(interaction.guild.id)

        # Apply punishment
        cog = self.bot.cogs.get("AutoMod")
        if cog:
            action = await cog._apply_punishment(user, new_count, config, reason)
        else:
            action = "No punishment applied (AutoMod cog not loaded)"

        # DM user
        try:
            await user.send(
                f"**You received a manual strike in {interaction.guild.name}**\n"
                f"**Reason:** {reason}\n"
                f"**Strike #{new_count}**\n"
                f"**Action:** {action}"
            )
        except Exception:
            pass

        # Log
        log_channel_id = config.get("log_channel_id")
        if log_channel_id:
            channel = interaction.guild.get_channel(log_channel_id)
            if channel:
                embed = discord.Embed(
                    title="Manual Strike Added",
                    colour=utils.COLOUR_AUTOMOD,
                )
                embed.add_field(name="User", value=f"{user.mention} (`{user.id}`)", inline=True)
                embed.add_field(name="Moderator", value=interaction.user.mention, inline=True)
                embed.add_field(name="Strike #", value=str(new_count), inline=True)
                embed.add_field(name="Reason", value=reason, inline=False)
                embed.add_field(name="Action", value=action, inline=False)
                try:
                    await channel.send(embed=embed)
                except Exception:
                    pass

        await interaction.followup.send(
            f"Strike added to {user.mention}. They now have **{new_count}** strike(s). Action: {action}",
            ephemeral=True,
        )

    @app_commands.command(name="strike-remove", description="Remove one strike from a user.")
    @app_commands.describe(user="The member to remove a strike from")
    @utils.is_mod()
    async def strike_remove(self, interaction: discord.Interaction, user: discord.Member):
        new_count = await db.remove_strike(interaction.guild.id, user.id)
        await interaction.response.send_message(
            f"Removed one strike from {user.mention}. They now have **{new_count}** strike(s).",
            ephemeral=True,
        )

    @app_commands.command(name="strike-reset", description="Clear all strikes from a user.")
    @app_commands.describe(user="The member to reset strikes for")
    @utils.is_mod()
    async def strike_reset(self, interaction: discord.Interaction, user: discord.Member):
        await db.reset_strikes(interaction.guild.id, user.id)
        await interaction.response.send_message(
            f"All strikes cleared for {user.mention}.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Strikes(bot))
