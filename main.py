import os
import time
import asyncio
import logging
import itertools
import discord
from discord.ext import commands, tasks
from google import genai

# Configure structured logging for production debugging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

# Load secrets from system / Railway environment variables
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")

# Initialize Gemini Client
ai_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

# Bot Metrics & Runtime Tracking
BOT_START_TIME = time.time()
PROCESSED_MESSAGES_COUNT = 0

# Per-user conversation memory thread
# Structure: { user_id: [ {"role": "user"/"model", "text": "..."}, ... ] }
USER_MEMORY = {}
MAX_MEMORY_HISTORY = 6  # Keeps up to 3 prompt-reply turns per user

# Configure Discord Intents
intents = discord.Intents.default()
intents.message_content = True  # Required to read text content when mentioned

bot = commands.Bot(command_prefix=commands.when_mentioned, intents=intents)

# Activity status pool (rotates every 5 seconds)
STATUS_MESSAGES = itertools.cycle([
    discord.Activity(type=discord.ActivityType.listening, name="@ChatBot ask me anything!"),
    discord.Activity(type=discord.ActivityType.playing, name="with Gemini 3.5 AI 🤖"),
    discord.Activity(type=discord.ActivityType.watching, name="for mentions in chat 👀"),
    discord.Activity(type=discord.ActivityType.listening, name="@ChatBot reset to clear memory 🧹"),
    discord.Activity(type=discord.ActivityType.competing, name="24/7 Railway Server ⚡")
])


@tasks.loop(seconds=5)
async def change_status():
    """Background task changing the bot activity status every 5 seconds."""
    current_activity = next(STATUS_MESSAGES)
    await bot.change_presence(activity=current_activity)


@bot.event
async def on_ready():
    logging.info(f"✅ Logged in successfully as {bot.user} (ID: {bot.user.id})")
    if not change_status.is_running():
        change_status.start()


@bot.event
async def on_message(message: discord.Message):
    global PROCESSED_MESSAGES_COUNT

    # Ignore messages sent by any bot
    if message.author.bot:
        return

    # Check if this bot was directly mentioned
    if bot.user in message.mentions:
        PROCESSED_MESSAGES_COUNT += 1

        # Strip out the mention tag to get pure prompt text
        raw_prompt = (
            message.content.replace(f"<@{bot.user.id}>", "")
            .replace(f"<@!{bot.user.id}>", "")
            .strip()
        )

        user_id = message.author.id

        # --- Sub-command Handler: Empty Mention / Help ---
        if not raw_prompt or raw_prompt.lower() in ["help", "info"]:
            embed = discord.Embed(
                title="🤖 AI ChatBot Guide",
                description="I am an advanced AI assistant powered by Google Gemini! Mention me in chat to interact.",
                color=discord.Color.blurple()
            )
            embed.add_field(
                name="💬 How to Chat",
                value="Simply tag me followed by your question:\n`@ChatBot Explain quantum physics`",
                inline=False
            )
            embed.add_field(
                name="🧹 Clear History",
                value="Tag me with `reset` or `clear` to wipe your chat history thread:\n`@ChatBot reset`",
                inline=False
            )
            embed.add_field(
                name="📊 System Status",
                value="Tag me with `stats` to view runtime statistics:\n`@ChatBot stats`",
                inline=False
            )
            embed.set_footer(text=f"Requested by {message.author.display_name}", icon_url=message.author.display_avatar.url)
            await message.reply(embed=embed, mention_author=True)
            return

        # --- Sub-command Handler: Memory Reset ---
        if raw_prompt.lower() in ["reset", "clear", "clear memory"]:
            if user_id in USER_MEMORY:
                del USER_MEMORY[user_id]
                embed = discord.Embed(
                    title="🧹 Memory Cleared",
                    description="Your conversation history has been reset. Starting fresh!",
                    color=discord.Color.green()
                )
            else:
                embed = discord.Embed(
                    title="ℹ️ No Active Memory",
                    description="You don't have any saved context history to clear.",
                    color=discord.Color.gold()
                )
            await message.reply(embed=embed, mention_author=True)
            return

        # --- Sub-command Handler: Statistics ---
        if raw_prompt.lower() in ["stats", "status"]:
            uptime_seconds = int(time.time() - BOT_START_TIME)
            hours, remainder = divmod(uptime_seconds, 3600)
            minutes, seconds = divmod(remainder, 60)

            embed = discord.Embed(
                title="📊 System Statistics",
                color=discord.Color.teal()
            )
            embed.add_field(name="Uptime", value=f"{hours}h {minutes}m {seconds}s", inline=True)
            embed.add_field(name="Active Chat Threads", value=str(len(USER_MEMORY)), inline=True)
            embed.add_field(name="Prompts Handled", value=str(PROCESSED_MESSAGES_COUNT), inline=True)
            embed.add_field(name="AI Model", value=MODEL_NAME, inline=True)
            embed.set_footer(text=f"Requested by {message.author.display_name}", icon_url=message.author.display_avatar.url)
            await message.reply(embed=embed, mention_author=True)
            return

        # Check API Key validity
        if not ai_client:
            err_embed = discord.Embed(
                title="❌ API Key Missing",
                description="The `GEMINI_API_KEY` variable is missing or empty in Railway variables.",
                color=discord.Color.red()
            )
            await message.reply(embed=err_embed)
            return

        # --- Core AI Generation Request ---
        async with message.channel.typing():
            # Initialize context thread if new user
            if user_id not in USER_MEMORY:
                USER_MEMORY[user_id] = []

            # Push current query
            USER_MEMORY[user_id].append({"role": "user", "text": raw_prompt})

            # Trim history to memory limit
            if len(USER_MEMORY[user_id]) > MAX_MEMORY_HISTORY:
                USER_MEMORY[user_id] = USER_MEMORY[user_id][-MAX_MEMORY_HISTORY:]

            # Construct full context string
            formatted_prompt = ""
            for msg in USER_MEMORY[user_id]:
                role_label = "User" if msg["role"] == "user" else "Assistant"
                formatted_prompt += f"{role_label}: {msg['text']}\n"
            formatted_prompt += "Assistant:"

            try:
                # Async execution using gemini-3.5-flash
                loop = asyncio.get_running_loop()
                response = await loop.run_in_executor(
                    None,
                    lambda: ai_client.models.generate_content(
                        model=MODEL_NAME,
                        contents=formatted_prompt
                    )
                )

                ai_reply = response.text.strip() if (response and response.text) else "No text generated."

                # Append assistant reply to memory
                USER_MEMORY[user_id].append({"role": "model", "text": ai_reply})

                # Format output into Discord Embed or Chunked Messages
                if len(ai_reply) <= 4000:
                    embed = discord.Embed(
                        description=ai_reply,
                        color=discord.Color.blurple()
                    )
                    embed.set_author(name="AI Assistant", icon_url=bot.user.display_avatar.url)
                    embed.set_footer(
                        text=f"Requested by {message.author.display_name} • Mention with 'reset' to clear context",
                        icon_url=message.author.display_avatar.url
                    )
                    await message.reply(embed=embed, mention_author=True)
                else:
                    # Message chunking for extra-long outputs
                    chunks = [ai_reply[i:i + 1900] for i in range(0, len(ai_reply), 1900)]
                    for idx, chunk in enumerate(chunks):
                        if idx == 0:
                            await message.reply(f"**AI Response (Part {idx + 1}):**\n{chunk}")
                        else:
                            await message.channel.send(f"**Part {idx + 1}:**\n{chunk}")

            except Exception as e:
                logging.error(f"Gemini Generation Exception: {e}", exc_info=True)

                # Rollback failed user message from memory on error
                if USER_MEMORY[user_id] and USER_MEMORY[user_id][-1]["role"] == "user":
                    USER_MEMORY[user_id].pop()

                err_embed = discord.Embed(
                    title="⚠️ Generation Error",
                    description=f"An error occurred while calling the AI model:\n`{str(e)[:300]}`",
                    color=discord.Color.red()
                )
                await message.reply(embed=err_embed, mention_author=True)


if __name__ == "__main__":
    if not DISCORD_TOKEN:
        logging.critical("DISCORD_TOKEN environment variable is missing!")
    else:
        bot.run(DISCORD_TOKEN)
        
