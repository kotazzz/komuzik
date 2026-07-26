"""Configuration constants and settings for the bot."""

import os
import re

from dotenv import load_dotenv

from .config_loader import ConfigLoader
from .i18n import t

# Load environment variables
load_dotenv()

# Load YAML configuration
_config = ConfigLoader()

# API credentials
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
SESSION_STRING = os.getenv("SESSION_STRING", "")

# URL regex patterns
YOUTUBE_REGEX = re.compile(
    r"(https?://)?(www\.)?(youtube|youtu|youtube-nocookie)\.(com|be)/(watch\?v=|embed/|v/|shorts/|.+\?v=)?([^&=%\?]{11})"
)
TIKTOK_REGEX = re.compile(r"(https?://)?(www\.|vm\.|vt\.)?(tiktok\.com)/(\S+)")
TWITTER_REGEX = re.compile(r"(https?://)?(www\.|mobile\.)?(twitter\.com|x\.com)/(\S+)")
PINTEREST_REGEX = re.compile(
    r"(https?://)?(www\.|[a-z]{2}\.)?(pinterest\.com/pin/|pinterest\.co\.uk/pin/|pin\.it/)(\S+)"
)
HLS_HOST_REGEX = re.compile(
    r"(https?://)?(www\.)?murrtube\.net/v/([A-Za-z0-9_-]+)"
)

# ============= Video Settings =============
VIDEO_SETTINGS = _config.get_section("video")

DEFAULT_VIDEO_WIDTH = VIDEO_SETTINGS.get("default_youtube_width", 1280)
DEFAULT_VIDEO_HEIGHT = VIDEO_SETTINGS.get("default_youtube_height", 720)
DEFAULT_TIKTOK_WIDTH = VIDEO_SETTINGS.get("default_tiktok_width", 720)
DEFAULT_TIKTOK_HEIGHT = VIDEO_SETTINGS.get("default_tiktok_height", 1280)

# ============= Download Settings =============
DOWNLOAD_SETTINGS = _config.get_section("downloads")

MAX_DOWNLOADS_PER_USER = DOWNLOAD_SETTINGS.get("max_concurrent_per_user", 3)
MAX_DOWNLOAD_SIZE_BYTES = DOWNLOAD_SETTINGS.get("max_download_size_bytes", 2 * 1024 * 1024 * 1024)
ADMIN_USER_IDS = set(DOWNLOAD_SETTINGS.get("admin_user_ids", []))
UNLIMITED_USER_IDS = set(DOWNLOAD_SETTINGS.get("unlimited_user_ids", []))

# ============= Audio Settings =============
AUDIO_SETTINGS = _config.get_section("audio")

AUDIO_FORMAT = AUDIO_SETTINGS.get("format", "mp3")
AUDIO_BITRATE = AUDIO_SETTINGS.get("default_bitrate", "192")
AUDIO_QUALITY_SETTINGS = AUDIO_SETTINGS.get(
    "quality_presets",
    {
        "high": "bestaudio/best",
        "medium": "bestaudio[abr<=128]/bestaudio/best",
        "low": "bestaudio[abr<=96]/bestaudio/best",
    },
)

# ============= YT-DLP Settings =============
YDLP_SETTINGS = _config.get_section("yt_dlp")

YDLP_BASE_OPTS = {
    "quiet": YDLP_SETTINGS.get("quiet", True),
    "no_warnings": YDLP_SETTINGS.get("no_warnings", True),
    "noplaylist": YDLP_SETTINGS.get("noplaylist", True),
    # Without this a stalled connection blocks the worker thread forever;
    # asyncio.wait_for on the caller side cannot kill a thread, only stop waiting.
    "socket_timeout": YDLP_SETTINGS.get("socket_timeout", 30),
}

# Wall-clock ceiling for one download, applied by handlers via asyncio.wait_for.
DOWNLOAD_TIMEOUT_SECONDS = DOWNLOAD_SETTINGS.get("download_timeout_seconds", 3600)

# ============= YouTube Settings =============
YOUTUBE_SETTINGS = _config.get_section("youtube")

VIDEO_FALLBACK_QUALITIES = YOUTUBE_SETTINGS.get(
    "video_fallback_qualities", [1080, 720, 480, 360, 240]
)
DEFAULT_SEARCH_RESULTS = YOUTUBE_SETTINGS.get("default_search_results", 10)

# ============= TikTok Settings =============
TIKTOK_SETTINGS = _config.get_section("tiktok")

TIKTOK_MAX_RETRIES = TIKTOK_SETTINGS.get("max_retries", 3)
TIKTOK_RETRY_BACKOFF = TIKTOK_SETTINGS.get("retry_backoff_base", 2)

# ============= Twitter/X Settings =============
TWITTER_SETTINGS = _config.get_section("twitter")

TWITTER_MAX_RETRIES = TWITTER_SETTINGS.get("max_retries", 3)
TWITTER_RETRY_BACKOFF = TWITTER_SETTINGS.get("retry_backoff_base", 2)

# ============= Pinterest Settings =============
PINTEREST_SETTINGS = _config.get_section("pinterest")

PINTEREST_MAX_RETRIES = PINTEREST_SETTINGS.get("max_retries", 3)
PINTEREST_RETRY_BACKOFF = PINTEREST_SETTINGS.get("retry_backoff_base", 2)

# ============= Bot Messages (messages.yaml via t) =============
PRIVACY_URL = (
    "https://telegra.ph/Pravila-polzovaniya-i-politika-konfidencialnosti-bota-Komuzik-07-20"
)

MSG_START = t("start")
MSG_PRIVACY = t("privacy")
TIKTOK_ERROR_MESSAGE = t("errors.tiktok")
TWITTER_ERROR_MESSAGE = t("errors.twitter")
PINTEREST_ERROR_MESSAGE = t("errors.pinterest")
HLS_HOST_ERROR_MESSAGE = t("errors.download")
HLS_HOST_MAX_RETRIES = 3
HLS_HOST_RETRY_BACKOFF = 2

