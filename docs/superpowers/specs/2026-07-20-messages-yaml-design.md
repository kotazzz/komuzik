# Design: централизация текстов — `messages.yaml` + `t()`

Дата: 2026-07-20  
Статус: approved (чат)

## Цель

Собрать пользовательские тексты бота в один YAML и читать их через `t("key", **kwargs)`, чтобы править копирайт без правок логики. Английский и выбор языка **не** входят в объём; структура ключей должна упростить будущий i18n.

## Решения

- Отдельный файл **`messages.yaml`** (не раздувать `config.yaml`).
- API: **`t(key, **kwargs)`** без параметра `lang`.
- Только русский.
- Миграция **волнами**, не big-bang всего `handlers.py` за один PR.

## Файлы

| Файл | Роль |
|------|------|
| `messages.yaml` | Каталог строк (корень репозитория) |
| `src/komuzik/i18n.py` | Загрузка YAML, `t()`, опционально `has_key` |
| `Dockerfile` / compose | `COPY messages.yaml` рядом с `config.yaml` |
| `config.yaml` | Убрать `messages:` и платформенные `error_message` после переноса |

Путь к YAML: рядом с `config.yaml` (cwd контейнера `/app`), с fallback на путь относительно пакета при локальных тестах — как уже сделано для конфига, если есть; иначе явный путь из env/`CONFIG_DIR` не обязателен в v1 (достаточно `/app/messages.yaml` + корень репо).

## API

```python
from komuzik.i18n import t

t("errors.client_unavailable")
t("download.limit_busy", active=2, max=3)
```

- Ключи: точечная нотация, вложенный YAML (`errors: { client_unavailable: "…" }`).
- Подстановки: `{name}` через `str.format_map` / безопасный аналог (неизвестный placeholder не обязан крашить бот — либо KeyError в тестах, в рантайме логировать и оставить шаблон).
- Missing key: залогировать warning, вернуть сам ключ (видно в чате); в unit-тестах — явная проверка покрытия.
- Без `lang`. Позже: `t(key, lang="ru", **kwargs)` или `gettext`-обёртка поверх того же YAML/`locales/ru.yaml`.

## Структура `messages.yaml` (секции)

Пример (не полный список ключей):

```yaml
start: |
  …

privacy: |
  …

info:
  body: |
    …
  button_source: "Исходный код"

help:
  toc: |
    …
  admin_toc: |
    …
  pages:
    start: |
      …
    # … platforms, playlists, inline, groups, commands
  admin_pages:
    panel: |
      …
  buttons:
    for_admin: "🛠 Для админа"
    back: "← Назад"

errors:
  client_unavailable: "…"
  download_unavailable: |
    …
  no_access: "Нет доступа."

# далее волнами: settings, playlist, inline, report, admin, buttons, …
```

Кнопки с эмодзи — тоже ключи (`buttons.video`, `help.buttons.back`), не магия в коде.

## Волны внедрения

### Волна 1 (каркас + уже «центральные» тексты)

1. Добавить `i18n.py` + `messages.yaml` с переносом:
   - `MSG_START` / `MSG_PRIVACY` (из config)
   - `help_pages.py` тексты и подписи кнопок справки
   - `INFO_TEXT` / URL можно оставить URL константой кода или ключом `info.github_url`
   - `user_errors.MSG_DOWNLOAD_UNAVAILABLE`
   - `inline_media.PM_UNAVAILABLE_MESSAGE`
   - платформенные `*_ERROR_MESSAGE` из config
2. Удалить неиспользуемый `messages.help` из `config.yaml` (и секцию `messages` целиком после переноса start/privacy).
3. Тесты: загрузка, format, ключевые ключи существуют; help toc / info содержат ожидаемые фрагменты.
4. Docker COPY `messages.yaml`.

### Волна 2+

По зонам в `handlers.py`: settings UI, playlist UX, report, download progress, admin replies, group messages. Каждый коммит — одна зона + ключи в YAML.

Критерий «готово для i18n позже»: почти все `event.respond`/`Button.inline` литералы проходят через `t()`.

## Вне scope

- Второй язык, `/lang`, язык в БД/settings.
- Перевод логов и stack traces.
- Вынос **всех** строк handlers в волне 1.

## Тесты

- `t("known.key")` возвращает текст из фикстуры/файла.
- `t("x", name="a")` подставляет `{name}`.
- Реестр или явный список ключей волны 1 — все присутствуют в YAML.
- Импорт бота / `help_pages` не падает без файла (или падает явно при старте — предпочтительно **fail fast** если `messages.yaml` нет при загрузке модуля в проде).

## Критерии готовности волны 1

- `messages.yaml` в образе и репо.
- `/start`, `/privacy`, `/help`, `/info`, access-error UX, PM-unavailable читают YAML через `t()`.
- `config.yaml` без дублирующих user-facing messages (или только deprecated stub — лучше удалить).
- Документ/README: «тексты — в `messages.yaml`».
