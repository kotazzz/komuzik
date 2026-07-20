# Report reply — design

## Goal

Админ может ответить (reply) на любое из двух сообщений репорта — заголовок или копию отзыва — и бот доставляет ответ пользователю 1:1 с цитированием исходного репорта.

## Flow

1. Пользователь `/report` → текст/медиа.
2. Админу: заголовок `📋 Новый отчет…` + копия сообщения через `send_message(admin, message)` (без «переслано от»).
3. В SQLite `report_threads`: `admin_id`, `header_msg_id`, `body_msg_id`, `user_id`, `user_report_msg_id`.
4. Админ отвечает reply на header или body.
5. Бот: `send_message(user, admin_message, reply_to=user_report_msg_id)` + подтверждение админу.

## Out of scope

Альбомы как единый объект; ответы не-админов; UI-кнопки.