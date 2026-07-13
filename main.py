import asyncio
import json
import os
import re
import uuid
from datetime import timedelta
from pathlib import Path

import discord
from discord.ext import bridge, commands
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).parent / ".env")
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN not found in the .env file")

DEFAULT_PREFIX = "e!"
PREFIX_FILE = Path(__file__).parent / "prefixes.json"
LOG_CHANNEL_FILE = Path(__file__).parent / "log_channels.json"
REMINDER_FILE = Path(__file__).parent / "reminders.json"


def load_json(path, default):
    if not path.exists():
        return default
    with open(path, "r") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


prefixes = load_json(PREFIX_FILE, {})
log_channels = load_json(LOG_CHANNEL_FILE, {})
reminders = load_json(REMINDER_FILE, [])


def get_prefix(bot_, message):
    if not message.guild:
        return commands.when_mentioned_or(DEFAULT_PREFIX)(bot_, message)
    p = prefixes.get(str(message.guild.id), DEFAULT_PREFIX)
    return commands.when_mentioned_or(p)(bot_, message)


intents = discord.Intents.default()
intents.message_content = True
intents.members = True

# prob not needed but doesnt hurt to have it in
try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

bot = bridge.Bot(command_prefix=get_prefix, intents=intents)


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
    save_json(PREFIX_FILE, prefixes)
    await ctx.respond(f"prefix is now `{new_prefix}`")


@bot.bridge_command(name="resetprefix")
@commands.has_permissions(manage_guild=True)
async def resetprefix(ctx):
    prefixes.pop(str(ctx.guild.id), None)
    save_json(PREFIX_FILE, prefixes)
    await ctx.respond(f"back to default (`{DEFAULT_PREFIX}`)")


def get_log_channel(ctx):
    log_channel_id = log_channels.get(str(ctx.guild.id))
    if log_channel_id is None:
        return None
    return ctx.guild.get_channel(log_channel_id)


async def post_mod_log(ctx, *, title, color, fields):
    """Best-effort post of a moderation action embed to the configured log channel.
    Silently does nothing if no log channel is set or the bot can't post there.
    """
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
        # +1 so the command eats itself
        deleted = await ctx.channel.purge(limit=amount + 1)
        # can't ctx.respond() here - it replies to the invoking message,
        # which we just purged, so Discord rejects the reference
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

    # discord's hard limit on timeouts is 28 days
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


@bot.bridge_command(name="unban")
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
    save_json(LOG_CHANNEL_FILE, log_channels)
    await ctx.respond(f"Moderation logs will be posted in {channel.mention}")


@bot.bridge_command(name="warn")
@commands.has_permissions(moderate_members=True)
async def warn(ctx, member: discord.Member, *, reason="No reason provided"):
    # warns aren't persisted anywhere, just posted to the log channel.
    # good enough for now, might add a proper warn history later
    log_channel = get_log_channel(ctx)
    if log_channel is None:
        await ctx.respond(
            "No log channel set yet, use `e!setlogchannel #channel` first"
        )
        return

    await post_mod_log(
        ctx,
        title="Member Warned",
        color=0xFFCC00,
        fields=[
            ("Member", f"{member.mention} ({member})"),
            ("Warned by", ctx.author.mention),
            ("Reason", reason),
        ],
    )

    await ctx.respond(f"Warned {member.mention}. Logged in {log_channel.mention}.")


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


def schedule_reminder(entry):
    delay = max(entry["fire_at"] - discord.utils.utcnow().timestamp(), 0)

    async def wait_and_remind():
        await asyncio.sleep(delay)

        channel = bot.get_channel(entry["channel_id"])
        if channel is not None:
            try:
                await channel.send(
                    f"<@{entry['user_id']}> reminder: {entry['message']}"
                )
            except discord.Forbidden:
                pass

        reminders[:] = [r for r in reminders if r["id"] != entry["id"]]
        save_json(REMINDER_FILE, reminders)

    bot.loop.create_task(wait_and_remind())


@bot.bridge_command(name="reminder", aliases=["remindme"])
async def reminder(ctx, duration: str, *, message: str = "Reminder!"):
    seconds = parse_duration(duration)
    if not seconds:
        await ctx.respond("couldn't parse that, try `10m` or `1h30m`")
        return

    if seconds > 2592000:  # max
        await ctx.respond("30 days max")
        return

    entry = {
        "id": str(uuid.uuid4()),
        "user_id": ctx.author.id,
        "channel_id": ctx.channel.id,
        "fire_at": discord.utils.utcnow().timestamp() + seconds,
        "message": message,
    }
    reminders.append(entry)
    save_json(REMINDER_FILE, reminders)

    await ctx.respond(f"ok, reminding you in {duration}")
    schedule_reminder(entry)


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
        value="Moderate Members required, posts to the log channel (not stored)",
        inline=False,
    )
    embed.add_field(
        name=f"{prefix}setlogchannel [#channel]",
        value="Manage Server required, sets where mod actions (warn/kick/ban/mute/unmute/unban/clear) are logged",
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
        name=f'{prefix}poll "q" ["opt"...]',
        value="no options = thumbs up/down, up to 10 options",
        inline=False,
    )
    embed.add_field(
        name=f"{prefix}reminder <10m/2h/1d> <msg>", value="30 day max", inline=False
    )
    await ctx.respond(embed=embed)


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send(f"missing perms: {', '.join(error.missing_permissions)}")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"missing argument: {error.param.name}")
    elif isinstance(error, commands.BadArgument):
        await ctx.send("couldn't find that user/role")
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
    else:
        print(error)
        await ctx.respond("something broke", ephemeral=True)


@bot.event
async def on_ready():
    print(f"logged in as {bot.user}")

    # Wait until the internal cache is fully loaded
    await bot.wait_until_ready()

    for entry in list(reminders):
        schedule_reminder(entry)
    if reminders:
        print(f"rescheduled {len(reminders)} pending reminder(s)")


bot.run(DISCORD_TOKEN)
