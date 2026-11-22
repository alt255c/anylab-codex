"""Task statements extracted from the indexed course reports, with their source locations."""
import json
import sqlite3
from pathlib import Path

def refresh(db):
    records = json.loads((Path(__file__).parent / "data/assignments.json").read_text("utf-8"))
    with sqlite3.connect(db) as con:
        con.execute("CREATE TABLE IF NOT EXISTS course_tasks (id TEXT PRIMARY KEY, lab INTEGER, record TEXT)")
        con.executemany("INSERT OR REPLACE INTO course_tasks VALUES (?,?,?)",
                        [(r["id"],r["lab"],json.dumps(r,ensure_ascii=False)) for r in records])


def catalog(db):
    with sqlite3.connect(db) as con:
        return [json.loads(r) for r, in con.execute("SELECT record FROM course_tasks ORDER BY lab,id")]
