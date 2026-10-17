import os

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
# Egalar (birinchi adminlar): Telegram ID'lar, vergul bilan
OWNER_IDS = [int(x) for x in os.getenv("OWNER_IDS", "").replace(" ", "").split(",") if x]
ADMIN_CONTACT = os.getenv("ADMIN_CONTACT", "@admin")
NEWS_URL = os.getenv("NEWS_URL", "")

# PostgreSQL ulanish manzili (Neon, Supabase, Render Postgres va h.k.)
DATABASE_URL = os.getenv("DATABASE_URL", "")

# ---------- Olmos sotish (chek orqali, admin tasdiqlaydi) ----------
PAY_CARD = os.getenv("PAY_CARD", "")              # masalan: 8600 1234 5678 9012
PAY_CARD_OWNER = os.getenv("PAY_CARD_OWNER", "")  # karta egasi ismi
# Paketlar "olmos:narx_som" ko'rinishida. Oraliq miqdorlar narxi shulardan avtomatik hisoblanadi.
_DEFAULT_PACKS = "1:1800,5:5900,10:9999"


def _parse_packs(raw: str) -> list[tuple[int, int]]:
    packs = []
    for part in raw.split(","):
        qty, price = part.strip().split(":")
        packs.append((int(qty), int(price)))
    if 1 not in [q for q, _ in packs]:
        raise ValueError("DIAMOND_PACKS ichida 1 ta olmos narxi bo'lishi shart (masalan 1:1800)")
    return sorted(packs)


DIAMOND_PACKS = _parse_packs(os.getenv("DIAMOND_PACKS", _DEFAULT_PACKS))

# Tun/kun xabarlariga GIF (file_id yoki havola). Bo'sh bo'lsa oddiy matn.
GIF_NIGHT = os.getenv("GIF_NIGHT", "")
GIF_DAY = os.getenv("GIF_DAY", "")

# ---------- O'yin vaqtlari (soniya). Render > Environment orqali o'zgartirsa bo'ladi ----------
def _num(name: str, default: float):
    try:
        v = float(os.getenv(name, default))
    except ValueError:
        return default
    return int(v) if v == int(v) else v


LOBBY_TIME = _num("LOBBY_TIME", 120)      # ro'yxatga olish
NIGHT_TIME = _num("NIGHT_TIME", 60)       # tun: eng ko'pi bilan
NIGHT_MIN = _num("NIGHT_MIN", 20)         # tun: hamma tanlab bo'lsa ham kamida shuncha davom etadi
DAY_TIME = _num("DAY_TIME", 90)           # kunduzgi muhokama
VOTE_TIME = _num("VOTE_TIME", 60)         # ovoz berish (hamma ovoz bersa erta tugaydi)
CONFIRM_TIME = _num("CONFIRM_TIME", 30)   # "Rostdan ham osmoqchimisiz?"
IDLE_ROUNDS = _num("IDLE_ROUNDS", 2)         # shuncha davr ketma-ket hech kim harakat qilmasa o'yin to'xtaydi
MAX_GAME_MIN = _num("MAX_GAME_MIN", 120)     # o'yinning eng uzoq davomiyligi (daqiqa)

# Bot username'i ishga tushganda avtomatik to'ldiriladi ("Guruhga qo'shish" tugmasi uchun)
BOT_USERNAME = ""

# Render "Web Service" porti (Render o'zi beradi). UptimeRobot shu manzilni tekshiradi.
PORT = os.getenv("PORT", "")
