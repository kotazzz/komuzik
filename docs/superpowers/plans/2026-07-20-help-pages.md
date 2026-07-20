# Help pages + /info Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Постраничный `/help` (оглавление → разделы) с админ-веткой и отдельная команда `/info`.

**Architecture:** Тексты и кнопки в `help_pages.py`; `handlers.py` только шлёт/редактирует сообщения и проверяет админа/бан. Callback `help_*` редактирует то же сообщение.

**Tech Stack:** Python, Telethon `Button.inline` / `Button.url`, pytest.

**Spec:** `docs/superpowers/specs/2026-07-20-help-pages-design.md`

## Global Constraints

- Callback prefixes: `help_toc`, `help_u_<slug>`, `help_a_toc`, `help_a_<slug>`
- Admin button only when `is_admin=True` / `ADMIN_USER_IDS`
- `/help` ≠ `/info`
- User-facing copy in Russian
- Commit style: conventional Russian (`feat(help): …`)

---

### Task 1: `help_pages` module + unit tests

**Files:**
- Create: `src/komuzik/help_pages.py`
- Create: `tests/test_help_pages.py`

**Interfaces:**
- Produces:
  - `USER_SLUGS: tuple[str, ...]`
  - `ADMIN_SLUGS: tuple[str, ...]`
  - `INFO_GITHUB_URL: str` = `"https://github.com/kotazzz/komuzik"`
  - `INFO_TEXT: str` — тело `/info`
  - `def user_toc_text() -> str`
  - `def admin_toc_text() -> str`
  - `def user_page_text(slug: str) -> str` — KeyError if unknown
  - `def admin_page_text(slug: str) -> str`
  - `def user_toc_buttons(*, is_admin: bool) -> list` — Telethon button rows
  - `def admin_toc_buttons() -> list`
  - `def user_page_buttons() -> list` — только «← Назад» → `help_toc`
  - `def admin_page_buttons() -> list` — «← Назад» → `help_a_toc`
  - `def resolve_help_callback(data: str) -> tuple[str, str | None]`  
    returns `("user_toc"|"admin_toc"|"user_page"|"admin_page"|"unknown", slug|None)`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_help_pages.py
from komuzik.help_pages import (
    ADMIN_SLUGS,
    INFO_GITHUB_URL,
    INFO_TEXT,
    USER_SLUGS,
    admin_page_buttons,
    admin_page_text,
    admin_toc_buttons,
    admin_toc_text,
    resolve_help_callback,
    user_page_buttons,
    user_page_text,
    user_toc_buttons,
    user_toc_text,
)


def _button_data(rows) -> set[bytes]:
    out = set()
    for row in rows:
        for btn in row:
            data = getattr(btn, "data", None)
            if data is not None:
                out.add(data)
    return out


def test_user_toc_no_admin_button():
    data = _button_data(user_toc_buttons(is_admin=False))
    assert b"help_a_toc" not in data
    for slug in USER_SLUGS:
        assert f"help_u_{slug}".encode() in data


def test_user_toc_admin_button():
    data = _button_data(user_toc_buttons(is_admin=True))
    assert b"help_a_toc" in data


def test_pages_nonempty_and_callback_len():
    assert user_toc_text().strip()
    assert admin_toc_text().strip()
    for slug in USER_SLUGS:
        assert user_page_text(slug).strip()
        assert len(f"help_u_{slug}") <= 64
    for slug in ADMIN_SLUGS:
        assert admin_page_text(slug).strip()
        assert len(f"help_a_{slug}") <= 64


def test_key_commands_mentioned():
    cmds = user_page_text("commands")
    for cmd in ("/report", "/info", "/settings", "/search", "/stats", "/privacy"):
        assert cmd in cmds
    assert "/admin" in admin_page_text("panel")
    assert "/ban" in admin_page_text("bans")
    assert "/setstorage" in admin_page_text("storage")
    assert "/post" in admin_page_text("post")


def test_info_constants():
    assert INFO_GITHUB_URL == "https://github.com/kotazzz/komuzik"
    assert "Kotaz" in INFO_TEXT
    assert "/report" in INFO_TEXT
    assert INFO_GITHUB_URL in INFO_TEXT


def test_resolve_callback():
    assert resolve_help_callback("help_toc") == ("user_toc", None)
    assert resolve_help_callback("help_a_toc") == ("admin_toc", None)
    assert resolve_help_callback("help_u_inline") == ("user_page", "inline")
    assert resolve_help_callback("help_a_limits") == ("admin_page", "limits")
    assert resolve_help_callback("help_u_nope") == ("unknown", None)


def test_back_buttons():
    assert b"help_toc" in _button_data(admin_toc_buttons())
    assert b"help_toc" in _button_data(user_page_buttons())
    assert b"help_a_toc" in _button_data(admin_page_buttons())
```

- [ ] **Step 2: Run tests — expect FAIL**

Run: `uv run pytest tests/test_help_pages.py -q`  
Expected: import error / missing module

- [ ] **Step 3: Implement `help_pages.py`**

Create `src/komuzik/help_pages.py` with:

- `USER_SECTIONS`: list of `(slug, button_label, markdown_body)` for start/platforms/playlists/inline/groups/commands — detailed Russian copy (YouTube quality, playlists exclusions/batches/stop/daily limit, inline prefixes, group settings, commands list). Mention `/info` on toc and in commands.
- `ADMIN_SECTIONS`: panel/limits/bans/users/storage/post with command examples matching real handlers.
- Builders using `Button.inline(label, data=...)`.
- `admin_toc_buttons`: section buttons + row `[Button.inline("← Назад", data="help_toc")]`.
- `INFO_TEXT` and `INFO_GITHUB_URL`.
- `resolve_help_callback` as above; unknown slug → `("unknown", None)`.

- [ ] **Step 4: Run tests — expect PASS**

Run: `uv run pytest tests/test_help_pages.py -q`  
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add src/komuzik/help_pages.py tests/test_help_pages.py
git commit -m "feat(help): модуль страниц справки и /info текст"
```

---

### Task 2: Wire `/help`, `/info`, callbacks in handlers

**Files:**
- Modify: `src/komuzik/handlers.py` (imports, `__init__` handlers, `help_handler`, new `info_handler`, `callback_handler` branch)
- Modify: `README.md` (commands list only)
- Optional: leave `MSG_HELP` / `config.yaml` help unused

**Interfaces:**
- Consumes: all Task 1 exports
- Uses: `self._is_bot_admin(user_id)`, `_reject_if_banned`, `event.respond` / `event.edit` / `event.answer`

- [ ] **Step 1: Register `/info` and rewrite `help_handler`**

In `__init__` next to `/help`:

```python
self.client.on(events.NewMessage(pattern=r"^/info(?:@\w+)?"))(self.info_handler)
```

Replace `help_handler` body after ban/track:

```python
is_admin = self._is_bot_admin(user_id) if user_id else False
await event.respond(
    user_toc_text(),
    buttons=user_toc_buttons(is_admin=is_admin),
    link_preview=False,
)
```

Add `info_handler`:

```python
async def info_handler(self, event: Message):
    user_id, _ = self._get_user_info(event)
    if await self._reject_if_banned(
        event, user_id, chat_is_group=bool(getattr(event, "is_group", False))
    ):
        return
    self._track_user(event)
    await event.respond(
        INFO_TEXT,
        buttons=[[Button.url("Исходный код", INFO_GITHUB_URL)]],
        link_preview=False,
    )
```

Remove unused `MSG_HELP` import if no longer referenced.

- [ ] **Step 2: Add `_handle_help_callback`**

```python
async def _handle_help_callback(self, event, data: str) -> None:
    user_id = cast("int | None", event.sender_id)
    kind, slug = resolve_help_callback(data)
    is_admin = bool(user_id and self._is_bot_admin(user_id))

    if kind in {"admin_toc", "admin_page"} and not is_admin:
        await event.answer("Нет доступа.", alert=True)
        return

    try:
        if kind == "user_toc":
            text, buttons = user_toc_text(), user_toc_buttons(is_admin=is_admin)
        elif kind == "admin_toc":
            text, buttons = admin_toc_text(), admin_toc_buttons()
        elif kind == "user_page" and slug is not None:
            text, buttons = user_page_text(slug), user_page_buttons()
        elif kind == "admin_page" and slug is not None:
            text, buttons = admin_page_text(slug), admin_page_buttons()
        else:
            await event.answer()
            return
    except KeyError:
        await event.answer()
        return

    await event.edit(text, buttons=buttons, link_preview=False)
    await event.answer()
```

In `callback_handler`, after ban check:

```python
if data.startswith("help_"):
    await self._handle_help_callback(event, data)
    return
```

- [ ] **Step 3: Update README commands**

Under available commands add `/info`; note that `/help` is sectioned.

- [ ] **Step 4: Run unit tests**

Run: `uv run pytest tests/test_help_pages.py -q`  
Expected: PASS

- [ ] **Step 5: Commit + push + deploy**

```bash
git add src/komuzik/handlers.py README.md
git commit -m "feat(help): постраничный /help и команда /info"
git push origin HEAD
```

Manual smoke: `/help` → разделы → назад; админом — «Для админа»; `/info` — GitHub + Kotaz + `/report`.

---

## Spec coverage check

| Spec item | Task |
|-----------|------|
| User TOC + pages + back | 1–2 |
| Admin button + admin TOC/pages | 1–2 |
| Callback names | 1–2 |
| Ban on /help /info | 2 |
| Non-admin admin callback | 2 |
| /info separate | 2 |
| Tests for buttons/slugs/commands | 1 |
| README | 2 |
