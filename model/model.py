import asyncio
import random
import time
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple, List

import discord
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
# weights sum ~100; adjust to taste

BASE_POOL_100 = [
    "Cube","Sphere","Plane","Cylinder","Cone","Torus","Icosphere","Capsule","Pyramid","Suzanne",
    "Tetrahedron","Octahedron","Dodecahedron","Icosahedron","Prism","Tri-Prism","Hex Prism","Arch","Stair","Gear",
    "Offset Gear","Bevel Gear","Helix","Coil","Spring","Knot","Trefoil","Mobius","Lattice","Dome",
    "Vault","Arc","Bridge","Truss","Beam","Bracket","Frame","Panel","Louver","Grille",
    "Vent","Fan","Rotor","Propeller","Blade","Wing","Fin","Rudder","Rail","Track",
    "Ramp","Spiral Stair","Spline Arc","Bezier Orb","NURBS Surface","Patch","Voronoi Shell","Boolean Core","Arrayed Fan","Catmull Dome",
    "Subdivision Relic","Lattice Heart","Low-Poly Arch","Pillar","Column","Obelisk","Monolith","Slab","Tile","Brick",
    "Wedge","Chisel","Keystone","Ring","Halo","Torus Knot","Donut","Bowl","Vase","Amphora",
    "Bottle","Flask","Test Tube","Tube","Pipe","Elbow","Tee Junction","Manifold","Nozzle","Jet",
    "Lens","Prism Lens","Mirror","Reflector","Antenna","Dish","Radar","Satellite","Pod","Module"
]

COMMON_BASES = BASE_POOL_100[:60]
RARE_BASES   = BASE_POOL_100[:80]
EPIC_BASES   = BASE_POOL_100[:90]
LEGEND_BASES = BASE_POOL_100[:]

MATERIALS = [
    "Clay","Plastic","Glass","Obsidian","Copper","Steel","Carbon","Quartz","Marble","Onyx",
    "Titanium","Aluminum","Brass","Bronze","Iron","Gold","Silver","Cobalt","Nickel","Tungsten",
    "Granite","Basalt","Concrete","Wood","Jade","Emerald","Sapphire","Ruby","Amethyst","Topaz"
]

MYTHIC_UNIQUES = ["Markyn Ring of Majesty", "Doombringer"]
GODDESS_UNIQUE = "Metatron"

COMMON_ADJ = ["Default", "Beveled", "Smooth", "Low-Poly", "Decimated", "Chiseled", "Matte", "Brushed", "Plain"]
RARE_ADJ = COMMON_ADJ + ["Iridescent", "Polished", "Engraved", "Inlaid", "Hardened", "Embossed", "Dimpled"]
EPIC_ADJ = RARE_ADJ + ["Resonant", "Phase-Shifted", "Radiant", "Crystalline", "Fractal", "Spectral"]
LEGEND_ADJ = EPIC_ADJ + ["Sunglint", "Starforged", "Chrono-locked"]
MYTHIC_ADJ = LEGEND_ADJ + ["Singularity", "Axiom", "Evergold"]

def pick_rarity() -> Tuple[str, int, str]:
    names   = [r[0] for r in RARITY_WEIGHTS]
    weights = [r[1] for r in RARITY_WEIGHTS]
    rarity  = random.choices(names, weights=weights, k=1)[0]
    color   = next(c for (n, _, c, _) in RARITY_WEIGHTS if n == rarity)
    emoji   = next(e for (n, _, _, e) in RARITY_WEIGHTS if n == rarity)
    return rarity, color, emoji

def generate_item_for(rarity: str) -> str:
    if rarity == "Goddess":
        return GODDESS_UNIQUE
    if rarity == "Mythic":
        return random.choice(MYTHIC_UNIQUES)
    if rarity == "Legendary":
        adj, base, mat = random.choice(LEGEND_ADJ), random.choice(LEGEND_BASES), random.choice(MATERIALS)
        return f"{adj} {mat} {base}"
    if rarity == "Epic":
        adj, base, mat = random.choice(EPIC_ADJ), random.choice(EPIC_BASES), random.choice(MATERIALS)
        return f"{adj} {mat} {base}"
    if rarity == "Rare":
        adj, base, mat = random.choice(RARE_ADJ), random.choice(RARE_BASES), random.choice(MATERIALS)
        return f"{adj} {mat} {base}"
    adj, base, mat = random.choice(COMMON_ADJ), random.choice(COMMON_BASES), random.choice(MATERIALS)
    return f"{adj} {base}" if adj == "Default" else f"{adj} {mat} {base}"

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

# ---------- Pagination View ----------

class BagPaginator(discord.ui.View):
    def __init__(self, owner_id: int, pages: List[discord.Embed], timeout: int = 120):
        super().__init__(timeout=timeout)
        self.owner_id = owner_id
        self.pages = pages
        self.index = 0

    async def update(self, interaction: discord.Interaction):
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = False
        if self.index <= 0:
            self.prev_button.disabled = True  # type: ignore
        if self.index >= len(self.pages) - 1:
            self.next_button.disabled = True  # type: ignore
        await interaction.response.edit_message(embed=self.pages[self.index], view=self)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user and interaction.user.id != self.owner_id:
            await interaction.response.send_message("Only the requester can use these buttons.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="◀ Previous", style=discord.ButtonStyle.secondary)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.index > 0:
            self.index -= 1
        await self.update(interaction)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.index < len(self.pages) - 1:
            self.index += 1
        await self.update(interaction)

# ---------- the cog ----------

class Model(commands.Cog):
    """Model drop minigame (no-timeout; persists inventory)."""

    guild_defaults = {
        "drop_channel_id": None,
        "min_interval": 1800,    # 30min
        "max_interval": 3600,    # 60min
        "user_attempt_cooldown": 2.0,  # seconds between attempts per user
    }

    member_defaults = {
        "last_attempt": 0.0,
        "claims": 0,
        # rarity counters stored raw for flexibility, e.g. rarity_common, rarity_epic...
        # inventory stored under "items": list of dicts {name, rarity, emoji, ts}
        "items": [],
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

                # if a previous drop is still active, skip new one
                if state.active_message_id and state.claimed_by is None:
                    continue

                # issue a drop (NO TIMEOUT — waits until someone claims)
                try:
                    embed = discord.Embed(
                        title="A Model Appears",
                        description="⬛ **A mysterious model shimmers into existence...**\nType `model` to reveal it!",
                        color=discord.Color.dark_grey()
                    )
                    msg = await channel.send(embed=embed)
                    state.active_message_id = msg.id
                    state.drop_started_at = time.time()
                    state.claimed_by = None
                    state.waiting_for_claim = asyncio.Event()

                    # wait indefinitely for claim (until set by claim handler)
                    await state.waiting_for_claim.wait()
                except asyncio.CancelledError:
                    break
                except Exception:
                    await asyncio.sleep(5)

        state.task = self.bot.loop.create_task(runner())

    @commands.Cog.listener()
    async def on_guild_available(self, guild: discord.Guild):
        await self._ensure_state_task(guild)

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild):
        await self._ensure_state_task(guild)

    # ---------- admin: set channel ----------

    @commands.hybrid_command(name="setchannel", description="Set the channel used for model drops.")
    @checks.admin_or_permissions(manage_guild=True)
    @commands.guild_only()
    async def setchannel(self, ctx: commands.Context, channel: discord.TextChannel):
        await self.config.guild(ctx.guild).drop_channel_id.set(channel.id)
        await self._ensure_state_task(ctx.guild)
        await ctx.reply(f"✅ Model drops will appear in {channel.mention}.")

    # ---------- user: claim via slash/text ----------

    @commands.hybrid_command(name="model", description="Reveal the active model (if any).")
    @commands.guild_only()
    async def model_cmd(self, ctx: commands.Context):
        await self._handle_claim(ctx=ctx)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        if message.content.strip().lower() != "model":
            return

        gconf = self.config.guild(message.guild)
        channel_id = await gconf.drop_channel_id()
        if not channel_id or message.channel.id != channel_id:
            return  # only listen in configured channel

        state = self._states.get(message.guild.id)
        if not state or not state.active_message_id or state.claimed_by is not None:
            try:
                await message.add_reaction("🚫")
            except Exception:
                pass
            return

        class DummyCtx:
            def __init__(self, bot, guild, channel, author, message):
                self.bot, self.guild, self.channel = bot, guild, channel
                self.author, self.message, self.interaction = author, message, None
            async def reply(self, *a, **k): return await message.reply(*a, **k)

        await self._handle_claim(ctx=DummyCtx(self.bot, message.guild, message.channel, message.author, message))

    # ---------- claim logic (persists inventory) ----------

    async def _handle_claim(self, ctx):
        guild: discord.Guild = ctx.guild
        member: discord.Member = ctx.author
        gconf = self.config.guild(guild)
        state = self._states.get(guild.id)

        # cooldown
        mconf = self.config.member(member)
        last = await mconf.last_attempt()
        cd = await gconf.user_attempt_cooldown()
        now = time.time()
        if now - last < cd:
            try:
                if getattr(ctx, "message", None):
                    await ctx.message.add_reaction("⏳")
                else:
                    await ctx.reply("⏳ Slow down a bit.", ephemeral=True)
            except Exception:
                pass
            return
        await mconf.last_attempt.set(now)

        drop_channel_id = await gconf.drop_channel_id()
        if not drop_channel_id:
            await ctx.reply("⚠️ No drop channel configured yet. Ask an admin to run `/setchannel`.", ephemeral=True if getattr(ctx, "interaction", None) else False)
            return

        if not state or not state.active_message_id or state.claimed_by is not None:
            if getattr(ctx, "message", None):
                try: await ctx.message.add_reaction("🚫")
                except Exception: pass
            else:
                await ctx.reply("🚫 No active model right now.", ephemeral=True)
            return

        if hasattr(ctx, "channel") and ctx.channel.id != drop_channel_id:
            if getattr(ctx, "message", None):
                try: await ctx.message.add_reaction("🚫")
                except Exception: pass
            else:
                await ctx.reply("🚫 Try this in the configured drop channel.", ephemeral=True)
            return

        # race-lock
        async with state.claim_lock:
            if state.claimed_by is not None:
                if getattr(ctx, "message", None):
                    try: await ctx.message.add_reaction("❌")
                    except Exception: pass
                else:
                    await ctx.reply("❌ Someone else already revealed it.", ephemeral=True)
                return

            rarity, color, emoji = pick_rarity()
            item_name = generate_item_for(rarity)
            state.claimed_by = member.id
            if state.waiting_for_claim:
                state.waiting_for_claim.set()

        # update stats + inventory
        await self.config.member(member).claims.set((await self.config.member(member).claims()) + 1)
        key = f"rarity_{rarity.lower()}"
        current = await self.config.member(member).get_raw(key, default=0)
        await self.config.member(member).set_raw(key, value=current + 1)

        item_entry = {
            "name": item_name,
            "rarity": rarity,
            "emoji": emoji,
            "ts": int(time.time())
        }
        items = await self.config.member(member).items()
        items.append(item_entry)
        # OPTIONAL: cap inventory length to prevent unbounded growth (comment out to keep all)
        if len(items) > 5000:
            items = items[-5000:]
        await self.config.member(member).items.set(items)

        # reveal
        try:
            embed = discord.Embed(
                title=f"{emoji} {rarity} Model Revealed!",
                description=f"**{member.mention}** unveiled **{item_name}**",
                color=color
            )
            embed.set_footer(text="gg 🧊")
            await ctx.reply(embed=embed)
        except Exception:
            pass

        # clear active drop so loop can schedule next
        state.active_message_id = None
        state.drop_started_at = None

    # ---------- inventory viewer with pagination ----------

    @commands.hybrid_command(name="modelbag", description="Show your (or another user's) model earnings.")
    @commands.guild_only()
    async def modelbag(self, ctx: commands.Context, member: Optional[discord.Member] = None):
        member = member or ctx.author
        items: List[dict] = await self.config.member(member).items()
        if not items:
            return await ctx.reply(f"{member.mention} has no models yet.")

        # newest first
        items = sorted(items, key=lambda x: x.get("ts", 0), reverse=True)

        # build pages (10 per)
        per = 10
        pages: List[discord.Embed] = []
        total = len(items)
        for i in range(0, total, per):
            chunk = items[i:i+per]
            desc_lines = []
            for idx, it in enumerate(chunk, start=i+1):
                ts = it.get("ts", 0)
                dt = discord.utils.format_dt(discord.utils.snowflake_time(ts) if isinstance(ts, int) else discord.utils.utcnow(), style='R') if ts else ""
                rarity = it.get("rarity", "?")
                emoji = it.get("emoji", "•")
                name  = it.get("name", "Unknown")
                # absolute time formatting without Snowflake util; fallback:
                when = f"<t:{ts}:R>" if isinstance(ts, int) and ts > 0 else ""
                desc_lines.append(f"**{idx}.** {emoji} **{name}** — *{rarity}* {when}")

            e = discord.Embed(
                title=f"{member.display_name}'s Models",
                description="\n".join(desc_lines),
                color=discord.Color.blurple()
            )
            e.set_footer(text=f"Items {i+1}-{min(i+per, total)} / {total}")
            pages.append(e)

        view = BagPaginator(owner_id=ctx.author.id, pages=pages)
        await ctx.reply(embed=pages[0], view=view)

    # ---------- optional: quick sanity check ----------

    @commands.command(name="modeldebug")
    @checks.is_owner()
    async def model_debug(self, ctx: commands.Context, action: str = "ping"):
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
                title="A Model Appears (debug)",
                description="⬛ **Type `model` to reveal it!**",
                color=discord.Color.dark_grey()
            )
            msg = await channel.send(embed=embed)
            state.active_message_id = msg.id
            state.drop_started_at = time.time()
            state.claimed_by = None
            state.waiting_for_claim = asyncio.Event()
            await ctx.send("debug drop sent ✅")

    # keep the background loop alive on availability/join handled above
