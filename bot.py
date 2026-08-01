"""
Discord Member Farm Bot - Advanced Customizable Version
=======================================================
Features:
- Auto "Members" role on authorize
- Customizable embeds (!setembed / /setembed)
- Add/Remove from pool
- Slash + Prefix commands
- Role tier farming limits
"""

import os
import asyncio
import json
import aiohttp
from aiohttp import web
import aiosqlite
import discord
from discord.ext import commands
from discord import app_commands
from discord.ui import View, Button, Modal, TextInput

# ==================== CONFIG ====================
BOT_TOKEN = os.getenv("BOT_TOKEN")
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
REDIRECT_URI = os.getenv("REDIRECT_URI")
WEB_PORT = int(os.getenv("PORT", 8080))

# Auto role + Main server settings
AUTO_ROLE_ID = 1532666234439471270          # Members role ID
MAIN_GUILD_ID = 1532047125742096394         # Your main server (always has access)

ROLE_LIMITS = {
    "member": 2,
    "silver": 10,
    "gold": 15,
    "diamond": 25,
    "premium": 35,
}

DB_PATH = "authorized_users.db"

# Default embeds (edit these with /setembed)
DEFAULT_EMBEDS = {
    "auth": {
        "title": "🔐 Authorize Bot",
        "description": "Click the button below to authorize.\nAfter authorizing you will get the **Members** role and can be farmed.",
        "color": 0x57F287,
        "footer": "You only need to authorize once"
    },
    "help": {
        "title": "📖 Bot Commands",
        "description": "Here are all available commands:",
        "color": 0x5865F2,
        "footer": "Limits → Member:2 | Silver:10 | Gold:15 | Diamond:25 | Premium:35"
    },
    "tutorial": {
        "title": "ℹ️ How to Use This Bot",
        "description": "Follow these simple steps:",
        "color": 0x9B59B6,
        "footer": "Need help? Contact the server owner"
    },
    "pool": {
        "title": "👥 Authorization Pool",
        "description": "Users who have authorized the bot:",
        "color": 0xFEE75C,
        "footer": "These users can be farmed into servers"
    }
}

# =================================================

if not all([BOT_TOKEN, CLIENT_ID, CLIENT_SECRET, REDIRECT_URI]):
    raise ValueError("Missing required environment variables")

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
        await db.execute("""
            CREATE TABLE IF NOT EXISTS embeds (
                name TEXT PRIMARY KEY,
                data TEXT NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS allowed_guilds (
                guild_id TEXT PRIMARY KEY
            )
        """)
        # Always allow main guild
        await db.execute(
            "INSERT OR IGNORE INTO allowed_guilds (guild_id) VALUES (?)",
            (str(MAIN_GUILD_ID),)
        )
        await db.commit()

        for name, data in DEFAULT_EMBEDS.items():
            await db.execute(
                "INSERT OR IGNORE INTO embeds (name, data) VALUES (?, ?)",
                (name, json.dumps(data))
            )
        await db.commit()


async def save_token(user_id: str, access_token: str, refresh_token: str = None, expires_at: int = 0):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO authorized (user_id, access_token, refresh_token, expires_at) VALUES (?, ?, ?, ?)",
            (user_id, access_token, refresh_token, expires_at)
        )
        await db.commit()


async def get_token(user_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT access_token FROM authorized WHERE user_id = ?", (user_id,)) as c:
            return await c.fetchone()


async def get_all_authorized():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id, access_token FROM authorized") as c:
            return await c.fetchall()


async def remove_token(user_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM authorized WHERE user_id = ?", (user_id,))
        await db.commit()


async def is_guild_allowed(guild_id: int) -> bool:
    if guild_id == MAIN_GUILD_ID:
        return True
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT 1 FROM allowed_guilds WHERE guild_id = ?", (str(guild_id),)) as c:
            return await c.fetchone() is not None


async def add_guild_access(guild_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO allowed_guilds (guild_id) VALUES (?)", (guild_id,))
        await db.commit()


async def remove_guild_access(guild_id: str):
    if str(guild_id) == str(MAIN_GUILD_ID):
        return False  # cannot remove main
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM allowed_guilds WHERE guild_id = ?", (guild_id,))
        await db.commit()
    return True


async def get_allowed_guilds():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT guild_id FROM allowed_guilds") as c:
            return [row[0] for row in await c.fetchall()]


async def get_embed(name: str) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT data FROM embeds WHERE name = ?", (name,)) as c:
            row = await c.fetchone()
            if row:
                return json.loads(row[0])
    return DEFAULT_EMBEDS.get(name, {"title": name, "description": "", "color": 0x5865F2})


async def set_embed(name: str, data: dict):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO embeds (name, data) VALUES (?, ?)",
            (name, json.dumps(data))
        )
        await db.commit()


# -------------------- OAuth Helpers --------------------
def get_auth_url():
    return (
        f"https://discord.com/api/oauth2/authorize"
        f"?client_id={CLIENT_ID}"
        f"&redirect_uri={REDIRECT_URI}"
        f"&response_type=code"
        f"&scope=identify%20guilds.join"
    )


def get_bot_invite_url():
    return (
        f"https://discord.com/api/oauth2/authorize"
        f"?client_id={CLIENT_ID}"
        f"&permissions=8"
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
                raise Exception(await resp.text())
            return await resp.json()


async def get_user_info(access_token: str):
    headers = {"Authorization": f"Bearer {access_token}"}
    async with aiohttp.ClientSession() as session:
        async with session.get("https://discord.com/api/users/@me", headers=headers) as resp:
            return await resp.json() if resp.status == 200 else None


async def add_member_to_guild(guild_id: str, user_id: str, access_token: str):
    url = f"https://discord.com/api/guilds/{guild_id}/members/{user_id}"
    headers = {
        "Authorization": f"Bot {BOT_TOKEN}",
        "Content-Type": "application/json",
    }
    async with aiohttp.ClientSession() as session:
        async with session.put(url, json={"access_token": access_token}, headers=headers) as resp:
            return resp.status, await resp.text()


# -------------------- Auto Role --------------------
async def give_members_role(user_id: str):
    """Give the Members role (by ID) to the user in the main server"""
    try:
        guild = bot.get_guild(MAIN_GUILD_ID)
        if guild is None:
            try:
                guild = await bot.fetch_guild(MAIN_GUILD_ID)
            except Exception as e:
                print(f"[AUTO-ROLE] Cannot fetch main guild: {e}")
                return

        role = guild.get_role(AUTO_ROLE_ID)
        if role is None:
            print(f"[AUTO-ROLE] Role ID {AUTO_ROLE_ID} not found in {guild.name}")
            print(f"[AUTO-ROLE] Available roles: {[r.name for r in guild.roles]}")
            return

        # Check bot hierarchy
        bot_member = guild.get_member(bot.user.id)
        if bot_member is None:
            print(f"[AUTO-ROLE] Bot is not a member of {guild.name}")
            return
        if role >= bot_member.top_role:
            print(f"[AUTO-ROLE] Bot role is too low! Move bot role ABOVE '{role.name}'")
            return
        if not bot_member.guild_permissions.manage_roles:
            print(f"[AUTO-ROLE] Bot missing Manage Roles permission in {guild.name}")
            return

        member = guild.get_member(int(user_id))
        if member is None:
            try:
                member = await guild.fetch_member(int(user_id))
            except discord.NotFound:
                print(f"[AUTO-ROLE] User {user_id} is NOT in {guild.name} - cannot give role")
                return

        if role in member.roles:
            print(f"[AUTO-ROLE] User {user_id} already has {role.name}")
            return

        await member.add_roles(role, reason="Authorized the farm bot")
        print(f"[AUTO-ROLE] SUCCESS: Gave '{role.name}' to {member} in {guild.name}")
    except Exception as e:
        print(f"[AUTO-ROLE] ERROR: {e}")
        import traceback
        traceback.print_exc()


# -------------------- Web Server --------------------
async def handle_callback(request):
    code = request.rel_url.query.get("code")
    if not code:
        return web.Response(text="❌ Authorization failed - no code.", status=400)

    try:
        token_data = await exchange_code(code)
        access_token = token_data["access_token"]
        user = await get_user_info(access_token)
        if not user:
            return web.Response(text="❌ Failed to get user info.", status=400)

        user_id = user["id"]
        await save_token(
            user_id,
            access_token,
            token_data.get("refresh_token"),
            token_data.get("expires_in", 0)
        )

        # Auto give Members role
        await give_members_role(user_id)

        username = user.get("username", "Unknown")
        return web.Response(
            text=f"✅ Successfully authorized as **{username}**!\n\nYou have been given the Members role (if possible) and can now be farmed.",
            content_type="text/plain"
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
    print(f"🌐 OAuth callback running on port {WEB_PORT}")


# -------------------- Buttons --------------------
class AuthView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Authorize Now", style=discord.ButtonStyle.green, custom_id="persistent_auth")
    async def auth_button(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_message(
            f"🔐 **Click the link below to authorize:**\n{get_auth_url()}",
            ephemeral=True
        )


class AddBotView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Invite Bot", style=discord.ButtonStyle.blurple, custom_id="persistent_addbot")
    async def addbot_button(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_message(
            f"🤖 **Bot Invite Link:**\n{get_bot_invite_url()}",
            ephemeral=True
        )


# -------------------- Embed Editor Modal --------------------
class EmbedEditModal(Modal, title="Edit Embed"):
    def __init__(self, embed_name: str, current: dict):
        super().__init__()
        self.embed_name = embed_name

        self.title_input = TextInput(
            label="Title",
            default=current.get("title", ""),
            max_length=256,
            required=True
        )
        self.desc_input = TextInput(
            label="Description",
            default=current.get("description", ""),
            style=discord.TextStyle.paragraph,
            max_length=2000,
            required=True
        )
        self.footer_input = TextInput(
            label="Footer (optional)",
            default=current.get("footer", ""),
            max_length=2048,
            required=False
        )
        self.color_input = TextInput(
            label="Color (hex without #, e.g. 57F287)",
            default=format(current.get("color", 0x5865F2), "X"),
            max_length=6,
            required=False
        )

        self.add_item(self.title_input)
        self.add_item(self.desc_input)
        self.add_item(self.footer_input)
        self.add_item(self.color_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            color = int(self.color_input.value or "5865F2", 16)
        except ValueError:
            color = 0x5865F2

        new_data = {
            "title": self.title_input.value,
            "description": self.desc_input.value,
            "footer": self.footer_input.value,
            "color": color
        }
        await set_embed(self.embed_name, new_data)

        embed = discord.Embed(
            title=new_data["title"],
            description=new_data["description"],
            color=color
        )
        if new_data.get("footer"):
            embed.set_footer(text=new_data["footer"])

        await interaction.response.send_message(
            content=f"✅ Embed `{self.embed_name}` updated!",
            embed=embed,
            ephemeral=True
        )


# -------------------- Events --------------------
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user} (ID: {bot.user.id})")
    await init_db()
    bot.add_view(AuthView())
    bot.add_view(AddBotView())
    try:
        synced = await tree.sync()
        print(f"✅ Synced {len(synced)} slash commands")
    except Exception as e:
        print(f"Slash sync error: {e}")


@bot.check
async def global_guild_check(ctx: commands.Context):
    """Only allow commands in servers that have access"""
    if ctx.guild is None:
        return True  # allow DMs for now
    if await is_guild_allowed(ctx.guild.id):
        return True
    await ctx.send("❌ This server does not have access to use the bot.\nAsk the bot owner to use `!addaccess` first.")
    return False


# -------------------- Prefix Commands --------------------
@bot.command(name="help")
async def help_command(ctx: commands.Context):
    data = await get_embed("help")
    embed = discord.Embed(
        title=data["title"],
        description=data["description"],
        color=data.get("color", 0x5865F2)
    )
    embed.add_field(name="🔐 Authorization", value="`!auth` `/auth` - Authorize yourself\n`!addbot` `/addbot` - Invite the bot", inline=False)
    embed.add_field(name="🌾 Farming", value="`!farm <server_id>` - Farm members\n`!pool` `/pool` - See authorized count", inline=False)
    embed.add_field(name="👥 Pool Management", value="`!addpool <user_id>` / `!removepool <user_id>`\n`!backup` - Download authorized list", inline=False)
    embed.add_field(name="🔓 Server Access", value="`!addaccess <server_id>` - Allow server\n`!removeaccess <server_id>` - Remove access\n`!accesslist` - Show allowed servers", inline=False)
    embed.add_field(name="🎭 Roles", value="`!giverole @user @role`\n`!removerole @user @role`", inline=False)
    embed.add_field(name="✏️ Customize", value="`/setembed` - Edit any embed\nAvailable: `auth`, `help`, `tutorial`, `pool`", inline=False)
    embed.add_field(name="Other", value="`!myauth` `!access` `!tutorial`", inline=False)
    if data.get("footer"):
        embed.set_footer(text=data["footer"])
    await ctx.send(embed=embed)


@bot.command(name="auth")
async def auth_command(ctx: commands.Context):
    data = await get_embed("auth")
    embed = discord.Embed(
        title=data["title"],
        description=data["description"],
        color=data.get("color", 0x57F287)
    )
    if data.get("footer"):
        embed.set_footer(text=data["footer"])
    await ctx.send(embed=embed, view=AuthView())


@bot.command(name="addbot")
async def addbot_command(ctx: commands.Context):
    embed = discord.Embed(
        title="🤖 Add Bot to Server",
        description="Click the button below to invite the bot to any server.",
        color=discord.Color.blurple()
    )
    await ctx.send(embed=embed, view=AddBotView())


@bot.command(name="pool")
async def pool_command(ctx: commands.Context):
    rows = await get_all_authorized()
    data = await get_embed("pool")
    embed = discord.Embed(
        title=data["title"],
        description=f"{data['description']}\n\n**Total Authorized Users:** `{len(rows)}`",
        color=data.get("color", 0xFEE75C)
    )
    if data.get("footer"):
        embed.set_footer(text=data["footer"])
    await ctx.send(embed=embed)


@bot.command(name="myauth")
async def myauth_command(ctx: commands.Context):
    token = await get_token(str(ctx.author.id))
    if token:
        embed = discord.Embed(title="✅ You are Authorized", description="You can be farmed into servers.", color=discord.Color.green())
    else:
        embed = discord.Embed(title="❌ Not Authorized", description="Use `!auth` to authorize yourself.", color=discord.Color.red())
    await ctx.send(embed=embed)


@bot.command(name="access")
async def access_command(ctx: commands.Context):
    if not bot.guilds:
        return await ctx.send("❌ Bot is not in any servers.")
    embed = discord.Embed(title="🤖 Bot Access", description="Servers the bot is currently in:", color=discord.Color.blurple())
    for g in bot.guilds[:20]:
        embed.add_field(name=g.name, value=f"ID: `{g.id}`", inline=True)
    await ctx.send(embed=embed)


@bot.command(name="tutorial")
async def tutorial_command(ctx: commands.Context):
    data = await get_embed("tutorial")
    embed = discord.Embed(
        title=data["title"],
        description=data["description"],
        color=data.get("color", 0x9B59B6)
    )
    embed.add_field(name="Step 1", value="Run `!auth` and authorize the bot", inline=False)
    embed.add_field(name="Step 2", value="You will automatically get the **Members** role", inline=False)
    embed.add_field(name="Step 3", value="Use `!addbot` to add the bot to the target server", inline=False)
    embed.add_field(name="Step 4", value="Run `!farm <server_id>` to pull members", inline=False)
    embed.add_field(name="Role Limits", value="Member: 2 | Silver: 10 | Gold: 15 | Diamond: 25 | Premium: 35", inline=False)
    if data.get("footer"):
        embed.set_footer(text=data["footer"])
    await ctx.send(embed=embed)


@bot.command(name="addpool")
@commands.has_permissions(administrator=True)
async def addpool_command(ctx: commands.Context, user_id: str):
    await save_token(user_id, "MANUAL_PLACEHOLDER")
    embed = discord.Embed(
        title="✅ Added to Pool",
        description=f"User `{user_id}` has been added to the pool.\n\nNote: They still need to authorize properly to be farmable.",
        color=discord.Color.green()
    )
    await ctx.send(embed=embed)


@bot.command(name="removepool")
@commands.has_permissions(administrator=True)
async def removepool_command(ctx: commands.Context, user_id: str):
    await remove_token(user_id)
    embed = discord.Embed(
        title="🗑️ Removed from Pool",
        description=f"User `{user_id}` has been removed from the authorization pool.",
        color=discord.Color.orange()
    )
    await ctx.send(embed=embed)


@bot.command(name="backup")
@commands.has_permissions(administrator=True)
async def backup_command(ctx: commands.Context):
    """Export all authorized user IDs to a file"""
    rows = await get_all_authorized()
    if not rows:
        return await ctx.send("❌ Pool is empty. Nothing to backup.")

    # Create backup content
    lines = ["# Authorized Users Backup", f"# Total: {len(rows)}", f"# Date: {__import__('datetime').datetime.utcnow().isoformat()}", ""]
    for user_id, token in rows:
        lines.append(user_id)

    content = "\n".join(lines)
    file = discord.File(fp=__import__('io').BytesIO(content.encode()), filename="authorized_backup.txt")

    embed = discord.Embed(
        title="📦 Backup Created",
        description=f"**{len(rows)}** authorized users exported.\nDownload the file and keep it safe.",
        color=discord.Color.green()
    )
    await ctx.send(embed=embed, file=file)



@bot.command(name="addaccess")
@commands.has_permissions(administrator=True)
async def addaccess_command(ctx: commands.Context, server_id: str):
    """Allow a server to use the bot"""
    await add_guild_access(server_id)
    embed = discord.Embed(
        title="✅ Access Granted",
        description=f"Server `{server_id}` can now use the bot.",
        color=discord.Color.green()
    )
    await ctx.send(embed=embed)


@bot.command(name="removeaccess")
@commands.has_permissions(administrator=True)
async def removeaccess_command(ctx: commands.Context, server_id: str):
    """Remove a server's access to the bot"""
    ok = await remove_guild_access(server_id)
    if not ok:
        return await ctx.send("❌ Cannot remove access from the main server.")
    embed = discord.Embed(
        title="🗑️ Access Removed",
        description=f"Server `{server_id}` can no longer use the bot.",
        color=discord.Color.orange()
    )
    await ctx.send(embed=embed)


@bot.command(name="accesslist")
@commands.has_permissions(administrator=True)
async def accesslist_command(ctx: commands.Context):
    """Show all servers that have access"""
    guilds = await get_allowed_guilds()
    embed = discord.Embed(title="🔓 Allowed Servers", color=discord.Color.blurple())
    if not guilds:
        embed.description = "No servers have access yet."
    else:
        for gid in guilds:
            name = "Main Server" if str(gid) == str(MAIN_GUILD_ID) else "Unknown"
            g = bot.get_guild(int(gid))
            if g:
                name = g.name
            embed.add_field(name=name, value=f"`{gid}`", inline=False)
    await ctx.send(embed=embed)


@bot.command(name="giverole")
@commands.has_permissions(manage_roles=True)
async def giverole_command(ctx: commands.Context, member: discord.Member, role: discord.Role):
    await member.add_roles(role)
    embed = discord.Embed(title="🎭 Role Given", description=f"Gave {role.mention} to {member.mention}", color=discord.Color.green())
    await ctx.send(embed=embed)


@bot.command(name="removerole")
@commands.has_permissions(manage_roles=True)
async def removerole_command(ctx: commands.Context, member: discord.Member, role: discord.Role):
    await member.remove_roles(role)
    embed = discord.Embed(title="🎭 Role Removed", description=f"Removed {role.mention} from {member.mention}", color=discord.Color.orange())
    await ctx.send(embed=embed)


@bot.command(name="farm")
@commands.guild_only()
async def farm_command(ctx: commands.Context, server_id: str):
    limit = 0
    matched_role = None
    member_roles = [r.name.lower() for r in ctx.author.roles]

    for role_name, max_count in ROLE_LIMITS.items():
        if role_name in member_roles and max_count > limit:
            limit = max_count
            matched_role = role_name

    if limit == 0:
        embed = discord.Embed(
            title="❌ No Permission",
            description="You need one of these roles:\n`Member` `Silver` `Gold` `Diamond` `Premium`",
            color=discord.Color.red()
        )
        return await ctx.send(embed=embed)

    try:
        target_guild = bot.get_guild(int(server_id))
        if target_guild is None:
            target_guild = await bot.fetch_guild(int(server_id))
    except Exception:
        embed = discord.Embed(title="❌ Invalid Server", description="Bot is not in that server or ID is wrong.", color=discord.Color.red())
        return await ctx.send(embed=embed)

    authorized = await get_all_authorized()
    authorized = [(uid, tok) for uid, tok in authorized if tok != "MANUAL_PLACEHOLDER"]

    if not authorized:
        embed = discord.Embed(title="❌ Empty Pool", description="No one has authorized yet.\nTell people to use `!auth`", color=discord.Color.red())
        return await ctx.send(embed=embed)

    status_embed = discord.Embed(
        title="🔄 Farming in Progress",
        description=f"**Target:** {target_guild.name}\n**Role:** `{matched_role}`\n**Limit:** `{limit}` members",
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
            if member is not None:
                already_in += 1
                continue
        except Exception:
            pass

        status, _ = await add_member_to_guild(str(target_guild.id), user_id, access_token)

        if status in (201, 204):
            added += 1
        else:
            failed += 1
            if status == 403:
                await remove_token(user_id)

        await asyncio.sleep(0.45)

    result = discord.Embed(title="✅ Farm Complete", color=discord.Color.green())
    result.add_field(name="Server", value=target_guild.name, inline=True)
    result.add_field(name="Added", value=str(added), inline=True)
    result.add_field(name="Already In", value=str(already_in), inline=True)
    result.add_field(name="Failed", value=str(failed), inline=True)
    result.add_field(name="Limit Used", value=f"{added}/{limit}", inline=True)
    result.add_field(name="Your Role", value=matched_role.title(), inline=True)
    await msg.edit(embed=result)


# -------------------- Slash Commands --------------------
@tree.command(name="help", description="Show all bot commands")
async def slash_help(interaction: discord.Interaction):
    data = await get_embed("help")
    embed = discord.Embed(title=data["title"], description=data["description"], color=data.get("color", 0x5865F2))
    embed.add_field(name="Main", value="`/auth` `/addbot` `/farm` `/pool`", inline=False)
    embed.add_field(name="Pool", value="`/addpool` `/removepool`", inline=False)
    embed.add_field(name="Customize", value="`/setembed`", inline=False)
    if data.get("footer"):
        embed.set_footer(text=data["footer"])
    await interaction.response.send_message(embed=embed)


@tree.command(name="auth", description="Authorize yourself")
async def slash_auth(interaction: discord.Interaction):
    data = await get_embed("auth")
    embed = discord.Embed(title=data["title"], description=data["description"], color=data.get("color", 0x57F287))
    if data.get("footer"):
        embed.set_footer(text=data["footer"])
    await interaction.response.send_message(embed=embed, view=AuthView())


@tree.command(name="addbot", description="Get bot invite link")
async def slash_addbot(interaction: discord.Interaction):
    embed = discord.Embed(title="🤖 Invite Bot", description="Click the button to invite the bot.", color=discord.Color.blurple())
    await interaction.response.send_message(embed=embed, view=AddBotView())


@tree.command(name="pool", description="See how many users authorized")
async def slash_pool(interaction: discord.Interaction):
    rows = await get_all_authorized()
    data = await get_embed("pool")
    embed = discord.Embed(
        title=data["title"],
        description=f"**Total Authorized:** `{len(rows)}`",
        color=data.get("color", 0xFEE75C)
    )
    await interaction.response.send_message(embed=embed)


@tree.command(name="myauth", description="Check if you are authorized")
async def slash_myauth(interaction: discord.Interaction):
    if await get_token(str(interaction.user.id)):
        await interaction.response.send_message(embed=discord.Embed(title="✅ You are authorized", color=discord.Color.green()))
    else:
        await interaction.response.send_message(embed=discord.Embed(title="❌ Not authorized", description="Use `/auth`", color=discord.Color.red()))


@tree.command(name="setembed", description="Edit any bot embed (Admin only)")
@app_commands.describe(name="Which embed to edit")
@app_commands.choices(name=[
    app_commands.Choice(name="auth", value="auth"),
    app_commands.Choice(name="help", value="help"),
    app_commands.Choice(name="tutorial", value="tutorial"),
    app_commands.Choice(name="pool", value="pool"),
])
async def slash_setembed(interaction: discord.Interaction, name: str):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("❌ Admin only.", ephemeral=True)

    current = await get_embed(name)
    modal = EmbedEditModal(name, current)
    await interaction.response.send_modal(modal)


@tree.command(name="addpool", description="Manually add user to pool (Admin)")
@app_commands.describe(user_id="Discord User ID")
async def slash_addpool(interaction: discord.Interaction, user_id: str):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("❌ Admin only.", ephemeral=True)
    await save_token(user_id, "MANUAL_PLACEHOLDER")
    await interaction.response.send_message(f"✅ Added `{user_id}` to pool.", ephemeral=True)


@tree.command(name="removepool", description="Remove user from pool (Admin)")
@app_commands.describe(user_id="Discord User ID")
async def slash_removepool(interaction: discord.Interaction, user_id: str):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("❌ Admin only.", ephemeral=True)
    await remove_token(user_id)
    await interaction.response.send_message(f"🗑️ Removed `{user_id}` from pool.", ephemeral=True)


@tree.command(name="backup", description="Backup all authorized users (Admin)")
async def slash_backup(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("❌ Admin only.", ephemeral=True)

    rows = await get_all_authorized()
    if not rows:
        return await interaction.response.send_message("❌ Pool is empty.", ephemeral=True)

    lines = ["# Authorized Users Backup", f"# Total: {len(rows)}", f"# Date: {__import__('datetime').datetime.utcnow().isoformat()}", ""]
    for user_id, token in rows:
        lines.append(user_id)

    content = "\n".join(lines)
    file = discord.File(fp=__import__('io').BytesIO(content.encode()), filename="authorized_backup.txt")

    embed = discord.Embed(
        title="📦 Backup Created",
        description=f"**{len(rows)}** authorized users exported.\nDownload and keep this file safe.",
        color=discord.Color.green()
    )
    await interaction.response.send_message(embed=embed, file=file, ephemeral=True)


@tree.command(name="tutorial", description="How to use the bot")
async def slash_tutorial(interaction: discord.Interaction):
    data = await get_embed("tutorial")
    embed = discord.Embed(title=data["title"], description=data["description"], color=data.get("color", 0x9B59B6))
    embed.add_field(name="Steps", value="1. `/auth`\n2. Get Members role automatically\n3. `/addbot`\n4. `!farm server_id`", inline=False)
    await interaction.response.send_message(embed=embed)


@tree.command(name="addaccess", description="Allow a server to use the bot (Admin)")
@app_commands.describe(server_id="Server ID to allow")
async def slash_addaccess(interaction: discord.Interaction, server_id: str):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("❌ Admin only.", ephemeral=True)
    await add_guild_access(server_id)
    await interaction.response.send_message(f"✅ Server `{server_id}` now has access.", ephemeral=True)


@tree.command(name="removeaccess", description="Remove a server's access (Admin)")
@app_commands.describe(server_id="Server ID to remove")
async def slash_removeaccess(interaction: discord.Interaction, server_id: str):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("❌ Admin only.", ephemeral=True)
    ok = await remove_guild_access(server_id)
    if not ok:
        return await interaction.response.send_message("❌ Cannot remove main server.", ephemeral=True)
    await interaction.response.send_message(f"🗑️ Access removed from `{server_id}`.", ephemeral=True)


@tree.command(name="accesslist", description="Show servers that have access (Admin)")
async def slash_accesslist(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("❌ Admin only.", ephemeral=True)
    guilds = await get_allowed_guilds()
    embed = discord.Embed(title="🔓 Allowed Servers", color=discord.Color.blurple())
    for gid in guilds:
        name = "Main Server" if str(gid) == str(MAIN_GUILD_ID) else "Unknown"
        g = bot.get_guild(int(gid))
        if g:
            name = g.name
        embed.add_field(name=name, value=f"`{gid}`", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)


# -------------------- Main --------------------
async def main():
    await init_db()
    asyncio.create_task(start_web_server())
    async with bot:
        await bot.start(BOT_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
