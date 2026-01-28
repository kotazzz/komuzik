"""Event handlers for Telegram bot commands and callbacks."""
import re
import logging
import shutil
import os
import uuid
from typing import Callable, Dict
from telethon import events, Button
from telethon.tl.custom import Message
from telethon.tl.types import TypeUpdate

from .config import YOUTUBE_REGEX, TIKTOK_REGEX, TWITTER_REGEX, MSG_START, MSG_HELP
from .downloaders import (
    get_available_formats,
    search_youtube,
    download_youtube_video,
    download_youtube_audio,
    download_tiktok_video,
    download_twitter_video,
    send_video_content,
    send_audio_content,
    send_image_content,
)
from .repository import StatsRepository
from .download_limiter import DownloadLimiter

logger = logging.getLogger(__name__)

# States for /report command state machine
REPORT_STATES = {}


class BotHandlers:
    """Handles all bot commands and callbacks."""
    
    def __init__(self, client, stats_repo: StatsRepository, bot_username: str = ""):
        self.client = client
        self.bot_username = bot_username
        self.stats = stats_repo
        self.download_limiter = DownloadLimiter()
        self._register_handlers()
    
    def _register_handlers(self):
        """Register all event handlers."""
        self.client.on(events.NewMessage(pattern='/start'))(self.start_handler)
        self.client.on(events.NewMessage(pattern='/help'))(self.help_handler)
        self.client.on(events.NewMessage(pattern='/stats'))(self.stats_handler)
        self.client.on(events.NewMessage(pattern='/post'))(self.post_handler)
        self.client.on(events.NewMessage(pattern='/report'))(self.report_handler)
        self.client.on(events.NewMessage(pattern=r'^/search(?:\s+(.+))?'))(self.search_handler)
        self.client.on(events.NewMessage())(self.message_handler)
        self.client.on(events.CallbackQuery())(self.callback_handler)
    
    def _track_user(self, event: Message):
        """Track user activity."""
        user_id = event.sender_id
        username = event.sender.username if event.sender else None
        self.stats.track_user(user_id, username)
    
    def _get_user_info(self, event: Message) -> tuple[int, str | None]:
        """Extract user ID and username from event."""
        user_id = event.sender_id
        username = event.sender.username if event.sender else None
        return user_id, username
    
    async def _check_download_limit(self, event: Message, user_id: int, download_id: str) -> bool:
        """Check if user can start a new download.
        
        Returns:
            True if download can proceed, False if limit reached
        """
        if not self.download_limiter.start_download(user_id, download_id):
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
        action: str
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
        
        try:
            async with event.client.action(event.chat_id, action):
                try:
                    processing_msg = await event.respond(f"Загрузка {content_type}... Пожалуйста, подождите.")
                    logger.info(f"Downloading {content_type}: {url} with quality: {quality}")
                    
                    file_path, metadata = await download_func(url, quality)
                    logger.info(f"{content_type.capitalize()} downloaded successfully: {file_path}")
                    
                    await send_func(event, file_path, metadata, self.bot_username)
                    await processing_msg.delete()
                    
                    # Track successful download
                    track_func(user_id, quality, username, success=True)
                    
                    # Cleanup
                    if os.path.exists(os.path.dirname(file_path)):
                        shutil.rmtree(os.path.dirname(file_path))
                        
                except Exception as e:
                    logger.error(f"Error sending {content_type}: {e}")
                    # Track failed download
                    track_func(user_id, quality, username, success=False, error_message=str(e))
                    await event.respond(f"Произошла ошибка при обработке {content_type}: {str(e)}")
        finally:
            # Always release the download slot
            self.download_limiter.finish_download(user_id, download_id)
    
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
                Button.inline("📅 За месяц", data="stats_month")
            ],
            [
                Button.inline("📈 За все время", data="stats_all")
            ]
        ]
        
        await event.respond(
            "📊 Статистика бота Komuzik\n\n"
            "Выберите период для просмотра статистики:",
            buttons=buttons
        )
    
    async def search_handler(self, event: Message):
        """Handle /search command."""
        self._track_user(event)
        
        match = re.match(r'^/search(?:\s+(.+))?', event.message.text)
        query = match.group(1) if match else None
        
        if not query:
            await event.respond("Пожалуйста, укажите поисковый запрос.\nПример: /search название песни")
            return
        
        # Track search
        user_id = event.sender_id
        username = event.sender.username if event.sender else None
        self.stats.track_search(user_id, username)
        
        searching_msg = await event.respond(f"🔍 Поиск: {query}...")
        results = await search_youtube(query, max_results=5)
        
        if not results:
            await searching_msg.edit("Ничего не найдено. Попробуйте изменить запрос.")
            return
        
        buttons = []
        for i, result in enumerate(results, 1):
            duration = int(result['duration']) if result['duration'] else 0
            duration_min = duration // 60
            duration_sec = duration % 60
            button_text = f"{i}. {result['title'][:50]}{'...' if len(result['title']) > 50 else ''} ({duration_min}:{duration_sec:02d})"
            buttons.append([Button.inline(button_text, data=f"select_{result['url']}")])
        
        await searching_msg.edit("Выберите видео из результатов поиска:", buttons=buttons)
    
    async def message_handler(self, event: Message):
        """Handle incoming messages with YouTube, TikTok and Twitter links."""
        if event.message.text is None:
            return
        
        user_id, username = self._get_user_info(event)
        
        # Check if user is in report state
        if user_id in REPORT_STATES and REPORT_STATES[user_id]:
            report_text = event.message.text
            
            # Ignore if user sends another command while in report state
            if report_text.startswith('/'):
                # Handle /cancel command
                if report_text.strip() == '/cancel':
                    del REPORT_STATES[user_id]
                    await event.respond("❌ Отправка отчета отменена.")
                return
            
            # Save report to database
            self.stats.save_user_report(user_id, username, report_text)
            
            # Send report to admins
            report_msg = f"📋 **Новый отчет**\n\nОт: @{username or user_id}\nID: {user_id}\n\nТекст:\n{report_text}"
            
            for admin_id in self.download_limiter.ADMIN_USER_IDS:
                try:
                    await self.client.send_message(admin_id, report_msg)
                except Exception as e:
                    logger.error(f"Failed to send report to admin {admin_id}: {e}")
            
            # Confirm to user
            await event.respond("✅ Спасибо! Ваш отчет отправлен администраторам.")
            
            # Clear state
            del REPORT_STATES[user_id]
            return
        
        if event.message.text.startswith('/'):
            return
        
        self._track_user(event)
        
        # Check for Twitter/X
        twitter_match = TWITTER_REGEX.search(event.message.text)
        if twitter_match:
            await self._handle_twitter(event, twitter_match.group(0))
            return
        
        # Check for TikTok
        tiktok_match = TIKTOK_REGEX.search(event.message.text)
        if tiktok_match:
            await self._handle_tiktok(event, tiktok_match.group(0))
            return
        
        # Check for YouTube (including Shorts)
        youtube_match = YOUTUBE_REGEX.search(event.message.text)
        if not youtube_match:
            await event.respond("Пожалуйста, отправьте корректную ссылку на видео YouTube, YouTube Shorts, TikTok или Twitter/X.")
            return
        
        # Check if it's a YouTube Shorts
        if '/shorts/' in event.message.text:
            await self._handle_youtube_shorts(event, youtube_match.group(0))
        else:
            await self._show_content_type_selection(event, youtube_match.group(0))
    
    async def _handle_tiktok(self, event: Message, url: str):
        """Handle TikTok video download."""
        user_id, username = self._get_user_info(event)
        download_id = str(uuid.uuid4())
        
        # Check download limit
        if not await self._check_download_limit(event, user_id, download_id):
            return
        
        try:
            async with event.client.action(event.chat_id, 'video'):
                try:
                    processing_msg = await event.respond("Загрузка TikTok видео... Пожалуйста, подождите.")
                    logger.info(f"Downloading TikTok video: {url}")
                    
                    file_path, metadata = await download_tiktok_video(url)
                    logger.info(f"TikTok video downloaded successfully: {file_path}")
                    
                    await send_video_content(event, file_path, metadata, self.bot_username)
                    await processing_msg.delete()
                    
                    # Track successful TikTok download
                    self.stats.track_tiktok_download(user_id, username, success=True)
                    
                    # Cleanup
                    if os.path.exists(os.path.dirname(file_path)):
                        shutil.rmtree(os.path.dirname(file_path))
                        
                except Exception as e:
                    logger.error(f"Error sending TikTok video: {e}")
                    # Track failed TikTok download
                    self.stats.track_tiktok_download(user_id, username, success=False, error_message=str(e))
                    await event.respond(f"Произошла ошибка при обработке TikTok видео: {str(e)}")
        finally:
            # Always release the download slot
            self.download_limiter.finish_download(user_id, download_id)
    
    async def _show_content_type_selection(self, event: Message, url: str):
        """Show content type selection buttons for YouTube."""
        buttons = [
            [
                Button.inline("🎬 Видео", data=f"content_video_{url}"),
                Button.inline("🎵 Аудио", data=f"content_audio_{url}")
            ]
        ]
        await event.respond("Выберите тип контента для загрузки:", buttons=buttons)
    
    async def _handle_youtube_shorts(self, event: Message, url: str):
        """Handle YouTube Shorts download."""
        user_id, username = self._get_user_info(event)
        download_id = str(uuid.uuid4())
        
        if not await self._check_download_limit(event, user_id, download_id):
            return
        
        try:
            async with event.client.action(event.chat_id, 'video'):
                try:
                    processing_msg = await event.respond("Загрузка YouTube Short... Пожалуйста, подождите.")
                    logger.info(f"Downloading YouTube Short: {url}")
                    
                    file_path, metadata = await download_youtube_video(url, quality='best')
                    logger.info(f"YouTube Short downloaded successfully: {file_path}")
                    
                    await send_video_content(event, file_path, metadata, self.bot_username)
                    await processing_msg.delete()
                    
                    self.stats.track_video_download(user_id, 'auto', 'youtube_shorts', username, success=True)
                    
                    if os.path.exists(os.path.dirname(file_path)):
                        shutil.rmtree(os.path.dirname(file_path))
                        
                except Exception as e:
                    logger.error(f"Error sending YouTube Short: {e}")
                    self.stats.track_video_download(user_id, 'auto', 'youtube_shorts', username, success=False, error_message=str(e))
                    await event.respond(f"Произошла ошибка при обработке YouTube Short: {str(e)}")
        finally:
            self.download_limiter.finish_download(user_id, download_id)

    
    
    async def _handle_select_callback(self, event, data: str):
        """Handle video selection from search results."""
        url = data[7:]  # Remove 'select_' prefix
        await self._show_content_type_selection(event, url)
    
    async def _handle_content_callback(self, event, data: str):
        """Handle content type selection (video/audio)."""
        parts = data.split('_', 2)
        if len(parts) != 3:
            return
        
        content_type, url = parts[1], parts[2]
        
        if content_type == 'video':
            await self._show_video_quality_selection(event, url)
        elif content_type == 'audio':
            await self._show_audio_quality_selection(event, url)
    
    async def _show_video_quality_selection(self, event, url: str):
        """Show video quality selection buttons."""
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
            row.append(Button.inline(label, data=f"quality_{quality_id}_{url}"))
            
            # Two buttons per row
            if len(row) == 2:
                buttons.append(row)
                row = []
        
        # Add remaining buttons
        if row:
            buttons.append(row)
        
        if not buttons:
            logger.warning(f"No buttons created for available heights: {available_heights}")
            await event.edit("К сожалению, для этого видео нет доступных форматов. Попробуйте другое видео.")
            return
        
        await event.edit("Выберите качество видео:", buttons=buttons)
    
    async def _show_audio_quality_selection(self, event, url: str):
        """Show audio quality selection buttons."""
        buttons = [
            [
                Button.inline("Высокое качество", data=f"audio_high_{url}"),
                Button.inline("Среднее качество", data=f"audio_medium_{url}")
            ],
            [
                Button.inline("Низкое качество", data=f"audio_low_{url}")
            ]
        ]
        await event.edit("Выберите качество аудио:", buttons=buttons)
    
    async def _handle_quality_callback(self, event, data: str):
        """Handle video quality selection."""
        parts = data.split('_', 2)
        if len(parts) != 3:
            return
        
        quality, url = parts[1], parts[2]
        await event.answer(f"Загрузка видео в качестве {quality}...")
        
        await self._download_and_send_video(event, url, quality)
    
    async def _handle_audio_callback(self, event, data: str):
        """Handle audio quality selection."""
        parts = data.split('_', 2)
        if len(parts) != 3:
            return
        
        quality, url = parts[1], parts[2]
        await event.answer(f"Загрузка аудио в качестве {quality}...")
        
        await self._download_and_send_audio(event, url, quality)
    
    async def _download_and_send_video(self, event, url: str, quality: str):
        """Download and send YouTube video."""
        def track_video(user_id, quality, username, success, error_message=None):
            self.stats.track_video_download(user_id, quality, 'youtube', username, success=success, error_message=error_message)
        
        await self._download_and_send_content(
            event=event,
            url=url,
            quality=quality,
            content_type="видео",
            download_func=download_youtube_video,
            send_func=send_video_content,
            track_func=track_video,
            action='video'
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
            action='audio'
        )
    
    async def _handle_stats_callback(self, event, data: str):
        """Handle statistics view callback."""
        period = data.split('_')[1]  # Extract period (day, month, all)
        
        await event.answer("Загрузка статистики...")
        
        try:
            stats = self.stats.get_statistics(period)
            
            # Format period name in Russian
            period_names = {
                'day': 'за день',
                'month': 'за месяц',
                'all': 'за все время'
            }
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
            if stats['popular_video_formats']:
                message += "📊 Популярные форматы видео:\n"
                for format_name, count in stats['popular_video_formats']:
                    message += f"  • {format_name}: {count}\n"
                message += "\n"
            
            # Popular audio formats
            if stats['popular_audio_formats']:
                message += "🎧 Популярные форматы аудио:\n"
                for format_name, count in stats['popular_audio_formats']:
                    message += f"  • {format_name}: {count}\n"
            
            # Add buttons to switch periods
            buttons = [
                [
                    Button.inline("📊 За день", data="stats_day"),
                    Button.inline("📅 За месяц", data="stats_month")
                ],
                [
                    Button.inline("📈 За все время", data="stats_all")
                ]
            ]
            
            await event.edit(message, buttons=buttons)
            
        except Exception as e:
            logger.error(f"Error getting statistics: {e}")
            await event.edit(f"Произошла ошибка при получении статистики: {str(e)}")
    
    async def _handle_twitter(self, event: Message, url: str):
        """Handle Twitter/X video and photo download."""
        user_id, username = self._get_user_info(event)
        download_id = str(uuid.uuid4())
        
        if not await self._check_download_limit(event, user_id, download_id):
            return
        
        try:
            async with event.client.action(event.chat_id, 'video'):
                try:
                    processing_msg = await event.respond("Загрузка с Twitter... Пожалуйста, подождите.")
                    logger.info(f"Downloading Twitter content: {url}")
                    
                    file_path, metadata = await download_twitter_video(url)
                    logger.info(f"Twitter content downloaded successfully: {file_path}")
                    
                    # Send appropriate content type
                    if metadata.get('content_type') == 'photo':
                        await send_image_content(event, file_path, self.bot_username)
                    else:
                        await send_video_content(event, file_path, metadata, self.bot_username)
                    
                    await processing_msg.delete()
                    
                    self.stats.track_tiktok_download(user_id, username, success=True)
                    
                    if os.path.exists(os.path.dirname(file_path)):
                        shutil.rmtree(os.path.dirname(file_path))
                        
                except Exception as e:
                    logger.error(f"Error sending Twitter content: {e}")
                    self.stats.track_tiktok_download(user_id, username, success=False, error_message=str(e))
                    await event.respond(f"Произошла ошибка при обработке контента: {str(e)}")
        finally:
            self.download_limiter.finish_download(user_id, download_id)
    
    async def post_handler(self, event: Message):
        """Handle /post command for admin broadcast."""
        user_id, username = self._get_user_info(event)
        
        if user_id not in self.download_limiter.ADMIN_USER_IDS:
            await event.respond("❌ У вас нет доступа к этой команде.")
            return
        
        # Check if it's a reply
        if not event.message.is_reply:
            await event.respond("ℹ️ Используйте команду /post в ответе на сообщение, которое нужно переслать всем пользователям.")
            return
        
        try:
            reply_msg = await event.message.get_reply_message()
            
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
            
            await processing_msg.edit(result)
            
        except Exception as e:
            logger.error(f"Error in post handler: {e}")
            await event.respond(f"Произошла ошибка: {str(e)}")
    
    async def report_handler(self, event: Message):
        """Handle /report command for user reports."""
        user_id, username = self._get_user_info(event)
        
        REPORT_STATES[user_id] = True
        
        await event.respond(
            "📝 Опишите проблему (или отправьте /cancel для отмены):",
            buttons=[[Button.inline("❌ Отмена", data="report_cancel")]]
        )
    
    async def callback_handler(self, event):
        """Handle callback queries from inline buttons."""
        data = event.data.decode('utf-8')
        user_id = event.sender_id
        
        # Handle report cancel
        if data == "report_cancel":
            if user_id in REPORT_STATES:
                del REPORT_STATES[user_id]
            await event.edit("❌ Отправка отчета отменена.")
            return
        
        # Route callbacks using dictionary
        handlers: Dict[str, Callable] = {
            'select_': self._handle_select_callback,
            'content_': self._handle_content_callback,
            'quality_': self._handle_quality_callback,
            'audio_': self._handle_audio_callback,
            'stats_': self._handle_stats_callback,
        }
        
        for prefix, handler in handlers.items():
            if data.startswith(prefix):
                await handler(event, data)
                return
        
        logger.warning(f"Unknown callback data: {data}")

