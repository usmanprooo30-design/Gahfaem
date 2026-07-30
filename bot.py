"""
Discord Member Farm Bot - Advanced Version
"""

import os
import asyncio
import aiohttp
from aiohttp import web
import aiosqlite
import discord
from discord.ext import commands
from discord.ui import View, Button

# ==================== CONFIG ====================
BOT_TOKEN = os.getenv("BOT_TOKEN")
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
REDIRECT_URI = os.getenv("REDIRECT_URI")
WEB_PORT = int(os.getenv("PORT", 8080))

ROLE_LIMITS = {
    "member": 2,
    "silver": 10,
    "gold": 15,
    "diamond": 25,
    "premium": 35,
}

DB_PATH = "authorized_users.db"

# ==================== EMOJIS (You can change these) ====================
EMOJI_SUCCESS = "✅"
EMOJI_ERROR = "❌"
EMOJI_LOADING = "🔄"
EMOJI_AUTH = "🔐"
EMOJI_BOT = "🤖"
EMOJI_USERS = "👥"
EMOJI_INFO = "ℹ️"
EMOJI_HELP = "📖"
EMOJI_FARM = "🌾"
EMOJI_STAR = "⭐"

# =================================================

if not all([BOT_TOKEN, CLIENT_ID, CLIENT_SECRET, REDIRECT_URI]):
    raise ValueError("Missing environment variables")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)
bot.remove_command("help")


# -------------------- Database --------------------
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS authorized (
                user_id TEXT PRIMARY KEY,
                access_token TEXT NOT NULL,
                refresh_token TEXT,
                expires_at INTEGER
            )
        """)
        await db.commit()


async def save_token(user_id: str, access_token: str, refresh_token: str = None, expires_at: int = 0):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO authorized (user_id, access_token, refresh_token, expires_at) VALUES (?, ?, ?, ?)",
            (user_id, access_token, refresh_token, expires_at),
        )
        await db.commit()


async def get_token(user_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT access_token FROM authorized WHERE user_id = ?", (user_id,)) as cursor:
            return await cursor.fetchone()


async def get_all_authorized():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id, access_token FROM authorized") as cursor:
            return await cursor.fetchall()


async def remove_token(user_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM authorized WHERE user_id = ?", (user_id,))
        await db.commit()


# -------------------- OAuth Helpers --------------------
def get_auth_url():
    scopes = "identify%20guilds.join"
    return f"https://discord.com/api/oauth2/authorize?client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}&response_type=code&scope={scopes}"


def get_bot_invite_url():
    return f"https://discord.com/api/oauth2/authorize?client_id={CLIENT_ID}&permissions=8&scope=bot%20applications.commands"


async def exchange_code(code: str):
    data = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    async with aiohttp.ClientSession() as session:
        async with session.post("https://discord.com/api/oauth2/token", data=data, headers=headers) as resp:
            if resp.status != 200:
                raise Exception(await resp.text())
            return await resp.json()


async def get_user_info(access_token: str):
    headers = {"Authorization": f"Bearer {access_token}"}
    async with aiohttp.ClientSession() as session:
        async with session.get("https://discord.com/api/users/@me", headers=headers) as resp:
            return await resp.json() if resp.status == 200 else None


async def add_member_to_guild(guild_id: str, user_id: str, access_token: str):
    url = f"https://discord.com/api/guilds/{guild_id}/members/{user_id}"
    headers = {"Authorization": f"Bot {BOT_TOKEN}", "Content-Type": "application/json"}
    async with aiohttp.ClientSession() as session:
        async with session.put(url, json={"access_token": access_token}, headers=headers) as resp:
            return resp.status, await resp.text()


# -------------------- Web Server --------------------
async def handle_callback(request):
    code = request.rel_url.query.get("code")
    if not code:
        return web.Response(text="Authorization failed.", status=400)
    try:
        token_data = await exchange_code(code)
        user = await get_user_info(token_data["access_token"])
        if not user:
            return web.Response(text="Failed to get user info.", status=400)
        await save_token(user["id"], token_data["access_token"], token_data.get("refresh_token"), token_data.get("expires_in", 0))
        return web.Response(text=f"✅ Successfully authorized as {user.get('username')}!\nYou can now be farmed.", content_type="text/plain")
    except Exception as e:
        return web.Response(text=f"Error: {str(e)}", status=500)


async def start_web_server():
    app = web.Application()
    app.router.add_get("/callback", handle_callback)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", WEB_PORT).start()
    print(f"OAuth server running on port {WEB_PORT}")


# -------------------- Buttons --------------------
class AuthButton(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Authorize Now", style=discord.ButtonStyle.green, custom_id="auth_btn")
    async def auth_btn(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_message(f"{EMOJI_AUTH} **Click below to authorize:**\n{get_auth_url()}", ephemeral=True)


class AddBotButton(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Add Bot to Server", style=discord.ButtonStyle.blurple, custom_id="addbot_btn")
    async def addbot_btn(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_message(f"{EMOJI_BOT} **Invite Link:**\n{get_bot_invite_url()}", ephemeral=True)


# -------------------- Commands --------------------
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    await init_db()
    bot.add_view(AuthButton())
    bot.add_view(AddBotButton())


@bot.command(name="help")
async def help_command(ctx):
    embed = discord.Embed(
        title=f"{EMOJI_HELP} Bot Commands",
        description="Here are all available commands:",
        color=discord.Color.blurple()
    )
    embed.add_field(name="`!auth`", value="Authorize yourself so you can be farmed", inline=False)
    embed.add_field(name="`!addbot`", value="Get the bot invite link", inline=False)
    embed.add_field(name="`!farm <server_id>`", value="Farm authorized members into a server", inline=False)
    embed.add_field(name="`!pool`", value="See how many users have authorized", inline=False)
    embed.add_field(name="`!myauth`", value="Check if you are authorized", inline=False)
    embed.add_field(name="`!access`", value="Show servers the bot is currently in", inline=False)
    embed.add_field(name="`!tutorial`", value="How to use this bot", inline=False)
    embed.set_footer(text="Role Limits: Member 2 | Silver 10 | Gold 15 | Diamond 25 | Premium 35")
    await ctx.send(embed=embed)


@bot.command(name="auth")
async def auth_command(ctx):
    embed = discord.Embed(
        title=f"{EMOJI_AUTH} Authorize Bot",
        description="Click the button below to authorize.\nAfter authorizing, you can be added to servers using `!farm`.",
        color=discord.Color.green()
    )
    embed.set_footer(text="You only need to authorize once")
    await ctx.send(embed=embed, view=AuthButton())


@bot.command(name="addbot")
async def addbot_command(ctx):
    embed = discord.Embed(
        title=f"{EMOJI_BOT} Add Bot",
        description="Click the button below to invite the bot to any server.",
        color=discord.Color.blurple()
    )
    await ctx.send(embed=embed, view=AddBotButton())


@bot.command(name="pool")
async def pool_command(ctx):
    rows = await get_all_authorized()
    embed = discord.Embed(
        title=f"{EMOJI_USERS} Authorization Pool",
        description=f"**Total Authorized Users:** `{len(rows)}`",
        color=discord.Color.gold()
    )
    embed.set_footer(text="These users can be farmed into servers")
    await ctx.send(embed=embed)


@bot.command(name="myauth")
async def myauth_command(ctx):
    token = await get_token(str(ctx.author.id))
    if token:
        embed = discord.Embed(title=f"{EMOJI_SUCCESS} You are Authorized", description="You can be farmed into servers.", color=discord.Color.green())
    else:
        embed = discord.Embed(title=f"{EMOJI_ERROR} Not Authorized", description="Use `!auth` to authorize yourself.", color=discord.Color.red())
    await ctx.send(embed=embed)


@bot.command(name="access")
async def access_command(ctx):
    if not bot.guilds:
        return await ctx.send(f"{EMOJI_ERROR} Bot is not in any servers.")
    
    embed = discord.Embed(title=f"{EMOJI_BOT} Bot Access", description="Servers the bot is currently in:", color=discord.Color.blurple())
    for g in bot.guilds[:15]:
        embed.add_field(name=g.name, value=f"ID: `{g.id}`", inline=False)
    if len(bot.guilds) > 15:
        embed.set_footer(text=f"Showing 15 of {len(bot.guilds)} servers")
    await ctx.send(embed=embed)


@bot.command(name="tutorial")
async def tutorial_command(ctx):
    embed = discord.Embed(
        title=f"{EMOJI_INFO} How to Use This Bot",
        color=discord.Color.purple()
    )
    embed.add_field(name="Step 1", value="Run `!auth` and authorize the bot", inline=False)
    embed.add_field(name="Step 2", value="Get a farming role (Member / Silver / Gold / Diamond / Premium)", inline=False)
    embed.add_field(name="Step 3", value="Use `!addbot` to add the bot to the target server", inline=False)
    embed.add_field(name="Step 4", value="Run `!farm <server_id>` to pull members", inline=False)
    embed.add_field(name="Role Limits", value="Member: 2 | Silver: 10 | Gold: 15 | Diamond: 25 | Premium: 35", inline=False)
    embed.set_footer(text="Need help? Contact the server owner")
    await ctx.send(embed=embed)


@bot.command(name="farm")
@commands.guild_only()
async def farm_command(ctx, server_id: str):
    limit = 0
    matched_role = None
    member_roles = [r.name.lower() for r in ctx.author.roles]

    for role_name, max_count in ROLE_LIMITS.items():
        if role_name in member_roles and max_count > limit:
            limit = max_count
            matched_role = role_name

    if limit == 0:
        embed = discord.Embed(title=f"{EMOJI_ERROR} No Permission", description="You need one of these roles:\n`Member` `Silver` `Gold` `Diamond` `Premium`", color=discord.Color.red())
        return await ctx.send(embed=embed)

    try:
        target_guild = bot.get_guild(int(server_id)) or await bot.fetch_guild(int(server_id))
    except:
        embed = discord.Embed(title=f"{EMOJI_ERROR} Invalid Server", description="Bot is not in that server or ID is wrong.", color=discord.Color.red())
        return await ctx.send(embed=embed)

    authorized = await get_all_authorized()
    if not authorized:
        embed = discord.Embed(title=f"{EMOJI_ERROR} Empty Pool", description="No one has authorized yet. Tell people to use `!auth`", color=discord.Color.red())
        return await ctx.send(embed=embed)

    status_embed = discord.Embed(
        title=f"{EMOJI_LOADING} Farming in Progress",
        description=f"Target: **{target_guild.name}**\nRole: `{matched_role}`\nLimit: `{limit}` members",
        color=discord.Color.orange()
    )
    msg = await ctx.send(embed=status_embed)

    added = failed = already_in = 0

    for user_id, access_token in authorized:
        if added >= limit:
            break
        try:
            member = target_guild.get_member(int(user_id))
            if member is None:
                try:
                    member = await target_guild.fetch_member(int(user_id))
                except discord.NotFound:
                    member = None
            if member:
                already_in += 1
                continue
        except:
            pass

        status, _ = await add_member_to_guild(str(target_guild.id), user_id, access_token)
        if status in (201, 204):
            added += 1
        else:
            failed += 1
            if status == 403:
                await remove_token(user_id)
        await asyncio.sleep(0.5)

    result = discord.Embed(
        title=f"{EMOJI_SUCCESS} Farm Complete",
        color=discord.Color.green()
    )
    result.add_field(name="Server", value=target_guild.name, inline=True)
    result.add_field(name="Added", value=str(added), inline=True)
    result.add_field(name="Already In", value=str(already_in), inline=True)
    result.add_field(name="Failed", value=str(failed), inline=True)
    result.add_field(name="Limit Used", value=f"{added}/{limit}", inline=True)
    result.add_field(name="Role", value=matched_role.title(), inline=True)
    await msg.edit(embed=result)


# -------------------- Main --------------------
async def main():
    await init_db()
    asyncio.create_task(start_web_server())
    async with bot:
        await bot.start(BOT_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
