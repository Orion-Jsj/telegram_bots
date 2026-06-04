"""Enumerate members of a group/channel and detect changes over time.

Telegram exposes only CURRENT user fields — there is no past-username history.
So we snapshot every member each time we scan, store it, and diff against the
previous snapshot. That gives forward-looking "username/name changed" detection.
A user's numeric ID never changes, so it's the stable key.
"""
from telethon.tl import types

from . import db
from .rights import _kind


async def fetch_members(client, entity, limit=None):
    """Return member list with current details + any detected changes."""
    kind = _kind(entity)
    members = []

    if kind == "basic_group":
        from telethon.tl import functions
        full = await client(functions.messages.GetFullChatRequest(entity.id))
        users = {u.id: u for u in full.users}
        for p in full.full_chat.participants.participants:
            u = users.get(p.user_id)
            if u:
                members.append(_user_dict(u, join_date=getattr(p, "date", None)))
    elif kind in ("supergroup", "broadcast"):
        count = 0
        async for u in client.iter_participants(entity, limit=limit):
            jd = None
            part = getattr(u, "participant", None)
            if part is not None and hasattr(part, "date"):
                jd = part.date
            members.append(_user_dict(u, join_date=jd))
            count += 1
    else:
        return {"members": [], "changes": [], "note": "Not a group/channel."}

    changes = _diff_and_store(entity.id, members)
    return {"members": members, "changes": changes,
            "count": len(members), "kind": kind}


def _user_dict(u, join_date=None):
    is_admin = False
    is_owner = False
    part = getattr(u, "participant", None)
    if isinstance(part, types.ChannelParticipantCreator):
        is_owner = True
    elif isinstance(part, types.ChannelParticipantAdmin):
        is_admin = True
    return {
        "user_id": u.id,
        "username": getattr(u, "username", None),
        "first_name": getattr(u, "first_name", None),
        "last_name": getattr(u, "last_name", None),
        "phone": getattr(u, "phone", None),
        "join_date": join_date.isoformat() if join_date else None,
        "is_admin": is_admin,
        "is_owner": is_owner,
        "is_bot": getattr(u, "bot", False),
    }


def _diff_and_store(chat_id, members):
    changes = []
    for m in members:
        prev = db.latest_snapshot(chat_id, m["user_id"])
        if prev:
            for field in ("username", "first_name", "last_name"):
                old = prev[field]
                new = m.get(field)
                if (old or None) != (new or None):
                    changes.append({
                        "user_id": m["user_id"],
                        "field": field,
                        "old": old,
                        "new": new,
                    })
        db.save_snapshot(chat_id, m)
    return changes
