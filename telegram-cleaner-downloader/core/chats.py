"""List the user's chats (dialogs) and resolve entities."""
from telethon.tl import types

from .rights import _kind, _title


async def list_dialogs(client):
    groups, channels, dms = [], [], []
    async for d in client.iter_dialogs():
        ent = d.entity
        kind = _kind(ent)
        item = {
            "id": ent.id,
            "title": _title(ent),
            "username": getattr(ent, "username", None),
            "kind": kind,
        }
        if kind in ("basic_group", "supergroup"):
            groups.append(item)
        elif kind == "broadcast":
            channels.append(item)
        elif kind == "user":
            if not getattr(ent, "bot", False):
                dms.append(item)
    return {"groups": groups, "channels": channels, "dms": dms}


async def resolve(client, chat_id):
    return await client.get_entity(int(chat_id))
