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

from .config import MSG_HELP, MSG_START, TIKTOK_REGEX, TWITTER_REGEX, YOUTUBE_REGEX
from .download_limiter import DownloadLimiter
from .downloaders import (
    download_tiktok_video,
    download_twitter_video,
    download_youtube_audio,
    download_youtube_video,
    get_available_formats,
    search_youtube,
    send_audio_content,
    send_image_content,
    send_video_content,
)
from .repository import StatsRepository

logger = logging.getLogger(__name__)

# States for /report command state machine
REPORT_STATES = {}
CALLBACK_URLS: dict[str, str] = {}
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
        self.client.on(events.NewMessage(pattern="/stats"))(self.stats_handler)
        self.client.on(events.NewMessage(pattern="/post"))(self.post_handler)
        self.client.on(events.NewMessage(pattern="/report"))(self.report_handler)
        self.client.on(events.NewMessage(pattern=r"^/search(?:\s+(.+))?"))(self.search_handler)
        self.client.on(events.NewMessage())(self.message_handler)
        self.client.on(events.CallbackQuery())(self.callback_handler)

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

                    await send_func(event, file_path, metadata, self.bot_username)
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
        """Handle incoming messages with YouTube, TikTok and Twitter links."""
        message_obj = event.message
        user_id, username = self._get_user_info(event)

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

            # Send report to admins
            header_msg = f"📋 **Новый отчет**\nОт: @{username or user_id} (ID: {user_id})"

            for admin_id in self.download_limiter.ADMIN_USER_IDS:
                try:
                    await self.client.send_message(admin_id, header_msg)
                    if message_obj is not None:
                        await self.client.send_message(admin_id, message_obj)
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

        self._track_user(event)

        # Check for Twitter/X
        twitter_match = TWITTER_REGEX.search(text)
        if twitter_match:
            await self._handle_twitter(event, twitter_match.group(0))
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
                "Пожалуйста, отправьте корректную ссылку на видео YouTube, YouTube Shorts, TikTok или Twitter/X."
            )
            return

        matched_url = youtube_match.group(0)

        # Check if it's a YouTube Shorts
        if "/shorts/" in matched_url:
            await self._handle_youtube_shorts(event, matched_url)
        else:
            await self._show_content_type_selection(event, matched_url)

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

                    await send_video_content(event, file_path, metadata, self.bot_username)
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

                    await send_video_content(event, file_path, metadata, self.bot_username)
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
        """Handle statistics view callback."""
        period = data.split("_")[1]  # Extract period (day, month, all)

        await event.answer("Загрузка статистики...")

        try:
            stats = self.stats.get_statistics(period)

            # Format period name in Russian
            period_names = {"day": "за день", "month": "за месяц", "all": "за все время"}
            period_name = period_names.get(period, period)

            # Build statistics message
            message = f"📊 Статистика бота Komuzik {period_name}\n\n"

            message += f"👥 Пользователей: {stats['total_users']}\n"
            message += f"🔍 Поисков: {stats['total_searches']}\n\n"

            message += f"📥 Всего загрузок: {stats['total_downloads']}\n"
            message += f"  ✅ Успешных: {stats['successful_downloads']}\n"
            message += f"  ❌ Ошибок: {stats['failed_downloads']}\n\n"

            message += f"🎬 Видео (YouTube): {stats['total_videos']}\n"
            message += f"🎵 Аудио: {stats['total_audio']}\n"
            message += f"📱 TikTok: {stats['total_tiktoks']}\n\n"

            # Popular video formats
            if stats["popular_video_formats"]:
                message += "📊 Популярные форматы видео:\n"
                for format_name, count in stats["popular_video_formats"]:
                    message += f"  • {format_name}: {count}\n"
                message += "\n"

            # Popular audio formats
            if stats["popular_audio_formats"]:
                message += "🎧 Популярные форматы аудио:\n"
                for format_name, count in stats["popular_audio_formats"]:
                    message += f"  • {format_name}: {count}\n"

            # Add buttons to switch periods
            buttons = [
                [
                    Button.inline("📊 За день", data="stats_day"),
                    Button.inline("📅 За месяц", data="stats_month"),
                ],
                [Button.inline("📈 За все время", data="stats_all")],
            ]

            await event.edit(message, buttons=buttons)

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
                    if metadata.get("content_type") == "photo":
                        await send_image_content(event, file_path, self.bot_username)
                    else:
                        await send_video_content(event, file_path, metadata, self.bot_username)

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

    async def callback_handler(self, event):
        """Handle callback queries from inline buttons."""
        data = event.data.decode("utf-8")
        user_id = cast("int | None", event.sender_id)

        # Handle report cancel
        if data == "report_cancel":
            if user_id is None:
                await event.edit("❌ Не удалось определить пользователя.")
                return
            REPORT_STATES.pop(user_id, None)
            await event.edit("❌ Отправка отчета отменена.")
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
