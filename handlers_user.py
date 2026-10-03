"""Foydalanuvchi bo'limi: /start, profil, do'kon, o'tkazma, TOP, nikoh, yordam."""
from html import escape

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton as Btn
from aiogram.types import InlineKeyboardMarkup as Kb
from aiogram.types import Message

import config
import database as db
import game as g

router = Router()
PRIVATE = F.chat.type == ChatType.PRIVATE

# ---------- Matnlar (menyu va profil: uz / ru) ----------
TEXTS = {
    "uz": {
        "welcome": "🐺 <b>MAFIA</b> o'yiniga xush kelibsiz, {name}!\n\n"
                   "Guruhda o'ynang, pul va olmos yig'ing, do'kondan imtiyozlar oling.\n"
                   "O'yinni boshlash uchun meni guruhga qo'shing va <code>/game</code> yozing.",
        "group_hint": "🐺 Men Mafia botiman. O'yin uchun /game, profil va do'kon uchun menga shaxsiy xabarda /start yozing.",
        "profile": "🆔 ID: <code>{id}</code>\n👤 <b>{name}</b>\n\n"
                   "💵 Dollar: {dollars}\n💎 Olmos: {diamonds}\n\n"
                   "🛡 Himoya: {shield}\n⛑ Qotildan himoya: {killer_shield}\n"
                   "⚖️ Ovoz berishni himoya qilish: {vote_shield}\n🔫 Miltiq: {gun}\n\n"
                   "🎭 Maska: {mask}\n📁 Hujjatlar: {docs}\n"
                   "🃏 Keyingi o'yindagi rolingiz: {role}\n{love}\n"
                   "🏆 G'alabalar: {wins}\n🎲 Jami o'yinlar: {games}",
        "married": "💍 Juftingiz: {name}",
        "choose_lang": "🌐 Tilni tanlang:",
        "lang_set": "✅ Til o'zgartirildi.",
        "b_profile": "👤 Profil", "b_shop": "🛒 Do'kon", "b_transfer": "💸 O'tkazma",
        "b_buy_usd": "Xarid qilish 💵", "b_buy_diamond": "Xarid qilish 💎",
        "b_premium": "🎲 Premium guruhlar", "b_news": "📰 Yangiliklar",
        "b_topgroups": "⭐ Top guruhlar", "b_addgroup": "➕ Guruhga qo'shish",
        "b_top": "🏆 TOP", "b_lang": "🌐 Til", "b_back": "⬅️ Orqaga",
    },
    "ru": {
        "welcome": "🐺 Добро пожаловать в игру <b>МАФИЯ</b>, {name}!\n\n"
                   "Играйте в группе, копите деньги и алмазы, покупайте привилегии в магазине.\n"
                   "Чтобы начать игру, добавьте меня в группу и напишите <code>/game</code>.",
        "group_hint": "🐺 Я бот Мафия. Для игры — /game, для профиля и магазина напишите мне в личные сообщения /start.",
        "profile": "🆔 ID: <code>{id}</code>\n👤 <b>{name}</b>\n\n"
                  "💵 Доллары: {dollars}\n💎 Алмазы: {diamonds}\n\n"
                  "🛡 Защита: {shield}\n⛑ Защита от убийцы: {killer_shield}\n"
                  "⚖️ Защита при голосовании: {vote_shield}\n🔫 Ружьё: {gun}\n\n"
                  "🎭 Маска: {mask}\n📁 Документы: {docs}\n"
                  "🃏 Роль в следующей игре: {role}\n{love}\n"
                  "🏆 Побед: {wins}\n🎲 Всего игр: {games}",
        "married": "💍 Ваша пара: {name}",
        "choose_lang": "🌐 Выберите язык:",
        "lang_set": "✅ Язык изменён.",
        "b_profile": "👤 Профиль", "b_shop": "🛒 Магазин", "b_transfer": "💸 Перевод",
        "b_buy_usd": "Купить 💵", "b_buy_diamond": "Купить 💎",
        "b_premium": "🎲 Премиум группы", "b_news": "📰 Новости",
        "b_topgroups": "⭐ Топ группы", "b_addgroup": "➕ Добавить в группу",
        "b_top": "🏆 ТОП", "b_lang": "🌐 Язык", "b_back": "⬅️ Назад",
    },
}


def t(lang: str, key: str, **kw) -> str:
    text = TEXTS.get(lang, TEXTS["uz"])[key]
    return text.format(**kw) if kw else text


def add_to_group_url() -> str:
    # admin huquqlarini ham taklif qiladi: xabarni qadash va o'chirish (ro'yxat xabari uchun kerak)
    return f"https://t.me/{config.BOT_USERNAME}?startgroup=true&admin=pin_messages+delete_messages"


def main_menu(lang: str) -> Kb:
    rows = []
    if config.BOT_USERNAME:
        rows.append([Btn(text=t(lang, "b_addgroup"), url=add_to_group_url())])
    rows += [
        [Btn(text=t(lang, "b_profile"), callback_data="profile"),
         Btn(text=t(lang, "b_shop"), callback_data="shop")],
        [Btn(text=t(lang, "b_buy_usd"), callback_data="buy_usd"),
         Btn(text=t(lang, "b_buy_diamond"), callback_data="buy_dia")],
        [Btn(text=t(lang, "b_transfer"), callback_data="transfer"),
         Btn(text=t(lang, "b_top"), callback_data="top:wins")],
        [Btn(text=t(lang, "b_topgroups"), callback_data="topgroups"),
         Btn(text=t(lang, "b_premium"), callback_data="premium")],
    ]
    if config.NEWS_URL:
        rows.append([Btn(text=t(lang, "b_news"), url=config.NEWS_URL)])
    rows.append([Btn(text=t(lang, "b_lang"), callback_data="lang")])
    return Kb(inline_keyboard=rows)


def back_kb(lang: str = "uz", to: str = "menu") -> Kb:
    return Kb(inline_keyboard=[[Btn(text=t(lang, "b_back"), callback_data=to)]])


async def safe_edit(call: CallbackQuery, text: str, markup: Kb | None = None) -> None:
    try:
        await call.message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest:
        pass


async def reg(u) -> dict:
    return await db.get_or_create_user(u.id, u.username, u.full_name)


async def profile_text(user_id: int) -> tuple[str, str]:
    user = await db.get_user(user_id)
    inv = await db.get_inventory(user_id)
    lang = user["lang"]
    role = g.ROLE_INFO.get(user["next_role"] or "")
    love = ""
    partner_id = await db.get_partner(user_id)
    if partner_id:
        pu = await db.get_user(partner_id)
        love = t(lang, "married", name=escape((pu or {}).get("full_name") or str(partner_id))) + "\n"
    text = t(lang, "profile", id=user_id, name=escape(user["full_name"] or ""),
             dollars=user["dollars"], diamonds=user["diamonds"],
             shield=inv.get("shield", 0), killer_shield=inv.get("killer_shield", 0),
             vote_shield=inv.get("vote_shield", 0), gun=inv.get("gun", 0),
             mask=inv.get("mask", 0), docs=inv.get("docs", 0),
             role=f"{role[0]} {role[1]}" if role else "-", love=love,
             wins=user["wins"], games=user["games_played"])
    return lang, text


# ---------- /start ----------
@router.message(CommandStart(deep_link=True), PRIVATE)
async def cmd_start_deeplink(message: Message, command: CommandObject, state: FSMContext) -> None:
    await state.clear()
    user = await reg(message.from_user)
    arg = command.args or ""
    if not arg.startswith("join_"):
        await message.answer(t(user["lang"], "welcome", name=escape(message.from_user.full_name)),
                             reply_markup=main_menu(user["lang"]))
        return
    try:
        chat_id = int(arg[5:])
    except ValueError:
        return
    game = g.GAMES.get(chat_id)
    if not game or game.status != "lobby":
        await message.answer("❌ Bu guruhda hozir ro'yxatga olish ochiq emas.")
        return
    res = await game.join(message.from_user.id, message.from_user.full_name)
    await message.answer({
        "ok": "✅ Siz o'yinga qo'shildingiz! Guruhga qayting va o'yin boshlanishini kuting.",
        "already": "ℹ️ Siz allaqachon ro'yxatdasiz.",
        "full": "❌ O'yin to'la.",
        "closed": "❌ Ro'yxatga olish yopilgan.",
    }[res])


@router.message(CommandStart(), PRIVATE)
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    user = await reg(message.from_user)
    await message.answer(t(user["lang"], "welcome", name=escape(message.from_user.full_name)),
                         reply_markup=main_menu(user["lang"]))


@router.message(CommandStart())
async def cmd_start_group(message: Message) -> None:
    await message.answer(t("uz", "group_hint"))


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("❌ Bekor qilindi.")


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        "🐺 <b>Buyruqlar</b>\n\n"
        "<b>Guruhda:</b>\n/game — o'yin ochish\n/go — darhol boshlash\n/extend — vaqtni uzaytirish\n"
        "/leave — ro'yxatdan/o'yindan chiqish\n/players — o'yinchilar\n/stop — o'yinni to'xtatish\n"
        "/kick (reply) — o'yinchini chiqarish\n"
        "/giveto &lt;miqdor&gt; [dollar|olmos] — reply qilib pul tashlash\n"
        "/nikoh (reply) — juftlik taklifi, /ajrashish\n\n"
        "<b>Hamma joyda:</b>\n/profile — profil\n/top — reyting\n/roles — rollar ro'yxati\n\n"
        "<b>Shaxsiy xabarda:</b>\n/start — menyu (do'kon, o'tkazma, olmos xaridi, til)\n/paysupport — to'lov yordami\n\n<b>Adminlar:</b> /admin, /orders")


@router.message(Command("roles"))
async def cmd_roles(message: Message) -> None:
    lines = ["🎭 <b>Rollar</b>\n"]
    for code, (e, name, desc) in g.ROLE_INFO.items():
        lines.append(f"{e} <b>{name}</b> — {desc}")
    await message.answer("\n\n".join(lines))


# ---------- Menyu, profil, til ----------
@router.callback_query(F.data == "menu")
async def cb_menu(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    user = await reg(call.from_user)
    await safe_edit(call, t(user["lang"], "welcome", name=escape(call.from_user.full_name)),
                    main_menu(user["lang"]))
    await call.answer()


@router.message(Command("profile"))
async def cmd_profile(message: Message) -> None:
    await reg(message.from_user)
    lang, text = await profile_text(message.from_user.id)
    await message.answer(text)


@router.callback_query(F.data == "profile")
async def cb_profile(call: CallbackQuery) -> None:
    await reg(call.from_user)
    lang, text = await profile_text(call.from_user.id)
    await safe_edit(call, text, back_kb(lang))
    await call.answer()


@router.callback_query(F.data == "lang")
async def cb_lang(call: CallbackQuery) -> None:
    user = await reg(call.from_user)
    lang = user["lang"]
    kb = Kb(inline_keyboard=[
        [Btn(text="🇺🇿 O'zbekcha", callback_data="setlang:uz"),
         Btn(text="🇷🇺 Русский", callback_data="setlang:ru")],
        [Btn(text=t(lang, "b_back"), callback_data="menu")]])
    await safe_edit(call, t(lang, "choose_lang"), kb)
    await call.answer()


@router.callback_query(F.data.startswith("setlang:"))
async def cb_setlang(call: CallbackQuery) -> None:
    lang = call.data.split(":", 1)[1]
    if lang not in TEXTS:
        await call.answer()
        return
    await reg(call.from_user)
    await db.set_lang(call.from_user.id, lang)
    await safe_edit(call, t(lang, "welcome", name=escape(call.from_user.full_name)), main_menu(lang))
    await call.answer(t(lang, "lang_set"))


@router.callback_query(F.data == "buy_usd")
async def cb_buy_usd(call: CallbackQuery) -> None:
    await safe_edit(call, "💵 Dollarni o'yinda g'alaba qozonib yig'asiz.\n\n"
                          f"Boshqa savollar uchun {config.ADMIN_CONTACT} ga murojaat qiling.", back_kb())
    await call.answer()


@router.callback_query(F.data == "premium")
async def cb_premium(call: CallbackQuery) -> None:
    await safe_edit(
        call,
        "🎲 <b>Premium guruhlar</b>\n\nPremium guruhda g'oliblar mukofoti ikki barobar (×2).\n"
        f"Guruhingizni premium qilish uchun {config.ADMIN_CONTACT} ga murojaat qiling.", back_kb())
    await call.answer()


@router.callback_query(F.data == "topgroups")
async def cb_topgroups(call: CallbackQuery) -> None:
    user = await reg(call.from_user)
    lang = user["lang"]
    ads = await db.list_ads(40)
    rows = [[Btn(text=f"👥 {a['title'][:40]}", url=a["url"])] for a in ads]
    if config.BOT_USERNAME:
        rows.append([Btn(text=t(lang, "b_addgroup"), url=add_to_group_url())])
    rows.append([Btn(text=t(lang, "b_back"), callback_data="menu")])
    text = ("⭐ <b>Top guruhlar</b>\n\nQuyidagi guruhlardan birini bosing va o'yinga qo'shiling 👇" if ads
            else "⭐ <b>Top guruhlar</b>\n\nHozircha guruhlar yo'q. Tez orada qo'shiladi!")
    await safe_edit(call, text, Kb(inline_keyboard=rows))
    await call.answer()


# ---------- Do'kon ----------
async def shop_view() -> tuple[str, Kb]:
    items = await db.list_shop()
    lines = ["🛒 <b>Do'kon</b>\n"]
    rows = []
    for it in items:
        sym = "💵" if it["currency"] == "dollars" else "💎"
        lines.append(f"{it['name']} — {it['description']}")
        rows.append([Btn(text=f"{it['name']} - {sym} {it['price']}", callback_data=f"buy:{it['item_id']}")])
    lines.append("\n🃏 <b>Rol</b>\nOldindan rol sotib olib, keyingi o'yinda shu rol bilan o'ynashingiz mumkin.")
    rows.append([Btn(text="🃏 Rol sotib olish", callback_data="roles")])
    rows.append([Btn(text="🎴 Faol rol", callback_data="myrole")])
    rows.append([Btn(text="⬅️ Orqaga", callback_data="menu")])
    return "\n".join(lines), Kb(inline_keyboard=rows)


@router.callback_query(F.data == "shop")
async def cb_shop(call: CallbackQuery) -> None:
    await reg(call.from_user)
    text, kb = await shop_view()
    await safe_edit(call, text, kb)
    await call.answer()


@router.callback_query(F.data.startswith("buy:"))
async def cb_buy(call: CallbackQuery) -> None:
    await reg(call.from_user)
    res = await db.buy_item(call.from_user.id, int(call.data.split(":")[1]))
    msg = {"ok": "✅ Sotib olindi!", "ok_reset": "✅ Statistika tiklandi.",
           "not_enough": "❌ Balansingiz yetarli emas.", "no_item": "❌ Mahsulot topilmadi."}[res]
    await call.answer(msg, show_alert=True)


@router.callback_query(F.data == "roles")
async def cb_roles(call: CallbackQuery) -> None:
    rows = [[Btn(text=f"{g.role_label(code)} — 💎 {price}", callback_data=f"role:{code}")]
            for code, price in g.ROLE_PRICES.items()]
    rows.append([Btn(text="⬅️ Orqaga", callback_data="shop")])
    await safe_edit(call, "🃏 <b>Rol sotib olish</b>\nSotib olingan rol keyingi o'yinda beriladi "
                          "(agar o'yinda shu rolga joy bo'lsa).", Kb(inline_keyboard=rows))
    await call.answer()


@router.callback_query(F.data.startswith("role:"))
async def cb_role_buy(call: CallbackQuery) -> None:
    await reg(call.from_user)
    code = call.data.split(":")[1]
    if code not in g.ROLE_PRICES:
        await call.answer()
        return
    res = await db.buy_role(call.from_user.id, code, g.ROLE_PRICES[code])
    msg = {"ok": f"✅ Keyingi o'yinda rolingiz: {g.role_label(code)}",
           "has_role": "ℹ️ Sizda faol rol bor. Avval undan foydalaning.",
           "not_enough": "❌ Olmosingiz yetarli emas."}[res]
    await call.answer(msg, show_alert=True)


@router.callback_query(F.data == "myrole")
async def cb_myrole(call: CallbackQuery) -> None:
    user = await reg(call.from_user)
    role = user["next_role"]
    await call.answer(f"Faol rol: {g.role_label(role)}" if role in g.ROLE_INFO else "Faol rol yo'q.",
                      show_alert=True)


# ---------- O'tkazma (shaxsiy xabarda) ----------
class TS(StatesGroup):
    target = State()
    currency = State()
    amount = State()


TRANSFER_ERR = {
    "bad_amount": "❌ Miqdor noto'g'ri.", "self_transfer": "❌ O'zingizga o'tkaza olmaysiz.",
    "no_receiver": "❌ Qabul qiluvchi topilmadi.", "not_enough": "❌ Balansingiz yetarli emas.",
}


@router.callback_query(F.data == "transfer")
async def cb_transfer(call: CallbackQuery, state: FSMContext) -> None:
    await reg(call.from_user)
    await state.set_state(TS.target)
    await safe_edit(call, "💸 <b>O'tkazma</b>\n\nQabul qiluvchining ID raqami yoki @username ini yuboring.\n"
                          "(U botni ishga tushirgan bo'lishi kerak. Bekor qilish: /cancel)",
                    back_kb())
    await call.answer()


@router.message(TS.target, F.text)
async def ts_target(message: Message, state: FSMContext) -> None:
    user = await db.find_user(message.text)
    if not user:
        await message.answer("❌ Foydalanuvchi topilmadi. ID yoki @username ni tekshiring.")
        return
    if user["user_id"] == message.from_user.id:
        await message.answer("❌ O'zingizga o'tkaza olmaysiz.")
        return
    await state.update_data(to=user["user_id"], to_name=user["full_name"] or str(user["user_id"]))
    await state.set_state(TS.currency)
    kb = Kb(inline_keyboard=[[Btn(text="💵 Dollar", callback_data="tcur:dollars"),
                              Btn(text="💎 Olmos", callback_data="tcur:diamonds")]])
    await message.answer(f"Qabul qiluvchi: <b>{escape(user['full_name'] or '')}</b>\nQaysi valyuta?", reply_markup=kb)


@router.callback_query(TS.currency, F.data.startswith("tcur:"))
async def ts_currency(call: CallbackQuery, state: FSMContext) -> None:
    cur = call.data.split(":")[1]
    if cur not in db.CURRENCIES:
        await call.answer()
        return
    await state.update_data(cur=cur)
    await state.set_state(TS.amount)
    await safe_edit(call, "Miqdorni yuboring (butun son):")
    await call.answer()


@router.message(TS.amount, F.text)
async def ts_amount(message: Message, state: FSMContext, bot: Bot) -> None:
    if not message.text.strip().isdigit():
        await message.answer("❌ Faqat musbat butun son yuboring.")
        return
    amount = int(message.text.strip())
    data = await state.get_data()
    await state.clear()
    res = await db.transfer(message.from_user.id, data["to"], data["cur"], amount)
    if res != "ok":
        await message.answer(TRANSFER_ERR[res])
        return
    sym = "💵" if data["cur"] == "dollars" else "💎"
    await message.answer(f"✅ {escape(data['to_name'])} ga {sym} {amount} o'tkazildi.")
    try:
        await bot.send_message(data["to"], f"🎁 {escape(message.from_user.full_name)} sizga {sym} {amount} yubordi!")
    except TelegramAPIError:
        pass


# ---------- Guruhda pul tashlash: /send (reply) ----------
@router.message(Command("send", "giveto"))
async def cmd_send(message: Message, command: CommandObject) -> None:
    rep = message.reply_to_message
    if not rep or not rep.from_user or rep.from_user.is_bot:
        await message.reply("ℹ️ Foydalanuvchi xabariga reply qilib yozing: <code>/send 100</code> yoki "
                            "<code>/send 5 olmos</code>")
        return
    args = (command.args or "").lower().split()
    if not args or not args[0].isdigit():
        await message.reply("❌ Miqdorni yozing: <code>/send 100</code>")
        return
    cur = "diamonds" if len(args) > 1 and args[1] in ("olmos", "diamond", "💎", "almaz") else "dollars"
    await reg(message.from_user)
    await reg(rep.from_user)
    res = await db.transfer(message.from_user.id, rep.from_user.id, cur, int(args[0]))
    if res != "ok":
        await message.reply(TRANSFER_ERR[res])
        return
    sym = "💵" if cur == "dollars" else "💎"
    a, b = message.from_user, rep.from_user
    give = f'<a href="tg://user?id={a.id}">{escape(a.full_name)}</a>'
    take = f'<a href="tg://user?id={b.id}">{escape(b.full_name)}</a>'
    await message.answer(f"{sym} {give} — {take} ga {int(args[0])} {sym} berdi")


# ---------- TOP ----------
TOP_LABELS = {"wins": "🏆 G'alabalar", "diamonds": "💎 Olmos", "dollars": "💵 Dollar"}


async def top_view(kind: str, back: bool) -> tuple[str, Kb]:
    rows = await db.top_users(kind, 10)
    medals = ["🥇", "🥈", "🥉"]
    lines = [f"🏆 <b>TOP 10 — {TOP_LABELS[kind]}</b>\n"]
    for i, r in enumerate(rows):
        mark = medals[i] if i < 3 else f"{i + 1}."
        lines.append(f"{mark} {escape(r['full_name'] or str(r['user_id']))} — {r['score']}")
    if not rows:
        lines.append("Hozircha ma'lumot yo'q.")
    kb_rows = [[Btn(text=lbl, callback_data=f"top:{k}") for k, lbl in TOP_LABELS.items() if k != kind]]
    if back:
        kb_rows.append([Btn(text="⬅️ Orqaga", callback_data="menu")])
    return "\n".join(lines), Kb(inline_keyboard=kb_rows)


@router.message(Command("top"))
async def cmd_top(message: Message) -> None:
    text, kb = await top_view("wins", back=False)
    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data.startswith("top:"))
async def cb_top(call: CallbackQuery) -> None:
    kind = call.data.split(":")[1]
    if kind not in TOP_LABELS:
        await call.answer()
        return
    is_private = call.message.chat.type == ChatType.PRIVATE
    text, kb = await top_view(kind, back=is_private)
    await safe_edit(call, text, kb)
    await call.answer()


# ---------- Nikoh ----------
@router.message(Command("nikoh"))
async def cmd_nikoh(message: Message) -> None:
    rep = message.reply_to_message
    a = message.from_user
    if not rep or not rep.from_user or rep.from_user.is_bot or rep.from_user.id == a.id:
        await message.reply("💍 Juftlik taklifi uchun kimningdir xabariga reply qilib /nikoh yozing.")
        return
    b = rep.from_user
    await reg(a)
    await reg(b)
    if await db.get_partner(a.id) or await db.get_partner(b.id):
        await message.reply("❌ Ikkalangizdan biri allaqachon juftlikda.")
        return
    kb = Kb(inline_keyboard=[[Btn(text="💍 Ha", callback_data=f"mar:y:{a.id}:{b.id}"),
                              Btn(text="💔 Yo'q", callback_data=f"mar:n:{a.id}:{b.id}")]])
    await message.answer(f"💍 {escape(b.full_name)}, {escape(a.full_name)} sizga juftlik taklif qilmoqda!",
                         reply_markup=kb)


@router.callback_query(F.data.startswith("mar:"))
async def cb_marry(call: CallbackQuery) -> None:
    _, ans, a, b = call.data.split(":")
    if call.from_user.id != int(b):
        await call.answer("Bu taklif sizga emas.", show_alert=True)
        return
    if ans == "n":
        await safe_edit(call, "💔 Taklif rad etildi.")
        await call.answer()
        return
    ok = await db.marry(int(a), int(b))
    await safe_edit(call, "💞 Tabriklaymiz! Endi siz juftlik bo'ldingiz. Ikkalangiz ham bitta o'yinda "
                          f"yutsangiz +{g.MARRIAGE_BONUS}$ bonus olasiz." if ok else "❌ Nikoh amalga oshmadi.")
    await call.answer()


@router.message(Command("ajrashish"))
async def cmd_divorce(message: Message) -> None:
    partner = await db.divorce(message.from_user.id)
    await message.reply("💔 Ajrashdingiz." if partner else "ℹ️ Siz juftlikda emassiz.")
