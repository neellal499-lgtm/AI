import os
import asyncio
import logging
import discord
from discord.ext import commands
from google import genai

# Configure logging for debugging inside Railway / Termux
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

# Load Environment Variables
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Initialize Gemini Client with explicit API key
if not GEMINI_API_KEY:
    logging.critical("GEMINI_API_KEY variable is missing!")
ai_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

# Memory storage to hold recent chat history per user
# Structure: { user_id: [ {"role": "user"/"model", "text": "..."}, ... ] }
USER_MEMORY = {}
MAX_MEMORY_HISTORY = 6  # Keeps last 3 turns of conversation

# Configure Discord Bot Gateway Intents
intents = discord.Intents.default()
intents.message_content = True  # Required to read text in @mentions

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    logging.info(f"Logged in as {bot.user} (ID: {bot.user.id})")
    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.listening, 
            name="@ChatBot <question>"
        )
    )


@bot.command(name="clear")
async def clear_memory(ctx):
    """Command to reset the user's AI conversation memory."""
    user_id = ctx.author.id
    if user_id in USER_MEMORY:
        del USER_MEMORY[user_id]
        await ctx.reply("🧹 Your conversation memory has been cleared!")
    else:
        await ctx.reply("You don't have any active conversation history.")


@bot.event
async def on_message(message):
    # Ignore messages sent by bots (including itself)
    if message.author.bot:
        return

    # Process standard prefix commands first (e.g., !clear)
    await bot.process_commands(message)

    # Check if the bot was mentioned in the channel
    if bot.user in message.mentions:
        # Strip out the mention tag from text
        raw_prompt = (
            message.content.replace(f"<@{bot.user.id}>", "")
            .replace(f"<@!{bot.user.id}>", "")
            .strip()
        )

        if not raw_prompt:
            await message.reply("👋 Need help? Tag me with a question like `@ChatBot Explain quantum computing!`")
            return

        if not ai_client:
            await message.reply("❌ Gemini API Key is missing. Check your Railway environment variables.")
            return

        async with message.channel.typing():
            user_id = message.author.id

            # Initialize user memory if not present
            if user_id not in USER_MEMORY:
                USER_MEMORY[user_id] = []

            # Append current user prompt to history
            USER_MEMORY[user_id].append({"role": "user", "text": raw_prompt})

            # Trim history to maintain budget/context window
            if len(USER_MEMORY[user_id]) > MAX_MEMORY_HISTORY:
                USER_MEMORY[user_id] = USER_MEMORY[user_id][-MAX_MEMORY_HISTORY:]

            # Construct full context prompt from history
            formatted_prompt = ""
            for msg in USER_MEMORY[user_id]:
                prefix = "User" if msg["role"] == "user" else "Assistant"
                formatted_prompt += f"{prefix}: {msg['text']}\n"
            formatted_prompt += "Assistant:"

            try:
                # Run API call in an async executor to avoid blocking the main event loop
                loop = asyncio.get_running_loop()
                response = await loop.run_in_executor(
                    None,
                    lambda: ai_client.models.generate_content(
                        model="gemini-1.5-flash",
                        contents=formatted_prompt
                    )
                )

                ai_reply = response.text.strip() if response and response.text else "I couldn't generate a text response."

                # Save model response back to memory
                USER_MEMORY[user_id].append({"role": "model", "text": ai_reply})

                # Discord Embed limit is 4096 characters in description
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
                    # Split long answers into 2000-character plain text chunks
                    chunks = [ai_reply[i:i + 1900] for i in range(0, len(ai_reply), 1900)]
                    for idx, chunk in enumerate(chunks):
                        if idx == 0:
                            await message.reply(f"**AI Response (Part {idx + 1}):**\n{chunk}")
                        else:
                            await message.channel.send(f"**Part {idx + 1}:**\n{chunk}")

            except Exception as e:
                logging.error(f"Gemini API Execution Error: {e}", exc_info=True)
                
                # Rollback user's failed prompt from memory
                if USER_MEMORY[user_id] and USER_MEMORY[user_id][-1]["role"] == "user":
                    USER_MEMORY[user_id].pop()

                err_embed = discord.Embed(
                    title="⚠️ Generation Error",
                    description=f"An error occurred while contacting the AI model:\n`{str(e)[:300]}`",
                    color=discord.Color.red()
                )
                await message.reply(embed=err_embed)


if __name__ == "__main__":
    if not DISCORD_TOKEN:
        logging.critical("DISCORD_TOKEN environment variable not set. Exiting.")
    else:
        bot.run(DISCORD_TOKEN)
        
