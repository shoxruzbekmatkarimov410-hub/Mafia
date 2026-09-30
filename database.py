"""Mafia bot - PostgreSQL (asyncpg) ma'lumotlar bazasi qatlami."""
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import asyncpg

import config

CURRENCIES = {"dollars", "diamonds"}  # SQL ustun nomlari uchun oq ro'yxat
_pool = None


class _Abort(Exception):
    """Tranzaksiyani bekor qilib, natija kodini qaytarish uchun."""

    def __init__(self, code: str):
        self.code = code


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id       BIGINT PRIMARY KEY,
    username      TEXT,
    full_name     TEXT,
    lang          TEXT    NOT NULL DEFAULT 'uz',
    dollars       BIGINT  NOT NULL DEFAULT 0 CHECK (dollars >= 0),
    diamonds      BIGINT  NOT NULL DEFAULT 0 CHECK (diamonds >= 0),
    games_played  INTEGER NOT NULL DEFAULT 0,
    wins          INTEGER NOT NULL DEFAULT 0,
    next_role     TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS admins (
    user_id   BIGINT PRIMARY KEY,
    added_by  BIGINT,
    added_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS games (
    game_id     BIGSERIAL PRIMARY KEY,
    chat_id     BIGINT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'running',
    day_number  INTEGER NOT NULL DEFAULT 0,
    winner      TEXT,
    started_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ
);
CREATE TABLE IF NOT EXISTS game_players (
    game_id   BIGINT NOT NULL REFERENCES games(game_id) ON DELETE CASCADE,
    user_id   BIGINT NOT NULL REFERENCES users(user_id),
    role      TEXT,
    is_alive  INTEGER NOT NULL DEFAULT 1,
    won       INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (game_id, user_id)
);
CREATE TABLE IF NOT EXISTS shop_items (
    item_id     BIGSERIAL PRIMARY KEY,
    code        TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL,
    description TEXT,
    price       INTEGER NOT NULL CHECK (price > 0),
    currency    TEXT NOT NULL CHECK (currency IN ('dollars', 'diamonds')),
    is_active   INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS inventory (
    user_id   BIGINT NOT NULL REFERENCES users(user_id),
    item_id   BIGINT NOT NULL REFERENCES shop_items(item_id),
    quantity  INTEGER NOT NULL DEFAULT 0 CHECK (quantity >= 0),
    PRIMARY KEY (user_id, item_id)
);
CREATE TABLE IF NOT EXISTS transactions (
    tx_id      BIGSERIAL PRIMARY KEY,
    from_id    BIGINT,
    to_id      BIGINT,
    currency   TEXT NOT NULL,
    amount     BIGINT NOT NULL,
    kind       TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS marriages (
    user_id    BIGINT PRIMARY KEY,
    partner_id BIGINT NOT NULL,
    since      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS premium_groups (
    chat_id  BIGINT PRIMARY KEY,
    added_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS orders (
    order_id       BIGSERIAL PRIMARY KEY,
    user_id        BIGINT NOT NULL REFERENCES users(user_id),
    diamonds       INTEGER NOT NULL,
    amount         BIGINT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'pending',   -- pending / approved / rejected
    file_id        TEXT NOT NULL,
    file_unique_id TEXT NOT NULL,
    file_kind      TEXT NOT NULL DEFAULT 'photo',
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    decided_by     BIGINT,
    decided_at     TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
CREATE INDEX IF NOT EXISTS idx_orders_file ON orders(file_unique_id);
"""

# code, nom, tavsif, narx, valyuta
DEFAULT_SHOP = [
    ("stat_reset", "🔄 Statistikani tiklash", "G'alaba va o'yinlar sonini 0 ga tushiradi", 500, "dollars"),
    ("docs", "📁 Hujjatlar", "Komissar tekshirganda tinch aholi bo'lib ko'rinasiz (1 marta)", 190, "dollars"),
    ("shield", "🛡 Himoya", "Tunda bitta hujumdan saqlaydi", 140, "dollars"),
    ("mask", "🎭 Maska", "O'lsangiz rolingiz e'lon qilinmaydi", 1, "diamonds"),
    ("gun", "🔫 Miltiq", "Tunda bir marta otish imkoniyati", 1, "diamonds"),
    ("killer_shield", "⛑ Qotildan himoya", "Qotil hujumidan bir marta saqlaydi", 2, "diamonds"),
    ("vote_shield", "⚖️ Ovoz berishni himoya qilish", "Osilishdan bir marta saqlaydi", 1, "diamonds"),
]


def _clean_dsn(url: str) -> str:
    """asyncpg tushunmaydigan 'channel_binding' parametrini olib tashlaydi (Neon URL'larida bo'ladi)."""
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query) if k != "channel_binding"]
    return urlunsplit(parts._replace(query=urlencode(query)))


async def init_db() -> None:
    global _pool
    if not config.DATABASE_URL:
        raise SystemExit("DATABASE_URL o'rnatilmagan")
    # statement_cache_size=0: pgbouncer/Supabase pooler bilan ham ishlashi uchun
    _pool = await asyncpg.create_pool(_clean_dsn(config.DATABASE_URL), min_size=1, max_size=5,
                                      statement_cache_size=0)
    async with _pool.acquire() as c:
        await c.execute(SCHEMA)
        for code, name, desc, price, cur in DEFAULT_SHOP:
            await c.execute(
                "INSERT INTO shop_items (code, name, description, price, currency) "
                "VALUES ($1, $2, $3, $4, $5) ON CONFLICT (code) DO UPDATE SET "
                "name = EXCLUDED.name, description = EXCLUDED.description, "
                "price = EXCLUDED.price, currency = EXCLUDED.currency, is_active = 1",
                code, name, desc, price, cur)
        known = {x[0] for x in DEFAULT_SHOP}
        for row in await c.fetch("SELECT code FROM shop_items"):
            if row["code"] not in known:
                await c.execute("UPDATE shop_items SET is_active = 0 WHERE code = $1", row["code"])


async def close_db() -> None:
    if _pool is not None:
        await _pool.close()


# ---------- Foydalanuvchilar ----------

async def get_or_create_user(user_id: int, username: str | None, full_name: str) -> dict:
    async with _pool.acquire() as c:
        row = await c.fetchrow(
            "INSERT INTO users (user_id, username, full_name) VALUES ($1, $2, $3) "
            "ON CONFLICT (user_id) DO UPDATE SET username = EXCLUDED.username, "
            "full_name = EXCLUDED.full_name RETURNING *", user_id, username, full_name)
        return dict(row)


async def get_user(user_id: int) -> dict | None:
    async with _pool.acquire() as c:
        row = await c.fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)
        return dict(row) if row else None


async def find_user(query: str) -> dict | None:
    """ID raqami yoki @username bo'yicha qidirish."""
    query = query.strip().lstrip("@")
    async with _pool.acquire() as c:
        if query.isdigit():
            row = await c.fetchrow("SELECT * FROM users WHERE user_id = $1", int(query))
        else:
            row = await c.fetchrow("SELECT * FROM users WHERE LOWER(username) = LOWER($1)", query)
        return dict(row) if row else None


async def set_lang(user_id: int, lang: str) -> None:
    async with _pool.acquire() as c:
        await c.execute("UPDATE users SET lang = $1 WHERE user_id = $2", lang, user_id)


async def set_next_role(user_id: int, role: str | None) -> None:
    async with _pool.acquire() as c:
        await c.execute("UPDATE users SET next_role = $1 WHERE user_id = $2", role, user_id)


# ---------- Balans ----------

async def change_balance(user_id: int, currency: str, amount: int, kind: str = "admin") -> bool:
    """amount > 0 qo'shadi, amount < 0 ayiradi. Balans yetmasa False."""
    if currency not in CURRENCIES:
        raise ValueError("Noto'g'ri valyuta")
    async with _pool.acquire() as c:
        try:
            async with c.transaction():
                row = await c.fetchrow(
                    f"UPDATE users SET {currency} = {currency} + $1 "
                    f"WHERE user_id = $2 AND {currency} + $1 >= 0 RETURNING user_id", amount, user_id)
                if row is None:
                    raise _Abort("fail")
                await c.execute(
                    "INSERT INTO transactions (from_id, to_id, currency, amount, kind) "
                    "VALUES (NULL, $1, $2, $3, $4)", user_id, currency, amount, kind)
        except _Abort:
            return False
        return True


async def transfer(from_id: int, to_id: int, currency: str, amount: int) -> str:
    """Natija: ok / bad_amount / self_transfer / no_receiver / not_enough."""
    if currency not in CURRENCIES:
        raise ValueError("Noto'g'ri valyuta")
    if amount <= 0:
        return "bad_amount"
    if from_id == to_id:
        return "self_transfer"
    async with _pool.acquire() as c:
        try:
            async with c.transaction():
                if await c.fetchval("SELECT 1 FROM users WHERE user_id = $1", to_id) is None:
                    raise _Abort("no_receiver")
                row = await c.fetchrow(
                    f"UPDATE users SET {currency} = {currency} - $1 "
                    f"WHERE user_id = $2 AND {currency} >= $1 RETURNING user_id", amount, from_id)
                if row is None:
                    raise _Abort("not_enough")
                await c.execute(f"UPDATE users SET {currency} = {currency} + $1 WHERE user_id = $2",
                                amount, to_id)
                await c.execute(
                    "INSERT INTO transactions (from_id, to_id, currency, amount, kind) "
                    "VALUES ($1, $2, $3, $4, 'transfer')", from_id, to_id, currency, amount)
        except _Abort as e:
            return e.code
        return "ok"


# ---------- Adminlar ----------

async def is_admin(user_id: int) -> bool:
    async with _pool.acquire() as c:
        return await c.fetchval("SELECT 1 FROM admins WHERE user_id = $1", user_id) is not None


async def add_admin(user_id: int, added_by: int) -> None:
    async with _pool.acquire() as c:
        await c.execute("INSERT INTO admins (user_id, added_by) VALUES ($1, $2) "
                        "ON CONFLICT DO NOTHING", user_id, added_by)


async def del_admin(user_id: int) -> bool:
    async with _pool.acquire() as c:
        row = await c.fetchrow("DELETE FROM admins WHERE user_id = $1 RETURNING user_id", user_id)
        return row is not None


async def list_admins() -> list[int]:
    async with _pool.acquire() as c:
        return [r["user_id"] for r in await c.fetch("SELECT user_id FROM admins ORDER BY added_at")]


# ---------- Do'kon va inventar ----------

async def list_shop() -> list[dict]:
    async with _pool.acquire() as c:
        rows = await c.fetch("SELECT * FROM shop_items WHERE is_active = 1 ORDER BY item_id")
        return [dict(r) for r in rows]


async def buy_item(user_id: int, item_id: int) -> str:
    """ok / ok_reset / no_item / not_enough."""
    async with _pool.acquire() as c:
        try:
            async with c.transaction():
                item = await c.fetchrow(
                    "SELECT * FROM shop_items WHERE item_id = $1 AND is_active = 1", item_id)
                if item is None:
                    raise _Abort("no_item")
                col = item["currency"]  # CHECK bilan cheklangan, xavfsiz
                row = await c.fetchrow(
                    f"UPDATE users SET {col} = {col} - $1 "
                    f"WHERE user_id = $2 AND {col} >= $1 RETURNING user_id", item["price"], user_id)
                if row is None:
                    raise _Abort("not_enough")
                await c.execute(
                    "INSERT INTO transactions (from_id, to_id, currency, amount, kind) "
                    "VALUES ($1, NULL, $2, $3, 'shop')", user_id, col, item["price"])
                if item["code"] == "stat_reset":
                    await c.execute("UPDATE users SET games_played = 0, wins = 0 WHERE user_id = $1",
                                    user_id)
                    return "ok_reset"
                await c.execute(
                    "INSERT INTO inventory (user_id, item_id, quantity) VALUES ($1, $2, 1) "
                    "ON CONFLICT (user_id, item_id) DO UPDATE SET quantity = inventory.quantity + 1",
                    user_id, item_id)
        except _Abort as e:
            return e.code
        return "ok"


async def buy_role(user_id: int, role: str, price: int) -> str:
    """ok / has_role / not_enough. Rol keyingi o'yin uchun yoziladi."""
    async with _pool.acquire() as c:
        try:
            async with c.transaction():
                row = await c.fetchrow(
                    "SELECT next_role FROM users WHERE user_id = $1 FOR UPDATE", user_id)
                if row and row["next_role"]:
                    raise _Abort("has_role")
                row = await c.fetchrow(
                    "UPDATE users SET diamonds = diamonds - $1, next_role = $2 "
                    "WHERE user_id = $3 AND diamonds >= $1 RETURNING user_id", price, role, user_id)
                if row is None:
                    raise _Abort("not_enough")
                await c.execute(
                    "INSERT INTO transactions (from_id, to_id, currency, amount, kind) "
                    "VALUES ($1, NULL, 'diamonds', $2, 'shop')", user_id, price)
        except _Abort as e:
            return e.code
        return "ok"


async def get_inventory(user_id: int) -> dict[str, int]:
    async with _pool.acquire() as c:
        rows = await c.fetch(
            "SELECT s.code, i.quantity FROM inventory i "
            "JOIN shop_items s ON s.item_id = i.item_id "
            "WHERE i.user_id = $1 AND i.quantity > 0", user_id)
        return {r["code"]: r["quantity"] for r in rows}


async def consume_item(user_id: int, code: str) -> bool:
    async with _pool.acquire() as c:
        row = await c.fetchrow(
            "UPDATE inventory SET quantity = quantity - 1 WHERE user_id = $1 AND quantity > 0 "
            "AND item_id = (SELECT item_id FROM shop_items WHERE code = $2) RETURNING user_id",
            user_id, code)
        return row is not None


# ---------- O'yinlar ----------

async def create_game(chat_id: int) -> int:
    async with _pool.acquire() as c:
        return await c.fetchval("INSERT INTO games (chat_id) VALUES ($1) RETURNING game_id", chat_id)


async def finish_game(game_id: int, winner: str, day: int,
                      results: list[tuple[int, str, bool, bool, int]]) -> None:
    """results: (user_id, role, tirikmi, yutdimi, mukofot_dollar)."""
    async with _pool.acquire() as c:
        async with c.transaction():
            await c.execute(
                "UPDATE games SET status = 'finished', winner = $1, day_number = $2, "
                "finished_at = NOW() WHERE game_id = $3", winner, day, game_id)
            for uid, role, alive, won, reward in results:
                await c.execute(
                    "INSERT INTO game_players (game_id, user_id, role, is_alive, won) "
                    "VALUES ($1, $2, $3, $4, $5) ON CONFLICT (game_id, user_id) DO UPDATE SET "
                    "role = EXCLUDED.role, is_alive = EXCLUDED.is_alive, won = EXCLUDED.won",
                    game_id, uid, role, int(alive), int(won))
                await c.execute(
                    "UPDATE users SET games_played = games_played + 1, wins = wins + $1, "
                    "dollars = dollars + $2 WHERE user_id = $3", int(won), reward, uid)
                if reward:
                    await c.execute(
                        "INSERT INTO transactions (from_id, to_id, currency, amount, kind) "
                        "VALUES (NULL, $1, 'dollars', $2, 'reward')", uid, reward)


# ---------- Buyurtmalar (chek orqali olmos sotib olish) ----------

async def create_order(user_id: int, diamonds: int, amount: int, file_id: str,
                       file_unique_id: str, file_kind: str) -> int | None:
    """Yangi buyurtma. Shu chek rasmi avval yuborilgan bo'lsa None."""
    async with _pool.acquire() as c:
        async with c.transaction():
            dup = await c.fetchval(
                "SELECT 1 FROM orders WHERE file_unique_id = $1 "
                "AND status IN ('pending', 'approved')", file_unique_id)
            if dup is not None:
                return None
            return await c.fetchval(
                "INSERT INTO orders (user_id, diamonds, amount, file_id, file_unique_id, file_kind) "
                "VALUES ($1, $2, $3, $4, $5, $6) RETURNING order_id",
                user_id, diamonds, amount, file_id, file_unique_id, file_kind)


async def count_pending_orders(user_id: int) -> int:
    async with _pool.acquire() as c:
        return await c.fetchval(
            "SELECT COUNT(*) FROM orders WHERE user_id = $1 AND status = 'pending'", user_id)


async def pending_orders(limit: int = 20) -> list[dict]:
    async with _pool.acquire() as c:
        rows = await c.fetch(
            "SELECT * FROM orders WHERE status = 'pending' ORDER BY order_id LIMIT $1", limit)
        return [dict(r) for r in rows]


async def decide_order(order_id: int, admin_id: int, approve: bool) -> dict | None:
    """Buyurtmani tasdiqlaydi (olmos qo'shiladi) yoki rad etadi.
    Buyurtma allaqachon ko'rib chiqilgan bo'lsa None (ikki marta qo'shilmaydi)."""
    async with _pool.acquire() as c:
        async with c.transaction():
            row = await c.fetchrow(
                "UPDATE orders SET status = $1, decided_by = $2, decided_at = NOW() "
                "WHERE order_id = $3 AND status = 'pending' RETURNING *",
                "approved" if approve else "rejected", admin_id, order_id)
            if row is None:
                return None
            if approve:
                await c.execute("UPDATE users SET diamonds = diamonds + $1 WHERE user_id = $2",
                                row["diamonds"], row["user_id"])
                await c.execute(
                    "INSERT INTO transactions (from_id, to_id, currency, amount, kind) "
                    "VALUES (NULL, $1, 'diamonds', $2, 'purchase')", row["user_id"], row["diamonds"])
            return dict(row)


# ---------- Nikoh ----------

async def get_partner(user_id: int) -> int | None:
    async with _pool.acquire() as c:
        return await c.fetchval("SELECT partner_id FROM marriages WHERE user_id = $1", user_id)


async def marry(a: int, b: int) -> bool:
    async with _pool.acquire() as c:
        try:
            async with c.transaction():
                r1 = await c.fetchrow(
                    "INSERT INTO marriages (user_id, partner_id) VALUES ($1, $2) "
                    "ON CONFLICT DO NOTHING RETURNING user_id", a, b)
                r2 = await c.fetchrow(
                    "INSERT INTO marriages (user_id, partner_id) VALUES ($1, $2) "
                    "ON CONFLICT DO NOTHING RETURNING user_id", b, a)
                if r1 is None or r2 is None:
                    raise _Abort("taken")
        except _Abort:
            return False
        return True


async def divorce(user_id: int) -> int | None:
    partner = await get_partner(user_id)
    if partner is None:
        return None
    async with _pool.acquire() as c:
        await c.execute("DELETE FROM marriages WHERE user_id = $1 OR user_id = $2", user_id, partner)
    return partner


# ---------- Premium guruhlar ----------

async def is_premium(chat_id: int) -> bool:
    async with _pool.acquire() as c:
        return await c.fetchval("SELECT 1 FROM premium_groups WHERE chat_id = $1", chat_id) is not None


async def toggle_premium(chat_id: int) -> bool:
    """Yoqilgan bo'lsa o'chiradi (False), o'chiq bo'lsa yoqadi (True)."""
    async with _pool.acquire() as c:
        row = await c.fetchrow("DELETE FROM premium_groups WHERE chat_id = $1 RETURNING chat_id", chat_id)
        if row is not None:
            return False
        await c.execute("INSERT INTO premium_groups (chat_id) VALUES ($1) ON CONFLICT DO NOTHING", chat_id)
        return True


# ---------- Statistika va reyting ----------

async def get_stats() -> dict:
    async with _pool.acquire() as c:
        async def one(sql: str) -> int:
            return await c.fetchval(sql)
        return {
            "users": await one("SELECT COUNT(*) FROM users"),
            "admins": await one("SELECT COUNT(*) FROM admins"),
            "total_games": await one("SELECT COUNT(*) FROM games WHERE status = 'finished'"),
            "premium": await one("SELECT COUNT(*) FROM premium_groups"),
            "pending_orders": await one("SELECT COUNT(*) FROM orders WHERE status = 'pending'"),
        }


async def get_all_user_ids() -> list[int]:
    async with _pool.acquire() as c:
        return [r["user_id"] for r in await c.fetch("SELECT user_id FROM users")]


async def top_users(order_by: str = "wins", limit: int = 10) -> list[dict]:
    if order_by not in {"wins", "diamonds", "dollars", "games_played"}:
        raise ValueError("Noto'g'ri saralash")
    async with _pool.acquire() as c:
        rows = await c.fetch(
            f"SELECT user_id, full_name, username, {order_by} AS score "
            f"FROM users WHERE {order_by} > 0 ORDER BY {order_by} DESC LIMIT $1", limit)
        return [dict(r) for r in rows]
