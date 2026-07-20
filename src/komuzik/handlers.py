"""Event handlers for Telegram bot commands and callbacks."""

import logging
import os
import re
import shutil
import uuid
from collections.abc import Awaitable, Callable
from typing import Any, cast

from telethon import Button, events
from telethon.tl.custom import Message
from telethon.tl.types import UpdateBotInlineSend

from .config import (
    MSG_HELP,
    MSG_START,
    PINTEREST_REGEX,
    TIKTOK_REGEX,
    TWITTER_REGEX,
    YOUTUBE_REGEX,
)
from .download_limiter import DownloadLimiter
from .downloaders import (
    download_pinterest_content,
    download_tiktok_video,
    download_twitter_video,
    download_youtube_audio,
    download_youtube_video,
    get_available_formats,
    get_media_title,
    search_youtube,
    send_audio_content,
    send_image_content,
    send_video_content,
)
from .inline_media import (
    PM_UNAVAILABLE_MESSAGE,
    delete_staging_message,
    edit_inline_text,
    edit_inline_with_media,
    is_pm_unavailable_error,
    stage_media_to_user,
)
from .inline_query import ParsedInlineQuery, parse_inline_query
from .repository import StatsRepository
from .stats_infographic import get_stats_image

logger = logging.getLogger(__name__)

# States for /report command state machine
REPORT_STATES = {}
CALLBACK_URLS: dict[str, str] = {}
INLINE_JOBS: dict[str, ParsedInlineQuery] = {}
CallbackHandler = Callable[[Any, str], Awaitable[None]]


class BotHandlers:
    """Handles all bot commands and callbacks."""

    def __init__(
        self,
        client,
        stats_repo: StatsRepository,
        bot_username: str = "",
        download_limiter: DownloadLimiter | None = None,
    ):
        self.client = client
        self.bot_username = bot_username
        self.stats = stats_repo
        self.download_limiter = download_limiter or DownloadLimiter()
        self._register_handlers()

    def _register_handlers(self):
        """Register all event handlers."""
        self.client.on(events.NewMessage(pattern="/start"))(self.start_handler)
        self.client.on(events.NewMessage(pattern="/help"))(self.help_handler)
        self.client.on(events.NewMessage(pattern="/settings"))(self.settings_handler)
        self.client.on(events.NewMessage(pattern="/stats"))(self.stats_handler)
        self.client.on(events.NewMessage(pattern="/post"))(self.post_handler)
        self.client.on(events.NewMessage(pattern="/report"))(self.report_handler)
        self.client.on(events.NewMessage(pattern=r"^/search(?:\s+(.+))?"))(self.search_handler)
        self.client.on(events.NewMessage())(self.message_handler)
        self.client.on(events.CallbackQuery())(self.callback_handler)
        self.client.on(events.InlineQuery())(self.inline_query_handler)
        self.client.on(events.Raw(UpdateBotInlineSend))(self.chosen_inline_handler)

    def _track_user(self, event: Message):
        """Track user activity."""
        user_id = cast("int | None", event.sender_id)
        if user_id is None:
            return
        username = event.sender.username if event.sender else None
        self.stats.track_user(user_id, username)

    def _get_user_info(self, event: Message) -> tuple[int, str | None]:
        """Extract user ID and username from event."""
        user_id = cast("int | None", event.sender_id)
        if user_id is None:
            raise ValueError("Missing sender_id in Telegram event")
        username = event.sender.username if event.sender else None
        return user_id, username

    def _store_callback_url(self, url: str) -> str:
        """Store a URL behind a short callback token."""
        token = uuid.uuid4().hex
        CALLBACK_URLS[token] = url
        return token

    def _resolve_callback_url(self, token: str) -> str | None:
        """Resolve a callback token to its stored URL."""
        return CALLBACK_URLS.get(token)

    def _caption_kwargs(self, user_id: int) -> dict[str, bool]:
        """Load caption preferences for send_* helpers."""
        settings = self.stats.get_user_settings(user_id)
        return {
            "show_bot_caption": settings.show_bot_caption,
            "show_title": settings.show_title,
        }

    def _cleanup_download_file(self, file_path: str):
        """Remove the temporary directory that contains a downloaded file."""
        directory = os.path.dirname(file_path)
        if os.path.exists(directory):
            shutil.rmtree(directory)

    async def _check_download_limit(self, event: Message, user_id: int, download_id: str) -> bool:
        """Check if user can start a new download.

        Returns:
            True if download can proceed, False if limit reached

        """
        if not await self.download_limiter.start_download(user_id, download_id):
            active_count = self.download_limiter.get_active_count(user_id)
            await event.respond(
                f"⚠️ У вас уже есть активная загрузка ({active_count}/{self.download_limiter.MAX_DOWNLOADS_PER_USER}). "
                f"Пожалуйста, дождитесь завершения текущей загрузки."
            )
            return False
        return True

    async def _download_and_send_content(
        self,
        event: Message,
        url: str,
        quality: str,
        content_type: str,
        download_func: Callable,
        send_func: Callable,
        track_func: Callable,
        action: str,
    ):
        """Generic function to download and send content (video/audio).

        Args:
            event: Telegram event
            url: Content URL
            quality: Quality setting
            content_type: 'video' or 'audio' for logging
            download_func: Function to download content
            send_func: Function to send content
            track_func: Function to track download stats
            action: Telegram action type ('video' or 'audio')

        """
        user_id, username = self._get_user_info(event)
        download_id = str(uuid.uuid4())

        # Check download limit
        if not await self._check_download_limit(event, user_id, download_id):
            return

        file_path = None
        try:
            client = event.client
            if client is None:
                await event.respond("Произошла ошибка: клиент Telegram недоступен.")
                return

            async with client.action(event.chat_id, action):
                try:
                    processing_msg = await event.respond(
                        f"Загрузка {content_type}... Пожалуйста, подождите."
                    )
                    logger.info(f"Downloading {content_type}: {url} with quality: {quality}")

                    file_path, metadata = await download_func(url, quality)
                    logger.info(f"{content_type.capitalize()} downloaded successfully: {file_path}")

                    await send_func(
                        event,
                        file_path,
                        metadata,
                        self.bot_username,
                        **self._caption_kwargs(user_id),
                    )
                    if processing_msg is not None:
                        await processing_msg.delete()

                    # Track successful download
                    track_func(user_id, quality, username, success=True)

                except Exception as e:
                    logger.error(f"Error sending {content_type}: {e}")
                    # Track failed download
                    track_func(user_id, quality, username, success=False, error_message=str(e))
                    await event.respond(f"Произошла ошибка при обработке {content_type}: {e!s}")
        finally:
            # Always release the download slot
            if file_path:
                self._cleanup_download_file(file_path)
            await self.download_limiter.finish_download(user_id, download_id)

    async def start_handler(self, event: Message):
        """Handle /start command."""
        self._track_user(event)
        await event.respond(MSG_START)

    async def help_handler(self, event: Message):
        """Handle /help command."""
        self._track_user(event)
        await event.respond(MSG_HELP)

    async def _count_bot_groups(self) -> int:
        """Count groups/supergroups the bot is currently in."""
        count = 0
        try:
            async for dialog in self.client.iter_dialogs():
                if bool(getattr(dialog, "is_group", False)):
                    count += 1
        except Exception as e:
            logger.error(f"Failed to count bot groups: {e}")
        return count

    async def settings_handler(self, event: Message):
        """Handle /settings — personal in DM, chat settings in groups (admins only)."""
        self._track_user(event)
        user_id, _ = self._get_user_info(event)

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
            "⚙️ **Настройки подписи**\n\n"
            f"🤖 Подпись бота (@{self.bot_username or 'bot'}): {bot_state}\n"
            f"📝 Название видео: {title_state}\n\n"
            "По умолчанию оба пункта включены."
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
        ]

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
            f"📝 Название видео: {state(settings.show_title)}\n\n"
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
        ]

    async def stats_handler(self, event: Message):
        """Handle /stats command."""
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
        self._track_user(event)

        text = getattr(event.message, "text", None)
        if not isinstance(text, str):
            await event.respond(
                "Пожалуйста, укажите поисковый запрос.\nПример: /search название песни"
            )
            return

        match = re.match(r"^/search(?:\s+(.+))?", text)
        query = match.group(1) if match else None

        if not query:
            await event.respond(
                "Пожалуйста, укажите поисковый запрос.\nПример: /search название песни"
            )
            return

        # Track search
        user_id, username = self._get_user_info(event)
        self.stats.track_search(user_id, username)

        searching_msg = await event.respond(f"🔍 Поиск: {query}...")
        results = await search_youtube(query, max_results=5)

        if not results:
            if searching_msg is not None:
                await searching_msg.edit("Ничего не найдено. Попробуйте изменить запрос.")
            return

        buttons = []
        for i, result in enumerate(results, 1):
            duration = int(result["duration"]) if result["duration"] else 0
            duration_min = duration // 60
            duration_sec = duration % 60
            button_text = f"{i}. {result['title'][:50]}{'...' if len(result['title']) > 50 else ''} ({duration_min}:{duration_sec:02d})"
            buttons.append(
                [
                    Button.inline(
                        button_text, data=f"select_{self._store_callback_url(result['url'])}"
                    )
                ]
            )

        if searching_msg is not None:
            await searching_msg.edit("Выберите видео из результатов поиска:", buttons=buttons)

    async def message_handler(self, event: Message):
        """Handle incoming messages with YouTube, TikTok, Twitter and Pinterest links."""
        message_obj = event.message
        user_id, username = self._get_user_info(event)

        # Admin reply to a report → copy 1:1 to the reporter (quote their report)
        if await self._maybe_handle_report_reply(event, message_obj, user_id):
            return

        # Check if user is in report state
        if REPORT_STATES.get(user_id):
            raw_report_text = (
                getattr(message_obj, "text", None) if message_obj is not None else None
            )
            report_text = raw_report_text if isinstance(raw_report_text, str) else ""

            # Ignore if user sends another command while in report state
            if report_text.startswith("/"):
                # Handle /cancel command
                if report_text.strip() == "/cancel":
                    del REPORT_STATES[user_id]
                    await event.respond("❌ Отправка отчета отменена.")
                return

            # Save report to database
            db_text = report_text or "[Медиафайл]"
            self.stats.save_user_report(user_id, username, db_text)

            # Send report to admins (header + 1:1 copy without "forwarded from")
            header_text = f"📋 **Новый отчет**\nОт: @{username or user_id} (ID: {user_id})"
            user_report_msg_id = int(message_obj.id) if message_obj is not None else 0

            for admin_id in self.download_limiter.ADMIN_USER_IDS:
                try:
                    header = await self.client.send_message(admin_id, header_text)
                    if message_obj is None:
                        continue
                    body = await self.client.send_message(admin_id, message_obj)
                    self.stats.save_report_thread(
                        admin_id=int(admin_id),
                        header_msg_id=int(header.id),
                        body_msg_id=int(body.id),
                        user_id=user_id,
                        user_report_msg_id=user_report_msg_id,
                    )
                except Exception as e:
                    logger.error(f"Failed to send report to admin {admin_id}: {e}")

            # Confirm to user
            await event.respond("✅ Спасибо! Ваш отчет отправлен администраторам.")

            # Clear state
            del REPORT_STATES[user_id]
            return

        text = getattr(message_obj, "text", None) if message_obj is not None else None
        if not isinstance(text, str) or not text:
            return

        if text.startswith("/"):
            return

        # Groups/supergroups: auto-download links (silent if no URL)
        if bool(getattr(event, "is_group", False)):
            await self._handle_group_link_message(event, text)
            return

        self._track_user(event)

        # Check for Twitter/X
        twitter_match = TWITTER_REGEX.search(text)
        if twitter_match:
            await self._handle_twitter(event, twitter_match.group(0))
            return

        # Check for Pinterest
        pinterest_match = PINTEREST_REGEX.search(text)
        if pinterest_match:
            await self._handle_pinterest(event, pinterest_match.group(0))
            return

        # Check for TikTok
        tiktok_match = TIKTOK_REGEX.search(text)
        if tiktok_match:
            await self._handle_tiktok(event, tiktok_match.group(0))
            return

        # Check for YouTube (including Shorts)
        youtube_match = YOUTUBE_REGEX.search(text)
        if not youtube_match:
            await event.respond(
                "Пожалуйста, отправьте корректную ссылку на видео YouTube, YouTube Shorts, TikTok, Twitter/X или Pinterest."
            )
            return

        matched_url = youtube_match.group(0)

        # Check if it's a YouTube Shorts
        if "/shorts/" in matched_url:
            await self._handle_youtube_shorts(event, matched_url)
        else:
            await self._show_content_type_selection(event, matched_url)

    async def _handle_group_link_message(self, event: Message, text: str) -> None:
        """Auto-download a supported link in a group (reply to the link message)."""
        if bool(getattr(event, "out", False)):
            return

        parsed = parse_inline_query(text)
        if parsed is None:
            return

        chat_id = int(event.chat_id)
        chat_settings = self.stats.get_chat_settings(chat_id)
        if not chat_settings.allows_platform(parsed.platform):
            return

        user_id, username = self._get_user_info(event)
        self._track_user(event)
        download_id = str(uuid.uuid4())

        if not await self._check_download_limit(event, user_id, download_id):
            return

        reply_to = int(event.message.id) if event.message is not None else None
        processing_msg = None
        file_path = None
        try:
            client = event.client
            if client is None:
                await event.respond(
                    "Произошла ошибка: клиент Telegram недоступен.",
                    reply_to=reply_to,
                )
                return

            action = "audio" if parsed.mode == "audio" else "video"
            async with client.action(event.chat_id, action):
                processing_msg = await event.respond(
                    f"Загрузка ({parsed.description})…",
                    reply_to=reply_to,
                )
                file_path, metadata, media_kind = await self._download_for_inline(parsed)
                caption_kwargs = {
                    "show_bot_caption": chat_settings.show_bot_caption,
                    "show_title": chat_settings.show_title,
                    "reply_to": reply_to,
                }
                if media_kind == "audio":
                    await send_audio_content(
                        event, file_path, metadata, self.bot_username, **caption_kwargs
                    )
                elif media_kind == "photo":
                    await send_image_content(
                        event,
                        file_path,
                        self.bot_username,
                        metadata=metadata,
                        **caption_kwargs,
                    )
                else:
                    await send_video_content(
                        event, file_path, metadata, self.bot_username, **caption_kwargs
                    )
                self._track_parsed_download(
                    parsed, user_id, username, success=True, source="group"
                )
        except Exception as e:
            logger.error(f"Group download failed for {parsed.url}: {e}")
            self._track_parsed_download(
                parsed,
                user_id,
                username,
                success=False,
                error_message=str(e),
                source="group",
            )
            try:
                await event.respond(
                    f"❌ Не удалось загрузить: {e!s}",
                    reply_to=reply_to,
                )
            except Exception as send_error:
                logger.error(f"Failed to send group error reply: {send_error}")
        finally:
            if processing_msg is not None:
                try:
                    await processing_msg.delete()
                except Exception:
                    pass
            if file_path:
                self._cleanup_download_file(file_path)
            await self.download_limiter.finish_download(user_id, download_id)

    async def _handle_tiktok(self, event: Message, url: str):
        """Handle TikTok video download."""
        user_id, username = self._get_user_info(event)
        download_id = str(uuid.uuid4())

        # Check download limit
        if not await self._check_download_limit(event, user_id, download_id):
            return

        file_path = None
        try:
            client = event.client
            if client is None:
                await event.respond("Произошла ошибка: клиент Telegram недоступен.")
                return

            async with client.action(event.chat_id, "video"):
                try:
                    processing_msg = await event.respond(
                        "Загрузка TikTok видео... Пожалуйста, подождите."
                    )
                    logger.info(f"Downloading TikTok video: {url}")

                    file_path, metadata = await download_tiktok_video(url)
                    logger.info(f"TikTok video downloaded successfully: {file_path}")

                    await send_video_content(
                        event,
                        file_path,
                        metadata,
                        self.bot_username,
                        **self._caption_kwargs(user_id),
                    )
                    if processing_msg is not None:
                        await processing_msg.delete()

                    # Track successful TikTok download
                    self.stats.track_tiktok_download(user_id, username, success=True)

                except Exception as e:
                    logger.error(f"Error sending TikTok video: {e}")
                    # Track failed TikTok download
                    self.stats.track_tiktok_download(
                        user_id, username, success=False, error_message=str(e)
                    )
                    await event.respond(f"Произошла ошибка при обработке TikTok видео: {e!s}")
        finally:
            # Always release the download slot
            if file_path:
                self._cleanup_download_file(file_path)
            await self.download_limiter.finish_download(user_id, download_id)

    async def _show_content_type_selection(self, event: Message, url: str):
        """Show content type selection buttons for YouTube."""
        token = self._store_callback_url(url)
        buttons = [
            [
                Button.inline("🎬 Видео", data=f"content_video_{token}"),
                Button.inline("🎵 Аудио", data=f"content_audio_{token}"),
            ]
        ]
        await event.respond("Выберите тип контента для загрузки:", buttons=buttons)

    async def _handle_youtube_shorts(self, event: Message, url: str):
        """Handle YouTube Shorts download."""
        user_id, username = self._get_user_info(event)
        download_id = str(uuid.uuid4())

        if not await self._check_download_limit(event, user_id, download_id):
            return

        file_path = None
        try:
            client = event.client
            if client is None:
                await event.respond("Произошла ошибка: клиент Telegram недоступен.")
                return

            async with client.action(event.chat_id, "video"):
                try:
                    processing_msg = await event.respond(
                        "Загрузка YouTube Short... Пожалуйста, подождите."
                    )
                    logger.info(f"Downloading YouTube Short: {url}")

                    file_path, metadata = await download_youtube_video(url, quality="best")
                    logger.info(f"YouTube Short downloaded successfully: {file_path}")

                    await send_video_content(
                        event,
                        file_path,
                        metadata,
                        self.bot_username,
                        **self._caption_kwargs(user_id),
                    )
                    if processing_msg is not None:
                        await processing_msg.delete()

                    self.stats.track_video_download(
                        user_id, "auto", "youtube_shorts", username, success=True
                    )

                except Exception as e:
                    logger.error(f"Error sending YouTube Short: {e}")
                    self.stats.track_video_download(
                        user_id,
                        "auto",
                        "youtube_shorts",
                        username,
                        success=False,
                        error_message=str(e),
                    )
                    await event.respond(f"Произошла ошибка при обработке YouTube Short: {e!s}")
        finally:
            if file_path:
                self._cleanup_download_file(file_path)
            await self.download_limiter.finish_download(user_id, download_id)

    async def _handle_select_callback(self, event, data: str):
        """Handle video selection from search results."""
        token = data[7:]  # Remove 'select_' prefix
        url = self._resolve_callback_url(token)
        if not url:
            await event.edit("Ссылка для этого результата больше недоступна. Повторите поиск.")
            return
        CALLBACK_URLS.pop(token, None)
        await self._show_content_type_selection(event, url)

    async def _handle_content_callback(self, event, data: str):
        """Handle content type selection (video/audio)."""
        parts = data.split("_", 2)
        if len(parts) != 3:
            return

        content_type, token = parts[1], parts[2]
        url = self._resolve_callback_url(token)
        if not url:
            await event.edit("Ссылка для этого выбора больше недоступна. Повторите поиск.")
            return

        if content_type == "video":
            await self._show_video_quality_selection(event, token)
        elif content_type == "audio":
            await self._show_audio_quality_selection(event, token)

    async def _show_video_quality_selection(self, event, token: str):
        """Show video quality selection buttons."""
        url = self._resolve_callback_url(token)
        if not url:
            await event.edit("Ссылка для этого выбора больше недоступна. Повторите поиск.")
            return

        await event.answer("Проверка доступных форматов...")
        logger.info(f"Getting available formats for: {url}")

        available_heights = await get_available_formats(url)
        logger.info(f"Available heights: {available_heights}")

        buttons = []
        row = []

        for height in available_heights:
            # Create label based on height
            if height >= 2160:
                label = f"{height}p 4K"
            elif height >= 1440:
                label = f"{height}p 2K"
            elif height >= 720:
                label = f"{height}p HD"
            else:
                label = f"{height}p"

            quality_id = f"{height}p"
            row.append(Button.inline(label, data=f"quality_{quality_id}_{token}"))

            # Two buttons per row
            if len(row) == 2:
                buttons.append(row)
                row = []

        # Add remaining buttons
        if row:
            buttons.append(row)

        if not buttons:
            logger.warning(f"No buttons created for available heights: {available_heights}")
            await event.edit(
                "К сожалению, для этого видео нет доступных форматов. Попробуйте другое видео."
            )
            return

        await event.edit("Выберите качество видео:", buttons=buttons)

    async def _show_audio_quality_selection(self, event, token: str):
        """Show audio quality selection buttons."""
        buttons = [
            [
                Button.inline("Высокое качество", data=f"audio_high_{token}"),
                Button.inline("Среднее качество", data=f"audio_medium_{token}"),
            ],
            [Button.inline("Низкое качество", data=f"audio_low_{token}")],
        ]
        await event.edit("Выберите качество аудио:", buttons=buttons)

    async def _handle_quality_callback(self, event, data: str):
        """Handle video quality selection."""
        parts = data.split("_", 2)
        if len(parts) != 3:
            return

        quality, token = parts[1], parts[2]
        url = self._resolve_callback_url(token)
        if not url:
            await event.edit("Ссылка для этой загрузки больше недоступна. Повторите поиск.")
            return
        await event.answer(f"Загрузка видео в качестве {quality}...")

        try:
            await self._download_and_send_video(event, url, quality)
        finally:
            CALLBACK_URLS.pop(token, None)

    async def _handle_audio_callback(self, event, data: str):
        """Handle audio quality selection."""
        parts = data.split("_", 2)
        if len(parts) != 3:
            return

        quality, token = parts[1], parts[2]
        url = self._resolve_callback_url(token)
        if not url:
            await event.edit("Ссылка для этой загрузки больше недоступна. Повторите поиск.")
            return
        await event.answer(f"Загрузка аудио в качестве {quality}...")

        try:
            await self._download_and_send_audio(event, url, quality)
        finally:
            CALLBACK_URLS.pop(token, None)

    async def _download_and_send_video(self, event, url: str, quality: str):
        """Download and send YouTube video."""

        def track_video(user_id, quality, username, success, error_message=None):
            self.stats.track_video_download(
                user_id, quality, "youtube", username, success=success, error_message=error_message
            )

        await self._download_and_send_content(
            event=event,
            url=url,
            quality=quality,
            content_type="видео",
            download_func=download_youtube_video,
            send_func=send_video_content,
            track_func=track_video,
            action="video",
        )

    async def _download_and_send_audio(self, event, url: str, quality: str):
        """Download and send YouTube audio."""
        await self._download_and_send_content(
            event=event,
            url=url,
            quality=quality,
            content_type="аудио",
            download_func=download_youtube_audio,
            send_func=send_audio_content,
            track_func=self.stats.track_audio_download,
            action="audio",
        )

    async def _handle_stats_callback(self, event, data: str):
        """Handle statistics view callback — send infographic image."""
        period = data.split("_")[1]  # Extract period (day, month, all)

        await event.answer("Рисую инфографику...")

        try:
            stats = self.stats.get_statistics(period)
            stats["total_groups"] = await self._count_bot_groups()
            period_names = {"day": "за день", "month": "за месяц", "all": "за всё время"}
            period_name = period_names.get(period, period)

            image_path = await get_stats_image(stats, period)

            total = int(stats.get("total_downloads") or 0)
            ok = int(stats.get("successful_downloads") or 0)
            success_pct = round(100 * ok / total) if total else 0
            by_source = stats.get("by_source") or {}
            caption = (
                f"📊 Komuzik {period_name}\n"
                f"👥 {stats.get('total_users', 0)} · "
                f"💬 {stats.get('total_groups', 0)} · "
                f"📥 {total} · "
                f"✅ {success_pct}%\n"
                f"ЛС {by_source.get('dm', 0)} · "
                f"Inline {by_source.get('inline', 0)} · "
                f"Группы {by_source.get('group', 0)}"
            )

            buttons = [
                [
                    Button.inline("📊 За день", data="stats_day"),
                    Button.inline("📅 За месяц", data="stats_month"),
                ],
                [Button.inline("📈 За все время", data="stats_all")],
            ]

            # Prefer editing current message into a photo; fall back to new message.
            try:
                await event.edit(caption, file=str(image_path), buttons=buttons)
            except Exception:
                await event.respond(caption, file=str(image_path), buttons=buttons)
                try:
                    await event.delete()
                except Exception:
                    pass

        except Exception as e:
            logger.error(f"Error getting statistics: {e}")
            await event.edit(f"Произошла ошибка при получении статистики: {e!s}")

    async def _handle_twitter(self, event: Message, url: str):
        """Handle Twitter/X video and photo download."""
        user_id, username = self._get_user_info(event)
        download_id = str(uuid.uuid4())

        if not await self._check_download_limit(event, user_id, download_id):
            return

        file_path = None
        try:
            client = event.client
            if client is None:
                await event.respond("Произошла ошибка: клиент Telegram недоступен.")
                return

            async with client.action(event.chat_id, "video"):
                try:
                    processing_msg = await event.respond(
                        "Загрузка с Twitter... Пожалуйста, подождите."
                    )
                    logger.info(f"Downloading Twitter content: {url}")

                    file_path, metadata = await download_twitter_video(url)
                    logger.info(f"Twitter content downloaded successfully: {file_path}")

                    # Send appropriate content type
                    caption_kw = self._caption_kwargs(user_id)
                    if metadata.get("content_type") == "photo":
                        await send_image_content(
                            event,
                            file_path,
                            self.bot_username,
                            metadata=metadata,
                            **caption_kw,
                        )
                    else:
                        await send_video_content(
                            event,
                            file_path,
                            metadata,
                            self.bot_username,
                            **caption_kw,
                        )

                    if processing_msg is not None:
                        await processing_msg.delete()

                    self.stats.track_tiktok_download(user_id, username, success=True)

                except Exception as e:
                    logger.error(f"Error sending Twitter content: {e}")
                    self.stats.track_tiktok_download(
                        user_id, username, success=False, error_message=str(e)
                    )
                    await event.respond(f"Произошла ошибка при обработке контента: {e!s}")
        finally:
            if file_path:
                self._cleanup_download_file(file_path)
            await self.download_limiter.finish_download(user_id, download_id)

    async def _handle_pinterest(self, event: Message, url: str):
        """Handle Pinterest video and photo download."""
        user_id, username = self._get_user_info(event)
        download_id = str(uuid.uuid4())

        if not await self._check_download_limit(event, user_id, download_id):
            return

        file_path = None
        try:
            client = event.client
            if client is None:
                await event.respond("Произошла ошибка: клиент Telegram недоступен.")
                return

            async with client.action(event.chat_id, "document"):
                try:
                    processing_msg = await event.respond(
                        "Загрузка с Pinterest... Пожалуйста, подождите."
                    )
                    logger.info(f"Downloading Pinterest content: {url}")

                    file_path, metadata = await download_pinterest_content(url)
                    logger.info(f"Pinterest content downloaded successfully: {file_path}")

                    caption_kw = self._caption_kwargs(user_id)
                    if metadata.get("content_type") == "photo":
                        await send_image_content(
                            event,
                            file_path,
                            self.bot_username,
                            metadata=metadata,
                            **caption_kw,
                        )
                    else:
                        await send_video_content(
                            event,
                            file_path,
                            metadata,
                            self.bot_username,
                            **caption_kw,
                        )

                    if processing_msg is not None:
                        await processing_msg.delete()

                    self.stats.track_pinterest_download(user_id, username, success=True)

                except Exception as e:
                    logger.error(f"Error sending Pinterest content: {e}")
                    self.stats.track_pinterest_download(
                        user_id, username, success=False, error_message=str(e)
                    )
                    await event.respond(f"Произошла ошибка при обработке Pinterest: {e!s}")
        finally:
            if file_path:
                self._cleanup_download_file(file_path)
            await self.download_limiter.finish_download(user_id, download_id)

    async def post_handler(self, event: Message):
        """Handle /post command for admin broadcast."""
        user_id, _username = self._get_user_info(event)

        if user_id not in self.download_limiter.ADMIN_USER_IDS:
            await event.respond("❌ У вас нет доступа к этой команде.")
            return

        message_obj = cast("Message", event.message)

        # Check if it's a reply
        if not message_obj or not getattr(message_obj, "is_reply", False):
            await event.respond(
                "ℹ️ Используйте команду /post в ответе на сообщение, которое нужно переслать всем пользователям."
            )
            return

        try:
            reply_msg = await message_obj.get_reply_message()

            processing_msg = await event.respond("📢 Отправляю сообщение всем пользователям...")

            # Get all users from database
            users = self.stats.get_all_users()
            sent_count = 0
            failed_count = 0

            for user_id_target, _ in users:
                try:
                    await self.client.send_message(user_id_target, reply_msg)
                    sent_count += 1
                except Exception as e:
                    logger.warning(f"Failed to send message to user {user_id_target}: {e}")
                    failed_count += 1

            result = f"✅ Сообщение отправлено {sent_count} пользователям"
            if failed_count > 0:
                result += f"\n⚠️ Не удалось отправить {failed_count} пользователям"

            if processing_msg is not None:
                await processing_msg.edit(result)

        except Exception as e:
            logger.error(f"Error in post handler: {e}")
            await event.respond(f"Произошла ошибка: {e!s}")

    async def report_handler(self, event: Message):
        """Handle /report command for user reports."""
        user_id, username = self._get_user_info(event)

        REPORT_STATES[user_id] = True

        await event.respond(
            "📝 Опишите проблему (или отправьте /cancel для отмены):",
            buttons=[[Button.inline("❌ Отмена", data="report_cancel")]],
        )

    async def _maybe_handle_report_reply(
        self, event: Message, message_obj: Any, user_id: int
    ) -> bool:
        """If admin replies to a report message, copy the reply to the reporter.

        Returns True when the event was handled as a report reply.
        """
        if user_id not in self.download_limiter.ADMIN_USER_IDS:
            return False
        if message_obj is None:
            return False

        reply = getattr(message_obj, "reply_to", None)
        reply_msg_id = getattr(reply, "reply_to_msg_id", None) if reply is not None else None
        if not isinstance(reply_msg_id, int):
            return False

        thread = self.stats.get_report_thread_by_admin_msg(user_id, reply_msg_id)
        if thread is None:
            return False

        reporter_id, user_report_msg_id = thread
        try:
            await self.client.send_message(
                reporter_id,
                message_obj,
                reply_to=user_report_msg_id,
            )
            await event.respond("✅ Ответ отправлен пользователю.")
        except Exception as e:
            logger.error(f"Failed to deliver report reply to {reporter_id}: {e}")
            await event.respond(f"❌ Не удалось отправить ответ: {e!s}")
        return True

    async def callback_handler(self, event):
        """Handle callback queries from inline buttons."""
        data = event.data.decode("utf-8")
        user_id = cast("int | None", event.sender_id)

        # Dummy keyboard on inline placeholder — needed for inline_message_id
        if data == "noop":
            await event.answer()
            return

        # Handle report cancel
        if data == "report_cancel":
            if user_id is None:
                await event.edit("❌ Не удалось определить пользователя.")
                return
            REPORT_STATES.pop(user_id, None)
            await event.edit("❌ Отправка отчета отменена.")
            return

        if data.startswith("settings_"):
            await self._handle_settings_callback(event, data)
            return

        if data.startswith("chatset_"):
            await self._handle_chat_settings_callback(event, data)
            return

        # Route callbacks using dictionary
        handlers: dict[str, CallbackHandler] = {
            "select_": self._handle_select_callback,
            "content_": self._handle_content_callback,
            "quality_": self._handle_quality_callback,
            "audio_": self._handle_audio_callback,
            "stats_": self._handle_stats_callback,
        }

        for prefix, handler in handlers.items():
            if data.startswith(prefix):
                await handler(event, data)
                return

        logger.warning(f"Unknown callback data: {data}")

    async def _handle_settings_callback(self, event, data: str):
        """Toggle caption settings from inline buttons."""
        user_id = cast("int | None", event.sender_id)
        if user_id is None:
            await event.answer("Не удалось определить пользователя.", alert=True)
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

        chat_id = int(event.chat_id)
        settings = self.stats.toggle_chat_setting(chat_id, key)
        await event.edit(
            self._format_chat_settings_message(settings),
            buttons=self._chat_settings_buttons(settings),
        )
        await event.answer("Сохранено")

    async def inline_query_handler(self, event):
        """Answer inline queries with a placeholder article for supported links."""
        query_text = event.text or ""
        parsed = parse_inline_query(query_text)
        builder = event.builder

        if not parsed:
            hint = await builder.article(
                title="Кинь ссылку YouTube / TikTok / X / Pinterest",
                description="Для YouTube: music или 360/480/720/1080 + ссылка",
                text=(
                    "Отправьте ссылку после @бота.\n"
                    "YouTube: `music` / `480` + ссылка. Остальные платформы — просто ссылка.\n"
                    "Сначала напишите боту /start в ЛС."
                ),
                buttons=[Button.inline("⏳", b"noop")],
                id="hint",
            )
            await event.answer([hint], cache_time=0)
            return

        title = await get_media_title(parsed.url, fallback=parsed.description)
        token = uuid.uuid4().hex[:16]
        INLINE_JOBS[token] = parsed

        result = await builder.article(
            title=title,
            description=parsed.description,
            text="⏳ Загрузка…",
            buttons=[Button.inline("⏳", b"noop")],
            id=token,
        )
        await event.answer([result], cache_time=0)

    async def chosen_inline_handler(self, event: UpdateBotInlineSend):
        """Download media after user picks an inline result and edit the via-message."""
        token = event.id
        inline_msg_id = event.msg_id
        user_id = event.user_id
        parsed = INLINE_JOBS.pop(token, None)

        if parsed is None:
            logger.warning(f"Unknown inline job token: {token}")
            return

        if inline_msg_id is None:
            logger.warning("Chosen inline result without msg_id (enable /setinlinefeedback)")
            return

        username = None
        try:
            user = await self.client.get_entity(user_id)
            username = getattr(user, "username", None)
        except Exception:
            pass

        self.stats.track_user(user_id, username)

        download_id = str(uuid.uuid4())
        if not await self.download_limiter.start_download(user_id, download_id):
            active_count = self.download_limiter.get_active_count(user_id)
            await edit_inline_text(
                self.client,
                inline_msg_id,
                f"⚠️ Уже есть активная загрузка ({active_count}/"
                f"{self.download_limiter.MAX_DOWNLOADS_PER_USER}). Подождите.",
            )
            return

        file_path = None
        try:
            await edit_inline_text(self.client, inline_msg_id, "⏳ Загрузка…")
            file_path, metadata, media_kind = await self._download_for_inline(parsed)
            try:
                staging_msg = await stage_media_to_user(
                    self.client,
                    user_id,
                    file_path,
                    media_kind,
                    metadata,
                    self.bot_username,
                    **self._caption_kwargs(user_id),
                )
            except Exception as e:
                if is_pm_unavailable_error(e):
                    await edit_inline_text(self.client, inline_msg_id, PM_UNAVAILABLE_MESSAGE)
                    self._track_inline_download(
                        parsed, user_id, username, success=False, error_message=str(e)
                    )
                    return
                raise

            await edit_inline_with_media(self.client, inline_msg_id, staging_msg)
            await delete_staging_message(self.client, user_id, staging_msg)
            self._track_inline_download(parsed, user_id, username, success=True)

        except Exception as e:
            logger.error(f"Inline download failed for {parsed.url}: {e}")
            try:
                await edit_inline_text(
                    self.client,
                    inline_msg_id,
                    f"❌ Не удалось загрузить: {e!s}",
                )
            except Exception as edit_error:
                logger.error(f"Failed to edit inline error text: {edit_error}")
            self._track_inline_download(
                parsed, user_id, username, success=False, error_message=str(e)
            )
        finally:
            if file_path:
                self._cleanup_download_file(file_path)
            await self.download_limiter.finish_download(user_id, download_id)

    async def _download_for_inline(self, parsed: ParsedInlineQuery) -> tuple[str, dict, str]:
        """Download media for an inline job. Returns (path, metadata, media_kind)."""
        if parsed.platform == "youtube" and parsed.mode == "audio":
            file_path, metadata = await download_youtube_audio(parsed.url, parsed.quality)
            return file_path, metadata, "audio"

        if parsed.platform in {"youtube", "youtube_shorts"}:
            quality = parsed.quality if parsed.platform == "youtube" else "best"
            file_path, metadata = await download_youtube_video(parsed.url, quality)
            return file_path, metadata, "video"

        if parsed.platform == "tiktok":
            file_path, metadata = await download_tiktok_video(parsed.url)
            return file_path, metadata, "video"

        if parsed.platform == "twitter":
            file_path, metadata = await download_twitter_video(parsed.url)
            kind = "photo" if metadata.get("content_type") == "photo" else "video"
            return file_path, metadata, kind

        if parsed.platform == "pinterest":
            file_path, metadata = await download_pinterest_content(parsed.url)
            kind = "photo" if metadata.get("content_type") == "photo" else "video"
            return file_path, metadata, kind

        raise ValueError(f"Unsupported platform: {parsed.platform}")

    def _track_inline_download(
        self,
        parsed: ParsedInlineQuery,
        user_id: int,
        username: str | None,
        *,
        success: bool,
        error_message: str | None = None,
    ):
        """Record inline download stats with source=inline."""
        self._track_parsed_download(
            parsed,
            user_id,
            username,
            success=success,
            error_message=error_message,
            source="inline",
        )

    def _track_parsed_download(
        self,
        parsed: ParsedInlineQuery,
        user_id: int,
        username: str | None,
        *,
        success: bool,
        source: str,
        error_message: str | None = None,
    ):
        """Record download stats for a parsed media link."""
        if parsed.platform == "youtube" and parsed.mode == "audio":
            self.stats.track_audio_download(
                user_id,
                parsed.quality,
                username,
                success=success,
                error_message=error_message,
                source=source,
            )
        elif parsed.platform in {"youtube", "youtube_shorts"}:
            platform = "youtube_shorts" if parsed.platform == "youtube_shorts" else "youtube"
            self.stats.track_video_download(
                user_id,
                parsed.quality,
                platform,
                username,
                success=success,
                error_message=error_message,
                source=source,
            )
        elif parsed.platform == "pinterest":
            self.stats.track_pinterest_download(
                user_id,
                username,
                success=success,
                error_message=error_message,
                source=source,
            )
        else:
            # tiktok + twitter (existing DM path also uses tiktok tracker for twitter)
            self.stats.track_tiktok_download(
                user_id,
                username,
                success=success,
                error_message=error_message,
                source=source,
            )
