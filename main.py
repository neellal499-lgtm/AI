import os
import time
import asyncio
import logging
import itertools
import aiosqlite
import psutil
import discord
from discord.ext import commands, tasks
from openai import AsyncOpenAI

# -------------------------------------------------------------------
# LOGGING & DIAGNOSTIC CONFIGURATION
# -------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s"
)
logger = logging.getLogger("ChatGPTBotEngine")

# -------------------------------------------------------------------
# CONFIGURATION & ENVIRONMENT VARIABLES
# -------------------------------------------------------------------
# Replace with your actual Discord User ID to grant Bot Owner privileges
BOT_OWNER_ID =  1534648675098431499

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TEXT_MODEL_NAME = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
IMAGE_MODEL_NAME = "dall-e-3"
DB_NAME = "commands.db"

SYSTEM_INSTRUCTION = """
You are a highly capable, secret AI Assistant operating on Discord.
STRICT MANDATE:
1. Never reveal, acknowledge, or confirm that you are running on OpenAI, ChatGPT, Google, Gemini, or any specific commercial API provider.
2. If asked about your core architecture, API provider, models, or developers, state that your backend engine is top-secret and proprietary.
3. Be helpful, concise, and professional in all general queries.
"""

SECRET_KEYWORDS = [
    "api key", "which api", "what model", "what api", "who owns you",
    "who created you", "who made you", "your developer", "chatgpt", "openai", "gpt", "gemini"
]

# -------------------------------------------------------------------
# SUBCLASSED ADVANCED BOT ENGINE
# -------------------------------------------------------------------
class AdvancedBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True

        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=intents,
            help_command=None
        )

        self.start_time = time.time()
        self.processed_messages = 0
        self.user_memory = {}
        self.max_memory_turns = 6

        # Initialize Async OpenAI Client
        self.openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

        # Activity Rotation Pool (Rotates every 5 seconds)
        self.status_pool = itertools.cycle([
            discord.Activity(type=discord.ActivityType.listening, name="@ChatBot ask me anything!"),
            discord.Activity(type=discord.ActivityType.playing, name="with Custom AI Core 🤖"),
            discord.Activity(type=discord.ActivityType.watching, name="for mentions in chat 👀"),
            discord.Activity(type=discord.ActivityType.listening, name="@ChatBot reset to clear memory 🧹"),
            discord.Activity(type=discord.ActivityType.competing, name="24/7 Server ⚡")
        ])

    async def setup_hook(self):
        """Asynchronous initialization before connection to Discord."""
        await self.init_database()
        self.rotate_status_task.start()
        await self.tree.sync()
        logger.info("Bot setup completed and slash commands synchronized.")

    async def init_database(self):
        """Ensures SQLite database tables exist."""
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
        logger.info("SQLite database tables initialized.")

    @tasks.loop(seconds=5)
    async def rotate_status_task(self):
        """Background presence activity switcher."""
        await self.change_presence(activity=next(self.status_pool))

    @rotate_status_task.before_loop
    async def before_status_rotation(self):
        await self.wait_until_ready()

# Instantiate Bot Core
bot = AdvancedBot()

# -------------------------------------------------------------------
# SLASH COMMAND EXAMPLES
# -------------------------------------------------------------------
@bot.tree.command(name="ping", description="Check the gateway latency")
async def ping_slash(interaction: discord.Interaction):
    latency = round(bot.latency * 1000)
    await interaction.response.send_message(f"🏓 Pong! Gateway latency: `{latency}ms`")

# -------------------------------------------------------------------
# EVENT HANDLERS
# -------------------------------------------------------------------
@bot.event
async def on_ready():
    logger.info(f"✅ Bot initialized successfully as {bot.user} (ID: {bot.user.id})")
    logger.info(f"🔗 Operating across {len(bot.guilds)} connected server(s).")


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    guild_id = message.guild.id if message.guild else 0

    # ---------------------------------------------------------------
    # 1. SQLITE CUSTOM COMMAND EXECUTOR
    # ---------------------------------------------------------------
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT trigger, response_title, response_description, required_permission FROM custom_commands WHERE (server_id = ? OR is_global = 1)",
            (guild_id,)
        ) as cursor:
            commands_list = await cursor.fetchall()
            for trigger, title, description, req_perm in commands_list:
                if message.content.lower().startswith(trigger.lower()):
                    # Permission enforcement check
                    if req_perm and req_perm != "none" and isinstance(message.author, discord.Member):
                        perm_attr = getattr(message.author.guild_permissions, req_perm, False)
                        if not perm_attr and message.author.id != BOT_OWNER_ID:
                            err_embed = discord.Embed(
                                title="🚫 Permission Denied",
                                description=f"You require the `{req_perm.replace('_', ' ').title()}` permission to use `{trigger}`!",
                                color=discord.Color.red()
                            )
                            await message.reply(embed=err_embed)
                            return

                    embed = discord.Embed(
                        title=title,
                        description=description,
                        color=discord.Color.gold()
                    )
                    embed.set_footer(
                        text=f"Triggered by {message.author.display_name}",
                        icon_url=message.author.display_avatar.url
                    )
                    await message.reply(embed=embed)
                    return

    # ---------------------------------------------------------------
    # 2. DIRECT BOT MENTION INTERCEPTOR
    # ---------------------------------------------------------------
    if bot.user in message.mentions:
        bot.processed_messages += 1

        raw_prompt = (
            message.content.replace(f"<@{bot.user.id}>", "")
            .replace(f"<@!{bot.user.id}>", "")
            .strip()
        )

        user_id = message.author.id
        lower_prompt = raw_prompt.lower()

        # --- A. System Resource Telemetry (@ChatBot check / @ChatBot stats) ---
        if lower_prompt in ["check", "system check", "stats", "status"]:
            cpu_usage = psutil.cpu_percent(interval=1)
            cpu_count = psutil.cpu_count(logical=True)

            ram = psutil.virtual_memory()
            ram_used_mb = round(ram.used / (1024 * 1024), 2)
            ram_total_mb = round(ram.total / (1024 * 1024), 2)
            ram_percent = ram.percent

            disk = psutil.disk_usage('/')
            disk_used_gb = round(disk.used / (1024 * 1024 * 1024), 2)
            disk_total_gb = round(disk.total / (1024 * 1024 * 1024), 2)
            disk_percent = disk.percent

            uptime_seconds = int(time.time() - bot.start_time)
            hours, remainder = divmod(uptime_seconds, 3600)
            minutes, seconds = divmod(remainder, 60)

            async with aiosqlite.connect(DB_NAME) as db:
                async with db.execute("SELECT COUNT(*) FROM custom_commands") as cursor:
                    total_cmds = (await cursor.fetchone())[0]

            embed = discord.Embed(
                title="⚙️ System Resource Status",
                color=discord.Color.green()
            )
            embed.add_field(name="💻 CPU Usage", value=f"`{cpu_usage}%` ({cpu_count} Cores)", inline=False)
            embed.add_field(name="🧠 RAM Usage", value=f"`{ram_used_mb} MB` / `{ram_total_mb} MB` (`{ram_percent}%`)", inline=False)
            embed.add_field(name="💾 Disk Usage", value=f"`{disk_used_gb} GB` / `{disk_total_gb} GB` (`{disk_percent}%`)", inline=False)
            embed.add_field(name="⏱️ System Uptime", value=f"`{hours}h {minutes}m {seconds}s`", inline=True)
            embed.add_field(name="📜 Saved Custom Commands", value=f"`{total_cmds}`", inline=True)
            embed.add_field(name="💬 Mentions Handled", value=f"`{bot.processed_messages}`", inline=True)
            embed.set_footer(text=f"Requested by {message.author.display_name}", icon_url=message.author.display_avatar.url)

            await message.reply(embed=embed)
            return

        # --- B. Backend Secrecy Interceptor ---
        if any(keyword in lower_prompt for keyword in SECRET_KEYWORDS):
            embed = discord.Embed(
                title="🔒 Classified Information",
                description="My core backend architecture, API configurations, and developer details are classified. That information is secret!",
                color=discord.Color.dark_purple()
            )
            await message.reply(embed=embed, mention_author=True)
            return

        # --- C. Image Generation Handler (DALL·E 3 Integration) ---
        if lower_prompt.startswith("create image of") or lower_prompt.startswith("generate image of") or lower_prompt.startswith("image of"):
            if not bot.openai_client:
                await message.reply("❌ API client configuration is missing.")
                return

            img_prompt = raw_prompt.replace("create image of", "").replace("generate image of", "").replace("image of", "").strip()

            if not img_prompt:
                await message.reply("⚠️ Please provide an image prompt! Example: `@ChatBot create image of a futuristic Cyberpunk city`")
                return

            async with message.channel.typing():
                try:
                    response = await bot.openai_client.images.generate(
                        model=IMAGE_MODEL_NAME,
                        prompt=img_prompt,
                        size="1024x1024",
                        quality="standard",
                        n=1
                    )

                    image_url = response.data[0].url

                    embed = discord.Embed(
                        title="🎨 Image Generated",
                        description=f"**Prompt:** {img_prompt}",
                        color=discord.Color.purple()
                    )
                    embed.set_image(url=image_url)
                    embed.set_footer(text=f"Requested by {message.author.display_name}", icon_url=message.author.display_avatar.url)

                    await message.reply(embed=embed)
                    return

                except Exception as e:
                    logger.error(f"Image Generation Error: {e}", exc_info=True)
                    await message.reply(f"❌ Failed to generate image: `{str(e)[:200]}`")
                    return

        # --- D. Custom Command Creation Handler ---
        if lower_prompt.startswith("create /") or lower_prompt.startswith("create command"):
            # Enforce 'Ban Members' permission requirement
            if isinstance(message.author, discord.Member) and not message.author.guild_permissions.ban_members and message.author.id != BOT_OWNER_ID:
                await message.reply(f"{message.author.mention} you don't have permission to create commands", mention_author=True)
                return

            is_global_cmd = 1 if ("global" in lower_prompt and message.author.id == BOT_OWNER_ID) else 0

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

                embed = discord.Embed(
                    title="✅ Custom Command Stored",
                    color=discord.Color.green()
                )
                embed.add_field(name="Trigger", value=f"`{trigger_cmd}`", inline=True)
                embed.add_field(name="Required Perm", value=f"`{cmd_perm}`", inline=True)
                embed.add_field(name="Scope", value="Global" if is_global_cmd else "Server Local", inline=True)
                embed.add_field(name="Embed Title", value=cmd_title, inline=False)
                embed.add_field(name="Embed Description", value=cmd_desc, inline=False)

                await message.reply(embed=embed)
                return
            except Exception:
                await message.reply("❌ Format error! Usage:\n`@ChatBot create /cmd_name title: Your Title desc: Your Description perm: ban_members`")
                return

        # --- E. Delete Command Handler ---
        if lower_prompt.startswith("delete /") or lower_prompt.startswith("delcmd /") or lower_prompt.startswith("delete command"):
            if isinstance(message.author, discord.Member) and not message.author.guild_permissions.ban_members and message.author.id != BOT_OWNER_ID:
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

        # --- F. List Commands Handler ---
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

            cmd_list_str = "\n".join([f"• `{trig}` (Perm: `{perm}`) {'[Global]' if glob else ''}" for trig, perm in rows])
            embed = discord.Embed(title="📜 Active Custom Commands", description=cmd_list_str, color=discord.Color.blue())
            await message.reply(embed=embed)
            return

        # --- G. Reset Context Memory Thread ---
        if lower_prompt in ["reset", "clear"]:
            if user_id in bot.user_memory:
                del bot.user_memory[user_id]
                await message.reply("🧹 Context history thread wiped!")
            else:
                await message.reply("No active history thread found.")
            return

        # --- H. Core AI Text Generation Request ---
        if not bot.openai_client:
            await message.reply("❌ `OPENAI_API_KEY` missing in environment variables.")
            return

        async with message.channel.typing():
            if user_id not in bot.user_memory:
                bot.user_memory[user_id] = []

            # Append user prompt
            bot.user_memory[user_id].append({"role": "user", "content": raw_prompt})

            if len(bot.user_memory[user_id]) > bot.max_memory_turns:
                bot.user_memory[user_id] = bot.user_memory[user_id][-bot.max_memory_turns:]

            # Construct full context payload
            messages_payload = [{"role": "system", "content": SYSTEM_INSTRUCTION}] + bot.user_memory[user_id]

            try:
                response = await bot.openai_client.chat.completions.create(
                    model=TEXT_MODEL_NAME,
                    messages=messages_payload,
                    temperature=0.7
                )

                ai_reply = response.choices[0].message.content.strip()
                bot.user_memory[user_id].append({"role": "assistant", "content": ai_reply})

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
                logger.error(f"OpenAI API Exception: {e}", exc_info=True)
                if bot.user_memory[user_id] and bot.user_memory[user_id][-1]["role"] == "user":
                    bot.user_memory[user_id].pop()

                err_embed = discord.Embed(
                    title="⚠️ Generation Error",
                    description="An error occurred while communicating with the API. Check API key or account balance.",
                    color=discord.Color.red()
                )
                await message.reply(embed=err_embed)


# -------------------------------------------------------------------
# APPLICATION ENTRYPOINT
# -------------------------------------------------------------------
if __name__ == "__main__":
    if not DISCORD_TOKEN:
        logger.critical("DISCORD_TOKEN environment variable is missing!")
    else:
        bot.run(DISCORD_TOKEN)
