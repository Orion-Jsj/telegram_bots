# Telegram Cleaner

A **local, single-user dashboard** to clean up message history in your Telegram
groups, channels and private chats — and to learn about the members of those
groups. It logs in as **you** (a *userbot* via Telethon), not as a bot account,
so it can act anywhere your own account can.

Everything runs on your own machine. Nothing is sent anywhere except to
Telegram, and nothing is ever deleted automatically — you build a job, preview
it, and only then confirm a real deletion.

The app has **two modes**, switched from the toggle in the top-left:
- **🧹 Cleaner** — delete message history (tabs: Home, Create, Jobs, Reports).
- **⬇ Downloader** — save files from a chat to your PC (tabs: Browse, Downloads).
Login, the theme toggle, and the live-log rail are shared by both.

---

## Table of contents

1. [What you need first](#1-what-you-need-first)
2. [Get your Telegram API credentials](#2-get-your-telegram-api-credentials)
3. [Setup](#3-setup)
4. [Running the dashboard](#4-running-the-dashboard)
5. [Logging in (first time)](#5-logging-in-first-time)
6. [How to use it — the workflow](#6-how-to-use-it--the-workflow)
7. [The dashboard explained, tab by tab](#7-the-dashboard-explained-tab-by-tab)
8. [Key concepts](#8-key-concepts)
9. [What you can and cannot delete (rights)](#9-what-you-can-and-cannot-delete-rights)
10. [config.json reference](#10-configjson-reference)
11. [Files the app creates](#11-files-the-app-creates)
12. [Troubleshooting](#12-troubleshooting)
13. [Limitations & safety](#13-limitations--safety)

---

## 1. What you need first

- **Python 3.8 or newer** (3.10+ recommended). The Windows launcher can tell you
  if it's missing.
- A **Telegram account** (the one you want to clean / manage groups for).
- Your **API ID** and **API hash** (free, from Telegram — see next section).

---

## 2. Get your Telegram API credentials

These identify the app to Telegram. They are free and take a minute.

1. Go to **https://my.telegram.org** and log in with your phone number.
2. Open **API development tools**.
3. Create an app (any title / short-name is fine, e.g. "cleaner").
4. Copy the **`api_id`** (a number) and **`api_hash`** (a long string).

You'll put these into a `.env` file during setup.

---

## 3. Setup

### Windows (easiest) — use the launcher

Double-click **`Telegram-Cleaner.bat`** in the project folder. You'll see a menu:

```
[1]  First-time setup   (create .venv + install packages)
[2]  Run dashboard
[3]  Exit
```

Choose **[1] First-time setup**. It will:

- find your Python (it checks the Python Launcher, your PATH, and the usual
  install folders, and skips the fake Microsoft-Store "python"),
- create an isolated environment in **`.venv`**,
- install the requirements,
- create a **`.env`** file from the template.

Then **edit `.env`** (it's a normal text file) and fill in your details:

```
API_ID=1234567
API_HASH=your_api_hash_here
PHONE=+15551234567
```

If Python isn't installed, the launcher shows you where to get it. When
installing Python, **tick "Add python.exe to PATH"** on the first screen.

### Manual setup (any OS — Windows / macOS / Linux)

```bash
pip install -r requirements.txt        # installs Flask + Telethon
cp .env.example .env                    # Windows: copy .env.example .env
# then edit .env with your API_ID, API_HASH, PHONE
```

---

## 4. Running the dashboard

### Windows

Run `Telegram-Cleaner.bat` again and choose **[2] Run dashboard**. The browser
opens automatically at **http://127.0.0.1:5000**. Keep the window open while you
use the app; press **Ctrl+C** there to stop it.

### Manual (any OS)

```bash
python app.py
```

Then open **http://127.0.0.1:5000** in your browser.

The whole app lives at that one address — the tabs switch instantly without
reloading the page.

---

## 5. Logging in (first time)

Open the **Login** tab.

1. Enter your **phone number** (with country code) and click **Send code**.
2. Telegram sends a **login code** to your Telegram app — enter it and **Verify**.
3. If your account has **two-step verification**, you'll be asked for your **2FA
   password**.

After that you're authorized and the session is saved to **`.tg_session`**, so you
won't have to log in again. The pill in the top-right shows your account when
connected.

---

## 6. How to use it — the workflow

The tool is built around a safe, repeatable loop:

```
Login  ->  Create a job  ->  Dry run (preview)  ->  Review in Reports
                                                  ->  Run & delete (confirm)  ->  Review again
```

1. **Create a job** (Create tab): pick the chats, choose what to delete and who to
   protect, and save it. A job is just a saved recipe — it does nothing on its own.
2. **Dry run it** (Jobs tab → *dry run*): the app walks every message exactly as a
   real run would, but **deletes nothing**. It reports how many messages *would* be
   removed, broken down by type.
3. **Review** (Reports tab): open the run to see the per-target breakdown and the
   reasons messages were skipped. Adjust the job if needed.
4. **Run for real** (Jobs tab → *run* → tick the confirmation box): the deletion
   runs in safe chunks, with live progress in the log on the right.
5. **Review again** (Reports tab): the live run is recorded with how many were
   actually deleted.

> **Always dry-run first.** Deletion is permanent.

---

## 7. The dashboard explained, tab by tab

### Top bar & side rail (always visible)

- **Tabs:** Home · Create · Jobs · Reports · Login.
- **Session pill** (top-right): shows your connected account, or a warning if
  you're not logged in.
- **Live Log** (right side): real-time messages from the engine while a job runs —
  scanning progress, FloodWait pauses, completion summaries. "clear" empties the
  on-screen view (history is still kept in Reports).

### Home

A summary and a reminder of the flow: counts of saved jobs, runs, and total
messages deleted, plus a short explanation of what can be removed where.

### Create — build a cleanup job

Five steps, left to right:

1. **Targets.** Switch between **Groups**, **Channels** and **Personal chats** and
   tick the ones you want. **Check my rights** tells you, per target, whether you
   can delete everyone's messages (owner/admin) or only your own, and which
   permission you're missing if not.
2. **What to delete.** Tick the content categories to remove: *text, links, photos,
   videos, files, voice, stickers, gifs, polls, forwarded, service messages*.
   **Everything is protected by default** — if you tick nothing, nothing is deleted.
3. **When.** Optionally set **"delete messages older than"** a date (blank = all
   history). For private chats, choose the **scope**: both sides, only your
   messages, or only the other person's.
4. **Protect.** Independent toggles to **keep pinned**, **keep your own messages**,
   **keep the owner's messages**, and **keep admins' messages**. Plus **Protect
   specific members** — click **load members** to get the group's member list and
   tick exactly who to spare (or paste extra user IDs). Members whose name or
   username changed since the last scan are flagged **changed**.
5. **Save.** Optionally enable **Verbose dry-run** (logs the reason each message is
   skipped — great for understanding results). Name the job and click **Create job**.

### Jobs — your saved recipes

A table of saved jobs (name, target count, what it deletes, cutoff, how many times
it's been run).

- **Click a row** to see the full configuration in a popup.
- **dry run** — preview only, deletes nothing.
- **run** — opens a confirmation popup; tick *"I understand this can't be undone"*
  and the Delete button activates. One click, no typing.
- **delete** — removes the job (its past runs stay in Reports).

### Reports — audit & results

A table of every run (job name, dry/live, status, scanned / matched / deleted,
timestamp), newest first. It auto-refreshes while a run is in progress.

- **Click a row** for the per-target breakdown: counts, a **by-type** tally of what
  matched, a **skipped** tally showing *why* messages were kept
  (e.g. `pinned:3`, `protected-user:12`, `type-not-selected:40`, `dm-scope:5`),
  and a **preview of the matched messages** (date, type, sender, text snippet) so
  you can see exactly *what* would be / was removed before trusting a live run.
- **Resume** appears on a **paused** run (one that hit the per-run scan ceiling).
  It continues each unfinished target from where it stopped — see below.
- **delete** removes the run and its logs from the database.

### Login

Connect, see who you're logged in as, or log out (which clears the session).

### Downloader · Browse — list and grab files

Switch to **⬇ Downloader** mode, then **Browse**:

1. **Chat** — pick one group / channel / personal chat.
2. **File types** — tick which kinds to list: photos, videos, files/docs, audio,
   voice, gifs. Set "list up to N" to bound how much history is scanned.
3. **List files** — shows a checkbox table of files (name, type, size, date).
   Use *select all / none*; the summary shows how many and the total size.
4. **Download to** — the destination folder on your PC (a sensible default is
   pre-filled; change it to any path). Click **Download selected**.

Files are saved as `<message-id>_<original-name>` so names never collide and
re-downloads can be skipped.

### Downloader · Downloads — progress & resume

A table of your downloads with a progress bar (files done / total), status, and
folder. Click a row for the **per-file list** (name, size, status: done / pending
/ error). A **paused** or **error** download has a **resume** button that
continues from where it stopped, skipping files already on disk.

Downloads are deliberately gentle on Telegram: **one file at a time**, a short
pause between files, and full **FloodWait** compliance — so large batches won't
get your account rate-limited.

---

## 8. Key concepts

- **Userbot, not a bot.** It acts as your own account, so it can clean private
  chats and any group/channel where your account has the right permissions.
- **Safe by default.** Nothing is selected for deletion until you tick it. A job
  with no categories ticked deletes nothing.
- **Jobs vs runs.** A **job** is a saved configuration. A **run** is one execution
  of it — either a **dry run** (counts only) or a **live** deletion. Both are
  recorded for audit.
- **Dry run = truthful preview.** It follows the exact same logic as a live run,
  so its "would delete" numbers match what a real run would do.
- **Protections** decide what is *kept*: pinned messages, the owner, admins,
  your own messages, and any specific members you whitelist.
- **Chunking & FloodWait.** Telegram rate-limits bulk deletes. The engine deletes
  in batches with short pauses, and when Telegram asks it to wait (a *FloodWait*),
  it waits and logs it. Large cleanups can therefore take a while — that's normal.
- **Per-run safety ceiling & resume.** By default a run stops after scanning 5,000
  messages per target (configurable) and is marked **paused**. Press **Resume** in
  Reports to continue from exactly where it left off — each target remembers a
  message-id cursor, so nothing is rescanned. Thousands of messages can be cleared
  across several resumes (also handy if a run is interrupted).
- **Member change tracking.** Each time you load a group's members, the app
  snapshots their name/username and compares with last time, flagging anyone whose
  username or name **changed**. (Telegram has no history of past usernames, so this
  is forward-looking only — IDs never change and are the stable key.)

---

## 9. What you can and cannot delete (rights)

Telegram has three roles: **Owner** (creator), **Admin** (with a set of
permissions — one of which is *Delete messages*), and **Member**.

| Where | Your own messages | Other people's messages |
|---|---|---|
| Private chat (DM) | Yes (revoke both sides) | Yes (revoke both sides) |
| Basic group | Yes | Only if you're the creator or an admin |
| Supergroup | Yes | Admin **with the "Delete messages" right** |
| Broadcast channel | Your own posts | Admin with delete right |

The **Check my rights** button on the Create tab tells you exactly which of these
applies to each target, and names the permission to request if a full cleanup
isn't possible. Where you lack the right, a run simply limits itself to **your own
messages** in that chat.

---

## 10. config.json reference

Defaults are sensible and safe; edit `config.json` (or the values via the app) to
tune behaviour. Restart the app after editing.

```json
{
  "chunking": {
    "batch_size": 100,              // messages deleted per API call (max 100)
    "sleep_between_batches_sec": 2, // pause between batches to avoid rate limits
    "floodwait_cap_sec": 300,       // if Telegram asks to wait longer, pause the run
    "max_messages_per_run": 5000,   // safety ceiling per target per run (raise when ready)
    "scan_only_limit": 0            // 0 = scan all; >0 stops after N scanned (testing)
  },
  "defaults": {
    "protect_admins": true,         // pre-tick "keep admins" on new jobs
    "protect_pinned": true,         // pre-tick "keep pinned" on new jobs
    "dry_run_default": true
  },
  "delete_types": {                 // pre-ticked delete categories for new jobs
    "text": false, "links": false, "photos": false, "videos": false,
    "files": false, "voice": false, "stickers": false, "gifs": false, "polls": false
  },
  "download": {
    "sleep_between_files_sec": 0.6, // pause between files (be gentle with Telegram)
    "floodwait_cap_sec": 300,       // cap for logging long waits; we still wait it out
    "max_files_per_run": 0,         // 0 = no cap (resume covers interruptions)
    "max_list": 500,                // files listed per type when browsing
    "skip_existing": true,          // skip files already on disk with matching size
    "folder": ""                    // default download folder (blank = <project>/downloads)
  }
}
```

---

## 11. Files the app creates

| File | What it is | Sensitive? |
|---|---|---|
| `.env` | your API ID / hash / phone | **Yes** — keep private |
| `.tg_session` | your saved Telegram login | **Yes** — anyone with it can act as you |
| `cleaner.db` | SQLite store: jobs, runs, logs, member snapshots | local only |
| `config.json` | tunable settings | no |

Keep `.env` and `.tg_session` private and never share them.

---

## 12. Troubleshooting

- **"Python not found" (Windows).** Install Python 3.8+ from
  python.org/downloads and tick **Add python.exe to PATH**, then run setup again.
  The Microsoft-Store "python" stub does not work for this.
- **Tabs feel slow / pages take time.** The app is a single page and caches your
  login status, so navigation is instant; the first load of the chat list talks to
  Telegram once and is cached afterwards.
- **A dry run shows scanned but 0 matched.** Either no category was ticked, your
  cutoff date excluded everything, or those messages are a type you didn't select.
  Turn on **Verbose dry-run** and re-run — the log shows the reason for each skip.
- **"Insufficient rights" / only my own messages deleted.** You're not an admin
  with the *Delete messages* permission in that group. Ask the owner to grant it.
- **Deletion is slow / "FloodWait".** Normal for large cleanups — Telegram throttles
  bulk deletes. The engine waits and continues; watch the live log.
- **Few members load for a big group.** Telegram limits member listing for very
  large supergroups unless you're an admin; channel subscriber lists are hidden to
  non-admins.
- **Login code never arrives / expired.** Re-request it from the Login tab; codes
  are time-limited.
- **Port 5000 already in use.** Stop the other program using it, or change the port
  at the bottom of `app.py`.

---

## 13. Limitations & safety

- **Deletion is permanent.** There is no undo. Always **dry-run first** and review
  the Reports breakdown before a live run.
- **No past-username history.** Change tracking only sees changes that happen after
  you start scanning a group.
- **Large groups / channels.** Member enumeration is capped by Telegram for big
  supergroups, and broadcast subscriber lists are hidden unless you're an admin.
- **Long runs.** Cleaning years of history across many chats can take a long time
  due to rate limits; the job/run model is designed for exactly this — start small,
  watch the log, and raise `max_messages_per_run` when you're comfortable.
- **Keep your secrets safe.** `.env` and `.tg_session` give full access to your
  account. Don't commit or share them.
