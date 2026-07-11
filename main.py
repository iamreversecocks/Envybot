import os
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
intents.members = True  # needed for member lookups (userinfo etc)

bot = commands.Bot(command_prefix="e!", intents=intents)


@bot.command(name="ping")
async def ping(ctx):
    latency_ms = round(bot.latency * 1000)
    await ctx.send(f"Pong! {latency_ms}ms", delete_after=5)


@bot.command(name="clear")
@commands.has_permissions(manage_messages=True)
async def clear(ctx, amount: int = 5):
    # cap it so people can't nuke the whole channel by accident
    to_delete = min(amount, 100)
    deleted = await ctx.channel.purge(limit=to_delete + 1)  # +1 for the command msg itself
    await ctx.send(f"Deleted {len(deleted) - 1} message(s).", delete_after=5)


@bot.command(name="kick")
@commands.has_permissions(kick_members=True)
async def kick(ctx, member: discord.Member, *, reason="No reason provided"):
    try:
        await member.kick(reason=reason)
        await ctx.send(f"Kicked {member.mention}. Reason: {reason}", delete_after=5)
    except discord.Forbidden:
        await ctx.send("I don't have permission to kick that member.", delete_after=5)
    except Exception as exc:
        await ctx.send(f"Failed to kick: {exc}", delete_after=5)


@bot.command(name="ban")
@commands.has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, *, reason="No reason provided"):
    try:
        await member.ban(reason=reason, delete_message_days=0)
        await ctx.send(f"Banned {member.mention}. Reason: {reason}", delete_after=5)
    except discord.Forbidden:
        await ctx.send("I don't have permission to ban that member.", delete_after=5)
    except Exception as exc:
        await ctx.send(f"Failed to ban: {exc}", delete_after=5)


def _user_embed(member, requestor_name):
    embed = discord.Embed(
        title=f"{member.display_name}'s Details",
        color=0x00AAFF,
        timestamp=discord.utils.utcnow(),
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="Tag", value=str(member), inline=True)
    embed.add_field(name="Account Created", value=member.created_at.strftime("%b %d, %Y %H:%M"), inline=True)
    embed.add_field(name="Joined Server", value=member.joined_at.strftime("%b %d, %Y %H:%M"), inline=True)

    top_roles = [r.name for r in member.roles if r != member.guild.default_role][:5]
    embed.add_field(name="Top Roles", value=", ".join(top_roles) or "None", inline=False)
    embed.set_footer(text=f"Requested by {requestor_name}")
    return embed


@bot.command(name="userinfo")
async def userinfo(ctx, member: discord.Member = None):
    target = member or ctx.author
    await ctx.send(embed=_user_embed(target, ctx.author.display_name))


def _guild_embed(guild):
    # owner can be None if it's not cached, so don't assume it's there
    owner_tag = guild.owner.mention if guild.owner else "Unknown"

    embed = discord.Embed(title=guild.name, color=0xFFAA00, timestamp=discord.utils.utcnow())
    embed.set_thumbnail(url=guild.icon.url if guild.icon else None)
    embed.add_field(name="Owner", value=owner_tag, inline=True)
    embed.add_field(name="Members", value=str(guild.member_count), inline=True)
    embed.add_field(name="Created", value=guild.created_at.strftime("%b %d, %Y %H:%M"), inline=False)
    embed.set_footer(text=f"Server ID: {guild.id}")
    return embed


@bot.command(name="serverinfo")
async def serverinfo(ctx):
    await ctx.send(embed=_guild_embed(ctx.guild))


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        perms = ", ".join(error.missing_permissions)
        await ctx.send(f"You're missing permission(s): {perms}", delete_after=5)
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"Missing argument: {error.param.name}", delete_after=5)
    elif isinstance(error, commands.BadArgument):
        await ctx.send(f"Bad argument: {error}", delete_after=5)
    elif isinstance(error, discord.Forbidden):
        await ctx.send("I don't have permission to do that.", delete_after=5)
    else:
        print(f"Unhandled command error: {error}")
        await ctx.send("Something went wrong running that command.", delete_after=5)


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} ({bot.user.id})")


if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
