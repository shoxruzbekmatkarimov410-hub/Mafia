"""Admin panel: /admin, balans, rol berish, broadcast, statistika, /addadmin, /deladmin."""
import asyncio
import logging
from html import escape

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton as Btn
from aiogram.types import InlineKeyboardMarkup as Kb
from aiogram.types import Message

import config
import database as db
import game as g

log = logging.getLogger("mafia.admin")
router = Router()
PRIVATE = F.chat.type == ChatType.PRIVATE


class AS(StatesGroup):
    balance = State()
    role_target = State()
    broadcast = State()


def admin_kb() -> Kb:
    return Kb(inline_keyboard=[
        [Btn(text="💵 Dollar +/−", callback_data="adm:bal:dollars"),
         Btn(text="💎 Olmos +/−", callback_data="adm:bal:diamonds")],
        [Btn(text="🎭 Rol berish", callback_data="adm:role")],
        [Btn(text="🧾 Buyurtmalar (chek)", callback_data="adm:orders")],
        [Btn(text="📢 Broadcast", callback_data="adm:bc")],
        [Btn(text="📊 Statistika", callback_data="adm:stats"),
         Btn(text="👑 Adminlar", callback_data="adm:list")],
    ])


BACK = Kb(inline_keyboard=[[Btn(text="⬅️ Admin panel", callback_data="adm:menu")]])


@router.message(Command("admin"), PRIVATE)
async def cmd_admin(message: Message, state: FSMContext) -> None:
    if not await db.is_admin(message.from_user.id):
        return
    await state.clear()
    await message.answer("👑 <b>Admin panel</b>", reply_markup=admin_kb())


@router.callback_query(F.data.startswith("adm:"))
async def cb_admin(call: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    if not await db.is_admin(call.from_user.id):
        await call.answer("Ruxsat yo'q.", show_alert=True)
        return
    action = call.data.split(":")[1]
    if action == "menu":
        await state.clear()
        await call.message.edit_text("👑 <b>Admin panel</b>", reply_markup=admin_kb())
    elif action == "bal":
        cur = call.data.split(":")[2]
        await state.set_state(AS.balance)
        await state.update_data(cur=cur)
        sym = "💵 dollar" if cur == "dollars" else "💎 olmos"
        await call.message.edit_text(
            f"{sym}: yuboring <code>ID_yoki_@username miqdor</code>\n"
            "Masalan: <code>@ali 50</code> (qo'shadi) yoki <code>123456 -20</code> (ayiradi)", reply_markup=BACK)
    elif action == "role":
        await state.set_state(AS.role_target)
        await call.message.edit_text("🎭 Rol beriladigan o'yinchining ID yoki @username ini yuboring:",
                                     reply_markup=BACK)
    elif action == "setrole":
        data = await state.get_data()
        target, code = data.get("target"), call.data.split(":")[2]
        if not target:
            await call.answer("Avval o'yinchini tanlang.", show_alert=True)
            return
        role = None if code == "none" else code
        if role and role not in g.ROLE_INFO:
            await call.answer()
            return
        await db.set_next_role(target, role)
        await state.clear()
        await call.message.edit_text(
            "✅ Rol olib tashlandi." if role is None else f"✅ Keyingi o'yin uchun rol: {g.role_label(role)}",
            reply_markup=BACK)
    elif action == "orders":
        from handlers_pay import send_pending
        await send_pending(bot, call.message.chat.id)
    elif action == "bc":
        await state.set_state(AS.broadcast)
        await call.message.edit_text("📢 Barcha foydalanuvchilarga yuboriladigan xabarni yuboring "
                                     "(matn, rasm, video — nima bo'lsa).\nBekor qilish: /cancel", reply_markup=BACK)
    elif action == "stats":
        s = await db.get_stats()
        await call.message.edit_text(
            "📊 <b>Statistika</b>\n\n"
            f"👥 Foydalanuvchilar: {s['users']}\n🎮 Hozir faol o'yinlar: {len(g.GAMES)}\n"
            f"🏁 Tugagan o'yinlar: {s['total_games']}\n👑 Adminlar: {s['admins']}\n"
            f"🎲 Premium guruhlar: {s['premium']}\n🧾 Kutilayotgan buyurtmalar: {s['pending_orders']}", reply_markup=BACK)
    elif action == "list":
        ids = await db.list_admins()
        text = "\n".join(f"• <code>{i}</code>" + (" (ega)" if i in config.OWNER_IDS else "") for i in ids)
        await call.message.edit_text(f"👑 <b>Adminlar</b>\n\n{text or '—'}\n\n"
                                     "Qo'shish/o'chirish (faqat ega): /addadmin, /deladmin", reply_markup=BACK)
    await call.answer()


@router.message(AS.balance, F.text)
async def as_balance(message: Message, state: FSMContext, bot: Bot) -> None:
    if not await db.is_admin(message.from_user.id):
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
    try:
        await bot.send_message(user["user_id"], f"{sym} Balansingiz admin tomonidan {amount:+d} ga o'zgartirildi.")
    except TelegramAPIError:
        pass


@router.message(AS.role_target, F.text)
async def as_role_target(message: Message, state: FSMContext) -> None:
    if not await db.is_admin(message.from_user.id):
        return
    user = await db.find_user(message.text)
    if not user:
        await message.answer("❌ Foydalanuvchi topilmadi.")
        return
    await state.update_data(target=user["user_id"])
    rows = [[Btn(text=g.role_label(code), callback_data=f"adm:setrole:{code}")] for code in g.ROLE_INFO
            if code != "civilian"]
    rows.append([Btn(text="❌ Rolni olib tashlash", callback_data="adm:setrole:none")])
    await message.answer(f"👤 {escape(user['full_name'] or '')} uchun rolni tanlang:",
                         reply_markup=Kb(inline_keyboard=rows))


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


async def _resolve_id(arg: str) -> int | None:
    arg = (arg or "").strip()
    if arg.lstrip("-").isdigit():
        return int(arg)
    user = await db.find_user(arg)
    return user["user_id"] if user else None


@router.message(Command("addadmin"))
async def cmd_addadmin(message: Message, command: CommandObject) -> None:
    if message.from_user.id not in config.OWNER_IDS:
        return
    uid = await _resolve_id(command.args)
    if uid is None:
        await message.reply("Foydalanish: <code>/addadmin ID_yoki_@username</code>")
        return
    await db.add_admin(uid, message.from_user.id)
    await message.reply(f"✅ <code>{uid}</code> admin qilindi.")


@router.message(Command("deladmin"))
async def cmd_deladmin(message: Message, command: CommandObject) -> None:
    if message.from_user.id not in config.OWNER_IDS:
        return
    uid = await _resolve_id(command.args)
    if uid is None:
        await message.reply("Foydalanish: <code>/deladmin ID_yoki_@username</code>")
        return
    if uid in config.OWNER_IDS:
        await message.reply("❌ Egani o'chirib bo'lmaydi.")
        return
    await message.reply("✅ Admin o'chirildi." if await db.del_admin(uid) else "ℹ️ Bunday admin yo'q.")
