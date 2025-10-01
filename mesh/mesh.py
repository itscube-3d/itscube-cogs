import asyncio
import random
import time
from dataclasses import dataclass, field
from typing import Dict, Optional, List, Tuple

import discord
from discord import app_commands
from redbot.core import commands, Config, checks

# ---------- helpers: rarity table & name generation ----------

RARITY_WEIGHTS = [
    ("Common",    55.00, 0x8b8b8b, "🟫"),
    ("Rare",      35.00, 0x3da5ff, "🔷"),
    ("Epic",       8.00, 0x9b59b6, "🟣"),
    ("Legendary",  1.60, 0xffa500, "🟧"),
    ("Mythic",     0.34, 0x00ffa2, "🟢"),
    ("Goddess",    0.06, 0xff2ed1, "✨"),
]
# weights sum to 100; adjust if you wish

COMMON_BASES   = ["Cube", "Sphere", "Plane", "Cylinder", "Cone", "Torus", "Icosphere", "Capsule", "Pyramid", "Suzanne"]
RARE_BASES     = COMMON_BASES + ["Low-Poly Arch", "Bezier Orb", "Offset Gear", "Truss Beam"]
EPIC_BASES     = RARE_BASES + ["Voronoi Shell", "Boolean Core", "Arrayed Fan"]
LEGEND_BASES   = EPIC_BASES + ["Catmull Dome", "Subdivision Relic", "Lattice Heart"]
MYTHIC_UNIQUES = ["Markyn Ring of Majesty", "Doombringer"]
GODDESS_UNIQUE = "Metatron"

COMMON_ADJ     = ["Default", "Beveled", "Smooth", "Low-Poly", "Decimated", "Chiseled", "Matte", "Brushed", "Plain"]
RARE_ADJ       = COMMON_ADJ + ["Iridescent", "Polished", "Engraved", "Inlaid", "Hardened", "Embossed", "Dimpled"]
EPIC_ADJ       = RARE_ADJ   + ["Resonant", "Phase-Shifted", "Radiant", "Crystalline", "Fractal", "Spectral"]
LEGEND_ADJ     = EPIC_ADJ   + ["Sunglint", "Starforged", "Chrono-locked"]
MYTHIC_ADJ     = LEGEND_ADJ + ["Singularity", "Axiom", "Evergold"]
MATERIALS      = ["Clay", "Plastic", "Glass", "Obsidian", "Copper", "Steel", "Carbon", "Quartz", "Marble", "Onyx"]

def pick_rarity() -> Tuple[str, int, str]:
    names  = [r[0] for r in RARITY_WEIGHTS]
    weights = [r[1] for r in RARITY_WEIGHTS]
    rarity = random.choices(names, weights=weights, k=1)[0]
    color  = next(c for (n, _, c, _) in RARITY_WEIGHTS if n == rarity)
    emoji  = next(e for (n, _, _, e) in RARITY_WEIGHTS if n == rarity)
    return rarity, color, emoji

def generate_item_for(rarity: str) -> str:
    if rarity == "Goddess":
        return GODDESS_UNIQUE
    if rarity == "Mythic":
        return random.choice(MYTHIC_UNIQUES)
    if rarity == "Legendary":
        adj = random.choice(LEGEND_ADJ)
        base = random.choice(LEGEND_BASES)
        mat = random.choice(MATERIALS)
        return f"{adj} {mat} {base}"
    if rarity == "Epic":
        adj = random.choice(EPIC_ADJ)
        base = random.choice(EPIC_BASES)
        mat = random.choice(MATERIALS)
        return f"{adj} {mat} {base}"
    if rarity == "Rare":
        adj = random.choice(RARE_ADJ)
        base = random.choice(RARE_BASES)
        mat = random.choice(MATERIALS)
        return f"{adj} {mat} {base}"
    # Common
    adj = random.choice(COMMON_ADJ)
    base = random.choice(COMMON_BASES)
    mat = random.choice(MATERIALS)
    # Weighted chance to keep it ultra-simple like "Default Cube"
    if adj == "Default":
        return f"{adj} {base}"
    return f"{adj} {mat} {base}"

# ---------- state containers ----------

@dataclass
class DropState:
    channel_id: Optional[int] = None
    active_message_id: Optional[int] = None
    drop_started_at: Optional[float] = None
    claimed_by: Optional[int] = None
    claim_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    waiting_for_claim: Optional[asyncio.Event] = None
    task: Optional[asyncio.Task] = None

# ---------- the cog ----------

class Mesh(commands.Cog):
    """Mesh drop minigame."""

    guild_defaults = {
        "drop_channel_id": None,
        "expiry_seconds": 600,   # 10 minutes to claim before it fizzles
        "min_interval": 1800,    # 30min
        "max_interval": 3600,    # 60min
        "user_attempt_cooldown": 2.0,  # seconds between attempts per user
    }

    member_defaults = {
        "last_attempt": 0.0,
        "claims": 0,
        # rarity counters stored raw for flexibility
    }

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=0xC0DEB00F, force_registration=True)
        self.config.register_guild(**self.guild_defaults)
        self.config.register_member(**self.member_defaults)
        self._states: Dict[int, DropState] = {}

    def cog_unload(self):
        for state in self._states.values():
            if state.task and not state.task.done():
                state.task.cancel()

    # ---------- setup & background tasks ----------

    async def _ensure_state_task(self, guild: discord.Guild):
        state = self._states.get(guild.id)
        if not state:
            state = DropState()
            self._states[guild.id] = state

        if state.task and not state.task.done():
            return  # already running

        # make sure there's a channel set
        channel_id = await self.config.guild(guild).drop_channel_id()
        if not channel_id:
            return

        state.channel_id = channel_id
        state.waiting_for_claim = asyncio.Event()
        state.waiting_for_claim.clear()

        async def runner():
            await self.bot.wait_until_ready()
            while True:
                gconf = self.config.guild(guild)
                min_i = await gconf.min_interval()
                max_i = await gconf.max_interval()
                sleep_for = random.randint(min_i, max_i)
                await asyncio.sleep(sleep_for)

                # re-check configured channel
                channel_id_now = await gconf.drop_channel_id()
                if not channel_id_now:
                    continue
                channel = guild.get_channel(channel_id_now)
                if not isinstance(channel, discord.TextChannel):
                    continue

                # if a previous drop is still active, skip
                if state.active_message_id and state.claimed_by is None:
                    continue

                # issue a drop
                try:
                    embed = discord.Embed(
                        title="A Mesh Appears",
                        description="⬛ **A mysterious mesh shimmers into existence...**\nType `mesh` to reveal it!",
                        color=discord.Color.dark_grey()
                    )
                    expiry = await gconf.expiry_seconds()
                    embed.set_footer(text=f"Expires in {expiry//60} min if not claimed.")
                    msg = await channel.send(embed=embed)
                    state.active_message_id = msg.id
                    state.drop_started_at = time.time()
                    state.claimed_by = None
                    state.waiting_for_claim = asyncio.Event()

                    # wait for claim or timeout
                    try:
                        await asyncio.wait_for(state.waiting_for_claim.wait(), timeout=expiry)
                    except asyncio.TimeoutError:
                        # fizzle the drop
                        try:
                            await msg.reply("⏳ The mesh faded away.")
                        except Exception:
                            pass
                        state.active_message_id = None
                        state.drop_started_at = None
                        state.claimed_by = None
                except asyncio.CancelledError:
                    break
                except Exception:
                    # swallow unexpected errors; keep loop alive
                    await asyncio.sleep(5)

        state.task = self.bot.loop.create_task(runner())

    @commands.Cog.listener()
    async def on_guild_available(self, guild: discord.Guild):
        await self._ensure_state_task(guild)

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild):
        await self._ensure_state_task(guild)

    # ---------- admin: set channel ----------

    @commands.hybrid_command(name="setchannel", description="Set the channel used for mesh drops.")
    @checks.admin_or_permissions(manage_guild=True)
    @commands.guild_only()
    async def setchannel(self, ctx: commands.Context, channel: discord.TextChannel):
        """Pick a drop channel via a channel dropdown in slash UI, or pass a channel mention in prefix mode."""
        await self.config.guild(ctx.guild).drop_channel_id.set(channel.id)
        # boot/refresh the loop task
        await self._ensure_state_task(ctx.guild)
        await ctx.reply(f"✅ Mesh drops will appear in {channel.mention}.")

    # ---------- user: claim via slash ----------

    @commands.hybrid_command(name="mesh", description="Reveal the active mesh (if any).")
    @commands.guild_only()
    async def mesh_cmd(self, ctx: commands.Context):
        await self._handle_claim(ctx=ctx)

    # ---------- user: claim via typing 'mesh' ----------

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        content = message.content.strip().lower()
        if content != "mesh":
            return

        gconf = self.config.guild(message.guild)
        channel_id = await gconf.drop_channel_id()
        if not channel_id or message.channel.id != channel_id:
            return  # only listen in configured channel

        # channel ok; attempt or 🚫
        state = self._states.get(message.guild.id)
        if not state or not state.active_message_id or state.claimed_by is not None:
            try:
                await message.add_reaction("🚫")
            except Exception:
                pass
            return

        # convert to a claim flow similar to slash
        # wrap message objects in a faux context-like shim
        class DummyCtx:
            def __init__(self, bot, guild, channel, author, message):
                self.bot = bot
                self.guild = guild
                self.channel = channel
                self.author = author
                self.message = message
                self.interaction = None  # text message
            async def send(self, *a, **k):  # for fallback
                return await channel.send(*a, **k)
            async def reply(self, *a, **k):
                return await message.reply(*a, **k)

        dummy = DummyCtx(self.bot, message.guild, message.channel, message.author, message)
        await self._handle_claim(ctx=dummy)

    # ---------- claim logic ----------

    async def _handle_claim(self, ctx):
        guild: discord.Guild = ctx.guild
        member: discord.Member = ctx.author
        gconf = self.config.guild(guild)
        state = self._states.get(guild.id)

        # cooldown check
        mconf = self.config.member(member)
        last = await mconf.last_attempt()
        cd = await gconf.user_attempt_cooldown()
        now = time.time()
        if now - last < cd:
            # be silent to avoid spam; optional to react
            try:
                if getattr(ctx, "message", None):
                    await ctx.message.add_reaction("⏳")
                else:
                    await ctx.reply("⏳ Slow down a bit.", ephemeral=True)  # hybrid slash will accept ephemeral on interaction
            except Exception:
                pass
            return
        await mconf.last_attempt.set(now)

        drop_channel_id = await gconf.drop_channel_id()
        if not drop_channel_id:
            await ctx.reply("⚠️ No drop channel configured yet. Ask an admin to run `/setchannel`.", ephemeral=True if getattr(ctx, "interaction", None) else False)
            return

        if not state or not state.active_message_id or state.claimed_by is not None:
            # no active drop
            if getattr(ctx, "message", None):
                try:
                    await ctx.message.add_reaction("🚫")
                except Exception:
                    pass
            else:
                await ctx.reply("🚫 No active mesh right now.", ephemeral=True)
            return

        # verify correct channel
        if hasattr(ctx, "channel") and ctx.channel.id != drop_channel_id:
            if getattr(ctx, "message", None):
                try:
                    await ctx.message.add_reaction("🚫")
                except Exception:
                    pass
            else:
                await ctx.reply("🚫 Try this in the configured drop channel.", ephemeral=True)
            return

        # race-lock
        async with state.claim_lock:
            if state.claimed_by is not None:
                # lost the race
                if getattr(ctx, "message", None):
                    try:
                        await ctx.message.add_reaction("❌")
                    except Exception:
                        pass
                else:
                    await ctx.reply("❌ Someone else already revealed it.", ephemeral=True)
                return

            # determine rarity + item
            rarity, color, emoji = pick_rarity()
            item_name = generate_item_for(rarity)
            state.claimed_by = member.id
            if state.waiting_for_claim:
                state.waiting_for_claim.set()

        # update stats
        await self.config.member(member).claims.set((await self.config.member(member).claims()) + 1)
        # store rarity-specific counters under raw
        key = f"rarity_{rarity.lower()}"
        current = await self.config.member(member).get_raw(key, default=0)
        await self.config.member(member).set_raw(key, value=current + 1)

        # send reveal
        try:
            embed = discord.Embed(
                title=f"{emoji} {rarity} Mesh Revealed!",
                description=f"**{member.mention}** unveiled **{item_name}**",
                color=color
            )
            embed.set_footer(text="gg 🧊")
            await ctx.reply(embed=embed)
        except Exception:
            pass

        # clear active drop ref so the loop can schedule again (the loop already continues after event.set())
        state.active_message_id = None
        state.drop_started_at = None

    # ---------- optional: quick sanity check ----------

    @commands.command(name="meshdebug")
    @checks.is_owner()
    async def mesh_debug(self, ctx: commands.Context, action: str = "ping"):
        """Owner debug helper (ping | dropnow)."""
        if action == "ping":
            await ctx.send("pong")
            return
        if action == "dropnow":
            guild = ctx.guild
            if not guild:
                return
            await self._ensure_state_task(guild)
            state = self._states.get(guild.id)
            if not state:
                await ctx.send("no state")
                return
            # fake a quick drop
            gconf = self.config.guild(guild)
            channel_id = await gconf.drop_channel_id()
            if not channel_id:
                await ctx.send("no channel set")
                return
            channel = guild.get_channel(channel_id)
            if not channel:
                await ctx.send("channel missing")
                return
            if state.active_message_id and state.claimed_by is None:
                await ctx.send("drop already active")
                return
            embed = discord.Embed(
                title="A Mesh Appears (debug)",
                description="⬛ **Type `mesh` to reveal it!**",
                color=discord.Color.dark_grey()
            )
            expiry = await gconf.expiry_seconds()
            embed.set_footer(text=f"Expires in {expiry//60} min if not claimed.")
            msg = await channel.send(embed=embed)
            state.active_message_id = msg.id
            state.drop_started_at = time.time()
            state.claimed_by = None
            state.waiting_for_claim = asyncio.Event()
            await ctx.send("debug drop sent ✅")
