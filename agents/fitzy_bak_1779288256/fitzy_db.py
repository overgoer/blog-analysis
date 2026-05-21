#!/usr/bin/env python3
"""Fitzy — SQLite database layer. One file, zero deps beyond Python stdlib."""
import sqlite3
import json
import os
from datetime import datetime, date
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "fitzy.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS profile (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recorded_at TEXT NOT NULL DEFAULT (datetime('now')),
    weight REAL,
    pulse INTEGER,
    pressure_sys INTEGER,
    pressure_dia INTEGER,
    sleep_hours REAL,
    water_ml INTEGER,
    steps INTEGER,
    note TEXT
);

CREATE TABLE IF NOT EXISTS workouts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL DEFAULT (date('now')),
    title TEXT NOT NULL,
    exercises TEXT NOT NULL,
    status TEXT DEFAULT 'planned',
    note TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS nutrition (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL DEFAULT (date('now')),
    meal_type TEXT NOT NULL,
    dish TEXT NOT NULL,
    kcal INTEGER,
    protein_g REAL,
    fat_g REAL,
    carbs_g REAL,
    note TEXT
);

CREATE TABLE IF NOT EXISTS exams (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL DEFAULT (date('now')),
    exam_type TEXT NOT NULL,
    doctor TEXT,
    summary TEXT,
    raw_text TEXT,
    parsed_json TEXT,
    file_name TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS medications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    dose TEXT,
    schedule TEXT,
    start_date TEXT,
    end_date TEXT,
    note TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS schedules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    day_of_week INTEGER NOT NULL,
    time TEXT,
    activity_type TEXT NOT NULL,
    description TEXT NOT NULL,
    active INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL DEFAULT (date('now')),
    topic TEXT,
    question TEXT NOT NULL,
    answer TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS research_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'pubmed',
    result TEXT,
    cached_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_metrics_date ON metrics(recorded_at);
CREATE INDEX IF NOT EXISTS idx_workouts_date ON workouts(date);
CREATE INDEX IF NOT EXISTS idx_nutrition_date ON nutrition(date);
CREATE INDEX IF NOT EXISTS idx_exams_date ON exams(date);
CREATE INDEX IF NOT EXISTS idx_conversations_date ON conversations(date);
"""


def get_conn():
    db_path = str(DB_PATH)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = get_conn()
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()


# --- Profile ---

def profile_get(key):
    conn = get_conn()
    r = conn.execute("SELECT value FROM profile WHERE key=?", (key,)).fetchone()
    conn.close()
    return json.loads(r[0]) if r else None


def profile_set(key, value):
    conn = get_conn()
    conn.execute(
        "INSERT INTO profile (key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=datetime('now')",
        (key, json.dumps(value, ensure_ascii=False)),
    )
    conn.commit()
    conn.close()


def profile_get_all():
    conn = get_conn()
    rows = conn.execute("SELECT key, value FROM profile").fetchall()
    conn.close()
    return {r[0]: json.loads(r[1]) for r in rows}


# --- Metrics ---

def metrics_add(weight=None, pulse=None, pressure_sys=None, pressure_dia=None,
                sleep_hours=None, water_ml=None, steps=None, note=None):
    conn = get_conn()
    conn.execute(
        """INSERT INTO metrics (weight, pulse, pressure_sys, pressure_dia, sleep_hours, water_ml, steps, note)
           VALUES (?,?,?,?,?,?,?,?)""",
        (weight, pulse, pressure_sys, pressure_dia, sleep_hours, water_ml, steps, note),
    )
    conn.commit()
    conn.close()


def metrics_latest(limit=7):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM metrics ORDER BY recorded_at DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def metrics_range(start_date, end_date):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM metrics WHERE date(recorded_at) BETWEEN ? AND ? ORDER BY recorded_at",
        (start_date, end_date),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# --- Workouts ---

def workout_add(title, exercises, date_str=None):
    conn = get_conn()
    conn.execute(
        "INSERT INTO workouts (date, title, exercises) VALUES (?,?,?)",
        (date_str or date.today().isoformat(), title, exercises),
    )
    conn.commit()
    conn.close()


def workout_list(status=None, limit=10):
    conn = get_conn()
    if status:
        rows = conn.execute(
            "SELECT * FROM workouts WHERE status=? ORDER BY date DESC LIMIT ?",
            (status, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM workouts ORDER BY date DESC LIMIT ?", (limit,)
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def workout_done(wid):
    conn = get_conn()
    conn.execute("UPDATE workouts SET status='done' WHERE id=?", (wid,))
    conn.commit()
    conn.close()


# --- Nutrition ---

def nutrition_add(date_str, meal_type, dish, kcal=None, protein_g=None, fat_g=None, carbs_g=None):
    conn = get_conn()
    conn.execute(
        "INSERT INTO nutrition (date, meal_type, dish, kcal, protein_g, fat_g, carbs_g) VALUES (?,?,?,?,?,?,?)",
        (date_str or date.today().isoformat(), meal_type, dish, kcal, protein_g, fat_g, carbs_g),
    )
    conn.commit()
    conn.close()


def nutrition_today():
    today = date.today().isoformat()
    conn = get_conn()
    rows = conn.execute("SELECT * FROM nutrition WHERE date=? ORDER BY id", (today,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def nutrition_summary(date_str=None):
    d = date_str or date.today().isoformat()
    conn = get_conn()
    row = conn.execute(
        "SELECT SUM(kcal) as total_kcal, SUM(protein_g) as total_protein, SUM(fat_g) as total_fat, SUM(carbs_g) as total_carbs FROM nutrition WHERE date=?",
        (d,),
    ).fetchone()
    conn.close()
    return dict(row) if row else {}


# --- Exams ---

def exam_add(exam_type, doctor=None, summary=None, raw_text=None, parsed_json=None, file_name=None):
    conn = get_conn()
    conn.execute(
        "INSERT INTO exams (exam_type, doctor, summary, raw_text, parsed_json, file_name) VALUES (?,?,?,?,?,?)",
        (exam_type, doctor, summary, raw_text, json.dumps(parsed_json, ensure_ascii=False) if parsed_json else None, file_name),
    )
    conn.commit()
    conn.close()


def exam_list(limit=10):
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, date, exam_type, doctor, summary, file_name FROM exams ORDER BY date DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# --- Medications ---

def meds_add(name, dose=None, schedule=None, start_date=None, end_date=None, note=None):
    conn = get_conn()
    conn.execute(
        "INSERT INTO medications (name, dose, schedule, start_date, end_date, note) VALUES (?,?,?,?,?,?)",
        (name, dose, schedule, start_date, end_date, note),
    )
    conn.commit()
    conn.close()


def meds_active():
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM medications WHERE (end_date IS NULL OR end_date >= date('now')) AND start_date <= date('now') ORDER BY name"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# --- Schedules ---
# day_of_week: 0=Mon, 6=Sun

def schedule_add(day_of_week, time, activity_type, description):
    conn = get_conn()
    conn.execute(
        "INSERT INTO schedules (day_of_week, time, activity_type, description) VALUES (?,?,?,?)",
        (day_of_week, time, activity_type, description),
    )
    conn.commit()
    conn.close()
    return True


def schedule_list():
    days = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM schedules WHERE active=1 ORDER BY day_of_week, time"
    ).fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        d['day_name'] = days[r['day_of_week']]
        result.append(d)
    return result


def schedule_today():
    today = date.today().weekday()
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM schedules WHERE day_of_week=? AND active=1 ORDER BY time",
        (today,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# --- Conversations ---

def convo_add(question, answer=None, topic=None):
    conn = get_conn()
    conn.execute(
        "INSERT INTO conversations (topic, question, answer) VALUES (?,?,?)",
        (topic, question, answer),
    )
    conn.commit()
    conn.close()


def convo_recent(limit=5):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM conversations ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def convo_by_topic(topic, limit=10):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM conversations WHERE topic=? ORDER BY id DESC LIMIT ?",
        (topic, limit),
    ).fetchall()
    conn.close()
    return list(reversed([dict(r) for r in rows]))


# --- Research cache ---

def research_cache_get(query, source='pubmed'):
    conn = get_conn()
    r = conn.execute(
        "SELECT result FROM research_cache WHERE query=? AND source=? AND cached_at > datetime('now', '-1 day')",
        (query, source),
    ).fetchone()
    conn.close()
    return r[0] if r else None


def research_cache_set(query, result, source='pubmed'):
    conn = get_conn()
    conn.execute(
        "INSERT INTO research_cache (query, source, result) VALUES (?,?,?)",
        (query, source, result),
    )
    conn.commit()
    conn.close()


# Init on import
if not DB_PATH.exists():
    init_db()
