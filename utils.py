"""
Shared helpers: embeds, permission checks, formatting.
"""

import discord
from datetime import datetime, timezone
from typing import Optional


# ---------------------------------------------------------------------------
# Colours
# ---------------------------------------------------------------------------
COLOUR_AUTOMOD  = discord.Colour.from_str("#F0A500")   # yellow
COLOUR_ANTIRAID = discord.Colour.from_str("#FF4444")   # red
COLOUR_ANTINUKE = discord.Colour.from_str("#CC0000")   # dark red
COLOUR_INFO     = discord.Colour.from_str("#5865F2")   # blurple
COLOUR_SUCCESS  = discord.Colour.from_str("#57F287")   # green
COLOUR_WARNING  = discord.Colour.from_str("#FEE75C")   # bright yellow


# ---------------------------------------------------------------------------
# Embed builders
# ---------------------------------------------------------------------------

def automod_embed(
    member: discord.Member,
    violation: str,
    message_content: str,
    strike_count: int,
    action: str,
    duration_str: Optional[str] = None,
) -> discord.Embed:
    content_preview = (message_content[:300] + "...") if len(message_content) > 300 else message_content
    embed = discord.Embed(
        title="AutoMod Action",
        colour=COLOUR_AUTOMOD,
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_author(name=str(member), icon_url=member.display_avatar.url)
    embed.add_field(name="User", value=f"{member.mention} (`{member.id}`)", inline=True)
    embed.add_field(name="Violation", value=violation, inline=True)
    embed.add_field(name="Strike Count", value=str(strike_count), inline=True)
    embed.add_field(name="Action", value=action if not duration_str else f"{action} ({duration_str})", inline=True)
    embed.add_field(name="Message", value=f"```{content_preview}```", inline=False)
    return embed


def raid_embed(title: str, description: str) -> discord.Embed:
    embed = discord.Embed(
        title=f"RAID ALERT: {title}",
        description=description,
        colour=COLOUR_ANTIRAID,
        timestamp=datetime.now(timezone.utc),
    )
    return embed


def nuke_embed(actor: discord.Member, actions: list[str]) -> discord.Embed:
    embed = discord.Embed(
        title="ANTI-NUKE: Destructive Activity Detected",
        colour=COLOUR_ANTINUKE,
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_author(name=str(actor), icon_url=actor.display_avatar.url)
    embed.add_field(name="Suspect", value=f"{actor.mention} (`{actor.id}`)", inline=False)
    embed.add_field(name="Actions Detected", value="\n".join(actions) or "None", inline=False)
    embed.add_field(name="Response", value="Dangerous permissions stripped.", inline=False)
    return embed


def verification_embed() -> discord.Embed:
    embed = discord.Embed(
        title="Verification",
        description="Click the button below to verify yourself and gain access to the server.",
        colour=COLOUR_SUCCESS,
    )
    return embed


def new_account_embed(member: discord.Member, age_days: float) -> discord.Embed:
    embed = discord.Embed(
        title="New Account Joined",
        colour=COLOUR_WARNING,
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_author(name=str(member), icon_url=member.display_avatar.url)
    embed.add_field(name="User", value=f"{member.mention} (`{member.id}`)", inline=True)
    embed.add_field(name="Account Age", value=f"{age_days:.1f} days", inline=True)
    embed.add_field(name="Created", value=discord.utils.format_dt(member.created_at, style="R"), inline=True)
    embed.set_footer(text="Flagged: account below minimum age threshold")
    return embed


def strike_info_embed(member: discord.Member, strike_count: int, logs: list[dict]) -> discord.Embed:
    embed = discord.Embed(
        title=f"Strike Info — {member}",
        colour=COLOUR_INFO,
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="Current Strikes", value=str(strike_count), inline=True)
    if logs:
        history = []
        for entry in logs:
            ts = entry.get("created_at", "")
            reason = entry.get("reason", "?")
            mod = f"<@{entry['moderator_id']}>" if entry.get("moderator_id") else "AutoMod"
            history.append(f"• `{ts[:10]}` — {reason} (by {mod})")
        embed.add_field(name="Recent History", value="\n".join(history), inline=False)
    return embed


# ---------------------------------------------------------------------------
# Permission check decorator (used inside cogs)
# ---------------------------------------------------------------------------

def is_mod():
    """Check that the invoker has manage_guild or administrator."""
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.user.guild_permissions.manage_guild or \
                interaction.user.guild_permissions.administrator:
            return True
        await interaction.response.send_message(
            "You need **Manage Server** or **Administrator** permission to use this command.",
            ephemeral=True,
        )
        return False
    return discord.app_commands.check(predicate)


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def minutes_to_str(minutes: int) -> str:
    if minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''}"
    hours = minutes // 60
    rem = minutes % 60
    if rem == 0:
        return f"{hours} hour{'s' if hours != 1 else ''}"
    return f"{hours}h {rem}m"


def safe_truncate(text: str, length: int = 1024) -> str:
    return (text[:length - 3] + "...") if len(text) > length else text


# ---------------------------------------------------------------------------
# Danger permission flags (used by anti-nuke)
# ---------------------------------------------------------------------------

DANGEROUS_PERMS = discord.Permissions(
    administrator=True,
    manage_guild=True,
    manage_channels=True,
    manage_roles=True,
    ban_members=True,
    kick_members=True,
    manage_webhooks=True,
)
