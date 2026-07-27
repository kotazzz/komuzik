"""User-facing commands and settings."""

import logging
import uuid
from typing import Any, cast

from telethon import Button
from telethon.tl.custom import Message

from ..config import DEFAULT_SEARCH_RESULTS, MSG_PRIVACY, MSG_START
from ..downloaders import enrich_youtube_search_stats, search_youtube
from ..help_pages import (
    INFO_GITHUB_URL,
    INFO_TEXT,
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
from ..i18n import t
from ..search_preview import render_search_preview_async
from ..stats_infographic import format_stats_caption, get_stats_image
from .common import BOT_GROUPS_CACHE, CALLBACK_URLS, SEARCH_SESSIONS

logger = logging.getLogger(__name__)

class UserCommandsMixin:
    """Mixin for BotHandlers."""

    async def start_handler(self, event: Message):
        """Handle /start command."""
        user_id, _ = self._get_user_info(event)
        if await self._reject_if_banned(
            event, user_id, chat_is_group=bool(getattr(event, "is_group", False))
        ):
            return
        self._track_user(event)
        await event.respond(MSG_START, link_preview=False)

    async def help_handler(self, event: Message):
        """Handle /help — sectioned TOC with inline navigation."""
        user_id, _ = self._get_user_info(event)
        if await self._reject_if_banned(
            event, user_id, chat_is_group=bool(getattr(event, "is_group", False))
        ):
            return
        self._track_user(event)
        is_admin = bool(user_id and self._is_bot_admin(user_id))
        await event.respond(
            user_toc_text(),
            buttons=user_toc_buttons(is_admin=is_admin),
            link_preview=False,
        )

    async def info_handler(self, event: Message):
        """Handle /info — author, source repo, report hint."""
        user_id, _ = self._get_user_info(event)
        if await self._reject_if_banned(
            event, user_id, chat_is_group=bool(getattr(event, "is_group", False))
        ):
            return
        self._track_user(event)
        await event.respond(
            INFO_TEXT,
            buttons=[[Button.url(t("info.button_source"), INFO_GITHUB_URL)]],
            link_preview=False,
        )

    async def _handle_help_callback(self, event, data: str) -> None:
        """Navigate paginated /help (edit same message)."""
        user_id = cast("int | None", event.sender_id)
        kind, slug = resolve_help_callback(data)
        is_admin = bool(user_id and self._is_bot_admin(user_id))

        if kind in {"admin_toc", "admin_page"} and not is_admin:
            await event.answer(t("errors.no_access"), alert=True)
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

    async def privacy_handler(self, event: Message):
        """Handle /privacy — send rules and privacy policy link."""
        user_id, _ = self._get_user_info(event)
        if await self._reject_if_banned(
            event, user_id, chat_is_group=bool(getattr(event, "is_group", False))
        ):
            return
        self._track_user(event)
        await event.respond(MSG_PRIVACY, link_preview=False)

    def _format_user_limits_message(self, user_id: int) -> str:
        """Build /limits text for the current user."""
        is_admin = self._is_bot_admin(user_id)
        unlimited_concurrent = is_admin or user_id in self.download_limiter.UNLIMITED_USER_IDS
        active = self.download_limiter.get_active_count(user_id)
        concurrent_cap = self.download_limiter.get_max_per_user()

        if unlimited_concurrent:
            concurrent_line = f"Одновременные загрузки: **{active}** активных · без лимита"
        else:
            concurrent_line = (
                f"Одновременные загрузки: **{active}/{concurrent_cap}** активных"
            )

        playlist_limit = self.stats.effective_playlist_limit(
            user_id,
            is_admin=is_admin,
            is_unlimited=unlimited_concurrent,
        )
        used = self.stats.get_playlist_usage(user_id)
        personal = self.stats.get_user_playlist_limit(user_id)

        if playlist_limit is None:
            playlist_line = "Плейлист / сутки (МСК): без лимита"
        else:
            remaining = max(0, playlist_limit - used)
            source = "персональный" if personal is not None else "общий"
            playlist_line = (
                f"Плейлист / сутки (МСК): **{used}/{playlist_limit}** "
                f"(осталось {remaining}, {source})"
            )

        return (
            "📊 **Ваши лимиты**\n\n"
            f"{concurrent_line}\n"
            f"{playlist_line}\n\n"
            "Суточный лимит плейлиста обновляется в полночь по Москве."
        )

    async def limits_handler(self, event: Message):
        """Handle /limits — show current concurrent and playlist quotas."""
        user_id, _ = self._get_user_info(event)
        if await self._reject_if_banned(
            event, user_id, chat_is_group=bool(getattr(event, "is_group", False))
        ):
            return
        self._track_user(event)
        await event.respond(self._format_user_limits_message(user_id), link_preview=False)

    async def _count_bot_groups(self) -> int:
        """Count groups/supergroups the bot is currently in (cached ~5 min)."""
        cached = BOT_GROUPS_CACHE.get("count")
        if cached is not None:
            return cached
        count = 0
        try:
            async for dialog in self.client.iter_dialogs():
                if bool(getattr(dialog, "is_group", False)):
                    count += 1
        except Exception as e:
            logger.error(f"Failed to count bot groups: {e}")
            return count
        BOT_GROUPS_CACHE["count"] = count
        return count

    async def settings_handler(self, event: Message):
        """Handle /settings — personal in DM, chat settings in groups (admins only)."""
        user_id, _ = self._get_user_info(event)
        if await self._reject_if_banned(
            event, user_id, chat_is_group=bool(getattr(event, "is_group", False))
        ):
            return
        self._track_user(event)

        if bool(getattr(event, "is_group", False)):
            if not await self._is_chat_admin(event):
                await event.respond("❌ Только администраторы могут менять настройки чата.")
                return
            chat_id = int(event.chat_id)
            settings = self.stats.get_chat_settings(chat_id)
            await event.respond(
                self._format_chat_settings_message(settings),
                buttons=self._chat_settings_buttons(settings),
            )
            return

        settings = self.stats.get_user_settings(user_id)
        await event.respond(
            self._format_settings_message(settings),
            buttons=self._settings_buttons(settings),
        )

    async def _is_chat_admin(self, event: Message) -> bool:
        """Return True if the sender is any admin/creator of the chat."""
        sender_id = cast("int | None", event.sender_id)
        if sender_id is None:
            return False
        try:
            perms = await self.client.get_permissions(event.chat_id, sender_id)
            return bool(getattr(perms, "is_admin", False) or getattr(perms, "is_creator", False))
        except Exception as e:
            logger.error(f"Failed to check admin rights: {e}")
            return False

    def _format_settings_message(self, settings) -> str:
        bot_state = "✅ Вкл" if settings.show_bot_caption else "❌ Выкл"
        title_state = "✅ Вкл" if settings.show_title else "❌ Выкл"
        return (
            "⚙️ **Личные настройки**\n\n"
            f"🤖 Подпись бота (@{self.bot_username or 'bot'}): {bot_state}\n"
            f"📝 Название видео: {title_state}\n"
            f"📺 Качество (инлайн): **{settings.default_quality}**\n\n"
            "Качество влияет на инлайн без префикса. "
            "В ЛС по ссылке выбор формата как раньше."
        )

    def _settings_buttons(self, settings):
        bot_label = (
            "🤖 Подпись бота: выключить"
            if settings.show_bot_caption
            else "🤖 Подпись бота: включить"
        )
        title_label = "📝 Название: выключить" if settings.show_title else "📝 Название: включить"
        return [
            [Button.inline(bot_label, data="settings_bot")],
            [Button.inline(title_label, data="settings_title")],
            [Button.inline("📺 Качество по умолчанию", data="settings_quality")],
        ]

    def _format_quality_settings_message(self, current_quality: str, *, scope: str) -> str:
        scope_line = (
            "для **инлайна** (личные настройки)"
            if scope == "user"
            else "для **этой группы** (автозагрузка)"
        )
        return (
            f"📺 **Качество по умолчанию** {scope_line}\n\n"
            "Сейчас: **"
            f"{current_quality}**\n\n"
            "Ориентир размера (ролик ~3–5 мин):\n"
            "• 360p — ~5–15 МБ\n"
            "• 480p — ~15–30 МБ\n"
            "• 720p — ~30–60 МБ\n"
            "• 1080p — ~60–120+ МБ\n\n"
            "⚠️ Не ставьте высокое качество без нужды — "
            "файлы быстро забивают память телефона.\n\n"
            "Префикс в запросе (`480`, `music`…) всегда важнее этого дефолта."
        )

    def _quality_settings_buttons(self, current_quality: str, *, prefix: str) -> list:
        """Build quality picker. prefix is 'settings_q_' or 'chatset_q_'."""
        row: list = []
        buttons: list = []
        for q in ("360p", "480p", "720p", "1080p"):
            mark = "✅ " if q == current_quality else ""
            row.append(Button.inline(f"{mark}{q}", data=f"{prefix}{q}"))
            if len(row) == 2:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)
        back = "settings_back" if prefix.startswith("settings_") else "chatset_back"
        buttons.append([Button.inline("← Назад", data=back)])
        return buttons

    def _format_chat_settings_message(self, settings) -> str:
        def state(on: bool) -> str:
            return "✅ Вкл" if on else "❌ Выкл"

        return (
            "⚙️ **Настройки чата**\n\n"
            f"▶ YouTube: {state(settings.allow_youtube)}\n"
            f"♪ TikTok: {state(settings.allow_tiktok)}\n"
            f"𝕏 Twitter/X: {state(settings.allow_twitter)}\n"
            f"📌 Pinterest: {state(settings.allow_pinterest)}\n\n"
            f"🤖 Подпись бота: {state(settings.show_bot_caption)}\n"
            f"📝 Название видео: {state(settings.show_title)}\n"
            f"📺 Качество YouTube: **{settings.default_quality}**\n\n"
            "Выключенные платформы бот игнорирует. Только для этой группы."
        )

    def _chat_settings_buttons(self, settings):
        def label(name: str, on: bool) -> str:
            mark = "✅" if on else "❌"
            return f"{mark} {name}"

        return [
            [
                Button.inline(
                    label("YouTube", settings.allow_youtube), data="chatset_allow_youtube"
                ),
                Button.inline(label("TikTok", settings.allow_tiktok), data="chatset_allow_tiktok"),
            ],
            [
                Button.inline(
                    label("Twitter/X", settings.allow_twitter), data="chatset_allow_twitter"
                ),
                Button.inline(
                    label("Pinterest", settings.allow_pinterest), data="chatset_allow_pinterest"
                ),
            ],
            [
                Button.inline(
                    label("Подпись бота", settings.show_bot_caption),
                    data="chatset_show_bot_caption",
                ),
            ],
            [
                Button.inline(
                    label("Название", settings.show_title),
                    data="chatset_show_title",
                ),
            ],
            [Button.inline("📺 Качество по умолчанию", data="chatset_quality")],
        ]

    async def stats_handler(self, event: Message):
        """Handle /stats command."""
        user_id, _ = self._get_user_info(event)
        if await self._reject_if_banned(
            event, user_id, chat_is_group=bool(getattr(event, "is_group", False))
        ):
            return
        self._track_user(event)

        buttons = [
            [
                Button.inline("📊 За день", data="stats_day"),
                Button.inline("📅 За месяц", data="stats_month"),
            ],
            [Button.inline("📈 За все время", data="stats_all")],
        ]

        await event.respond(
            "📊 Статистика бота Komuzik\n\nВыберите период для просмотра статистики:",
            buttons=buttons,
        )

    async def search_handler(self, event: Message):
        """Handle /search command."""
        user_id, _ = self._get_user_info(event)
        if await self._reject_if_banned(
            event, user_id, chat_is_group=bool(getattr(event, "is_group", False))
        ):
            return
        self._track_user(event)

        text = getattr(event.message, "text", None)
        if not isinstance(text, str):
            await event.respond(
                "Пожалуйста, укажите поисковый запрос.\nПример: /search название песни"
            )
            return

        query = self.command_args(text, "search")

        if not query:
            await event.respond(
                "Пожалуйста, укажите поисковый запрос.\nПример: /search название песни"
            )
            return

        # Track search
        user_id, username = self._get_user_info(event)
        self.stats.track_search(user_id, username)

        searching_msg = await event.respond(f"🔍 Поиск: {query}...")
        page_size = DEFAULT_SEARCH_RESULTS
        results = await search_youtube(query, max_results=page_size, offset=0)

        if not results:
            if searching_msg is not None:
                await searching_msg.edit("Ничего не найдено. Попробуйте изменить запрос.")
            return

        session_token = uuid.uuid4().hex[:16]
        SEARCH_SESSIONS[session_token] = {
            "query": query,
            "results": results,
            "offset": 0,
            "page_size": page_size,
            "has_more": len(results) >= page_size,
        }

        if searching_msg is not None:
            await searching_msg.edit(
                self._format_search_page_text(session_token),
                buttons=self._search_page_buttons(session_token),
            )

    def _format_search_page_text(self, session_token: str) -> str:
        session = SEARCH_SESSIONS.get(session_token) or {}
        results = list(session.get("results") or [])
        offset = int(session.get("offset") or 0)
        start = offset + 1
        end = offset + len(results)
        return (
            f"Выберите видео ({start}–{end}):\n"
            "Превью — отдельной кнопкой. «Ещё 10» подгружает следующую страницу."
        )

    def _search_page_buttons(self, session_token: str) -> list:
        session = SEARCH_SESSIONS.get(session_token) or {}
        results = list(session.get("results") or [])
        offset = int(session.get("offset") or 0)
        page_size = int(session.get("page_size") or DEFAULT_SEARCH_RESULTS)

        buttons: list = []
        for i, result in enumerate(results):
            num = offset + i + 1
            duration = int(result["duration"]) if result.get("duration") else 0
            duration_min = duration // 60
            duration_sec = duration % 60
            title = str(result.get("title") or "Без названия")
            button_text = (
                f"{num}. {title[:48]}{'...' if len(title) > 48 else ''}"
                f" ({duration_min}:{duration_sec:02d})"
            )
            buttons.append(
                [
                    Button.inline(
                        button_text,
                        data=f"select_{self._store_callback_url(str(result['url']))}",
                    )
                ]
            )

        nav: list = [
            Button.inline("🖼 Превью", data=f"searchprev_{session_token}"),
        ]
        if session.get("has_more"):
            nav.append(Button.inline("➡️ Ещё 10", data=f"searchmore_{session_token}"))
        buttons.append(nav)
        return buttons

    async def _handle_stats_callback(self, event, data: str):
        """Handle statistics view callback — send infographic image."""
        period = data.split("_")[1]  # Extract period (day, month, all)

        await event.answer("Рисую инфографику...")

        try:
            stats = self.stats.get_statistics(period)
            stats["total_groups"] = await self._count_bot_groups()

            image = await get_stats_image(stats, period)
            # Caption must use the same snapshot the PNG was drawn from —
            # otherwise a cache hit shows stale art next to a fresh caption.
            caption = format_stats_caption(image.stats, image.period)

            buttons = [
                [
                    Button.inline("📊 За день", data="stats_day"),
                    Button.inline("📅 За месяц", data="stats_month"),
                ],
                [Button.inline("📈 За все время", data="stats_all")],
            ]

            # Prefer editing current message into a photo; fall back to new message.
            try:
                await event.edit(caption, file=str(image.path), buttons=buttons)
            except Exception:
                await event.respond(caption, file=str(image.path), buttons=buttons)
                try:
                    await event.delete()
                except Exception:
                    pass

        except Exception as e:
            logger.error(f"Error getting statistics: {e}")
            await event.edit(f"Произошла ошибка при получении статистики: {e!s}")

    async def _handle_settings_callback(self, event, data: str):
        """Toggle personal settings / open quality screen."""
        user_id = cast("int | None", event.sender_id)
        if user_id is None:
            await event.answer("Не удалось определить пользователя.", alert=True)
            return

        if data == "settings_quality":
            settings = self.stats.get_user_settings(user_id)
            await event.edit(
                self._format_quality_settings_message(settings.default_quality, scope="user"),
                buttons=self._quality_settings_buttons(settings.default_quality, prefix="settings_q_"),
            )
            await event.answer()
            return

        if data == "settings_back":
            settings = self.stats.get_user_settings(user_id)
            await event.edit(
                self._format_settings_message(settings),
                buttons=self._settings_buttons(settings),
            )
            await event.answer()
            return

        if data.startswith("settings_q_"):
            quality = data.removeprefix("settings_q_")
            settings = self.stats.set_user_default_quality(user_id, quality)
            await event.edit(
                self._format_quality_settings_message(settings.default_quality, scope="user"),
                buttons=self._quality_settings_buttons(settings.default_quality, prefix="settings_q_"),
            )
            await event.answer(f"Качество: {settings.default_quality}")
            return

        key = "show_bot_caption" if data == "settings_bot" else None
        if data == "settings_title":
            key = "show_title"
        if key is None:
            await event.answer()
            return

        settings = self.stats.toggle_user_setting(user_id, key)
        await event.edit(
            self._format_settings_message(settings),
            buttons=self._settings_buttons(settings),
        )
        await event.answer("Сохранено")

    async def _handle_chat_settings_callback(self, event, data: str):
        """Toggle group chat settings (admins only)."""
        if not await self._is_chat_admin(event):
            await event.answer("Только администраторы могут менять настройки.", alert=True)
            return

        chat_id = int(event.chat_id)

        if data == "chatset_quality":
            settings = self.stats.get_chat_settings(chat_id)
            await event.edit(
                self._format_quality_settings_message(settings.default_quality, scope="chat"),
                buttons=self._quality_settings_buttons(settings.default_quality, prefix="chatset_q_"),
            )
            await event.answer()
            return

        if data == "chatset_back":
            settings = self.stats.get_chat_settings(chat_id)
            await event.edit(
                self._format_chat_settings_message(settings),
                buttons=self._chat_settings_buttons(settings),
            )
            await event.answer()
            return

        if data.startswith("chatset_q_"):
            quality = data.removeprefix("chatset_q_")
            settings = self.stats.set_chat_default_quality(chat_id, quality)
            await event.edit(
                self._format_quality_settings_message(settings.default_quality, scope="chat"),
                buttons=self._quality_settings_buttons(settings.default_quality, prefix="chatset_q_"),
            )
            await event.answer(f"Качество: {settings.default_quality}")
            return

        key = data.removeprefix("chatset_")
        if key not in {
            "allow_youtube",
            "allow_tiktok",
            "allow_twitter",
            "allow_pinterest",
            "show_bot_caption",
            "show_title",
        }:
            await event.answer()
            return

        settings = self.stats.toggle_chat_setting(chat_id, key)
        await event.edit(
            self._format_chat_settings_message(settings),
            buttons=self._chat_settings_buttons(settings),
        )
        await event.answer("Сохранено")
