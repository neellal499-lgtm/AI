import os
import asyncio
import logging
import itertools
import discord
from discord.ext import commands, tasks
from google import genai

# Setup console logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

# Load secrets from Railway environment variables
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Initialize Gemini Client
ai_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

# Per-user chat memory thread
USER_MEMORY = {}
MAX_MEMORY_HISTORY = 6  # Remembers last 3 question/answer turns

# Discord Gateway setup
intents = discord.Intents.default()
intents.message_content = True  # Required for @bot detection

bot = commands.Bot(command_prefix="!", intents=intents)

# List of activities to cycle through every 5 seconds
STATUS_MESSAGES = itertools.cycle([
    discord.Activity(type=discord.ActivityType.listening, name="@ChatBot <question>"),
    discord.Activity(type=discord.ActivityType.playing, name="with Gemini 2.5 AI 🤖"),
    discord.Activity(type=discord.ActivityType.watching, name="for @mentions in chat 👀"),
    discord.Activity(type=discord.ActivityType.listening, name="type !clear to reset memory 🧹"),
    discord.Activity(type=discord.ActivityType.competing, name="24/7 Railway Server ⚡")
])


@tasks.loop(seconds=5)
async def change_status():
    """Background task changing the bot activity every 5 seconds."""
    current_activity = next(STATUS_MESSAGES)
    await bot.change_presence(activity=current_activity)


@bot.event
async def on_ready():
    logging.info(f"✅ Logged in as {bot.user} (ID: {bot.user.id})")
    # Start the 5-second status switcher task
    if not change_status.is_running():
        change_status.start()


@bot.command(name="clear")
async def clear_memory(ctx):
    """Command: !clear (Resets individual user's AI chat thread)"""
    user_id = ctx.author.id
    if user_id in USER_MEMORY:
        del USER_MEMORY[user_id]
        await ctx.reply("🧹 Your conversation memory has been cleared!")
    else:
        await ctx.reply("You don't have active conversation history.")


@bot.event
async def on_message(message):
    # Ignore self and other bots
    if message.author.bot:
        return

    # Process standard prefix commands like !clear
    await bot.process_commands(message)

    # Trigger when mentioned
    if bot.user in message.mentions:
        # Strip mention tags out of prompt text
        raw_prompt = (
            message.content.replace(f"<@{bot.user.id}>", "")
            .replace(f"<@!{bot.user.id}>", "")
            .strip()
        )

        if not raw_prompt:
            await message.reply("👋 Tag me with a question! Example: `@ChatBot What is Termux?`")
            return

        if not ai_client:
            await message.reply("❌ `GEMINI_API_KEY` is missing in Railway variables!")
            return

        async with message.channel.typing():
            user_id = message.author.id

            # Initialize user conversation
            if user_id not in USER_MEMORY:
                USER_MEMORY[user_id] = []

            USER_MEMORY[user_id].append({"role": "user", "text": raw_prompt})

            # Keep context trimmed
            if len(USER_MEMORY[user_id]) > MAX_MEMORY_HISTORY:
                USER_MEMORY[user_id] = USER_MEMORY[user_id][-MAX_MEMORY_HISTORY:]

            # Format memory for prompt context
            formatted_prompt = ""
            for msg in USER_MEMORY[user_id]:
                role_label = "User" if msg["role"] == "user" else "Assistant"
                formatted_prompt += f"{role_label}: {msg['text']}\n"
            formatted_prompt += "Assistant:"

            try:
                # Async execution using active gemini-2.5-flash model
                loop = asyncio.get_running_loop()
                response = await loop.run_in_executor(
                    None,
                    lambda: ai_client.models.generate_content(
                        model="gemini-2.5-flash",
                        contents=formatted_prompt
                    )
                )

                ai_reply = response.text.strip() if (response and response.text) else "No text response generated."

                # Save AI response to history thread
                USER_MEMORY[user_id].append({"role": "model", "text": ai_reply})

                # Embed size check
                if len(ai_reply) <= 4000:
                    embed = discord.Embed(
                        description=ai_reply,
                        color=discord.Color.blurple()
                    )
                    embed.set_author(name="AI Assistant", icon_url=bot.user.display_avatar.url)
                    embed.set_footer(
                        text=f"Requested by {message.author.display_name} • Type !clear to reset memory",
                        icon_url=message.author.display_avatar.url
                    )
                    await message.reply(embed=embed, mention_author=True)
                else:
                    # Message chunking for answers exceeding 4,000 characters
                    chunks = [ai_reply[i:i + 1900] for i in range(0, len(ai_reply), 1900)]
                    for idx, chunk in enumerate(chunks):
                        if idx == 0:
                            await message.reply(f"**AI Response (Part {idx + 1}):**\n{chunk}")
                        else:
                            await message.channel.send(f"**Part {idx + 1}:**\n{chunk}")

            except Exception as e:
                logging.error(f"Gemini API Error: {e}", exc_info=True)

                # Rollback failed prompt from memory
                if USER_MEMORY[user_id] and USER_MEMORY[user_id][-1]["role"] == "user":
                    USER_MEMORY[user_id].pop()

                err_embed = discord.Embed(
                    title="⚠️ Generation Error",
                    description=f"An error occurred while contacting the AI:\n`{str(e)[:300]}`",
                    color=discord.Color.red()
                )
                await message.reply(embed=err_embed)


if __name__ == "__main__":
    if not DISCORD_TOKEN:
        logging.critical("DISCORD_TOKEN environment variable is missing!")
    else:
        bot.run(DISCORD_TOKEN)
        
