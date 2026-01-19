import discord
import json
import random
from pathlib import Path
from discord.ext import tasks
from redbot.core import commands, Config, app_commands, checks

class ReasonView(discord.ui.View):
    def __init__(self, cog, *, target_user_id: int | None = None):
        super().__init__(timeout=None)
        self.cog = cog
        self.target_user_id = target_user_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # If a target is set, only that user can click the buttons.
        if self.target_user_id is not None and interaction.user and interaction.user.id != self.target_user_id:
            await interaction.response.send_message("These buttons are only for the selected user.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.success, custom_id="reason_accept")
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("You accepted the reason! (This choice is visible only to you).", ephemeral=True)

    @discord.ui.button(label="Reject", style=discord.ButtonStyle.danger, custom_id="reason_reject")
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("You rejected the reason! (This choice is visible only to you).", ephemeral=True)

    @discord.ui.button(label="Stop showing me this", style=discord.ButtonStyle.secondary, custom_id="reason_stop")
    async def stop_showing(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.guild is None:
            await interaction.response.send_message("This button only works inside a server.", ephemeral=True)
            return
        async with self.cog.config.guild(interaction.guild).opt_out_list() as opt_out:
            if interaction.user.id not in opt_out:
                opt_out.append(interaction.user.id)
                await interaction.response.send_message("You won't be picked for random reasons anymore.", ephemeral=True)
            else:
                await interaction.response.send_message("You have already opted out.", ephemeral=True)

class Reason(commands.Cog):
    """
    Ever needed a graceful way to say “no”?
    This tiny cog returns random, generic, creative, and sometimes hilarious reasons.
    """

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=9876543210, force_registration=True)
        default_guild = {"channel_id": None, "opt_out_list": []}
        self.config.register_guild(**default_guild)
        
        reasons_path = Path(__file__).parent / "reasons.json"
        try:
            with open(reasons_path, "r", encoding="utf-8") as f:
                self.reasons = json.load(f)
        except Exception as e:
            self.reasons = ["Error loading reasons."]
            print(f"Error loading reasons.json: {e}")

        self.reason_loop.start()

    def cog_unload(self):
        self.reason_loop.cancel()

    @tasks.loop(hours=48)
    async def reason_loop(self):
        for guild in self.bot.guilds:
            channel_id = await self.config.guild(guild).channel_id()
            if not channel_id:
                continue
            
            channel = guild.get_channel(channel_id)
            if not channel:
                # Cleanup if channel was deleted? 
                # For now just skip
                continue

            opt_out = await self.config.guild(guild).opt_out_list()
            # Pick a random member who is not a bot and not opted out
            # Fetching members might be needed if intent not present, but using guild.members usually works if cached
            members = [m for m in guild.members if not m.bot and m.id not in opt_out]
            
            if not members:
                continue

            member = random.choice(members)
            reason_text = random.choice(self.reasons)
            
            embed = discord.Embed(
                title="Reason to Reject",
                description=reason_text,
                color=discord.Color.random()
            )
            embed.set_footer(text=f"Selected for: {member.display_name} | Your choice is private")
            
            view = ReasonView(self, target_user_id=member.id)
            message_content = f"Hey {member.mention}, here is a reason for you!"
            
            try:
                await channel.send(content=message_content, embed=embed, view=view)
            except discord.Forbidden:
                pass
            except Exception as e:
                print(f"Error sending reason in guild {guild.id}: {e}")

    @reason_loop.before_loop
    async def before_reason_loop(self):
        await self.bot.wait_until_ready()

    @commands.hybrid_group(name="reason", fallback="show")
    async def reason(self, ctx):
        """Get a random reason."""
        # If invoked without subcommand (text) or via fallback (slash)
        await self.send_reason(ctx)

    async def send_reason(self, ctx):
        reason_text = random.choice(self.reasons)
        embed = discord.Embed(
            title="Reason",
            description=reason_text,
            color=discord.Color.random()
        )
        view = ReasonView(self, target_user_id=ctx.author.id)
        await ctx.send(content=f"Hey {ctx.author.mention}, here is a reason for you!", embed=embed, view=view)

    @reason.command(name="channel")
    @app_commands.describe(channel="The channel for random drops")
    @checks.admin_or_permissions(manage_guild=True)
    @commands.guild_only()
    async def set_channel(self, ctx, channel: discord.TextChannel):
        """Set the channel where the embeds will be dropped."""
        await self.config.guild(ctx.guild).channel_id.set(channel.id)
        await ctx.send(f"Reason drops will now happen in {channel.mention}.")

    @reason.command(name="help")
    async def reason_help(self, ctx):
        """Show help for the Reason cog."""
        msg = (
            "Ever needed a graceful way to say “no”?\n"
            "This tiny cog returns random, generic, creative, and sometimes hilarious reasons (to reject) — perfectly suited for any scenario: personal, professional, student life, dev life, or just because.\n\n"
            "Built for humans, excuses, and humor."
        )
        embed = discord.Embed(title="Reason Help", description=msg, color=discord.Color.blue())
        embed.set_footer(text="Use `/reason` to get a reason instantly.")
        await ctx.send(embed=embed)
