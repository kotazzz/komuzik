"""Configuration constants and settings for the bot."""
import os
import re
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# API credentials
API_ID = int(os.getenv("API_ID", 0))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
SESSION_STRING = os.getenv("SESSION_STRING", "")

# URL regex patterns
YOUTUBE_REGEX = re.compile(
    r'(https?://)?(www\.)?(youtube|youtu|youtube-nocookie)\.(com|be)/(watch\?v=|embed/|v/|.+\?v=)?([^&=%\?]{11})'
)
TIKTOK_REGEX = re.compile(
    r'(https?://)?(www\.|vm\.|vt\.)?(tiktok\.com)/(\S+)'
)

# Video quality settings
DEFAULT_VIDEO_WIDTH = 1280
DEFAULT_VIDEO_HEIGHT = 720
DEFAULT_TIKTOK_WIDTH = 720
DEFAULT_TIKTOK_HEIGHT = 1280

# Audio quality settings
AUDIO_FORMAT = 'mp3'
AUDIO_BITRATE = '192'
AUDIO_QUALITY_SETTINGS = {
    'high': 'bestaudio/best',
    'medium': 'bestaudio[abr<=128]/bestaudio/best',
    'low': 'bestaudio[abr<=96]/bestaudio/best',
}

# YT-DLP base options
YDLP_BASE_OPTS = {
    'quiet': True,
    'no_warnings': True,
    'noplaylist': True,
}

# Common video format fallbacks
VIDEO_FALLBACK_QUALITIES = [1080, 720, 480, 360, 240]

# Search settings
DEFAULT_SEARCH_RESULTS = 5

# Bot messages
MSG_START = (
    "👋 Привет! Я бот для скачивания видео и музыки с YouTube и TikTok.\n\n"
    "📺 **YouTube**: выбирайте качество видео и аудио\n"
    "🎵 **TikTok**: автоматическая загрузка видео\n\n"
    "Просто отправьте мне ссылку на видео!\n\n"
    "Для получения помощи используйте команду /help."
)

MSG_HELP = (
    "🔍 **Как пользоваться ботом:**\n\n"
    "1. Отправьте мне ссылку на видео YouTube или TikTok\n"
    "2. Используйте /search для поиска видео на YouTube\n"
    "3. Для YouTube: выберите тип контента (видео или аудио) и качество\n"
    "4. Для TikTok: видео скачается автоматически\n"
    "5. Дождитесь загрузки и получите файл\n\n"
    "📌 **Доступные команды:**\n"
    "/start - Запустить бота\n"
    "/help - Показать справку\n"
    "/search <запрос> - Поиск видео на YouTube\n"
    "/stats - Показать статистику бота\n\n"
    "🎬 **Поддерживаемые платформы:**\n"
    "• YouTube (с выбором качества)\n"
    "• TikTok (автоматическая загрузка)"
)
