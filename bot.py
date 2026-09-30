"""Mafia bot - ishga tushirish fayli.

    export BOT_TOKEN="123456:ABC..."
    export OWNER_IDS="111111111,222222222"
    python bot.py
"""
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand, BotCommandScopeAllGroupChats, BotCommandScopeAllPrivateChats

import config
import database as db
import handlers_admin
import handlers_game
import handlers_pay
import handlers_user


async def set_commands(bot: Bot) -> None:
    group_cmds = [
        BotCommand(command="game", description="O'yin ochish"),
        BotCommand(command="go", description="O'yinni darhol boshlash"),
        BotCommand(command="extend", description="Ro'yxat vaqtini uzaytirish"),
        BotCommand(command="leave", description="Ro'yxatdan chiqish"),
        BotCommand(command="players", description="O'yinchilar ro'yxati"),
        BotCommand(command="stop", description="O'yinni to'xtatish"),
        BotCommand(command="kick", description="O'yinchini chiqarish (reply)"),
        BotCommand(command="giveto", description="Pul/olmos yuborish (reply)"),
        BotCommand(command="profile", description="Profil"),
        BotCommand(command="top", description="Reyting"),
        BotCommand(command="roles", description="Rollar"),
        BotCommand(command="help", description="Yordam"),
    ]
    private_cmds = [
        BotCommand(command="start", description="Menyu"),
        BotCommand(command="profile", description="Profil"),
        BotCommand(command="top", description="Reyting"),
        BotCommand(command="roles", description="Rollar"),
        BotCommand(command="help", description="Yordam"),
    ]
    await bot.set_my_commands(group_cmds, scope=BotCommandScopeAllGroupChats())
    await bot.set_my_commands(private_cmds, scope=BotCommandScopeAllPrivateChats())


async def health_server() -> None:
    """Render "Web Service" port kutadi. PORT bo'lmasa (Background Worker) ishga tushmaydi."""
    if not config.PORT:
        return
    from aiohttp import web
    app = web.Application()
    ok = lambda request: web.Response(text="ok")  # noqa: E731
    app.router.add_get("/", ok)
    app.router.add_get("/health", ok)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", int(config.PORT)).start()


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    if not config.BOT_TOKEN:
        raise SystemExit("BOT_TOKEN o'rnatilmagan")

    await db.init_db()
    for owner_id in config.OWNER_IDS:
        await db.get_or_create_user(owner_id, None, "Owner")
        await db.add_admin(owner_id, owner_id)

    bot = Bot(config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    # Tartib muhim: buyruqlar (/cancel, /start) holatlardan oldin ishlashi kerak
    dp.include_router(handlers_pay.router)
    dp.include_router(handlers_user.router)
    dp.include_router(handlers_game.router)
    dp.include_router(handlers_admin.router)
    await set_commands(bot)
    await health_server()
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await db.close_db()


if __name__ == "__main__":
    asyncio.run(main())
