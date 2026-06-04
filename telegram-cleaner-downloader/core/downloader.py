"""File downloader engine.

Lists downloadable media in a chat (with server-side filters so we don't scan
the whole history) and downloads selected files to a local folder.

Telegram-friendly by design:
  - downloads run ONE AT A TIME (no parallel connections),
  - a short sleep between files,
  - FloodWaitError is honoured (we wait the requested time, capped for logging),
  - already-downloaded files are skipped (size match),
  - runs are resumable per-file, so big batches survive interruptions.
"""
import asyncio
import mimetypes
import os
import re
import time

from telethon.errors import FloodWaitError
from telethon.tl import types

from . import config, db, logbus
from .chats import resolve

# UI category -> Telegram server-side filter + the classified type we expect
FILTERS = {
    "photos": (types.InputMessagesFilterPhotos, "photo"),
    "videos": (types.InputMessagesFilterVideo, "video"),
    "gifs":   (types.InputMessagesFilterGif, "gif"),
    "voice":  (types.InputMessagesFilterVoice, "voice"),
    "audio":  (types.InputMessagesFilterMusic, "audio"),
    "files":  (types.InputMessagesFilterDocument, "file"),
}
INVALID = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def _safe_name(name):
    name = INVALID.sub("_", name or "").strip().strip(".") or "file"
    return name[:120]


def _classify_file(msg):
    """Return (type, filename, size, mime) for a media message, or None."""
    photo = getattr(msg, "photo", None)
    doc = getattr(msg, "document", None)
    if photo is not None:
        size = 0
        try:
            size = max([getattr(s, "size", 0) or 0 for s in getattr(photo, "sizes", [])] or [0])
        except Exception:
            size = 0
        return ("photo", f"photo_{msg.id}.jpg", size, "image/jpeg")
    if doc is not None:
        mime = getattr(doc, "mime_type", "") or ""
        size = getattr(doc, "size", 0) or 0
        attrs = doc.attributes or []
        name = None
        for a in attrs:
            if isinstance(a, types.DocumentAttributeFilename):
                name = a.file_name
        if any(isinstance(a, types.DocumentAttributeSticker) for a in attrs):
            ftype = "sticker"
        elif any(isinstance(a, types.DocumentAttributeAnimated) for a in attrs) or mime == "image/gif":
            ftype = "gif"
        elif any(isinstance(a, types.DocumentAttributeAudio) and getattr(a, "voice", False) for a in attrs):
            ftype = "voice"
        elif any(isinstance(a, types.DocumentAttributeAudio) for a in attrs):
            ftype = "audio"
        elif mime.startswith("video") or any(isinstance(a, types.DocumentAttributeVideo) for a in attrs):
            ftype = "video"
        else:
            ftype = "file"
        if not name:
            ext = mimetypes.guess_extension(mime.split(";")[0]) or ""
            name = f"{ftype}_{msg.id}{ext}"
        return (ftype, name, size, mime)
    return None


def _entry(msg):
    c = _classify_file(msg)
    if not c:
        return None
    ftype, name, size, mime = c
    return {"id": msg.id, "name": name, "size": size, "mime": mime, "type": ftype,
            "date": msg.date.strftime("%Y-%m-%d %H:%M") if getattr(msg, "date", None) else "",
            "sender": msg.sender_id}


async def list_files(client, chat_id, types_sel, limit=500):
    """List downloadable files in a chat for the selected categories."""
    ent = await resolve(client, chat_id)
    seen = {}
    for cat in types_sel:
        if cat not in FILTERS:
            continue
        filt, expected = FILTERS[cat]
        try:
            async for msg in client.iter_messages(ent, filter=filt(), limit=limit):
                e = _entry(msg)
                if e and e["type"] == expected and msg.id not in seen:
                    seen[msg.id] = e
        except Exception as e:
            logbus.log(f"list {cat} failed: {e}", "warn")
    files = sorted(seen.values(), key=lambda x: x["id"], reverse=True)
    return {"files": files, "count": len(files),
            "total_size": sum(f["size"] for f in files)}


def human(n):
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024


async def execute_download(run_id, resume=False):
    from .tg import MANAGER
    client = MANAGER.client
    cfg = config.load_config()
    dl = cfg.get("download", {})
    run = db.get_run(run_id)
    job = db.get_job(run["job_id"])
    jc = job["config"]

    chat = jc["chat"]
    folder = jc["folder"]
    ids = jc.get("msg_ids", [])
    sleep_s = dl.get("sleep_between_files_sec", 0.6)
    fw_cap = dl.get("floodwait_cap_sec", 300)
    skip_existing = dl.get("skip_existing", True)
    max_files = dl.get("max_files_per_run", 0)

    try:
        os.makedirs(folder, exist_ok=True)
    except Exception as e:
        db.update_run(run_id, status="error",
                      detail={"error": f"cannot create folder: {e}", "files": []})
        logbus.log(f"Download run #{run_id}: cannot create folder '{folder}': {e}", "error", run_id)
        return

    prior = {f["id"]: f for f in (run.get("detail") or {}).get("files", [])} if resume else {}
    files = []
    for mid in ids:
        st = prior.get(mid) or {"id": mid, "name": None, "size": 0, "type": None,
                                "status": "pending", "path": None, "error": None}
        files.append(st)

    ent = await resolve(client, chat)
    db.update_run(run_id, status="running")
    logbus.log(f"[DOWNLOAD] run #{run_id} {'resumed' if resume else 'started'} — "
               f"{len(files)} file(s) -> {folder}", run_id=run_id)

    def save(status):
        done = sum(1 for f in files if f["status"] == "done")
        db.update_run(run_id, status=status, scanned=len(files), matched=done, deleted=0,
                      detail={"kind": "download", "chat": chat, "folder": folder,
                              "files": files, "title": jc.get("title", str(chat))})

    processed_this = 0
    for f in files:
        if f["status"] == "done":
            continue
        if max_files and processed_this >= max_files:
            logbus.log(f"[DOWNLOAD] reached max_files_per_run ({max_files}) — pausing. "
                       f"Resume to continue.", "warn", run_id)
            save("paused")
            return

        try:
            msg = await client.get_messages(ent, ids=f["id"])
        except FloodWaitError as e:
            logbus.log(f"[DOWNLOAD] FloodWait {int(e.seconds)}s while fetching — waiting…", "warn", run_id)
            await asyncio.sleep(min(int(e.seconds), fw_cap) + 1)
            continue
        if not msg or not (getattr(msg, "document", None) or getattr(msg, "photo", None)):
            f["status"] = "error"; f["error"] = "no media / deleted"
            logbus.log(f"[DOWNLOAD] message {f['id']} has no media (skipped).", "warn", run_id)
            continue

        e = _entry(msg)
        f["name"] = e["name"]; f["size"] = e["size"]; f["type"] = e["type"]
        path = os.path.join(folder, f"{f['id']}_{_safe_name(e['name'])}")
        f["path"] = path

        if skip_existing and os.path.exists(path) and e["size"] and os.path.getsize(path) == e["size"]:
            f["status"] = "done"
            processed_this += 1
            logbus.log(f"[DOWNLOAD] skip (already have) {e['name']}", run_id=run_id)
            save("running")
            continue

        logbus.log(f"[DOWNLOAD] {e['name']} ({human(e['size'])}) …", run_id=run_id)
        while True:
            try:
                await client.download_media(msg, file=path)
                f["status"] = "done"
                f["size"] = os.path.getsize(path) if os.path.exists(path) else e["size"]
                break
            except FloodWaitError as ex:
                wait = int(ex.seconds)
                logbus.log(f"[DOWNLOAD] FloodWait {wait}s"
                           + (f" (exceeds cap {fw_cap})" if wait > fw_cap else "") + " — waiting…",
                           "warn", run_id)
                await asyncio.sleep(min(wait, fw_cap) + 1)
            except Exception as ex:
                f["status"] = "error"; f["error"] = str(ex)
                logbus.log(f"[DOWNLOAD] failed {e['name']}: {ex}", "error", run_id)
                break

        processed_this += 1
        save("running")
        await asyncio.sleep(sleep_s)

    done = sum(1 for f in files if f["status"] == "done")
    err = sum(1 for f in files if f["status"] == "error")
    pending = sum(1 for f in files if f["status"] == "pending")
    status = "done" if pending == 0 else "paused"
    db.update_run(run_id, finished_at=time.time())
    save(status)
    logbus.log(f"[DOWNLOAD] run #{run_id} {status.upper()} — {done} downloaded, "
               f"{err} failed, {pending} remaining -> {folder}",
               "success" if status == "done" else "warn", run_id)
