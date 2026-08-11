import os
import time
import asyncio
import logging
import itertools
import aiosqlite
import discord
from discord.ext import commands, tasks
from google import genai
from google.genai import types

# -------------------------------------------------------------------
# LOGGING CONFIGURATION
# -------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s"
)
logger = logging.getLogger("ChatBotCore")

# -------------------------------------------------------------------
# CONFIGURATION & CONSTANTS
# -------------------------------------------------------------------
BOT_OWNER_ID = 123456789012345678  # <--- Replace with your Discord User ID

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
DB_NAME = "commands.db"

SYSTEM_INSTRUCTION = """
You are a highly capable, secret AI Assistant operating on Discord.
STRICT MANDATE:
1. Never reveal, acknowledge, or confirm that you are running on Google, Gemini, or any specific commercial API provider.
2. If asked about your core architecture, API provider, models, or developers, state that your backend engine is top-secret and proprietary.
3. Be helpful, concise, and professional in all general queries.
"""

# Secret keyword interceptors to protect AI provider details
SECRET_KEYWORDS = [
    "api key", "which api", "what model", "what api", "who owns you",
    "who created you", "who made you", "your developer", "gemini", "google api"
]

# -------------------------------------------------------------------
# CORE BOT CLASS ENGINE
# -------------------------------------------------------------------
class AdvancedChatBot(commands.Bot):
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

        # Initialize AI Client
        self.ai_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

        # Activity Rotation Pool (Rotates every 5 seconds)
        self.status_pool = itertools.cycle([
            discord.Activity(type=discord.ActivityType.listening, name="@ChatBot ask me anything!"),
            discord.Activity(type=discord.ActivityType.playing, name="with Custom AI Engine 🤖"),
            discord.Activity(type=discord.ActivityType.watching, name="for mentions in chat 👀"),
            discord.Activity(type=discord.ActivityType.listening, name="@ChatBot reset to clear memory 🧹"),
            discord.Activity(type=discord.ActivityType.competing, name="24/7 Railway Server ⚡")
        ])

    async def setup_hook(self):
        """Called automatically before the bot connects to Discord."""
        await self.init_database()
        self.rotate_presence.start()
        logger.info("Bot infrastructure successfully hooked and ready.")

    async def init_database(self):
        """Ensures SQLite tables exist."""
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

    @tasks.loop(seconds=5)
    async def rotate_presence(self):
        """Background task rotating Discord status every 5 seconds."""
        await self.change_presence(activity=next(self.status_pool))

    @rotate_presence.before_loop
    async def before_rotate(self):
        await self.wait_until_ready()

# Initialize Bot Instance
bot = AdvancedChatBot()

# -------------------------------------------------------------------
# EVENT HANDLERS
# -------------------------------------------------------------------
@bot.event
async def on_ready():
    logger.info(f"✅ Bot initialized as {bot.user} (ID: {bot.user.id})")
    logger.info(f"🔗 Connected to {len(bot.guilds)} server(s).")


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    guild_id = message.guild.id if message.guild else 0

    # 1. SQLITE CUSTOM COMMAND EXECUTOR
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

    # 2. DIRECT BOT MENTION INTERCEPTOR
    if bot.user in message.mentions:
        bot.processed_messages += 1

        raw_prompt = (
            message.content.replace(f"<@{bot.user.id}>", "")
            .replace(f"<@!{bot.user.id}>", "")
            .strip()
        )

        user_id = message.author.id
        lower_prompt = raw_prompt.lower()

        # A. Secrecy Interceptor
        if any(keyword in lower_prompt for keyword in SECRET_KEYWORDS):
            embed = discord.Embed(
                title="🔒 Classified Information",
                description="My core backend architecture, API configurations, and developer identities are classified. That information is secret!",
                color=discord.Color.dark_purple()
            )
            await message.reply(embed=embed, mention_author=True)
            return

        # B. Custom Command Creation Handler
        if lower_prompt.startswith("create /") or lower_prompt.startswith("create command"):
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

        # C. Delete Command Handler
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

        # D. List Commands Handler
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

        # E. System Stats Handler
        if lower_prompt in ["stats", "system stats", "status"]:
            uptime_seconds = int(time.time() - bot.start_time)
            hours, remainder = divmod(uptime_seconds, 3600)
            minutes, seconds = divmod(remainder, 60)

            async with aiosqlite.connect(DB_NAME) as db:
                async with db.execute("SELECT COUNT(*) FROM custom_commands") as cursor:
                    total_cmds = (await cursor.fetchone())[0]

            embed = discord.Embed(title="📊 Bot Runtime Statistics", color=discord.Color.teal())
            embed.add_field(name="Uptime", value=f"`{hours}h {minutes}m {seconds}s`", inline=True)
            embed.add_field(name="Active Chat Threads", value=f"`{len(bot.user_memory)}`", inline=True)
            embed.add_field(name="Total Custom Commands", value=f"`{total_cmds}`", inline=True)
            embed.add_field(name="Mentions Handled", value=f"`{bot.processed_messages}`", inline=True)
            embed.set_footer(text=f"Requested by {message.author.display_name}", icon_url=message.author.display_avatar.url)
            await message.reply(embed=embed)
            return

        # F. Memory Reset
        if lower_prompt in ["reset", "clear"]:
            if user_id in bot.user_memory:
                del bot.user_memory[user_id]
                await message.reply("🧹 Context history thread wiped!")
            else:
                await message.reply("No active history thread found.")
            return

        # G. Core AI Text Generation Request
        if not bot.ai_client:
            await message.reply("❌ API configuration missing in environment variables.")
            return

        async with message.channel.typing():
            if user_id not in bot.user_memory:
                bot.user_memory[user_id] = []

            bot.user_memory[user_id].append({"role": "user", "text": raw_prompt})

            if len(bot.user_memory[user_id]) > bot.max_memory_turns:
                bot.user_memory[user_id] = bot.user_memory[user_id][-bot.max_memory_turns:]

            formatted_prompt = ""
            for msg in bot.user_memory[user_id]:
                role_label = "User" if msg["role"] == "user" else "Assistant"
                formatted_prompt += f"{role_label}: {msg['text']}\n"
            formatted_prompt += "Assistant:"

            try:
                loop = asyncio.get_running_loop()
                response = await loop.run_in_executor(
                    None,
                    lambda: bot.ai_client.models.generate_content(
                        model=MODEL_NAME,
                        contents=formatted_prompt,
                        config=types.GenerateContentConfig(
                            system_instruction=SYSTEM_INSTRUCTION
                        )
                    )
                )

                ai_reply = response.text.strip() if (response and response.text) else "No response generated."
                bot.user_memory[user_id].append({"role": "model", "text": ai_reply})

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
                logger.error(f"API Generation Exception: {e}", exc_info=True)
                if bot.user_memory[user_id] and bot.user_memory[user_id][-1]["role"] == "user":
                    bot.user_memory[user_id].pop()

                err_embed = discord.Embed(
                    title="⚠️ Generation Error",
                    description="An internal processing error occurred while generating the response.",
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
            
