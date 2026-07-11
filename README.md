# EnvyBot 🛡️

A clean, reliable, and high-performance Discord bot built with **Py-Cord** designed for server moderation, interactive utilities, and user management.

## 🚀 Features

*   **⚡ High-Speed Utilities:** Instantly check bot latency and performance metrics.
*   **🛡️ Robust Moderation:** Advanced tools for message purging, kicking, banning, and comprehensive unbanning matching (handles raw IDs, Mentions, usernames, and legacy tags).
*   **📊 Interactive Polls:** Create flexible voting setups supporting up to 10 custom options with automatic emoji reactions, or fallback to simple binary (👍/👎) votes.
*   **⏰ Smart Reminders:** Background task scheduling using asynchronous relative time strings (e.g., `10m`, `1h30m`) that run concurrently without blocking bot processes.
*   **🔍 Detailed Information Lookups:** Deep-dive inspection embeds for Users, Roles (including complete layout of permissions), and Server configurations.

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

---

## 💻 Running the Bot

To start the process, execute the main script:
```bash
python main.py
```

---

## 📜 Command Reference

The default command prefix is `e!`.

| Command | Arguments | Permissions Required | Description |
| :--- | :--- | :--- | :--- |
| `e!cmds` | None | None | Displays a clean help embed containing all active commands. |
| `e!ping` | None | None | Checks the current gateway websocket latency. |
| `e!userinfo` | `[@member]` | None | Displays profile details, creation dates, join dates, and top roles. Defaults to self. |
| `e!serverinfo` | None | None | Renders server context including owner, member metrics, and setup timestamps. |
| `e!roleinfo` | `<@role / name>` | None | Returns role ID, position hierarchy, member distribution, and full permissions. |
| `e!poll` | `"question" ["opts"...]` | None | Launches a tracking poll. Supports binary thumbs or up to 10 custom answers. |
| `e!reminder` | `<duration> <message>` | None | Schedules an asynchronous reminder ping (e.g., `e!reminder 2h30m check oven`). Max 30 days. |
| `e!clear` | `[amount]` | **Manage Messages** | Cleans up channel history. Removes target count + command source. Max 100. |
| `e!kick` | `<@member> [reason]` | **Kick Members** | Kicks a specified member from the guild with logging rationale. |
| `e!ban` | `<@member> [reason]` | **Ban Members** | Permanently bans a member from the server. |
| `e!unban` | `<name/id/tag>` | **Ban Members** | Advanced lookup engine to revoke a ban using raw IDs, mentions, or text usernames. |

---

## ⚙️ Architecture Notes

*   **Asynchronous Tasks:** The reminder tracking module leverages `asyncio.sleep` running natively within the `bot.loop` context. This avoids blocking active event handling queues across concurrent guilds.
*   **Self-Cleaning Mod Loops:** Contextual confirmations (like message totals purged via `e!clear`) automatically delete their tracking messages after a 5-second interval to eliminate administrative layout spam.
*   **Robust Lookups:** The `e!unban` engine parses string sequences dynamically through multi-layer regex evaluations, ensuring high matching precision without relying on local cache stores.

---

## 📄 License

This project is licensed under the **GNU General Public License v3 (GPLv3)**[cite: 4]. 

### Summary of Terms:
*   **Permissions:** You are free to copy, distribute, run, and modify this software for any purpose, including commercial use[cite: 4].
*   **Condition (Copyleft):** If you modify and distribute this software, you must make your modified version's source code available under the same GPLv3 license terms[cite: 4]. You must also clearly mark that you changed the files and include the modification date[cite: 4].
*   **No Warranty:** This software is provided completely "AS IS" without warranty of any kind[cite: 4]. The entire risk regarding performance and quality stays with you[cite: 4].
*   **Liability:** In no event will the copyright holders or authors be liable to you for any damages resulting from the use or inability to use this software[cite: 4].
