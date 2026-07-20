# Group auto-download Implementation Plan

> **For agentic workers:** Implement task-by-task. Spec: `docs/superpowers/specs/2026-07-20-group-auto-download-design.md`

**Goal:** In groups, auto-download supported links (with inline-style prefixes) and reply with media; DM unchanged.

**Architecture:** Reuse `parse_inline_query` + `_download_for_inline`. Branch group vs private in `message_handler`. Add `reply_to` to send helpers. Stats `source=group`.

**Tech Stack:** Telethon, existing downloaders, SQLite stats.

## Global Constraints

- Phase 1 only (no chat settings / default quality UI / last-format button)
- Group YouTube default: 720p (via existing parser)
- Silent ignore when no URL; error reply on failure
- Rate limit per message author

---

### Task 1: `reply_to` on send helpers

**Files:** `src/komuzik/downloaders.py`

- [ ] Add optional `reply_to: int | None = None` to `send_video_content`, `send_audio_content`, `send_image_content`
- [ ] Pass through to `event.respond(..., reply_to=reply_to)`

### Task 2: Group message handler

**Files:** `src/komuzik/handlers.py`

- [ ] After report/state handling, if `event.is_group`: call `_handle_group_link_message` and return
- [ ] Private path: keep current behavior (including invalid-link error)
- [ ] `_handle_group_link_message`: `parse_inline_query` → silent if None → limit check → processing reply → `_download_for_inline` → send with `reply_to=message.id` → track `source=group` → cleanup
- [ ] Reuse/generalize `_track_inline_download` to accept `source` param (or add `_track_parsed_download`)

### Task 3: Docs ops note + commit/deploy

- [ ] Mention BotFather `/setprivacy` Disable in design (already) / short ops note if needed
- [ ] Commit, push, deploy
