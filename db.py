import sqlite3
from datetime import date

DB_NAME = "planka.db"


def init_db():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        name TEXT,
        last_plank_date TEXT,
        plank_value TEXT
    )
    """)
    conn.commit()
    conn.close()


def mark_plank(user_id: int, name: str, plank_value: str | None):
    today = date.today().isoformat()
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()

    cur.execute("SELECT last_plank_date FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()

    if row is None:
        cur.execute(
            "INSERT INTO users (user_id, name, last_plank_date, plank_value) "
            "VALUES (?, ?, ?, ?)",
            (user_id, name, today, plank_value)
        )
        conn.commit()
        conn.close()
        return True

    last_date = row[0]
    if last_date == today:
        conn.close()
        return False

    cur.execute(
        "UPDATE users SET last_plank_date = ?, name = ?, plank_value = ? WHERE user_id = ?",
        (today, name, plank_value, user_id)
    )
    conn.commit()
    conn.close()
    return True


def get_stats_for_today():
    today = date.today().isoformat()
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()

    cur.execute("SELECT name, plank_value FROM users WHERE last_plank_date = ?", (today,))
    done_rows = cur.fetchall()
    done = []
    for name, value in done_rows:
        if value is not None and value != "":
            done.append(f"{name} ({value})")
        else:
            done.append(name)

    cur.execute("SELECT name FROM users WHERE last_plank_date IS NULL OR last_plank_date != ?", (today,))
    not_done = [r[0] for r in cur.fetchall()]

    conn.close()
    return done, not_done
