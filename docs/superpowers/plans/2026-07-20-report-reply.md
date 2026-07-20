# Report reply Implementation Plan

> **For agentic workers:** `database.py` → `repository.py` → `handlers.py` → commit/push/deploy.

**Goal:** Reply на сообщения репорта → копия ответа юзеру с `reply_to` его репорта.

**Files:**
- `src/komuzik/database.py` — таблица `report_threads`
- `src/komuzik/repository.py` — save/lookup
- `src/komuzik/handlers.py` — отправка репорта + обработка reply админа

## Task 1: DB + repository

Create table + `save_report_thread` / `get_report_thread_by_admin_msg`.

## Task 2: Handlers

- При отправке репорта сохранять оба msg id.
- В `message_handler` (до report state): если админ + reply_to → lookup → copy → confirm.
