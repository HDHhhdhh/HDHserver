import os, json, sqlite3
from datetime import datetime, timezone

DB_PATH = os.environ.get("DB_PATH", r"C:\server\app.sqlite")
LOGS_JSON = os.environ.get("LOGS_JSON", r"C:\server\logs.json")
CUTOFF = os.environ.get("CUTOFF_DATE", "2026-01-01")  # 포함

def iso_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")

def setup(con: sqlite3.Connection):
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA synchronous=NORMAL;")
    con.execute("PRAGMA busy_timeout=5000;")
    con.execute("""
    CREATE TABLE IF NOT EXISTS logs (
      date TEXT NOT NULL,
      sid  TEXT NOT NULL,
      entry_json TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      PRIMARY KEY(date, sid)
    )
    """)
    con.execute("CREATE INDEX IF NOT EXISTS idx_logs_sid ON logs(sid)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_logs_date ON logs(date)")

def main():
    if not os.path.exists(LOGS_JSON):
        raise SystemExit(f"logs.json not found: {LOGS_JSON}")

    with open(LOGS_JSON, "r", encoding="utf-8") as f:
        logs = json.load(f)

    if not isinstance(logs, dict):
        raise SystemExit("logs.json must be {date:{sid:entry}} object")

    con = sqlite3.connect(DB_PATH)
    setup(con)

    now = iso_now()
    inserted = 0
    skipped_dates = 0
    skipped_rows = 0

    with con:
        for date, day in logs.items():
            date = str(date)
            if date < CUTOFF:
                skipped_dates += 1
                continue
            if not isinstance(day, dict):
                skipped_rows += 1
                continue

            for sid, entry in day.items():
                sid = str(sid)
                if not isinstance(entry, dict):
                    skipped_rows += 1
                    continue

                entry_json = json.dumps(entry, ensure_ascii=False)
                con.execute(
                    """
                    INSERT INTO logs(date,sid,entry_json,updated_at)
                    VALUES(?,?,?,?)
                    ON CONFLICT(date,sid)
                    DO UPDATE SET
                      entry_json=excluded.entry_json,
                      updated_at=excluded.updated_at
                    """,
                    (date, sid, entry_json, now),
                )
                inserted += 1

    cur = con.execute("SELECT COUNT(*) FROM logs WHERE date >= ?", (CUTOFF,))
    total = cur.fetchone()[0]
    con.close()

    print("DB:", DB_PATH)
    print("CUTOFF:", CUTOFF)
    print("rows upserted:", inserted)
    print("rows in db (date>=cutoff):", total)
    print("skipped old dates:", skipped_dates)
    print("skipped bad rows:", skipped_rows)
    print("DONE")

if __name__ == "__main__":
    main()
