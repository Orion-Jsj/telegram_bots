"""Loads .env credentials and config.json settings.

.env  -> secrets (api_id, api_hash, phone)        [never committed]
config.json -> tunable behaviour (chunking, defaults, delete types)
"""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"
CONFIG_PATH = ROOT / "config.json"
SESSION_PATH = ROOT / "tg.session"          # Telethon session file lives here
DB_PATH = ROOT / "cleaner.db"

DEFAULT_CONFIG = {
    "chunking": {
        "batch_size": 100,                  # ids per delete call (Telegram hard max = 100)
        "sleep_between_batches_sec": 2.0,   # politeness pause to avoid FloodWait
        "floodwait_cap_sec": 300,           # if Telegram asks us to wait longer, pause the run
        "max_messages_per_run": 5000,       # safety ceiling per target per run; raise when comfortable
        "scan_only_limit": 0                # 0 = scan all; otherwise stop after N scanned (testing)
    },
    "defaults": {
        "protect_admins": True,             # never delete messages from admins/owner
        "protect_pinned": True,             # never delete pinned messages
        "dry_run_default": True             # runs are dry unless explicitly told otherwise
    },
    # Everything FALSE = everything protected. You opt-IN to delete a type by setting True.
    "delete_types": {
        "text": False,
        "links": False,
        "photos": False,
        "videos": False,
        "files": False,
        "voice": False,
        "stickers": False,
        "gifs": False,
        "polls": False
    }
}


def _load_env():
    """Minimal .env parser (no external dependency needed)."""
    data = {}
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            data[k.strip()] = v.strip().strip('"').strip("'")
    # environment variables override the file
    for k in ("API_ID", "API_HASH", "PHONE", "DASHBOARD_TOKEN"):
        if os.environ.get(k):
            data[k] = os.environ[k]
    return data


def load_config():
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))  # deep copy
    if CONFIG_PATH.exists():
        try:
            user_cfg = json.loads(CONFIG_PATH.read_text())
            for section, values in user_cfg.items():
                if isinstance(values, dict) and section in cfg:
                    cfg[section].update(values)
                else:
                    cfg[section] = values
        except Exception as e:
            print(f"[config] could not parse config.json, using defaults: {e}")
    # enforce Telegram's hard limit
    cfg["chunking"]["batch_size"] = max(1, min(100, int(cfg["chunking"]["batch_size"])))
    return cfg


def save_config(cfg):
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2))


ENV = _load_env()
CONFIG = load_config()


def credentials():
    api_id = ENV.get("API_ID")
    api_hash = ENV.get("API_HASH")
    phone = ENV.get("PHONE")
    if not api_id or not api_hash:
        return None
    try:
        api_id = int(api_id)
    except ValueError:
        return None
    return {"api_id": api_id, "api_hash": api_hash, "phone": phone}
