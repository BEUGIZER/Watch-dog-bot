"""
Discord Guard Bot — main entry point.
Loads all cogs and starts the bot.
"""

import os
import asyncio
import discord
from discord.ext import commands

import db

TOKEN = os.environ.get("DISCORD_TOKEN")

COGS = [
    "cogs.automod",
    "cogs.antiraid",
    "cogs.antinuke",
    "cogs.verification",
    "cogs.strikes",
    "cogs.config",
]


class GuardBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        intents.moderation = True

        super().__init__(
            command_prefix="!guard ",  # prefix commands not used, but required
            intents=intents,
            help_command=None,
        )

    async def setup_hook(self):
        # Initialise database
        await db.get_db()
        print("[DB] Database initialised.")

        # Load cogs
        for cog in COGS:
            try:
                await self.load_extension(cog)
                print(f"[COG] Loaded: {cog}")
            except Exception as e:
                print(f"[COG] Failed to load {cog}: {e}")

        # Sync application commands globally
        try:
            synced = await self.tree.sync()
            print(f"[SYNC] Synced {len(synced)} slash command(s).")
        except Exception as e:
            print(f"[SYNC] Failed to sync commands: {e}")

    async def on_ready(self):
        print(f"[READY] Logged in as {self.user} (ID: {self.user.id})")
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="for rule violations",
            )
        )

    async def close(self):
        await db.close_db()
        await super().close()


async def main():
    if not TOKEN:
        print(
            "[ERROR] DISCORD_TOKEN is not set.\n"
            "Add it as a Replit Secret: Tools → Secrets → DISCORD_TOKEN"
        )
        return

    bot = GuardBot()
    async with bot:
        await bot.start(TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
