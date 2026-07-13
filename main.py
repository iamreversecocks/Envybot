import asyncio
import json
import os
import re
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

if PREFIX_FILE.exists():
    with open(PREFIX_FILE, "r") as f:
        prefixes = json.load(f)
else:
    prefixes = {}


def save_prefixes():
    with open(PREFIX_FILE, "w") as f:
        json.dump(prefixes, f, indent=2)


def get_prefix(bot_, message):
    if not message.guild:
        return commands.when_mentioned_or(DEFAULT_PREFIX)(bot_, message)
    p = prefixes.get(str(message.guild.id), DEFAULT_PREFIX)
    return commands.when_mentioned_or(p)(bot_, message)


intents = discord.Intents.default()
intents.message_content = True
intents.members = True  # need this for userinfo lookups

# Python 3.14 removed the auto-create fallback in asyncio.get_event_loop(),
# but py-cord 2.6.1's Client.__init__ still calls it expecting one to exist.
# Create and set a loop manually so that call doesn't blow up.
try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

# bridge.Bot gives every @bot.bridge_command both a e!prefix version and a /slash version
bot = bridge.Bot(command_prefix=get_prefix, intents=intents)


@bot.bridge_command(name="ping")
async def ping(ctx):
    latency_ms = round(bot.latency * 1000)
    await ctx.respond(f"Pong! {latency_ms}ms")


@bot.bridge_command(name="setprefix")
@commands.has_permissions(manage_guild=True)
async def setprefix(ctx, new_prefix: str = None):
    if new_prefix is None:
        cur = prefixes.get(str(ctx.guild.id), DEFAULT_PREFIX)
        await ctx.respond(f"prefix is currently `{cur}`, do `{cur}setprefix <new>` to change it")
        return

    if len(new_prefix) > 5:
        await ctx.respond("5 chars max")
        return

    prefixes[str(ctx.guild.id)] = new_prefix
    save_prefixes()
    await ctx.respond(f"prefix is now `{new_prefix}`")


@bot.bridge_command(name="resetprefix")
@commands.has_permissions(manage_guild=True)
async def resetprefix(ctx):
    prefixes.pop(str(ctx.guild.id), None)
    save_prefixes()
    await ctx.respond(f"back to default (`{DEFAULT_PREFIX}`)")


@bot.bridge_command(name="clear")
@commands.has_permissions(manage_messages=True)
async def clear(ctx, amount: int = 5):
    if amount > 100:
        amount = 100
    # purge only works on the prefix path (interactions can't purge before responding),
    # so for slash use just delete via history instead
    if ctx.is_app:
        deleted = await ctx.channel.purge(limit=amount)
        await ctx.respond(f"Deleted {len(deleted)} messages.", ephemeral=True, delete_after=5)
    else:
        deleted = await ctx.channel.purge(limit=amount + 1)  # +1 so it eats its own command message
        msg = await ctx.respond(f"Deleted {len(deleted) - 1} messages.")
        await msg.delete(delay=5)


@bot.bridge_command(name="kick")
@commands.has_permissions(kick_members=True)
async def kick(ctx, member: discord.Member, *, reason="No reason provided"):
    if member == ctx.author:
        await ctx.respond("I refuse")
        return
    try:
        await member.kick(reason=reason)
        await ctx.respond(f"Kicked {member.mention}. Reason: {reason}")
    except discord.Forbidden:
        await ctx.respond("No perms to kick that user")


@bot.bridge_command(name="ban")
@commands.has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, *, reason="No reason provided"):
    try:
        await member.ban(reason=reason, delete_message_days=0)
        await ctx.respond(f"Banned {member.mention}. Reason: {reason}")
    except discord.Forbidden:
        await ctx.respond("No perms to ban that user")


@bot.bridge_command(name="unban")
@commands.has_permissions(ban_members=True)
async def unban(ctx, *, user: str):
    # ban list isn't cached
    banned = [entry async for entry in ctx.guild.bans()]
    user = user.strip()

    mention_match = re.match(r"<@!?(\d+)>$", user)
    match = None

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


@bot.bridge_command(name="userinfo")
async def userinfo(ctx, member: discord.Member = None):
    if member is None:
        member = ctx.author

    embed = discord.Embed(title=f"{member.display_name}'s Details", color=0x00AAFF)
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="Tag", value=str(member), inline=True)
    embed.add_field(name="Account Created", value=member.created_at.strftime("%b %d, %Y"), inline=True)
    embed.add_field(name="Joined Server", value=member.joined_at.strftime("%b %d, %Y"), inline=True)

    roles = [r.name for r in member.roles if r.name != "@everyone"]
    embed.add_field(name="Roles", value=", ".join(roles[:5]) if roles else "None", inline=False)

    await ctx.respond(embed=embed)


@bot.bridge_command(name="serverinfo")
async def serverinfo(ctx):
    guild = ctx.guild
    embed = discord.Embed(title=guild.name, color=0xFFAA00)
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)
    embed.add_field(name="Owner", value=guild.owner.mention if guild.owner else "unknown", inline=True)
    embed.add_field(name="Members", value=str(guild.member_count), inline=True)
    embed.add_field(name="Created", value=guild.created_at.strftime("%b %d, %Y"), inline=False)
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
        perms = ", ".join(p.replace("_", " ").title() for p, val in role.permissions if val)
        if not perms:
            perms = "None"
    embed.add_field(name="Permissions", value=perms[:1000], inline=False)

    await ctx.respond(embed=embed)


NUMBERS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]


@bot.bridge_command(name="poll")
async def poll(
    ctx, question: str,
    opt1: str = None, opt2: str = None, opt3: str = None, opt4: str = None, opt5: str = None,
    opt6: str = None, opt7: str = None, opt8: str = None, opt9: str = None, opt10: str = None,
):
    options = [o for o in (opt1, opt2, opt3, opt4, opt5, opt6, opt7, opt8, opt9, opt10) if o]

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


@bot.bridge_command(name="reminder", aliases=["remindme"])
async def reminder(ctx, duration: str, *, message: str = "Reminder!"):
    seconds = parse_duration(duration)
    if not seconds:
        await ctx.respond("couldn't parse that, try `10m` or `1h30m`")
        return

    if seconds > 2592000:
        await ctx.respond("30 days max")
        return

    await ctx.respond(f"ok, reminding you in {duration}")

    async def wait_and_remind():
        await asyncio.sleep(seconds)
        try:
            await ctx.send(f"{ctx.author.mention} reminder: {message}")
        except discord.Forbidden:
            pass

    bot.loop.create_task(wait_and_remind())
    # TODO: this doesn't survive a restart, should probably persist these to a json
    # file or sqlite at some point if this blows up


@bot.bridge_command(name="cmds")
async def cmds(ctx):
    prefix = prefixes.get(str(ctx.guild.id), DEFAULT_PREFIX) if ctx.guild else DEFAULT_PREFIX
    embed = discord.Embed(title="Commands", description="also all work as /slash commands", color=0x5865F2)
    embed.add_field(name=f"{prefix}ping", value="latency check", inline=False)
    embed.add_field(name=f"{prefix}setprefix [new]", value="Manage Server required, 5 chars max", inline=False)
    embed.add_field(name=f"{prefix}resetprefix", value="Manage Server required", inline=False)
    embed.add_field(name=f"{prefix}clear [amount]", value="Manage Messages required, max 100", inline=False)
    embed.add_field(name=f"{prefix}kick @member [reason]", value="Kick Members required", inline=False)
    embed.add_field(name=f"{prefix}ban @member [reason]", value="Ban Members required", inline=False)
    embed.add_field(name=f"{prefix}unban <name/id/name#0000>", value="Ban Members required", inline=False)
    embed.add_field(name=f"{prefix}userinfo [@member]", value="yourself if nothing tagged", inline=False)
    embed.add_field(name=f"{prefix}serverinfo", value="", inline=False)
    embed.add_field(name=f"{prefix}roleinfo <role>", value="", inline=False)
    embed.add_field(name=f'{prefix}poll "q" ["opt"...]', value="no options = thumbs up/down, up to 10 options", inline=False)
    embed.add_field(name=f"{prefix}reminder <10m/2h/1d> <msg>", value="30 day max", inline=False)
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
        await ctx.respond(f"missing perms: {', '.join(error.missing_permissions)}", ephemeral=True)
    elif isinstance(error, commands.BadArgument):
        await ctx.respond("couldn't find that user/role", ephemeral=True)
    else:
        print(error)
        await ctx.respond("something broke", ephemeral=True)


@bot.event
async def on_ready():
    print(f"logged in as {bot.user}")


bot.run(DISCORD_TOKEN)