"""Event handlers for Telegram bot commands and callbacks."""
import re
import logging
import shutil
import os
from typing import Callable, Dict
from telethon import events, Button
from telethon.tl.custom import Message

from .config import YOUTUBE_REGEX, TIKTOK_REGEX, MSG_START, MSG_HELP
from .downloaders import (
    get_available_formats,
    search_youtube,
    download_youtube_video,
    download_youtube_audio,
    download_tiktok_video,
    send_video_content,
    send_audio_content,
)

logger = logging.getLogger(__name__)


class BotHandlers:
    """Handles all bot commands and callbacks."""
    
    def __init__(self, client, bot_username: str = ""):
        self.client = client
        self.bot_username = bot_username
        self._register_handlers()
    
    def _register_handlers(self):
        """Register all event handlers."""
        self.client.on(events.NewMessage(pattern='/start'))(self.start_handler)
        self.client.on(events.NewMessage(pattern='/help'))(self.help_handler)
        self.client.on(events.NewMessage(pattern=r'^/search(?:\s+(.+))?'))(self.search_handler)
        self.client.on(events.NewMessage())(self.message_handler)
        self.client.on(events.CallbackQuery())(self.callback_handler)
    
    async def start_handler(self, event: Message):
        """Handle /start command."""
        await event.respond(MSG_START)
    
    async def help_handler(self, event: Message):
        """Handle /help command."""
        await event.respond(MSG_HELP)
    
    async def search_handler(self, event: Message):
        """Handle /search command."""
        match = re.match(r'^/search(?:\s+(.+))?', event.message.text)
        query = match.group(1) if match else None
        
        if not query:
            await event.respond("Пожалуйста, укажите поисковый запрос.\nПример: /search название песни")
            return
        
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
        """Handle incoming messages with YouTube and TikTok links."""
        if event.message.text.startswith('/'):
            return
        
        # Check for TikTok
        tiktok_match = TIKTOK_REGEX.search(event.message.text)
        if tiktok_match:
            await self._handle_tiktok(event, tiktok_match.group(0))
            return
        
        # Check for YouTube
        youtube_match = YOUTUBE_REGEX.search(event.message.text)
        if not youtube_match:
            await event.respond("Пожалуйста, отправьте корректную ссылку на видео YouTube или TikTok.")
            return
        
        await self._show_content_type_selection(event, youtube_match.group(0))
    
    async def _handle_tiktok(self, event: Message, url: str):
        """Handle TikTok video download."""
        async with event.client.action(event.chat_id, 'video'):
            try:
                processing_msg = await event.respond("Загрузка TikTok видео... Пожалуйста, подождите.")
                logger.info(f"Downloading TikTok video: {url}")
                
                file_path, metadata = await download_tiktok_video(url)
                logger.info(f"TikTok video downloaded successfully: {file_path}")
                
                await send_video_content(event, file_path, metadata, self.bot_username)
                await processing_msg.delete()
                
                # Cleanup
                if os.path.exists(os.path.dirname(file_path)):
                    shutil.rmtree(os.path.dirname(file_path))
                    
            except Exception as e:
                logger.error(f"Error sending TikTok video: {e}")
                await event.respond(f"Произошла ошибка при обработке TikTok видео: {str(e)}")
    
    async def _show_content_type_selection(self, event: Message, url: str):
        """Show content type selection buttons for YouTube."""
        buttons = [
            [
                Button.inline("🎬 Видео", data=f"content_video_{url}"),
                Button.inline("🎵 Аудио", data=f"content_audio_{url}")
            ]
        ]
        await event.respond("Выберите тип контента для загрузки:", buttons=buttons)
    
    async def callback_handler(self, event):
        """Handle callback queries from inline buttons."""
        data = event.data.decode('utf-8')
        
        # Route callbacks using dictionary
        handlers: Dict[str, Callable] = {
            'select_': self._handle_select_callback,
            'content_': self._handle_content_callback,
            'quality_': self._handle_quality_callback,
            'audio_': self._handle_audio_callback,
        }
        
        for prefix, handler in handlers.items():
            if data.startswith(prefix):
                await handler(event, data)
                return
        
        logger.warning(f"Unknown callback data: {data}")
    
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
        async with event.client.action(event.chat_id, 'video'):
            try:
                processing_msg = await event.respond("Загрузка видео... Пожалуйста, подождите.")
                logger.info(f"Downloading video: {url} with quality: {quality}")
                
                file_path, metadata = await download_youtube_video(url, quality)
                logger.info(f"Video downloaded successfully: {file_path}")
                
                await send_video_content(event, file_path, metadata, self.bot_username)
                await processing_msg.delete()
                
                # Cleanup
                if os.path.exists(os.path.dirname(file_path)):
                    shutil.rmtree(os.path.dirname(file_path))
                    
            except Exception as e:
                logger.error(f"Error sending video: {e}")
                await event.respond(f"Произошла ошибка при обработке видео: {str(e)}")
    
    async def _download_and_send_audio(self, event, url: str, quality: str):
        """Download and send YouTube audio."""
        async with event.client.action(event.chat_id, 'audio'):
            try:
                processing_msg = await event.respond("Загрузка аудио... Пожалуйста, подождите.")
                logger.info(f"Downloading audio: {url} with quality: {quality}")
                
                file_path, metadata = await download_youtube_audio(url, quality)
                logger.info(f"Audio downloaded successfully: {file_path}")
                
                await send_audio_content(event, file_path, metadata, self.bot_username)
                await processing_msg.delete()
                
                # Cleanup
                if os.path.exists(os.path.dirname(file_path)):
                    shutil.rmtree(os.path.dirname(file_path))
                    
            except Exception as e:
                logger.error(f"Error sending audio: {e}")
                await event.respond(f"Произошла ошибка при обработке аудио: {str(e)}")
