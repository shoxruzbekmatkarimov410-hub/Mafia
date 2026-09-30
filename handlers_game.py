"""Guruhdagi o'yin buyruqlari va tun/ovoz callback'lari."""
import asyncio

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

import database as db
import game as g

router = Router()
GROUP = F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP})


async def can_manage(bot: Bot, game: g.Game, uid: int) -> bool:
    """O'yin ochgan, guruh admini yoki bot admini."""
    if uid == game.creator_id or await db.is_admin(uid):
        return True
    try:
        member = await bot.get_chat_member(game.chat_id, uid)
        return member.status in ("creator", "administrator")
    except TelegramAPIError:
        return False


@router.message(Command("game"), GROUP)
async def cmd_game(message: Message, bot: Bot) -> None:
    chat_id = message.chat.id
    if chat_id in g.GAMES:
        await message.reply("⚠️ Bu guruhda o'yin allaqachon bor.")
        return
    u = message.from_user
    await db.get_or_create_user(u.id, u.username, u.full_name)
    me = await bot.get_me()
    game = g.Game(bot, chat_id, u.id, me.username)
    g.GAMES[chat_id] = game
    await game.open_lobby()
    game.task = asyncio.create_task(game.run())


@router.message(Command("go"), GROUP)
async def cmd_go(message: Message, bot: Bot) -> None:
    game = g.GAMES.get(message.chat.id)
    if not game or game.status != "lobby":
        await message.reply("ℹ️ Ro'yxatga olish ochiq emas.")
        return
    if not await can_manage(bot, game, message.from_user.id):
        await message.reply("❌ Faqat o'yin ochgan yoki guruh admini boshlay oladi.")
        return
    if len(game.players) < g.MIN_PLAYERS:
        await message.reply(f"❌ Kamida {g.MIN_PLAYERS} o'yinchi kerak.")
        return
    game.force_start = True


@router.message(Command("extend"), GROUP)
async def cmd_extend(message: Message) -> None:
    game = g.GAMES.get(message.chat.id)
    if not game or game.status != "lobby":
        return
    game.extend(60)
    await message.reply("⏳ Ro'yxatga olish 60 soniyaga uzaytirildi.")


@router.message(Command("leave"), GROUP)
async def cmd_leave(message: Message) -> None:
    game = g.GAMES.get(message.chat.id)
    if not game:
        return
    was_lobby = game.status == "lobby"
    if await game.remove_player(message.from_user.id) and was_lobby:
        await message.reply("👋 Siz ro'yxatdan chiqdingiz.")


@router.message(Command("kick"), GROUP)
async def cmd_kick(message: Message, bot: Bot) -> None:
    game = g.GAMES.get(message.chat.id)
    rep = message.reply_to_message
    if not game or not rep or not rep.from_user:
        await message.reply("ℹ️ Chiqariladigan o'yinchi xabariga reply qilib /kick yozing.")
        return
    if not await can_manage(bot, game, message.from_user.id):
        await message.reply("❌ Faqat o'yin ochgan yoki guruh admini chiqara oladi.")
        return
    was_lobby = game.status == "lobby"
    if await game.remove_player(rep.from_user.id, kicked=True) and was_lobby:
        await message.reply("🚪 O'yinchi ro'yxatdan chiqarildi.")


@router.message(Command("players"), GROUP)
async def cmd_players(message: Message) -> None:
    game = g.GAMES.get(message.chat.id)
    if not game:
        await message.reply("ℹ️ Hozir o'yin yo'q. Boshlash: /game")
        return
    await message.reply(game.status_text())


@router.message(Command("stopgame", "stop"), GROUP)
async def cmd_stop(message: Message, bot: Bot) -> None:
    game = g.GAMES.get(message.chat.id)
    if not game:
        return
    if not await can_manage(bot, game, message.from_user.id):
        await message.reply("❌ Faqat o'yin ochgan yoki guruh admini to'xtata oladi.")
        return
    if game.task:
        game.task.cancel()
    g.GAMES.pop(message.chat.id, None)
    await message.answer("🛑 O'yin to'xtatildi.")


@router.message(Command("premium"), GROUP)
async def cmd_premium(message: Message) -> None:
    if not await db.is_admin(message.from_user.id):
        return
    on = await db.toggle_premium(message.chat.id)
    await message.reply("🎲 Premium rejim yoqildi (mukofot ×2)." if on else "Premium rejim o'chirildi.")


# ---------- Callback'lar ----------
def _parse(data: str, parts: int) -> list[str] | None:
    bits = data.split(":", parts - 1)
    return bits if len(bits) == parts else None


@router.callback_query(F.data.startswith("n:"))
async def cb_night(call: CallbackQuery) -> None:
    bits = _parse(call.data, 4)
    if not bits:
        await call.answer()
        return
    game = g.GAMES.get(int(bits[1]))
    if not game:
        await call.answer("O'yin tugagan.", show_alert=True)
        return
    ok, text = await game.handle_night(call.from_user.id, bits[2], bits[3])
    await call.answer(text if not ok else "✅")
    if ok:
        try:
            await call.message.edit_text(text)
        except TelegramAPIError:
            pass


@router.callback_query(F.data.startswith("v:"))
async def cb_vote(call: CallbackQuery) -> None:
    bits = _parse(call.data, 3)
    if not bits:
        await call.answer()
        return
    game = g.GAMES.get(int(bits[1]))
    if not game:
        await call.answer("O'yin tugagan.", show_alert=True)
        return
    ok, text = await game.handle_vote(call.from_user.id, int(bits[2]))
    await call.answer(text)


@router.callback_query(F.data.startswith("c:"))
async def cb_confirm(call: CallbackQuery) -> None:
    bits = _parse(call.data, 3)
    if not bits:
        await call.answer()
        return
    game = g.GAMES.get(int(bits[1]))
    if not game:
        await call.answer("O'yin tugagan.", show_alert=True)
        return
    ok, text = await game.handle_confirm(call.from_user.id, bits[2])
    await call.answer(text)


@router.callback_query(F.data.startswith("a:"))
async def cb_afsun(call: CallbackQuery) -> None:
    bits = _parse(call.data, 3)
    if not bits:
        await call.answer()
        return
    game = g.GAMES.get(int(bits[1]))
    if not game:
        await call.answer("O'yin tugagan.", show_alert=True)
        return
    ok, text = await game.handle_afsun(call.from_user.id, int(bits[2]))
    await call.answer(text if not ok else "✅")
    if ok:
        try:
            await call.message.edit_text(text)
        except TelegramAPIError:
            pass
