"""
Discord Member Farm Bot - Advanced + Slash Commands
"""

import os
import asyncio
import aiohttp
from aiohttp import web
import aiosqlite
import discord
from discord.ext import commands
from discord import app_commands
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

# ==================== EMOJIS (Edit these) ====================
E = {
    "success": "✅",
    "error": "❌",
    "loading": "🔄",
    "auth": "🔐",
    "bot": "🤖",
    "users": "👥",
    "info": "ℹ️",
    "help": "📖",
    "farm": "🌾",
    "star": "⭐",
    "role": "🎭"
}

# =================================================

if not all([BOT_TOKEN, CLIENT_ID, CLIENT_SECRET, REDIRECT_URI]):
    raise ValueError("Missing environment variables")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)
bot.remove_command("help")
tree = bot.tree


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


async def save_token(user_id, access_token, refresh_token=None, expires_at=0):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO authorized (user_id, access_token, refresh_token, expires_at) VALUES (?, ?, ?, ?)",
            (user_id, access_token, refresh_token, expires_at)
        )
        await db.commit()


async def get_token(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT access_token FROM authorized WHERE user_id = ?", (user_id,)) as c:
            return await c.fetchone()


async def get_all_authorized():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id, access_token FROM authorized") as c:
            return await c.fetchall()


async def remove_token(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM authorized WHERE user_id = ?", (user_id,))
        await db.commit()


# -------------------- OAuth --------------------
def get_auth_url():
    return f"https://discord.com/api/oauth2/authorize?client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}&response_type=code&scope=identify%20guilds.join"


def get_bot_invite_url():
    return f"https://discord.com/api/oauth2/authorize?client_id={CLIENT_ID}&permissions=8&scope=bot%20applications.commands"


async def exchange_code(code):
    data = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
    }
    async with aiohttp.ClientSession() as s:
        async with s.post("https://discord.com/api/oauth2/token", data=data, headers={"Content-Type": "application/x-www-form-urlencoded"}) as r:
            if r.status != 200:
                raise Exception(await r.text())
            return await r.json()


async def get_user_info(token):
    async with aiohttp.ClientSession() as s:
        async with s.get("https://discord.com/api/users/@me", headers={"Authorization": f"Bearer {token}"}) as r:
            return await r.json() if r.status == 200 else None


async def add_member_to_guild(guild_id, user_id, token):
    url = f"https://discord.com/api/guilds/{guild_id}/members/{user_id}"
    async with aiohttp.ClientSession() as s:
        async with s.put(url, json={"access_token": token}, headers={"Authorization": f"Bot {BOT_TOKEN}", "Content-Type": "application/json"}) as r:
            return r.status, await r.text()


# -------------------- Web Server --------------------
async def handle_callback(request):
    code = request.rel_url.query.get("code")
    if not code:
        return web.Response(text="Failed", status=400)
    try:
        data = await exchange_code(code)
        user = await get_user_info(data["access_token"])
        if not user:
            return web.Response(text="Failed to get user", status=400)
        await save_token(user["id"], data["access_token"], data.get("refresh_token"), data.get("expires_in", 0))
        return web.Response(text=f"✅ Authorized as {user.get('username')}!\nYou can now be farmed.", content_type="text/plain")
    except Exception as e:
        return web.Response(text=str(e), status=500)


async def start_web():
    app = web.Application()
    app.router.add_get("/callback", handle_callback)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", WEB_PORT).start()
    print(f"OAuth running on {WEB_PORT}")


# -------------------- Buttons --------------------
class AuthView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Authorize Now", style=discord.ButtonStyle.green, custom_id="auth_btn")
    async def auth(self, i: discord.Interaction, b: Button):
        await i.response.send_message(f"{E['auth']} **Authorize here:**\n{get_auth_url()}", ephemeral=True)


class AddBotView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Invite Bot", style=discord.ButtonStyle.blurple, custom_id="addbot_btn")
    async def add(self, i: discord.Interaction, b: Button):
        await i.response.send_message(f"{E['bot']} **Invite Link:**\n{get_bot_invite_url()}", ephemeral=True)


# -------------------- Events --------------------
@bot.event
async def on_ready():
    print(f"Online as {bot.user}")
    await init_db()
    bot.add_view(AuthView())
    bot.add_view(AddBotView())
    try:
        synced = await tree.sync()
        print(f"Synced {len(synced)} slash commands")
    except Exception as e:
        print(e)


# -------------------- Prefix Commands --------------------
@bot.command(name="help")
async def help_cmd(ctx):
    embed = discord.Embed(title=f"{E['help']} Bot Help", color=discord.Color.blurple())
    embed.add_field(name="Authorization", value="`!auth` / `/auth` - Authorize yourself\n`!addbot` / `/addbot` - Invite the bot", inline=False)
    embed.add_field(name="Farming", value="`!farm <server_id>` - Farm members\n`!pool` / `/pool` - See authorized count", inline=False)
    embed.add_field(name="Roles", value="`!giverole @user @role`\n`!removerole @user @role`", inline=False)
    embed.add_field(name="Other", value="`!myauth` `/myauth`\n`!access` `/access`\n`!tutorial` `/tutorial`", inline=False)
    embed.set_footer(text="Limits → Member:2 | Silver:10 | Gold:15 | Diamond:25 | Premium:35")
    await ctx.send(embed=embed)


@bot.command(name="auth")
async def auth_cmd(ctx):
    embed = discord.Embed(title=f"{E['auth']} Authorize", description="Click the button to authorize so you can be farmed.", color=discord.Color.green())
    await ctx.send(embed=embed, view=AuthView())


@bot.command(name="addbot")
async def addbot_cmd(ctx):
    embed = discord.Embed(title=f"{E['bot']} Add Bot", description="Invite the bot to any server.", color=discord.Color.blurple())
    await ctx.send(embed=embed, view=AddBotView())


@bot.command(name="pool")
async def pool_cmd(ctx):
    rows = await get_all_authorized()
    embed = discord.Embed(title=f"{E['users']} Authorization Pool", description=f"**Total Authorized:** `{len(rows)}`", color=discord.Color.gold())
    await ctx.send(embed=embed)


@bot.command(name="myauth")
async def myauth_cmd(ctx):
    if await get_token(str(ctx.author.id)):
        embed = discord.Embed(title=f"{E['success']} Authorized", description="You can be farmed.", color=discord.Color.green())
    else:
        embed = discord.Embed(title=f"{E['error']} Not Authorized", description="Use `!auth` first.", color=discord.Color.red())
    await ctx.send(embed=embed)


@bot.command(name="access")
async def access_cmd(ctx):
    embed = discord.Embed(title=f"{E['bot']} Bot Servers", color=discord.Color.blurple())
    for g in bot.guilds[:20]:
        embed.add_field(name=g.name, value=f"`{g.id}`", inline=True)
    await ctx.send(embed=embed)


@bot.command(name="tutorial")
async def tutorial_cmd(ctx):
    embed = discord.Embed(title=f"{E['info']} Tutorial", color=discord.Color.purple())
    embed.add_field(name="1. Authorize", value="Use `!auth` and complete authorization", inline=False)
    embed.add_field(name="2. Get Role", value="Member / Silver / Gold / Diamond / Premium", inline=False)
    embed.add_field(name="3. Add Bot", value="Use `!addbot` in the target server", inline=False)
    embed.add_field(name="4. Farm", value="`!farm server_id`", inline=False)
    await ctx.send(embed=embed)


@bot.command(name="giverole")
@commands.has_permissions(manage_roles=True)
async def giverole_cmd(ctx, member: discord.Member, role: discord.Role):
    await member.add_roles(role)
    embed = discord.Embed(title=f"{E['role']} Role Given", description=f"Gave {role.mention} to {member.mention}", color=discord.Color.green())
    await ctx.send(embed=embed)


@bot.command(name="removerole")
@commands.has_permissions(manage_roles=True)
async def removerole_cmd(ctx, member: discord.Member, role: discord.Role):
    await member.remove_roles(role)
    embed = discord.Embed(title=f"{E['role']} Role Removed", description=f"Removed {role.mention} from {member.mention}", color=discord.Color.orange())
    await ctx.send(embed=embed)


@bot.command(name="farm")
@commands.guild_only()
async def farm_cmd(ctx, server_id: str):
    limit = 0
    matched = None
    roles = [r.name.lower() for r in ctx.author.roles]
    for name, maxc in ROLE_LIMITS.items():
        if name in roles and maxc > limit:
            limit = maxc
            matched = name

    if not limit:
        return await ctx.send(embed=discord.Embed(title=f"{E['error']} No Role", description="You need Member/Silver/Gold/Diamond/Premium role", color=discord.Color.red()))

    try:
        guild = bot.get_guild(int(server_id)) or await bot.fetch_guild(int(server_id))
    except:
        return await ctx.send(embed=discord.Embed(title=f"{E['error']} Invalid", description="Bot not in that server", color=discord.Color.red()))

    auth = await get_all_authorized()
    if not auth:
        return await ctx.send(embed=discord.Embed(title=f"{E['error']} Empty", description="No authorized users", color=discord.Color.red()))

    msg = await ctx.send(embed=discord.Embed(title=f"{E['loading']} Farming...", description=f"Target: **{guild.name}**\nLimit: `{limit}`", color=discord.Color.orange()))

    added = failed = already = 0
    for uid, token in auth:
        if added >= limit:
            break
        try:
            m = guild.get_member(int(uid))
            if not m:
                try:
                    m = await guild.fetch_member(int(uid))
                except:
                    m = None
            if m:
                already += 1
                continue
        except:
            pass

        status, _ = await add_member_to_guild(str(guild.id), uid, token)
        if status in (201, 204):
            added += 1
        else:
            failed += 1
            if status == 403:
                await remove_token(uid)
        await asyncio.sleep(0.4)

    result = discord.Embed(title=f"{E['success']} Farm Done", color=discord.Color.green())
    result.add_field(name="Added", value=str(added))
    result.add_field(name="Already", value=str(already))
    result.add_field(name="Failed", value=str(failed))
    result.add_field(name="Role", value=matched.title())
    await msg.edit(embed=result)


# -------------------- Slash Commands --------------------
@tree.command(name="help", description="Show all bot commands")
async def slash_help(i: discord.Interaction):
    embed = discord.Embed(title=f"{E['help']} Bot Help", color=discord.Color.blurple())
    embed.add_field(name="Main", value="`/auth` `/addbot` `/farm` `/pool`", inline=False)
    embed.add_field(name="Roles", value="`/giverole` `/removerole`", inline=False)
    embed.add_field(name="Other", value="`/myauth` `/access` `/tutorial`", inline=False)
    await i.response.send_message(embed=embed)


@tree.command(name="auth", description="Authorize yourself")
async def slash_auth(i: discord.Interaction):
    embed = discord.Embed(title=f"{E['auth']} Authorize", description="Click the button below", color=discord.Color.green())
    await i.response.send_message(embed=embed, view=AuthView())


@tree.command(name="addbot", description="Get bot invite link")
async def slash_addbot(i: discord.Interaction):
    embed = discord.Embed(title=f"{E['bot']} Invite Bot", color=discord.Color.blurple())
    await i.response.send_message(embed=embed, view=AddBotView())


@tree.command(name="pool", description="See how many users authorized")
async def slash_pool(i: discord.Interaction):
    rows = await get_all_authorized()
    embed = discord.Embed(title=f"{E['users']} Pool", description=f"**{len(rows)}** authorized users", color=discord.Color.gold())
    await i.response.send_message(embed=embed)


@tree.command(name="myauth", description="Check if you are authorized")
async def slash_myauth(i: discord.Interaction):
    if await get_token(str(i.user.id)):
        await i.response.send_message(embed=discord.Embed(title=f"{E['success']} You are authorized", color=discord.Color.green()))
    else:
        await i.response.send_message(embed=discord.Embed(title=f"{E['error']} Not authorized", color=discord.Color.red()))


@tree.command(name="access", description="Show servers bot is in")
async def slash_access(i: discord.Interaction):
    embed = discord.Embed(title=f"{E['bot']} Servers", color=discord.Color.blurple())
    for g in bot.guilds[:15]:
        embed.add_field(name=g.name, value=f"`{g.id}`", inline=True)
    await i.response.send_message(embed=embed)


@tree.command(name="tutorial", description="How to use the bot")
async def slash_tutorial(i: discord.Interaction):
    embed = discord.Embed(title=f"{E['info']} Tutorial", color=discord.Color.purple())
    embed.add_field(name="Steps", value="1. `/auth`\n2. Get farming role\n3. `/addbot`\n4. `!farm server_id`", inline=False)
    await i.response.send_message(embed=embed)


@tree.command(name="giverole", description="Give a role to a member")
@app_commands.describe(member="Member", role="Role to give")
async def slash_giverole(i: discord.Interaction, member: discord.Member, role: discord.Role):
    if not i.user.guild_permissions.manage_roles:
        return await i.response.send_message("No permission", ephemeral=True)
    await member.add_roles(role)
    await i.response.send_message(embed=discord.Embed(title=f"{E['role']} Role Given", description=f"{role.mention} → {member.mention}", color=discord.Color.green()))


@tree.command(name="removerole", description="Remove a role from a member")
@app_commands.describe(member="Member", role="Role to remove")
async def slash_removerole(i: discord.Interaction, member: discord.Member, role: discord.Role):
    if not i.user.guild_permissions.manage_roles:
        return await i.response.send_message("No permission", ephemeral=True)
    await member.remove_roles(role)
    await i.response.send_message(embed=discord.Embed(title=f"{E['role']} Role Removed", description=f"Removed {role.mention} from {member.mention}", color=discord.Color.orange()))


# -------------------- Main --------------------
async def main():
    await init_db()
    asyncio.create_task(start_web())
    async with bot:
        await bot.start(BOT_TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
