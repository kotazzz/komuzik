# Admin ban (block B) — design

## Goal

Let bot admins ban a user by Telegram id with a reason. Banned users see a fixed message in DM and inline; the bot stays silent toward them in groups. `/report` remains available so they can appeal.

## Locked decisions

| Topic | Choice |
|-------|--------|
| User-facing text | `🚫 Вы заблокированы.\nПричина: {reason}\nЕсли ошибка — /report` |
| Scope | DM + inline → ban message; **groups → silent** |
| `/report` | Still works while banned |
| Storage | SQLite table `user_bans` |
| Cannot ban | `admin_user_ids` |
| TTL / auto-ban | Out of scope |

## Scope

**In**
- `/ban <user_id> <reason…>`, `/unban <user_id>`
- Ban check on DM messages/commands/callbacks (except allowlist), inline query + chosen inline
- Silent ignore in groups for banned users
- `/admin` hint / simple ban-unban entry (commands or pending prompt)
- Upsert reason on re-ban

**Out**
- User list / download history (block C)
- Temporary bans with expiry
- Banning via Telegram chat permissions APIs

## Data

```sql
CREATE TABLE IF NOT EXISTS user_bans (
    user_id INTEGER PRIMARY KEY,
    reason TEXT NOT NULL,
    banned_by INTEGER,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

- Re-ban same `user_id`: update `reason`, `banned_by`, `created_at` (or keep created_at and add `updated_at` — prefer update reason + `banned_by`, refresh timestamp).
- Unban: `DELETE` row.

## API (repository)

- `get_ban(user_id) -> str | None` — reason or None
- `is_banned(user_id) -> bool`
- `ban_user(user_id, reason, banned_by) -> None`
- `unban_user(user_id) -> bool` — True if a row was deleted
- `count_bans() -> int` (optional, for `/admin`)

## Guard behavior

Central helper used by handlers, e.g. `async def enforce_ban(event_or_context) -> bool`:
- Returns `True` if caller should **stop** (user blocked / silenced).
- Returns `False` if processing may continue.

### Allowlist (never blocked by ban)

- Bot admins (`admin_user_ids`) — always pass
- `/report` (and report follow-up state if any) for the banned user

### DM (private chat)

If banned and not allowlisted: reply with template (reason filled), stop.

Applies to: free text, URLs, playlist flow, `/start`/`/help`/`/settings`/…, callbacks — except allowlist.

### Groups

If banned: **no reply**, stop handler (do not download, do not error).

### Inline

- `InlineQuery`: answer with a single article/text result showing the ban template (or empty + switch PM), cache_time=0 — user must see the reason somehow. Prefer one article titled/blocked with the template body.
- `UpdateBotInlineSend` / chosen: if somehow reached, edit via-message to ban text; do not download.

## Admin commands

Only `admin_user_ids`. Non-admins: silent ignore (same as `/setstorage`).

| Command | Effect |
|---------|--------|
| `/ban <user_id> <reason…>` | Upsert ban; reason required (non-empty after id) |
| `/unban <user_id>` | Delete ban; say if not banned |

Refuse `/ban` if `user_id` is in `admin_user_ids`.

### `/admin` menu

Extend limits panel with:
- Ban count (optional)
- Hint: `/ban <id> причина` · `/unban <id>`
- Optional buttons «Забанить» / «Разбанить» → `ADMIN_PENDING` expecting `id reason` or `id` (pure parsing; don’t steal URLs)

## Message template

Exact user text:

```
🚫 Вы заблокированы.
Причина: {reason}
Если ошибка — /report
```

## Modules

| Piece | Role |
|-------|------|
| `database.py` | `user_bans` table |
| `repository.py` | ban CRUD |
| `handlers.py` | guard + commands + `/admin` snippet |
| Tests | ban upsert/unban; allowlist logic unit if extracted |

## Manual test plan

1. `/ban <non_admin_id> тест` → user gets template on next DM URL; `/report` still works.
2. Same user in a group with a link → bot silent.
3. Inline as banned user → sees ban text, no download.
4. `/unban <id>` → normal behavior restored.
5. `/ban <admin_id> x` → rejected.
6. Re-ban updates reason shown in template.
