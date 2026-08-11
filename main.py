import os
import discord
from discord.ext import commands
from google import genai

# Load tokens securely from Railway environment variables
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Initialize Google GenAI client
ai_client = genai.Client(api_key=GEMINI_API_KEY)

# Set up required Discord intents
intents = discord.Intents.default()
intents.message_content = True  # Allows reading message text for @bot mentions

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    print(f"✅ Bot successfully logged in as {bot.user} (ID: {bot.user.id})")


@bot.event
async def on_message(message):
    # 1. Ignore messages sent by bots (including itself)
    if message.author.bot:
        return

    # 2. Check if the bot was mentioned in the message
    if bot.user in message.mentions:
        # Strip out the @bot mention tag from the text
        question = (
            message.content.replace(f"<@{bot.user.id}>", "")
            .replace(f"<@!{bot.user.id}>", "")
            .strip()
        )

        # Handle empty pings (user tags @bot with no question)
        if not question:
            await message.reply("Hey! Tag me and ask a question, like `@ChatBot What is Termux?`")
            return

        async with message.channel.typing():
            try:
                # Call Gemini API with gemini-1.5-flash
                response = ai_client.models.generate_content(
                    model="gemini-1.5-flash",
                    contents=question
                )

                ai_reply = response.text if response.text else "No response generated."

                # Discord embed description limit is 4096 characters
                if len(ai_reply) > 4000:
                    ai_reply = ai_reply[:4000] + "\n\n*(Response truncated due to length)*"

                # 3. Create response Embed
                embed = discord.Embed(
                    title="🤖 AI Assistant",
                    description=ai_reply,
                    color=discord.Color.blue()
                )
                
                # Add user question field and requestor footer
                embed.add_field(
                    name="Question",
                    value=question[:1024],
                    inline=False
                )
                embed.set_footer(
                    text=f"Requested by {message.author.display_name}",
                    icon_url=message.author.display_avatar.url
                )

                # Send embed reply
                await message.reply(embed=embed, mention_author=True)

            except Exception as e:
                # Print exact error trace to Railway deployment logs for easy debugging
                print(f"[ERROR] Gemini API call failed: {e}")

                err_embed = discord.Embed(
                    title="❌ Error",
                    description="Failed to generate a response. Please check Railway logs or API key.",
                    color=discord.Color.red()
                )
                await message.reply(embed=err_embed)

    # Process standard prefix commands (e.g., !ping)
    await bot.process_commands(message)


# Start the bot
if __name__ == "__main__":
    if not DISCORD_TOKEN:
        print("[CRITICAL] DISCORD_TOKEN variable is missing from environment variables!")
    elif not GEMINI_API_KEY:
        print("[CRITICAL] GEMINI_API_KEY variable is missing from environment variables!")
    else:
        bot.run(DISCORD_TOKEN)
        
