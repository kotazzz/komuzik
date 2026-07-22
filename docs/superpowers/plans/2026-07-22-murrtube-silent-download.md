# Silent HLS host download Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Скачивать видео по ссылкам `murrtube.net/v/…` в best-качестве в ЛС, inline и группах, без UI/help/настроек и без пользовательских упоминаний хоста; yt-dlp — с форка `kotazzz/yt-dlp@fix/murrtube-extractor`.

**Architecture:** Как TikTok: regex → `parse_inline_query` (`platform="hls_host"`) → `download_hls_host_video` (`format: best`) → send. Группы уже пропускают неизвестные `allow_*` (`allows_platform → True`). Внутренний ключ `hls_host`; в админ-истории подпись платформы пустая.

**Tech Stack:** Telethon, yt-dlp (git fork), uv, pytest.

**Spec:** `docs/superpowers/specs/2026-07-22-murrtube-silent-download-design.md`

## Global Constraints

- Пользовательские тексты (help, /start, README features, chat settings, status/error/inline description) **не называют** хост и не рекламируют поддержку
- Качество только best / auto; без кнопок выбора
- Нет `allow_hls_host` / тумблера в настройках чата
- `messages.yaml` → `help.platforms` **не менять**
- Упоминание хоста допустимо в коммитах и в `docs/yt-dlp-fork.md`
- Коммиты в стиле репозитория (`feat:` / `fix:` / `docs:` / `chore:`), без выдуманного JIRA

## File map

| File | Role |
|------|------|
| `pyproject.toml`, `uv.lock` | git-источник yt-dlp |
| `docs/yt-dlp-fork.md` | зачем форк, PR #17285, когда вернуться на PyPI |
| `src/komuzik/config.py` | `HLS_HOST_REGEX`, generic error |
| `messages.yaml` | `errors.download` (нейтральный) |
| `src/komuzik/inline_query.py` | парсинг URL → `hls_host` |
| `src/komuzik/downloaders.py` | `download_hls_host_video` |
| `src/komuzik/handlers.py` | DM handler + inline/group wiring |
| `src/komuzik/repository.py` | `_history_platform_label("hls_host") → ""` |
| `tests/test_inline_search.py` | парсер |
| `tests/test_admin_users_history.py` | пустая подпись в истории |

---

### Task 1: yt-dlp fork dependency + ops note

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock` (via `uv lock`)
- Create: `docs/yt-dlp-fork.md`

**Interfaces:**
- Produces: установленный пакет `yt_dlp` с рабочим extractor для `murrtube.net` из ветки форка

- [ ] **Step 1: Point yt-dlp at the fork branch**

In `pyproject.toml` replace the PyPI pin:

```toml
dependencies = [
    "gallery-dl>=1.31.10",
    "pillow>=12.3.0",
    "pyrogram>=2.0.106",
    "python-dotenv>=1.2.2",
    "pyyaml>=6.0.3",
    "telethon>=1.42.0",
    "tgcrypto>=1.2.5",
    "yt-dlp",
]
```

Keep `[tool.uv] package = false` and add:

```toml
[tool.uv.sources]
yt-dlp = { git = "https://github.com/kotazzz/yt-dlp.git", branch = "fix/murrtube-extractor" }
```

- [ ] **Step 2: Refresh lock and sync**

```bash
uv lock
uv sync
```

Expected: `uv.lock` lists yt-dlp from GitHub (`kotazzz/yt-dlp`, rev of `fix/murrtube-extractor`), not files.pythonhosted.org.

- [ ] **Step 3: Smoke-check extractor from the fork**

```bash
uv run yt-dlp -F "https://murrtube.net/v/BS0W"
```

Expected: список форматов (как в пользовательском логе), без `TypeError` / extract failure.

- [ ] **Step 4: Write `docs/yt-dlp-fork.md`**

```markdown
# yt-dlp: временный форк

## Почему не PyPI

Extractor Murrtube в upstream сломан после перехода сайта на Inertia.js
(`data-page` JSON вместо `<video id="video">`).

## Что используем

- Репозиторий: https://github.com/kotazzz/yt-dlp
- Ветка: `fix/murrtube-extractor`
- Upstream PR: https://github.com/yt-dlp/yt-dlp/pull/17285

Источник задан в `pyproject.toml` → `[tool.uv.sources]`.

## Когда вернуться на оригинал

1. Проверить, что PR #17285 (или эквивалент) **merged**.
2. Дождаться релиза yt-dlp на PyPI с этим фиксом.
3. Убрать `[tool.uv.sources]` для yt-dlp, вернуть `"yt-dlp>=…"`, `uv lock` / `uv sync`.
4. Удалить или обновить этот файл.
```

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock docs/yt-dlp-fork.md
git commit -m "$(cat <<'EOF'
chore(deps): yt-dlp с форка fix/murrtube-extractor

EOF
)"
git push
```

---

### Task 2: URL parse + silent history label (TDD)

**Files:**
- Modify: `src/komuzik/config.py`
- Modify: `src/komuzik/inline_query.py`
- Modify: `src/komuzik/repository.py` (`_history_platform_label`)
- Test: `tests/test_inline_search.py`
- Test: `tests/test_admin_users_history.py`

**Interfaces:**
- Produces: `HLS_HOST_REGEX`; `parse_inline_query` → `ParsedInlineQuery(platform="hls_host", mode="video", quality="best", description="Видео")`; `_history_platform_label("hls_host") == ""`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_inline_search.py`:

```python
def test_hls_host_url_parses_silently():
    job = parse_inline_query("https://murrtube.net/v/BS0W")
    assert job is not None
    assert job.platform == "hls_host"
    assert job.mode == "video"
    assert job.quality == "best"
    assert job.description == "Видео"
    assert "murr" not in job.description.lower()


def test_hls_host_url_without_scheme():
    job = parse_inline_query("murrtube.net/v/BS0W")
    assert job is not None
    assert job.platform == "hls_host"
    assert job.url.startswith("https://")
```

Append to `tests/test_admin_users_history.py`:

```python
from komuzik.repository import _history_platform_label


def test_hls_host_history_label_is_blank():
    assert _history_platform_label("hls_host") == ""
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
uv run pytest tests/test_inline_search.py::test_hls_host_url_parses_silently tests/test_inline_search.py::test_hls_host_url_without_scheme tests/test_admin_users_history.py::test_hls_host_history_label_is_blank -v
```

Expected: FAIL (нет regex / ветки / label).

- [ ] **Step 3: Add regex in `config.py`**

Next to other URL regexes:

```python
HLS_HOST_REGEX = re.compile(
    r"(https?://)?(www\.)?murrtube\.net/v/([A-Za-z0-9_-]+)"
)
```

- [ ] **Step 4: Wire `inline_query.py`**

Import `HLS_HOST_REGEX` from `.config`.

In `parse_inline_query`, include `HLS_HOST_REGEX` in the token scan and fallback loop (same places as TikTok/Twitter/Pinterest).

Before TikTok/Twitter branches (or after them, but before YouTube), add:

```python
    if HLS_HOST_REGEX.search(url_token):
        return ParsedInlineQuery(
            url=url_token,
            platform="hls_host",
            mode="video",
            quality="best",
            description="Видео",
        )
```

- [ ] **Step 5: Blank admin label**

In `_history_platform_label`:

```python
def _history_platform_label(platform: str | None) -> str:
    key = (platform or "").strip().lower()
    if key == "hls_host":
        return ""
    labels = {
        "youtube": "Ютуб",
        "youtube_shorts": "Ютуб шортс",
        "tiktok": "ТикТок",
        "twitter": "Твиттер",
        "pinterest": "Пинтерест",
    }
    return labels.get(key, platform.strip() if platform else "")
```

- [ ] **Step 6: Run tests — expect PASS**

```bash
uv run pytest tests/test_inline_search.py tests/test_admin_users_history.py::test_hls_host_history_label_is_blank -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/komuzik/config.py src/komuzik/inline_query.py src/komuzik/repository.py tests/test_inline_search.py tests/test_admin_users_history.py
git commit -m "$(cat <<'EOF'
feat: парсинг hls_host URL без упоминания в UI

EOF
)"
git push
```

---

### Task 3: Downloader + neutral error copy

**Files:**
- Modify: `messages.yaml` (`errors.download`)
- Modify: `src/komuzik/config.py` (`HLS_HOST_ERROR_MESSAGE` / retries optional)
- Modify: `src/komuzik/downloaders.py`

**Interfaces:**
- Consumes: `YDLP_BASE_OPTS`, `HLS_HOST_ERROR_MESSAGE`
- Produces: `async def download_hls_host_video(url: str, max_retries: int | None = None) -> tuple[str, dict]`

- [ ] **Step 1: Neutral error string**

In `messages.yaml` under `errors:` add (no host name):

```yaml
  download: |-
    Не удалось скачать это видео. Проверьте ссылку или попробуйте позже.
```

In `config.py`:

```python
HLS_HOST_ERROR_MESSAGE = t("errors.download")
HLS_HOST_MAX_RETRIES = 3
HLS_HOST_RETRY_BACKOFF = 2
```

(Do **not** add a `murrtube:` / host-named key in `messages.yaml`.)

- [ ] **Step 2: Implement `download_hls_host_video`**

Mirror `download_tiktok_video`, but:

- `format`: `"best"`
- size-limit labels / log lines: `"video"` / `"hls_host"` (no brand in user-raised exceptions)
- on exhausted extract retries: `raise Exception(HLS_HOST_ERROR_MESSAGE)`
- other `DownloadError`: `raise Exception(HLS_HOST_ERROR_MESSAGE)` (keep user text neutral; details only in `logger`)

Sketch:

```python
async def download_hls_host_video(url: str, max_retries: int | None = None) -> tuple[str, dict]:
    retries = _safe_int(max_retries, _safe_int(HLS_HOST_MAX_RETRIES, 3))
    retries = max(1, retries)
    temp_dir = tempfile.mkdtemp()
    cleanup_on_error = True
    last_error = None

    for attempt in range(retries):
        try:
            loop = asyncio.get_running_loop()
            ydl_opts = {
                **YDLP_BASE_OPTS,
                "format": "best",
                "outtmpl": f"{temp_dir}/%(id)s.%(ext)s",
            }
            with yt_dlp.YoutubeDL(cast("Any", ydl_opts)) as ydl:
                info = cast(
                    "dict[str, Any]",
                    await loop.run_in_executor(None, ydl.extract_info, url, False),
                )
                _ensure_size_within_limit(_get_expected_size(info), "video")
                await loop.run_in_executor(None, ydl.download, [url])

            file_path = _find_downloaded_file(temp_dir)
            _ensure_file_within_limit(file_path, "video")
            metadata = {
                "title": info.get("title") or info.get("description") or "",
                "duration": _safe_int(info.get("duration"), 0),
                "width": info.get("width", 0),
                "height": info.get("height", 0),
            }
            cleanup_on_error = False
            return file_path, metadata
        except DownloadTooLargeError:
            if cleanup_on_error and os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
            raise
        except DownloadError as e:
            last_error = e
            if attempt < retries - 1:
                await asyncio.sleep(HLS_HOST_RETRY_BACKOFF**attempt)
                continue
            logger.error("hls_host download failed after retries: %s url=%s", e, url)
            if cleanup_on_error and os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
            raise Exception(HLS_HOST_ERROR_MESSAGE)
        except Exception as e:
            last_error = e
            logger.error("hls_host download error: %s", e)
            if cleanup_on_error and os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
            raise Exception(HLS_HOST_ERROR_MESSAGE)

    if cleanup_on_error and os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)
    raise Exception(HLS_HOST_ERROR_MESSAGE)
```

Import `HLS_HOST_ERROR_MESSAGE`, `HLS_HOST_MAX_RETRIES`, `HLS_HOST_RETRY_BACKOFF` from `.config`.

- [ ] **Step 3: Lint/type quick check on touched modules**

```bash
uv run ruff check src/komuzik/downloaders.py src/komuzik/config.py
```

Expected: no new errors.

- [ ] **Step 4: Commit**

```bash
git add messages.yaml src/komuzik/config.py src/komuzik/downloaders.py
git commit -m "$(cat <<'EOF'
feat: загрузчик hls_host best через yt-dlp

EOF
)"
git push
```

---

### Task 4: Handlers — DM + inline/group wiring

**Files:**
- Modify: `src/komuzik/handlers.py`

**Interfaces:**
- Consumes: `HLS_HOST_REGEX`, `download_hls_host_video`, `parse_inline_query` (`hls_host`)
- Produces: DM auto-download; `_download_for_inline` branch; `_track_parsed_download` via `track_video_download(..., platform="hls_host")`

- [ ] **Step 1: Imports**

Add `HLS_HOST_REGEX` to config imports; `download_hls_host_video` to downloader imports.

- [ ] **Step 2: DM message branch**

In the private-message URL chain (near Twitter/Pinterest/TikTok), **before** YouTube:

```python
        hls_match = HLS_HOST_REGEX.search(text)
        if hls_match:
            await self._handle_hls_host(event, hls_match.group(0))
            return
```

Normalize URL if needed the same way other handlers do (pass matched substring; downloader/parser add scheme if required). Prefer normalizing like inline:

```python
url = hls_match.group(0)
if not url.startswith(("http://", "https://")):
    url = "https://" + url
await self._handle_hls_host(event, url)
```

- [ ] **Step 3: `_handle_hls_host` method**

Copy structure of `_handle_tiktok`, with **neutral** copy only:

- processing: `"Загрузка видео... Пожалуйста, подождите."`
- logs: may say `hls_host` (not user-visible)
- download: `await download_hls_host_video(url)`
- send: `send_video_content(...)`
- stats success/fail:

```python
self.stats.track_video_download(
    user_id,
    "best",
    "hls_host",
    username,
    success=True,  # or False
    error_message=...,
    url=url,
    title=_media_title(metadata),
)
```

- errors:

```python
await event.respond(
    format_download_error(e, context="Произошла ошибка при загрузке:")
)
```

Do **not** put the host name in `respond` strings.

- [ ] **Step 4: `_download_for_inline`**

```python
        if parsed.platform == "hls_host":
            file_path, metadata = await download_hls_host_video(parsed.url)
            return file_path, metadata, "video"
```

(before the final `raise ValueError`)

- [ ] **Step 5: `_track_parsed_download`**

Handle before the tiktok/twitter `else`:

```python
        elif parsed.platform == "hls_host":
            self.stats.track_video_download(
                user_id,
                parsed.quality,
                "hls_host",
                username,
                success=success,
                error_message=error_message,
                source=source,
                url=parsed.url,
                title=title,
            )
```

Groups: no new code beyond parse + `_download_for_inline` / `_track_parsed_download` (existing `_handle_group_link_message`). Do **not** add chat-setting toggles or help text.

- [ ] **Step 6: Regression tests + lint**

```bash
uv run pytest tests/test_inline_search.py tests/test_admin_users_history.py -q
uv run ruff check src/komuzik/handlers.py
```

Expected: PASS / clean.

- [ ] **Step 7: Manual smoke (optional but recommended)**

В ЛС боту: `https://murrtube.net/v/BS0W` → видео без кнопок качества; текст статуса без имени хоста.  
`/help` → раздел платформ без нового пункта.

- [ ] **Step 8: Commit**

```bash
git add src/komuzik/handlers.py
git commit -m "$(cat <<'EOF'
feat: silent download hls_host в ЛС/inline/группах

EOF
)"
git push
```

---

## Spec coverage checklist

| Spec item | Task |
|-----------|------|
| Git fork dependency + PR note / return path | Task 1 |
| Best quality only | Task 3 (`format: best`), Task 4 |
| No settings / no help / no README features | Tasks 2–4 (explicit non-goals) |
| DM + inline + groups | Task 2 parse + Task 4 |
| Neutral UX / blank history label | Task 2 label, Task 3 error, Task 4 copy |
| Internal key `hls_host` | Tasks 2–4 |

## Self-review notes

- No placeholders left.
- `allows_platform` already returns `True` for unknown keys — no schema migration.
- Infographic platform bars unchanged (no new public label).
- User-facing strings must not contain `murrtube` / brand; regex host string in code is required for matching.
