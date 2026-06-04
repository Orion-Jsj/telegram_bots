"""Telethon client wrapped in a persistent background asyncio loop.

Flask is synchronous; Telethon is async and the client must live on ONE loop.
So we run a dedicated loop in a daemon thread and submit coroutines to it via
run_coroutine_threadsafe. Every Telegram call in the app goes through .run().
"""
import asyncio
import threading
import time

from telethon import TelegramClient
from telethon.errors import (
    SessionPasswordNeededError,
    PhoneCodeInvalidError,
    PhoneCodeExpiredError,
    FloodWaitError,
)

from . import config, logbus


class TGManager:
    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        self.client = None
        self._phone_code_hash = None
        # login_state: disconnected | code_sent | password_needed | authorized
        self.login_state = "disconnected"
        self._connect_lock = threading.Lock()
        # cached status so tab navigation doesn't hit Telegram every time
        self._status_cache = None
        self._status_ts = 0.0
        self._me = None

    def _run_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def run(self, coro, timeout=None):
        """Submit a coroutine to the worker loop and block for the result."""
        fut = asyncio.run_coroutine_threadsafe(coro, self.loop)
        return fut.result(timeout=timeout)

    def submit(self, coro):
        """Fire-and-forget a coroutine on the worker loop (for long runs)."""
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

    # ---------- connection / auth ----------
    def _ensure_client(self):
        if self.client is None:
            creds = config.credentials()
            if not creds:
                raise RuntimeError("API_ID / API_HASH missing in .env")
            self.client = TelegramClient(
                str(config.SESSION_PATH), creds["api_id"], creds["api_hash"]
            )

    def status(self, max_age=60):
        creds = config.credentials()
        if not creds:
            return {"state": "no_credentials", "authorized": False, "me": None}
        now = time.time()
        # serve cached status for tab navigation — only re-probe Telegram occasionally
        if self._status_cache and (now - self._status_ts) < max_age:
            return self._status_cache
        try:
            authorized = self.run(self._is_authorized(), timeout=20)
        except Exception as e:
            if self._status_cache:        # don't flap on a transient hiccup
                return self._status_cache
            return {"state": "error", "authorized": False, "me": None, "error": str(e)}
        me = self._me
        if authorized:
            self.login_state = "authorized"
            if me is None:
                try:
                    me = self.run(self._whoami(), timeout=20)
                    self._me = me
                except Exception:
                    me = None
        st = {"state": self.login_state, "authorized": authorized, "me": me}
        self._status_cache = st
        self._status_ts = now
        return st

    def _invalidate_status(self):
        self._status_cache = None
        self._status_ts = 0.0

    async def _is_authorized(self):
        self._ensure_client()
        if not self.client.is_connected():
            await self.client.connect()
        return await self.client.is_user_authorized()

    async def _whoami(self):
        me = await self.client.get_me()
        if not me:
            return None
        return {
            "id": me.id,
            "username": me.username,
            "name": " ".join(filter(None, [me.first_name, me.last_name])),
            "phone": me.phone,
        }

    def start_login(self, phone):
        return self.run(self._start_login(phone), timeout=60)

    async def _start_login(self, phone):
        self._ensure_client()
        if not self.client.is_connected():
            await self.client.connect()
        if await self.client.is_user_authorized():
            self.login_state = "authorized"
            return {"ok": True, "state": "authorized"}
        sent = await self.client.send_code_request(phone)
        self._phone_code_hash = sent.phone_code_hash
        self._phone = phone
        self.login_state = "code_sent"
        logbus.log(f"Login code requested for {phone}")
        return {"ok": True, "state": "code_sent"}

    def submit_code(self, code):
        return self.run(self._submit_code(code), timeout=60)

    async def _submit_code(self, code):
        try:
            await self.client.sign_in(
                phone=self._phone, code=code, phone_code_hash=self._phone_code_hash
            )
        except SessionPasswordNeededError:
            self.login_state = "password_needed"
            return {"ok": True, "state": "password_needed"}
        except (PhoneCodeInvalidError, PhoneCodeExpiredError) as e:
            return {"ok": False, "error": f"Code rejected: {type(e).__name__}"}
        self.login_state = "authorized"
        self._invalidate_status()
        logbus.log("Login successful (code).")
        return {"ok": True, "state": "authorized"}

    def submit_password(self, password):
        return self.run(self._submit_password(password), timeout=60)

    async def _submit_password(self, password):
        try:
            await self.client.sign_in(password=password)
        except Exception as e:
            return {"ok": False, "error": f"2FA password rejected: {e}"}
        self.login_state = "authorized"
        self._invalidate_status()
        logbus.log("Login successful (2FA).")
        return {"ok": True, "state": "authorized"}

    def logout(self):
        return self.run(self._logout(), timeout=60)

    async def _logout(self):
        if self.client:
            await self.client.log_out()
        self.login_state = "disconnected"
        self._me = None
        self._invalidate_status()
        return {"ok": True}


MANAGER = TGManager()
