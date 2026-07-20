# Storage group — design

## Goal

Avoid notification spam while downloading audio playlists, and remove the inline dependency on user PM (`/start`).

Stage media in a private admin-owned group, then deliver to the user in one burst **without** a “Forwarded from” label. Delete staging messages immediately after successful delivery.

## Scope

**In**
- Admin commands to set/unset a storage group
- Persist `storage_chat_id` in SQLite (`bot_config`)
- Audio playlists: stage as music → copy-to-user burst → delete staging
- Inline (video + audio): always stage in storage when configured → edit via-message → delete staging

**Out**
- Video playlists (keep direct album with correct `w`/`h`)
- Sending audio as documents / file albums
- Bot auto-creating the group
- Changing concurrent download limits

## Decisions (locked)

| Topic | Choice |
|-------|--------|
| Storage type | Group / supergroup (admin creates) |
| Bind method | `/setstorage` in the group (admins only) |
| Delivery | Copy by file_id **without** forward header (`drop_author` / re-send media) |
| Audio format | Music player (`DocumentAttributeAudio`), never documents |
| Cleanup | Delete staging messages immediately after successful user delivery |
| Inline staging | Always storage when set (no user PM) |
| Video playlists | Unchanged (direct album) |
| No storage configured | Fallback: current behavior (audio singles to DM; inline stages to user PM) |

## Setup

### Commands

- `/setstorage` — admin only (`admin_user_ids`), only in a group/supergroup.
  - Bot must be able to post and delete its own messages.
  - Saves `storage_chat_id`; switching groups replaces the previous value.
  - Reply: confirmation + chat id.
- `/unsetstorage` — admin only, from anywhere; clears `storage_chat_id` and confirms.

### Data

Table `bot_config`:

```sql
CREATE TABLE IF NOT EXISTS bot_config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
```

Key: `storage_chat_id` → stringified Telegram chat id.

No process restart required after set/unset.

### Group hygiene (ops)

Prefer an empty group (admins only), notifications muted. Bot needs send + delete-own-messages.

## Flows

### Audio playlist (storage set)

1. Download selected entries in batches of 10 (progress + stop unchanged).
2. For each file in the batch: upload to storage as **music** (title / artist / duration).
3. After the batch (or on stop with pending files): copy all staged messages to the user chat in one burst (no re-upload, no forward label).
4. Delete staging messages in storage.
5. Delete local temp files as today.

User-facing progress stays on the playlist status message (“downloading…”, then “sending batch N”) so tracks do not appear one-by-one during download.

### Inline (storage set)

1. Download media.
2. Stage to storage (video or audio attributes as today).
3. Edit the via-message with staged media (`edit_inline_with_media`).
4. Delete staging message.
5. User PM / `/start` is **not** required for inline when storage is configured. `PM_UNAVAILABLE_MESSAGE` applies only to the fallback PM path.

### Video playlist

Unchanged: direct album via `send_playlist_album` with per-item `DocumentAttributeVideo` dimensions.

## Errors

| Case | Behavior |
|------|----------|
| Cannot write/delete in storage | User-visible error; log for admins; inline shows error text on via-message (not “open /start”) |
| Copy burst fails | Keep staging; retry once; then fallback send remaining items one-by-one from storage (still no re-upload); cleanup best-effort |
| Staging delete fails | Log only; user delivery already succeeded |
| Storage unset mid-job | Finish current job with the chat id already in hand; next job reloads config |
| Storage not configured | Fallback to current DM / PM staging paths |

## Concurrency

- Multiple inline jobs and playlist jobs may run in parallel; each owns its own staging message ids.
- Existing per-user concurrent download limits unchanged.

## Modules

| Piece | Responsibility |
|-------|----------------|
| `storage.py` | get/set/unset chat id; stage audio/video; copy media to user without forward label; delete staging |
| `database.py` / `repository.py` | `bot_config` CRUD |
| `handlers.py` | `/setstorage`, `/unsetstorage`; wire audio playlist + inline to storage |
| `inline_media.py` | Prefer storage staging; keep PM staging as fallback when unset |

## Manual test plan

1. `/setstorage` in empty group → confirmation.
2. Audio playlist ≥10 tracks → user receives music burst after batch; no document files; no “Forwarded from”; storage chat empty after.
3. Stop mid-playlist → already-downloaded batch still delivered, then cleaned.
4. Inline video + audio without user having opened bot PM → succeeds when storage set.
5. `/unsetstorage` → audio playlist and inline fall back to old behavior.
6. Bot without delete rights → delivery still works or errors clearly; no silent hang.
