# Admin Limits (Block A) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enforce Moscow-time daily playlist quotas (default 50, successful sends only) and let bot admins change concurrent + playlist limits at runtime via `/admin` and commands.

**Architecture:** Persist limits and usage in SQLite (`bot_config`, `user_playlist_limits`, `playlist_usage`). Repository exposes quota helpers. `DownloadLimiter` reads concurrent from DB. Handlers gate playlist start and increment usage after each successful item send.

**Tech Stack:** Python 3.11, Telethon, SQLite, `zoneinfo.ZoneInfo("Europe/Moscow")`, Docker deploy on `me`.

## Global Constraints

- Count only **successfully sent** playlist items toward daily quota.
- Refuse start if `selected > remaining` (no partial start).
- Day boundary: **Europe/Moscow** (`YYYY-MM-DD`).
- Bot `admin_user_ids`: unlimited playlist + unlimited concurrent.
- Default global playlist daily limit: **50**.
- Ban / user list / history: **out of scope** (blocks B/C).
- Spec: `docs/superpowers/specs/2026-07-20-admin-limits-design.md`.
- Commits: conventional Russian (`feat(admin): …`); push after chunks.

---

## File map

| File | Role |
|------|------|
| Modify `src/komuzik/database.py` | Tables `user_playlist_limits`, `playlist_usage` |
| Modify `src/komuzik/repository.py` | Config keys, user limits, usage, remaining quota |
| Create `src/komuzik/timeutil.py` | `today_msk() -> str` |
| Modify `src/komuzik/download_limiter.py` | Concurrent from DB (+ optional invalidate) |
| Modify `src/komuzik/handlers.py` | Gate, increment, `/admin`, limit commands |
| Create `tests/test_playlist_quota.py` | Unit tests for day/quota math |

Wire: if `DownloadLimiter` needs `StatsRepository`, pass it from bot startup (find where limiter is constructed — likely `main` / app init).

---

### Task 1: Schema + `today_msk` + repository quota API

**Files:**
- Create: `src/komuzik/timeutil.py`
- Modify: `src/komuzik/database.py`
- Modify: `src/komuzik/repository.py`
- Create: `tests/test_playlist_quota.py`

**Interfaces (produces):**
- `today_msk() -> str`
- `StatsRepository.get_bot_config_int(key: str, default: int) -> int`
- `StatsRepository.set_bot_config_int(key: str, value: int) -> None`
- `StatsRepository.get_playlist_daily_limit() -> int`  # global, default 50
- `StatsRepository.set_playlist_daily_limit(n: int) -> None`
- `StatsRepository.get_max_concurrent() -> int`  # seed from yaml default if missing
- `StatsRepository.set_max_concurrent(n: int) -> None`
- `StatsRepository.get_user_playlist_limit(user_id: int) -> int | None`
- `StatsRepository.set_user_playlist_limit(user_id: int, n: int) -> None`
- `StatsRepository.clear_user_playlist_limit(user_id: int) -> None`
- `StatsRepository.get_playlist_usage(user_id: int, day: str | None = None) -> int`
- `StatsRepository.increment_playlist_usage(user_id: int, amount: int = 1) -> None`
- `StatsRepository.effective_playlist_limit(user_id: int, *, is_admin: bool) -> int | None`  # None = unlimited
- `StatsRepository.remaining_playlist_quota(user_id: int, *, is_admin: bool) -> int | None`  # None = unlimited

Keys: `max_concurrent_per_user`, `playlist_daily_limit` (same style as `STORAGE_CHAT_ID_KEY`).

- [ ] **Step 1: `timeutil.py`**

```python
from datetime import datetime
from zoneinfo import ZoneInfo

MSK = ZoneInfo("Europe/Moscow")

def today_msk() -> str:
    return datetime.now(MSK).strftime("%Y-%m-%d")
```

- [ ] **Step 2: Create tables in `database.py` `_create_tables`**

Exact SQL from the spec for `user_playlist_limits` and `playlist_usage`.

- [ ] **Step 3: Repository methods**

Follow existing `get_storage_chat_id` / `set_storage_chat_id` patterns. For `get_max_concurrent`: if key missing, use default passed in (caller supplies yaml seed) or hardcode reading via optional `default` arg and `set` on miss.

`effective_playlist_limit`: if `is_admin` → `None`; else user override or global (default 50).

`remaining_playlist_quota`: if effective is `None` → `None`; else `max(0, effective - get_playlist_usage(...))`.

`increment_playlist_usage`: upsert `count = count + amount` for `(user_id, today_msk())`.

- [ ] **Step 4: Tests**

```python
def test_remaining_quota_and_increment():
    # temp DB, repo not admin, global 50
    # usage 0 → remaining 50
    # increment 3 → remaining 47
    # set_user_playlist_limit(uid, 10) → remaining 7
    # clear → remaining 47
    # is_admin True → remaining None
```

Also assert `today_msk()` matches `YYYY-MM-DD` regex.

- [ ] **Step 5: `uv run pytest tests/test_playlist_quota.py -v` → PASS**

- [ ] **Step 6: Commit** `feat(admin): квоты плейлиста в SQLite (МСК)`

---

### Task 2: `DownloadLimiter` reads concurrent from DB

**Files:**
- Modify: `src/komuzik/download_limiter.py`
- Modify: bot wiring (wherever `DownloadLimiter(...)` is created) to pass `stats_repo` or a getter

**Interfaces:**
- Consumes: `StatsRepository.get_max_concurrent()` / `set_max_concurrent` with yaml seed
- Produces: `max_per_user` property that reads DB each call (or cache + `invalidate_concurrent_cache()`)

- [ ] **Step 1: Find constructor site** (`grep DownloadLimiter` in repo)

- [ ] **Step 2: Inject repository**

On init, keep yaml as `_yaml_concurrent`. Method:

```python
def get_max_per_user(self) -> int:
    if self._stats is None:
        return self._yaml_concurrent
    return self._stats.get_max_concurrent(default=self._yaml_concurrent)
```

Use `get_max_per_user()` inside `can_download` / messages instead of frozen `MAX_DOWNLOADS_PER_USER` (keep attribute as property alias for compatibility).

- [ ] **Step 3: Smoke** — unit or manual: set DB concurrent to 1, `can_download` false when 1 active (mock active set).

- [ ] **Step 4: Commit** `feat(admin): concurrent из bot_config`

---

### Task 3: Gate playlist start + increment on success

**Files:**
- Modify: `src/komuzik/handlers.py` — `_download_playlist` / `flush_batch`

- [ ] **Step 1: Before download loop** (after `entries = selected_entries`, before `start_download` limit check is fine either order — prefer quota check **before** registering concurrent slot):

```python
is_admin = user_id in self.download_limiter.ADMIN_USER_IDS
remaining = self.stats.remaining_playlist_quota(user_id, is_admin=is_admin)
if remaining is not None and len(entries) > remaining:
    await event.edit(
        f"⚠️ Выбрано {len(entries)}, доступно {remaining} до конца дня (МСК). "
        "Уменьши выбор (исключения) или подожди завтра."
    )
    return
```

- [ ] **Step 2: After successful delivery**

Increment **per successfully delivered item**, not per batch blindly:
- Storage path: after `delivered` known → `increment_playlist_usage(user_id, delivered)` (skip if admin)
- Album/singles path: after successful `send_playlist_album` → `increment_playlist_usage(user_id, len(batch))`

Do **not** increment on failed batch.

- [ ] **Step 3: Optional progress line** for non-admins: `лимит: used/limit` in status text.

- [ ] **Step 4: Commit** `feat(admin): суточная квота плейлиста при скачивании`

---

### Task 4: Admin commands + `/admin` limits menu

**Files:**
- Modify: `src/komuzik/handlers.py`

**Commands:** register near other admin commands:
- `/admin`
- `/setconcurrent N`
- `/setplaylistlimit N`
- `/setuserlimit <user_id> N`
- `/unsetuserlimit <user_id>`

- [ ] **Step 1: Shared admin guard** — silent return if not in `ADMIN_USER_IDS` (match `/setstorage`).

- [ ] **Step 2: Parse helpers** — require `N >= 1` int; bad args → usage string.

- [ ] **Step 3: Command handlers** call repository setters; confirm with new values. `/setconcurrent` also refreshes limiter cache if any.

- [ ] **Step 4: `/admin` message**

```
🛠 Админ-панель

Одновременных загрузок: {concurrent}
Плейлист / сутки (глобально): {playlist_limit}

Персональный лимит: /setuserlimit <id> N
Сброс: /unsetuserlimit <id>
```

Buttons (inline):
- `⚙️ Concurrent` → `admin_set_concurrent` (ask next message / reply with number — simple pending state dict `ADMIN_PENDING[user_id] = "concurrent"|"playlist"`)
- `📺 Playlist limit` → same for playlist
- Or skip interactive and only show commands in block A — **prefer buttons that set `ADMIN_PENDING` and next DM number applies**.

- [ ] **Step 5: In `message_handler`**, if admin and `ADMIN_PENDING` set and text is int → apply, clear pending, confirm. Must not steal URLs/playlist links — only pure integer messages.

- [ ] **Step 6: Commit** `feat(admin): /admin и команды лимитов`

---

### Task 5: Deploy + manual verification

- [ ] **Step 1:** `git push` + `ssh me 'cd ~/komuzik && git pull && docker compose build && docker compose up -d'`

- [ ] **Step 2:** Manual checklist from spec (limit 3, refuse, user override, admin unlimited, concurrent, restart persistence).

---

## Spec coverage

| Spec item | Task |
|-----------|------|
| Tables + МСК day | 1 |
| Effective / remaining / increment | 1, 3 |
| Refuse if selected > remaining | 3 |
| Concurrent from DB | 2, 4 |
| `/admin` + commands | 4 |
| Admin unlimited | 1, 3 |
| Deploy / manual | 5 |

## Self-review

- No TBD.
- Increment amount matches delivered count (storage partial OK).
- Ban/users not in this plan.
