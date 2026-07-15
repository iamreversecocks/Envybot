# EnvyBot 🛡️

A clean, reliable, and high-performance Discord bot built with **Py-Cord** designed for server moderation, interactive utilities, and user management.

## 🚀 Features

*   **⚡ High-Speed Utilities:** Instantly check bot latency and performance metrics.
*   **🔧 Configurable Prefix:** Set a custom command prefix per server, persisted across restarts.
*   **🛡️ Robust Moderation:** Advanced tools for message purging, kicking, banning, muting/unmuting (timeouts), warning members, and comprehensive unbanning matching (handles raw IDs, Mentions, usernames, and legacy tags).
*   **📝 Moderation & Deletion Logging:** Optionally designate a channel to receive embeds for every mod action (clear/kick/ban/mute/unmute/unban/warn) as well as an automatic log of deleted messages.
*   **📊 Interactive Polls:** Create flexible voting setups supporting up to 10 custom options with automatic emoji reactions, or fallback to simple binary (👍/👎) votes.
*   **⏰ Smart Reminders:** Persistent, database-backed reminder scheduling using relative time strings (e.g., `10m`, `1h30m`) that survive bot restarts.
*   **🔍 Detailed Information Lookups:** Deep-dive inspection embeds for Users, Roles (including complete layout of permissions), and Server configurations.
*   **💬 Slash Command Support:** Every command is registered as a Py-Cord "bridge" command, so it works as both a classic prefixed text command and a native Discord `/slash` command.

---

## 🛠️ Requirements & Installation

### Prerequisites
*   Python 3.8 or higher
*   A Discord Bot Token (via the [Discord Developer Portal](https://discord.com/developers/applications))
*   **Privileged Gateway Intents** enabled in your developer panel:
    *   `Presence Intent` (Optional but recommended)
    *   `Server Members Intent` (Required for info lookups and moderation)
    *   `Message Content Intent` (Required for prefix command routing)

### 1. Clone the Repository
```bash
git clone https://github.com/iamreversecocks/Envybot.git
cd envybot
```

### 2. Install Dependencies
Install the pinned library requirements using pip:
```bash
pip install -r requirements.txt
```

### 3. Environment Configuration
Create a `.env` file in the root directory of your project to securely store your token:
```env
DISCORD_TOKEN=your_secret_bot_token_here
```

### 4. Persistent Storage
On first run, the bot creates the following files alongside the script:
*   `prefixes.json` — tracks any custom prefix set per server.
*   `log_channels.json` — tracks the designated moderation/deletion log channel per server.
*   `reminders.db` — a SQLite database (via `aiosqlite`) storing all pending reminders.

Make sure the bot's working directory is writable, and note that these files need to persist across deploys/restarts (a wipeable filesystem, e.g. some free hosting tiers, will reset all servers back to default prefixes, clear log channel settings, and drop any pending reminders).

---

## 💻 Running the Bot

To start the process, execute the main script:
```bash
python main.py
```

---

## 📜 Command Reference

The default command prefix is `e!`, but it can be changed per server — see `e!setprefix` below. The bot also always responds when mentioned, regardless of the configured prefix. Every command below also works as a native `/slash` command.

| Command | Arguments | Permissions Required | Description |
| :--- | :--- | :--- | :--- |
| `e!cmds` | None | None | Displays a clean help embed containing all active commands, using the server's current prefix. |
| `e!ping` | None | None | Checks the current gateway websocket latency. |
| `e!setprefix` | `[new_prefix]` | **Manage Server** | Sets a custom prefix for this server (5 characters max). Run with no argument to see the current prefix. |
| `e!resetprefix` | None | **Manage Server** | Resets this server's prefix back to the default (`e!`). |
| `e!userinfo` | `[@member]` | None | Displays profile details, creation dates, join dates, and top roles. Defaults to self. |
| `e!serverinfo` | None | None | Renders server context including owner, member metrics, and setup timestamps. |
| `e!roleinfo` | `<@role / name>` | None | Returns role ID, position hierarchy, member distribution, and full permissions. |
| `e!poll` | `"question" ["opts"...]` | None | Launches a tracking poll. Supports binary thumbs or up to 10 custom answers. |
| `e!reminder` (alias `e!remindme`) | `<duration> <message>` | None | Schedules a persistent, database-backed reminder ping (e.g., `e!reminder 2h30m check oven`). Max 30 days. |
| `e!clear` | `[amount]` | **Manage Messages** | Cleans up channel history. Removes target count + command source. Max 100. |
| `e!kick` | `<@member> [reason]` | **Kick Members** | Kicks a specified member from the guild with logging rationale. |
| `e!ban` | `<@member> [reason]` | **Ban Members** | Permanently bans a member from the server. |
| `e!unban` | `<name/id/tag>` | **Ban Members** | Advanced lookup engine to revoke a ban using raw IDs, mentions, or text usernames. |
| `e!mute` | `<@member> <duration> [reason]` | **Moderate Members** | Times out a member for the given duration (e.g., `10m`, `2h`, `1d`). Capped at Discord's 28-day timeout limit. |
| `e!unmute` | `<@member>` | **Moderate Members** | Clears an active timeout on a member. |
| `e!warn` | `<@member> [reason]` | **Moderate Members** | Posts a warning notice to the configured log channel. Not persisted — requires `e!setlogchannel` to be set first. |
| `e!setlogchannel` | `[#channel]` | **Manage Server** | Sets which channel receives moderation-action and message-deletion log embeds. Defaults to the current channel. |
| `e!slowmode` | `[seconds]` | **Manage Channels** | Enables slowmode on the current channel (default 10s, max 21600s/6h). Run again to disable it. |

---

## ⚙️ Architecture Notes

*   **Per-Guild Prefix Resolution:** Prefixes are resolved dynamically per message via a `get_prefix` callable rather than a single static value, keyed off each server's ID and stored in `prefixes.json`. Servers without a custom entry fall back to the default `e!`.
*   **Database-Backed Reminders:** Reminders are written to a `reminders.db` SQLite database (via `aiosqlite`) rather than held in memory, so they survive a bot restart. A background `tasks.loop` polls the table every 10 seconds, fires any reminder whose time has come, and removes it from the database.
*   **Self-Cleaning Mod Loops:** Contextual confirmations (like message totals purged via `e!clear`) automatically delete their tracking messages after a 5-second interval to eliminate administrative layout spam.
*   **Centralized Mod Logging:** If a log channel is configured via `e!setlogchannel` (stored in `log_channels.json`), moderation actions (clear/kick/ban/mute/unmute/unban/warn) post a detailed embed there. Logging is best-effort — if the bot can't post to that channel, it fails silently rather than erroring out the original command.
*   **Deletion Logging:** A `on_message_delete` listener posts an embed to the same configured log channel whenever a non-bot message is deleted, including content/attachments if the message was still in the bot's cache.
*   **Robust Lookups:** The `e!unban` engine parses string sequences dynamically through multi-layer regex evaluations, ensuring high matching precision without relying on local cache stores.

---

## 📄 License

This project is licensed under the **GNU General Public License v3 (GPLv3)**[cite: 4]. 

### Summary of Terms:
*   **Permissions:** You are free to copy, distribute, run, and modify this software for any purpose, including commercial use[cite: 4].
*   **Condition (Copyleft):** If you modify and distribute this software, you must make your modified version's source code available under the same GPLv3 license terms[cite: 4]. You must also clearly mark that you changed the files and include the modification date[cite: 4].
*   **No Warranty:** This software is provided completely "AS IS" without warranty of any kind[cite: 4]. The entire risk regarding performance and quality stays with you[cite: 4].
*   **Liability:** In no event will the copyright holders or authors be liable to you for any damages resulting from the use or inability to use this software[cite: 4].