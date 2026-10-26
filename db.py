import os
import sqlite3

# файл базы создастся сам рядом с bot.py
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "veli.db")


def init():
    with sqlite3.connect(DB_PATH) as con:
        con.execute(
            "CREATE TABLE IF NOT EXISTS users ("
            "user_id INTEGER PRIMARY KEY, tz INTEGER)"
        )
        con.execute(
            "CREATE TABLE IF NOT EXISTS favorites ("
            "user_id INTEGER, recipe TEXT, "
            "PRIMARY KEY (user_id, recipe))"
        )


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
            "INSERT INTO users (user_id, tz) VALUES (?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET tz = excluded.tz",
            (user_id, tz),
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
