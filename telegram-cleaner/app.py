"""Telegram Cleaner — Flask dashboard.

Local, single-user control panel. Talks to Telegram via the Telethon manager
running on a background asyncio loop. Create jobs, dry-run them, then run for
real with a typed confirmation. Live logs stream over SSE.
"""
import json
import time

from flask import (
    Flask, render_template, request, jsonify, redirect, url_for, Response, stream_with_context
)

from core import config, db, logbus
from core.tg import MANAGER
from core.chats import list_dialogs, resolve
from core.rights import probe_rights
from core.users import fetch_members
from core.engine import execute_run

app = Flask(__name__)
db.init_db()

ACTIVE_RUNS = {}  # run_id -> future


# ---------------- page ----------------
@app.route("/")
def index():
    return render_template("index.html")


# ---------------- auth API ----------------
@app.route("/api/status")
def api_status():
    creds = config.credentials()
    st = MANAGER.status() if creds else {"state": "no_credentials", "authorized": False, "me": None}
    return jsonify(st)


@app.route("/api/login/start", methods=["POST"])
def api_login_start():
    phone = request.json.get("phone") or (config.ENV.get("PHONE"))
    if not phone:
        return jsonify({"ok": False, "error": "No phone provided (set PHONE in .env or enter it)."})
    try:
        return jsonify(MANAGER.start_login(phone))
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/login/code", methods=["POST"])
def api_login_code():
    code = (request.json.get("code") or "").strip()
    try:
        return jsonify(MANAGER.submit_code(code))
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/login/password", methods=["POST"])
def api_login_password():
    pw = request.json.get("password") or ""
    try:
        return jsonify(MANAGER.submit_password(pw))
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/logout", methods=["POST"])
def api_logout():
    try:
        return jsonify(MANAGER.logout())
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


# ---------------- chats / rights / users ----------------
_DIALOGS_CACHE = {"data": None, "ts": 0.0}


@app.route("/api/dialogs")
def api_dialogs():
    import time as _t
    fresh = request.args.get("fresh")
    if not fresh and _DIALOGS_CACHE["data"] and (_t.time() - _DIALOGS_CACHE["ts"] < 120):
        return jsonify(_DIALOGS_CACHE["data"])
    try:
        data = MANAGER.run(list_dialogs(MANAGER.client), timeout=120)
        _DIALOGS_CACHE["data"] = data
        _DIALOGS_CACHE["ts"] = _t.time()
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/target/<chat_id>/rights")
def api_rights(chat_id):
    try:
        ent = MANAGER.run(resolve(MANAGER.client, chat_id), timeout=60)
        return jsonify(MANAGER.run(probe_rights(MANAGER.client, ent), timeout=60))
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/target/<chat_id>/users")
def api_users(chat_id):
    limit = request.args.get("limit", type=int)
    try:
        ent = MANAGER.run(resolve(MANAGER.client, chat_id), timeout=120)
        return jsonify(MANAGER.run(fetch_members(MANAGER.client, ent, limit), timeout=600))
    except Exception as e:
        return jsonify({"error": str(e)}), 400


# ---------------- config ----------------
@app.route("/api/config", methods=["GET", "POST"])
def api_config():
    if request.method == "POST":
        config.save_config(request.json)
        return jsonify({"ok": True})
    return jsonify(config.load_config())


# ---------------- jobs ----------------
@app.route("/api/jobs", methods=["GET", "POST"])
def api_jobs():
    if request.method == "POST":
        body = request.json
        name = body.get("name") or f"job-{int(time.time())}"
        cfg = {
            "targets": body.get("targets", []),
            "cutoff_date": body.get("cutoff_date") or None,
            "delete_types": body.get("delete_types", {}),
            "whitelist_user_ids": body.get("whitelist_user_ids", []),
            "protect_pinned": body.get("protect_pinned", True),
            "protect_owner": body.get("protect_owner", True),
            "protect_admins": body.get("protect_admins", True),
            "protect_self": body.get("protect_self", False),
            "dm_scope": body.get("dm_scope", "both"),
            "verbose": body.get("verbose", False),
        }
        jid = db.create_job(name, cfg)
        logbus.log(f"Job '{name}' created (#{jid}).")
        return jsonify({"ok": True, "id": jid})
    return jsonify(db.list_jobs())


@app.route("/api/jobs/<int:job_id>", methods=["DELETE"])
def api_delete_job(job_id):
    db.delete_job(job_id)
    logbus.log(f"Job #{job_id} deleted.")
    return jsonify({"ok": True})


@app.route("/api/jobs/<int:job_id>/run", methods=["POST"])
def api_run(job_id):
    body = request.json or {}
    dry = bool(body.get("dry_run", True))
    job = db.get_job(job_id)
    if not job:
        return jsonify({"ok": False, "error": "job not found"}), 404

    # Safety: a live run requires an explicit confirmation flag (checkbox).
    if not dry and not body.get("confirm"):
        return jsonify({"ok": False,
                        "error": "Live deletion requires confirmation."}), 400

    run_id = db.create_run(job_id, dry, job_name=job["name"])
    fut = MANAGER.submit(execute_run(run_id))
    ACTIVE_RUNS[run_id] = fut
    return jsonify({"ok": True, "run_id": run_id, "dry_run": dry})


# ---------------- runs / reports ----------------
@app.route("/api/runs")
def api_runs():
    return jsonify(db.list_runs())


@app.route("/api/runs/<int:run_id>")
def api_run_detail(run_id):
    r = db.get_run(run_id)
    return jsonify(r or {}), (200 if r else 404)


@app.route("/api/runs/<int:run_id>/resume", methods=["POST"])
def api_resume_run(run_id):
    body = request.json or {}
    run = db.get_run(run_id)
    if not run:
        return jsonify({"ok": False, "error": "run not found"}), 404
    if run["status"] not in ("paused", "error"):
        return jsonify({"ok": False, "error": f"run is '{run['status']}', not resumable"}), 400
    if not run["dry_run"] and not body.get("confirm"):
        return jsonify({"ok": False, "error": "Resuming a live run requires confirmation."}), 400
    db.update_run(run_id, status="queued")
    MANAGER.submit(execute_run(run_id, resume=True))
    return jsonify({"ok": True, "run_id": run_id})


@app.route("/api/runs/<int:run_id>", methods=["DELETE"])
def api_delete_run(run_id):
    db.delete_run(run_id)
    return jsonify({"ok": True})


@app.route("/api/logs")
def api_logs():
    run_id = request.args.get("run_id", type=int)
    return jsonify(db.get_logs(run_id))


# ---------------- live log stream (SSE) ----------------
@app.route("/stream/logs")
def stream_logs():
    @stream_with_context
    def gen():
        q = logbus.subscribe()
        try:
            yield "data: " + json.dumps({"ts": time.strftime("%H:%M:%S"),
                                         "level": "info",
                                         "message": "— log stream connected —"}) + "\n\n"
            while True:
                try:
                    entry = q.get(timeout=1)
                    yield "data: " + json.dumps(entry) + "\n\n"
                except Exception:
                    yield ": keepalive\n\n"   # also detects client disconnect fast
        finally:
            logbus.unsubscribe(q)

    return Response(gen(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


if __name__ == "__main__":
    print("Telegram Cleaner running at http://127.0.0.1:5000")
    app.run(host="127.0.0.1", port=5000, threaded=True, debug=False)
