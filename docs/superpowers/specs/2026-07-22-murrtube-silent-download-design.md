# Silent HLS host download via yt-dlp fork — design

## Goal

Скачивать видео по ссылкам `murrtube.net/v/…` в лучшем доступном качестве, без UI выбора качества и **без любых пользовательских упоминаний** платформы (help, /start, README features, chat settings, тексты ошибок/статусов, inline description).

## Why a yt-dlp fork

Upstream yt-dlp extractor для этого хоста сломан после перехода сайта на Inertia.js SPA: в HTML больше нет `<video id="video">`, из‑за чего extraction падает.

Фикс (ветка форка / PR): парсинг JSON из `data-page` у `<div id="app">` → `props.medium` (`hls_url`, title, thumbnail, id и т.д.).

**Зависимость:** `git+https://github.com/kotazzz/yt-dlp.git@fix/murrtube-extractor`  
(PR upstream: https://github.com/yt-dlp/yt-dlp/pull/17285)

После merge PR в yt-dlp/yt-dlp и релиза на PyPI — вернуть зависимость на официальный `yt-dlp` и убрать заметку о форке.

Dev-документация (не пользовательская): кратко зафиксировать причину форка и необходимость проверить актуальность PR перед возвратом на PyPI.

## Out of scope

- Выбор качества / аудио-режим / настройки
- Пункт в `/help`, README «возможности», `/start`
- Тумблер в настройках группы (`allow_*`)
- Публичные анонсы поддержки

## Behavior

| Context | Action |
|---|---|
| ЛС, ссылка | Сразу download `best` → отправить видео |
| Inline, ссылка | То же; description нейтральный («видео»), без имени хоста |
| Группа, ссылка | Автоскачивание как у TikTok; **всегда разрешено**, без chat setting |
| Качество | Только наилучшее (`format: best` / эквивалент) |
| Ошибки пользователю | Нейтральный текст («не удалось загрузить»), без имени платформы |
| Статус «Загрузка…» | Нейтральный, без имени платформы |
| Админ-история | В БД: `platform=hls_host` (внутренний ключ); в `_history_platform_label` / инфографике — пустая или нейтральная подпись, не имя хоста |

## Technical

1. **deps:** заменить PyPI `yt-dlp` на git-зависимость ветки `fix/murrtube-extractor`; обновить `uv.lock`.
2. **config:** regex хоста (как у TikTok/Twitter); без секции «настроек платформы» в help/config UI.
3. **downloaders:** функция загрузки по паттерну TikTok (`format: best`, retries по желанию минимально).
4. **handlers:** ветка в DM message flow; wiring в inline download + group auto-download через `parse_inline_query`.
5. **inline_query:** распознавание URL → `platform="hls_host"`; `quality=auto`/`best`; description без бренда (например «Видео»).
6. **repository / group settings:** не добавлять `allow_*` / тумблер; неизвестные ключи уже `allows_platform → True` — этого достаточно. Статы через generic `track_download` с `platform="hls_host"`.
7. **docs:** короткая dev-заметка про форк + PR #17285 (не в пользовательском README features).

## Ops / follow-up

- Периодически проверять статус [PR #17285](https://github.com/yt-dlp/yt-dlp/pull/17285).
- После merge + PyPI release: вернуть `yt-dlp>=…` с PyPI, `uv lock`, удалить/обновить заметку о форке.
