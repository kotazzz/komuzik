# Storage Group Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stage audio-playlist and inline media in an admin storage group, then copy to the user in a burst without a “Forwarded from” label, and delete staging immediately.

**Architecture:** Persist `storage_chat_id` in SQLite `bot_config`. New `storage.py` owns stage / copy-without-forward / delete. Handlers call it for audio playlist batches and all inline jobs when configured; otherwise keep today’s DM/PM paths. Video playlists stay on direct albums.

**Tech Stack:** Python 3.11, Telethon, SQLite (`Database` / `StatsRepository`), Docker deploy on `me`.

## Global Constraints

- Audio must remain **music** (`DocumentAttributeAudio`), never documents/file albums.
- Copy delivery: `client.send_file(dest, staging_message.media, caption=…)` (or `send_message` with Message) — **not** `forward_messages`.
- Video playlists: **do not** change (direct album with w/h).
- Inline with storage set: **never** require user PM / `/start`.
- Cleanup staging: delete immediately after successful user delivery (best-effort log on delete failure).
- Admin only: `/setstorage`, `/unsetstorage` via `download_limiter.ADMIN_USER_IDS`.
- Commit style: conventional Russian (`feat(storage): …`); push + deploy after meaningful chunks.
- Spec: `docs/superpowers/specs/2026-07-20-storage-group-design.md`.

---

## File map

| File | Role |
|------|------|
| Create `src/komuzik/storage.py` | Stage / copy / delete; thin helpers |
| Modify `src/komuzik/database.py` | Create `bot_config` table |
| Modify `src/komuzik/repository.py` | get/set/clear `storage_chat_id` |
| Modify `src/komuzik/handlers.py` | Commands + wire playlist audio + inline |
| Modify `src/komuzik/inline_media.py` | `stage_media_to_storage`; keep PM fallback |
| Create `tests/test_bot_config.py` | Unit tests for config CRUD |

---

### Task 1: `bot_config` table + repository API

**Files:**
- Modify: `src/komuzik/database.py` (`_create_tables`)
- Modify: `src/komuzik/repository.py`
- Create: `tests/test_bot_config.py`

**Interfaces:**
- Produces:
  - `StatsRepository.get_storage_chat_id() -> int | None`
  - `StatsRepository.set_storage_chat_id(chat_id: int) -> None`
  - `StatsRepository.clear_storage_chat_id() -> None`

- [ ] **Step 1: Add table in `database.py`**

Inside `_create_tables`, after `chat_settings` block:

```python
cursor.execute("""
    CREATE TABLE IF NOT EXISTS bot_config (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
""")
```

- [ ] **Step 2: Add repository methods**

In `StatsRepository` (near other settings helpers):

```python
STORAGE_CHAT_ID_KEY = "storage_chat_id"

def get_storage_chat_id(self) -> int | None:
    try:
        row = self.db.fetchone(
            "SELECT value FROM bot_config WHERE key = ?",
            (STORAGE_CHAT_ID_KEY,),
        )
        if not row or row[0] is None:
            return None
        return int(row[0])
    except Exception as e:
        logger.error(f"Failed to get storage_chat_id: {e}")
        return None

def set_storage_chat_id(self, chat_id: int) -> None:
    try:
        self.db.execute(
            """INSERT INTO bot_config(key, value) VALUES(?, ?)
               ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
            (STORAGE_CHAT_ID_KEY, str(int(chat_id))),
        )
    except Exception as e:
        logger.error(f"Failed to set storage_chat_id: {e}")
        raise

def clear_storage_chat_id(self) -> None:
    try:
        self.db.execute(
            "DELETE FROM bot_config WHERE key = ?",
            (STORAGE_CHAT_ID_KEY,),
        )
    except Exception as e:
        logger.error(f"Failed to clear storage_chat_id: {e}")
        raise
```

Use the same `db.execute` / `fetchone` patterns already used in this file (adjust if the Database API names differ — match existing calls).

- [ ] **Step 3: Unit test**

```python
# tests/test_bot_config.py
import tempfile
from pathlib import Path

from komuzik.database import Database
from komuzik.repository import StatsRepository


def test_storage_chat_id_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        db = Database(str(Path(tmp) / "t.db"))
        db.connect()
        repo = StatsRepository(db)
        assert repo.get_storage_chat_id() is None
        repo.set_storage_chat_id(-100123)
        assert repo.get_storage_chat_id() == -100123
        repo.set_storage_chat_id(-100999)
        assert repo.get_storage_chat_id() == -100999
        repo.clear_storage_chat_id()
        assert repo.get_storage_chat_id() is None
        db.close()
```

- [ ] **Step 4: Run test**

```bash
cd /Users/zheldaksemen/prj/komuzik && uv run pytest tests/test_bot_config.py -v
```

Expected: PASS (add `pytest` to dev deps only if missing — prefer `uv add --dev pytest` then re-run).

- [ ] **Step 5: Commit**

```bash
git add src/komuzik/database.py src/komuzik/repository.py tests/test_bot_config.py
git commit -m "$(cat <<'EOF'
feat(storage): bot_config для storage_chat_id

EOF
)"
```

---

### Task 2: `storage.py` — stage / copy / delete

**Files:**
- Create: `src/komuzik/storage.py`

**Interfaces:**
- Consumes: Telethon client; caption helpers from `captions.py`; attrs like `inline_media.stage_media_to_user`
- Produces:
  - `async def stage_media(client, storage_chat_id, file_path, media_kind, metadata, bot_username="", *, show_bot_caption=True, show_title=True) -> Message`
  - `async def copy_messages_to_chat(client, dest_chat_id, messages: list) -> None` — no forward header
  - `async def delete_staging(client, storage_chat_id, messages: list) -> None` — best-effort

- [ ] **Step 1: Implement `storage.py`**

```python
"""Staging media in an admin storage group and copying to users."""

from __future__ import annotations

import logging
from typing import Any

from telethon.tl.types import DocumentAttributeAudio, DocumentAttributeVideo

from .captions import build_media_caption
from .config import DEFAULT_VIDEO_HEIGHT, DEFAULT_VIDEO_WIDTH

logger = logging.getLogger(__name__)


async def stage_media(
    client: Any,
    storage_chat_id: int,
    file_path: str,
    media_kind: str,
    metadata: dict,
    bot_username: str = "",
    *,
    show_bot_caption: bool = True,
    show_title: bool = True,
):
    title = metadata.get("title") or metadata.get("track")
    caption = build_media_caption(
        bot_username=bot_username,
        title=title if isinstance(title, str) else None,
        show_bot_caption=show_bot_caption,
        show_title=show_title,
    )

    if media_kind == "video":
        attrs = [
            DocumentAttributeVideo(
                duration=int(metadata.get("duration") or 0),
                w=int(metadata.get("width") or DEFAULT_VIDEO_WIDTH),
                h=int(metadata.get("height") or DEFAULT_VIDEO_HEIGHT),
                supports_streaming=True,
            )
        ]
        return await client.send_file(
            storage_chat_id,
            file_path,
            caption=caption,
            supports_streaming=True,
            attributes=attrs,
        )

    if media_kind == "audio":
        attrs = [
            DocumentAttributeAudio(
                duration=int(metadata.get("duration") or 0),
                title=metadata.get("track", "Unknown"),
                performer=metadata.get("artist", "Unknown Artist"),
            )
        ]
        return await client.send_file(
            storage_chat_id,
            file_path,
            caption=caption,
            attributes=attrs,
            force_document=False,
        )

    return await client.send_file(storage_chat_id, file_path, caption=caption)


async def copy_messages_to_chat(client: Any, dest_chat_id: int, messages: list) -> None:
    """Re-send media by file_id without a Forwarded-from header."""
    for msg in messages:
        if msg is None or msg.media is None:
            continue
        caption = msg.message or ""
        await client.send_file(dest_chat_id, msg.media, caption=caption)


async def delete_staging(client: Any, storage_chat_id: int, messages: list) -> None:
    ids = [m.id for m in messages if m is not None]
    if not ids:
        return
    try:
        await client.delete_messages(storage_chat_id, ids)
    except Exception as e:
        logger.warning(f"Failed to delete staging messages in {storage_chat_id}: {e}")
```

- [ ] **Step 2: Smoke-import**

```bash
uv run python -c "from komuzik.storage import stage_media, copy_messages_to_chat, delete_staging; print('ok')"
```

Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add src/komuzik/storage.py
git commit -m "$(cat <<'EOF'
feat(storage): stage/copy/delete хелперы для группы-хранилища

EOF
)"
```

---

### Task 3: Admin commands `/setstorage` / `/unsetstorage`

**Files:**
- Modify: `src/komuzik/handlers.py` — register handlers near `/post`

**Interfaces:**
- Consumes: `self.stats.get/set/clear_storage_chat_id`, `ADMIN_USER_IDS`

- [ ] **Step 1: Register**

In `_register_handlers`:

```python
self.client.on(events.NewMessage(pattern=r"^/setstorage(?:@\w+)?"))(self.setstorage_handler)
self.client.on(events.NewMessage(pattern=r"^/unsetstorage(?:@\w+)?"))(self.unsetstorage_handler)
```

- [ ] **Step 2: Implement handlers**

```python
async def setstorage_handler(self, event: Message):
    user_id, _ = self._get_user_info(event)
    if user_id not in self.download_limiter.ADMIN_USER_IDS:
        return
    if not event.is_group:
        await event.respond("⚠️ Команду нужно вызвать в группе-хранилище.")
        return
    chat_id = event.chat_id
    # Probe write access
    probe = await event.respond("⏳ Проверяю права…")
    try:
        await self.client.delete_messages(chat_id, [probe.id])
    except Exception as e:
        await event.respond(
            f"❌ Не могу удалять сообщения в этой группе ({e!s}). "
            "Дай боту право удалять сообщения и повтори /setstorage."
        )
        return
    self.stats.set_storage_chat_id(int(chat_id))
    await event.respond(f"✅ Эта группа — хранилище бота.\nchat_id=`{chat_id}`")


async def unsetstorage_handler(self, event: Message):
    user_id, _ = self._get_user_info(event)
    if user_id not in self.download_limiter.ADMIN_USER_IDS:
        return
    prev = self.stats.get_storage_chat_id()
    self.stats.clear_storage_chat_id()
    if prev is None:
        await event.respond("ℹ️ Хранилище и так не задано.")
    else:
        await event.respond(f"✅ Хранилище сброшено (было `{prev}`).")
```

- [ ] **Step 3: Commit**

```bash
git add src/komuzik/handlers.py
git commit -m "$(cat <<'EOF'
feat(storage): /setstorage и /unsetstorage

EOF
)"
```

---

### Task 4: Audio playlist uses storage when configured

**Files:**
- Modify: `src/komuzik/handlers.py` — `_download_playlist` / `flush_batch`
- Optionally keep `send_playlist_album` for video only

**Interfaces:**
- Consumes: `stage_media`, `copy_messages_to_chat`, `delete_staging`, `get_storage_chat_id`
- Video path: still `send_playlist_album`

- [ ] **Step 1: Change `flush_batch`**

When `mode == "audio"` and `storage_chat_id := self.stats.get_storage_chat_id()` is not None:

```python
staging = []
try:
    for path, metadata in batch:
        msg = await stage_media(
            self.client,
            storage_chat_id,
            path,
            "audio",
            metadata,
            self.bot_username,
            **caption_kw,
        )
        staging.append(msg)
    try:
        await copy_messages_to_chat(self.client, event.chat_id, staging)
    except Exception:
        # one retry then one-by-one
        try:
            await copy_messages_to_chat(self.client, event.chat_id, staging)
        except Exception:
            for msg in staging:
                await copy_messages_to_chat(self.client, event.chat_id, [msg])
    sent += len(batch)
    self.stats.set_user_last_format(user_id, "audio", quality)
finally:
    await delete_staging(self.client, storage_chat_id, staging)
    for path in paths:
        self._cleanup_download_file(path)
    batch = []
```

When storage is None or mode is video: keep existing `send_playlist_album` behavior.

- [ ] **Step 2: Progress text**

For audio+storage, progress line may say `отправляю пачку N из хранилища…` (optional, keep short).

- [ ] **Step 3: Commit**

```bash
git add src/komuzik/handlers.py
git commit -m "$(cat <<'EOF'
feat(storage): аудио-плейлист через группу-хранилище

EOF
)"
```

---

### Task 5: Inline always stages to storage when configured

**Files:**
- Modify: `src/komuzik/inline_media.py`
- Modify: `src/komuzik/handlers.py` — `chosen_inline_handler`

**Interfaces:**
- Consumes: `stage_media`, `delete_staging`, `get_storage_chat_id`
- Keep `stage_media_to_user` + `PM_UNAVAILABLE_MESSAGE` only for fallback

- [ ] **Step 1: Thin wrapper in `inline_media.py` (optional)**

Either call `storage.stage_media` directly from handler, or:

```python
async def stage_media_for_inline(client, target_chat_id, file_path, media_kind, metadata, ...):
    from .storage import stage_media
    return await stage_media(client, target_chat_id, file_path, media_kind, metadata, ...)
```

Prefer importing `stage_media` in the handler to avoid indirection.

- [ ] **Step 2: Update `chosen_inline_handler`**

```python
storage_chat_id = self.stats.get_storage_chat_id()
if storage_chat_id is not None:
    staging_msg = await stage_media(
        self.client,
        storage_chat_id,
        file_path,
        media_kind,
        metadata,
        self.bot_username,
        **self._caption_kwargs(user_id),
    )
    try:
        await edit_inline_with_media(self.client, inline_msg_id, staging_msg)
        self._track_inline_download(parsed, user_id, username, success=True)
    finally:
        await delete_staging(self.client, storage_chat_id, [staging_msg])
else:
    # existing stage_media_to_user + PM_UNAVAILABLE path
    ...
```

Remove the requirement that users open PM when storage is set.

- [ ] **Step 3: Commit**

```bash
git add src/komuzik/handlers.py src/komuzik/inline_media.py
git commit -m "$(cat <<'EOF'
feat(storage): инлайн стейджинг через группу-хранилище

EOF
)"
```

---

### Task 6: Deploy + manual verification

- [ ] **Step 1: Push and deploy**

```bash
git push origin HEAD
ssh me 'cd ~/komuzik && git pull && docker compose build && docker compose up -d'
```

- [ ] **Step 2: Manual checklist (from spec)**

1. Create empty group, add bot, grant delete messages.
2. `/setstorage` → confirmation + chat_id.
3. Audio playlist ≥10 → burst of music (players), no documents, no “Forwarded from”; storage empty after.
4. Stop mid-playlist → pending batch still delivered + cleaned.
5. Inline video/audio without user PM → works with storage set.
6. `/unsetstorage` → playlist audio + inline fall back to old behavior.
7. Video playlist still albums with correct aspect ratio.

- [ ] **Step 3: Final commit only if docs/help need a one-liner** (optional `/help` mention of storage is out of scope unless already editing help).

---

## Spec coverage checklist

| Spec item | Task |
|-----------|------|
| `/setstorage` / `/unsetstorage` | 3 |
| `bot_config` persistence | 1 |
| Audio playlist stage→copy→delete | 4 |
| Inline always via storage when set | 5 |
| No forward label | 2 (`copy_messages_to_chat`) |
| Immediate cleanup | 2 + 4 + 5 |
| Fallback when unset | 4 + 5 |
| Video playlists unchanged | 4 (explicit) |
| Error / retry on copy | 4 |
| Manual test plan | 6 |

## Placeholder / consistency self-review

- No TBD left.
- Method names aligned: `get/set/clear_storage_chat_id`, `stage_media`, `copy_messages_to_chat`, `delete_staging`.
- Key name: `storage_chat_id` everywhere.
