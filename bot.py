"""
Discord Member Farm Bot - Railway Ready
=======================================
Commands:
  !lauth          → Buttons: Add Bot | Auth Bot
  !farm <server_id> → Pull authorized members (limited by role tier)
  !authcheck      → How many users authorized
  !myauth         → Check if you authorized

Role Tiers (case-insensitive):
  Member   → 2
  Silver   → 10
  Gold     → 15
  Diamond  → 25
  Premium  → 35
"""

import os
import asyncio
import aiohttp
from aiohttp import web
import aiosqlite
import discord
from discord.ext import commands
from discord.ui import View, Button

# ==================== CONFIG (from Railway Variables) ====================
BOT_TOKEN = os.getenv("BOT_TOKEN")
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
REDIRECT_URI = os.getenv("REDIRECT_URI")  # Example: https://your-app.up.railway.app/callback
WEB_PORT = int(os.getenv("PORT", 8080))   # Railway sets PORT automatically

# Role name → max members per !farm
ROLE_LIMITS = {
    "member": 2,
    "silver": 10,
    "gold": 15,
    "diamond": 25,
    "premium": 35,
}

DB_PATH = "authorized_users.db"

# ========================================================================

if not all([BOT_TOKEN, CLIENT_ID, CLIENT_SECRET, REDIRECT_URI]):
    raise ValueError("Missing required environment variables: BOT_TOKEN, CLIENT_ID, CLIENT_SECRET, REDIRECT_URI")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)


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
            """
            INSERT OR REPLACE INTO authorized (user_id, access_token, refresh_token, expires_at)
            VALUES (?, ?, ?, ?)
            """,
            (user_id, access_token, refresh_token, expires_at),
        )
        await db.commit()


async def get_token(user_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT access_token, refresh_token, expires_at FROM authorized WHERE user_id = ?",
            (user_id,),
        ) as cursor:
            return await cursor.fetchone()


async def get_all_authorized():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id, access_token FROM authorized") as cursor:
            return await cursor.fetchall()


async def remove_token(user_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM authorized WHERE user_id = ?", (user_id,))
        await db.commit()


# -------------------- OAuth2 Helpers --------------------
def get_auth_url():
    scopes = "identify%20guilds.join"
    return (
        f"https://discord.com/api/oauth2/authorize"
        f"?client_id={CLIENT_ID}"
        f"&redirect_uri={REDIRECT_URI}"
        f"&response_type=code"
        f"&scope={scopes}"
    )


def get_bot_invite_url():
    permissions = 8  # Administrator
    return (
        f"https://discord.com/api/oauth2/authorize"
        f"?client_id={CLIENT_ID}"
        f"&permissions={permissions}"
        f"&scope=bot%20applications.commands"
    )


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
                text = await resp.text()
                raise Exception(f"Token exchange failed: {resp.status} {text}")
            return await resp.json()


async def get_user_info(access_token: str):
    headers = {"Authorization": f"Bearer {access_token}"}
    async with aiohttp.ClientSession() as session:
        async with session.get("https://discord.com/api/users/@me", headers=headers) as resp:
            if resp.status != 200:
                return None
            return await resp.json()


async def add_member_to_guild(guild_id: str, user_id: str, access_token: str):
    url = f"https://discord.com/api/guilds/{guild_id}/members/{user_id}"
    headers = {
        "Authorization": f"Bot {BOT_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {"access_token": access_token}
    async with aiohttp.ClientSession() as session:
        async with session.put(url, json=payload, headers=headers) as resp:
            return resp.status, await resp.text()


# -------------------- Web Server (OAuth Callback) --------------------
async def handle_callback(request):
    code = request.rel_url.query.get("code")
    if not code:
        return web.Response(text="❌ No code provided. Authorization failed.", status=400)

    try:
        token_data = await exchange_code(code)
        access_token = token_data["access_token"]
        refresh_token = token_data.get("refresh_token")
        expires_in = token_data.get("expires_in", 0)

        user = await get_user_info(access_token)
        if not user:
            return web.Response(text="❌ Failed to fetch user info.", status=400)

        user_id = user["id"]
        await save_token(user_id, access_token, refresh_token, expires_in)

        username = user.get("username", "Unknown")
        return web.Response(
            text=f"✅ Successfully authorized!\n\nUser: {username} ({user_id})\n\nYou can now be added to servers via the !farm command.",
            content_type="text/plain",
        )
    except Exception as e:
        return web.Response(text=f"❌ Error: {str(e)}", status=500)


async def start_web_server():
    app = web.Application()
    app.router.add_get("/callback", handle_callback)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", WEB_PORT)
    await site.start()
    print(f"🌐 OAuth callback server running on port {WEB_PORT}")


# -------------------- UI Buttons --------------------
class AuthView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Add Bot", style=discord.ButtonStyle.primary, custom_id="add_bot")
    async def add_bot_button(self, interaction: discord.Interaction, button: Button):
        invite = get_bot_invite_url()
        await interaction.response.send_message(
            f"🔗 **Add the bot to your server:**\n{invite}",
            ephemeral=True,
        )

    @discord.ui.button(label="Auth Bot", style=discord.ButtonStyle.success, custom_id="auth_bot")
    async def auth_bot_button(self, interaction: discord.Interaction, button: Button):
        auth_url = get_auth_url()
        await interaction.response.send_message(
            f"🔐 **Authorize the bot** (required so you can be farmed into servers):\n{auth_url}\n\n"
            "After authorizing, you will be able to be added via `!farm`.",
            ephemeral=True,
        )


# -------------------- Commands --------------------
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user} (ID: {bot.user.id})")
    await init_db()
    bot.add_view(AuthView())


@bot.command(name="lauth")
async def lauth(ctx: commands.Context):
    """Show buttons to add the bot or authorize it."""
    embed = discord.Embed(
        title="Bot Authorization",
        description=(
            "**Add Bot** → Invite this bot to a server.\n"
            "**Auth Bot** → Authorize so you can be added to servers with `!farm`.\n\n"
            "You must authorize before you can be farmed."
        ),
        color=discord.Color.blurple(),
    )
    await ctx.send(embed=embed, view=AuthView())


@bot.command(name="farm")
@commands.guild_only()
async def farm(ctx: commands.Context, server_id: str):
    """
    Farm authorized members into the given server.
    Usage: !farm <server_id>
    Limit depends on your highest matching role tier.
    """
    limit = 0
    matched_role = None
    member_roles = [r.name.lower() for r in ctx.author.roles]

    for role_name, max_count in ROLE_LIMITS.items():
        if role_name in member_roles:
            if max_count > limit:
                limit = max_count
                matched_role = role_name

    if limit == 0:
        await ctx.send(
            "❌ You don't have a valid farming role.\n"
            "Required roles: Member (2), Silver (10), Gold (15), Diamond (25), Premium (35)"
        )
        return

    try:
        target_guild = bot.get_guild(int(server_id))
        if target_guild is None:
            target_guild = await bot.fetch_guild(int(server_id))
    except Exception:
        await ctx.send("❌ Invalid server ID or bot is not in that server.")
        return

    if target_guild is None:
        await ctx.send("❌ Bot is not in the target server. Add the bot first.")
        return

    authorized = await get_all_authorized()
    if not authorized:
        await ctx.send("❌ No authorized users found. People need to use the Auth Bot button first.")
        return

    await ctx.send(
        f"🔄 Farming up to **{limit}** members into **{target_guild.name}** "
        f"(role: {matched_role})..."
    )

    added = 0
    failed = 0
    already_in = 0

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
            if member is not None:
                already_in += 1
                continue
        except Exception:
            pass

        status, response_text = await add_member_to_guild(str(target_guild.id), user_id, access_token)

        if status in (201, 204):
            added += 1
        else:
            failed += 1
            if status == 403 or "invalid" in response_text.lower():
                await remove_token(user_id)

        await asyncio.sleep(0.5)

    await ctx.send(
        f"✅ **Farm complete** for `{target_guild.name}`\n"
        f"• Added: **{added}**\n"
        f"• Already in server: **{already_in}**\n"
        f"• Failed: **{failed}**\n"
        f"• Limit used: {added}/{limit} (role: {matched_role})"
    )


@bot.command(name="authcheck")
async def authcheck(ctx: commands.Context):
    """Check how many users have authorized the bot."""
    rows = await get_all_authorized()
    await ctx.send(f"📊 Currently **{len(rows)}** users have authorized the bot.")


@bot.command(name="myauth")
async def myauth(ctx: commands.Context):
    """Check if you have authorized the bot."""
    token = await get_token(str(ctx.author.id))
    if token:
        await ctx.send("✅ You are authorized and can be farmed.")
    else:
        await ctx.send("❌ You are **not** authorized. Use `!lauth` → Auth Bot.")


# -------------------- Main --------------------
async def main():
    await init_db()
    asyncio.create_task(start_web_server())
    async with bot:
        await bot.start(BOT_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
