"""Paginated /help texts and /info constants."""

from __future__ import annotations

from telethon import Button

INFO_GITHUB_URL = "https://github.com/kotazzz/komuzik"

INFO_TEXT = (
    "ℹ️ **О боте Komuzik**\n\n"
    f"Исходный код: {INFO_GITHUB_URL}\n"
    "Автор: **Kotaz**\n\n"
    "Нашли ошибку или есть жалоба — напишите `/report`."
)

_USER_SECTIONS: list[tuple[str, str, str]] = [
    (
        "start",
        "Старт",
        "🚀 **С чего начать**\n\n"
        "1. Напишите боту `/start` в личке (нужно и для inline).\n"
        "2. Пришлите ссылку на ролик или плейлист — в ЛС или в группе, где есть бот.\n"
        "3. Для YouTube выберите **видео** или **аудио**, затем качество.\n"
        "4. Дождитесь файла. Если что-то пошло не так — `/report`.\n\n"
        "Подпись с @ботом и названием ролика настраиваются в `/settings`.\n"
        "Об авторе и исходниках — `/info`.",
    ),
    (
        "platforms",
        "Платформы",
        "🎬 **Платформы**\n\n"
        "• **YouTube** — видео (360p–1080p) или аудио (высокое / среднее / низкое). "
        "Можно повторить последний выбранный формат одной кнопкой.\n"
        "• **YouTube Shorts** — скачивается сразу как видео.\n"
        "• **TikTok** — видео автоматически.\n"
        "• **Twitter / X** — видео, фото, альбомы.\n"
        "• **Pinterest** — видео и фото.\n\n"
        "Если ролик недоступен, ограничен по возрасту или требует входа — бот напишет "
        "понятное сообщение вместо сырой ошибки.\n\n"
        "Поиск роликов на YouTube: `/search запрос`.",
    ),
    (
        "playlists",
        "Плейлисты",
        "📑 **Плейлисты YouTube / YouTube Music**\n\n"
        "Только в **личке** с ботом.\n\n"
        "1. Пришлите ссылку на плейлист.\n"
        "2. Откроется превью со списком треков — листайте ⬅️➡️.\n"
        "3. Чтобы **исключить** треки: ответьте на сообщение превью номерами "
        "(например `1 3 5` или `2-4`).\n"
        "4. Выберите **Видео** или **Аудио** и качество.\n"
        "5. Бот шлёт пачками; можно нажать **Стоп**.\n\n"
        "Есть **суточный лимит** элементов плейлиста (для обычных пользователей). "
        "Админы бота безлимитны.",
    ),
    (
        "inline",
        "Inline",
        "💬 **Inline в любом чате**\n\n"
        "Напишите `@имя_бота` и дальше:\n"
        "• просто **ссылку** — скачать и отправить в чат;\n"
        "• YouTube аудио: `music` (или `audio`) и ссылку;\n"
        "• YouTube видео: `360` / `480` / `720` / `1080` и ссылку "
        "(если префикса нет — качество из `/settings`).\n\n"
        "Остальные платформы — только ссылка, без префиксов.\n\n"
        "⚠️ Один раз напишите боту `/start` в ЛС — иначе файл не доставится.\n"
        "Сначала появится «Загрузка…», затем медиа.",
    ),
    (
        "groups",
        "Группы",
        "👥 **Группы**\n\n"
        "В группе сошлитесь на ролик — бот может скачать его автоматически "
        "(с учётом настроек чата).\n\n"
        "Админы чата: `/settings` в группе — какие платформы разрешены, "
        "подписи и качество по умолчанию.\n\n"
        "Персональные `/settings` работают в личке с ботом.",
    ),
    (
        "commands",
        "Команды",
        "📌 **Команды**\n\n"
        "`/start` — приветствие и краткий гайд\n"
        "`/help` — эта справка по разделам\n"
        "`/info` — автор, исходный код, куда писать о багах\n"
        "`/settings` — подпись @бота, название, качество по умолчанию\n"
        "`/search запрос` — поиск на YouTube\n"
        "`/stats` — статистика бота\n"
        "`/report` — сообщить об ошибке или проблеме\n"
        "`/privacy` — правила и политика\n\n"
        "Жалобы и баги — только через `/report` (не в личку автору).",
    ),
]

_ADMIN_SECTIONS: list[tuple[str, str, str]] = [
    (
        "panel",
        "Панель",
        "🛠 **Админ-панель**\n\n"
        "`/admin` — сводка: одновременные загрузки, лимит плейлиста / сутки, "
        "число блокировок.\n\n"
        "Кнопки на панели:\n"
        "• **Одновременные** — лимит параллельных загрузок на пользователя;\n"
        "• **Лимит плейлиста** — глобальная суточная квота элементов;\n"
        "• **Пользователи** — список и история.",
    ),
    (
        "limits",
        "Лимиты",
        "📊 **Лимиты**\n\n"
        "`/setconcurrent N` — макс. одновременных загрузок (≥ 1)\n"
        "`/setplaylistlimit N` — плейлист-элементов на пользователя в сутки (МСК)\n"
        "`/setuserlimit <айди> N` — персональный лимит плейлиста\n"
        "`/unsetuserlimit <айди>` — сбросить персональный лимит\n\n"
        "Можно задать число и через кнопки панели (бот попросит ввести значение).\n"
        "Админы бота не расходуют суточную квоту плейлиста.",
    ),
    (
        "bans",
        "Блокировки",
        "🚫 **Блокировки**\n\n"
        "`/ban <айди> причина` — заблокировать пользователя\n"
        "`/unban <айди>` — снять блок\n\n"
        "В ЛС и inline заблокированный видит сообщение о блокировке.\n"
        "В группах бот его игнорирует (тишина).\n"
        "`/report` у заблокированных по-прежнему принимается.",
    ),
    (
        "users",
        "Пользователи",
        "👥 **Пользователи и история**\n\n"
        "`/users` или кнопка на `/admin` — список с вкладками "
        "**Известные** / **Анонимы**.\n"
        "`/user <айди>` — карточка: профиль, лимиты, история загрузок "
        "(страницы по 10, до 50 записей).\n\n"
        "В истории: платформа, видео/аудио, качество, ссылка и название "
        "(если сохранились).",
    ),
    (
        "storage",
        "Хранилище",
        "📦 **Группа-хранилище**\n\n"
        "Нужна, чтобы стейджить медиа (плейлист / inline) без «Переслано от».\n\n"
        "`/setstorage` — **в группе-хранилище**, от имени админа бота: "
        "запомнить этот чат. У бота должно быть право удалять сообщения.\n"
        "`/unsetstorage` — отвязать хранилище.\n\n"
        "Без хранилища inline стейджится в ЛС пользователя (нужен `/start`).",
    ),
    (
        "post",
        "Рассылка",
        "📣 **Рассылка**\n\n"
        "`/post` — ответом на сообщение, которое нужно разослать всем "
        "известным пользователям бота.\n\n"
        "Используйте осторожно.",
    ),
]

USER_SLUGS: tuple[str, ...] = tuple(s for s, _, _ in _USER_SECTIONS)
ADMIN_SLUGS: tuple[str, ...] = tuple(s for s, _, _ in _ADMIN_SECTIONS)

_USER_BY_SLUG = {slug: (label, body) for slug, label, body in _USER_SECTIONS}
_ADMIN_BY_SLUG = {slug: (label, body) for slug, label, body in _ADMIN_SECTIONS}


def user_toc_text() -> str:
    return (
        "🔍 **Справка Komuzik**\n\n"
        "Выберите раздел кнопкой ниже.\n"
        "Об авторе и исходном коде — команда `/info`."
    )


def admin_toc_text() -> str:
    return (
        "🛠 **Справка для админа**\n\n"
        "Разделы по командам и лимитам. "
        "«← Назад» вернёт к обычной справке."
    )


def user_page_text(slug: str) -> str:
    return _USER_BY_SLUG[slug][1]


def admin_page_text(slug: str) -> str:
    return _ADMIN_BY_SLUG[slug][1]


def _chunk_buttons(items: list, per_row: int = 2) -> list:
    rows: list = []
    for i in range(0, len(items), per_row):
        rows.append(items[i : i + per_row])
    return rows


def user_toc_buttons(*, is_admin: bool) -> list:
    items = [
        Button.inline(label, data=f"help_u_{slug}")
        for slug, label, _ in _USER_SECTIONS
    ]
    rows = _chunk_buttons(items, 2)
    if is_admin:
        rows.append([Button.inline("🛠 Для админа", data="help_a_toc")])
    return rows


def admin_toc_buttons() -> list:
    items = [
        Button.inline(label, data=f"help_a_{slug}")
        for slug, label, _ in _ADMIN_SECTIONS
    ]
    rows = _chunk_buttons(items, 2)
    rows.append([Button.inline("← Назад", data="help_toc")])
    return rows


def user_page_buttons() -> list:
    return [[Button.inline("← Назад", data="help_toc")]]


def admin_page_buttons() -> list:
    return [[Button.inline("← Назад", data="help_a_toc")]]


def resolve_help_callback(data: str) -> tuple[str, str | None]:
    if data == "help_toc":
        return "user_toc", None
    if data == "help_a_toc":
        return "admin_toc", None
    if data.startswith("help_u_"):
        slug = data.removeprefix("help_u_")
        if slug in _USER_BY_SLUG:
            return "user_page", slug
        return "unknown", None
    if data.startswith("help_a_"):
        slug = data.removeprefix("help_a_")
        if slug in _ADMIN_BY_SLUG:
            return "admin_page", slug
        return "unknown", None
    return "unknown", None
