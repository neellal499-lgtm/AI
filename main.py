import os
import discord
from discord.ext import commands
from google import genai

# Read environment variables set in Railway
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Initialize Gemini Client
ai_client = genai.Client(api_key=GEMINI_API_KEY)

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"Bot successfully running on Railway as {bot.user}")

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    if bot.user in message.mentions:
        question = message.content.replace(f"<@{bot.user.id}>", "").replace(f"<@!{bot.user.id}>", "").strip()
        
        if not question:
            await message.channel.send("Ask me a question after pinging me!")
            return

        async with message.channel.typing():
            try:
                response = ai_client.models.generate_content(
                    model='gemini-2.5-flash',
                    contents=question
                )
                
                embed = discord.Embed(
                    title="🤖 AI Response",
                    description=response.text[:4000],
                    color=discord.Color.blue()
                )
                embed.set_footer(text=f"Requested by {message.author.display_name}")
                
                await message.reply(embed=embed)
            except Exception as e:
                print(f"Error: {e}")
                await message.reply("Failed to generate a response.")

    await bot.process_commands(message)

# Run the bot using the token variable
bot.run(DISCORD_TOKEN)

