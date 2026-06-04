"""In-memory pub/sub for live logs (Server-Sent Events) + DB persistence.

Anything in the engine calls log(); the dashboard subscribes via /stream/logs
and also reads persisted logs for the Reports tab.
"""
import queue
import threading
import time

_subscribers = []
_lock = threading.Lock()
_db_writer = None  # set by db module to avoid circular import


def set_db_writer(fn):
    global _db_writer
    _db_writer = fn


def subscribe():
    q = queue.Queue(maxsize=1000)
    with _lock:
        _subscribers.append(q)
    return q


def unsubscribe(q):
    with _lock:
        if q in _subscribers:
            _subscribers.remove(q)


def log(message, level="info", run_id=None):
    entry = {
        "ts": time.strftime("%H:%M:%S"),
        "level": level,
        "run_id": run_id,
        "message": message,
    }
    with _lock:
        dead = []
        for q in _subscribers:
            try:
                q.put_nowait(entry)
            except queue.Full:
                dead.append(q)
        for q in dead:
            _subscribers.remove(q)
    if _db_writer:
        try:
            _db_writer(run_id, level, message)
        except Exception:
            pass
    print(f"[{entry['ts']}] {level.upper()}: {message}")
