"""Admin panel: /admin — balans, rol, Top guruhlar (reklama), adminlar, broadcast, statistika."""
import asyncio
import logging
import re
from html import escape

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramRetryAfter
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton as Btn
from aiogram.types import InlineKeyboardMarkup as Kb
from aiogram.types import Message

import config
import database as db
import game as g
from handlers_pay import is_staff_user, notify_owners, send_pending

log = logging.getLogger("mafia.admin")
router = Router()
PRIVATE = F.chat.type == ChatType.PRIVATE

BLOCKED = ("❌ Adminlarga (o'zingizga ham) balans yoki rol berishni faqat ega qila oladi.\n"
           "Boshqa foydalanuvchilarga bera olasiz.")


class AS(StatesGroup):
    balance = State()
    role_target = State()
    broadcast = State()
    ad_link = State()
    admin_add = State()


def is_owner(uid: int) -> bool:
    return uid in config.OWNER_IDS


async def _blocked(actor: int, target: int) -> bool:
    """Ega bo'lmagan admin o'ziga yoki boshqa adminga balans/rol bera olmaydi."""
    return not is_owner(actor) and await is_staff_user(target)


def admin_kb(uid: int) -> Kb:
    rows = [
        [Btn(text="💵 Dollar +/−", callback_data="adm:bal:dollars"),
         Btn(text="💎 Olmos +/−", callback_data="adm:bal:diamonds")],
        [Btn(text="🎭 Rol berish", callback_data="adm:role")],
        [Btn(text="🧾 Buyurtmalar (chek)", callback_data="adm:orders")],
        [Btn(text="⭐ Top guruh qo'shish", callback_data="adm:adadd"),
         Btn(text="🗑 Reklamani o'chirish", callback_data="adm:adlist")],
    ]
    if is_owner(uid):
        rows.append([Btn(text="➕ Admin qo'shish", callback_data="adm:adminadd"),
                     Btn(text="➖ Admin o'chirish", callback_data="adm:admindel")])
    rows += [
        [Btn(text="📢 Broadcast", callback_data="adm:bc")],
        [Btn(text="📊 Statistika", callback_data="adm:stats"),
         Btn(text="👑 Adminlar", callback_data="adm:list")],
    ]
    return Kb(inline_keyboard=rows)


BACK = Kb(inline_keyboard=[[Btn(text="⬅️ Admin panel", callback_data="adm:menu")]])


async def _edit(call: CallbackQuery, text: str, kb: Kb | None = None) -> None:
    try:
        await call.message.edit_text(text, reply_markup=kb)
    except TelegramBadRequest:
        pass


# ---------- Guruh havolasini tekshirish ----------
_LINK = re.compile(r"^(?:https?://)?(?:www\.)?(?:t|telegram)\.me/(joinchat/)?([A-Za-z0-9_+\-]{5,64})/?(?:\?.*)?$", re.I)
_USER = re.compile(r"^@([A-Za-z][A-Za-z0-9_]{4,31})$")


def parse_group_link(raw: str) -> tuple[str, str | None] | None:
    """(to'liq havola, ochiq username yoki None). Yaroqsiz bo'lsa None."""
    raw = (raw or "").strip()
    m = _USER.match(raw)
    if m:
        return f"https://t.me/{m.group(1)}", m.group(1)
    m = _LINK.match(raw)
    if not m:
        return None
    joinchat, slug = m.group(1), m.group(2)
    url = "https://t.me/" + ("joinchat/" if joinchat else "") + slug
    public = None if (joinchat or slug.startswith("+")) else slug
    return url, public


async def _ads_view() -> tuple[str, Kb]:
    ads = await db.list_ads(40)
    rows = [[Btn(text=f"🗑 {a['title'][:35]}", callback_data=f"adm:addel:{a['ad_id']}")] for a in ads]
    rows.append([Btn(text="⬅️ Admin panel", callback_data="adm:menu")])
    text = ("🗑 <b>Reklamani o'chirish</b>\n\nO'chirmoqchi bo'lgan guruhni bosing:" if ads
            else "⭐ Hozircha reklama guruhlari yo'q.")
    return text, Kb(inline_keyboard=rows)


async def _admins_del_view() -> tuple[str, Kb]:
    ids = [i for i in await db.list_admins() if not is_owner(i)]
    rows = []
    for i in ids:
        u = await db.get_user(i)
        label = ((u or {}).get("full_name") or "Admin")[:22]
        rows.append([Btn(text=f"➖ {label} ({i})", callback_data=f"adm:admindel:{i}")])
    rows.append([Btn(text="⬅️ Admin panel", callback_data="adm:menu")])
    text = ("➖ <b>Admin o'chirish</b>\n\nAdminlikni bekor qilmoqchi bo'lgan odamni bosing:" if ids
            else "👑 Egadan boshqa adminlar yo'q.")
    return text, Kb(inline_keyboard=rows)


# ---------- Panel ----------
@router.message(Command("admin"), PRIVATE)
async def cmd_admin(message: Message, state: FSMContext) -> None:
    if not await db.is_admin(message.from_user.id):
        return
    await state.clear()
    await message.answer("👑 <b>Admin panel</b>", reply_markup=admin_kb(message.from_user.id))


@router.callback_query(F.data.startswith("adm:"))
async def cb_admin(call: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    uid = call.from_user.id
    if not await db.is_admin(uid):
        await call.answer("Ruxsat yo'q.", show_alert=True)
        return
    bits = call.data.split(":")
    action = bits[1]
    arg = bits[2] if len(bits) > 2 else ""

    if action == "menu":
        await state.clear()
        await _edit(call, "👑 <b>Admin panel</b>", admin_kb(uid))
    elif action == "bal":
        await state.set_state(AS.balance)
        await state.update_data(cur=arg)
        sym = "💵 dollar" if arg == "dollars" else "💎 olmos"
        await _edit(call, f"{sym}: yuboring <code>ID_yoki_@username miqdor</code>\n"
                          "Masalan: <code>@ali 50</code> (qo'shadi) yoki <code>123456 -20</code> (ayiradi)", BACK)
    elif action == "role":
        await state.set_state(AS.role_target)
        await _edit(call, "🎭 Rol beriladigan o'yinchining ID yoki @username ini yuboring:", BACK)
    elif action == "setrole":
        data = await state.get_data()
        target = data.get("target")
        if not target:
            await call.answer("Avval o'yinchini tanlang.", show_alert=True)
            return
        if await _blocked(uid, target):
            await state.clear()
            await _edit(call, BLOCKED, BACK)
            await call.answer()
            return
        role = None if arg == "none" else arg
        if role and role not in g.ROLE_INFO:
            await call.answer()
            return
        await db.set_next_role(target, role)
        await state.clear()
        await _edit(call, "✅ Rol olib tashlandi." if role is None
                    else f"✅ Keyingi o'yin uchun rol: {g.role_label(role)}", BACK)
        if role and not is_owner(uid):
            await notify_owners(bot, f"ℹ️ Admin {escape(call.from_user.full_name)} ({uid}) "
                                     f"{target} ga rol berdi: {g.role_label(role)}")
    elif action == "orders":
        await send_pending(bot, call.message.chat.id, uid)
    elif action == "adadd":
        await state.set_state(AS.ad_link)
        await _edit(call, "⭐ <b>Top guruh qo'shish</b>\n\n"
                          "Guruh (yoki kanal) havolasini yuboring:\n"
                          "<code>https://t.me/guruh_nomi</code> yoki <code>@guruh_nomi</code>\n"
                          "Yopiq guruh uchun taklif havolasi: <code>https://t.me/+AbCd...</code>\n\n"
                          "Xohlasangiz, 2-qatorga guruh nomini yozing (yopiq guruhda nom shart emas, "
                          "ochiq guruhda bot o'zi topadi).\nBekor qilish: /cancel", BACK)
    elif action == "adlist":
        text, kb = await _ads_view()
        await _edit(call, text, kb)
    elif action == "addel":
        ok = await db.del_ad(int(arg))
        text, kb = await _ads_view()
        await _edit(call, text, kb)
        await call.answer("🗑 O'chirildi." if ok else "Bu reklama allaqachon o'chirilgan.")
        return
    elif action in ("adminadd", "admindel"):
        if not is_owner(uid):
            await call.answer("Bu amalni faqat ega bajara oladi.", show_alert=True)
            return
        if action == "adminadd":
            await state.set_state(AS.admin_add)
            await _edit(call, "➕ <b>Admin qo'shish</b>\n\nYangi adminning Telegram <b>ID raqami</b>ni yuboring "
                              "(ID ni @userinfobot orqali bilib olish mumkin).\nBekor qilish: /cancel", BACK)
        elif arg:
            target = int(arg)
            if is_owner(target):
                await call.answer("Egani o'chirib bo'lmaydi.", show_alert=True)
                return
            ok = await db.del_admin(target)
            text, kb = await _admins_del_view()
            await _edit(call, text, kb)
            await call.answer("✅ Adminlik bekor qilindi." if ok else "Bunday admin yo'q.")
            if ok:
                try:
                    await bot.send_message(target, "ℹ️ Sizning adminligingiz bekor qilindi.")
                except TelegramAPIError:
                    pass
            return
        else:
            text, kb = await _admins_del_view()
            await _edit(call, text, kb)
    elif action == "bc":
        await state.set_state(AS.broadcast)
        await _edit(call, "📢 Barcha foydalanuvchilarga yuboriladigan xabarni yuboring "
                          "(matn, rasm, video — nima bo'lsa).\nBekor qilish: /cancel", BACK)
    elif action == "stats":
        s = await db.get_stats()
        await _edit(call, "📊 <b>Statistika</b>\n\n"
                          f"👥 Foydalanuvchilar: {s['users']}\n🎮 Hozir faol o'yinlar: {len(g.GAMES)}\n"
                          f"🏁 Tugagan o'yinlar: {s['total_games']}\n👑 Adminlar: {s['admins']}\n"
                          f"🎲 Premium guruhlar: {s['premium']}\n⭐ Reklama guruhlari: {s['ads']}\n"
                          f"🧾 Kutilayotgan buyurtmalar: {s['pending_orders']}", BACK)
    elif action == "list":
        lines = []
        for i in await db.list_admins():
            u = await db.get_user(i)
            name = escape((u or {}).get("full_name") or "—")
            lines.append(f"• {name} <code>{i}</code>" + (" 👑 ega" if is_owner(i) else ""))
        await _edit(call, f"👑 <b>Adminlar</b>\n\n{chr(10).join(lines) or '—'}", BACK)
    await call.answer()


# ---------- Balans ----------
@router.message(AS.balance, F.text)
async def as_balance(message: Message, state: FSMContext, bot: Bot) -> None:
    actor = message.from_user.id
    if not await db.is_admin(actor):
        return
    parts = message.text.split()
    if len(parts) != 2:
        await message.answer("❌ Format: <code>ID_yoki_@username miqdor</code>")
        return
    try:
        amount = int(parts[1])
    except ValueError:
        await message.answer("❌ Miqdor butun son bo'lishi kerak.")
        return
    user = await db.find_user(parts[0])
    if not user:
        await message.answer("❌ Foydalanuvchi topilmadi (u botni ishga tushirgan bo'lishi kerak).")
        return
    if await _blocked(actor, user["user_id"]):
        await state.clear()
        await message.answer(BLOCKED, reply_markup=BACK)
        return
    cur = (await state.get_data())["cur"]
    ok = await db.change_balance(user["user_id"], cur, amount, kind="admin")
    await state.clear()
    if not ok:
        await message.answer("❌ Foydalanuvchi balansi yetarli emas.", reply_markup=BACK)
        return
    fresh = await db.get_user(user["user_id"])
    sym = "💵" if cur == "dollars" else "💎"
    await message.answer(f"✅ {escape(user['full_name'] or '')}: {sym} {amount:+d}\nYangi balans: {fresh[cur]}",
                         reply_markup=BACK)
    if not is_owner(actor):
        await notify_owners(bot, f"ℹ️ Admin {escape(message.from_user.full_name)} ({actor}) → "
                                 f"{escape(user['full_name'] or '')} ({user['user_id']}): {sym} {amount:+d}")
    try:
        await bot.send_message(user["user_id"], f"{sym} Balansingiz admin tomonidan {amount:+d} ga o'zgartirildi.")
    except TelegramAPIError:
        pass


# ---------- Rol ----------
@router.message(AS.role_target, F.text)
async def as_role_target(message: Message, state: FSMContext) -> None:
    actor = message.from_user.id
    if not await db.is_admin(actor):
        return
    user = await db.find_user(message.text)
    if not user:
        await message.answer("❌ Foydalanuvchi topilmadi.")
        return
    if await _blocked(actor, user["user_id"]):
        await state.clear()
        await message.answer(BLOCKED, reply_markup=BACK)
        return
    await state.update_data(target=user["user_id"])
    rows = [[Btn(text=g.role_label(code), callback_data=f"adm:setrole:{code}")] for code in g.ROLE_INFO
            if code != "civilian"]
    rows.append([Btn(text="❌ Rolni olib tashlash", callback_data="adm:setrole:none")])
    await message.answer(f"👤 {escape(user['full_name'] or '')} uchun rolni tanlang:",
                         reply_markup=Kb(inline_keyboard=rows))


# ---------- Top guruh (reklama) qo'shish ----------
@router.message(AS.ad_link, F.text)
async def as_ad_link(message: Message, state: FSMContext, bot: Bot) -> None:
    if not await db.is_admin(message.from_user.id):
        return
    lines = [ln.strip() for ln in message.text.strip().splitlines() if ln.strip()]
    parsed = parse_group_link(lines[0]) if lines else None
    if not parsed:
        await message.answer("❌ Havola noto'g'ri. Masalan: <code>https://t.me/guruh_nomi</code> yoki "
                             "<code>@guruh_nomi</code>. Qaytadan yuboring (bekor qilish: /cancel).")
        return
    url, public = parsed
    title = " ".join(lines[1:])[:40] if len(lines) > 1 else ""
    if public:
        try:
            chat = await bot.get_chat("@" + public)
        except TelegramAPIError:
            await message.answer("❌ Bunday ochiq guruh yoki kanal topilmadi. Havolani tekshirib, qayta yuboring.")
            return
        if chat.type not in ("group", "supergroup", "channel"):
            await message.answer("❌ Bu guruh yoki kanal emas (bot yoki foydalanuvchi). Boshqa havola yuboring.")
            return
        title = title or (chat.title or public)[:40]
    title = title or "Guruh"
    ad_id = await db.add_ad(title, url, message.from_user.id)
    await state.clear()
    if ad_id is None:
        await message.answer("ℹ️ Bu guruh allaqachon reklama ro'yxatida.", reply_markup=BACK)
        return
    await message.answer(f"✅ Qo'shildi: <b>{escape(title)}</b>\nEndi u foydalanuvchilarga "
                         "«⭐ Top guruhlar» tugmasida ko'rinadi.", reply_markup=BACK)


# ---------- Admin qo'shish (faqat ega) ----------
async def _resolve_id(arg: str) -> int | None:
    arg = (arg or "").strip()
    if arg.lstrip("-").isdigit():
        return int(arg)
    user = await db.find_user(arg)
    return user["user_id"] if user else None


@router.message(AS.admin_add, F.text)
async def as_admin_add(message: Message, state: FSMContext, bot: Bot) -> None:
    if not is_owner(message.from_user.id):
        return
    uid = await _resolve_id(message.text)
    if uid is None:
        await message.answer("❌ Topilmadi. Telegram ID raqamini yuboring (yoki u botga /start bosgan bo'lsin).")
        return
    await state.clear()
    await db.add_admin(uid, message.from_user.id)
    await message.answer(f"✅ <code>{uid}</code> admin qilindi.", reply_markup=BACK)
    try:
        await bot.send_message(uid, "👑 Siz botda admin qilindingiz. Panel: /admin")
    except TelegramAPIError:
        pass


@router.message(Command("addadmin"))
async def cmd_addadmin(message: Message, command: CommandObject) -> None:
    if not is_owner(message.from_user.id):
        return
    uid = await _resolve_id(command.args)
    if uid is None:
        await message.reply("Foydalanish: <code>/addadmin ID_yoki_@username</code>")
        return
    await db.add_admin(uid, message.from_user.id)
    await message.reply(f"✅ <code>{uid}</code> admin qilindi.")


@router.message(Command("deladmin"))
async def cmd_deladmin(message: Message, command: CommandObject) -> None:
    if not is_owner(message.from_user.id):
        return
    uid = await _resolve_id(command.args)
    if uid is None:
        await message.reply("Foydalanish: <code>/deladmin ID_yoki_@username</code>")
        return
    if is_owner(uid):
        await message.reply("❌ Egani o'chirib bo'lmaydi.")
        return
    await message.reply("✅ Admin o'chirildi." if await db.del_admin(uid) else "ℹ️ Bunday admin yo'q.")


# ---------- Broadcast ----------
@router.message(AS.broadcast)
async def as_broadcast(message: Message, state: FSMContext, bot: Bot) -> None:
    if not await db.is_admin(message.from_user.id):
        return
    await state.clear()
    ids = await db.get_all_user_ids()
    await message.answer(f"📢 Yuborish boshlandi: {len(ids)} ta foydalanuvchi...")
    asyncio.create_task(_broadcast(bot, message.chat.id, message.message_id, ids))


async def _broadcast(bot: Bot, admin_chat: int, msg_id: int, ids: list[int]) -> None:
    ok = fail = 0
    for uid in ids:
        for _ in range(2):
            try:
                await bot.copy_message(uid, admin_chat, msg_id)
                ok += 1
                break
            except TelegramRetryAfter as e:
                await asyncio.sleep(e.retry_after)
            except TelegramAPIError:
                fail += 1
                break
        await asyncio.sleep(0.05)
    try:
        await bot.send_message(admin_chat, f"📢 Tugadi.\n✅ Yetkazildi: {ok}\n❌ Yetkazilmadi: {fail}")
    except TelegramAPIError:
        log.warning("broadcast hisoboti yuborilmadi")
