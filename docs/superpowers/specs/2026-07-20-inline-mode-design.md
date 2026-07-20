# Inline-режим KOMUZIK — design

Дата: 2026-07-20

## Цель

Позволить в любом чате писать `@komuzik_bot [префиксы] <ссылка>` и отправлять скачанное медиа как via-сообщение.

## Решение

1. `InlineQuery` → быстрый Article (title из metadata) с текстом «⏳ Загрузка…» и dummy inline-кнопкой.
2. `UpdateBotInlineSend` (ChosenInlineResult) → download → staging в ЛС пользователя → `edit_message` по `InputBotInlineMessageID` с уже загруженным media → удалить staging.
3. Если ЛС недоступен → `edit` текста с ошибкой («напиши /start» / ЧС).

Ограничение Telegram: при edit inline нельзя залить новый файл — только уже известный media/`file_id`.

## Префиксы (только YouTube, не Shorts)

| Query | Результат |
|---|---|
| `url` | видео 720p |
| `music` / `audio` + url | аудио |
| `360`/`480`/`720`/`1080` + url | видео указанной высоты |

Остальные платформы: префиксы игнорируются, медиа как в ЛС.

## Статистика

Поле `source` (`dm` | `inline`) — отдельное измерение. В `/stats` — разбивки source и video/audio. Старые NULL = `dm`.

## Ops (BotFather)

Перед использованием на проде:

1. `/setinline` — placeholder: `ссылка или music/480 + ссылка`
2. `/setinlinefeedback` — 100% (иначе нет UpdateBotInlineSend / msg_id)

## Вне scope v1

- Альбомы (только первое медиа)
- Prefetch до выбора
- Dump-канал (staging только ЛС)
