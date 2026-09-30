"""O'yin dvigateli: ro'yxat (lobby), tun/kun fazalari, rollar, g'alaba shartlari."""
from __future__ import annotations

import asyncio
import logging
import random
import time
from collections import Counter
from dataclasses import dataclass, field
from html import escape

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import InlineKeyboardButton as Btn, InlineKeyboardMarkup as Kb

import config
import database as db

log = logging.getLogger("mafia.game")

# ---------- Sozlamalar ----------
MIN_PLAYERS = 4
MAX_PLAYERS = 30
LOBBY_TIME = 120      # ro'yxatga olish (soniya)
NIGHT_TIME = 45
DAY_TIME = 45         # kunduzgi muhokama
VOTE_TIME = 45
CONFIRM_TIME = 20     # "Rostdan ham osmoqchimisiz?"
AFSUN_TIME = 20
WIN_REWARD = 30       # g'olibga dollar (premium guruhda x2). Olmos berilmaydi!
MARRIAGE_BONUS = 10   # juftlik ikkalasi ham yutsa qo'shimcha

# emoji, nom, tavsif
ROLE_INFO = {
    "civilian": ("👨🏼", "Tinch aholi", "Kunduzi mafiyani topib, ovoz berish orqali osing."),
    "kezuvchi": ("💃🏼", "Kezuvchi", "Tunda birovnikiga borib, uning harakatini to'xtatasiz. Komissarni uxlatib qo'ymang!"),
    "serjant": ("👮🏻‍♂️", "Serjant", "Komissarning yordamchisi. Komissar o'lsa, uning o'rnini egallaysiz."),
    "komissar": ("🕵🏼", "Komissar Katani", "Tunda bir kishini tekshirasiz yoki otasiz. 1-tunda otish mumkin emas."),
    "doktor": ("👨🏼‍⚕️", "Doktor", "Tunda bir o'yinchini davolaysiz. O'zingizni faqat 1 marta davolay olasiz."),
    "daydi": ("🧙🏼‍♂️", "Daydi", "Tunda birovnikiga borib, u yerga kimlar kelganini ko'rasiz."),
    "afsungar": ("🧟‍♂️", "Afsungar", "Tunda o'ldirilsangiz qotilingizni olib ketasiz. Ovoz berishda osilsangiz, xohlagan odamni olib ketasiz."),
    "don": ("🤵🏼", "Don", "Mafiya sardori. Tunda kimni o'ldirishni hal qilasiz."),
    "mafiya": ("🤵🏽", "Mafiya", "Donning yordamchisi. Qotillikda qatnashasiz."),
    "advokat": ("👨🏼‍💼", "Advokat", "Tunda kimnidir himoya qilasiz. Mafiyani tanlasangiz, Komissar uni tinch aholi deb ko'radi."),
    "qotil": ("🔪", "Qotil", "Mustaqil. Har tunda bittani o'ldirasiz. Faqat oxirigacha tirik qolsangiz yutasiz."),
    "bori": ("🐺", "Bo'ri", "Mustaqil. Mafiya o'ldirsa Mafiyaga, Komissar otsa Serjantga aylanasiz. Qotil o'ldirsa o'lasiz."),
}
# Keyingi o'yin uchun rol sotib olish narxi (olmos)
ROLE_PRICES = {
    "serjant": 2, "daydi": 2, "mafiya": 2, "doktor": 3, "kezuvchi": 3, "advokat": 3,
    "afsungar": 4, "bori": 4, "komissar": 5, "don": 5, "qotil": 5,
}
MAFIA_SIDE = {"don", "mafiya", "advokat"}
UNIQUE_ROLES = set(ROLE_INFO) - {"civilian", "mafiya"}

GROUP_ROLES = {
    "kill": {"don", "mafiya"}, "lawyer": {"advokat"}, "heal": {"doktor"},
    "block": {"kezuvchi"}, "watch": {"daydi"}, "kom": {"komissar"},
    "qkill": {"qotil"}, "gun": None,
}
ACT_GROUP = {"kill": "kill", "lawyer": "lawyer", "heal": "heal", "block": "block",
             "watch": "watch", "check": "kom", "shoot": "kom", "qkill": "qkill", "gun": "gun"}
ACT_LABEL = {"kill": "🔪 Nishon", "lawyer": "⚖️ Himoya", "heal": "💉 Davolash",
             "block": "💃🏼 Ziyorat", "watch": "👁 Kuzatish", "check": "🔍 Tekshirish",
             "shoot": "🔫 Otish", "qkill": "🔪 Nishon", "gun": "🔫 Miltiq"}
# Tunda guruhga chiqadigan "jarayon" xabarlari (kimga ekani aytilmaydi)
ACT_NEWS = {
    "check": "🕵🏼 Komissar katani shubhali shaxsni tekshirishga ketdi...",
    "shoot": "🔫 Komissar katani pistoletini o'qladi...",
    "heal": "👨🏼‍⚕️ Doktor kimnidir davolashga shoshildi...",
    "block": "💃🏼 Kezuvchi tunda kimnidir ziyorat qilishga ketdi...",
    "watch": "🧙🏼‍♂️ Daydi shisha butilka bilan ko'chaga chiqdi...",
    "lawyer": "👨🏼‍💼 Advokat mijozini himoya qilishga ketdi...",
    "qkill": "🔪 Qotil tunda ovga chiqdi...",
    "gun": "🔫 Kimdir miltiqni o'qladi...",
}

GAMES: dict[int, "Game"] = {}


def make_roles(n: int) -> list[str]:
    mafia_n = max(1, n // 4)
    roles = ["don"] + ["mafiya"] * (mafia_n - 1) + ["komissar"]
    for min_n, role in ((5, "doktor"), (6, "kezuvchi"), (7, "serjant"), (8, "advokat"),
                        (9, "daydi"), (10, "qotil"), (11, "afsungar"), (12, "bori")):
        if n >= min_n:
            roles.append(role)
    roles += ["civilian"] * (n - len(roles))
    return roles[:n]


def role_label(role: str) -> str:
    e, n, _ = ROLE_INFO[role]
    return f"{e} {n}"


def side_of(role: str) -> str:
    if role in MAFIA_SIDE:
        return "mafia"
    return "killer" if role == "qotil" else "civil"


@dataclass
class Player:
    uid: int
    name: str
    role: str = "civilian"
    alive: bool = True
    items: dict = field(default_factory=dict)
    self_healed: bool = False

    @property
    def mention(self) -> str:
        return f'<a href="tg://user?id={self.uid}">{escape(self.name)}</a>'


class Game:
    def __init__(self, bot: Bot, chat_id: int, creator_id: int, bot_username: str):
        self.bot = bot
        self.chat_id = chat_id
        self.creator_id = creator_id
        self.bot_username = bot_username
        self.players: dict[int, Player] = {}
        self.status = "lobby"          # lobby / running
        self.phase = ""                # night / day / voting / confirm / resolving / finished
        self.day = 0
        self.game_id = 0
        self.premium = False
        self.started_at = 0.0
        self.task: asyncio.Task | None = None
        # lobby
        self.lobby_msg_id: int | None = None
        self.deadline = 0.0
        self.warned = False
        self.force_start = False
        # tun
        self.actions: dict[tuple[int, str], tuple[str, int]] = {}
        self.required: set[tuple[int, str]] = set()
        self.night_event = asyncio.Event()
        self._said: set[str] = set()
        # ovoz berish
        self.votes: dict[int, int] = {}
        self.vote_event = asyncio.Event()
        self.vote_msg_id: int | None = None
        # tasdiqlash
        self.confirm_target = 0
        self.confirm_votes: dict[int, str] = {}
        self.confirm_event = asyncio.Event()
        self.confirm_msg_id: int | None = None
        # afsungar
        self.afsun_uid = 0
        self.afsun_target: int | None = None
        self.afsun_event = asyncio.Event()

    # ---------- Yordamchilar ----------
    async def send(self, text: str, markup: Kb | None = None):
        try:
            return await self.bot.send_message(self.chat_id, text, reply_markup=markup)
        except TelegramAPIError as e:
            log.warning("guruhga yuborib bo'lmadi: %s", e)
            return None

    async def send_media(self, text: str, gif: str, markup: Kb | None = None):
        if gif:
            try:
                return await self.bot.send_animation(self.chat_id, gif, caption=text,
                                                     reply_markup=markup)
            except TelegramAPIError as e:
                log.warning("GIF yuborilmadi: %s", e)
        return await self.send(text, markup)

    async def dm(self, uid: int, text: str, markup: Kb | None = None) -> bool:
        try:
            await self.bot.send_message(uid, text, reply_markup=markup)
            return True
        except TelegramAPIError:
            return False

    def alive_players(self) -> list[Player]:
        return [p for p in self.players.values() if p.alive]

    def alive_text(self) -> str:
        alive = self.alive_players()
        lines = "\n".join(f"{i}. {p.mention}" for i, p in enumerate(alive, 1))
        comp = Counter(p.role for p in alive)
        parts = [f"{ROLE_INFO[r][1]} - {comp[r]}" if comp[r] > 1 else ROLE_INFO[r][1]
                 for r in ROLE_INFO if r in comp]
        return (f"<b>Tirik o'yinchilar:</b>\n{lines}\n\n"
                f"Ulardan: {', '.join(parts)}\n<b>Jami:</b> {len(alive)}")

    def status_text(self) -> str:
        return self.lobby_text() if self.status == "lobby" else self.alive_text()

    # ---------- Lobby ----------
    def lobby_text(self) -> str:
        names = "\n".join(f"{i}. {p.mention}" for i, p in enumerate(self.players.values(), 1))
        return (f"📝 <b>Ro'yxatdan o'tish davom etmoqda...</b>\n\n"
                f"🐺 <b>MAFIA</b> o'yini\n"
                f"👥 O'yinchilar ({len(self.players)}/{MAX_PLAYERS}):\n{names or '—'}\n\n"
                f"Kamida {MIN_PLAYERS} o'yinchi kerak. Qo'shilish uchun tugmani bosing 👇")

    def lobby_kb(self) -> Kb:
        url = f"https://t.me/{self.bot_username}?start=join_{self.chat_id}"
        return Kb(inline_keyboard=[[Btn(text="🤵🏼 Qo'shilish", url=url)]])

    async def open_lobby(self) -> None:
        msg = await self.send(self.lobby_text(), self.lobby_kb())
        self.lobby_msg_id = msg.message_id if msg else None
        if self.lobby_msg_id:
            try:
                await self.bot.pin_chat_message(self.chat_id, self.lobby_msg_id,
                                                disable_notification=True)
            except TelegramAPIError:
                pass  # botda "xabarni qadash" huquqi yo'q

    async def _unpin_lobby(self) -> None:
        if self.lobby_msg_id:
            try:
                await self.bot.unpin_chat_message(self.chat_id, self.lobby_msg_id)
            except TelegramAPIError:
                pass

    async def refresh_lobby(self) -> None:
        if not self.lobby_msg_id:
            return
        try:
            await self.bot.edit_message_text(
                self.lobby_text(), chat_id=self.chat_id,
                message_id=self.lobby_msg_id, reply_markup=self.lobby_kb())
        except TelegramAPIError:
            pass

    async def join(self, uid: int, name: str) -> str:
        if self.status != "lobby":
            return "closed"
        if uid in self.players:
            return "already"
        if len(self.players) >= MAX_PLAYERS:
            return "full"
        self.players[uid] = Player(uid, name)
        if len(self.players) >= MAX_PLAYERS:
            self.force_start = True
        await self.refresh_lobby()
        return "ok"

    async def leave(self, uid: int) -> bool:
        if self.status != "lobby" or uid not in self.players:
            return False
        del self.players[uid]
        await self.refresh_lobby()
        return True

    def extend(self, seconds: int = 60) -> None:
        self.deadline += seconds
        self.warned = False

    # ---------- O'yin davomida chiqish / chiqarib yuborish ----------
    async def remove_player(self, uid: int, kicked: bool = False) -> bool:
        if self.status == "lobby":
            return await self.leave(uid)
        p = self.players.get(uid)
        if not p or not p.alive or self.status != "running":
            return False
        p.alive = False
        reveal = await self._reveal(p)
        if kicked:
            await self.send(f"🚪 {p.mention} o'yindan chiqarib yuborildi.\nU edi {reveal}..")
        else:
            await self.send(f"💀 {p.mention} bu shaharning yovuzliklariga chiday olmadi va "
                            f"o'zini osib qo'ydi.\nU {reveal} edi")
        self.required = {k for k in self.required if k[0] != uid}
        if self.phase == "night":
            self._maybe_done()
        elif self.phase == "voting":
            self.votes.pop(uid, None)
            if self._all_voted():
                self.vote_event.set()
        elif self.phase == "confirm":
            self.confirm_votes.pop(uid, None)
            if uid == self.confirm_target or self._all_confirmed():
                self.confirm_event.set()
        await self._promote_serjant()
        return True

    # ---------- Asosiy sikl ----------
    async def run(self) -> None:
        try:
            await self._lobby_wait()
            await self._unpin_lobby()
            if len(self.players) < MIN_PLAYERS:
                await self.send(f"❌ O'yinchilar yetarli emas (kamida {MIN_PLAYERS}). O'yin bekor qilindi.")
                return
            await self._setup()
            while True:
                self.day += 1
                await self._night()
                if await self._check_win():
                    return
                await self._day_talk()
                await self._vote()
                if await self._check_win():
                    return
        except asyncio.CancelledError:
            await self._unpin_lobby()
            raise
        except Exception:
            log.exception("O'yinda xatolik")
            await self.send("⚠️ O'yinda kutilmagan xatolik yuz berdi. O'yin to'xtatildi.")
        finally:
            GAMES.pop(self.chat_id, None)

    async def _lobby_wait(self) -> None:
        loop = asyncio.get_running_loop()
        self.deadline = loop.time() + LOBBY_TIME
        while not self.force_start and loop.time() < self.deadline:
            await asyncio.sleep(1)
            if not self.warned and self.deadline - loop.time() <= 30:
                self.warned = True
                await self.send("⏳ Ro'yxat tugashiga 30 soniya qoldi!", self.lobby_kb())

    async def _setup(self) -> None:
        self.status = "running"
        self.started_at = time.monotonic()
        self.game_id = await db.create_game(self.chat_id)
        self.premium = await db.is_premium(self.chat_id)
        await self._assign_roles()
        for p in self.players.values():
            p.items = await db.get_inventory(p.uid)

        await self.send(f"🎲 <b>O'yin boshlandi!</b> Ishtirokchilar: {len(self.players)}\n\n"
                        "Rollaringiz shaxsiy xabarda yuborildi.")
        mafia_team = [p for p in self.players.values() if p.role in MAFIA_SIDE]
        for p in self.players.values():
            text = f"{role_label(p.role)}\n\n<b>Sizning rolingiz!</b>\n{ROLE_INFO[p.role][2]}"
            if p.role in MAFIA_SIDE:
                team = "\n".join(f"• {q.mention} — {role_label(q.role)}" for q in mafia_team)
                text += f"\n\n🤵🏼 <b>Mafiya jamoasi:</b>\n{team}"
            if not await self.dm(p.uid, text):
                await self.send(f"⚠️ {p.mention} ga xabar yuborib bo'lmadi. Botga /start bosing!")

    async def _assign_roles(self) -> None:
        ids = list(self.players)
        random.shuffle(ids)
        pool = make_roles(len(ids))
        assigned: dict[int, str] = {}
        used_unique: set[str] = set()
        for uid in ids:
            user = await db.get_user(uid)
            want = (user or {}).get("next_role")
            if not want or want not in ROLE_INFO or want == "civilian":
                continue
            if want in pool:
                pool.remove(want)
            elif want in UNIQUE_ROLES and want not in used_unique and "civilian" in pool:
                pool.remove("civilian")
            else:
                continue
            assigned[uid] = want
            if want in UNIQUE_ROLES:
                used_unique.add(want)
        random.shuffle(pool)
        for uid in ids:
            self.players[uid].role = assigned.get(uid) or pool.pop()
        for uid in assigned:
            await db.set_next_role(uid, None)

    # ---------- Tun ----------
    def _menu_rows(self, act: str, targets: list[Player]) -> list[list[Btn]]:
        return [[Btn(text=q.name[:30], callback_data=f"n:{self.chat_id}:{act}:{q.uid}")]
                for q in targets]

    async def _night(self) -> None:
        self.phase = "night"
        self.actions = {}
        self.required = set()
        self._said = set()
        self.night_event = asyncio.Event()
        to_bot = Kb(inline_keyboard=[[Btn(text="🤖 Botga o'tish",
                                          url=f"https://t.me/{self.bot_username}")]])
        await self.send_media(
            f"🌙 <b>Tun: {self.day}</b>\nKo'chaga faqat jasur va qo'rqmas odamlar chiqishdi. "
            "Ertalab tirik qolganlarni sanaymiz...", config.GIF_NIGHT, to_bot)
        await self.send(self.alive_text())

        alive = self.alive_players()
        don_alive = any(p.role == "don" for p in alive)
        for p in alive:
            r = p.role
            rows = None
            if r in ("don", "mafiya"):
                rows = self._menu_rows("kill", [q for q in alive if q.role not in MAFIA_SIDE])
                title, grp = "🔪 Kimni o'ldiramiz?", "kill"
                if r == "don" or not don_alive:
                    self.required.add((p.uid, grp))
            elif r == "qotil":
                rows = self._menu_rows("qkill", [q for q in alive if q.uid != p.uid])
                title, grp = "🔪 Bu tun kimni o'ldirasiz?", "qkill"
                self.required.add((p.uid, grp))
            elif r == "doktor":
                rows = self._menu_rows("heal", [q for q in alive if q.uid != p.uid or not p.self_healed])
                title, grp = "💉 Kimni davolaysiz?", "heal"
                self.required.add((p.uid, grp))
            elif r == "kezuvchi":
                rows = self._menu_rows("block", [q for q in alive if q.uid != p.uid])
                title, grp = "💃🏼 Kimning oldiga borasiz?", "block"
                self.required.add((p.uid, grp))
            elif r == "daydi":
                rows = self._menu_rows("watch", [q for q in alive if q.uid != p.uid])
                title, grp = "🧙🏼‍♂️ Kimning oldiga borasiz?", "watch"
                self.required.add((p.uid, grp))
            elif r == "advokat":
                rows = self._menu_rows("lawyer", alive)
                title, grp = "⚖️ Kimni himoya qilasiz?", "lawyer"
                self.required.add((p.uid, grp))
            elif r == "komissar":
                rows = []
                for q in alive:
                    if q.uid == p.uid:
                        continue
                    row = [Btn(text=f"🔍 {q.name[:22]}", callback_data=f"n:{self.chat_id}:check:{q.uid}")]
                    if self.day >= 2:
                        row.append(Btn(text=f"🔫 {q.name[:22]}",
                                       callback_data=f"n:{self.chat_id}:shoot:{q.uid}"))
                    rows.append(row)
                title, grp = "🕵🏼 Tekshirasizmi yoki otasizmi?", "kom"
                self.required.add((p.uid, grp))
            if rows is not None:
                rows.append([Btn(text="⏭ O'tkazib yuborish", callback_data=f"n:{self.chat_id}:s:{grp}")])
                await self.dm(p.uid, f"🌙 <b>Tun: {self.day}</b>\n{title}", Kb(inline_keyboard=rows))
            if p.items.get("gun", 0) > 0:
                grows = self._menu_rows("gun", [q for q in alive if q.uid != p.uid])
                grows.append([Btn(text="⏭ Ishlatmayman", callback_data=f"n:{self.chat_id}:s:gun")])
                await self.dm(p.uid, "🔫 <b>Miltiq!</b> Kimni otasiz? (bir marta ishlatiladi)",
                              Kb(inline_keyboard=grows))

        if not self.required:
            self.night_event.set()
        try:
            await asyncio.wait_for(self.night_event.wait(), NIGHT_TIME)
        except asyncio.TimeoutError:
            pass
        self.phase = "resolving"
        await self._resolve_night()

    def _can(self, p: Player, grp: str) -> bool:
        if grp not in GROUP_ROLES:
            return False
        if grp == "gun":
            return p.items.get("gun", 0) > 0
        return p.role in GROUP_ROLES[grp]

    def _maybe_done(self) -> None:
        if self.required <= set(self.actions):
            self.night_event.set()

    async def _news(self, key: str, text: str) -> None:
        if key not in self._said:
            self._said.add(key)
            await self.send(text)

    async def handle_night(self, uid: int, act: str, arg: str) -> tuple[bool, str]:
        if self.status != "running" or self.phase != "night":
            return False, "⏳ Hozir tun emas."
        p = self.players.get(uid)
        if not p or not p.alive:
            return False, "Siz o'yinda emassiz."
        if act == "s":
            if not self._can(p, arg):
                return False, "Noto'g'ri harakat."
            if (uid, arg) in self.actions:
                return False, "Siz allaqachon tanlagansiz."
            self.actions[(uid, arg)] = ("skip", 0)
            self._maybe_done()
            return True, "⏭ Bu tunda harakat qilmaslikni tanladingiz."
        grp = ACT_GROUP.get(act)
        if not grp or not self._can(p, grp):
            return False, "Noto'g'ri harakat."
        if (uid, grp) in self.actions:
            return False, "Siz allaqachon tanlagansiz."
        try:
            tid = int(arg)
        except ValueError:
            return False, "Xato."
        t = self.players.get(tid)
        if not t or not t.alive:
            return False, "Bu o'yinchi tirik emas."
        if act == "shoot" and self.day < 2:
            return False, "1-tunda otish mumkin emas."
        if tid == uid and act not in ("heal", "lawyer"):
            return False, "O'zingizni tanlay olmaysiz."
        if act == "heal" and tid == uid and p.self_healed:
            return False, "O'zingizni allaqachon davolagansiz."
        if act == "kill" and t.role in MAFIA_SIDE:
            return False, "Jamoadoshni tanlab bo'lmaydi."
        self.actions[(uid, grp)] = (act, tid)
        self._maybe_done()
        if act == "kill":
            await self._news("kill", f"🤵🏼 {ROLE_INFO[p.role][1]} navbatdagi o'ljasini tanladi...")
        elif act in ACT_NEWS:
            await self._news(act, ACT_NEWS[act])
        return True, f"{ACT_LABEL[act]}: {escape(t.name)}"

    async def _use_item(self, p: Player, code: str) -> None:
        p.items[code] = max(0, p.items.get(code, 0) - 1)
        await db.consume_item(p.uid, code)

    async def _reveal(self, p: Player) -> str:
        if p.items.get("mask", 0) > 0:
            await self._use_item(p, "mask")
            return "🎭 (rol maska bilan yashirilgan)"
        return role_label(p.role)

    async def _resolve_night(self) -> None:
        P = self.players
        acts = [(uid, a, t) for (uid, _), (a, t) in self.actions.items()
                if a != "skip" and P[uid].alive]
        blocked = {t for _, a, t in acts if a == "block"}
        for b in blocked:
            await self.dm(b, "😴 Bu tunda sizni uxlatishdi. Harakatingiz bajarilmadi.")
        live = [x for x in acts if x[0] not in blocked]

        visits: dict[int, list[int]] = {}
        for uid, _, t in live:
            visits.setdefault(t, []).append(uid)

        healed: dict[int, int] = {}
        disguised: set[int] = set()
        for uid, a, t in live:
            if a == "heal":
                healed[t] = uid
                if t == uid:
                    P[uid].self_healed = True
            elif a == "lawyer" and P[t].role in MAFIA_SIDE:
                disguised.add(t)

        attacks: list[tuple[int, int, str]] = []
        kills = [(uid, t) for uid, a, t in live if a == "kill"]
        if kills:
            dons = [x for x in kills if P[x[0]].role == "don"]
            uid, t = dons[0] if dons else random.choice(kills)
            attacks.append((uid, t, "mafia"))
        for uid, a, t in live:
            if a == "qkill":
                attacks.append((uid, t, "qkill"))
            elif a == "shoot":
                attacks.append((uid, t, "kom"))
            elif a == "gun":
                attacks.append((uid, t, "gun"))
                await self._use_item(P[uid], "gun")

        deaths: dict[int, int] = {}
        saved_any = False
        for attacker, tid, kind in attacks:
            v = P[tid]
            if not v.alive or tid in deaths:
                continue
            if tid in healed:
                saved_any = True
                await self.dm(healed[tid], f"💉 Siz {escape(v.name)} ni o'limdan qutqardingiz!")
                await self.dm(tid, "💉 Sizga hujum qilishdi, lekin doktor qutqardi!")
                continue
            if v.role == "bori" and kind in ("mafia", "kom"):
                v.role = "mafiya" if kind == "mafia" else "serjant"
                await self.dm(tid, f"🐺 Sizga hujum qilishdi va siz endi {role_label(v.role)} bo'ldingiz!")
                saved_any = True
                continue
            if kind == "qkill" and v.items.get("killer_shield", 0) > 0:
                await self._use_item(v, "killer_shield")
                await self.dm(tid, "⛑ Qotildan himoya sizni qutqardi!")
                saved_any = True
                continue
            if v.items.get("shield", 0) > 0:
                await self._use_item(v, "shield")
                await self.dm(tid, "🛡 Himoyangiz sizni qutqardi!")
                saved_any = True
                continue
            deaths[tid] = attacker

        revenge: list[tuple[int, int]] = []
        for vid, attacker in list(deaths.items()):
            if P[vid].role == "afsungar" and P[attacker].alive and attacker not in deaths:
                deaths[attacker] = vid
                revenge.append((vid, attacker))

        for uid, a, t in live:
            if a != "check":
                continue
            v = P[t]
            raw = "mafia" if v.role in MAFIA_SIDE else "killer" if v.role == "qotil" else "civil"
            if raw != "civil":
                if t in disguised:
                    raw = "civil"
                elif v.items.get("docs", 0) > 0:
                    await self._use_item(v, "docs")
                    raw = "civil"
            text = {"mafia": "🤵🏼 MAFIYA", "killer": "🔪 QOTIL", "civil": "👨🏼 Tinch aholi"}[raw]
            await self.dm(uid, f"🔍 {escape(v.name)} — <b>{text}</b>")

        for uid, a, t in live:
            if a == "watch":
                seen = [P[x].name for x in visits.get(t, []) if x != uid]
                if seen:
                    who = ", ".join(escape(n) for n in seen)
                    await self.dm(uid, f"🧙🏼‍♂️ {escape(P[t].name)} ning oldiga kelganlar: <b>{who}</b>")
                else:
                    await self.dm(uid, f"🧙🏼‍♂️ {escape(P[t].name)} ning oldiga hech kim kelmadi.")

        await self.send_media(
            f"🌅 <b>Xayrli tong!</b>\n☀️ Kun: {self.day}\n"
            "Shamollar tundagi mish-mishlarni butun shaharga yetkazmoqda..", config.GIF_DAY)
        lines = []
        if saved_any:
            lines.append("💫 Kimdir ximoyasini ishlatdi!")
        if deaths:
            for vid in deaths:
                v = P[vid]
                v.alive = False
                lines.append(f"💀 Bu tunda {v.mention} o'ldirildi.\nU edi {await self._reveal(v)}..")
            for vid, attacker in revenge:
                lines.append(f"🔥 Afsungar o'zi bilan {P[attacker].mention} ni ham olib ketdi!")
        else:
            lines.append("Ishonish qiyin, lekin bu tunda hech kim o'lmadi...")
        await self.send("\n\n".join(lines))
        await self._promote_serjant()

    async def _promote_serjant(self) -> None:
        alive = self.alive_players()
        if any(p.role == "komissar" for p in alive):
            return
        for p in alive:
            if p.role == "serjant":
                p.role = "komissar"
                await self.dm(p.uid, "🕵🏼 Komissar vafot etdi. Endi siz <b>Komissar Katani</b>siz!")
                await self.send("🕵🏼 Serjant Komissarning o'rnini egalladi.")
                return

    # ---------- Kun ----------
    async def _day_talk(self) -> None:
        self.phase = "day"
        await self.send(f"{self.alive_text()}\n\nEndi kechaning natijalarini muhokama qilish, "
                        "sabablari va oqibatlarini tushunish vaqti keldi ...")
        await asyncio.sleep(DAY_TIME)

    def _all_voted(self) -> bool:
        return all(p.uid in self.votes for p in self.alive_players())

    def _vote_kb(self) -> Kb:
        counts = Counter(self.votes.values())
        rows = [[Btn(text=f"{p.name[:28]} ({counts.get(p.uid, 0)})",
                     callback_data=f"v:{self.chat_id}:{p.uid}")] for p in self.alive_players()]
        rows.append([Btn(text=f"🚫 Hech kim ({counts.get(0, 0)})",
                         callback_data=f"v:{self.chat_id}:0")])
        return Kb(inline_keyboard=rows)

    async def _vote(self) -> None:
        self.phase = "voting"
        self.votes = {}
        self.vote_event = asyncio.Event()
        msg = await self.send(f"⚖️ <b>Aybdorlarni aniqlash va jazolash vaqti keldi.</b>\n"
                              f"Ovoz berish uchun {VOTE_TIME} sekund", self._vote_kb())
        self.vote_msg_id = msg.message_id if msg else None
        try:
            await asyncio.wait_for(self.vote_event.wait(), VOTE_TIME)
        except asyncio.TimeoutError:
            pass
        self.phase = "resolving"
        await self._drop_kb(self.vote_msg_id)

        P = self.players
        counts = Counter(v for voter, v in self.votes.items()
                         if v != 0 and P[voter].alive and P[v].alive)
        skip = sum(1 for voter, v in self.votes.items() if v == 0 and P[voter].alive)
        ranked = counts.most_common()
        no_result = ("🗳 <b>Ovoz berish yakunlandi:</b>\nAholi kelisha olmadi... "
                     "Kelisha olmaslik oqibatida hech kim osilmadi...")
        if not ranked or (len(ranked) > 1 and ranked[1][1] == ranked[0][1]) or skip >= ranked[0][1]:
            await self.send(no_result)
            return
        victim = P[ranked[0][0]]
        if not await self._confirm(victim):
            await self.send(f"⚖️ Aholi {victim.mention} ni osishni qo'llab-quvvatlamadi. Hech kim osilmadi.")
            return
        if not victim.alive:
            return
        if victim.items.get("vote_shield", 0) > 0:
            await self._use_item(victim, "vote_shield")
            await self.send(f"⚖️ {victim.mention} osilishi kerak edi, lekin ovoz himoyasi uni qutqardi!")
            return
        victim.alive = False
        await self.send(f"⚰️ {victim.mention} O'tkazilgan kunduzgi yig'ilishda osildi!\n"
                        f"U edi {await self._reveal(victim)}..")
        if victim.role == "afsungar":
            await self._afsun_revenge(victim)
        await self._promote_serjant()

    async def _drop_kb(self, msg_id: int | None) -> None:
        if msg_id:
            try:
                await self.bot.edit_message_reply_markup(
                    chat_id=self.chat_id, message_id=msg_id, reply_markup=None)
            except TelegramAPIError:
                pass

    async def handle_vote(self, uid: int, target: int) -> tuple[bool, str]:
        if self.status != "running" or self.phase != "voting":
            return False, "⏳ Hozir ovoz berish vaqti emas."
        p = self.players.get(uid)
        if not p or not p.alive:
            return False, "Faqat tirik o'yinchilar ovoz beradi."
        if uid in self.votes:
            return False, "Siz allaqachon ovoz bergansiz."
        if target != 0:
            t = self.players.get(target)
            if not t or not t.alive:
                return False, "Bu o'yinchi tirik emas."
            if target == uid:
                return False, "O'zingizga ovoz bera olmaysiz."
            news = f"{p.mention} — {t.mention} ga ovoz berdi"
        else:
            news = f"🚫 {p.mention} hech kimni tanlamaslikka qaror qildi.."
        self.votes[uid] = target
        if self._all_voted():
            self.vote_event.set()
        if self.vote_msg_id:
            try:
                await self.bot.edit_message_reply_markup(
                    chat_id=self.chat_id, message_id=self.vote_msg_id, reply_markup=self._vote_kb())
            except TelegramAPIError:
                pass
        await self.send(news)
        return True, "✅ Ovozingiz qabul qilindi"

    # ---------- Tasdiqlash: "Rostdan ham osmoqchimisiz?" ----------
    def _confirm_voters(self) -> list[Player]:
        return [p for p in self.alive_players() if p.uid != self.confirm_target]

    def _all_confirmed(self) -> bool:
        return all(p.uid in self.confirm_votes for p in self._confirm_voters())

    def _confirm_kb(self) -> Kb:
        c = Counter(self.confirm_votes.values())
        return Kb(inline_keyboard=[[
            Btn(text=f"👍 {c.get('y', 0)}", callback_data=f"c:{self.chat_id}:y"),
            Btn(text=f"👎 {c.get('n', 0)}", callback_data=f"c:{self.chat_id}:n")]])

    async def _confirm(self, victim: Player) -> bool:
        self.phase = "confirm"
        self.confirm_target = victim.uid
        self.confirm_votes = {}
        self.confirm_event = asyncio.Event()
        msg = await self.send(f"Rostdan ham {victim.mention} ni osmoqchimisiz?", self._confirm_kb())
        self.confirm_msg_id = msg.message_id if msg else None
        try:
            await asyncio.wait_for(self.confirm_event.wait(), CONFIRM_TIME)
        except asyncio.TimeoutError:
            pass
        self.phase = "resolving"
        await self._drop_kb(self.confirm_msg_id)
        c = Counter(self.confirm_votes.values())
        yes, no = c.get("y", 0), c.get("n", 0)
        await self.send(f"<b>Ovoz berish natijalari:</b>\n{yes} 👍 | {no} 👎")
        return yes > no

    async def handle_confirm(self, uid: int, choice: str) -> tuple[bool, str]:
        if self.status != "running" or self.phase != "confirm":
            return False, "⏳ Hozir ovoz berish vaqti emas."
        p = self.players.get(uid)
        if not p or not p.alive or uid == self.confirm_target:
            return False, "Siz bu ovozda qatnasha olmaysiz."
        if uid in self.confirm_votes:
            return False, "Siz allaqachon ovoz bergansiz."
        if choice not in ("y", "n"):
            return False, "Xato."
        self.confirm_votes[uid] = choice
        if self._all_confirmed():
            self.confirm_event.set()
        if self.confirm_msg_id:
            try:
                await self.bot.edit_message_reply_markup(
                    chat_id=self.chat_id, message_id=self.confirm_msg_id,
                    reply_markup=self._confirm_kb())
            except TelegramAPIError:
                pass
        return True, "✅ Ovozingiz qabul qilindi"

    # ---------- Afsungar ----------
    async def _afsun_revenge(self, p: Player) -> None:
        others = [q for q in self.alive_players() if q.uid != p.uid]
        if not others:
            return
        self.afsun_uid = p.uid
        self.afsun_target = None
        self.afsun_event = asyncio.Event()
        rows = [[Btn(text=q.name[:30], callback_data=f"a:{self.chat_id}:{q.uid}")] for q in others]
        sent = await self.dm(p.uid, f"🧟‍♂️ Siz osildingiz! O'zingiz bilan kimni olib ketasiz? "
                                    f"({AFSUN_TIME} soniya)", Kb(inline_keyboard=rows))
        if sent:
            try:
                await asyncio.wait_for(self.afsun_event.wait(), AFSUN_TIME)
            except asyncio.TimeoutError:
                pass
        self.afsun_uid = 0
        t = self.players.get(self.afsun_target) if self.afsun_target else None
        if not t or not t.alive:
            t = random.choice(others)
        t.alive = False
        await self.send(f"🔥 Afsungar o'zi bilan {t.mention} ni ham olib ketdi!\n"
                        f"U edi {await self._reveal(t)}..")

    async def handle_afsun(self, uid: int, target: int) -> tuple[bool, str]:
        if uid != self.afsun_uid:
            return False, "Hozir tanlash vaqti emas."
        t = self.players.get(target)
        if not t or not t.alive or target == uid:
            return False, "Bu o'yinchini tanlab bo'lmaydi."
        self.afsun_target = target
        self.afsun_event.set()
        return True, f"🔥 Tanlov: {escape(t.name)}"

    # ---------- G'alaba ----------
    def _winner(self) -> str | None:
        alive = self.alive_players()
        if not alive:
            return "draw"
        m = sum(1 for p in alive if p.role in MAFIA_SIDE)
        k = sum(1 for p in alive if p.role == "qotil")
        c = len(alive) - m - k
        if m == 0 and k == 0:
            return "civil"
        if m == 0 and c == 0:
            return "killer"
        if m > 0 and m >= c + k:
            return "mafia"
        return None

    async def _check_win(self) -> bool:
        winner = self._winner()
        if winner is None:
            return False
        await self._finish(winner)
        return True

    async def _finish(self, winner: str) -> None:
        self.phase = "finished"
        titles = {"civil": "🏆 Tinch aholi g'alaba qozondi!", "mafia": "🏆 Mafiya g'alaba qozondi!",
                  "killer": "🏆 Qotil g'alaba qozondi!", "draw": "🤝 Durang! Hech kim tirik qolmadi."}
        winners = [p for p in self.players.values() if side_of(p.role) == winner]
        win_ids = {p.uid for p in winners}
        base = WIN_REWARD * (2 if self.premium else 1)
        results = []
        for p in self.players.values():
            reward = 0
            if p.uid in win_ids:
                reward = base
                partner = await db.get_partner(p.uid)
                if partner in win_ids:
                    reward += MARRIAGE_BONUS
            results.append((p.uid, p.role, p.alive, p.uid in win_ids, reward))
        try:
            await db.finish_game(self.game_id, winner, self.day, results)
        except Exception:
            log.exception("natijani saqlab bo'lmadi")

        minutes = max(1, round((time.monotonic() - self.started_at) / 60))
        lines = ["<b>O'yin tugadi!</b>", titles[winner], ""]
        n = 0
        if winners:
            lines.append("<b>G'oliblar:</b>")
            for p in winners:
                n += 1
                lines.append(f"    {n}. {p.mention} - {ROLE_INFO[p.role][1]}")
            lines.append("")
        rest = [p for p in self.players.values() if p.uid not in win_ids]
        if rest:
            lines.append("<b>Qolgan o'yinchilar:</b>")
            for p in rest:
                n += 1
                lines.append(f"    {n}. {p.mention} - {ROLE_INFO[p.role][1]}")
            lines.append("")
        lines.append(f"O'yin: <b>{minutes} minut</b> davom etdi")
        if winners:
            lines.append(f"💵 G'oliblarga {base}$ berildi" + (" (premium ×2)" if self.premium else ""))
        await self.send("\n".join(lines))
