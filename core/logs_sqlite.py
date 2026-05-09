# core/logs_sqlite.py
import sqlite3, json, os

DB_PATH = os.environ.get("DB_PATH", r"C:\server\app.sqlite")

def get_logs(date: str | None = None):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    if date:
        cur.execute(
            "SELECT sid, entry_json FROM logs WHERE date=?",
            (date,)
        )
    else:
        cur.execute("SELECT date, sid, entry_json FROM logs")

    rows = cur.fetchall()
    con.close()

    out = {}
    for row in rows:
        if date:
            sid, entry = row
            out[sid] = json.loads(entry)
        else:
            d, sid, entry = row
            out.setdefault(d, {})[sid] = json.loads(entry)
    return out
