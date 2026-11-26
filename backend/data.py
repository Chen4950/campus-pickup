import hashlib
import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]


def load_station_data():
    source = Path(os.getenv("PICKUP_DEMO_DATA", PROJECT / "backend" / "data" / "demo.json"))
    database = Path(os.getenv("PICKUP_DB", PROJECT / "backend" / "runtime" / "station.sqlite3"))
    raw = source.read_bytes()
    fingerprint = hashlib.sha256(raw).hexdigest()
    sample = json.loads(raw)
    database.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(database)) as db, db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS dataset (
                id INTEGER PRIMARY KEY CHECK(id = 1),
                fingerprint TEXT NOT NULL,
                configuration TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS parcels (id TEXT PRIMARY KEY, details TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS queue (
                id TEXT PRIMARY KEY,
                joined_at TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT NOT NULL
            );
        """)
        db.execute("BEGIN IMMEDIATE")
        current = db.execute("SELECT fingerprint FROM dataset WHERE id = 1").fetchone()
        if not current or current[0] != fingerprint:
            db.execute("DELETE FROM queue")
            db.execute("DELETE FROM parcels")
            db.executemany(
                "INSERT INTO queue VALUES (?, ?, ?, ?)",
                [(row["sample_id"], row["queue_joined_at"], row["service_started_at"], row["service_finished_at"])
                 for row in sample["queue_observations"]],
            )
            db.executemany(
                "INSERT INTO parcels VALUES (?, ?)",
                [(row["parcel_id"], json.dumps(row, ensure_ascii=False)) for row in sample["parcels"]],
            )
            configuration = {name: sample[name] for name in ("station", "layout", "meta", "route_test_scenarios")}
            db.execute("INSERT OR REPLACE INTO dataset VALUES (1, ?, ?)", (fingerprint, json.dumps(configuration)))
        configuration = json.loads(db.execute("SELECT configuration FROM dataset WHERE id = 1").fetchone()[0])
        configuration["parcels"] = [json.loads(details) for (details,) in db.execute("SELECT details FROM parcels ORDER BY id")]
        configuration["queue"] = db.execute("SELECT joined_at, started_at, finished_at FROM queue ORDER BY joined_at").fetchall()
    return configuration
