# yt-dlp: временный форк

## Почему не PyPI

Extractor Murrtube в upstream сломан после перехода сайта на Inertia.js
(`data-page` JSON вместо `<video id="video">`).

## Что используем

- Репозиторий: https://github.com/kotazzz/yt-dlp
- Ветка: `fix/murrtube-extractor`
- Upstream PR: https://github.com/yt-dlp/yt-dlp/pull/17285

Источник задан в `pyproject.toml` → `[tool.uv.sources]`.

Docker-сборка ставит пакет через git, поэтому в `Dockerfile` нужен пакет `git`
(см. `apt-get install`).

## Когда вернуться на оригинал

1. Проверить, что PR #17285 (или эквивалент) **merged**.
2. Дождаться релиза yt-dlp на PyPI с этим фиксом.
3. Убрать `[tool.uv.sources]` для yt-dlp, вернуть `"yt-dlp>=…"`, `uv lock` / `uv sync`.
4. Удалить или обновить этот файл.
