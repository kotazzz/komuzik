"""Download functionality for YouTube and TikTok content."""

import asyncio
import json
import logging
import os
import shutil
import subprocess
import tempfile
from collections.abc import Mapping
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, cast

import yt_dlp
from telethon.tl.custom import Message
from telethon.tl.types import DocumentAttributeAudio, DocumentAttributeVideo
from yt_dlp.utils import DownloadError

from .config import (
    AUDIO_BITRATE,
    AUDIO_FORMAT,
    AUDIO_QUALITY_SETTINGS,
    DEFAULT_SEARCH_RESULTS,
    DEFAULT_VIDEO_HEIGHT,
    DEFAULT_VIDEO_WIDTH,
    MAX_DOWNLOAD_SIZE_BYTES,
    PINTEREST_ERROR_MESSAGE,
    PINTEREST_MAX_RETRIES,
    PINTEREST_RETRY_BACKOFF,
    TIKTOK_ERROR_MESSAGE,
    TIKTOK_MAX_RETRIES,
    TIKTOK_RETRY_BACKOFF,
    TWITTER_ERROR_MESSAGE,
    TWITTER_MAX_RETRIES,
    TWITTER_RETRY_BACKOFF,
    VIDEO_FALLBACK_QUALITIES,
    YDLP_BASE_OPTS,
)

logger = logging.getLogger(__name__)


def _safe_int(value: Any, default: int = 0) -> int:
    """Convert arbitrary values to int with a safe fallback."""
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


class DownloadTooLargeError(Exception):
    """Raised when a media file exceeds the configured size limit."""


def _find_downloaded_file(
    temp_dir: str, expected_extension: str | None = None, allow_images: bool = False
) -> str:
    """Find and verify downloaded file in temp directory.

    Args:
        temp_dir: Directory to search in
        expected_extension: Optional expected file extension (e.g., 'mp3')
        allow_images: If True, also include image files (for Twitter photos)

    Returns:
        Full path to the downloaded file

    Raises:
        Exception: If no files found, no valid media files, or file is empty

    """
    files = os.listdir(temp_dir)
    if not files:
        raise Exception("No files downloaded")

    # Filter out thumbnails unless allow_images is True
    if allow_images:
        media_files = list(files)
    else:
        media_files = [f for f in files if not f.endswith((".jpg", ".png", ".webp"))]

    # If expected extension specified, try to find file with that extension first
    if expected_extension:
        exact_match = [f for f in media_files if f.endswith(f".{expected_extension}")]
        if exact_match:
            media_files = exact_match

    if not media_files:
        raise Exception("No media file found in download directory")

    file_path = os.path.join(temp_dir, media_files[0])

    # Verify file is not empty
    if Path(file_path).stat().st_size == 0:
        raise Exception("The downloaded file is empty")

    return file_path


@asynccontextmanager
async def temp_directory():
    """Context manager for temporary directory cleanup."""
    temp_dir = tempfile.mkdtemp()
    try:
        yield temp_dir
    finally:
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)


async def get_available_formats(url: str) -> list[int]:
    """Get available video formats for a YouTube URL."""
    try:
        loop = asyncio.get_running_loop()
        with yt_dlp.YoutubeDL(cast("Any", YDLP_BASE_OPTS)) as ydl:
            info = cast(
                "dict[str, Any]", await loop.run_in_executor(None, ydl.extract_info, url, False)
            )
            formats = info.get("formats")
            if not isinstance(formats, list):
                formats = []

            available_heights = set()
            for fmt in formats:
                if not isinstance(fmt, Mapping):
                    continue
                height = fmt.get("height")
                vcodec = fmt.get("vcodec", "none")
                if isinstance(height, int) and vcodec and vcodec != "none":
                    available_heights.add(height)

            if not available_heights:
                logger.warning(f"No specific heights found for {url}, using fallback")
                return VIDEO_FALLBACK_QUALITIES

            return sorted(available_heights, reverse=True)
    except Exception as e:
        logger.error(f"Error getting available formats: {e}")
        return VIDEO_FALLBACK_QUALITIES


async def get_media_title(url: str, fallback: str = "Медиа") -> str:
    """Fetch a short title for inline results without downloading the file."""
    try:
        loop = asyncio.get_running_loop()
        with yt_dlp.YoutubeDL(cast("Any", YDLP_BASE_OPTS)) as ydl:
            info = cast(
                "dict[str, Any]", await loop.run_in_executor(None, ydl.extract_info, url, False)
            )
        title = info.get("title") or info.get("fulltitle") or fallback
        title = str(title).strip()
        if len(title) > 64:
            title = title[:61] + "..."
        return title or fallback
    except Exception as e:
        logger.warning(f"Failed to get media title for {url}: {e}")
        return fallback


async def search_youtube(query: str, max_results: int = DEFAULT_SEARCH_RESULTS) -> list[dict]:
    """Search for YouTube videos and return top results."""
    try:
        loop = asyncio.get_running_loop()
        ydl_opts = {
            **YDLP_BASE_OPTS,
            "extract_flat": True,
            "default_search": "ytsearch",
        }

        search_query = f"ytsearch{max_results}:{query}"

        with yt_dlp.YoutubeDL(cast("Any", ydl_opts)) as ydl:
            search_results = cast(
                "dict[str, Any]",
                await loop.run_in_executor(None, ydl.extract_info, search_query, False),
            )
            entries = search_results.get("entries")
            if not isinstance(entries, list):
                entries = []

            results = []
            for entry in entries:
                if not isinstance(entry, Mapping):
                    continue
                results.append(
                    {
                        "id": entry.get("id", ""),
                        "title": entry.get("title", "Unknown"),
                        "url": f"https://www.youtube.com/watch?v={entry.get('id', '')}",
                        "duration": entry.get("duration", 0),
                        "channel": entry.get("channel", "Unknown"),
                    }
                )

            return results
    except Exception as e:
        logger.error(f"Error searching YouTube: {e}")
        return []


def _extract_metadata(info: Mapping[str, Any], title: str) -> tuple[str, str]:
    """Extract artist and track name from video info."""
    artist = info.get("artist") or info.get("creator") or info.get("uploader", "Unknown Artist")
    track = info.get("track") or title

    # Try to parse "Artist - Track" format from title if no artist metadata
    if artist == "Unknown Artist" and " - " in title:
        parts = title.split(" - ", 1)
        artist = parts[0].strip()
        track = parts[1].strip()

    return artist, track


def _build_video_format(quality: str) -> str:
    """Build format string for video download.

    Prefer H.264 (avc1) + AAC (mp4a): Telegram iOS/macOS cannot play AV1/VP9
    in-app (black picture, audio works). Android and external players are fine.
    """
    # Fallbacks still allow non-H.264; _ensure_telegram_ios_video re-encodes if needed.
    try:
        if quality.endswith("p"):
            height = int(quality[:-1])
            h = f"[height<={height}]"
            return (
                f"bestvideo{h}[vcodec^=avc1]+bestaudio[acodec^=mp4a]/"
                f"best{h}[vcodec^=avc1][acodec^=mp4a]/"
                f"bestvideo{h}[vcodec^=avc1]+bestaudio/"
                f"best{h}/"
                f"bestvideo{h}+bestaudio/best"
            )
        return (
            "bestvideo[vcodec^=avc1]+bestaudio[acodec^=mp4a]/"
            "best[vcodec^=avc1][acodec^=mp4a]/"
            "bestvideo[vcodec^=avc1]+bestaudio/"
            "bestvideo+bestaudio/best"
        )
    except (ValueError, AttributeError):
        return "bestvideo[vcodec^=avc1]+bestaudio[acodec^=mp4a]/bestvideo+bestaudio/best"


def _is_h264_codec(codec: str | None) -> bool:
    """Return True if codec name is H.264/AVC."""
    if not codec:
        return False
    name = codec.lower()
    return name in {"h264", "avc1", "avc"} or name.startswith(("avc1", "h264"))


async def _probe_video_file(file_path: str) -> dict[str, Any]:
    """Read codec/dimensions/duration from a media file via ffprobe."""
    loop = asyncio.get_running_loop()

    def _run() -> dict[str, Any]:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-print_format",
                "json",
                "-show_streams",
                "-show_format",
                file_path,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            logger.warning(f"ffprobe failed for {file_path}: {result.stderr}")
            return {}
        try:
            return json.loads(result.stdout or "{}")
        except json.JSONDecodeError:
            return {}

    probe = await loop.run_in_executor(None, _run)
    video_stream = next(
        (
            s
            for s in probe.get("streams", [])
            if isinstance(s, dict) and s.get("codec_type") == "video"
        ),
        None,
    )
    audio_stream = next(
        (
            s
            for s in probe.get("streams", [])
            if isinstance(s, dict) and s.get("codec_type") == "audio"
        ),
        None,
    )
    fmt_raw = probe.get("format")
    fmt: dict[str, Any] = fmt_raw if isinstance(fmt_raw, dict) else {}

    duration = 0
    if video_stream and video_stream.get("duration"):
        duration = _safe_int(float(video_stream["duration"]), 0)
    elif fmt.get("duration"):
        duration = _safe_int(float(fmt["duration"]), 0)

    return {
        "vcodec": (video_stream or {}).get("codec_name"),
        "acodec": (audio_stream or {}).get("codec_name"),
        "width": _safe_int((video_stream or {}).get("width"), 0),
        "height": _safe_int((video_stream or {}).get("height"), 0),
        "duration": duration,
    }


async def _ensure_telegram_ios_video(file_path: str) -> tuple[str, dict[str, Any]]:
    """Ensure MP4 is H.264+yuv420p (+AAC when possible) for Telegram iOS/macOS.

    Returns:
        (path, probe_metadata) — path may be a new file in the same directory.

    """
    probe = await _probe_video_file(file_path)
    vcodec = probe.get("vcodec")
    needs_reencode = not _is_h264_codec(vcodec if isinstance(vcodec, str) else None)

    loop = asyncio.get_running_loop()
    out_path = str(Path(file_path).with_name(f"{Path(file_path).stem}_tg.mp4"))

    def _run_ffmpeg(args: list[str]) -> None:
        result = subprocess.run(args, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg failed: {result.stderr[-2000:]}")

    if needs_reencode:
        logger.info(
            f"Re-encoding {file_path} to H.264/AAC for Telegram iOS (source vcodec={vcodec!r})"
        )
        await loop.run_in_executor(
            None,
            _run_ffmpeg,
            [
                "ffmpeg",
                "-y",
                "-i",
                file_path,
                "-c:v",
                "libx264",
                "-preset",
                "fast",
                "-crf",
                "23",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-movflags",
                "+faststart",
                out_path,
            ],
        )
        try:
            os.remove(file_path)
        except OSError:
            pass
        file_path = out_path
    else:
        # Remux with faststart so Telegram can stream without full download.
        logger.debug(f"Remuxing {file_path} with +faststart (already H.264)")
        await loop.run_in_executor(
            None,
            _run_ffmpeg,
            [
                "ffmpeg",
                "-y",
                "-i",
                file_path,
                "-c",
                "copy",
                "-movflags",
                "+faststart",
                out_path,
            ],
        )
        try:
            os.remove(file_path)
        except OSError:
            pass
        file_path = out_path

    probe = await _probe_video_file(file_path)
    return file_path, probe


def _get_expected_size(info: Mapping[str, Any]) -> int:
    """Get an expected file size from yt-dlp metadata if available."""
    for key in ("filesize", "filesize_approx"):
        size = info.get(key)
        if isinstance(size, int) and size > 0:
            return size
    return 0


def _ensure_size_within_limit(size_bytes: int, label: str):
    """Reject downloads that exceed the configured size limit."""
    if size_bytes and size_bytes > MAX_DOWNLOAD_SIZE_BYTES:
        raise DownloadTooLargeError(
            f"{label} exceeds the maximum allowed size of {MAX_DOWNLOAD_SIZE_BYTES // (1024 * 1024 * 1024)} GB"
        )


def _ensure_file_within_limit(file_path: str, label: str):
    """Reject files that exceed the configured size limit after download."""
    file_size = Path(file_path).stat().st_size
    _ensure_size_within_limit(file_size, label)


async def _download_content(
    url: str, temp_dir: str, ydl_opts: dict[str, Any]
) -> tuple[str, dict[str, Any]]:
    """Download content using yt-dlp and return file path and info."""
    loop = asyncio.get_running_loop()
    with yt_dlp.YoutubeDL(cast("Any", ydl_opts)) as ydl:
        info = cast(
            "dict[str, Any]", await loop.run_in_executor(None, ydl.extract_info, url, False)
        )
        await loop.run_in_executor(None, ydl.download, [url])
        return temp_dir, info


async def download_youtube_video(url: str, quality: str = "best") -> tuple[str, dict]:
    """Download a YouTube video and return the path and metadata."""
    temp_dir = tempfile.mkdtemp()
    cleanup_on_error = True

    try:
        # Get info first
        loop = asyncio.get_running_loop()
        with yt_dlp.YoutubeDL(cast("Any", YDLP_BASE_OPTS)) as ydl:
            info = cast(
                "dict[str, Any]", await loop.run_in_executor(None, ydl.extract_info, url, False)
            )

        _ensure_size_within_limit(_get_expected_size(info), "YouTube video")

        video_id = info.get("id", "")
        format_option = _build_video_format(quality)

        ydl_opts = {
            **YDLP_BASE_OPTS,
            "format": format_option,
            "outtmpl": f"{temp_dir}/{video_id}.%(ext)s",
            "postprocessors": [
                {
                    "key": "FFmpegVideoConvertor",
                    "preferedformat": "mp4",
                },
                {"key": "FFmpegMetadata", "add_metadata": True},
            ],
            "merge_output_format": "mp4",
            "postprocessor_args": {
                "ffmpeg": ["-movflags", "+faststart"],
            },
        }

        with yt_dlp.YoutubeDL(cast("Any", ydl_opts)) as ydl:
            await loop.run_in_executor(None, ydl.download, [url])

        # Find the downloaded file
        file_path = _find_downloaded_file(temp_dir, expected_extension="mp4")
        file_path, probe = await _ensure_telegram_ios_video(file_path)
        _ensure_file_within_limit(file_path, "YouTube video")

        metadata = {
            "title": info.get("title", "Unknown"),
            "duration": probe.get("duration") or _safe_int(info.get("duration"), 0),
            "width": probe.get("width") or _safe_int(info.get("width"), DEFAULT_VIDEO_WIDTH),
            "height": probe.get("height") or _safe_int(info.get("height"), DEFAULT_VIDEO_HEIGHT),
        }

        cleanup_on_error = False
        return file_path, metadata
    except Exception:
        if cleanup_on_error and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
        raise


async def download_youtube_audio(url: str, quality: str = "high") -> tuple[str, dict]:
    """Download YouTube audio and return the path and metadata."""
    temp_dir = tempfile.mkdtemp()
    cleanup_on_error = True

    try:
        # Get info first
        loop = asyncio.get_running_loop()
        with yt_dlp.YoutubeDL(cast("Any", YDLP_BASE_OPTS)) as ydl:
            info = cast(
                "dict[str, Any]", await loop.run_in_executor(None, ydl.extract_info, url, False)
            )

        _ensure_size_within_limit(_get_expected_size(info), "YouTube audio")

        video_id = info.get("id", "")
        title_value = info.get("title")
        title = title_value if isinstance(title_value, str) else "Unknown"
        artist, track = _extract_metadata(info, title)

        format_option = AUDIO_QUALITY_SETTINGS.get(quality, AUDIO_QUALITY_SETTINGS["high"])

        ydl_opts = {
            **YDLP_BASE_OPTS,
            "format": format_option,
            "outtmpl": f"{temp_dir}/{video_id}.%(ext)s",
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": AUDIO_FORMAT,
                    "preferredquality": AUDIO_BITRATE,
                },
                {"key": "FFmpegMetadata", "add_metadata": True},
                {"key": "EmbedThumbnail"},
            ],
            "writethumbnail": True,
        }

        with yt_dlp.YoutubeDL(cast("Any", ydl_opts)) as ydl:
            await loop.run_in_executor(None, ydl.download, [url])

        # Find the downloaded audio file
        file_path = _find_downloaded_file(temp_dir, AUDIO_FORMAT)
        _ensure_file_within_limit(file_path, "YouTube audio")

        metadata = {
            "title": title,
            "artist": artist,
            "track": track,
            "duration": info.get("duration", 0),
        }

        cleanup_on_error = False
        return file_path, metadata
    except Exception:
        if cleanup_on_error and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
        raise


async def download_tiktok_video(url: str, max_retries: int | None = None) -> tuple[str, dict]:
    """Download a TikTok video and return the path and metadata.

    Includes retry logic for transient extraction failures.

    Args:
        url: TikTok video URL
        max_retries: Maximum number of retry attempts (uses config default if None)

    Raises:
        Exception: If download fails after all retries

    """
    retries = _safe_int(max_retries, _safe_int(TIKTOK_MAX_RETRIES, 3))
    retries = max(1, retries)

    temp_dir = tempfile.mkdtemp()
    last_error = None
    cleanup_on_error = True

    for attempt in range(retries):
        try:
            loop = asyncio.get_running_loop()
            ydl_opts = {
                **YDLP_BASE_OPTS,
                "format": "best",
                "outtmpl": f"{temp_dir}/%(id)s.%(ext)s",
            }

            with yt_dlp.YoutubeDL(cast("Any", ydl_opts)) as ydl:
                info = cast(
                    "dict[str, Any]", await loop.run_in_executor(None, ydl.extract_info, url, False)
                )
                _ensure_size_within_limit(_get_expected_size(info), "TikTok video")
                await loop.run_in_executor(None, ydl.download, [url])

            # Find the downloaded file
            file_path = _find_downloaded_file(temp_dir)
            _ensure_file_within_limit(file_path, "TikTok video")

            metadata = {
                "title": info.get("title") or info.get("description") or "",
                "duration": _safe_int(info.get("duration"), 0),
                "width": info.get("width", 0),
                "height": info.get("height", 0),
            }

            cleanup_on_error = False
            return file_path, metadata

        except DownloadTooLargeError:
            if cleanup_on_error and os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
            raise
        except DownloadError as e:
            error_msg = str(e)
            last_error = e

            # Check if it's an extraction error (likely temporary)
            if "Unable to extract" in error_msg or "webpage" in error_msg:
                if attempt < retries - 1:
                    wait_time = TIKTOK_RETRY_BACKOFF**attempt  # Exponential backoff
                    logger.warning(
                        f"TikTok extraction failed (attempt {attempt + 1}/{retries}). "
                        f"Retrying in {wait_time}s... Error: {error_msg}"
                    )
                    await asyncio.sleep(wait_time)
                    continue
                logger.error(
                    f"TikTok video extraction failed after {retries} attempts. "
                    f"This may be due to: 1) TikTok API changes, 2) Region restrictions, "
                    f"3) Video unavailability. URL: {url}"
                )
                if cleanup_on_error and os.path.exists(temp_dir):
                    shutil.rmtree(temp_dir)
                raise Exception(TIKTOK_ERROR_MESSAGE)
            # Not a temporary extraction error, fail immediately
            if cleanup_on_error and os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
            raise Exception(f"TikTok download error: {error_msg}")

        except Exception as e:
            if isinstance(e, DownloadTooLargeError):
                if cleanup_on_error and os.path.exists(temp_dir):
                    shutil.rmtree(temp_dir)
                raise
            last_error = e
            logger.error(
                f"Unexpected error downloading TikTok (attempt {attempt + 1}/{retries}): {e}"
            )
            if attempt == retries - 1:
                if cleanup_on_error and os.path.exists(temp_dir):
                    shutil.rmtree(temp_dir)
                raise

    if cleanup_on_error and os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)
    raise Exception(TIKTOK_ERROR_MESSAGE)


async def send_playlist_album(
    client,
    chat_id: int,
    items: list[tuple[str, dict]],
    *,
    mode: str,
    bot_username: str = "",
    show_bot_caption: bool = True,
    show_title: bool = True,
) -> None:
    """Send a playlist batch (up to 10 files).

    Telegram media groups cannot contain music/audio (MediaInvalidError).
    Audio is therefore sent as separate music messages with a player.
    Video is sent as one album when possible; falls back to singles.
    """
    from .captions import build_media_caption

    if not items:
        return

    def _item_caption(metadata: dict) -> str:
        title = metadata.get("title") or metadata.get("track")
        return build_media_caption(
            bot_username=bot_username,
            title=title if isinstance(title, str) else None,
            show_bot_caption=show_bot_caption,
            show_title=show_title,
        )

    # Music cannot be grouped — send as proper audio players.
    if mode == "audio":
        for path, metadata in items:
            audio_attr = DocumentAttributeAudio(
                duration=metadata.get("duration", 0),
                title=metadata.get("track", "Unknown"),
                performer=metadata.get("artist", "Unknown Artist"),
            )
            await client.send_file(
                chat_id,
                path,
                caption=_item_caption(metadata),
                attributes=[audio_attr],
                force_document=False,
            )
        return

    # Video: one album (media group); upload once, reuse handles on fallback.
    uploaded = [await client.upload_file(path) for path, _ in items]
    album_caption = f"📦 {len(items)} шт."
    if show_bot_caption and bot_username:
        album_caption = f"{album_caption}\n@{bot_username}"

    try:
        await client.send_file(
            chat_id,
            file=uploaded,
            caption=album_caption,
            supports_streaming=True,
        )
        return
    except Exception as e:
        logger.warning(f"Playlist album send failed, falling back to singles: {e}")

    for handle, (_path, metadata) in zip(uploaded, items, strict=True):
        video_attr = DocumentAttributeVideo(
            duration=metadata.get("duration", 0),
            w=metadata.get("width", DEFAULT_VIDEO_WIDTH),
            h=metadata.get("height", DEFAULT_VIDEO_HEIGHT),
            supports_streaming=True,
        )
        await client.send_file(
            chat_id,
            handle,
            caption=_item_caption(metadata),
            supports_streaming=True,
            attributes=[video_attr],
        )


async def send_video_content(
    event: Message,
    file_path: str,
    metadata: dict,
    bot_username: str = "",
    *,
    show_bot_caption: bool = True,
    show_title: bool = True,
    reply_to: int | None = None,
):
    """Send video file to Telegram with proper attributes."""
    from .captions import build_media_caption

    caption = build_media_caption(
        bot_username=bot_username,
        title=metadata.get("title"),
        show_bot_caption=show_bot_caption,
        show_title=show_title,
    )

    video_attr = DocumentAttributeVideo(
        duration=metadata.get("duration", 0),
        w=metadata.get("width", DEFAULT_VIDEO_WIDTH),
        h=metadata.get("height", DEFAULT_VIDEO_HEIGHT),
        supports_streaming=True,
    )

    await event.respond(
        caption,
        file=file_path,
        supports_streaming=True,
        attributes=[video_attr],
        reply_to=reply_to,
    )


async def send_audio_content(
    event: Message,
    file_path: str,
    metadata: dict,
    bot_username: str = "",
    *,
    show_bot_caption: bool = True,
    show_title: bool = True,
    reply_to: int | None = None,
):
    """Send audio file to Telegram with proper attributes."""
    from .captions import build_media_caption

    title = metadata.get("title") or metadata.get("track")
    caption = build_media_caption(
        bot_username=bot_username,
        title=title if isinstance(title, str) else None,
        show_bot_caption=show_bot_caption,
        show_title=show_title,
    )

    audio_attr = DocumentAttributeAudio(
        duration=metadata.get("duration", 0),
        title=metadata.get("track", "Unknown"),
        performer=metadata.get("artist", "Unknown Artist"),
    )

    await event.respond(caption, file=file_path, attributes=[audio_attr], reply_to=reply_to)


async def send_image_content(
    event: Message,
    file_path: str,
    bot_username: str = "",
    *,
    metadata: dict | None = None,
    show_bot_caption: bool = True,
    show_title: bool = True,
    reply_to: int | None = None,
):
    """Send image file to Telegram."""
    from .captions import build_media_caption

    meta = metadata or {}
    caption = build_media_caption(
        bot_username=bot_username,
        title=meta.get("title"),
        show_bot_caption=show_bot_caption,
        show_title=show_title,
    )

    await event.respond(caption, file=file_path, reply_to=reply_to)


async def _download_media_with_gallery_dl(url: str, temp_dir: str) -> tuple[str, dict]:
    """Download media content (photos or videos) using gallery-dl.

    Args:
        url: Content URL
        temp_dir: Directory to save files to

    Returns:
        Tuple of (file_path, metadata)

    Raises:
        Exception: If download fails or no media found

    """
    try:
        loop = asyncio.get_running_loop()
        # Run gallery-dl to download content (supports both photos and videos)
        # Use --no-mtime to avoid issues, and flat directory structure
        result = await loop.run_in_executor(
            None,
            lambda: subprocess.run(
                [
                    "gallery-dl",
                    "-d",
                    temp_dir,
                    "-o",
                    "directory=[]",
                    "-o",
                    "filename={tweet_id}_{num}.{extension}",
                    "--",
                    url,
                ],
                capture_output=True,
                text=True,
                timeout=120,
            ),
        )

        logger.info(f"gallery-dl stdout: {result.stdout}")
        logger.info(f"gallery-dl stderr: {result.stderr}")
        logger.info(f"gallery-dl return code: {result.returncode}")

        # Find downloaded files recursively (gallery-dl may create subdirectories)
        all_files = []
        for root, dirs, files in os.walk(temp_dir):
            for f in files:
                all_files.append(os.path.join(root, f))

        logger.info(f"Files found in temp_dir: {all_files}")

        if result.returncode != 0 and not all_files:
            logger.error(f"gallery-dl failed: {result.stderr}")
            raise Exception(f"gallery-dl error: {result.stderr}")

        # Video extensions
        video_files = [
            f for f in all_files if f.endswith((".mp4", ".webm", ".mov", ".avi", ".mkv"))
        ]
        # Image extensions
        image_files = [
            f for f in all_files if f.endswith((".jpg", ".jpeg", ".png", ".webp", ".gif"))
        ]

        # Prefer video files if available
        if video_files:
            file_path = video_files[0]
            content_type = "video"
            # Try to get video duration using ffprobe if available
            duration = 0
            try:
                probe_result = await loop.run_in_executor(
                    None,
                    lambda: subprocess.run(
                        [
                            "ffprobe",
                            "-v",
                            "error",
                            "-show_entries",
                            "format=duration",
                            "-of",
                            "default=noprint_wrappers=1:nokey=1",
                            file_path,
                        ],
                        capture_output=True,
                        text=True,
                        timeout=10,
                    ),
                )
                if probe_result.returncode == 0 and probe_result.stdout.strip():
                    duration = int(float(probe_result.stdout.strip()))
            except Exception:
                pass

            metadata = {
                "duration": duration,
                "width": 0,
                "height": 0,
                "content_type": content_type,
            }
        elif image_files:
            file_path = image_files[0]
            content_type = "photo"
            metadata = {
                "duration": 0,
                "width": 0,
                "height": 0,
                "content_type": content_type,
            }
        else:
            raise Exception("No media files downloaded by gallery-dl")

        return file_path, metadata

    except FileNotFoundError:
        raise Exception("gallery-dl not installed")
    except subprocess.TimeoutExpired:
        raise Exception("gallery-dl timeout")


async def download_twitter_video(url: str, max_retries: int | None = None) -> tuple[str, dict]:
    """Download a Twitter/X video or photo and return the path and metadata.

    Strategy: Try gallery-dl first (works best for photos), then fall back to yt-dlp for videos.

    Args:
        url: Twitter/X video or photo URL
        max_retries: Maximum number of retry attempts (uses config default if None)

    Returns:
        Tuple of (file_path, metadata) where metadata includes 'content_type' ('video' or 'photo')

    Raises:
        Exception: If download fails after all retries

    """
    retries = _safe_int(max_retries, _safe_int(TWITTER_MAX_RETRIES, 3))
    retries = max(1, retries)

    temp_dir = tempfile.mkdtemp()
    cleanup_on_error = True

    # First, try gallery-dl (works best for photos and also supports videos)
    try:
        logger.info(f"Trying gallery-dl first for Twitter content: {url}")
        file_path, metadata = await _download_media_with_gallery_dl(url, temp_dir)
        _ensure_file_within_limit(file_path, "Twitter content")
        logger.info(f"gallery-dl successfully downloaded: {file_path}")
        cleanup_on_error = False
        return file_path, metadata
    except DownloadTooLargeError:
        if cleanup_on_error and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
        raise
    except Exception as gallery_error:
        if isinstance(gallery_error, DownloadTooLargeError):
            if cleanup_on_error and os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
            raise
        logger.info(
            f"gallery-dl did not find content or failed: {gallery_error}, trying yt-dlp for video"
        )
        # Clean temp_dir for yt-dlp
        for f in os.listdir(temp_dir):
            try:
                os.remove(os.path.join(temp_dir, f))
            except Exception:
                pass

    # Fall back to yt-dlp for videos
    last_error = None

    for attempt in range(retries):
        try:
            loop = asyncio.get_running_loop()
            ydl_opts = {
                **YDLP_BASE_OPTS,
                "format": "best",
                "outtmpl": f"{temp_dir}/%(id)s.%(ext)s",
            }

            with yt_dlp.YoutubeDL(cast("Any", ydl_opts)) as ydl:
                info = cast(
                    "dict[str, Any]", await loop.run_in_executor(None, ydl.extract_info, url, False)
                )
                _ensure_size_within_limit(_get_expected_size(info), "Twitter content")
                await loop.run_in_executor(None, ydl.download, [url])

            # Try to find video/media files first, then fall back to images
            try:
                file_path = _find_downloaded_file(temp_dir, allow_images=False)
                content_type = "video"
            except Exception:
                # If no video found, try to find image files (for Twitter photos)
                file_path = _find_downloaded_file(temp_dir, allow_images=True)
                content_type = "photo"

            _ensure_file_within_limit(file_path, "Twitter content")

            metadata = {
                "title": info.get("title") or info.get("description") or "",
                "duration": _safe_int(info.get("duration"), 0),
                "width": info.get("width", 0),
                "height": info.get("height", 0),
                "content_type": content_type,
            }

            cleanup_on_error = False
            return file_path, metadata

        except DownloadTooLargeError:
            if cleanup_on_error and os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
            raise
        except DownloadError as e:
            error_msg = str(e)
            last_error = e

            if attempt < retries - 1:
                wait_time = TWITTER_RETRY_BACKOFF**attempt
                logger.warning(
                    f"Twitter extraction failed (attempt {attempt + 1}/{retries}). "
                    f"Retrying in {wait_time}s... Error: {error_msg}"
                )
                await asyncio.sleep(wait_time)
                continue
            if cleanup_on_error and os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
            raise Exception(TWITTER_ERROR_MESSAGE)

        except Exception as e:
            if isinstance(e, DownloadTooLargeError):
                if cleanup_on_error and os.path.exists(temp_dir):
                    shutil.rmtree(temp_dir)
                raise
            last_error = e
            logger.error(
                f"Unexpected error downloading Twitter (attempt {attempt + 1}/{retries}): {e}"
            )
            if attempt == retries - 1:
                if cleanup_on_error and os.path.exists(temp_dir):
                    shutil.rmtree(temp_dir)
                raise

    if cleanup_on_error and os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)
    raise Exception(TWITTER_ERROR_MESSAGE)


async def download_pinterest_content(url: str, max_retries: int | None = None) -> tuple[str, dict]:
    """Download a Pinterest video or photo and return the path and metadata.

    Strategy: Try gallery-dl first, then fall back to yt-dlp for video-oriented URLs.

    Args:
        url: Pinterest content URL
        max_retries: Maximum number of retry attempts (uses config default if None)

    Returns:
        Tuple of (file_path, metadata) where metadata includes 'content_type' ('video' or 'photo')

    Raises:
        Exception: If download fails after all retries

    """
    retries = _safe_int(max_retries, _safe_int(PINTEREST_MAX_RETRIES, 3))
    retries = max(1, retries)

    temp_dir = tempfile.mkdtemp()
    cleanup_on_error = True

    try:
        logger.info(f"Trying gallery-dl first for Pinterest content: {url}")
        file_path, metadata = await _download_media_with_gallery_dl(url, temp_dir)
        _ensure_file_within_limit(file_path, "Pinterest content")
        logger.info(f"gallery-dl successfully downloaded: {file_path}")
        cleanup_on_error = False
        return file_path, metadata
    except DownloadTooLargeError:
        if cleanup_on_error and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
        raise
    except Exception as gallery_error:
        logger.info(f"gallery-dl failed for Pinterest: {gallery_error}, trying yt-dlp")
        for filename in os.listdir(temp_dir):
            try:
                os.remove(os.path.join(temp_dir, filename))
            except Exception:
                pass

    last_error = None

    for attempt in range(retries):
        try:
            loop = asyncio.get_running_loop()
            ydl_opts = {
                **YDLP_BASE_OPTS,
                "format": "best",
                "outtmpl": f"{temp_dir}/%(id)s.%(ext)s",
            }

            with yt_dlp.YoutubeDL(cast("Any", ydl_opts)) as ydl:
                info = cast(
                    "dict[str, Any]", await loop.run_in_executor(None, ydl.extract_info, url, False)
                )
                _ensure_size_within_limit(_get_expected_size(info), "Pinterest content")
                await loop.run_in_executor(None, ydl.download, [url])

            try:
                file_path = _find_downloaded_file(temp_dir, allow_images=False)
                content_type = "video"
            except Exception:
                file_path = _find_downloaded_file(temp_dir, allow_images=True)
                content_type = "photo"

            _ensure_file_within_limit(file_path, "Pinterest content")

            metadata = {
                "title": info.get("title") or info.get("description") or "",
                "duration": _safe_int(info.get("duration"), 0),
                "width": info.get("width", 0),
                "height": info.get("height", 0),
                "content_type": content_type,
            }

            cleanup_on_error = False
            return file_path, metadata

        except DownloadTooLargeError:
            if cleanup_on_error and os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
            raise
        except DownloadError as e:
            error_msg = str(e)
            last_error = e

            if attempt < retries - 1:
                wait_time = PINTEREST_RETRY_BACKOFF**attempt
                logger.warning(
                    f"Pinterest extraction failed (attempt {attempt + 1}/{retries}). "
                    f"Retrying in {wait_time}s... Error: {error_msg}"
                )
                await asyncio.sleep(wait_time)
                continue
            if cleanup_on_error and os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
            raise Exception(PINTEREST_ERROR_MESSAGE)

        except Exception as e:
            if isinstance(e, DownloadTooLargeError):
                if cleanup_on_error and os.path.exists(temp_dir):
                    shutil.rmtree(temp_dir)
                raise
            last_error = e
            logger.error(
                f"Unexpected error downloading Pinterest (attempt {attempt + 1}/{retries}): {e}"
            )
            if attempt == retries - 1:
                if cleanup_on_error and os.path.exists(temp_dir):
                    shutil.rmtree(temp_dir)
                raise

    if cleanup_on_error and os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)
    raise Exception(PINTEREST_ERROR_MESSAGE)
