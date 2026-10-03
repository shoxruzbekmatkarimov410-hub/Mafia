"""Olmos sotib olish: miqdorni tanlash (➖/➕), kartaga o'tkazma, chek yuborish, admin tasdig'i."""
import logging
from html import escape

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton as Btn
from aiogram.types import InlineKeyboardMarkup as Kb
from aiogram.types import Message

import config
import database as db

log = logging.getLogger("mafia.pay")
router = Router()

MAX_QTY = 1000      # bir buyurtmada eng ko'pi
MAX_PENDING = 3     # bir foydalanuvchining kutilayotgan buyurtmalari


class PS(StatesGroup):
    receipt = State()


# ---------- Narx hisoblash ----------
def _build_prices() -> list[float]:
    """Har bir miqdor uchun eng arzon narx: paketlar (1, 5, 10, ...) kombinatsiyasidan.
    Ko'p olmos hech qachon arzonroq bo'lib qolmasligi uchun narx keyingi miqdorlardan oshmaydi."""
    top = MAX_QTY + max(q for q, _ in config.DIAMOND_PACKS)
    best = [0.0] + [float("inf")] * top
    for n in range(1, top + 1):
        for qty, price in config.DIAMOND_PACKS:
            if qty <= n and best[n - qty] + price < best[n]:
                best[n] = best[n - qty] + price
    for n in range(top - 1, 0, -1):
        best[n] = min(best[n], best[n + 1])
    return best


_PRICES = _build_prices()


def price_for(n: int) -> int:
    return int(_PRICES[n])


def _som(n: int) -> str:
    return f"{n:,}".replace(",", " ")


BACK = Kb(inline_keyboard=[[Btn(text="⬅️ Orqaga", callback_data="menu")]])


def is_staff(uid: int) -> bool:
    return uid in config.OWNER_IDS


# ---------- 1) Paket / miqdor tanlash ----------
@router.callback_query(F.data == "buy_dia")
async def cb_buy_dia(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    if not config.PAY_CARD:
        await call.message.edit_text(
            f"💎 <b>Olmos sotib olish</b>\n\nTo'lov uchun {config.ADMIN_CONTACT} ga murojaat qiling.",
            reply_markup=BACK)
        await call.answer()
        return
    rows = [[Btn(text=f"💎 {q} ta — {_som(p)} so'm", callback_data=f"q:{q}")]
            for q, p in config.DIAMOND_PACKS]
    rows.append([Btn(text="⬅️ Orqaga", callback_data="menu")])
    try:
        await call.message.edit_text(
            "💎 <b>Olmos sotib olish</b>\n\nOlmos faqat pulga sotib olinadi (o'yinda dollar yutasiz).\n"
            "Paketni tanlang, keyin ➖ ➕ bilan xohlagan miqdorni belgilang:",
            reply_markup=Kb(inline_keyboard=rows))
    except TelegramBadRequest:
        pass
    await call.answer()


def _counter(n: int) -> tuple[str, Kb]:
    text = (f"💎 <b>Olmos miqdori: {n}</b>\n💵 Narxi: <b>{_som(price_for(n))} so'm</b>\n\n"
            "➖ ➕ tugmalari bilan miqdorni o'zgartiring.")
    kb = Kb(inline_keyboard=[
        [Btn(text="➖", callback_data=f"q:{max(1, n - 1)}"),
         Btn(text=f"💎 {n}", callback_data="noop"),
         Btn(text="➕", callback_data=f"q:{min(MAX_QTY, n + 1)}")],
        [Btn(text="−10", callback_data=f"q:{max(1, n - 10)}"),
         Btn(text="+10", callback_data=f"q:{min(MAX_QTY, n + 10)}")],
        [Btn(text=f"✅ Davom etish — {_som(price_for(n))} so'm", callback_data=f"qok:{n}")],
        [Btn(text="⬅️ Orqaga", callback_data="buy_dia")],
    ])
    return text, kb


@router.callback_query(F.data.startswith("q:"))
async def cb_qty(call: CallbackQuery) -> None:
    n = min(MAX_QTY, max(1, int(call.data.split(":")[1])))
    text, kb = _counter(n)
    try:
        await call.message.edit_text(text, reply_markup=kb)
    except TelegramBadRequest:
        pass
    await call.answer()


@router.callback_query(F.data == "noop")
async def cb_noop(call: CallbackQuery) -> None:
    await call.answer()


# ---------- 2) To'lov ko'rsatmasi va chek ----------
@router.callback_query(F.data.startswith("qok:"))
async def cb_qty_ok(call: CallbackQuery, state: FSMContext) -> None:
    n = min(MAX_QTY, max(1, int(call.data.split(":")[1])))
    if not config.PAY_CARD:
        await call.answer("To'lov hozircha yopiq.", show_alert=True)
        return
    if await db.count_pending_orders(call.from_user.id) >= MAX_PENDING:
        await call.answer("Sizda tasdiq kutayotgan buyurtmalar ko'p. Avval ularni kuting.", show_alert=True)
        return
    await state.set_state(PS.receipt)
    await state.update_data(n=n)
    owner = f"\n👤 Karta egasi: {escape(config.PAY_CARD_OWNER)}" if config.PAY_CARD_OWNER else ""
    try:
        await call.message.edit_text(
            f"💳 <b>To'lov</b>\n\n💎 {n} ta olmos — <b>{_som(price_for(n))} so'm</b>\n\n"
            f"Shu kartaga aynan shu summani o'tkazing:\n<code>{escape(config.PAY_CARD)}</code>{owner}\n\n"
            "O'tkazgach, <b>chek rasmini (screenshot)</b> shu yerga yuboring. "
            "Admin tekshirib tasdiqlagach olmos hisobingizga tushadi.\n\nBekor qilish: /cancel",
            reply_markup=Kb(inline_keyboard=[[Btn(text="⬅️ Orqaga", callback_data=f"q:{n}")]]))
    except TelegramBadRequest:
        pass
    await call.answer()


def _order_caption(order: dict, user: dict | None) -> str:
    name = escape((user or {}).get("full_name") or str(order["user_id"]))
    uname = f" @{escape(user['username'])}" if user and user.get("username") else ""
    return (f"🧾 <b>Buyurtma #{order['order_id']}</b>\n"
            f"👤 {name}{uname} (<code>{order['user_id']}</code>)\n"
            f"💎 {order['diamonds']} ta — <b>{_som(order['amount'])} so'm</b>\n\n"
            "Kartaga shu summa tushganini tekshiring!")


def _order_kb(order_id: int) -> Kb:
    return Kb(inline_keyboard=[[Btn(text="✅ Tasdiqlash", callback_data=f"ord:ok:{order_id}"),
                                Btn(text="❌ Rad etish", callback_data=f"ord:no:{order_id}")]])


async def _send_order(bot: Bot, chat_id: int, order: dict, user: dict | None) -> bool:
    caption, kb = _order_caption(order, user), _order_kb(order["order_id"])
    try:
        if order["file_kind"] == "document":
            await bot.send_document(chat_id, order["file_id"], caption=caption, reply_markup=kb)
        else:
            await bot.send_photo(chat_id, order["file_id"], caption=caption, reply_markup=kb)
        return True
    except TelegramAPIError as e:
        log.warning("adminga (%s) yuborib bo'lmadi: %s", chat_id, e)
        return False


async def _staff_ids() -> set[int]:
    return set(await db.list_admins()) | set(config.OWNER_IDS)


async def is_staff_user(uid: int) -> bool:
    return uid in config.OWNER_IDS or await db.is_admin(uid)


async def notify_owners(bot: Bot, text: str) -> None:
    """Egalarga ogohlantirish (adminlar faoliyati uchun)."""
    for oid in config.OWNER_IDS:
        try:
            await bot.send_message(oid, text)
        except TelegramAPIError:
            pass


@router.message(PS.receipt, F.photo | F.document)
async def got_receipt(message: Message, state: FSMContext, bot: Bot) -> None:
    n = (await state.get_data()).get("n")
    if not n:
        await state.clear()
        return
    if message.photo:
        f = message.photo[-1]
        file_id, unique_id, kind = f.file_id, f.file_unique_id, "photo"
    else:
        d = message.document
        if not (d.mime_type or "").startswith("image/"):
            await message.answer("❌ Chekni rasm (screenshot) ko'rinishida yuboring.")
            return
        file_id, unique_id, kind = d.file_id, d.file_unique_id, "document"
    u = message.from_user
    await db.get_or_create_user(u.id, u.username, u.full_name)
    order_id = await db.create_order(u.id, n, price_for(n), file_id, unique_id, kind)
    if order_id is None:
        await message.answer("❌ Bu chek avval yuborilgan. Yangi to'lov chekini yuboring.")
        return
    await state.clear()
    order = {"order_id": order_id, "user_id": u.id, "diamonds": n, "amount": price_for(n),
             "file_id": file_id, "file_kind": kind}
    user = await db.get_user(u.id)
    buyer_is_staff = await is_staff_user(u.id)
    # Admin o'zi uchun olmos olsa, buyurtmani faqat EGA ko'radi va tasdiqlaydi.
    recipients = set(config.OWNER_IDS) if buyer_is_staff else await _staff_ids()
    delivered = 0
    for admin_id in recipients:
        if await _send_order(bot, admin_id, order, user):
            delivered += 1
    if delivered:
        extra = "\nAdmin buyurtmalarini faqat ega tasdiqlaydi." if buyer_is_staff and u.id not in config.OWNER_IDS else ""
        await message.answer(f"⏳ Chekingiz yuborildi (buyurtma #{order_id}).\n"
                             f"Tasdiqlangach olmos hisobingizga tushadi va sizga xabar keladi.{extra}")
    else:
        await message.answer(f"⚠️ Chek qabul qilindi (#{order_id}), lekin adminga xabar bormadi. "
                             f"Iltimos {config.ADMIN_CONTACT} ga yozing.")


@router.message(PS.receipt, F.text, ~F.text.startswith("/"))
async def receipt_text(message: Message) -> None:
    await message.answer("📸 Iltimos, to'lov chekining <b>rasmini</b> yuboring. Bekor qilish: /cancel")


# ---------- 3) Admin tasdig'i ----------
@router.callback_query(F.data.startswith("ord:"))
async def cb_order(call: CallbackQuery, bot: Bot) -> None:
    uid = call.from_user.id
    if not (is_staff(uid) or await db.is_admin(uid)):
        await call.answer("Ruxsat yo'q.", show_alert=True)
        return
    _, act, oid = call.data.split(":")
    approve = act == "ok"
    pre = await db.get_order(int(oid))
    if pre and uid not in config.OWNER_IDS and await is_staff_user(pre["user_id"]):
        await call.answer("Admin buyurtmasini faqat ega tasdiqlaydi.", show_alert=True)
        return
    order = await db.decide_order(int(oid), uid, approve)
    if order is None:
        await call.answer("Bu buyurtma allaqachon ko'rib chiqilgan.", show_alert=True)
        try:
            await call.message.edit_reply_markup(reply_markup=None)
        except TelegramAPIError:
            pass
        return
    mark = "✅ Tasdiqlandi" if approve else "❌ Rad etildi"
    try:
        await call.message.edit_caption(
            caption=f"{call.message.html_text or ''}\n\n<b>{mark}</b> — {escape(call.from_user.full_name)}",
            reply_markup=None)
    except TelegramAPIError:
        pass
    try:
        if approve:
            await bot.send_message(order["user_id"],
                                   f"✅ To'lovingiz tasdiqlandi!\n💎 +{order['diamonds']} olmos hisobingizga qo'shildi.")
        else:
            await bot.send_message(order["user_id"],
                                   f"❌ Buyurtma #{order['order_id']} rad etildi. Savol bo'lsa "
                                   f"{config.ADMIN_CONTACT} ga yozing.")
    except TelegramAPIError:
        pass
    if uid not in config.OWNER_IDS:
        buyer = await db.get_user(order["user_id"])
        await notify_owners(
            bot, f"{'✅' if approve else '❌'} Admin {escape(call.from_user.full_name)} ({uid}) "
                 f"buyurtma #{order['order_id']} ni {'tasdiqladi' if approve else 'rad etdi'}: "
                 f"{escape((buyer or {}).get('full_name') or str(order['user_id']))} ({order['user_id']}), "
                 f"💎{order['diamonds']}, {_som(order['amount'])} so'm")
    await call.answer("Bajarildi.")


async def send_pending(bot: Bot, chat_id: int, viewer_id: int | None = None) -> None:
    """Kutilayotgan buyurtmalarni adminga qayta yuboradi.
    Adminlarning o'z buyurtmalarini faqat ega ko'ra oladi."""
    viewer = viewer_id or chat_id
    orders = await db.pending_orders(40)
    if viewer not in config.OWNER_IDS:
        staff = await _staff_ids()
        orders = [o for o in orders if o["user_id"] not in staff]
    if not orders:
        await bot.send_message(chat_id, "🧾 Kutilayotgan buyurtmalar yo'q.")
        return
    for o in orders:
        await _send_order(bot, chat_id, o, await db.get_user(o["user_id"]))


@router.message(Command("orders"))
async def cmd_orders(message: Message, bot: Bot) -> None:
    uid = message.from_user.id
    if not (is_staff(uid) or await db.is_admin(uid)):
        return
    await send_pending(bot, message.chat.id, uid)


@router.message(Command("paysupport"))
async def cmd_paysupport(message: Message) -> None:
    await message.answer(f"💳 To'lov bo'yicha savollar uchun {config.ADMIN_CONTACT} ga yozing. "
                         "Buyurtma raqamini yuboring.")
