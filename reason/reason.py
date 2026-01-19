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
        await interaction.response.send_message("You accepted the reason!", ephemeral=True)

    @discord.ui.button(label="Reject", style=discord.ButtonStyle.danger, custom_id="reason_reject")
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("You rejected the reason!", ephemeral=True)

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
        default_guild = {
            "channel_id": None,
            "opt_out_list": [],
            "test_enabled": False,
            "test_channel_id": None,
        }
        self.config.register_guild(**default_guild)
        
        reasons_path = Path(__file__).parent / "reasons.json"
        try:
            with open(reasons_path, "r", encoding="utf-8") as f:
                self.reasons = json.load(f)
        except Exception as e:
            self.reasons = ["Error loading reasons."]
            print(f"Error loading reasons.json: {e}")

        self.reason_loop.start()
        self.reason_test_loop.start()

    def _build_reason_embed(self, *, member: discord.abc.User, reason_text: str, title: str = "Reason") -> discord.Embed:
        embed = discord.Embed(
            title=title,
            description="Use the buttons below to respond.",
            color=discord.Color.random(),
        )
        embed.add_field(
            name="Tip",
            value=(
                "Your choice is private. "
                "Use `/reason help` to learn what this cog does and how to configure drops."
            ),
            inline=False,
        )
        embed.set_footer(text=f"Selected for: {member.display_name} | Your choice is private")
        return embed

    def _build_reason_message_content(self, *, member: discord.abc.User, reason_text: str) -> str:
        # Regular message content renders larger than embed descriptions.
        # Keep within Discord's 2000 character limit.
        prefix = f"Hey {member.mention}, here is a reason for you!\n\n>>> **"
        suffix = "**"
        max_reason_len = 2000 - len(prefix) - len(suffix)
        if max_reason_len < 0:
            # Extremely defensive; should never happen.
            return f"Hey {member.mention}, here is a reason for you!"
        trimmed = reason_text
        if len(trimmed) > max_reason_len:
            trimmed = trimmed[: max(0, max_reason_len - 1)] + "…"
        return prefix + trimmed + suffix

    def _eligible_members_for_channel(
        self,
        *,
        guild: discord.Guild,
        channel: discord.abc.GuildChannel,
        opt_out: list[int],
    ) -> list[discord.Member]:
        # We can't reliably know "who is currently in" a text channel, so we use
        # "can view channel" as the meaning of "from that channel".
        members: list[discord.Member] = []
        for m in guild.members:
            if m.bot or m.id in opt_out:
                continue
            perms = channel.permissions_for(m)
            # discord.py v2: view_channel is the primary gate.
            if getattr(perms, "view_channel", False):
                members.append(m)
        return members

    async def _send_reason_drop(self, *, guild: discord.Guild, channel_id: int, title: str = "Reason") -> None:
        channel = guild.get_channel(channel_id)
        if not channel or not isinstance(channel, discord.abc.GuildChannel):
            return

        opt_out = await self.config.guild(guild).opt_out_list()
        members = self._eligible_members_for_channel(guild=guild, channel=channel, opt_out=opt_out)
        if not members:
            return

        member = random.choice(members)
        reason_text = random.choice(self.reasons)
        embed = self._build_reason_embed(member=member, reason_text=reason_text, title=title)
        view = ReasonView(self, target_user_id=member.id)
        message_content = self._build_reason_message_content(member=member, reason_text=reason_text)

        try:
            await channel.send(content=message_content, embed=embed, view=view)  # type: ignore[attr-defined]
        except discord.Forbidden:
            pass
        except Exception as e:
            print(f"Error sending reason in guild {guild.id}: {e}")

    def cog_unload(self):
        self.reason_loop.cancel()
        self.reason_test_loop.cancel()

    @tasks.loop(hours=48)
    async def reason_loop(self):
        for guild in self.bot.guilds:
            # If test mode is enabled, the 1-minute loop handles this guild.
            if await self.config.guild(guild).test_enabled():
                continue
            channel_id = await self.config.guild(guild).channel_id()
            if not channel_id:
                continue

            await self._send_reason_drop(guild=guild, channel_id=channel_id, title="Reason")

    @tasks.loop(minutes=1)
    async def reason_test_loop(self):
        for guild in self.bot.guilds:
            if not await self.config.guild(guild).test_enabled():
                continue
            channel_id = await self.config.guild(guild).test_channel_id()
            if not channel_id:
                continue
            await self._send_reason_drop(guild=guild, channel_id=channel_id, title="Reason (Test)")

    @reason_loop.before_loop
    async def before_reason_loop(self):
        await self.bot.wait_until_ready()

    @reason_test_loop.before_loop
    async def before_reason_test_loop(self):
        await self.bot.wait_until_ready()

    @commands.hybrid_group(name="reason", fallback="show")
    async def reason(self, ctx):
        """Get a random reason."""
        # If invoked without subcommand (text) or via fallback (slash)
        await self.send_reason(ctx)

    async def send_reason(self, ctx):
        reason_text = random.choice(self.reasons)
        embed = self._build_reason_embed(member=ctx.author, reason_text=reason_text, title="Reason")
        view = ReasonView(self, target_user_id=ctx.author.id)
        content = self._build_reason_message_content(member=ctx.author, reason_text=reason_text)
        await ctx.send(content=content, embed=embed, view=view)

    @reason.command(name="channel")
    @app_commands.describe(channel="The channel for random drops")
    @checks.admin_or_permissions(manage_guild=True)
    @commands.guild_only()
    async def set_channel(self, ctx, channel: discord.TextChannel):
        """Set the channel where the embeds will be dropped."""
        await self.config.guild(ctx.guild).channel_id.set(channel.id)
        await ctx.send(f"Reason drops will now happen in {channel.mention}.")

    @reason.command(name="channelclear")
    @checks.admin_or_permissions(manage_guild=True)
    @commands.guild_only()
    async def clear_channel(self, ctx):
        """Disable the 48-hour reason drops for this server."""
        await self.config.guild(ctx.guild).channel_id.set(None)
        await ctx.send("🛑 48-hour reason drops disabled (drop channel cleared).")

    @reason.command(name="test")
    @app_commands.describe(channel="The channel used for 1-minute test drops")
    @checks.admin_or_permissions(manage_guild=True)
    @commands.guild_only()
    async def reason_test(self, ctx, channel: discord.TextChannel | None = None):
        """Enable 1-minute test drops (so you don't have to wait 48h)."""
        channel = channel or ctx.channel
        if not isinstance(channel, discord.TextChannel):
            await ctx.send("Please choose a text channel.")
            return
        await self.config.guild(ctx.guild).test_channel_id.set(channel.id)
        await self.config.guild(ctx.guild).test_enabled.set(True)
        await ctx.send(f"✅ Test mode enabled. A reason will drop every minute in {channel.mention}.")

    @reason.command(name="teststop")
    @checks.admin_or_permissions(manage_guild=True)
    @commands.guild_only()
    async def reason_teststop(self, ctx):
        """Disable 1-minute test drops."""
        await self.config.guild(ctx.guild).test_enabled.set(False)
        await self.config.guild(ctx.guild).test_channel_id.set(None)
        await ctx.send("🛑 Test mode disabled.")

    @reason.command(name="testnow")
    @checks.admin_or_permissions(manage_guild=True)
    @commands.guild_only()
    async def reason_testnow(self, ctx):
        """Send one test drop immediately (uses the configured test channel)."""
        channel_id = await self.config.guild(ctx.guild).test_channel_id()
        if not channel_id:
            await ctx.send("No test channel set. Use `/reason test #channel` first.")
            return
        await self._send_reason_drop(guild=ctx.guild, channel_id=channel_id, title="Reason (Test)")
        await ctx.send("✅ Test drop sent.")

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
