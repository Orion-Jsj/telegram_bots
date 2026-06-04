"""The cleanup engine.

A JOB stores a saved config; a RUN executes it. Dry runs walk the exact same
path but count + sample instead of deleting. Live runs delete in chunks with
FloodWait handling. Everything is logged + persisted for auditability.

Resume: each target keeps a `cursor` (the id of the last message processed) and
a `complete` flag inside the run's stored detail. If a run stops at the per-run
safety ceiling, its status becomes `paused`; resuming continues each unfinished
target from its cursor (older messages only) without rescanning.

Deletion rule (safe-by-default). A message is deleted ONLY IF:
  - older than the cutoff date (if set), AND
  - at least one of its content tags is in the opt-in delete set, AND
  - it passes every enabled protection (pinned/owner/admins/self/whitelist), AND
  - in a private chat it falls within the chosen dm_scope (mine/theirs/both).
With no categories selected, nothing is ever deleted.
"""
import asyncio
import re
import time
from datetime import datetime, timezone

from telethon.errors import FloodWaitError
from telethon.tl import types

from . import config, db, logbus
from .rights import probe_rights, owner_and_admins
from .chats import resolve

URL_RE = re.compile(r"(https?://|www\.|t\.me/|telegram\.me/)", re.I)
CONTENT_TAGS = {"text", "links", "photos", "videos", "files",
                "voice", "stickers", "gifs", "polls", "forwards", "service"}
SAMPLE_CAP = 50          # matched-message previews kept per target


def classify(msg):
    if getattr(msg, "action", None) is not None:
        return {"service"}
    tags = set()
    if getattr(msg, "fwd_from", None) is not None:
        tags.add("forwards")
    if getattr(msg, "poll", None) is not None:
        tags.add("polls")
    if getattr(msg, "photo", None) is not None:
        tags.add("photos")
    doc = getattr(msg, "document", None)
    if doc is not None:
        mime = getattr(doc, "mime_type", "") or ""
        attrs = doc.attributes or []
        is_sticker = any(isinstance(a, types.DocumentAttributeSticker) for a in attrs)
        is_animated = any(isinstance(a, types.DocumentAttributeAnimated) for a in attrs)
        is_video = mime.startswith("video") or any(
            isinstance(a, types.DocumentAttributeVideo) for a in attrs)
        is_voice = any(
            isinstance(a, types.DocumentAttributeAudio) and getattr(a, "voice", False)
            for a in attrs)
        if is_sticker:
            tags.add("stickers")
        elif is_animated or mime == "image/gif":
            tags.add("gifs")
        elif is_voice:
            tags.add("voice")
        elif is_video:
            tags.add("videos")
        else:
            tags.add("files")
    text = msg.message or ""
    if text:
        has_url = bool(URL_RE.search(text)) or any(
            isinstance(e, (types.MessageEntityUrl, types.MessageEntityTextUrl))
            for e in (msg.entities or []))
        tags.add("links" if has_url else "text")
    if not (tags - {"forwards"}):
        tags.add("other")
    return tags


def _skip_reason(msg, delete_types, protected_ids, flags):
    if flags["protect_pinned"] and getattr(msg, "pinned", False):
        return "pinned"
    if flags["protect_self"] and getattr(msg, "out", False):
        return "self"
    if msg.sender_id in protected_ids:
        return "protected-user"
    if not (classify(msg) & delete_types):
        return "type-not-selected"
    return None


def _sample(msg):
    tags = sorted(classify(msg))
    txt = (msg.message or "").strip().replace("\n", " ")
    if len(txt) > 80:
        txt = txt[:80] + "…"
    if not txt:
        txt = "[" + (tags[0] if tags else "msg") + "]"
    return {"id": msg.id,
            "date": msg.date.strftime("%Y-%m-%d %H:%M") if getattr(msg, "date", None) else "",
            "sender": msg.sender_id, "type": ",".join(tags), "text": txt}


def _new_target(tid):
    return {"id": tid, "title": str(tid), "role": None, "scanned": 0, "matched": 0,
            "deleted": 0, "floodwait": 0.0, "by_type": {}, "skips": {}, "samples": [],
            "cursor": None, "complete": False, "can_delete_others": None, "error": None}


def _sums(targets):
    s = {"scanned": 0, "matched": 0, "deleted": 0, "floodwait": 0.0}
    for t in targets:
        for k in s:
            s[k] += t.get(k, 0) or 0
    return s


async def execute_run(run_id, resume=False):
    from .tg import MANAGER
    client = MANAGER.client
    cfg = config.load_config()
    run = db.get_run(run_id)
    job = db.get_job(run["job_id"])
    dry = bool(run["dry_run"])
    jc = job["config"]
    mode = "DRY RUN" if dry else "LIVE DELETE"

    delete_types = {k for k, v in jc.get("delete_types", {}).items() if v} & CONTENT_TAGS
    targets = jc.get("targets", [])
    whitelist = {int(x) for x in jc.get("whitelist_user_ids", []) if str(x).strip().lstrip("-").isdigit()}
    cutoff = _parse_cutoff(jc.get("cutoff_date"))
    dm_scope = jc.get("dm_scope", "both")
    verbose = bool(jc.get("verbose", False))
    flags = {
        "protect_pinned": jc.get("protect_pinned", cfg["defaults"]["protect_pinned"]),
        "protect_owner": jc.get("protect_owner", True),
        "protect_admins": jc.get("protect_admins", True),
        "protect_self": jc.get("protect_self", False),
    }

    batch_size = cfg["chunking"]["batch_size"]
    sleep_s = cfg["chunking"]["sleep_between_batches_sec"]
    fw_cap = cfg["chunking"]["floodwait_cap_sec"]
    max_per = cfg["chunking"]["max_messages_per_run"]

    # resume: reload prior per-target state from the run's stored detail
    prior = {str(t.get("id")): t for t in (run.get("detail") or {}).get("targets", [])} if resume else {}

    db.update_run(run_id, status="running")
    logbus.log(f"[{mode}] run #{run_id} {'resumed' if resume else 'started'} — "
               f"job '{job['name']}', {len(targets)} target(s).", run_id=run_id)
    if not resume:
        logbus.log(f"delete categories: {sorted(delete_types) or 'NONE → everything protected'}", run_id=run_id)
        logbus.log(f"cutoff: {'older than '+str(cutoff.date()) if cutoff else 'all history'} · "
                   f"keep pinned={flags['protect_pinned']} owner={flags['protect_owner']} "
                   f"admins={flags['protect_admins']} self={flags['protect_self']} · dm={dm_scope}",
                   run_id=run_id)

    per_target = []

    def save(status):
        s = _sums(per_target)
        db.update_run(run_id, status=status, scanned=s["scanned"], matched=s["matched"],
                      deleted=s["deleted"], floodwait_total=s["floodwait"],
                      detail={"mode": mode, "targets": per_target,
                              "delete_types": sorted(delete_types),
                              "paused": status == "paused"})

    for tid in targets:
        t = prior.get(str(tid)) or _new_target(tid)
        if t.get("complete"):
            per_target.append(t)
            continue

        try:
            entity = await resolve(client, tid)
        except Exception as e:
            t["error"] = str(e)
            logbus.log(f"Could not resolve target {tid}: {e}", "error", run_id)
            per_target.append(t)
            continue

        caps = await probe_rights(client, entity)
        t["id"] = entity.id
        t["title"] = caps["title"]
        t["role"] = caps["role"]
        t["can_delete_others"] = caps["can_delete_others"]
        t["error"] = None
        is_dm = caps["kind"] == "user"

        protected_ids = set(whitelist)
        if not is_dm and (flags["protect_owner"] or flags["protect_admins"]):
            owner_id, admin_set = await owner_and_admins(client, entity)
            if flags["protect_owner"] and owner_id:
                protected_ids.add(owner_id)
            if flags["protect_admins"]:
                protected_ids |= admin_set

        # resume from cursor (older messages) if we have one; else start at cutoff date
        it_kwargs = {}
        if t.get("cursor"):
            it_kwargs["offset_id"] = t["cursor"]
        elif cutoff:
            it_kwargs["offset_date"] = cutoff

        if delete_types and not caps["can_delete_others"] and not is_dm:
            logbus.log(f"[{caps['title']}] limited rights ({caps['role']}); only YOUR OWN "
                       f"messages deletable here.", "warn", run_id)
        logbus.log(f"[{caps['title']}] scanning"
                   f"{' from id ' + str(t['cursor']) if t.get('cursor') else ''} "
                   f"(role {caps['role']})…", run_id=run_id)

        batch, verbose_left, cap_hit, scanned_this = [], 30, False, 0
        try:
            async for msg in client.iter_messages(entity, **it_kwargs):
                if cutoff and getattr(msg, "date", None) and msg.date >= cutoff:
                    continue
                if max_per and scanned_this >= max_per:
                    cap_hit = True
                    break
                t["cursor"] = msg.id
                t["scanned"] += 1
                scanned_this += 1

                if is_dm:
                    if dm_scope == "mine" and not msg.out:
                        t["skips"]["dm-scope"] = t["skips"].get("dm-scope", 0) + 1
                        continue
                    if dm_scope == "theirs" and msg.out:
                        t["skips"]["dm-scope"] = t["skips"].get("dm-scope", 0) + 1
                        continue
                elif not caps["can_delete_others"] and not msg.out:
                    t["skips"]["no-rights"] = t["skips"].get("no-rights", 0) + 1
                    continue

                reason = _skip_reason(msg, delete_types, protected_ids, flags)
                if reason is None:
                    t["matched"] += 1
                    for tag in classify(msg) & delete_types:
                        t["by_type"][tag] = t["by_type"].get(tag, 0) + 1
                    if len(t["samples"]) < SAMPLE_CAP:
                        t["samples"].append(_sample(msg))
                    batch.append(msg.id)
                    if len(batch) >= batch_size:
                        await _flush(client, entity, batch, dry, t, fw_cap, run_id, caps["title"])
                        batch = []
                        if not dry:
                            await asyncio.sleep(sleep_s)
                else:
                    t["skips"][reason] = t["skips"].get(reason, 0) + 1
                    if verbose and verbose_left > 0:
                        verbose_left -= 1
                        logbus.log(f"[{caps['title']}] skip {msg.id} "
                                   f"({msg.date.date()}): {reason} · "
                                   f"{','.join(sorted(classify(msg)))}", run_id=run_id)

                if t["scanned"] % 300 == 0:
                    save("running")
            if batch:
                await _flush(client, entity, batch, dry, t, fw_cap, run_id, caps["title"])
            t["complete"] = not cap_hit
        except Exception as e:
            t["error"] = str(e)
            logbus.log(f"[{caps['title']}] error: {e}", "error", run_id)

        skip_summary = ", ".join(f"{k}:{v}" for k, v in t["skips"].items()) or "none"
        logbus.log(f"[{caps['title']}] {'PAUSED (cap reached)' if cap_hit else 'done'} — "
                   f"scanned {t['scanned']}, matched {t['matched']}, "
                   f"{'would delete' if dry else 'deleted'} "
                   f"{t['matched'] if dry else t['deleted']}. skipped: {skip_summary}",
                   "warn" if cap_hit else "info", run_id)
        if cap_hit:
            logbus.log(f"[{caps['title']}] resume this run to continue from id {t['cursor']}.",
                       "warn", run_id)
        per_target.append(t)

    status = "done" if all(t.get("complete") or t.get("error") for t in per_target) else "paused"
    db.update_run(run_id, finished_at=time.time())
    save(status)
    s = _sums(per_target)
    logbus.log(f"[{mode}] run #{run_id} {status.upper()} — scanned {s['scanned']}, "
               f"matched {s['matched']}, deleted {s['deleted']}, "
               f"floodwait {s['floodwait']:.0f}s."
               + ("  (Resume to continue.)" if status == "paused" else ""),
               "warn" if status == "paused" else "success", run_id)


async def _flush(client, entity, ids, dry, t, fw_cap, run_id, title):
    if dry:
        return
    while True:
        try:
            await client.delete_messages(entity, ids, revoke=True)
            t["deleted"] += len(ids)
            return
        except FloodWaitError as e:
            wait = int(e.seconds)
            t["floodwait"] = t.get("floodwait", 0) + wait
            logbus.log(f"[{title}] FloodWait: waiting {wait}s"
                       + (f" (exceeds cap {fw_cap}s)" if wait > fw_cap else "") + "…",
                       "warn", run_id)
            await asyncio.sleep(min(wait, fw_cap) + 1)
        except Exception as e:
            logbus.log(f"[{title}] delete failed for {len(ids)} msgs: {e}", "error", run_id)
            return


def _parse_cutoff(s):
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except Exception:
        return None
