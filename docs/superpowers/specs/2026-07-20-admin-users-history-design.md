# Admin users & download history (block C) — design

## Goal

Bot admins can browse known users (id, display name, profile link) and a short download history per user. New statistics rows store `url` + `title` for markdown links; older rows stay brief without links.

## Locked decisions

| Topic | Choice |
|-------|--------|
| History media fields | Add nullable `url`, `title` on `statistics`; **new** downloads only |
| Old rows | Show without link: `platform · type quality` |
| User list UX | `/users` paginated (~15) → click user → history |
| Also | `/user <id>` opens history; `/admin` → «👥 Пользователи» |
| History depth | Last **50** downloads, **10** per page |

## Scope

**In**
- Migrate `statistics` + optional `users.display_name`
- Pass `url`/`title` into `track_*_download` from handlers when available
- Admin-only `/users`, `/user`, `/admin` button, callback pagination
- History lines for video/audio/tiktok/twitter/pinterest download events

**Out**
- Username search / CSV export
- Search-event history
- Backfilling titles for old rows

## Data

### `statistics` (migration)

```sql
-- via _ensure_column
url TEXT
title TEXT
```

`_track_event(..., url=None, title=None)` writes them.

### `users`

```sql
display_name TEXT  -- nullable; first + last name when known
```

`track_user(user_id, username=None, display_name=None)` updates `display_name` when provided.

## Display

### User list row / button

- Label: `{display_name or '—'} (@username)` or `{id}` if no names
- Message line may include `[профиль](tg://user?id={id})`
- Sort: `last_seen DESC`
- Page size: **15**

### History line (Markdown)

With title+url:

`• [Title](url) · youtube · video 720p · 20.07 16:10`

Audio:

`• [Title](url) · youtube · audio high · …`

Without url/title:

`• youtube · video 720p · …`

Failed: prefix `✗ ` (and still show type/quality if present).

Escape markdown in titles (`[`, `]`, `(`, `)`) or strip to safe text.

Event types included: `video_download`, `audio_download`, `tiktok_download`, `twitter_download` / pinterest equivalents as stored today.

## Admin UX

### `/users`

1. Edit/respond with page of users + inline buttons (one per user) + prev/next.
2. Callback `admin_user_<id>` → history page 0.
3. Callbacks `admin_users_p_<n>` for list pages.

### History view

- Header: id, display_name, @username, profile link, ban flag if banned.
- 10 lines of history; `admin_hist_<id>_p_<n>`; button «← К списку».
- Cap query at 50 newest matching events for that `user_id`.

### `/user <id>`

Same history view (page 0). Invalid id → usage. Unknown user with no stats → «Нет данных».

### `/admin`

Button `👥 Пользователи` → same as `/users` page 0.

Silent ignore for non-admins (existing pattern).

## Writing url/title

Update repository `track_video_download` / `track_audio_download` / tiktok / twitter / pinterest to accept optional `url`, `title`.

Update call sites in `handlers.py` (and playlist loop) to pass:
- YouTube: page URL + metadata title
- Others: source URL + title when metadata has it

Failures: still pass url/title when known so history shows the attempt.

## Modules

| Piece | Role |
|-------|------|
| `database.py` | ensure `url`, `title`, `display_name` |
| `repository.py` | track args; `list_users(offset,limit)`; `list_user_downloads(user_id, offset, limit)` |
| `handlers.py` | `/users`, `/user`, callbacks, `/admin` button; pass url/title; enrich `track_user` with display_name |
| Tests | list pagination math; history formatting helper; migration smoke |

## Manual test plan

1. Download a YouTube video → `/user <you>` shows titled link + `video 720p`.
2. Old downloads (if any) appear without link.
3. `/users` pages; open another user; history next page.
4. `/admin` → Users opens list.
5. Non-admin: silent on `/users`.
6. Banned user still listed; header notes ban.
