"""Download functionality for YouTube and TikTok content."""
import asyncio
import logging
import tempfile
import shutil
import os
from contextlib import asynccontextmanager
from typing import Tuple, List
import time
import yt_dlp
from telethon.tl.custom import Message
from telethon.tl.types import DocumentAttributeAudio, DocumentAttributeVideo

from .config import (
    YDLP_BASE_OPTS,
    AUDIO_QUALITY_SETTINGS,
    AUDIO_FORMAT,
    AUDIO_BITRATE,
    VIDEO_FALLBACK_QUALITIES,
    DEFAULT_VIDEO_WIDTH,
    DEFAULT_VIDEO_HEIGHT,
    DEFAULT_SEARCH_RESULTS,
    TIKTOK_MAX_RETRIES,
    TIKTOK_RETRY_BACKOFF,
    TIKTOK_ERROR_MESSAGE,
    TWITTER_MAX_RETRIES,
    TWITTER_RETRY_BACKOFF,
    TWITTER_ERROR_MESSAGE,
)

logger = logging.getLogger(__name__)


def _find_downloaded_file(temp_dir: str, expected_extension: str = None, allow_images: bool = False) -> str:
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
        media_files = [f for f in files]
    else:
        media_files = [f for f in files if not f.endswith(('.jpg', '.png', '.webp'))]
    
    # If expected extension specified, try to find file with that extension first
    if expected_extension:
        exact_match = [f for f in media_files if f.endswith(f'.{expected_extension}')]
        if exact_match:
            media_files = exact_match
    
    if not media_files:
        raise Exception("No media file found in download directory")
    
    file_path = os.path.join(temp_dir, media_files[0])
    
    # Verify file is not empty
    if os.path.getsize(file_path) == 0:
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


async def get_available_formats(url: str) -> List[int]:
    """Get available video formats for a YouTube URL."""
    try:
        with yt_dlp.YoutubeDL(YDLP_BASE_OPTS) as ydl:
            info = await asyncio.get_event_loop().run_in_executor(None, ydl.extract_info, url, False)
            formats = info.get('formats', [])
            
            available_heights = set()
            for fmt in formats:
                height = fmt.get('height')
                vcodec = fmt.get('vcodec', 'none')
                if height and vcodec and vcodec != 'none':
                    available_heights.add(height)
            
            if not available_heights:
                logger.warning(f"No specific heights found for {url}, using fallback")
                return VIDEO_FALLBACK_QUALITIES
            
            return sorted(available_heights, reverse=True)
    except Exception as e:
        logger.error(f"Error getting available formats: {e}")
        return VIDEO_FALLBACK_QUALITIES


async def search_youtube(query: str, max_results: int = DEFAULT_SEARCH_RESULTS) -> List[dict]:
    """Search for YouTube videos and return top results."""
    try:
        ydl_opts = {
            **YDLP_BASE_OPTS,
            'extract_flat': True,
            'default_search': 'ytsearch',
        }
        
        search_query = f"ytsearch{max_results}:{query}"
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            search_results = await asyncio.get_event_loop().run_in_executor(
                None, ydl.extract_info, search_query, False
            )
            
            results = []
            for entry in search_results.get('entries', []):
                results.append({
                    'id': entry.get('id', ''),
                    'title': entry.get('title', 'Unknown'),
                    'url': f"https://www.youtube.com/watch?v={entry.get('id', '')}",
                    'duration': entry.get('duration', 0),
                    'channel': entry.get('channel', 'Unknown')
                })
            
            return results
    except Exception as e:
        logger.error(f"Error searching YouTube: {e}")
        return []


def _extract_metadata(info: dict, title: str) -> Tuple[str, str]:
    """Extract artist and track name from video info."""
    artist = info.get('artist') or info.get('creator') or info.get('uploader', 'Unknown Artist')
    track = info.get('track') or title
    
    # Try to parse "Artist - Track" format from title if no artist metadata
    if artist == 'Unknown Artist' and ' - ' in title:
        parts = title.split(' - ', 1)
        artist = parts[0].strip()
        track = parts[1].strip()
    
    return artist, track


def _build_video_format(quality: str) -> str:
    """Build format string for video download."""
    try:
        if quality.endswith('p'):
            height = int(quality[:-1])
            return f'bestvideo[height<={height}]+bestaudio/best[height<={height}]/bestvideo+bestaudio/best'
        else:
            return 'bestvideo+bestaudio/best'
    except (ValueError, AttributeError):
        return 'bestvideo+bestaudio/best'


async def _download_content(url: str, temp_dir: str, ydl_opts: dict) -> Tuple[str, dict]:
    """Download content using yt-dlp and return file path and info."""
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = await asyncio.get_event_loop().run_in_executor(None, ydl.extract_info, url, False)
        await asyncio.get_event_loop().run_in_executor(None, ydl.download, [url])
        return temp_dir, info


async def download_youtube_video(url: str, quality: str = 'best') -> Tuple[str, dict]:
    """Download a YouTube video and return the path and metadata."""
    temp_dir = tempfile.mkdtemp()
    
    try:
        # Get info first
        with yt_dlp.YoutubeDL(YDLP_BASE_OPTS) as ydl:
            info = await asyncio.get_event_loop().run_in_executor(None, ydl.extract_info, url, False)
        
        video_id = info.get('id', '')
        format_option = _build_video_format(quality)
        
        ydl_opts = {
            **YDLP_BASE_OPTS,
            'format': format_option,
            'outtmpl': f'{temp_dir}/{video_id}.%(ext)s',
            'postprocessors': [{'key': 'FFmpegMetadata', 'add_metadata': True}],
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            await asyncio.get_event_loop().run_in_executor(None, ydl.download, [url])
        
        # Find the downloaded file
        file_path = _find_downloaded_file(temp_dir)
        
        metadata = {
            'title': info.get('title', 'Unknown'),
            'duration': info.get('duration', 0),
            'width': info.get('width', 0),
            'height': info.get('height', 0),
        }
        
        return file_path, metadata
    except Exception:
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
        raise


async def download_youtube_audio(url: str, quality: str = 'high') -> Tuple[str, dict]:
    """Download YouTube audio and return the path and metadata."""
    temp_dir = tempfile.mkdtemp()
    
    try:
        # Get info first
        with yt_dlp.YoutubeDL(YDLP_BASE_OPTS) as ydl:
            info = await asyncio.get_event_loop().run_in_executor(None, ydl.extract_info, url, False)
        
        video_id = info.get('id', '')
        title = info.get('title', 'Unknown')
        artist, track = _extract_metadata(info, title)
        
        format_option = AUDIO_QUALITY_SETTINGS.get(quality, AUDIO_QUALITY_SETTINGS['high'])
        
        ydl_opts = {
            **YDLP_BASE_OPTS,
            'format': format_option,
            'outtmpl': f'{temp_dir}/{video_id}.%(ext)s',
            'postprocessors': [
                {'key': 'FFmpegExtractAudio', 'preferredcodec': AUDIO_FORMAT, 'preferredquality': AUDIO_BITRATE},
                {'key': 'FFmpegMetadata', 'add_metadata': True},
                {'key': 'EmbedThumbnail'}
            ],
            'writethumbnail': True,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            await asyncio.get_event_loop().run_in_executor(None, ydl.download, [url])
        
        # Find the downloaded audio file
        file_path = _find_downloaded_file(temp_dir, AUDIO_FORMAT)
        
        metadata = {
            'title': title,
            'artist': artist,
            'track': track,
            'duration': info.get('duration', 0),
        }
        
        return file_path, metadata
    except Exception:
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
        raise


async def download_tiktok_video(url: str, max_retries: int = None) -> Tuple[str, dict]:
    """Download a TikTok video and return the path and metadata.
    
    Includes retry logic for transient extraction failures.
    
    Args:
        url: TikTok video URL
        max_retries: Maximum number of retry attempts (uses config default if None)
        
    Raises:
        Exception: If download fails after all retries
    """
    if max_retries is None:
        max_retries = TIKTOK_MAX_RETRIES
    
    temp_dir = tempfile.mkdtemp()
    last_error = None
    
    for attempt in range(max_retries):
        try:
            ydl_opts = {
                **YDLP_BASE_OPTS,
                'format': 'best',
                'outtmpl': f'{temp_dir}/%(id)s.%(ext)s',
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = await asyncio.get_event_loop().run_in_executor(None, ydl.extract_info, url, False)
                await asyncio.get_event_loop().run_in_executor(None, ydl.download, [url])
            
            # Find the downloaded file
            file_path = _find_downloaded_file(temp_dir)
            
            metadata = {
                'duration': int(info.get('duration', 0)),
                'width': info.get('width', 0),
                'height': info.get('height', 0),
            }
            
            return file_path, metadata
            
        except yt_dlp.utils.DownloadError as e:
            error_msg = str(e)
            last_error = e
            
            # Check if it's an extraction error (likely temporary)
            if 'Unable to extract' in error_msg or 'webpage' in error_msg:
                if attempt < max_retries - 1:
                    wait_time = TIKTOK_RETRY_BACKOFF ** attempt  # Exponential backoff
                    logger.warning(
                        f"TikTok extraction failed (attempt {attempt + 1}/{max_retries}). "
                        f"Retrying in {wait_time}s... Error: {error_msg}"
                    )
                    await asyncio.sleep(wait_time)
                    continue
                else:
                    logger.error(
                        f"TikTok video extraction failed after {max_retries} attempts. "
                        f"This may be due to: 1) TikTok API changes, 2) Region restrictions, "
                        f"3) Video unavailability. URL: {url}"
                    )
                    if os.path.exists(temp_dir):
                        shutil.rmtree(temp_dir)
                    raise Exception(TIKTOK_ERROR_MESSAGE)
            else:
                # Not a temporary extraction error, fail immediately
                if os.path.exists(temp_dir):
                    shutil.rmtree(temp_dir)
                raise Exception(f"TikTok download error: {error_msg}")
                
        except Exception as e:
            last_error = e
            logger.error(f"Unexpected error downloading TikTok (attempt {attempt + 1}/{max_retries}): {e}")
            if attempt == max_retries - 1:
                if os.path.exists(temp_dir):
                    shutil.rmtree(temp_dir)
                raise


async def send_video_content(event: Message, file_path: str, metadata: dict, bot_username: str = ""):
    """Send video file to Telegram with proper attributes."""
    caption = f"@{bot_username}" if bot_username else ""
    
    video_attr = DocumentAttributeVideo(
        duration=metadata.get('duration', 0),
        w=metadata.get('width', DEFAULT_VIDEO_WIDTH),
        h=metadata.get('height', DEFAULT_VIDEO_HEIGHT),
        supports_streaming=True
    )
    
    await event.respond(
        caption,
        file=file_path,
        supports_streaming=True,
        attributes=[video_attr]
    )


async def send_audio_content(event: Message, file_path: str, metadata: dict, bot_username: str = ""):
    """Send audio file to Telegram with proper attributes."""
    caption = f"@{bot_username}" if bot_username else ""
    
    audio_attr = DocumentAttributeAudio(
        duration=metadata.get('duration', 0),
        title=metadata.get('track', 'Unknown'),
        performer=metadata.get('artist', 'Unknown Artist')
    )
    
    await event.respond(
        caption,
        file=file_path,
        attributes=[audio_attr]
    )


async def send_image_content(event: Message, file_path: str, bot_username: str = ""):
    """Send image file to Telegram."""
    caption = f"@{bot_username}" if bot_username else ""
    
    await event.respond(
        caption,
        file=file_path
    )

async def _download_twitter_photos_with_gallery_dl(url: str, temp_dir: str) -> Tuple[str, dict]:
    """Download Twitter photos using gallery-dl.
    
    Args:
        url: Twitter/X photo URL
        temp_dir: Directory to save files to
        
    Returns:
        Tuple of (file_path, metadata)
        
    Raises:
        Exception: If download fails
    """
    import subprocess
    
    try:
        # Run gallery-dl to download photos
        result = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: subprocess.run(
                ['gallery-dl', '--dest', temp_dir, '--filename', '{tweet_id}_{num}.{extension}', url],
                capture_output=True,
                text=True,
                timeout=60
            )
        )
        
        if result.returncode != 0:
            logger.error(f"gallery-dl failed: {result.stderr}")
            raise Exception(f"gallery-dl error: {result.stderr}")
        
        # Find downloaded files
        files = os.listdir(temp_dir)
        image_files = [f for f in files if f.endswith(('.jpg', '.jpeg', '.png', '.webp', '.gif'))]
        
        if not image_files:
            raise Exception("No images downloaded by gallery-dl")
        
        file_path = os.path.join(temp_dir, image_files[0])
        
        metadata = {
            'duration': 0,
            'width': 0,
            'height': 0,
            'content_type': 'photo',
        }
        
        return file_path, metadata
        
    except FileNotFoundError:
        raise Exception("gallery-dl not installed")
    except subprocess.TimeoutExpired:
        raise Exception("gallery-dl timeout")


async def download_twitter_video(url: str, max_retries: int = None) -> Tuple[str, dict]:
    """Download a Twitter/X video or photo and return the path and metadata.
    
    Includes retry logic for transient extraction failures.
    Supports both videos and photos. For photos, falls back to gallery-dl.
    
    Args:
        url: Twitter/X video or photo URL
        max_retries: Maximum number of retry attempts (uses config default if None)
        
    Returns:
        Tuple of (file_path, metadata) where metadata includes 'content_type' ('video' or 'photo')
        
    Raises:
        Exception: If download fails after all retries
    """
    if max_retries is None:
        max_retries = TWITTER_MAX_RETRIES
    
    temp_dir = tempfile.mkdtemp()
    last_error = None
    
    for attempt in range(max_retries):
        try:
            ydl_opts = {
                **YDLP_BASE_OPTS,
                'format': 'best',
                'outtmpl': f'{temp_dir}/%(id)s.%(ext)s',
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = await asyncio.get_event_loop().run_in_executor(None, ydl.extract_info, url, False)
                await asyncio.get_event_loop().run_in_executor(None, ydl.download, [url])
            
            # Try to find video/media files first, then fall back to images
            try:
                file_path = _find_downloaded_file(temp_dir, allow_images=False)
                content_type = 'video'
            except Exception:
                # If no video found, try to find image files (for Twitter photos)
                file_path = _find_downloaded_file(temp_dir, allow_images=True)
                content_type = 'photo'
            
            metadata = {
                'duration': int(info.get('duration', 0)),
                'width': info.get('width', 0),
                'height': info.get('height', 0),
                'content_type': content_type,
            }
            
            return file_path, metadata
            
        except yt_dlp.utils.DownloadError as e:
            error_msg = str(e)
            last_error = e
            
            # Check if this might be a photo-only tweet (no video available)
            if 'Unsupported URL' in error_msg or 'no video' in error_msg.lower() or 'Unable to extract' in error_msg:
                # Try gallery-dl for photos
                logger.info(f"yt-dlp failed, trying gallery-dl for potential photo: {url}")
                try:
                    # Clean temp_dir for gallery-dl
                    for f in os.listdir(temp_dir):
                        os.remove(os.path.join(temp_dir, f))
                    
                    return await _download_twitter_photos_with_gallery_dl(url, temp_dir)
                except Exception as gallery_error:
                    logger.warning(f"gallery-dl also failed: {gallery_error}")
                    # Continue with retry logic
            
            if attempt < max_retries - 1:
                wait_time = TWITTER_RETRY_BACKOFF ** attempt
                logger.warning(
                    f"Twitter extraction failed (attempt {attempt + 1}/{max_retries}). "
                    f"Retrying in {wait_time}s... Error: {error_msg}"
                )
                await asyncio.sleep(wait_time)
                continue
            else:
                if os.path.exists(temp_dir):
                    shutil.rmtree(temp_dir)
                raise Exception(TWITTER_ERROR_MESSAGE)
        
        except Exception as e:
            last_error = e
            logger.error(f"Unexpected error downloading Twitter (attempt {attempt + 1}/{max_retries}): {e}")
            if attempt == max_retries - 1:
                if os.path.exists(temp_dir):
                    shutil.rmtree(temp_dir)
                raise