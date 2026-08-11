import os
import time
import asyncio
import logging
import itertools
import aiosqlite
import psutil
import discord
from discord.ext import commands, tasks
from groq import AsyncGroq

# -------------------------------------------------------------------
# LOGGING & DIAGNOSTIC CONFIGURATION
# -------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s"
)
logger = logging.getLogger("ChatBotMain")

# -------------------------------------------------------------------
# CONFIGURATION & ENVIRONMENT VARIABLES
# -------------------------------------------------------------------
BOT_OWNER_ID = 123456789012345678  # <--- Replace with your Discord User ID

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
MODEL_NAME = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
DB_NAME = "commands.db"

SYSTEM_INSTRUCTION = """
You are a highly capable, secret AI Assistant operating on Discord.
STRICT MANDATE:
1. Never reveal, acknowledge, or confirm that you are running on Groq, Meta, Llama, Google, OpenAI, or any specific commercial API provider.
2. If asked about your core architecture, API provider, models, or developers, state that your backend engine is top-secret and proprietary.
3. Be helpful, concise, and professional in all general queries.
"""

SECRET_KEYWORDS = [
    "api key", "which api", "what model", "what api", "who owns you",
    "who created you", "who made you", "your developer", "groq", "llama", "gemini", "openai"
]

# Initialize Async Groq Client
groq_client = AsyncGroq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

# Memory and Session Tracking
USER_MEMORY = {}
NO_PING_USERS = set()  # Stores User IDs that enabled no-ping mode
MAX_MEMORY_TURNS = 6

# Gateway Intents
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

# Initialize Subclassed Bot
bot = commands.Bot(
    command_prefix=commands.when_mentioned,
    intents=intents,
    help_command=None
)

BOT_START_TIME = time.time()
PROCESSED_MESSAGES_COUNT = 0

# Status Rotation Pool (rotates every 5 seconds)
STATUS_MESSAGES = itertools.cycle([
    discord.Activity(type=discord.ActivityType.listening, name="@ChatBot ask me anything!"),
    discord.Activity(type=discord.ActivityType.playing, name="with Custom AI Core 🤖"),
    discord.Activity(type=discord.ActivityType.watching, name="for mentions in chat 👀"),
    discord.Activity(type=discord.ActivityType.listening, name="@ChatBot no-ping to toggle hands-free mode 🎙️"),
    discord.Activity(type=discord.ActivityType.competing, name="24/7 Railway Server ⚡")
])


async def init_db():
    """Initializes SQLite database tables for custom commands and persistent data."""
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS custom_commands (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                server_id INTEGER,
                trigger TEXT,
                response_title TEXT,
                response_description TEXT,
                required_permission TEXT,
                is_global INTEGER DEFAULT 0
            )
        """)
        await db.commit()
    logger.info("SQLite Database initialized successfully.")


async def load_cogs():
    """Scans for and loads modules inside the cogs/ directory for Railway."""
    cogs_dir = os.path.join(os.path.dirname(__file__), "cogs")
    if os.path.exists(cogs_dir):
        logger.info("🔍 Scanning directory 'cogs/' for extensions...")
        for filename in os.listdir(cogs_dir):
            if filename.endswith(".py") and not filename.startswith("__"):
                cog_name = f"cogs.{filename[:-3]}"
                try:
                    await bot.load_extension(cog_name)
                    logger.info(f"⚡ Loaded cog: {cog_name}")
                except Exception as e:
                    logger.error(f"❌ Failed to load cog {cog_name}: {e}")
    else:
        logger.info("📁 'cogs/' directory not found. Creating empty cogs directory...")
        os.makedirs(cogs_dir, exist_ok=True)


@tasks.loop(seconds=5)
async def change_status():
    """Cycles presence activity every 5 seconds."""
    await bot.change_presence(activity=next(STATUS_MESSAGES))


@bot.event
async def on_ready():
    await init_db()
    await load_cogs()
    try:
        await bot.tree.sync()
        logger.info("Synced Slash Commands across servers.")
    except Exception as e:
        logger.error(f"Failed to sync slash commands: {e}")

    logger.info(f"✅ Bot logged in as {bot.user} (ID: {bot.user.id})")
    if not change_status.is_running():
        change_status.start()


# -------------------------------------------------------------------
# NATIVE SLASH COMMANDS
# -------------------------------------------------------------------
@bot.tree.command(name="ping", description="Check the gateway latency")
async def ping_slash(interaction: discord.Interaction):
    latency = round(bot.latency * 1000)
    await interaction.response.send_message(f"🏓 Pong! Gateway latency: `{latency}ms`")


# -------------------------------------------------------------------
# MAIN MESSAGE LISTENER
# -------------------------------------------------------------------
@bot.event
async def on_message(message: discord.Message):
    global PROCESSED_MESSAGES_COUNT

    # Ignore all bot messages
    if message.author.bot:
        return

    guild_id = message.guild.id if message.guild else 0
    user_id = message.author.id

    # 1. Custom SQLite Command Executor
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT trigger, response_title, response_description, required_permission FROM custom_commands WHERE (server_id = ? OR is_global = 1)",
            (guild_id,)
        ) as cursor:
            commands_list = await cursor.fetchall()
            for trigger, title, description, req_perm in commands_list:
                if message.content.lower().startswith(trigger.lower()):
                    if req_perm and req_perm != "none" and isinstance(message.author, discord.Member):
                        perm_attr = getattr(message.author.guild_permissions, req_perm, False)
                        if not perm_attr and user_id != BOT_OWNER_ID:
                            err_embed = discord.Embed(
                                title="🚫 Permission Denied",
                                description=f"You require the `{req_perm.replace('_', ' ').title()}` permission to use `{trigger}`!",
                                color=discord.Color.red()
                            )
                            await message.reply(embed=err_embed)
                            return

                    embed = discord.Embed(title=title, description=description, color=discord.Color.gold())
                    embed.set_footer(text=f"Triggered by {message.author.display_name}", icon_url=message.author.display_avatar.url)
                    await message.reply(embed=embed)
                    return

    # Process Commands from Cogs
    await bot.process_commands(message)

    # 2. Check Activation Condition: Direct Mention OR No-Ping Mode
    is_mentioned = bot.user in message.mentions
    is_no_ping_user = user_id in NO_PING_USERS

    if is_mentioned or is_no_ping_user:
        # Strip out direct mention tag if present
        raw_prompt = (
            message.content.replace(f"<@{bot.user.id}>", "")
            .replace(f"<@!{bot.user.id}>", "")
            .strip()
        )

        lower_prompt = raw_prompt.lower()

        # A. Toggle No-Ping Mode (@ChatBot no-ping / @ChatBot noping)
        if lower_prompt in ["no-ping", "noping", "toggle no-ping", "toggle noping"]:
            if user_id in NO_PING_USERS:
                NO_PING_USERS.remove(user_id)
                embed = discord.Embed(
                    title="🔔 No-Ping Mode Disabled",
                    description=f"{message.author.mention}, you must tag me (`@ChatBot`) again to ask questions.",
                    color=discord.Color.gold()
                )
            else:
                NO_PING_USERS.add(user_id)
                embed = discord.Embed(
                    title="🎙️ No-Ping Mode Enabled",
                    description=f"{message.author.mention}, I will now respond to all your messages in this channel without requiring a tag! Mention me with `no-ping` again to disable.",
                    color=discord.Color.green()
                )
            await message.reply(embed=embed)
            return

        # Ignore empty prompts
        if not raw_prompt:
            return

        PROCESSED_MESSAGES_COUNT += 1

        # B. Detailed Bot & Server Statistics (@ChatBot stats)
        if lower_prompt in ["stats", "bot stats", "server stats"]:
            total_guilds = len(bot.guilds)
            total_channels = sum(len(guild.channels) for guild in bot.guilds)
            total_text_channels = sum(len(guild.text_channels) for guild in bot.guilds)
            total_voice_channels = sum(len(guild.voice_channels) for guild in bot.guilds)

            uptime_seconds = int(time.time() - BOT_START_TIME)
            hours, remainder = divmod(uptime_seconds, 3600)
            minutes, seconds = divmod(remainder, 60)

            async with aiosqlite.connect(DB_NAME) as db:
                async with db.execute("SELECT COUNT(*) FROM custom_commands") as cursor:
                    total_cmds = (await cursor.fetchone())[0]

            embed = discord.Embed(
                title="📊 Bot & Guild Statistics",
                color=discord.Color.teal()
            )
            embed.set_thumbnail(url=bot.user.display_avatar.url)
            embed.add_field(name="🤖 Bot Identity", value=f"**Username:** `{bot.user.name}#{bot.user.discriminator}`\n**User ID:** `{bot.user.id}`", inline=False)
            embed.add_field(name="🌐 Server Reach", value=f"**Joined Servers:** `{total_guilds}`\n**Total Channels:** `{total_channels}` (`{total_text_channels}` Text / `{total_voice_channels}` Voice)", inline=False)
            embed.add_field(name="⏱️ System Uptime", value=f"`{hours}h {minutes}m {seconds}s`", inline=True)
            embed.add_field(name="📜 Saved Custom Commands", value=f"`{total_cmds}`", inline=True)
            embed.add_field(name="🎙️ Active No-Ping Users", value=f"`{len(NO_PING_USERS)}`", inline=True)
            embed.set_footer(text=f"Requested by {message.author.display_name}", icon_url=message.author.display_avatar.url)

            await message.reply(embed=embed)
            return

        # C. Accurate System Diagnostics Check (@ChatBot check)
        if lower_prompt in ["check", "system check", "hardware"]:
            # Precise System CPU & Process Memory Calculation via psutil
            process = psutil.Process(os.getpid())
            cpu_usage = psutil.cpu_percent(interval=None)
            cpu_count = psutil.cpu_count(logical=True)

            ram = psutil.virtual_memory()
            system_ram_used_mb = round(ram.used / (1024 * 1024), 2)
            system_ram_total_mb = round(ram.total / (1024 * 1024), 2)
            bot_ram_mb = round(process.memory_info().rss / (1024 * 1024), 2)

            disk = psutil.disk_usage('/')
            disk_used_gb = round(disk.used / (1024 * 1024 * 1024), 2)
            disk_total_gb = round(disk.total / (1024 * 1024 * 1024), 2)

            embed = discord.Embed(
                title="⚙️ Accurate Resource Monitor",
                color=discord.Color.green()
            )
            embed.add_field(name="💻 CPU Load", value=f"`{cpu_usage}%` ({cpu_count} Cores)", inline=False)
            embed.add_field(name="🧠 Bot Memory Usage", value=f"`{bot_ram_mb} MB` (Process RAM)", inline=True)
            embed.add_field(name="🖥️ Total System RAM", value=f"`{system_ram_used_mb} MB` / `{system_ram_total_mb} MB` (`{ram.percent}%`)", inline=True)
            embed.add_field(name="💾 Disk Space", value=f"`{disk_used_gb} GB` / `{disk_total_gb} GB` (`{disk.percent}%`)", inline=False)
            embed.set_footer(text=f"Requested by {message.author.display_name}", icon_url=message.author.display_avatar.url)

            await message.reply(embed=embed)
            return

        # D. Backend Secrecy Interceptor
        if any(keyword in lower_prompt for keyword in SECRET_KEYWORDS):
            embed = discord.Embed(
                title="🔒 Classified Information",
                description="My core backend architecture, API configurations, and developer details are classified. That information is secret!",
                color=discord.Color.dark_purple()
            )
            await message.reply(embed=embed, mention_author=True)
            return

        # E. Create Custom Command (Requires Ban Members)
        if lower_prompt.startswith("create /") or lower_prompt.startswith("create command"):
            if isinstance(message.author, discord.Member) and not message.author.guild_permissions.ban_members and user_id != BOT_OWNER_ID:
                await message.reply(f"{message.author.mention} you don't have permission to create commands", mention_author=True)
                return

            is_global_cmd = 1 if ("global" in lower_prompt and user_id == BOT_OWNER_ID) else 0

            try:
                parts = raw_prompt.split()
                trigger_cmd = parts[1] if parts[1].startswith("/") else f"/{parts[1]}"

                cmd_title = "Custom Command Executed"
                cmd_desc = "Command processed successfully."
                cmd_perm = "none"

                if "title:" in raw_prompt:
                    cmd_title = raw_prompt.split("title:")[1].split("desc:")[0].strip()
                if "desc:" in raw_prompt:
                    cmd_desc = raw_prompt.split("desc:")[1].split("perm:")[0].strip()
                if "perm:" in raw_prompt:
                    cmd_perm = raw_prompt.split("perm:")[1].replace("global", "").strip().lower()

                async with aiosqlite.connect(DB_NAME) as db:
                    await db.execute(
                        "INSERT INTO custom_commands (server_id, trigger, response_title, response_description, required_permission, is_global) VALUES (?, ?, ?, ?, ?, ?)",
                        (guild_id, trigger_cmd, cmd_title, cmd_desc, cmd_perm, is_global_cmd)
                    )
                    await db.commit()

                embed = discord.Embed(title="✅ Custom Command Stored", color=discord.Color.green())
                embed.add_field(name="Trigger", value=f"`{trigger_cmd}`", inline=True)
                embed.add_field(name="Required Perm", value=f"`{cmd_perm}`", inline=True)
                embed.add_field(name="Scope", value="Global" if is_global_cmd else "Server Local", inline=True)
                embed.add_field(name="Embed Title", value=cmd_title, inline=False)
                embed.add_field(name="Embed Description", value=cmd_desc, inline=False)

                await message.reply(embed=embed)
                return
            except Exception:
                await message.reply("❌ Usage format: `@ChatBot create /cmd_name title: Title desc: Description perm: ban_members`")
                return

        # F. Delete Custom Command
        if lower_prompt.startswith("delete /") or lower_prompt.startswith("delcmd /") or lower_prompt.startswith("delete command"):
            if isinstance(message.author, discord.Member) and not message.author.guild_permissions.ban_members and user_id != BOT_OWNER_ID:
                await message.reply(f"{message.author.mention} you don't have permission to delete commands", mention_author=True)
                return

            try:
                parts = raw_prompt.split()
                target_cmd = parts[1] if parts[1].startswith("/") else f"/{parts[1]}"

                async with aiosqlite.connect(DB_NAME) as db:
                    cursor = await db.execute(
                        "DELETE FROM custom_commands WHERE trigger = ? AND (server_id = ? OR is_global = 1)",
                        (target_cmd, guild_id)
                    )
                    await db.commit()
                    deleted_rows = cursor.rowcount

                if deleted_rows > 0:
                    await message.reply(f"🗑️ Successfully deleted custom command `{target_cmd}`!")
                else:
                    await message.reply(f"❓ Custom command `{target_cmd}` was not found.")
                return
            except Exception:
                await message.reply("❌ Usage to delete: `@ChatBot delete /command_name`")
                return

        # G. List Custom Commands
        if lower_prompt in ["listcmds", "commands", "list commands"]:
            async with aiosqlite.connect(DB_NAME) as db:
                async with db.execute(
                    "SELECT trigger, required_permission, is_global FROM custom_commands WHERE (server_id = ? OR is_global = 1)",
                    (guild_id,)
                ) as cursor:
                    rows = await cursor.fetchall()

            if not rows:
                await message.reply("ℹ️ No custom commands registered for this server.")
                return

            cmd_list_str = "\n".join([f"• `{trig}` (Perm: `{perm}`) {'[Global]' if glob else ''}" for trig, perm, glob in rows])
            embed = discord.Embed(title="📜 Active Custom Commands", description=cmd_list_str, color=discord.Color.blue())
            await message.reply(embed=embed)
            return

        # H. Reset Context Thread
        if lower_prompt in ["reset", "clear"]:
            if user_id in USER_MEMORY:
                del USER_MEMORY[user_id]
                await message.reply("🧹 Context memory thread wiped!")
            else:
                await message.reply("No active memory thread found.")
            return

        # I. Core AI Text Generation Request via Groq
        if not groq_client:
            await message.reply("❌ `GROQ_API_KEY` missing in Railway environment variables.")
            return

        async with message.channel.typing():
            if user_id not in USER_MEMORY:
                USER_MEMORY[user_id] = []

            USER_MEMORY[user_id].append({"role": "user", "content": raw_prompt})

            if len(USER_MEMORY[user_id]) > MAX_MEMORY_TURNS:
                USER_MEMORY[user_id] = USER_MEMORY[user_id][-MAX_MEMORY_TURNS:]

            messages_payload = [{"role": "system", "content": SYSTEM_INSTRUCTION}] + USER_MEMORY[user_id]

            try:
                response = await groq_client.chat.completions.create(
                    model=MODEL_NAME,
                    messages=messages_payload,
                    temperature=0.7
                )

                ai_reply = response.choices[0].message.content.strip()
                USER_MEMORY[user_id].append({"role": "assistant", "content": ai_reply})

                if len(ai_reply) <= 4000:
                    embed = discord.Embed(description=ai_reply, color=discord.Color.blurple())
                    embed.set_author(name="AI Assistant", icon_url=bot.user.display_avatar.url)
                    embed.set_footer(text=f"Requested by {message.author.display_name} • Mention 'reset' to clear context", icon_url=message.author.display_avatar.url)
                    await message.reply(embed=embed, mention_author=True)
                else:
                    chunks = [ai_reply[i:i + 1900] for i in range(0, len(ai_reply), 1900)]
                    for idx, chunk in enumerate(chunks):
                        if idx == 0:
                            await message.reply(f"**AI Response (Part {idx + 1}):**\n{chunk}")
                        else:
                            await message.channel.send(f"**Part {idx + 1}:**\n{chunk}")

            except Exception as e:
                logger.error(f"Groq API Exception: {e}", exc_info=True)
                if USER_MEMORY[user_id] and USER_MEMORY[user_id][-1]["role"] == "user":
                    USER_MEMORY[user_id].pop()

                err_embed = discord.Embed(
                    title="⚠️ Generation Error",
                    description="An internal processing error occurred while generating the response.",
                    color=discord.Color.red()
                )
                await message.reply(embed=err_embed)


# -------------------------------------------------------------------
# ENTRYPOINT
# -------------------------------------------------------------------
if __name__ == "__main__":
    if not DISCORD_TOKEN:
        logger.critical("DISCORD_TOKEN environment variable is missing!")
    else:
        bot.run(DISCORD_TOKEN)
