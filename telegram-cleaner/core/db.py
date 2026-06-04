"""SQLite layer: jobs, runs, user_snapshots, logs.

Single-file local DB. Connection-per-call + a write lock keeps it thread-safe
across the Flask threads and the background asyncio worker. Foreign-key
enforcement is intentionally OFF so a job can be deleted while its run history
is preserved (the run stores a denormalised job_name copy).
"""
import json
import sqlite3
import threading
import time

from . import config, logbus

_write_lock = threading.Lock()


def _conn():
    c = sqlite3.connect(config.DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    with _write_lock, _conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                config_json TEXT NOT NULL,
                created_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER NOT NULL,
                job_name TEXT,
                dry_run INTEGER NOT NULL,
                status TEXT NOT NULL,
                scanned INTEGER DEFAULT 0,
                matched INTEGER DEFAULT 0,
                deleted INTEGER DEFAULT 0,
                floodwait_total REAL DEFAULT 0,
                detail_json TEXT,
                started_at REAL,
                finished_at REAL
            );
            CREATE TABLE IF NOT EXISTS user_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                username TEXT, first_name TEXT, last_name TEXT, phone TEXT,
                join_date TEXT, seen_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER, level TEXT, message TEXT, ts REAL NOT NULL
            );
            """
        )
        # migration: add job_name to older runs tables that predate it
        cols = [r[1] for r in c.execute("PRAGMA table_info(runs)").fetchall()]
        if "job_name" not in cols:
            c.execute("ALTER TABLE runs ADD COLUMN job_name TEXT")
    logbus.set_db_writer(_write_log)


# ---------- jobs ----------
def create_job(name, cfg):
    with _write_lock, _conn() as c:
        cur = c.execute("INSERT INTO jobs(name, config_json, created_at) VALUES (?,?,?)",
                        (name, json.dumps(cfg), time.time()))
        return cur.lastrowid


def get_job(job_id):
    with _conn() as c:
        row = c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            return None
        d = dict(row); d["config"] = json.loads(d.pop("config_json")); return d


def list_jobs():
    with _conn() as c:
        rows = c.execute(
            """SELECT j.*,
                      (SELECT COUNT(*) FROM runs r WHERE r.job_id=j.id) AS run_count,
                      (SELECT MAX(started_at) FROM runs r WHERE r.job_id=j.id) AS last_run
               FROM jobs j ORDER BY j.created_at DESC""").fetchall()
        out = []
        for r in rows:
            d = dict(r); d["config"] = json.loads(d.pop("config_json")); out.append(d)
        return out


def delete_job(job_id):
    with _write_lock, _conn() as c:
        c.execute("DELETE FROM jobs WHERE id=?", (job_id,))


# ---------- runs ----------
def create_run(job_id, dry_run, job_name=None):
    with _write_lock, _conn() as c:
        cur = c.execute(
            "INSERT INTO runs(job_id, job_name, dry_run, status, started_at) VALUES (?,?,?,?,?)",
            (job_id, job_name, 1 if dry_run else 0, "queued", time.time()))
        return cur.lastrowid


def update_run(run_id, **fields):
    if not fields:
        return
    if "detail" in fields:
        fields["detail_json"] = json.dumps(fields.pop("detail"))
    keys = ", ".join(f"{k}=?" for k in fields)
    with _write_lock, _conn() as c:
        c.execute(f"UPDATE runs SET {keys} WHERE id=?", (*fields.values(), run_id))


def get_run(run_id):
    with _conn() as c:
        row = c.execute(
            """SELECT r.*, COALESCE(r.job_name, j.name) AS display_name
               FROM runs r LEFT JOIN jobs j ON j.id=r.job_id WHERE r.id=?""",
            (run_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["detail"] = json.loads(d["detail_json"]) if d.get("detail_json") else {}
        return d


def list_runs(limit=200):
    with _conn() as c:
        rows = c.execute(
            """SELECT r.*, COALESCE(r.job_name, j.name) AS display_name
               FROM runs r LEFT JOIN jobs j ON j.id=r.job_id
               ORDER BY r.started_at DESC LIMIT ?""", (limit,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["detail"] = json.loads(d["detail_json"]) if d.get("detail_json") else {}
            d["job_name"] = d.get("display_name") or d.get("job_name") or "—"
            out.append(d)
        return out


def delete_run(run_id):
    with _write_lock, _conn() as c:
        c.execute("DELETE FROM runs WHERE id=?", (run_id,))
        c.execute("DELETE FROM logs WHERE run_id=?", (run_id,))


# ---------- user snapshots ----------
def latest_snapshot(chat_id, user_id):
    with _conn() as c:
        return c.execute(
            "SELECT * FROM user_snapshots WHERE chat_id=? AND user_id=? ORDER BY seen_at DESC LIMIT 1",
            (str(chat_id), str(user_id))).fetchone()


def save_snapshot(chat_id, u):
    with _write_lock, _conn() as c:
        c.execute(
            """INSERT INTO user_snapshots
               (chat_id,user_id,username,first_name,last_name,phone,join_date,seen_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (str(chat_id), str(u["user_id"]), u.get("username"), u.get("first_name"),
             u.get("last_name"), u.get("phone"), u.get("join_date"), time.time()))


# ---------- logs ----------
def _write_log(run_id, level, message):
    with _write_lock, _conn() as c:
        c.execute("INSERT INTO logs(run_id, level, message, ts) VALUES (?,?,?,?)",
                  (run_id, level, message, time.time()))


def get_logs(run_id=None, limit=300):
    with _conn() as c:
        if run_id:
            rows = c.execute("SELECT * FROM logs WHERE run_id=? ORDER BY id DESC LIMIT ?",
                             (run_id, limit)).fetchall()
        else:
            rows = c.execute("SELECT * FROM logs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows][::-1]
