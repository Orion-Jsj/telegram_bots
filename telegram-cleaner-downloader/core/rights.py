"""Probes the logged-in user's rights in a given chat.

Telegram roles are: Creator (owner), Admin (with a permission subset), Member.
'Moderator' is just informal shorthand for an admin who holds delete/ban rights.

Returns a capability dict the dashboard uses to tell the user, per target,
exactly what is possible and — if not — which right they are missing.
"""
from telethon.tl import types, functions


async def probe_rights(client, entity):
    kind = _kind(entity)
    cap = {
        "kind": kind,
        "title": _title(entity),
        "id": entity.id,
        "role": "member",
        "can_delete_own": True,        # you can always delete your own messages
        "can_delete_others": False,
        "missing_right": None,
        "note": "",
    }

    if kind == "user":
        cap["role"] = "n/a"
        cap["can_delete_others"] = True  # in a DM you may revoke received messages
        cap["note"] = "Private chat: you can delete/revoke messages on both sides."
        return cap

    if kind == "basic_group":
        # Basic groups: creator/admins can delete others; members only their own.
        try:
            full = await client(functions.messages.GetFullChatRequest(entity.id))
            me = await client.get_me()
            for p in full.full_chat.participants.participants:
                if p.user_id == me.id:
                    if isinstance(p, types.ChatParticipantCreator):
                        cap["role"] = "owner"
                        cap["can_delete_others"] = True
                    elif isinstance(p, types.ChatParticipantAdmin):
                        cap["role"] = "admin"
                        cap["can_delete_others"] = True
                    break
        except Exception as e:
            cap["note"] = f"Could not read group admins: {e}"
        if not cap["can_delete_others"]:
            cap["missing_right"] = "admin (basic groups only let admins delete others)"
        return cap

    # supergroup or broadcast channel
    try:
        part = await client(
            functions.channels.GetParticipantRequest(entity, participant="me")
        )
        p = part.participant
        if isinstance(p, types.ChannelParticipantCreator):
            cap["role"] = "owner"
            cap["can_delete_others"] = True
            cap["note"] = "You are the owner — full cleanup possible."
        elif isinstance(p, types.ChannelParticipantAdmin):
            cap["role"] = "admin"
            rights = p.admin_rights
            if rights and rights.delete_messages:
                cap["can_delete_others"] = True
                cap["note"] = "Admin with Delete-Messages right — full cleanup possible."
            else:
                cap["missing_right"] = "Delete Messages (admin permission)"
                cap["note"] = ("You are admin but lack the Delete-Messages right. "
                               "Ask the owner to enable it.")
        else:
            cap["role"] = "member"
            cap["missing_right"] = "Delete Messages (admin permission)"
            cap["note"] = "You are a regular member — only your own messages can be removed."
    except Exception as e:
        cap["note"] = f"Could not read your role here: {e}"
    return cap


def _kind(entity):
    if isinstance(entity, types.User):
        return "user"
    if isinstance(entity, types.Chat):
        return "basic_group"
    if isinstance(entity, types.Channel):
        return "broadcast" if getattr(entity, "broadcast", False) else "supergroup"
    return "unknown"


def _title(entity):
    if isinstance(entity, types.User):
        return " ".join(filter(None, [entity.first_name, entity.last_name])) or (
            entity.username or str(entity.id)
        )
    return getattr(entity, "title", str(entity.id))


async def owner_and_admins(client, entity):
    """Return (owner_id_or_None, set_of_admin_ids_excluding_owner).

    Kept separate so a job can protect the owner only, admins only, or both.
    """
    owner = None
    admins = set()
    kind = _kind(entity)
    try:
        if kind in ("supergroup", "broadcast"):
            async for u in client.iter_participants(
                entity, filter=types.ChannelParticipantsAdmins
            ):
                part = getattr(u, "participant", None)
                if isinstance(part, types.ChannelParticipantCreator):
                    owner = u.id
                else:
                    admins.add(u.id)
        elif kind == "basic_group":
            full = await client(functions.messages.GetFullChatRequest(entity.id))
            for p in full.full_chat.participants.participants:
                if isinstance(p, types.ChatParticipantCreator):
                    owner = p.user_id
                elif isinstance(p, types.ChatParticipantAdmin):
                    admins.add(p.user_id)
    except Exception:
        pass
    return owner, admins
