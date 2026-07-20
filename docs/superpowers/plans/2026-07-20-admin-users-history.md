# Admin Users & History (Block C) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Admin `/users` + `/user <id>` + `/admin` entry to browse users and last 50 downloads (10/page) with url/title links when available.

**Architecture:** Migrate `statistics.url/title` and `users.display_name`. Extend track_* APIs and call sites. Repository list helpers. Handlers for admin UX.

**Tech Stack:** Python 3.11, Telethon, SQLite.

## Global Constraints

- History: last **50**, **10**/page; user list **15**/page.
- Old rows without url/title: brief line without link.
- Admin only; silent non-admin.
- Spec: `docs/superpowers/specs/2026-07-20-admin-users-history-design.md`.
- Commits: `feat(admin): …`; push; deploy at end.

---

## File map

| File | Role |
|------|------|
| `database.py` | ensure url, title, display_name |
| `repository.py` | track args; list_users; list_user_downloads; format helpers optional |
| `handlers.py` | /users, /user, callbacks, admin button; pass url/title; display_name on track_user |
| `tests/test_admin_users_history.py` | list + format unit tests |

---

### Task 1: Migration + track API + list queries

- [ ] `_ensure_column` for `statistics.url`, `statistics.title`, `users.display_name`
- [ ] `_track_event` + all `track_*_download` accept optional `url`, `title`
- [ ] `track_user(..., display_name=None)` upsert display_name
- [ ] `list_users(offset, limit) -> list[dict]` (id, username, display_name, last_seen)
- [ ] `count_users() -> int`
- [ ] `list_user_downloads(user_id, offset, limit) -> list[dict]` (newest first; filter download event types; caller caps at 50)
- [ ] `count_user_downloads(user_id) -> int` (capped or raw; use min(50, count) in UI)
- [ ] Tests for list empty / insert with url
- [ ] Commit: `feat(admin): url/title в statistics и списки юзеров`

---

### Task 2: Format helpers + wire track call sites

- [ ] `format_download_history_line(row) -> str` (markdown; escape title)
- [ ] `format_user_label(user) -> str`
- [ ] Update handlers `track_*` / `_track_user` to pass url, title, display_name where available (DM, inline, playlist items, groups)
- [ ] Commit: `feat(admin): писать url/title при загрузках`

---

### Task 3: Admin UX + deploy

- [ ] `/users` paginated 15; callbacks `admin_users_p_<n>`, `admin_user_<id>`
- [ ] History view 10/page, max 50; `admin_hist_<id>_p_<n>`; back to list
- [ ] `/user <id>`
- [ ] `/admin` button «👥 Пользователи»
- [ ] Ban note in history header if `get_ban`
- [ ] Commit: `feat(admin): /users и история загрузок`
- [ ] Push + deploy `me`

---

## Spec coverage

| Item | Task |
|------|------|
| Columns + track | 1–2 |
| List / history queries | 1 |
| Formatting | 2 |
| /users /user /admin | 3 |

## Manual test

Per design doc checklist.
