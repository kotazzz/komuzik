"""Configuration constants and settings for the bot."""
import os
import re
from dotenv import load_dotenv
from .config_loader import ConfigLoader

# Load environment variables
load_dotenv()

# Load YAML configuration
_config = ConfigLoader()

# API credentials
API_ID = int(os.getenv("API_ID", 0))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
SESSION_STRING = os.getenv("SESSION_STRING", "")

# URL regex patterns
YOUTUBE_REGEX = re.compile(
    r'(https?://)?(www\.)?(youtube|youtu|youtube-nocookie)\.(com|be)/(watch\?v=|embed/|v/|shorts/|.+\?v=)?([^&=%\?]{11})'
)
TIKTOK_REGEX = re.compile(
    r'(https?://)?(www\.|vm\.|vt\.)?(tiktok\.com)/(\S+)'
)
TWITTER_REGEX = re.compile(
    r'(https?://)?(www\.|mobile\.)?(twitter\.com|x\.com)/(\S+)'
)

# ============= Video Settings =============
VIDEO_SETTINGS = _config.get_section('video')

DEFAULT_VIDEO_WIDTH = VIDEO_SETTINGS.get('default_youtube_width', 1280)
DEFAULT_VIDEO_HEIGHT = VIDEO_SETTINGS.get('default_youtube_height', 720)
DEFAULT_TIKTOK_WIDTH = VIDEO_SETTINGS.get('default_tiktok_width', 720)
DEFAULT_TIKTOK_HEIGHT = VIDEO_SETTINGS.get('default_tiktok_height', 1280)

# ============= Download Settings =============
DOWNLOAD_SETTINGS = _config.get_section('downloads')

MAX_DOWNLOADS_PER_USER = DOWNLOAD_SETTINGS.get('max_concurrent_per_user', 3)
ADMIN_USER_IDS = set(DOWNLOAD_SETTINGS.get('admin_user_ids', []))
UNLIMITED_USER_IDS = set(DOWNLOAD_SETTINGS.get('unlimited_user_ids', []))

# ============= Audio Settings =============
AUDIO_SETTINGS = _config.get_section('audio')

AUDIO_FORMAT = AUDIO_SETTINGS.get('format', 'mp3')
AUDIO_BITRATE = AUDIO_SETTINGS.get('default_bitrate', '192')
AUDIO_QUALITY_SETTINGS = AUDIO_SETTINGS.get('quality_presets', {
    'high': 'bestaudio/best',
    'medium': 'bestaudio[abr<=128]/bestaudio/best',
    'low': 'bestaudio[abr<=96]/bestaudio/best',
})

# ============= YT-DLP Settings =============
YDLP_SETTINGS = _config.get_section('yt_dlp')

YDLP_BASE_OPTS = {
    'quiet': YDLP_SETTINGS.get('quiet', True),
    'no_warnings': YDLP_SETTINGS.get('no_warnings', True),
    'noplaylist': YDLP_SETTINGS.get('noplaylist', True),
}

# ============= YouTube Settings =============
YOUTUBE_SETTINGS = _config.get_section('youtube')

VIDEO_FALLBACK_QUALITIES = YOUTUBE_SETTINGS.get('video_fallback_qualities', [1080, 720, 480, 360, 240])
DEFAULT_SEARCH_RESULTS = YOUTUBE_SETTINGS.get('default_search_results', 5)

# ============= TikTok Settings =============
TIKTOK_SETTINGS = _config.get_section('tiktok')

TIKTOK_MAX_RETRIES = TIKTOK_SETTINGS.get('max_retries', 3)
TIKTOK_RETRY_BACKOFF = TIKTOK_SETTINGS.get('retry_backoff_base', 2)
TIKTOK_ERROR_MESSAGE = TIKTOK_SETTINGS.get(
    'error_message',
    'Не удается загрузить видео с TikTok. Пожалуйста, проверьте ссылку и попробуйте позже.'
)

# ============= Twitter/X Settings =============
TWITTER_SETTINGS = _config.get_section('twitter')

TWITTER_MAX_RETRIES = TWITTER_SETTINGS.get('max_retries', 3)
TWITTER_RETRY_BACKOFF = TWITTER_SETTINGS.get('retry_backoff_base', 2)
TWITTER_ERROR_MESSAGE = TWITTER_SETTINGS.get(
    'error_message',
    'Не удается загрузить видео с Twitter/X. Пожалуйста, проверьте ссылку и попробуйте позже.'
)

# ============= Bot Messages =============
MESSAGES = _config.get_section('messages')

MSG_START = MESSAGES.get('start', 
    "👋 Привет! Я бот для скачивания видео и музыки с YouTube и TikTok.\n\n"
    "📺 **YouTube**: выбирайте качество видео и аудио\n"
    "🎵 **TikTok**: автоматическая загрузка видео\n\n"
    "Просто отправьте мне ссылку на видео!"
)

MSG_HELP = MESSAGES.get('help',
    "🔍 **Как пользоваться ботом:**\n\n"
    "1. Отправьте ссылку на видео с YouTube, YouTube Shorts, TikTok или Twitter/X\n"
    "2. /search <запрос> - поиск видео на YouTube\n"
    "3. /report - отправить报告 о проблеме\n"
    "4. /stats - статистика бота\n\n"
    "📌 **Поддерживаемые платформы:**\n"
    "• YouTube (видео и аудио, выбор качества)\n"
    "• YouTube Shorts (видео)\n"
    "• TikTok (видео)\n"
    "• Twitter/X (видео, фото, альбомы)"
)

