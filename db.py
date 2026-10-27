import os
import sqlite3
import time

# файл базы создастся сам рядом с bot.py
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "veli.db")


def init():
    with sqlite3.connect(DB_PATH) as con:
        con.execute(
            "CREATE TABLE IF NOT EXISTS users ("
            "user_id INTEGER PRIMARY KEY, tz INTEGER)"
        )
        # новые колонки добавляются в уже существующую базу
        for column in ("oven INTEGER", "created INTEGER", "kb INTEGER"):
            try:
                con.execute(f"ALTER TABLE users ADD COLUMN {column}")
            except sqlite3.OperationalError:
                pass
        con.execute(
            "CREATE TABLE IF NOT EXISTS favorites ("
            "user_id INTEGER, recipe TEXT, "
            "PRIMARY KEY (user_id, recipe))"
        )
        con.execute(
            "CREATE TABLE IF NOT EXISTS ratings ("
            "user_id INTEGER, recipe TEXT, value INTEGER, ts INTEGER, "
            "PRIMARY KEY (user_id, recipe))"
        )
        con.execute(
            "CREATE TABLE IF NOT EXISTS events ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, "
            "user_id INTEGER, kind TEXT, data TEXT)"
        )
        con.execute("CREATE INDEX IF NOT EXISTS idx_events_kind ON events(kind, ts)")


# ---------- часовой пояс ----------

def get_tz(user_id):
    """Сдвиг от UTC в часах (например, 5) или None, если ещё не спрашивали."""
    with sqlite3.connect(DB_PATH) as con:
        row = con.execute(
            "SELECT tz FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
    return row[0] if row else None


def set_tz(user_id, tz):
    with sqlite3.connect(DB_PATH) as con:
        con.execute(
            "INSERT INTO users (user_id, tz, created) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET tz = excluded.tz",
            (user_id, tz, int(time.time())),
        )


# ---------- духовка: 1 есть, 0 нет, None ещё не спрашивали ----------

def get_oven(user_id):
    with sqlite3.connect(DB_PATH) as con:
        row = con.execute(
            "SELECT oven FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
    return row[0] if row else None


def set_oven(user_id, value):
    with sqlite3.connect(DB_PATH) as con:
        con.execute(
            "INSERT INTO users (user_id, oven, created) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET oven = excluded.oven",
            (user_id, value, int(time.time())),
        )


# ---------- закреплённая кнопка «Меню»: показывали ли её пользователю ----------

def kb_shown(user_id):
    with sqlite3.connect(DB_PATH) as con:
        row = con.execute(
            "SELECT kb FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
    return bool(row and row[0])


def set_kb(user_id):
    with sqlite3.connect(DB_PATH) as con:
        con.execute(
            "INSERT INTO users (user_id, kb, created) VALUES (?, 1, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET kb = 1",
            (user_id, int(time.time())),
        )


# ---------- избранное (храним название рецепта) ----------

def is_fav(user_id, recipe):
    with sqlite3.connect(DB_PATH) as con:
        row = con.execute(
            "SELECT 1 FROM favorites WHERE user_id = ? AND recipe = ?",
            (user_id, recipe),
        ).fetchone()
    return row is not None


def add_fav(user_id, recipe):
    with sqlite3.connect(DB_PATH) as con:
        con.execute(
            "INSERT OR IGNORE INTO favorites (user_id, recipe) VALUES (?, ?)",
            (user_id, recipe),
        )


def remove_fav(user_id, recipe):
    with sqlite3.connect(DB_PATH) as con:
        con.execute(
            "DELETE FROM favorites WHERE user_id = ? AND recipe = ?",
            (user_id, recipe),
        )


def list_favs(user_id):
    with sqlite3.connect(DB_PATH) as con:
        rows = con.execute(
            "SELECT recipe FROM favorites WHERE user_id = ? ORDER BY rowid",
            (user_id,),
        ).fetchall()
    return [r[0] for r in rows]


# ---------- оценки: 1 «понравилось», -1 «не очень» ----------

def get_rating(user_id, recipe):
    with sqlite3.connect(DB_PATH) as con:
        row = con.execute(
            "SELECT value FROM ratings WHERE user_id = ? AND recipe = ?",
            (user_id, recipe),
        ).fetchone()
    return row[0] if row else 0


def set_rating(user_id, recipe, value):
    """value 1 или -1; значение 0 убирает оценку."""
    with sqlite3.connect(DB_PATH) as con:
        if value == 0:
            con.execute(
                "DELETE FROM ratings WHERE user_id = ? AND recipe = ?",
                (user_id, recipe),
            )
        else:
            con.execute(
                "INSERT INTO ratings (user_id, recipe, value, ts) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(user_id, recipe) DO UPDATE SET value = excluded.value, ts = excluded.ts",
                (user_id, recipe, value, int(time.time())),
            )


def rated_names(user_id, value):
    """Названия рецептов, которым пользователь поставил оценку value."""
    with sqlite3.connect(DB_PATH) as con:
        rows = con.execute(
            "SELECT recipe FROM ratings WHERE user_id = ? AND value = ?",
            (user_id, value),
        ).fetchall()
    return {r[0] for r in rows}


# ---------- события для статистики (только числовой id, без имён) ----------

def log(user_id, kind, data=""):
    """Записывает действие. Ошибка записи никогда не ломает бота."""
    try:
        now = int(time.time())
        with sqlite3.connect(DB_PATH) as con:
            con.execute(
                "INSERT OR IGNORE INTO users (user_id, created) VALUES (?, ?)",
                (user_id, now),
            )
            con.execute(
                "UPDATE users SET created = COALESCE(created, ?) WHERE user_id = ?",
                (now, user_id),
            )
            con.execute(
                "INSERT INTO events (ts, user_id, kind, data) VALUES (?, ?, ?, ?)",
                (now, user_id, kind, str(data)[:80]),
            )
    except Exception:
        pass


def stats():
    """Собирает сводку для разработчика."""
    now = int(time.time())
    day, week = now - 86400, now - 7 * 86400
    out = {}
    with sqlite3.connect(DB_PATH) as con:
        one = lambda q, a=(): con.execute(q, a).fetchone()[0]
        out["users"] = one("SELECT COUNT(*) FROM users")
        out["new_day"] = one("SELECT COUNT(*) FROM users WHERE created >= ?", (day,))
        out["new_week"] = one("SELECT COUNT(*) FROM users WHERE created >= ?", (week,))
        out["active_day"] = one("SELECT COUNT(DISTINCT user_id) FROM events WHERE ts >= ?", (day,))
        out["active_week"] = one("SELECT COUNT(DISTINCT user_id) FROM events WHERE ts >= ?", (week,))
        out["views"] = one("SELECT COUNT(*) FROM events WHERE kind = 'recipe'")
        out["views_week"] = one("SELECT COUNT(*) FROM events WHERE kind = 'recipe' AND ts >= ?", (week,))
        out["fridge"] = one("SELECT COUNT(*) FROM events WHERE kind = 'fridge'")
        out["fav_adds"] = one("SELECT COUNT(*) FROM events WHERE kind = 'fav_add'")
        out["shared_open"] = one("SELECT COUNT(*) FROM events WHERE kind = 'shared_open'")
        out["likes"] = one("SELECT COUNT(*) FROM ratings WHERE value = 1")
        out["dislikes"] = one("SELECT COUNT(*) FROM ratings WHERE value = -1")
        out["oven_yes"] = one("SELECT COUNT(*) FROM users WHERE oven = 1")
        out["oven_no"] = one("SELECT COUNT(*) FROM users WHERE oven = 0")
        out["top_recipes"] = con.execute(
            "SELECT data, COUNT(*) c FROM events WHERE kind = 'recipe' "
            "GROUP BY data ORDER BY c DESC LIMIT 5").fetchall()
        out["cats"] = con.execute(
            "SELECT data, COUNT(*) c FROM events WHERE kind = 'cat' "
            "GROUP BY data ORDER BY c DESC").fetchall()
        out["portions"] = con.execute(
            "SELECT data, COUNT(*) c FROM events WHERE kind = 'portions' "
            "GROUP BY data ORDER BY data").fetchall()
        out["tz"] = con.execute(
            "SELECT tz, COUNT(*) c FROM users WHERE tz IS NOT NULL "
            "GROUP BY tz ORDER BY c DESC").fetchall()
        out["top_liked"] = con.execute(
            "SELECT recipe, SUM(value) s FROM ratings GROUP BY recipe "
            "HAVING s > 0 ORDER BY s DESC LIMIT 3").fetchall()
        out["top_disliked"] = con.execute(
            "SELECT recipe, SUM(value) s FROM ratings GROUP BY recipe "
            "HAVING s < 0 ORDER BY s ASC LIMIT 3").fetchall()
        out["unknown"] = con.execute(
            "SELECT data, COUNT(*) c FROM events WHERE kind = 'unknown' "
            "GROUP BY data ORDER BY c DESC LIMIT 10").fetchall()
    return out
