# Admin limits (block A) — design

## Goal

Cap playlist abuse with a Moscow-time daily quota of successfully delivered playlist items, and let bot admins change concurrent + playlist limits at runtime without redeploy. Blocks B (ban) and C (user list / history) come later.

## Locked decisions

| Topic | Choice |
|-------|--------|
| What counts | Only **successfully sent** playlist items |
| Over-quota start | **Refuse** if `selected > remaining` (no partial start) |
| Day boundary | **Europe/Moscow** (`YYYY-MM-DD`) |
| Admin UX | `/admin` menu (limits section) + command shortcuts |
| Persistence | SQLite (`bot_config`, `user_playlist_limits`, `playlist_usage`) |
| Bot admins | Unlimited playlist quota + unlimited concurrent (existing) |

## Scope

**In**
- Default playlist daily limit **50** (global, overridable)
- Per-user playlist daily limit override
- Global concurrent downloads limit (runtime, seeded from `config.yaml`)
- Pre-start check + increment-on-success
- `/admin` limits UI + commands below

**Out**
- Ban / user list / download history (B, C)
- Daily cap on non-playlist single downloads
- Changing `admin_user_ids` / `unlimited_user_ids` via bot (still yaml)

## Data

### `bot_config` keys

| Key | Meaning | Default |
|-----|---------|---------|
| `max_concurrent_per_user` | Concurrent downloads for normal users | Seed from `config.yaml` `downloads.max_concurrent_per_user` on first read |
| `playlist_daily_limit` | Global playlist items/day | `50` |

### `user_playlist_limits`

```sql
CREATE TABLE IF NOT EXISTS user_playlist_limits (
    user_id INTEGER PRIMARY KEY,
    daily_limit INTEGER NOT NULL,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

No row → use global `playlist_daily_limit`.

### `playlist_usage`

```sql
CREATE TABLE IF NOT EXISTS playlist_usage (
    user_id INTEGER NOT NULL,
    day TEXT NOT NULL,  -- YYYY-MM-DD in Europe/Moscow
    count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, day)
);
```

Increment by 1 only after a playlist item is successfully delivered to the user.

## Effective limits

**Playlist daily (user):**
1. If `user_id ∈ admin_user_ids` → unlimited
2. Else if row in `user_playlist_limits` → that `daily_limit`
3. Else → `playlist_daily_limit` from `bot_config` (default 50)

**Remaining today:** `max(0, effective_limit - usage(user, today_msk))` (unlimited → skip checks)

**Concurrent:** `bot_config.max_concurrent_per_user`; admins and `unlimited_user_ids` unchanged (always allowed).

## Playlist download flow

1. User picks type/quality → about to start `_download_playlist`.
2. Compute `selected = len(selected_entries)`, `remaining`.
3. If limited and `selected > remaining` → respond with refusal, **do not** start download:
   - Example: `⚠️ Выбрано 30, доступно 10 до конца дня (МСК). Уменьши выбор (исключения) или подожди завтра.`
4. Otherwise download as today.
5. After each **successful** send of one playlist item → `playlist_usage.count += 1` for today.
6. Rare race (usage jumps mid-job): stop further items with the same limit message; already sent items stay; cleanup as usual.

Optional: show `лимит: used/limit` in the playlist progress status for non-admins.

## Concurrent limiter

- `DownloadLimiter` reads effective max from DB (or caches value invalidated on `/setconcurrent` / admin menu set).
- First read with missing key: copy yaml default into `bot_config`, then use it.
- No process restart required.

## Admin surface

### Who

Only `admin_user_ids` from config (same as `/post`, `/setstorage`).

### Commands

| Command | Effect |
|---------|--------|
| `/admin` | Open admin menu (limits section in block A) |
| `/setconcurrent N` | Set global concurrent (`N ≥ 1`) |
| `/setplaylistlimit N` | Set global playlist daily default (`N ≥ 1`) |
| `/setuserlimit <user_id> N` | Per-user playlist daily override (`N ≥ 1`) |
| `/unsetuserlimit <user_id>` | Remove override (back to global) |

Invalid args → short usage hint. Non-admins → silent ignore or short deny (match existing admin command style in this bot).

### `/admin` menu (block A)

Show current:
- concurrent
- global playlist daily limit
- (optional) hint how to set user limit

Buttons / flows to set concurrent and playlist limit (prompt for number via reply or next message state). User-limit can be command-only in A if menu state is heavy — menu should at least link/document `/setuserlimit`.

Placeholders for later: Ban, Users (disabled or “скоро”) — only if it doesn’t confuse; otherwise omit until B/C.

## Errors / edge cases

| Case | Behavior |
|------|----------|
| `N` not int / `< 1` | Reject with usage |
| DB write fails | Log + tell admin; don’t apply half-state if avoidable |
| Usage increment fails after send | Log; user already has the file (don’t roll back send) |
| Admin runs playlist | No quota checks / no usage rows required |

## Modules (implementation sketch)

| Piece | Role |
|-------|------|
| `database.py` | Tables `user_playlist_limits`, `playlist_usage` |
| `repository.py` | get/set config keys; get/set/clear user limit; get/increment usage; `remaining_playlist_quota(user_id)` |
| `download_limiter.py` | Read concurrent from repo/DB |
| `handlers.py` | Gate in `_download_playlist`; `/admin` + limit commands; increment after successful playlist item send |
| Time helper | `today_msk() -> str` via `zoneinfo.ZoneInfo("Europe/Moscow")` |

## Manual test plan

1. Non-admin: set global limit to 3 via admin; select 5 → refusal; select 2 → OK; after 2 success, third job with 2 selected → refusal (remaining 1).
2. Usage only grows on success (force one failure → count unchanged).
3. `/setuserlimit <id> 100` → that user gets 100; `/unsetuserlimit` → back to global.
4. Admin user: unlimited regardless of usage rows.
5. `/setconcurrent 2` → third parallel download blocked for normal user; admin unrestricted.
6. Restart container → limits and today’s usage preserved.
