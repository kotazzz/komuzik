# Chat settings Implementation Plan

> Spec: `docs/superpowers/specs/2026-07-20-chat-settings-design.md`

**Goal:** Group `/settings` for platform toggles + captions; enforce in group downloads.

**Files:** `database.py`, `repository.py`, `handlers.py`

### Task 1: Schema + repository
- [ ] `chat_settings` table
- [ ] `ChatSettings` dataclass, get/upsert/toggle

### Task 2: Settings UI + admin check
- [ ] Branch `/settings` private vs group
- [ ] Admin gate + inline toggles `chatset_*`

### Task 3: Enforce in group downloads
- [ ] Platform allow check before download
- [ ] Captions from chat settings
