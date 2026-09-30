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

# Render "Web Service" porti (Render o'zi beradi). UptimeRobot shu manzilni tekshiradi.
PORT = os.getenv("PORT", "")
