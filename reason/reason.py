import discord
import json
import random
import time
from pathlib import Path
from typing import TYPE_CHECKING
from discord.ext import tasks
from redbot.core import commands, Config, app_commands, checks

if TYPE_CHECKING:
    from redbot.core.bot import Red

# ---------------------------------------------------------------------------
# Achievements definitions
# ---------------------------------------------------------------------------

ACHIEVEMENTS = [
    {"id": "first_claim", "name": "🎉 First Claim", "desc": "Claim your first reason", "check": lambda s: s.get("total_claims", 0) >= 1},
    {"id": "collector_10", "name": "🧺 Collector", "desc": "Claim 10 reasons", "check": lambda s: s.get("total_claims", 0) >= 10},
    {"id": "collector_50", "name": "📦 Hoarder", "desc": "Claim 50 reasons", "check": lambda s: s.get("total_claims", 0) >= 50},
    {"id": "streak_5", "name": "🔥 On Fire", "desc": "Reach a 5 W streak", "check": lambda s: s.get("streak", 0) >= 5},
    {"id": "streak_10", "name": "💥 Unstoppable", "desc": "Reach a 10 W streak", "check": lambda s: s.get("streak", 0) >= 10},
    {"id": "points_100", "name": "💯 Century", "desc": "Earn 100 points", "check": lambda s: s.get("points", 0) >= 100},
    {"id": "points_500", "name": "🏆 High Roller", "desc": "Earn 500 points", "check": lambda s: s.get("points", 0) >= 500},
    {"id": "thief", "name": "😈 Thief", "desc": "Successfully steal once", "check": lambda s: s.get("total_steals_success", 0) >= 1},
    {"id": "master_thief", "name": "🦹 Master Thief", "desc": "Successfully steal 5 times", "check": lambda s: s.get("total_steals_success", 0) >= 5},
    {"id": "critic", "name": "👍 Critic", "desc": "Rate 10 reasons as W", "check": lambda s: s.get("total_ws", 0) >= 10},
]

def get_unlocked_achievements(stats: dict) -> list[dict]:
    return [a for a in ACHIEVEMENTS if a["check"](stats)]

# ---------------------------------------------------------------------------
# Persistent View for bot restarts
# ---------------------------------------------------------------------------

class PersistentReasonView(discord.ui.View):
    """
    Minimal persistent view registered on cog load.
    Handles button clicks after bot restart by looking up state from config.
    """

    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    async def _get_state(self, interaction: discord.Interaction) -> dict | None:
        if not interaction.message or not interaction.guild:
            return None
        msg_id = str(interaction.message.id)
        states = await self.cog.config.guild(interaction.guild).drop_states()
        return states.get(msg_id)

    async def _save_state(self, interaction: discord.Interaction, state: dict) -> None:
        if not interaction.message or not interaction.guild:
            return
        msg_id = str(interaction.message.id)
        async with self.cog.config.guild(interaction.guild).drop_states() as states:
            states[msg_id] = state
            # Cleanup: keep only last 100 entries
            if len(states) > 100:
                sorted_keys = sorted(states.keys(), key=int)
                for k in sorted_keys[:-100]:
                    del states[k]

    @discord.ui.button(label="Reroll 🎲", style=discord.ButtonStyle.primary, custom_id="reason_reroll", row=0)
    async def reroll(self, interaction: discord.Interaction, button: discord.ui.Button):
        state = await self._get_state(interaction)
        if not state:
            return await interaction.response.send_message("This drop has expired.", ephemeral=True)
        if interaction.user.id != state.get("target_user_id"):
            return await interaction.response.send_message("Not your loot drop 🙂", ephemeral=True)
        if state.get("rerolls_left", 0) <= 0:
            return await interaction.response.send_message("No rerolls left.", ephemeral=True)

        state["rerolls_left"] -= 1
        state["reason_text"] = random.choice(self.cog.reasons)
        await self._save_state(interaction, state)

        content = self.cog._build_reason_message_content(
            member=interaction.user, reason_text=state["reason_text"]
        )
        await interaction.response.edit_message(content=content)

    @discord.ui.button(label="Claim 🧾", style=discord.ButtonStyle.success, custom_id="reason_claim", row=0)
    async def claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        state = await self._get_state(interaction)
        if not state:
            return await interaction.response.send_message("This drop has expired.", ephemeral=True)
        if interaction.user.id != state.get("target_user_id"):
            return await interaction.response.send_message("Not your loot drop 🙂", ephemeral=True)
        if state.get("claimed"):
            return await interaction.response.send_message("Already claimed.", ephemeral=True)

        state["claimed"] = True
        await self._save_state(interaction, state)

        mconf = self.cog.config.member(interaction.user)
        async with mconf.wallet() as wallet:
            wallet.append({"reason": state["reason_text"], "ts": int(time.time())})
            if len(wallet) > 500:
                wallet[:] = wallet[-500:]

        pts = await mconf.points()
        bonus = 5
        bonus_msg = ""
        now = time.time()
        last_daily = await mconf.last_daily_claim()
        if now - last_daily >= 86400:
            bonus += 10
            bonus_msg = " (🎁 +10 daily bonus!)"
            await mconf.last_daily_claim.set(now)

        total_claims = await mconf.total_claims()
        await mconf.points.set(pts + bonus)
        await mconf.total_claims.set(total_claims + 1)
        await interaction.response.send_message(f"🧾 Claimed! +{bonus} pts{bonus_msg}", ephemeral=True)

    @discord.ui.button(label="W 👍", style=discord.ButtonStyle.success, custom_id="reason_w", row=1)
    async def rate_w(self, interaction: discord.Interaction, button: discord.ui.Button):
        state = await self._get_state(interaction)
        if not state:
            return await interaction.response.send_message("This drop has expired.", ephemeral=True)
        if interaction.user.id != state.get("target_user_id"):
            return await interaction.response.send_message("Not your loot drop 🙂", ephemeral=True)
        if state.get("rated"):
            return await interaction.response.send_message("Already rated.", ephemeral=True)

        state["rated"] = True
        await self._save_state(interaction, state)

        mconf = self.cog.config.member(interaction.user)
        pts = await mconf.points()
        streak = await mconf.streak()
        total_ws = await mconf.total_ws()
        await mconf.points.set(pts + 10)
        await mconf.streak.set(streak + 1)
        await mconf.total_ws.set(total_ws + 1)

        async with self.cog.config.guild(interaction.guild).best_reasons() as best:
            found = False
            for entry in best:
                if entry["reason"] == state["reason_text"]:
                    entry["votes"] += 1
                    found = True
                    break
            if not found:
                best.append({"reason": state["reason_text"], "votes": 1})
            best.sort(key=lambda x: x["votes"], reverse=True)
            best[:] = best[:50]

        await interaction.response.send_message(f"👍 W! +10 pts | 🔥 Streak: {streak + 1}", ephemeral=True)

    @discord.ui.button(label="L 👎", style=discord.ButtonStyle.danger, custom_id="reason_l", row=1)
    async def rate_l(self, interaction: discord.Interaction, button: discord.ui.Button):
        state = await self._get_state(interaction)
        if not state:
            return await interaction.response.send_message("This drop has expired.", ephemeral=True)
        if interaction.user.id != state.get("target_user_id"):
            return await interaction.response.send_message("Not your loot drop 🙂", ephemeral=True)
        if state.get("rated"):
            return await interaction.response.send_message("Already rated.", ephemeral=True)

        state["rated"] = True
        await self._save_state(interaction, state)

        mconf = self.cog.config.member(interaction.user)
        pts = await mconf.points()
        await mconf.points.set(pts + 2)
        await mconf.streak.set(0)
        await interaction.response.send_message("👎 L. +2 pts | Streak reset.", ephemeral=True)

    @discord.ui.button(label="Steal 😈", style=discord.ButtonStyle.secondary, custom_id="reason_steal", row=1)
    async def steal(self, interaction: discord.Interaction, button: discord.ui.Button):
        state = await self._get_state(interaction)
        if not state:
            return await interaction.response.send_message("This drop has expired.", ephemeral=True)
        if not interaction.guild:
            return await interaction.response.send_message("Server only.", ephemeral=True)
        if interaction.user.id == state.get("target_user_id"):
            return await interaction.response.send_message("Can't steal your own drop.", ephemeral=True)

        now = time.time()
        gconf = self.cog.config.guild(interaction.guild)
        guild_last_steal = await gconf.guild_last_steal()
        if now - guild_last_steal < 120:
            return await interaction.response.send_message(f"Server cooldown. {int(120-(now-guild_last_steal))}s left.", ephemeral=True)

        mconf = self.cog.config.member(interaction.user)
        last_steal = await mconf.last_steal()
        if now - last_steal < 300:
            return await interaction.response.send_message(f"Your cooldown. {int(300-(now-last_steal))}s left.", ephemeral=True)

        await mconf.last_steal.set(now)
        await gconf.guild_last_steal.set(now)

        if random.random() < 0.20:
            stolen = random.randint(5, 15)
            target = interaction.guild.get_member(state["target_user_id"])
            if target:
                tpts = await self.cog.config.member(target).points()
                stolen = min(stolen, tpts)
                await self.cog.config.member(target).points.set(tpts - stolen)
            pts = await mconf.points()
            total_steals = await mconf.total_steals_success()
            await mconf.points.set(pts + stolen)
            await mconf.total_steals_success.set(total_steals + 1)
            await interaction.response.send_message(f"😈 Stole {stolen} pts!", ephemeral=True)
        else:
            await interaction.response.send_message("😅 Steal failed.", ephemeral=True)

    @discord.ui.button(label="Mute 🔕", style=discord.ButtonStyle.secondary, custom_id="reason_mute", row=2)
    async def mute_drops(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild:
            return await interaction.response.send_message("Server only.", ephemeral=True)
        async with self.cog.config.guild(interaction.guild).opt_out_list() as opt_out:
            if interaction.user.id not in opt_out:
                opt_out.append(interaction.user.id)
                await interaction.response.send_message("🔕 Muted.", ephemeral=True)
            else:
                await interaction.response.send_message("Already muted.", ephemeral=True)

# ---------------------------------------------------------------------------
# Game View with mini-game mechanics
# ---------------------------------------------------------------------------

class ReasonGameView(discord.ui.View):
    """
    Loot-drop style view with:
    - Reroll 🎲: get a new reason (max 2 per drop)
    - Claim 🧾: save to your wallet (+5 pts)
    - W 👍 / L 👎: rate it (W = +10 pts + streak, L = +2 pts, resets streak)
    - Steal 😈: small chance to steal points from target (cooldown)
    - Mute 🔕: opt out of future drops
    """

    def __init__(
        self,
        cog,
        *,
        target_user_id: int,
        reason_text: str,
        all_reasons: list[str],
    ):
        # 12-hour timeout for interactive buttons
        super().__init__(timeout=43200)
        self.cog = cog
        self.target_user_id = target_user_id
        self.reason_text = reason_text
        self.all_reasons = all_reasons
        self.rerolls_left = 2
        self.claimed = False
        self.rated = False
        self.message: discord.Message | None = None  # set after send

    async def on_timeout(self) -> None:
        """Disable Reroll, Claim, Steal after 12 hours."""
        for child in self.children:
            if isinstance(child, discord.ui.Button) and child.custom_id in (
                "reason_reroll", "reason_claim", "reason_steal"
            ):
                child.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass

    # ---- helpers ----

    def _owner_only(self, interaction: discord.Interaction) -> bool:
        return interaction.user is not None and interaction.user.id == self.target_user_id

    async def _update_message(self, interaction: discord.Interaction) -> None:
        content = self.cog._build_reason_message_content(
            member=interaction.user, reason_text=self.reason_text
        )
        await interaction.message.edit(content=content, view=self)

    # ---- buttons ----

    @discord.ui.button(label="Reroll 🎲", style=discord.ButtonStyle.primary, custom_id="reason_reroll", row=0)
    async def reroll(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._owner_only(interaction):
            return await interaction.response.send_message("Not your loot drop 🙂", ephemeral=True)
        if self.rerolls_left <= 0:
            return await interaction.response.send_message("No rerolls left on this drop.", ephemeral=True)

        self.rerolls_left -= 1
        self.reason_text = random.choice(self.all_reasons)
        if self.rerolls_left == 0:
            button.disabled = True

        await interaction.response.defer()
        await self._update_message(interaction)

    @discord.ui.button(label="Claim 🧾", style=discord.ButtonStyle.success, custom_id="reason_claim", row=0)
    async def claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._owner_only(interaction):
            return await interaction.response.send_message("Not your loot drop 🙂", ephemeral=True)
        if self.claimed:
            return await interaction.response.send_message("Already claimed this one.", ephemeral=True)

        self.claimed = True
        button.disabled = True

        member = interaction.user
        mconf = self.cog.config.member(member)
        async with mconf.wallet() as wallet:
            wallet.append({"reason": self.reason_text, "ts": int(time.time())})
            # Cap wallet size
            if len(wallet) > 500:
                wallet[:] = wallet[-500:]

        pts = await mconf.points()
        bonus = 5
        bonus_msg = ""

        # Daily bonus: +10 extra if first claim in 24hrs
        now = time.time()
        last_daily = await mconf.last_daily_claim()
        if now - last_daily >= 86400:  # 24 hours
            bonus += 10
            bonus_msg = " (🎁 +10 daily bonus!)"
            await mconf.last_daily_claim.set(now)

        total_claims = await mconf.total_claims()
        await mconf.points.set(pts + bonus)
        await mconf.total_claims.set(total_claims + 1)

        await interaction.response.send_message(
            f"🧾 Claimed! +{bonus} pts (total: {pts + bonus}){bonus_msg}", ephemeral=True
        )
        await self._update_message(interaction)

    @discord.ui.button(label="W 👍", style=discord.ButtonStyle.success, custom_id="reason_w", row=1)
    async def rate_w(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._owner_only(interaction):
            return await interaction.response.send_message("Not your loot drop 🙂", ephemeral=True)
        if self.rated:
            return await interaction.response.send_message("Already rated.", ephemeral=True)

        self.rated = True
        button.disabled = True
        # Also disable L button
        for child in self.children:
            if isinstance(child, discord.ui.Button) and child.custom_id == "reason_l":
                child.disabled = True

        member = interaction.user
        mconf = self.cog.config.member(member)
        pts = await mconf.points()
        streak = await mconf.streak()
        total_ws = await mconf.total_ws()
        await mconf.points.set(pts + 10)
        await mconf.streak.set(streak + 1)
        await mconf.total_ws.set(total_ws + 1)

        # Update server best reasons
        async with self.cog.config.guild(interaction.guild).best_reasons() as best:
            found = False
            for entry in best:
                if entry["reason"] == self.reason_text:
                    entry["votes"] += 1
                    found = True
                    break
            if not found:
                best.append({"reason": self.reason_text, "votes": 1})
            # Keep top 50 by votes
            best.sort(key=lambda x: x["votes"], reverse=True)
            best[:] = best[:50]

        await interaction.response.send_message(
            f"👍 W! +10 pts (total: {pts + 10}) | 🔥 Streak: {streak + 1}", ephemeral=True
        )
        await self._update_message(interaction)

    @discord.ui.button(label="L 👎", style=discord.ButtonStyle.danger, custom_id="reason_l", row=1)
    async def rate_l(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._owner_only(interaction):
            return await interaction.response.send_message("Not your loot drop 🙂", ephemeral=True)
        if self.rated:
            return await interaction.response.send_message("Already rated.", ephemeral=True)

        self.rated = True
        button.disabled = True
        for child in self.children:
            if isinstance(child, discord.ui.Button) and child.custom_id == "reason_w":
                child.disabled = True

        member = interaction.user
        pts = await self.cog.config.member(member).points()
        await self.cog.config.member(member).points.set(pts + 2)
        await self.cog.config.member(member).streak.set(0)

        await interaction.response.send_message(
            f"👎 L. +2 pts (total: {pts + 2}) | Streak reset.", ephemeral=True
        )
        await self._update_message(interaction)

    @discord.ui.button(label="Steal 😈", style=discord.ButtonStyle.secondary, custom_id="reason_steal", row=1)
    async def steal(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user is None or interaction.guild is None:
            return await interaction.response.send_message("Can't do that here.", ephemeral=True)

        # Can't steal your own drop
        if interaction.user.id == self.target_user_id:
            return await interaction.response.send_message("Can't steal your own drop.", ephemeral=True)

        now = time.time()

        # Anti-spam: guild-wide cooldown (2 minutes)
        gconf = self.cog.config.guild(interaction.guild)
        guild_last_steal = await gconf.guild_last_steal()
        if now - guild_last_steal < 120:
            remaining = int(120 - (now - guild_last_steal))
            return await interaction.response.send_message(
                f"Server steal cooldown. Try again in {remaining}s.", ephemeral=True
            )

        # Per-user cooldown (5 minutes)
        mconf = self.cog.config.member(interaction.user)
        last_steal = await mconf.last_steal()
        if now - last_steal < 300:
            remaining = int(300 - (now - last_steal))
            return await interaction.response.send_message(
                f"Your steal cooldown. Try again in {remaining}s.", ephemeral=True
            )

        await mconf.last_steal.set(now)
        await gconf.guild_last_steal.set(now)

        # 20% success chance
        if random.random() < 0.20:
            # Steal 5-15 points
            stolen = random.randint(5, 15)
            target_member = interaction.guild.get_member(self.target_user_id)
            if target_member:
                target_pts = await self.cog.config.member(target_member).points()
                stolen = min(stolen, target_pts)  # Can't go negative
                await self.cog.config.member(target_member).points.set(target_pts - stolen)

            thief_conf = self.cog.config.member(interaction.user)
            thief_pts = await thief_conf.points()
            total_steals = await thief_conf.total_steals_success()
            await thief_conf.points.set(thief_pts + stolen)
            await thief_conf.total_steals_success.set(total_steals + 1)

            await interaction.response.send_message(
                f"😈 Heist success! Stole {stolen} pts (total: {thief_pts + stolen})", ephemeral=True
            )
        else:
            await interaction.response.send_message("😅 Steal failed. Better luck next time.", ephemeral=True)

    @discord.ui.button(label="Mute 🔕", style=discord.ButtonStyle.secondary, custom_id="reason_mute", row=2)
    async def mute_drops(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.guild is None:
            return await interaction.response.send_message("This button only works inside a server.", ephemeral=True)

        async with self.cog.config.guild(interaction.guild).opt_out_list() as opt_out:
            if interaction.user.id not in opt_out:
                opt_out.append(interaction.user.id)
                await interaction.response.send_message(
                    "🔕 Muted. You won't be picked for random drops anymore.", ephemeral=True
                )
            else:
                await interaction.response.send_message("Already opted out.", ephemeral=True)

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
            "best_reasons": [],  # [{"reason": str, "votes": int}, ...]
            "channel_set_at": 0.0,  # timestamp when channel was configured
            "first_drop_done": False,  # True after 6hr initial drop
            "last_drop_at": 0.0,  # timestamp of last drop for 48hr interval
            "guild_last_steal": 0.0,  # anti-spam: guild-wide steal cooldown
            "drop_states": {},  # persistent view state: {msg_id: {...}}
        }
        self.config.register_guild(**default_guild)
        self.config.register_member(
            seen_intro=False,
            wallet=[],       # [{"reason": str, "ts": int}, ...]
            points=0,
            streak=0,
            last_steal=0.0,
            last_daily_claim=0.0,  # daily bonus tracking
            total_claims=0,
            total_steals_success=0,
            total_ws=0,
        )
        
        reasons_path = Path(__file__).parent / "reasons.json"
        try:
            with open(reasons_path, "r", encoding="utf-8") as f:
                self.reasons = json.load(f)
        except Exception as e:
            self.reasons = ["Error loading reasons."]
            print(f"Error loading reasons.json: {e}")

        self.reason_loop.start()
        self.reason_test_loop.start()

    async def cog_load(self) -> None:
        """Register persistent view so buttons work after bot restart."""
        self.bot.add_view(PersistentReasonView(self))

    async def _intro_field_text_for(self, member: discord.Member) -> str:
        seen_intro = await self.config.member(member).seen_intro()
        if not seen_intro:
            return (
                "A tiny party-game that drops random ‘reasons’ for laughs.\n"
                "Fictional lines only — not advice, not a rulebook, not a lifestyle."
            )
        return "For when you need a NO with style — in-game."

    async def _build_reason_embed(self, *, member: discord.Member, reason_text: str, title: str = "Reason") -> discord.Embed:
        # Keep the embed minimal; Discord doesn't let us increase embed font size,
        # so the "big" text lives in the message content.
        embed = discord.Embed(color=discord.Color.random())
        embed.add_field(name="About", value=await self._intro_field_text_for(member), inline=False)
        embed.set_footer(
            text="Your choice is private. Use /reason help to learn what this cog does and how to configure drops."
        )
        return embed

    def _build_reason_message_content(self, *, member: discord.abc.User, reason_text: str) -> str:
        # Regular message content renders larger than embed descriptions.
        # Keep within Discord's 2000 character limit.
        prefix = f"Hey {member.mention}, here is a reason for you:\n**"
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
        embed = await self._build_reason_embed(member=member, reason_text=reason_text, title=title)
        view = ReasonGameView(
            self,
            target_user_id=member.id,
            reason_text=reason_text,
            all_reasons=self.reasons,
        )
        message_content = self._build_reason_message_content(member=member, reason_text=reason_text)

        try:
            msg = await channel.send(content=message_content, embed=embed, view=view)  # type: ignore[attr-defined]
            view.message = msg  # for on_timeout editing
            await self.config.member(member).seen_intro.set(True)

            # Save state for persistent view (survives bot restart)
            async with self.config.guild(guild).drop_states() as states:
                states[str(msg.id)] = {
                    "target_user_id": member.id,
                    "reason_text": reason_text,
                    "rerolls_left": 2,
                    "claimed": False,
                    "rated": False,
                }
                # Cleanup: keep only last 100 entries
                if len(states) > 100:
                    sorted_keys = sorted(states.keys(), key=int)
                    for k in sorted_keys[:-100]:
                        del states[k]
        except discord.Forbidden:
            pass
        except Exception as e:
            print(f"Error sending reason in guild {guild.id}: {e}")

    def cog_unload(self):
        self.reason_loop.cancel()
        self.reason_test_loop.cancel()

    @tasks.loop(minutes=30)
    async def reason_loop(self):
        """Check every 30 mins; first drop 6hrs after channel set, then every 48hrs."""
        now = time.time()
        all_guilds = await self.config.all_guilds()
        for guild in self.bot.guilds:
            gdata = all_guilds.get(guild.id, {})
            # If test mode is enabled, the 1-minute loop handles this guild.
            if gdata.get("test_enabled"):
                continue
            channel_id = gdata.get("channel_id")
            if not channel_id:
                continue

            gconf = self.config.guild(guild)
            channel_set_at = gdata.get("channel_set_at", 0)
            first_drop_done = gdata.get("first_drop_done", False)

            if not first_drop_done:
                # First drop: 6 hours after channel was set
                if now - channel_set_at < 6 * 3600:
                    continue  # not yet time
                await self._send_reason_drop(guild=guild, channel_id=channel_id, title="Reason")
                await gconf.first_drop_done.set(True)
                await gconf.last_drop_at.set(now)
            else:
                # Subsequent drops: every 48 hours
                last_drop = gdata.get("last_drop_at", 0)
                if now - last_drop < 48 * 3600:
                    continue
                await self._send_reason_drop(guild=guild, channel_id=channel_id, title="Reason")
                await gconf.last_drop_at.set(now)

    @tasks.loop(minutes=1)
    async def reason_test_loop(self):
        all_guilds = await self.config.all_guilds()
        for guild in self.bot.guilds:
            gdata = all_guilds.get(guild.id, {})
            if not gdata.get("test_enabled"):
                continue
            channel_id = gdata.get("test_channel_id")
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
        # make the instant drop admin-only, but keep subcommands public.
        if ctx.invoked_subcommand is None:
            allowed = await checks.admin_or_permissions(manage_guild=True).predicate(ctx)
            if not allowed:
                return await ctx.send(
                    "Admins only: use an admin to run this instant drop.",
                    ephemeral=getattr(ctx, "interaction", None) is not None,
                )
            await self.send_reason(ctx)

    async def send_reason(self, ctx):
        reason_text = random.choice(self.reasons)
        embed = await self._build_reason_embed(member=ctx.author, reason_text=reason_text, title="Reason")
        view = ReasonGameView(
            self,
            target_user_id=ctx.author.id,
            reason_text=reason_text,
            all_reasons=self.reasons,
        )
        content = self._build_reason_message_content(member=ctx.author, reason_text=reason_text)
        await ctx.send(content=content, embed=embed, view=view)
        await self.config.member(ctx.author).seen_intro.set(True)

    @reason.command(name="channel")
    @app_commands.describe(channel="The channel for random drops")
    @checks.admin_or_permissions(manage_guild=True)
    @commands.guild_only()
    async def set_channel(self, ctx, channel: discord.TextChannel):
        """Set the channel where the embeds will be dropped."""
        now = time.time()
        gconf = self.config.guild(ctx.guild)
        await gconf.channel_id.set(channel.id)
        await gconf.channel_set_at.set(now)
        await gconf.first_drop_done.set(False)  # reset so 6hr timer starts fresh
        await ctx.send(
            f"Reason drops will now happen in {channel.mention}.\n"
            f"First drop in ~6 hours, then every 48 hours."
        )

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
            "A tiny party-game that drops random 'reasons' for laughs.\n"
            "Fictional lines only — not advice, not a rulebook, not a lifestyle.\n\n"
            "**Buttons:**\n"
            "🎲 **Reroll** — get a new reason (max 2 per drop)\n"
            "🧾 **Claim** — save to your wallet (+5 pts)\n"
            "👍 **W** — rate it a win (+10 pts, +streak, adds to best-of)\n"
            "👎 **L** — rate it a loss (+2 pts, resets streak)\n"
            "😈 **Steal** — 20% chance to steal pts from target (cooldown)\n"
            "🔕 **Mute** — opt out of future drops\n\n"
            "**Commands:**\n"
            "`/reason` — instant drop for yourself\n"
            "`/reason wallet` — view your saved reasons\n"
            "`/reason stats` — view your points & streak\n"
            "`/reason best` — server's top-rated reasons\n"
            "`/reason channel` — (admin) set drop channel\n"
            "`/reason channelclear` — (admin) disable drops"
        )
        embed = discord.Embed(title="Reason Help", description=msg, color=discord.Color.blue())
        embed.set_footer(text="For when you need a NO with style — in-game.")
        await ctx.send(embed=embed)

    @reason.command(name="wallet")
    @commands.guild_only()
    async def reason_wallet(self, ctx, member: discord.Member | None = None):
        """View your (or another user's) saved reasons."""
        member = member or ctx.author
        wallet = await self.config.member(member).wallet()
        if not wallet:
            return await ctx.send(f"{member.display_name} has no saved reasons yet.")

        # Newest first, show up to 10
        wallet = sorted(wallet, key=lambda x: x.get("ts", 0), reverse=True)[:10]
        lines = []
        for i, entry in enumerate(wallet, 1):
            reason = entry.get("reason", "?")
            if len(reason) > 80:
                reason = reason[:77] + "…"
            lines.append(f"**{i}.** {reason}")

        embed = discord.Embed(
            title=f"🧾 {member.display_name}'s Wallet",
            description="\n".join(lines),
            color=discord.Color.gold(),
        )
        total = len(await self.config.member(member).wallet())
        embed.set_footer(text=f"Showing latest 10 of {total} saved reasons")
        await ctx.send(embed=embed)

    @reason.command(name="stats")
    @commands.guild_only()
    async def reason_stats(self, ctx, member: discord.Member | None = None):
        """View your (or another user's) points, streak, and achievements."""
        member = member or ctx.author
        mconf = self.config.member(member)

        # Batch read member stats
        points = await mconf.points()
        streak = await mconf.streak()
        wallet = await mconf.wallet()
        total_claims = await mconf.total_claims()
        total_steals_success = await mconf.total_steals_success()
        total_ws = await mconf.total_ws()

        stats_dict = {
            "points": points,
            "streak": streak,
            "total_claims": total_claims,
            "total_steals_success": total_steals_success,
            "total_ws": total_ws,
        }

        embed = discord.Embed(
            title=f"📊 {member.display_name}'s Stats",
            color=discord.Color.blurple(),
        )
        embed.add_field(name="Points", value=str(points), inline=True)
        embed.add_field(name="🔥 Streak", value=str(streak), inline=True)
        embed.add_field(name="🧾 Wallet", value=str(len(wallet)), inline=True)
        embed.add_field(name="Claims", value=str(total_claims), inline=True)
        embed.add_field(name="Steals", value=str(total_steals_success), inline=True)
        embed.add_field(name="W Ratings", value=str(total_ws), inline=True)

        # Achievements
        unlocked = get_unlocked_achievements(stats_dict)
        if unlocked:
            ach_text = "\n".join(f"{a['name']} — *{a['desc']}*" for a in unlocked)
        else:
            ach_text = "None yet. Keep playing!"
        embed.add_field(name="🏅 Achievements", value=ach_text, inline=False)

        await ctx.send(embed=embed)

    @reason.command(name="best")
    @commands.guild_only()
    async def reason_best(self, ctx):
        """View this server's top-rated reasons."""
        best = await self.config.guild(ctx.guild).best_reasons()
        if not best:
            return await ctx.send("No rated reasons yet. Start rating with 👍!")

        # Top 10
        best = sorted(best, key=lambda x: x.get("votes", 0), reverse=True)[:10]
        lines = []
        for i, entry in enumerate(best, 1):
            reason = entry.get("reason", "?")
            votes = entry.get("votes", 0)
            if len(reason) > 70:
                reason = reason[:67] + "…"
            lines.append(f"**{i}.** ({votes} 👍) {reason}")

        embed = discord.Embed(
            title="🏆 Server's Best Reasons",
            description="\n".join(lines),
            color=discord.Color.gold(),
        )
        await ctx.send(embed=embed)
