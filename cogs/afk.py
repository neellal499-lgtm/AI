import time
import logging
import discord
from discord.ext import commands

logger = logging.getLogger("AFKCog")

class AFK(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Dictionary structure:
        # { user_id: { "reason": str, "time": float, "original_name": str } }
        self.afk_users = {}

    def format_duration(self, seconds: float) -> str:
        """Helper method to format elapsed seconds into a human-readable string."""
        total_seconds = int(seconds)
        days, remainder = divmod(total_seconds, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, secs = divmod(remainder, 60)

        parts = []
        if days > 0:
            parts.append(f"{days}d")
        if hours > 0:
            parts.append(f"{hours}h")
        if minutes > 0:
            parts.append(f"{minutes}m")
        if secs > 0 or not parts:
            parts.append(f"{secs}s")

        return " ".join(parts)

    @commands.hybrid_command(name="afk", description="Set your AFK status with a custom reason.")
    @commands.guild_only()
    async def afk(self, ctx: commands.Context, *, reason: str):
        user = ctx.author
        now = time.time()
        original_display_name = user.display_name

        # Save AFK state in memory
        self.afk_users[user.id] = {
            "reason": reason,
            "time": now,
            "original_name": original_display_name
        }

        # Attempt to change the user's nickname to [AFK] Name
        new_nick = f"[AFK] {original_display_name}"
        if len(new_nick) > 32:
            new_nick = new_nick[:32]  # Discord nickname cap limit

        nick_changed = False
        try:
            await user.edit(nick=new_nick)
            nick_changed = True
        except discord.Forbidden:
            logger.warning(f"Could not change nickname for {user} (Missing Manage Nicknames or hierarchy issue).")
        except Exception as e:
            logger.error(f"Error changing nickname for {user}: {e}")

        embed = discord.Embed(
            title="🌙 AFK Status Enabled",
            description=f"{user.mention} you're set as afk for **{reason}**",
            color=discord.Color.dark_theme()
        )
        if nick_changed:
            embed.set_footer(text="Updated display name to [AFK].")
        else:
            embed.set_footer(text="Note: Couldn't edit nickname due to server permissions.")

        await ctx.send(embed=embed)

    # -------------------------------------------------------------------
    # ERROR HANDLING (MissingRequiredArgument)
    # -------------------------------------------------------------------
    @afk.error
    async def afk_error(self, ctx: commands.Context, error: commands.CommandError):
        if isinstance(error, commands.MissingRequiredArgument):
            embed = discord.Embed(
                title="⚠️ Missing Reason",
                description=f"{ctx.author.mention}, please provide a reason for going AFK!\n\n**Usage:** `/afk <reason>` or `@ChatBot afk <reason>`",
                color=discord.Color.red()
            )
            await ctx.send(embed=embed)
        else:
            logger.error(f"Unhandled AFK error: {error}")

    # -------------------------------------------------------------------
    # MESSAGE LISTENER
    # -------------------------------------------------------------------
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # Ignore bot messages
        if message.author.bot or not message.guild:
            return

        author = message.author
        now = time.time()

        # 1. CHECK IF THE AUTHOR IS RETURNING FROM AFK
        if author.id in self.afk_users:
            afk_data = self.afk_users.pop(author.id)
            elapsed_seconds = now - afk_data["time"]
            duration_str = self.format_duration(elapsed_seconds)
            original_name = afk_data["original_name"]

            # Restore original nickname if possible
            try:
                # If they were given an [AFK] tag, reset back to original name
                if author.display_name.startswith("[AFK]"):
                    await author.edit(nick=original_name if original_name != author.name else None)
            except discord.Forbidden:
                pass
            except Exception as e:
                logger.error(f"Failed to restore nickname for {author}: {e}")

            embed = discord.Embed(
                title="👋 Welcome Back!",
                description=f"{author.mention} you're back, you were afk since **{duration_str}** NOW GO AND CHAT!!",
                color=discord.Color.green()
            )
            await message.channel.send(embed=embed)

        # 2. CHECK IF THE MESSAGE MENTIONS ANY AFK USERS
        if message.mentions:
            for pinged_user in message.mentions:
                # Skip self-pings (already handled by return check above)
                if pinged_user.id == author.id:
                    continue

                if pinged_user.id in self.afk_users:
                    afk_data = self.afk_users[pinged_user.id]
                    elapsed_seconds = now - afk_data["time"]
                    duration_str = self.format_duration(elapsed_seconds)
                    reason = afk_data["reason"]

                    embed = discord.Embed(
                        title="💤 User is AFK",
                        description=f"{author.mention} the user **{pinged_user.display_name}** is afk for **{reason}** since **{duration_str}**",
                        color=discord.Color.orange()
                    )
                    await message.channel.send(embed=embed)


async def setup(bot):
    await bot.add_cog(AFK(bot))
          
