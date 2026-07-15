import asyncio
import os
import re
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiosqlite
import discord
from discord.ext import bridge, commands, tasks
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).parent / ".env")
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN not found in the .env file")

DEFAULT_PREFIX = "e!"
DB_FILE = Path(__file__).parent / "reminders.db"

# Guild Caches
prefixes = {}
log_channels = {}


def get_prefix(bot_, message):
    if not message.guild:
        return commands.when_mentioned_or(DEFAULT_PREFIX)(bot_, message)
    p = prefixes.get(str(message.guild.id), DEFAULT_PREFIX)
    return commands.when_mentioned_or(p)(bot_, message)


intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = bridge.Bot(command_prefix=get_prefix, intents=intents)


SPAM_WINDOW_SECONDS = 6
SPAM_MESSAGE_THRESHOLD = 5
SPAM_MUTE_SECONDS = 60
recent_messages = defaultdict(
    deque
)  # NOTE: stores message timestamps per member {member_id: deque([timestamps])}


WARN_MUTE_THRESHOLD = 3
WARN_MUTE_SECONDS = 600


@bot.bridge_command(name="ping")
async def ping(ctx):
    latency_ms = round(bot.latency * 1000)
    await ctx.respond(f"pong! {latency_ms}ms")


@bot.bridge_command(name="setprefix")
@commands.has_permissions(manage_guild=True)
async def setprefix(ctx, new_prefix: str = None):
    if new_prefix is None:
        cur = prefixes.get(str(ctx.guild.id), DEFAULT_PREFIX)
        await ctx.respond(
            f"prefix is currently `{cur}`, do `{cur}setprefix <new>` to change it"
        )
        return

    if len(new_prefix) > 5:
        await ctx.respond("5 chars max")
        return

    prefixes[str(ctx.guild.id)] = new_prefix
    await upsert_guild_setting(ctx.guild.id, prefix=new_prefix)
    await ctx.respond(f"prefix is now `{new_prefix}`")


@bot.bridge_command(name="resetprefix")
@commands.has_permissions(manage_guild=True)
async def resetprefix(ctx):
    prefixes.pop(str(ctx.guild.id), None)
    await clear_guild_prefix(ctx.guild.id)
    await ctx.respond(f"back to default (`{DEFAULT_PREFIX}`)")


def get_log_channel(ctx):
    log_channel_id = log_channels.get(str(ctx.guild.id))
    if log_channel_id is None:
        return None
    return ctx.guild.get_channel(log_channel_id)


async def post_mod_log(ctx, *, title, color, fields):
    channel = get_log_channel(ctx)
    if channel is None:
        return

    embed = discord.Embed(title=title, color=color)
    for name, value in fields:
        embed.add_field(name=name, value=value, inline=False)
    embed.set_footer(text=f"Action by {ctx.author}")
    embed.timestamp = discord.utils.utcnow()

    try:
        await channel.send(embed=embed)
    except discord.Forbidden:
        pass


@bot.bridge_command(name="clear")
@commands.has_permissions(manage_messages=True)
async def clear(ctx, amount: int = 5):
    if amount > 100:
        amount = 100

    if ctx.is_app:
        deleted = await ctx.channel.purge(limit=amount)
        await ctx.respond(
            f"Deleted {len(deleted)} messages.", ephemeral=True, delete_after=5
        )
    else:
        deleted = await ctx.channel.purge(limit=amount + 1)
        msg = await ctx.channel.send(f"Deleted {len(deleted) - 1} messages.")
        await msg.delete(delay=5)

    await post_mod_log(
        ctx,
        title="Messages Cleared",
        color=0x99AAB5,
        fields=[
            ("Channel", ctx.channel.mention),
            ("Amount", str(amount)),
            ("Cleared by", ctx.author.mention),
        ],
    )


@bot.bridge_command(name="kick")
@commands.has_permissions(kick_members=True)
async def kick(ctx, member: discord.Member, *, reason="No reason provided"):
    if member == ctx.author:
        await ctx.respond("I refuse")
        return
    try:
        await member.kick(reason=reason)
        await ctx.respond(f"kicked {member.mention}. Reason: {reason}")
    except discord.Forbidden:
        await ctx.respond("no perms to kick that user")
        return

    await post_mod_log(
        ctx,
        title="Member Kicked",
        color=0xFF9900,
        fields=[
            ("Member", f"{member.mention} ({member})"),
            ("Kicked by", ctx.author.mention),
            ("Reason", reason),
        ],
    )


@bot.bridge_command(name="ban")
@commands.has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, *, reason="No reason provided"):
    try:
        await member.ban(reason=reason, delete_message_seconds=0)
        await ctx.respond(f"banned {member.mention}. Reason: {reason}")
    except discord.Forbidden:
        await ctx.respond("no perms to ban that user")
        return

    await post_mod_log(
        ctx,
        title="Member Banned",
        color=0xFF0000,
        fields=[
            ("Member", f"{member.mention} ({member})"),
            ("Banned by", ctx.author.mention),
            ("Reason", reason),
        ],
    )


@bot.bridge_command(name="mute")
@commands.has_permissions(moderate_members=True)
async def mute(
    ctx, member: discord.Member, duration: str, *, reason="No reason provided"
):
    if member == ctx.author:
        await ctx.respond("I refuse")
        return

    seconds = parse_duration(duration)
    if not seconds:
        await ctx.respond("couldn't parse that, try `10m` or `1h30m`")
        return
    if seconds > 2419200:
        seconds = 2419200

    try:
        until = discord.utils.utcnow() + timedelta(seconds=seconds)
        await member.timeout(until, reason=reason)
        await ctx.respond(f"Muted {member.mention} for {duration}. Reason: {reason}")
    except discord.Forbidden:
        await ctx.respond("No perms to timeout that user")
        return

    await post_mod_log(
        ctx,
        title="Member Muted",
        color=0xFFCC00,
        fields=[
            ("Member", f"{member.mention} ({member})"),
            ("Duration", duration),
            ("Muted by", ctx.author.mention),
            ("Reason", reason),
        ],
    )


@bot.bridge_command(name="unmute")
@commands.has_permissions(moderate_members=True)
async def unmute(ctx, member: discord.Member):
    try:
        await member.timeout(None, reason=f"Unmuted by {ctx.author}")
        await ctx.respond(f"Unmuted {member.mention}.")
    except discord.Forbidden:
        await ctx.respond("No perms to unmute that user")
        return

    await post_mod_log(
        ctx,
        title="Member Unmuted",
        color=0x00CC66,
        fields=[
            ("Member", f"{member.mention} ({member})"),
            ("Unmuted by", ctx.author.mention),
        ],
    )


@bot.bridge_command(name="unban")  # TODO: Optimize this
@commands.has_permissions(ban_members=True)
async def unban(ctx, *, user: str):
    banned = [entry async for entry in ctx.guild.bans()]
    user = user.strip()

    match = None
    mention_match = re.match(r"<@!?(\d+)>$", user)

    if mention_match:
        uid = int(mention_match.group(1))
        for entry in banned:
            if entry.user.id == uid:
                match = entry
                break
    elif user.isdigit():
        uid = int(user)
        for entry in banned:
            if entry.user.id == uid:
                match = entry
                break
    elif "#" in user:
        name, disc = user.rsplit("#", 1)
        for entry in banned:
            if entry.user.name == name and entry.user.discriminator == disc:
                match = entry
                break
    else:
        for entry in banned:
            if entry.user.name.lower() == user.lower():
                match = entry
                break

    if match is None:
        await ctx.respond(f"couldn't find `{user}` in the ban list")
        return

    await ctx.guild.unban(match.user, reason=f"Unbanned by {ctx.author}")
    await ctx.respond(f"Unbanned {match.user}.")

    await post_mod_log(
        ctx,
        title="Member Unbanned",
        color=0x00CC66,
        fields=[
            ("Member", str(match.user)),
            ("Unbanned by", ctx.author.mention),
        ],
    )


@bot.bridge_command(name="userinfo")
async def userinfo(ctx, member: discord.Member = None):
    member = member or ctx.author

    embed = discord.Embed(title=f"{member.display_name}'s Details", color=0x00AAFF)
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="Tag", value=str(member), inline=True)
    embed.add_field(
        name="Account Created",
        value=member.created_at.strftime("%b %d, %Y"),
        inline=True,
    )
    embed.add_field(
        name="Joined Server", value=member.joined_at.strftime("%b %d, %Y"), inline=True
    )

    roles = [r.name for r in member.roles if r.name != "@everyone"]
    embed.add_field(
        name="Roles", value=", ".join(roles[:5]) if roles else "None", inline=False
    )

    await ctx.respond(embed=embed)


@bot.bridge_command(name="serverinfo")
async def serverinfo(ctx):
    guild = ctx.guild
    embed = discord.Embed(title=guild.name, color=0xFFAA00)

    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)

    embed.add_field(
        name="Owner",
        value=guild.owner.mention if guild.owner else "unknown",
        inline=True,
    )
    embed.add_field(name="Members", value=str(guild.member_count), inline=True)
    embed.add_field(
        name="Created", value=guild.created_at.strftime("%b %d, %Y"), inline=False
    )
    embed.set_footer(text=f"ID: {guild.id}")
    await ctx.respond(embed=embed)


@bot.bridge_command(name="roleinfo")
async def roleinfo(ctx, *, role: discord.Role):
    embed = discord.Embed(title=role.name, color=role.color)
    embed.add_field(name="ID", value=str(role.id))
    embed.add_field(name="Members", value=str(len(role.members)))
    embed.add_field(name="Position", value=str(role.position))
    embed.add_field(name="Mentionable", value=str(role.mentionable))

    if role.permissions.administrator:
        perms = "Administrator"
    else:
        perms = ", ".join(
            p.replace("_", " ").title() for p, val in role.permissions if val
        )
        if not perms:
            perms = "None"

    embed.add_field(name="Permissions", value=perms[:1000], inline=False)
    await ctx.respond(embed=embed)


@bot.bridge_command(name="setlogchannel")
@commands.has_permissions(manage_guild=True)
async def setlogchannel(ctx, channel: discord.TextChannel = None):
    channel = channel or ctx.channel
    log_channels[str(ctx.guild.id)] = channel.id
    await upsert_guild_setting(ctx.guild.id, log_channel_id=channel.id)
    await ctx.respond(f"modlogs will be posted in {channel.mention}")


@bot.bridge_command(name="warn")
@commands.has_permissions(moderate_members=True)
async def warn(ctx, member: discord.Member, *, reason="No reason provided"):
    log_channel = get_log_channel(ctx)
    if not log_channel:
        return await ctx.respond("no log channel set use {prefix}setlogchannel")

    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute(
            """INSERT INTO warnings (guild_id, user_id, moderator_id, reason, created_at) 
               VALUES (?, ?, ?, ?, ?)""",
            (
                ctx.guild.id,
                member.id,
                ctx.author.id,
                reason,
                discord.utils.utcnow().timestamp(),
            ),
        )
        await db.commit()

        async with db.execute(
            "SELECT COUNT(*) FROM warnings WHERE guild_id = ? AND user_id = ?",
            (ctx.guild.id, member.id),
        ) as cursor:
            (warning_count,) = await cursor.fetchone()

    await post_mod_log(
        ctx,
        title="user Warned",
        color=0xFFCC00,
        fields=[
            ("user", f"{member.mention} ({member})"),
            ("Warned by", ctx.author.mention),
            ("Reason", reason),
            ("Total Warnings", str(warning_count)),
        ],
    )

    response = f"warned {member.mention} ({warning_count} total)."

    if warning_count >= WARN_MUTE_THRESHOLD and member != ctx.author:
        try:
            until = discord.utils.utcnow() + timedelta(seconds=WARN_MUTE_SECONDS)
            await member.timeout(
                until, reason=f"Auto-mute: reached {warning_count} warnings"
            )

            response += f"\nAuto-muted for {WARN_MUTE_SECONDS // 60}m."
            await post_mod_log(
                ctx,
                title="user automuted",
                color=0xFF6600,
                fields=[
                    ("user", f"{member.mention} ({member})"),
                    ("Reason", f"Reached {warning_count} warnings"),
                ],
            )
        except discord.Forbidden:
            response += "\n*failed to automute check perms.*"

    await ctx.respond(response)


@bot.bridge_command(name="warnings")
@commands.has_permissions(moderate_members=True)
async def warnings_cmd(ctx, member: discord.Member):
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT id, moderator_id, reason, created_at FROM warnings "
            "WHERE guild_id = ? AND user_id = ? ORDER BY created_at DESC LIMIT 10",
            (ctx.guild.id, member.id),
        ) as cursor:
            rows = await cursor.fetchall()

    if not rows:
        await ctx.respond(f"{member.mention} has no warnings.")
        return

    embed = discord.Embed(title=f"Warnings for {member}", color=0xFFCC00)
    for row in rows:
        mod = ctx.guild.get_member(row["moderator_id"])
        mod_name = mod.mention if mod else f"<@{row['moderator_id']}>"
        when = discord.utils.format_dt(
            datetime.fromtimestamp(row["created_at"], tz=timezone.utc), style="R"
        )
        embed.add_field(
            name=f"#{row['id']} — {when}",
            value=f"By {mod_name}: {row['reason']}",
            inline=False,
        )
    await ctx.respond(embed=embed)


@bot.bridge_command(name="delwarning")
@commands.has_permissions(manage_guild=True)
async def delwarning(ctx, warning_id: int):
    async with aiosqlite.connect(DB_FILE) as db:
        cursor = await db.execute(
            "DELETE FROM warnings WHERE id = ? AND guild_id = ?",
            (warning_id, ctx.guild.id),
        )
        await db.commit()

    if cursor.rowcount == 0:
        await ctx.respond(f"no warning with id `{warning_id}` in this server")
        return

    await ctx.respond(f"Deleted warning `{warning_id}`.")


@bot.bridge_command(name="slowmode")
@commands.has_permissions(manage_channels=True)
async def slowmode(ctx, seconds: int = 10):
    channel = ctx.channel

    # toggle off if it's already on
    if channel.slowmode_delay > 0:
        await channel.edit(slowmode_delay=0)
        await ctx.respond("Slowmode disabled.")
        return

    seconds = max(0, min(seconds, 21600))  # max
    await channel.edit(slowmode_delay=seconds)
    await ctx.respond(f"Slowmode set to {seconds}s. Run again to disable.")


NUMBERS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]


@bot.bridge_command(name="poll")
@commands.cooldown(1, 15, commands.BucketType.user)
async def poll(
    ctx,
    question: str,
    opt1: str = None,
    opt2: str = None,
    opt3: str = None,
    opt4: str = None,
    opt5: str = None,
    opt6: str = None,
    opt7: str = None,
    opt8: str = None,
    opt9: str = None,
    opt10: str = None,
):
    options = [
        o for o in (opt1, opt2, opt3, opt4, opt5, opt6, opt7, opt8, opt9, opt10) if o
    ]

    if not options:
        embed = discord.Embed(title=question, color=0x5865F2)
        msg = await ctx.respond(embed=embed)
        await msg.add_reaction("👍")
        await msg.add_reaction("👎")
        return

    desc = ""
    for i, opt in enumerate(options):
        desc += f"{NUMBERS[i]} {opt}\n"

    embed = discord.Embed(title=question, description=desc, color=0x5865F2)
    msg = await ctx.respond(embed=embed)
    for i in range(len(options)):
        await msg.add_reaction(NUMBERS[i])


DURATION_RE = re.compile(r"(\d+)([smhd])")
UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def parse_duration(text):
    matches = DURATION_RE.findall(text.lower())
    if not matches:
        return None

    total = 0
    for num, unit in matches:
        total += int(num) * UNITS[unit]
    return total


async def init_db():
    """Create all tables if they don't already exist."""
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                fire_at REAL NOT NULL,
                message TEXT NOT NULL
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS guild_settings (
                guild_id INTEGER PRIMARY KEY,
                prefix TEXT,
                log_channel_id INTEGER
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS warnings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                moderator_id INTEGER NOT NULL,
                reason TEXT NOT NULL,
                created_at REAL NOT NULL
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS reaction_roles (
                guild_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                emoji TEXT NOT NULL,
                role_id INTEGER NOT NULL,
                PRIMARY KEY (message_id, emoji)
            )
            """
        )
        await db.commit()


async def load_guild_settings():
    """Populate the in-memory prefix/log-channel caches from the db."""
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT guild_id, prefix, log_channel_id FROM guild_settings"
        ) as cursor:
            rows = await cursor.fetchall()

    for row in rows:
        if row["prefix"]:
            prefixes[str(row["guild_id"])] = row["prefix"]
        if row["log_channel_id"]:
            log_channels[str(row["guild_id"])] = row["log_channel_id"]


async def upsert_guild_setting(guild_id, *, prefix=None, log_channel_id=None):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute(
            "INSERT INTO guild_settings (guild_id, prefix, log_channel_id) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT(guild_id) DO UPDATE SET "
            "prefix = COALESCE(excluded.prefix, prefix), "
            "log_channel_id = COALESCE(excluded.log_channel_id, log_channel_id)",
            (guild_id, prefix, log_channel_id),
        )
        await db.commit()


async def clear_guild_prefix(guild_id):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute(
            "INSERT INTO guild_settings (guild_id, prefix, log_channel_id) "
            "VALUES (?, NULL, NULL) "
            "ON CONFLICT(guild_id) DO UPDATE SET prefix = NULL",
            (guild_id,),
        )
        await db.commit()


@bot.bridge_command(name="reminder", aliases=["remindme"])
@commands.cooldown(1, 10, commands.BucketType.user)
async def reminder(ctx, duration: str, *, message: str = "Reminder!"):
    seconds = parse_duration(duration)
    if not seconds:
        await ctx.respond("couldn't parse that, try `10m` or `1h30m`")
        return

    if seconds > 2592000:  # max
        await ctx.respond("30 days max")
        return

    fire_at = discord.utils.utcnow().timestamp() + seconds

    async with aiosqlite.connect(DB_FILE) as db:
        cursor = await db.execute(
            "INSERT INTO reminders (user_id, channel_id, fire_at, message) "
            "VALUES (?, ?, ?, ?)",
            (ctx.author.id, ctx.channel.id, fire_at, message),
        )
        await db.commit()
        reminder_id = cursor.lastrowid

    await ctx.respond(
        f"ok, reminding you in {duration} (id `{reminder_id}`, "
        f"`{prefixes.get(str(ctx.guild.id), DEFAULT_PREFIX) if ctx.guild else DEFAULT_PREFIX}delreminder {reminder_id}` to cancel)"
    )


@bot.bridge_command(name="reminders")
async def list_reminders(ctx):
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT id, fire_at, message FROM reminders WHERE user_id = ? "
            "ORDER BY fire_at ASC",
            (ctx.author.id,),
        ) as cursor:
            rows = await cursor.fetchall()

    if not rows:
        await ctx.respond("you have no pending reminders")
        return

    lines = []
    for row in rows:
        when = discord.utils.format_dt(
            datetime.fromtimestamp(row["fire_at"], tz=timezone.utc), style="R"
        )
        lines.append(f"`{row['id']}` — {when}: {row['message']}")

    embed = discord.Embed(
        title="Your Reminders", description="\n".join(lines), color=0x5865F2
    )
    await ctx.respond(embed=embed)


@bot.bridge_command(name="delreminder")
async def delreminder(ctx, reminder_id: int):
    async with aiosqlite.connect(DB_FILE) as db:
        cursor = await db.execute(
            "DELETE FROM reminders WHERE id = ? AND user_id = ?",
            (reminder_id, ctx.author.id),
        )
        await db.commit()

    if cursor.rowcount == 0:
        await ctx.respond(f"no reminder with id `{reminder_id}` belonging to you")
        return

    await ctx.respond(f"cancelled reminder `{reminder_id}`.")


@tasks.loop(seconds=10)
async def check_reminders():
    now = discord.utils.utcnow().timestamp()

    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM reminders WHERE fire_at <= ?", (now,)
        ) as cursor:
            expired = await cursor.fetchall()

        for row in expired:
            channel = bot.get_channel(row["channel_id"])
            if channel is not None:
                try:
                    await channel.send(
                        f"<@{row['user_id']}> reminder: {row['message']}"
                    )
                except discord.Forbidden:
                    pass

            await db.execute("DELETE FROM reminders WHERE id = ?", (row["id"],))

        await db.commit()


@check_reminders.before_loop
async def before_check_reminders():
    # don't start hitting channels/db until the bot is fully connected
    await bot.wait_until_ready()


@bot.bridge_command(name="cmds")
async def cmds(ctx):
    prefix = (
        prefixes.get(str(ctx.guild.id), DEFAULT_PREFIX) if ctx.guild else DEFAULT_PREFIX
    )

    embed = discord.Embed(
        title="Commands", description="also all work as /slash commands", color=0x5865F2
    )
    embed.add_field(name=f"{prefix}ping", value="latency check", inline=False)
    embed.add_field(
        name=f"{prefix}setprefix [new]",
        value="Manage Server required, 5 chars max",
        inline=False,
    )
    embed.add_field(
        name=f"{prefix}resetprefix", value="Manage Server required", inline=False
    )
    embed.add_field(
        name=f"{prefix}clear [amount]",
        value="Manage Messages required, max 100",
        inline=False,
    )
    embed.add_field(
        name=f"{prefix}kick @member [reason]",
        value="Kick Members required",
        inline=False,
    )
    embed.add_field(
        name=f"{prefix}ban @member [reason]", value="Ban Members required", inline=False
    )
    embed.add_field(
        name=f"{prefix}unban <name/id/name#0000>",
        value="Ban Members required",
        inline=False,
    )
    embed.add_field(
        name=f"{prefix}mute @member <10m/2h/1d> [reason]",
        value="Moderate Members required, 28 day max",
        inline=False,
    )
    embed.add_field(
        name=f"{prefix}unmute @member", value="Moderate Members required", inline=False
    )
    embed.add_field(
        name=f"{prefix}warn @member [reason]",
        value="Moderate Members required, logged + stored, auto-mutes at "
        f"{WARN_MUTE_THRESHOLD} warnings",
        inline=False,
    )
    embed.add_field(
        name=f"{prefix}warnings @member",
        value="Moderate Members required, shows a member's last 10 warnings",
        inline=False,
    )
    embed.add_field(
        name=f"{prefix}delwarning <id>",
        value="Manage Server required, deletes a single warning",
        inline=False,
    )
    embed.add_field(
        name=f"{prefix}setlogchannel [#channel]",
        value="Manage Server required, sets where mod actions are logged",
        inline=False,
    )
    embed.add_field(
        name=f"{prefix}slowmode [seconds]",
        value="Manage Channels required, run again to disable, default 10s",
        inline=False,
    )
    embed.add_field(
        name=f"{prefix}userinfo [@member]",
        value="yourself if nothing tagged",
        inline=False,
    )
    embed.add_field(name=f"{prefix}serverinfo", value="", inline=False)
    embed.add_field(name=f"{prefix}roleinfo <role>", value="", inline=False)
    embed.add_field(
        name=f"{prefix}reactionrole <message_id> <emoji> <role>",
        value="Manage Roles required, sets up self-assignable roles via reactions",
        inline=False,
    )
    embed.add_field(
        name=f'{prefix}poll "q" ["opt"...]',
        value="no options = thumbs up/down, up to 10 options, 15s cooldown",
        inline=False,
    )
    embed.add_field(
        name=f"{prefix}reminder <10m/2h/1d> <msg>",
        value="30 day max, 10s cooldown",
        inline=False,
    )
    embed.add_field(
        name=f"{prefix}reminders", value="lists your pending reminders", inline=False
    )
    embed.add_field(
        name=f"{prefix}delreminder <id>",
        value="cancels one of your reminders",
        inline=False,
    )
    await ctx.respond(embed=embed)


@bot.event
async def on_message_delete(message: discord.Message):
    # ignore dms
    if not message.guild:
        return

    if message.author and message.author.bot:
        return

    log_channel_id = log_channels.get(str(message.guild.id))
    if not log_channel_id:
        return

    log_channel = message.guild.get_channel(log_channel_id)
    if not log_channel:
        return

    embed = discord.Embed(
        title="Message Deleted",
        color=0xFF0000,  # Red
        timestamp=discord.utils.utcnow(),
    )
    embed.set_footer(
        text=f"Author ID: {message.author.id if message.author else 'Unknown'}"
    )

    if message.content or message.attachments:
        embed.set_author(
            name=str(message.author), icon_url=message.author.display_avatar.url
        )
        embed.add_field(name="Channel", value=message.channel.mention, inline=True)
        embed.add_field(name="Author", value=message.author.mention, inline=True)

        if message.content:
            content = (
                message.content[:1000] + "..."
                if len(message.content) > 1000
                else message.content
            )
            embed.add_field(name="Content", value=content, inline=False)

        if message.attachments:
            filenames = ", ".join([att.filename for att in message.attachments])
            embed.add_field(name="Attachments", value=f"{filenames}", inline=False)

    else:
        embed.description = (
            "message was deleted but it was sent before bot was on "
            "or pushed out of the temp message cache"
        )
        embed.add_field(name="channel", value=message.channel.mention, inline=False)

    try:
        await log_channel.send(embed=embed)
    except discord.Forbidden:
        pass


@bot.bridge_command(name="reactionrole")
@commands.has_permissions(manage_roles=True)
async def reactionrole(ctx, message_id: str, emoji: str, role: discord.Role):
    try:
        message_id = int(message_id)
    except ValueError:
        await ctx.respond("that doesn't look like a message id")
        return

    if role >= ctx.guild.me.top_role:
        await ctx.respond("that role is above my highest role")
        return

    target = None
    for channel in ctx.guild.text_channels:
        try:
            target = await channel.fetch_message(message_id)
            break
        except (discord.NotFound, discord.Forbidden):
            continue

    if target is None:
        await ctx.respond("couldn't find a message with that id")
        return

    try:
        await target.add_reaction(emoji)
    except discord.HTTPException:
        await ctx.respond("that isnt an emoji")
        return

    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute(
            "INSERT INTO reaction_roles (guild_id, message_id, emoji, role_id) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(message_id, emoji) DO UPDATE SET role_id = excluded.role_id",
            (ctx.guild.id, message_id, emoji, role.id),
        )
        await db.commit()

    await ctx.respond(
        f"reacting with {emoji} on that message now grants {role.mention}."
    )


@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    if payload.member is None or payload.member.bot:
        return

    role_id = await get_reaction_role(payload.message_id, str(payload.emoji))
    if role_id is None:
        return

    role = payload.member.guild.get_role(role_id)
    if role is None:
        return

    try:
        await payload.member.add_roles(role, reason="Reaction role")
    except discord.Forbidden:
        pass


@bot.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent):
    guild = bot.get_guild(payload.guild_id) if payload.guild_id else None
    if guild is None:
        return

    role_id = await get_reaction_role(payload.message_id, str(payload.emoji))
    if role_id is None:
        return

    role = guild.get_role(role_id)
    member = guild.get_member(payload.user_id)
    if role is None or member is None:
        return

    try:
        await member.remove_roles(role, reason="Reaction role removed")
    except discord.Forbidden:
        pass


async def get_reaction_role(message_id: int, emoji: str):
    async with aiosqlite.connect(DB_FILE) as db:
        async with db.execute(
            "SELECT role_id FROM reaction_roles WHERE message_id = ? AND emoji = ?",
            (message_id, emoji),
        ) as cursor:
            row = await cursor.fetchone()
    return row[0] if row else None


@bot.event
async def on_message(message: discord.Message):
    if message.guild and not message.author.bot:
        key = (message.guild.id, message.author.id)
        now = discord.utils.utcnow().timestamp()
        dq = recent_messages[key]
        dq.append(now)
        while dq and now - dq[0] > SPAM_WINDOW_SECONDS:
            dq.popleft()

        if len(dq) >= SPAM_MESSAGE_THRESHOLD:
            dq.clear()
            member = message.author
            if (
                isinstance(member, discord.Member)
                and not member.guild_permissions.manage_messages
            ):
                try:
                    until = discord.utils.utcnow() + timedelta(
                        seconds=SPAM_MUTE_SECONDS
                    )
                    await member.timeout(until, reason="Automatic: message spam")
                    warning = await message.channel.send(
                        f"{member.mention} muted for {SPAM_MUTE_SECONDS}s (spam detected)"
                    )
                    await warning.delete(delay=5)
                except discord.Forbidden:
                    pass

    await bot.process_commands(message)


@bot.event
async def on_message_edit(before: discord.Message, after: discord.Message):
    if not before.guild or (before.author and before.author.bot):
        return
    if before.content == after.content:
        return

    log_channel_id = log_channels.get(str(before.guild.id))
    if not log_channel_id:
        return

    log_channel = before.guild.get_channel(log_channel_id)
    if not log_channel:
        return

    embed = discord.Embed(
        title="Message Edited", color=0xFFAA00, timestamp=discord.utils.utcnow()
    )
    embed.set_author(name=str(before.author), icon_url=before.author.display_avatar.url)
    embed.add_field(name="Channel", value=before.channel.mention, inline=True)
    embed.add_field(name="Author", value=before.author.mention, inline=True)
    embed.add_field(name="Jump", value=f"[link]({after.jump_url})", inline=True)

    old_content = before.content[:1000] if before.content else "*(none)*"
    new_content = after.content[:1000] if after.content else "*(none)*"
    embed.add_field(name="Before", value=old_content, inline=False)
    embed.add_field(name="After", value=new_content, inline=False)

    try:
        await log_channel.send(embed=embed)
    except discord.Forbidden:
        pass


# TODO: Implement proper logging framework instead of printing
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send(f"missing perms: {', '.join(error.missing_permissions)}")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"missing argument: {error.param.name}")
    elif isinstance(error, commands.BadArgument):
        await ctx.send("couldn't find that user/role")
    elif isinstance(error, commands.CommandOnCooldown):
        await ctx.send(f"slow down, try again in {error.retry_after:.1f}s")
    elif isinstance(error, commands.CommandNotFound):
        pass
    else:
        print(error)
        await ctx.send("something broke")


@bot.event
async def on_application_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.respond(
            f"missing perms: {', '.join(error.missing_permissions)}", ephemeral=True
        )
    elif isinstance(error, commands.BadArgument):
        await ctx.respond("couldn't find that user/role", ephemeral=True)
    elif isinstance(error, commands.CommandOnCooldown):
        await ctx.respond(
            f"slow down, try again in {error.retry_after:.1f}s", ephemeral=True
        )
    else:
        print(error)
        await ctx.respond("something broke", ephemeral=True)


@bot.event
async def on_ready():
    print(f"logged in as {bot.user}")

    await init_db()
    await load_guild_settings()

    if not check_reminders.is_running():
        check_reminders.start()


async def main():
    async with bot:
        await bot.start(DISCORD_TOKEN)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
# git commit -m "Resolving a race condition in my life choices"
