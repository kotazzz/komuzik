# Messages.yaml + t() Implementation Plan (Wave 1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Каркас `messages.yaml` + `t()` и перенос текстов волны 1 (start, privacy, help, info, access errors, PM unavailable, platform error_message).

**Architecture:** YAML в корне; `i18n.py` грузит при импорте; ключи через точки; `str.format_map`.

**Tech Stack:** PyYAML (уже в проекте через config), pytest.

**Spec:** `docs/superpowers/specs/2026-07-20-messages-yaml-design.md`

## Global Constraints

- Только RU, без `lang`
- Fail fast если нет `messages.yaml`
- Docker: `COPY messages.yaml .`
- Удалить `messages:` из `config.yaml` после переноса

---

### Task 1: `i18n.py` + tests

**Files:** Create `src/komuzik/i18n.py`, `tests/test_i18n.py`

- [ ] Implement `load_messages()`, `t(key, **kwargs)`, flatten nested dict to dotted keys
- [ ] Find file like ConfigLoader (cwd, repo root)
- [ ] Tests: format, missing key returns key + doesn't crash, nested keys

### Task 2: `messages.yaml` wave 1 content

**Files:** Create `messages.yaml`

- [ ] Port start, privacy, info, help pages/buttons, errors.*, platform errors from current sources

### Task 3: Wire consumers + Docker

**Files:** `help_pages.py`, `config.py`, `handlers.py`, `user_errors.py`, `inline_media.py`, `downloaders.py` (imports), `Dockerfile`, `entrypoint.sh` if checks files, `README.md`, strip `config.yaml` messages

- [ ] Replace literals with `t(...)`
- [ ] Keep `INFO_GITHUB_URL` as constant or `t("info.github_url")`
- [ ] pytest help_pages + i18n
- [ ] Commit, push, deploy

---

## Spec coverage (wave 1)

| Item | Task |
|------|------|
| messages.yaml + t() | 1–2 |
| help/info/start/privacy/errors/PM/platform | 2–3 |
| Docker COPY | 3 |
| Remove config messages | 3 |
| No EN / no lang | — |
