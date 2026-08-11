import os
import time
import asyncio
import logging
import itertools
import aiosqlite
import discord
from discord.ext import commands, tasks
from google import genai

# Setup structured logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

# -------------------------------------------------------------------
# CONFIGURATION & ENVIRONMENT VARIABLES
# -------------------------------------------------------------------
# Replace with your actual Discord User ID to gain Bot Owner privileges
BOT_OWNER_ID = 123456789012345678  

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
DB_NAME = "commands.db"

# Initialize Gemini AI Client
ai_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

# Runtime metrics
BOT_START_TIME = time.time()
PROCESSED_MESSAGES_COUNT = 0

# Per-user conversation memory
USER_MEMORY = {}
MAX_MEMORY_HISTORY = 6  # Keeps up to 3 turns (user + AI pairs)

# Configure Discord Intents
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix=commands.when_mentioned, intents=intents)

# -------------------------------------------------------------------
# BACKGROUND ACTIVITIES (Rotates every 5 seconds)
# -------------------------------------------------------------------
STATUS_MESSAGES = itertools.cycle([
    discord.Activity(type=discord.ActivityType.listening, name="@ChatBot ask me anything!"),
    discord.Activity(type=discord.ActivityType.playing, name="with Gemini AI 🤖"),
    discord.Activity(type=discord.ActivityType.watching, name="for mentions in chat 👀"),
    discord.Activity(type=discord.ActivityType.listening, name="@ChatBot reset to clear memory 🧹"),
    discord.Activity(type=discord.ActivityType.competing, name="24/7 Railway Server ⚡")
])


async def init_db():
    """Initializes the SQLite database table for custom commands."""
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


@tasks.loop(seconds=5)
async def change_status():
    """Cycles bot activity status every 5 seconds."""
    current_activity = next(STATUS_MESSAGES)
    await bot.change_presence(activity=current_activity)


@bot.event
async def on_ready():
    await init_db()
    logging.info(f"✅ Logged in successfully as {bot.user} (ID: {bot.user.id})")
    if not change_status.is_running():
        change_status.start()


# -------------------------------------------------------------------
# MAIN MESSAGE EVENT HANDLER
# -------------------------------------------------------------------
@bot.event
async def on_message(message: discord.Message):
    global PROCESSED_MESSAGES_COUNT

    # Ignore messages sent by bots
    if message.author.bot:
        return

    guild_id = message.guild.id if message.guild else 0

    # ---------------------------------------------------------------
    # 1. SQLITE CUSTOM COMMAND EXECUTION ENGINE
    # ---------------------------------------------------------------
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT trigger, response_title, response_description, required_permission FROM custom_commands WHERE (server_id = ? OR is_global = 1)",
            (guild_id,)
        ) as cursor:
            commands_list = await cursor.fetchall()
            for trigger, title, description, req_perm in commands_list:
                if message.content.lower().startswith(trigger.lower()):
                    # Permission Enforcement
                    if req_perm and req_perm != "none" and isinstance(message.author, discord.Member):
                        perm_attr = getattr(message.author.guild_permissions, req_perm, False)
                        if not perm_attr and message.author.id != BOT_OWNER_ID:
                            err_embed = discord.Embed(
                                title="🚫 Permission Denied",
                                description=f"You need the `{req_perm.replace('_', ' ').title()}` permission to run `{trigger}`!",
                                color=discord.Color.red()
                            )
                            await message.reply(embed=err_embed)
                            return

                    # Render and Send Custom Command Embed
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
    # 2. BOT MENTION HANDLER (@ChatBot)
    # ---------------------------------------------------------------
    if bot.user in message.mentions:
        PROCESSED_MESSAGES_COUNT += 1

        raw_prompt = (
            message.content.replace(f"<@{bot.user.id}>", "")
            .replace(f"<@!{bot.user.id}>", "")
            .strip()
        )

        user_id = message.author.id

        # --- A. Creator Identification Query ---
        creator_keywords = ["who created you", "who made you", "who is your owner", "who is your creator", "who developed you"]
        if any(keyword in raw_prompt.lower() for keyword in creator_keywords):
            owner_mention = f"<@{BOT_OWNER_ID}>" if BOT_OWNER_ID != 123456789012345678 else "my developer"
            embed = discord.Embed(
                title="👑 Bot Creator",
                description=f"I was created and developed by {owner_mention}! Feel free to reach out to them for bot inquiries or updates.",
                color=discord.Color.purple()
            )
            await message.reply(embed=embed, mention_author=True)
            return

        # --- B. Custom Command Creation Handler ---
        # Example: @ChatBot create /ban title: User Banned desc: Action taken perm: ban_members
        if raw_prompt.lower().startswith("create /") or raw_prompt.lower().startswith("create command"):
            if isinstance(message.author, discord.Member) and not message.author.guild_permissions.manage_guild and message.author.id != BOT_OWNER_ID:
                await message.reply("❌ You need `Manage Server` permission to create custom commands!")
                return

            is_global_cmd = 0
            if "global" in raw_prompt.lower():
                if message.author.id == BOT_OWNER_ID:
                    is_global_cmd = 1
                else:
                    await message.reply("⚠️ Only the Bot Owner can register global commands! Saving as server-local instead...")

            try:
                parts = raw_prompt.split()
                trigger_cmd = parts[1] if parts[1].startswith("/") else f"/{parts[1]}"

                # Parse optional arguments
                cmd_title = "Custom Command Result"
                cmd_desc = "Execution successful."
                cmd_perm = "none"

                if "title:" in raw_prompt:
                    cmd_title = raw_prompt.split("title:")[1].split("desc:")[0].strip()
                if "desc:" in raw_prompt:
                    cmd_desc = raw_prompt.split("desc:")[1].split("perm:")[0].strip()
                if "perm:" in raw_prompt:
                    cmd_perm = raw_prompt.split("perm:")[1].replace("global", "").strip().lower()

                # Insert into SQLite Database
                async with aiosqlite.connect(DB_NAME) as db:
                    await db.execute(
                        "INSERT INTO custom_commands (server_id, trigger, response_title, response_description, required_permission, is_global) VALUES (?, ?, ?, ?, ?, ?)",
                        (guild_id, trigger_cmd, cmd_title, cmd_desc, cmd_perm, is_global_cmd)
                    )
                    await db.commit()

                scope_label = "Global (All Servers)" if is_global_cmd else f"Server ({message.guild.name if message.guild else 'DM'})"

                embed = discord.Embed(
                    title="✅ Custom Command Stored!",
                    color=discord.Color.green()
                )
                embed.add_field(name="Trigger", value=f"`{trigger_cmd}`", inline=True)
                embed.add_field(name="Required Perm", value=f"`{cmd_perm}`", inline=True)
                embed.add_field(name="Scope", value=scope_label, inline=True)
                embed.add_field(name="Embed Title", value=cmd_title, inline=False)
                embed.add_field(name="Embed Description", value=cmd_desc, inline=False)

                await message.reply(embed=embed)
                return
            except Exception as e:
                await message.reply("❌ **Format Error!** Usage:\n`@ChatBot create /cmd_name title: Your Title desc: Your Description perm: permission_name [global]`")
                return

        # --- C. Delete Command Handler ---
        if raw_prompt.lower().startswith("delcmd") or raw_prompt.lower().startswith("delete command"):
            if isinstance(message.author, discord.Member) and not message.author.guild_permissions.manage_guild and message.author.id != BOT_OWNER_ID:
                await message.reply("❌ You need `Manage Server` permission to delete custom commands!")
                return

            try:
                target_trigger = raw_prompt.split()[1]
                if not target_trigger.startswith("/"):
                    target_trigger = f"/{target_trigger}"

                async with aiosqlite.connect(DB_NAME) as db:
                    cursor = await db.execute(
                        "DELETE FROM custom_commands WHERE trigger = ? AND (server_id = ? OR is_global = 1)",
                        (target_trigger, guild_id)
                    )
                    await db.commit()
                    deleted_count = cursor.rowcount

                if deleted_count > 0:
                    await message.reply(f"🗑️ Successfully deleted custom command `{target_trigger}`!")
                else:
                    await message.reply(f"❓ Command `{target_trigger}` was not found in database.")
                return
            except Exception:
                await message.reply("❌ Usage: `@ChatBot delcmd /command_name`")
                return

        # --- D. List Commands Handler ---
        if raw_prompt.lower() in ["listcmds", "commands", "list commands"]:
            async with aiosqlite.connect(DB_NAME) as db:
                async with db.execute(
                    "SELECT trigger, required_permission, is_global FROM custom_commands WHERE (server_id = ? OR is_global = 1)",
                    (guild_id,)
                ) as cursor:
                    rows = await cursor.fetchall()

            if not rows:
                await message.reply("ℹ️ No custom commands registered for this server yet.")
                return

            cmd_text = "\n".join([f"• `{trig}` (Perm: `{perm}`) {'[Global]' if glob else ''}" for trig, perm, glob in rows])
            embed = discord.Embed(
                title="📜 Active Custom Commands",
                description=cmd_text,
                color=discord.Color.blue()
            )
            await message.reply(embed=embed)
            return

        # --- E. Reset Context Thread Handler ---
        if raw_prompt.lower() in ["reset", "clear"]:
            if user_id in USER_MEMORY:
                del USER_MEMORY[user_id]
                await message.reply("🧹 Your conversation history has been wiped!")
            else:
                await message.reply("You don't have active conversation context.")
            return

        # --- F. Core Gemini AI Request Processing ---
        if not ai_client:
            await message.reply("❌ `GEMINI_API_KEY` is missing from Railway environment variables.")
            return

        async with message.channel.typing():
            if user_id not in USER_MEMORY:
                USER_MEMORY[user_id] = []

            USER_MEMORY[user_id].append({"role": "user", "text": raw_prompt})

            if len(USER_MEMORY[user_id]) > MAX_MEMORY_HISTORY:
                USER_MEMORY[user_id] = USER_MEMORY[user_id][-MAX_MEMORY_HISTORY:]

            formatted_prompt = ""
            for msg in USER_MEMORY[user_id]:
                role_label = "User" if msg["role"] == "user" else "Assistant"
                formatted_prompt += f"{role_label}: {msg['text']}\n"
            formatted_prompt += "Assistant:"

            try:
                loop = asyncio.get_running_loop()
                response = await loop.run_in_executor(
                    None,
                    lambda: ai_client.models.generate_content(
                        model=MODEL_NAME,
                        contents=formatted_prompt
                    )
                )

                ai_reply = response.text.strip() if (response and response.text) else "No text generated."
                USER_MEMORY[user_id].append({"role": "model", "text": ai_reply})

                # Embed Output or Chunking
                if len(ai_reply) <= 4000:
                    embed = discord.Embed(
                        description=ai_reply,
                        color=discord.Color.blurple()
                    )
                    embed.set_author(name="AI Assistant", icon_url=bot.user.display_avatar.url)
                    embed.set_footer(
                        text=f"Requested by {message.author.display_name} • Mention 'reset' to clear context",
                        icon_url=message.author.display_avatar.url
                    )
                    await message.reply(embed=embed, mention_author=True)
                else:
                    chunks = [ai_reply[i:i + 1900] for i in range(0, len(ai_reply), 1900)]
                    for idx, chunk in enumerate(chunks):
                        if idx == 0:
                            await message.reply(f"**AI Response (Part {idx + 1}):**\n{chunk}")
                        else:
                            await message.channel.send(f"**Part {idx + 1}:**\n{chunk}")

            except Exception as e:
                logging.error(f"Gemini API Exception: {e}", exc_info=True)
                if USER_MEMORY[user_id] and USER_MEMORY[user_id][-1]["role"] == "user":
                    USER_MEMORY[user_id].pop()

                err_embed = discord.Embed(
                    title="⚠️ Generation Error",
                    description=f"`{str(e)[:300]}`",
                    color=discord.Color.red()
                )
                await message.reply(embed=err_embed)


if __name__ == "__main__":
    if not DISCORD_TOKEN:
        logging.critical("DISCORD_TOKEN environment variable is missing!")
    else:
        bot.run(DISCORD_TOKEN)
                
