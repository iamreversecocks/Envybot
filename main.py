import asyncio
import os
import re
from pathlib import Path

import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).parent / ".env")
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN not found in the .env file")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True  # need this for userinfo lookups

bot = commands.Bot(command_prefix="e!", intents=intents)


@bot.command(name="ping")
async def ping(ctx):
    latency_ms = round(bot.latency * 1000)
    await ctx.send(f"Pong! {latency_ms}ms")


@bot.command(name="clear")
@commands.has_permissions(manage_messages=True)
async def clear(ctx, amount: int = 5):
    if amount > 100:
        amount = 100
    deleted = await ctx.channel.purge(limit=amount + 1)  # +1 so it eats its own command message
    # print(f"purged {len(deleted)} in #{ctx.channel.name}")
    msg = await ctx.send(f"Deleted {len(deleted) - 1} messages.")
    await msg.delete(delay=5)


@bot.command(name="kick")
@commands.has_permissions(kick_members=True)
async def kick(ctx, member: discord.Member, *, reason="No reason provided"):
    if member == ctx.author:
        await ctx.send("you can't kick yourself lol")
        return
    try:
        await member.kick(reason=reason)
        await ctx.send(f"Kicked {member.mention}. Reason: {reason}")
    except discord.Forbidden:
        await ctx.send("I don't have permission to kick that member.")


@bot.command(name="ban")
@commands.has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, *, reason="No reason provided"):
    try:
        await member.ban(reason=reason, delete_message_days=0)
        await ctx.send(f"Banned {member.mention}. Reason: {reason}")
    except discord.Forbidden:
        await ctx.send("I don't have permission to ban that member.")


@bot.command(name="unban")
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
        await ctx.send(f"couldn't find `{user}` in the ban list")
        return

    await ctx.guild.unban(match.user, reason=f"Unbanned by {ctx.author}")
    await ctx.send(f"Unbanned {match.user}.")


@bot.command(name="userinfo")
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

    await ctx.send(embed=embed)


@bot.command(name="serverinfo")
async def serverinfo(ctx):
    guild = ctx.guild
    embed = discord.Embed(title=guild.name, color=0xFFAA00)
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)
    embed.add_field(name="Owner", value=guild.owner.mention if guild.owner else "unknown", inline=True)
    embed.add_field(name="Members", value=str(guild.member_count), inline=True)
    embed.add_field(name="Created", value=guild.created_at.strftime("%b %d, %Y"), inline=False)
    embed.set_footer(text=f"ID: {guild.id}")
    await ctx.send(embed=embed)


@bot.command(name="roleinfo")
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

    await ctx.send(embed=embed)


NUMBERS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]


@bot.command(name="poll")
async def poll(ctx, question: str, *options: str):
    if len(options) > 10:
        await ctx.send("max 10 options")
        return

    if not options:
        embed = discord.Embed(title=question, color=0x5865F2)
        msg = await ctx.send(embed=embed)
        await msg.add_reaction("👍")
        await msg.add_reaction("👎")
        return

    desc = ""
    for i, opt in enumerate(options):
        desc += f"{NUMBERS[i]} {opt}\n"

    embed = discord.Embed(title=question, description=desc, color=0x5865F2)
    msg = await ctx.send(embed=embed)
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


@bot.command(name="reminder", aliases=["remindme"])
async def reminder(ctx, duration: str, *, message: str = "Reminder!"):
    seconds = parse_duration(duration)
    if not seconds:
        await ctx.send("couldn't parse that, try like `10m` or `1h30m`")
        return

    if seconds > 2592000:
        await ctx.send("30 days max")
        return

    await ctx.send(f"ok, reminding you in {duration}")

    async def wait_and_remind():
        await asyncio.sleep(seconds)
        try:
            await ctx.send(f"{ctx.author.mention} reminder: {message}")
        except discord.Forbidden:
            pass

    bot.loop.create_task(wait_and_remind())
    # TODO: this doesn't survive a restart, should probably persist these to a json
    # file or sqlite at some point if this blows up


@bot.command(name="cmds")
async def cmds(ctx):
    embed = discord.Embed(title="Commands", color=0x5865F2)
    embed.add_field(name="e!ping", value="latency check", inline=False)
    embed.add_field(name="e!clear [amount]", value="Manage Messages required, max 100", inline=False)
    embed.add_field(name="e!kick @member [reason]", value="Kick Members required", inline=False)
    embed.add_field(name="e!ban @member [reason]", value="Ban Members required", inline=False)
    embed.add_field(name="e!unban <name/id/name#0000>", value="Ban Members required", inline=False)
    embed.add_field(name="e!userinfo [@member]", value="yourself if nothing tagged", inline=False)
    embed.add_field(name="e!serverinfo", value="", inline=False)
    embed.add_field(name="e!roleinfo <role>", value="", inline=False)
    embed.add_field(name='e!poll "q" ["opt"...]', value="no options = thumbs up/down", inline=False)
    embed.add_field(name="e!reminder <10m/2h/1d> <msg>", value="30 day max", inline=False)
    await ctx.send(embed=embed)


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send(f"missing perms: {', '.join(error.missing_permissions)}")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"missing argument: {error.param.name}")
    elif isinstance(error, commands.BadArgument):
        await ctx.send("couldn't find that user/role, double check it")
    elif isinstance(error, commands.CommandNotFound):
        pass
    else:
        print(error)
        await ctx.send("something broke, check the logs")


@bot.event
async def on_ready():
    print(f"logged in as {bot.user}")


bot.run(DISCORD_TOKEN)
