"""
Verification cog: button-based member verification gate.
"""

import discord
from discord import app_commands
from discord.ext import commands

import db
import utils


class VerifyButton(discord.ui.View):
    """Persistent view so the button survives bot restarts."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Verify",
        style=discord.ButtonStyle.success,
        custom_id="guard:verify",
        emoji="✅",
    )
    async def verify(self, interaction: discord.Interaction, button: discord.ui.Button):
        member = interaction.user
        if not isinstance(member, discord.Member):
            await interaction.response.send_message("Could not verify — please contact a moderator.", ephemeral=True)
            return

        vcfg = await db.get_verification_config(member.guild.id)
        if not vcfg:
            await interaction.response.send_message("Verification is not configured for this server.", ephemeral=True)
            return

        unverified_role_id = vcfg.get("unverified_role_id")
        verified_role_id = vcfg.get("verified_role_id")

        unverified_role = member.guild.get_role(unverified_role_id) if unverified_role_id else None
        verified_role = member.guild.get_role(verified_role_id) if verified_role_id else None

        try:
            if unverified_role and unverified_role in member.roles:
                await member.remove_roles(unverified_role, reason="Verification passed")
            if verified_role and verified_role not in member.roles:
                await member.add_roles(verified_role, reason="Verification passed")
            await interaction.response.send_message(
                "You have been verified! Welcome to the server.", ephemeral=True
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                "I don't have permission to manage your roles. Please contact a moderator.", ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(f"An error occurred: {e}", ephemeral=True)


class Verification(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Register persistent view so it survives restarts
        self.bot.add_view(VerifyButton())

    @app_commands.command(name="verify-setup", description="Set up the verification gate in a channel.")
    @app_commands.describe(
        channel="Channel to post the verification button in",
        unverified_role="Role given to new members (no permissions except viewing this channel)",
        verified_role="Role granted after verification (default member role)",
    )
    @utils.is_mod()
    async def verify_setup(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        unverified_role: discord.Role,
        verified_role: discord.Role,
    ):
        await interaction.response.defer(ephemeral=True)

        await db.set_verification_config(
            interaction.guild.id,
            channel.id,
            unverified_role.id,
            verified_role.id,
        )

        embed = utils.verification_embed()
        view = VerifyButton()
        try:
            await channel.send(embed=embed, view=view)
        except discord.Forbidden:
            await interaction.followup.send("I don't have permission to send messages in that channel.", ephemeral=True)
            return

        await interaction.followup.send(
            f"Verification gate set up in {channel.mention}.\n"
            f"Unverified role: {unverified_role.mention}\n"
            f"Verified role: {verified_role.mention}",
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Verification(bot))
