"""
Presence cog — reads presence.json and applies the bot's Discord status/activity.

Edit presence.json to change the bot's appearance, then either:
  • Restart the bot, OR
  • Run /presence-reload (mod-only) to apply changes instantly without a restart.
"""

import json
import os
import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timezone

import utils

PRESENCE_FILE = "presence.json"


def _load() -> dict:
    """Load and return presence.json. Returns safe defaults on any error."""
    try:
        if os.path.exists(PRESENCE_FILE):
            with open(PRESENCE_FILE, encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        print(f"[PRESENCE] Failed to load {PRESENCE_FILE}: {e}")
    return {}


def _build_activity(data: dict) -> discord.BaseActivity | None:
    atype = (data.get("activity_type") or "watching").strip().lower()
    name  = (data.get("activity_name") or "for rule violations").strip()
    url   = (data.get("streaming_url") or "").strip()

    if atype == "playing":
        return discord.Game(name=name)

    if atype == "streaming":
        # Discord only shows the purple LIVE badge for Twitch / YouTube URLs.
        # Falls back to a generic URL so the object is always valid.
        stream_url = url or "https://twitch.tv/discord"
        return discord.Streaming(name=name, url=stream_url)

    if atype == "listening":
        return discord.Activity(type=discord.ActivityType.listening, name=name)

    if atype == "competing":
        return discord.Activity(type=discord.ActivityType.competing, name=name)

    if atype == "custom":
        # Shows as standalone text (what's on your mind).
        # Note: Discord displays custom activities differently for bots —
        # it appears in the member list tooltip and profile popout.
        return discord.CustomActivity(name=name)

    # Default: watching
    return discord.Activity(type=discord.ActivityType.watching, name=name)


def _build_status(data: dict) -> discord.Status:
    mapping = {
        "online":    discord.Status.online,
        "idle":      discord.Status.idle,
        "dnd":       discord.Status.dnd,
        "invisible": discord.Status.invisible,
    }
    return mapping.get((data.get("status") or "online").strip().lower(), discord.Status.online)


class Presence(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _apply(self) -> dict:
        """Load presence.json and push the new presence to Discord. Returns the loaded data."""
        data     = _load()
        activity = _build_activity(data)
        status   = _build_status(data)
        await self.bot.change_presence(status=status, activity=activity)
        return data

    # Apply presence whenever the bot connects / reconnects
    @commands.Cog.listener()
    async def on_ready(self):
        data = await self._apply()
        atype = (data.get("activity_type") or "watching").lower()
        aname = data.get("activity_name") or ""
        print(f"[PRESENCE] Applied — status={data.get('status','online')}  activity={atype}: {aname}")

    # ------------------------------------------------------------------
    # /presence-reload — apply changes from presence.json without restart
    # ------------------------------------------------------------------
    @app_commands.command(
        name="presence-reload",
        description="Reload the bot's status/activity from presence.json (no restart needed).",
    )
    @app_commands.default_permissions(manage_guild=True)
    async def presence_reload(self, interaction: discord.Interaction):
        data = await self._apply()

        atype  = (data.get("activity_type") or "watching").lower()
        aname  = data.get("activity_name") or "—"
        status = (data.get("status") or "online").lower()
        url    = data.get("streaming_url") or ""

        STATUS_ICONS = {
            "online":    "🟢",
            "idle":      "🟡",
            "dnd":       "🔴",
            "invisible": "⚫",
        }
        ACTIVITY_LABELS = {
            "playing":   "Playing",
            "watching":  "Watching",
            "listening": "Listening to",
            "streaming": "🔴 Live —",
            "competing": "Competing in",
            "custom":    "💬",
        }

        icon  = STATUS_ICONS.get(status, "🟢")
        label = ACTIVITY_LABELS.get(atype, "Watching")

        description = (
            f"**Status:** {icon} {status.capitalize()}\n"
            f"**Activity:** {label} **{aname}**"
        )
        if atype == "streaming" and url:
            description += f"\n**Stream URL:** {url}"

        embed = discord.Embed(
            title="✅ Presence Updated",
            description=description,
            colour=utils.COLOUR_SUCCESS,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_footer(text="Edit presence.json and run this command again to change anytime.")
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Presence(bot))
