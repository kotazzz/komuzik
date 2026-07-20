# BotFather: включение inline для Komuzik

Нужно сделать **один раз** для бота на проде (после деплоя кода с inline-handlers).

## 1. Включить inline mode

В [@BotFather](https://t.me/BotFather):

```
/setinline
```

Выбрать `@komuzik_bot` (или актуальный username).

Placeholder (текст в поле ввода после `@bot`):

```
ссылка, music/480 + ссылка или поиск
```

## 2. Включить inline feedback

Без этого бот **не получит** событие выбора результата и `inline_message_id` для edit:

```
/setinlinefeedback
```

Выбрать бота → **Enabled** → вероятность **100%** (на старте).

Позже при высокой нагрузке можно снизить (1/10 и т.д.), но для edit via-сообщения feedback обязателен.

## 3. Проверка

1. Пользователь хотя бы раз написал боту `/start`.
2. В любом чате: `@komuzik_bot https://youtube.com/watch?v=...` или `@komuzik_bot never gonna give you up`
3. Выбрать пункт → сначала «⏳ Загрузка…», затем видео; в ЛС staging-файл должен исчезнуть.
