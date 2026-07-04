# Discord Guard Bot

A modular Discord security and moderation bot built with **discord.py**. Protects servers from raids, nuke attacks, and spam, and enforces a 3-strike accountability system with escalating timeouts.

---

## Features

| Feature | Description |
|---|---|
| **AutoMod + Strikes** | Scans every message for banned words, scam links, unauthorized invites, spam, and mass mentions. Applies escalating timeouts (or kick/ban) per strike. |
| **Anti-Raid** | Tracks join rate in a rolling window. Auto-lockdown on join floods. Flags accounts younger than the configured minimum age. |
| **Anti-Nuke** | Detects rapid destructive actions (channel/role deletes, bans) by a single moderator. Instantly strips dangerous permissions. |
| **Verification Gate** | `/verify-setup` places a Verify button in a channel. New members get an Unverified role; clicking the button grants access. |
| **Slash Commands** | Full `/strikes`, `/config`, `/whitelist-*`, `/lockdown`, `/panic` command suite. |

---

## Setup

### 1. Create a Discord Bot

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications).
2. Click **New Application** → name it → go to **Bot**.
3. Enable these **Privileged Gateway Intents**:
   - ✅ Server Members Intent
   - ✅ Message Content Intent
4. Copy the **Bot Token** — you'll need it in step 3.

### 2. Invite the Bot

Use the **OAuth2 → URL Generator** with these scopes and permissions:

**Scopes:** `bot`, `applications.commands`

**Bot Permissions:**
- Manage Roles
- Manage Channels
- Kick Members
- Ban Members
- Moderate Members (for timeouts)
- Manage Messages
- Read Message History
- Send Messages
- View Audit Log
- Manage Guild

Or use this permission integer: `1101659695094`

### 3. Set the Bot Token (Replit)

1. In your Repl, go to **Tools → Secrets**.
2. Add a secret:
   - **Key:** `DISCORD_TOKEN`
   - **Value:** your bot token from step 1

> Never hardcode or commit your token. The bot reads it from the `DISCORD_TOKEN` environment variable.

### 4. Run the Bot

The bot runs via the **Guard Bot** workflow in Replit. Click **Run** or start the workflow manually.

For local development, copy `.env.example` to `.env`, fill in your token, and run:
```bash
pip install -r requirements.txt
python main.py
```

---

## Slash Commands

### Strikes
| Command | Description |
|---|---|
| `/strikes @user` | View strike count and recent history |
| `/strike-add @user reason:…` | Manually add a strike |
| `/strike-remove @user` | Remove one strike |
| `/strike-reset @user` | Clear all strikes |

### Config
| Command | Description |
|---|---|
| `/config log-channel #channel` | Set the log channel |
| `/config timeout strike:1\|2\|3 minutes:…` | Set timeout durations |
| `/config strike3-action action:timeout\|kick\|ban` | Set the strike 3 action |
| `/config decay days:…` | Set strike decay in days |
| `/config join-limit count:… window:…` | Set anti-raid join rate |
| `/config min-account-age days:…` | Set new account flag threshold |
| `/bannedword-add word:…` | Add a banned word |
| `/bannedword-remove word:…` | Remove a banned word |
| `/whitelist-add @role` | Exempt a role from moderation |
| `/whitelist-remove @role` | Remove a role from the whitelist |

### Emergency
| Command | Description |
|---|---|
| `/lockdown on\|off` | Manually toggle server lockdown |
| `/panic` | Instant lockdown + revoke all invites + DM owner |

### Verification
| Command | Description |
|---|---|
| `/verify-setup #channel @unverified @verified` | Set up the verification gate |

All mod commands require **Manage Server** or **Administrator** permission.

---

## File Structure

```
main.py              # Bot startup, loads all cogs
cogs/
  automod.py         # Message scanning + strike logic
  antiraid.py        # Join tracking + lockdown
  antinuke.py        # Destructive action tracking
  verification.py    # Verify button/gate
  strikes.py         # Strike slash commands
  config.py          # Config + emergency slash commands
db.py                # Database connection + all queries (aiosqlite)
utils.py             # Shared helpers (embeds, permission checks)
guard.db             # SQLite database (auto-created on first run)
requirements.txt
```

---

## Database

Uses **SQLite** (`guard.db`, auto-created). Stores strikes, strike history, per-guild config, role whitelist, banned words, and verification settings persistently across restarts.

In-memory structures (deques) are used only for short-lived rate-tracking windows (join timestamps, spam detection, anti-nuke action windows).

---

## Keep-Alive (Free Repls)

If you are on a **free Replit plan** (not Reserved VM / Always-On), your Repl will sleep after inactivity. You can add a simple keep-alive by pinging your Repl's URL with an external service like [UptimeRobot](https://uptimerobot.com/). No Flask keep-alive is included by default; a **Reserved VM** deployment keeps the bot running 24/7 without one.
