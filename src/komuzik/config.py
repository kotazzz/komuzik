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
    r'(https?://)?(www\.)?(youtube|youtu|youtube-nocookie)\.(com|be)/(watch\?v=|embed/|v/|.+\?v=)?([^&=%\?]{11})'
)
TIKTOK_REGEX = re.compile(
    r'(https?://)?(www\.|vm\.|vt\.)?(tiktok\.com)/(\S+)'
)

# ============= Video Settings =============
VIDEO_SETTINGS = _config.get_section('video')

DEFAULT_VIDEO_WIDTH = VIDEO_SETTINGS.get('default_youtube_width', 1280)
DEFAULT_VIDEO_HEIGHT = VIDEO_SETTINGS.get('default_youtube_height', 720)
DEFAULT_TIKTOK_WIDTH = VIDEO_SETTINGS.get('default_tiktok_width', 720)
DEFAULT_TIKTOK_HEIGHT = VIDEO_SETTINGS.get('default_tiktok_height', 1280)

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
    "1. Отправьте мне ссылку на видео YouTube или TikTok\n"
    "2. Используйте /search для поиска видео на YouTube\n"
    "3. Для YouTube: выберите тип контента (видео или аудио) и качество\n"
    "4. Для TikTok: видео скачается автоматически\n"
    "5. Дождитесь загрузки и получите файл"
)

