import os
import re
import asyncio
import logging
from telethon import TelegramClient, events, Button
from telethon.tl.custom import Message
from telethon.sessions import StringSession
from telethon.tl.types import DocumentAttributeAudio, DocumentAttributeVideo
import yt_dlp
from dotenv import load_dotenv
import tempfile
import shutil

# Setup logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Get API credentials from environment variables
API_ID = int(os.getenv("API_ID", 0))  # Convert to int
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
SESSION_STRING = os.getenv("SESSION_STRING", "")  # For StringSession if needed

# URL regex patterns
YOUTUBE_REGEX = r'(https?://)?(www\.)?(youtube|youtu|youtube-nocookie)\.(com|be)/(watch\?v=|embed/|v/|.+\?v=)?([^&=%\?]{11})'
TIKTOK_REGEX = r'(https?://)?(www\.|vm\.|vt\.)?(tiktok\.com)/(\S+)'

# Ensure session directory exists
os.makedirs("session", exist_ok=True)

# Initialize the client
# Use MemorySession for Docker environments to avoid SQLite issues
if SESSION_STRING:
    # If session string is provided, use it
    client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
    logger.info("Using StringSession for authentication")
else:
    # Otherwise use file-based session but with proper path
    session_file = os.path.join(os.getcwd(), "session", "komuzik_bot_session")
    client = TelegramClient(session_file, API_ID, API_HASH)
    logger.info(f"Using file-based session at {session_file}")

# Global variable to store bot username
BOT_USERNAME = ""

async def get_available_formats(url: str):
    """Get available video formats for a YouTube URL."""
    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = await asyncio.get_event_loop().run_in_executor(None, ydl.extract_info, url, False)
            formats = info.get('formats', [])
            
            # Extract unique resolutions for video formats
            available_heights = set()
            for fmt in formats:
                height = fmt.get('height')
                vcodec = fmt.get('vcodec', 'none')
                # Include formats that have video codec (not 'none' and not None)
                if height and vcodec and vcodec != 'none':
                    available_heights.add(height)
            
            # If no heights found, return common qualities as fallback
            if not available_heights:
                logger.warning(f"No specific heights found for {url}, using fallback")
                return [1080, 720, 480, 360, 240]
            
            return sorted(available_heights, reverse=True)
    except Exception as e:
        logger.error(f"Error getting available formats: {e}")
        # Return common qualities as fallback on error
        return [1080, 720, 480, 360, 240]

async def search_youtube(query: str, max_results: int = 5):
    """Search for YouTube videos and return top results."""
    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
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

async def download_youtube_content(url: str, quality: str = 'best', content_type: str = 'video'):
    """Download a YouTube video or audio and return the path to the downloaded file."""
    temp_dir = tempfile.mkdtemp()
    try:
        format_option = ''
        ext = 'mp4'
        
        # Get video info to extract proper metadata
        ydl_info_opts = {'quiet': True, 'no_warnings': True}
        with yt_dlp.YoutubeDL(ydl_info_opts) as ydl:
            info = await asyncio.get_event_loop().run_in_executor(None, ydl.extract_info, url, False)
        
        # Extract artist and track name for music.youtube.com
        title = info.get('title', 'Unknown')
        artist = info.get('artist') or info.get('creator') or info.get('uploader', 'Unknown Artist')
        track = info.get('track') or title
        
        # Try to parse "Artist - Track" format from title if no artist metadata
        if artist == 'Unknown Artist' and ' - ' in title:
            parts = title.split(' - ', 1)
            artist = parts[0].strip()
            track = parts[1].strip()
        
        if content_type == 'audio':
            # Always use mp3 for audio to ensure compatibility with thumbnail embedding
            if quality == 'high':
                format_option = 'bestaudio/best'
            elif quality == 'medium':
                format_option = 'bestaudio[abr<=128]/bestaudio/best'
            elif quality == 'low':
                format_option = 'bestaudio[abr<=96]/bestaudio/best'
            else:
                format_option = 'bestaudio/best'
            
            ext = 'mp3'
            
            ydl_opts_with_quality = {
                'format': format_option,
                'outtmpl': f'{temp_dir}/%(id)s.%(ext)s',
                'noplaylist': True,
                'quiet': True,
                'no_warnings': True,
                # Convert to mp3 for compatibility
                'postprocessors': [
                    {'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'},
                    {
                        'key': 'FFmpegMetadata',
                        'add_metadata': True,
                    },
                    {'key': 'EmbedThumbnail'}  # This will now work with mp3
                ],
                'writethumbnail': True,
            }
        else:  # video
            # More flexible format selection with multiple fallback options
            # Extract height from quality string (e.g., "1080p" -> 1080)
            try:
                if quality.endswith('p'):
                    height = int(quality[:-1])
                    format_option = f'bestvideo[height<={height}]+bestaudio/best[height<={height}]/bestvideo+bestaudio/best'
                else:
                    # Fallback to best quality
                    format_option = 'bestvideo+bestaudio/best'
            except (ValueError, AttributeError):
                # If quality parsing fails, use best available
                format_option = 'bestvideo+bestaudio/best'
            
            ydl_opts_with_quality = {
                'format': format_option,
                'outtmpl': f'{temp_dir}/%(id)s.%(ext)s',
                'noplaylist': True,
                'quiet': True,
                'no_warnings': True,
                'postprocessors': [
                    {'key': 'FFmpegMetadata', 'add_metadata': True},
                ],
            }
        
        with yt_dlp.YoutubeDL(ydl_opts_with_quality) as ydl:
            info = await asyncio.get_event_loop().run_in_executor(None, ydl.extract_info, url, False)
            video_id = info.get('id', '')
            
            # For audio, we explicitly set mp3 extension because of the FFmpeg conversion
            if content_type == 'audio':
                file_path = f"{temp_dir}/{video_id}.mp3"
            else:
                download_ext = info.get('ext', ext)
                file_path = f"{temp_dir}/{video_id}.{download_ext}"
            
            # Actually download the content
            await asyncio.get_event_loop().run_in_executor(None, ydl.download, [url])
            
            # Get duration in seconds and other metadata
            duration = info.get('duration', 0)
            width = info.get('width', 0)
            height = info.get('height', 0)
            
            return file_path, title, duration, width, height, artist, track
    except Exception as e:
        logger.error(f"Error downloading content: {e}")
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
        raise

async def send_youtube_video(event: Message, url: str, quality: str = 'best'):
    """Download and send a YouTube video."""
    async with event.client.action(event.chat_id, 'video'):
        try:
            # Send "Processing" message
            processing_msg = await event.respond("Загрузка видео... Пожалуйста, подождите.")
            
            logger.info(f"Downloading video: {url} with quality: {quality}")
            # Download the video
            video_path, video_title, duration, width, height, artist, track = await download_youtube_content(url, quality, 'video')
            logger.info(f"Video downloaded successfully: {video_path}")
            
            # Send the video with bot reference (only bot link)
            caption = ""
            if BOT_USERNAME:
                caption = f"@{BOT_USERNAME}"
            
            # Create proper Telethon DocumentAttributeVideo object
            video_attr = DocumentAttributeVideo(
                duration=duration,
                w=width if width > 0 else 1280,  # Default width if not available
                h=height if height > 0 else 720,  # Default height if not available
                supports_streaming=True
            )
            
            await event.respond(
                caption,
                file=video_path,
                supports_streaming=True,
                attributes=[video_attr]
            )
            
            # Delete the processing message
            await processing_msg.delete()
            
            # Clean up - remove the downloaded file
            if os.path.exists(os.path.dirname(video_path)):
                shutil.rmtree(os.path.dirname(video_path))
        
        except Exception as e:
            logger.error(f"Error sending video: {e}")
            await event.respond(f"Произошла ошибка при обработке видео: {str(e)}")

async def send_youtube_audio(event: Message, url: str, quality: str = 'high'):
    """Download and send YouTube audio."""
    async with event.client.action(event.chat_id, 'audio'):
        try:
            # Send "Processing" message
            processing_msg = await event.respond("Загрузка аудио... Пожалуйста, подождите.")
            
            logger.info(f"Downloading audio: {url} with quality: {quality}")
            # Download the audio
            audio_path, audio_title, duration, _, _, artist, track = await download_youtube_content(url, quality, 'audio')
            logger.info(f"Audio downloaded successfully: {audio_path}")
            
            # Send the audio with bot reference (only bot link)
            caption = ""
            if BOT_USERNAME:
                caption = f"@{BOT_USERNAME}"
            
            # Create proper Telethon DocumentAttributeAudio object with correct metadata
            audio_attr = DocumentAttributeAudio(
                duration=duration,
                title=track,
                performer=artist
            )
            
            await event.respond(
                caption,
                file=audio_path,
                attributes=[audio_attr]
            )
            
            # Delete the processing message
            await processing_msg.delete()
            
            # Clean up - remove the downloaded file
            if os.path.exists(os.path.dirname(audio_path)):
                shutil.rmtree(os.path.dirname(audio_path))
        
        except Exception as e:
            logger.error(f"Error sending audio: {e}")
            await event.respond(f"Произошла ошибка при обработке аудио: {str(e)}")

async def send_tiktok_video(event: Message, url: str):
    """Download and send a TikTok video directly without quality selection."""
    async with event.client.action(event.chat_id, 'video'):
        try:
            # Send "Processing" message
            processing_msg = await event.respond("Загрузка TikTok видео... Пожалуйста, подождите.")
            
            logger.info(f"Downloading TikTok video: {url}")
            
            # Download TikTok video
            temp_dir = tempfile.mkdtemp()
            try:
                ydl_opts = {
                    'format': 'best',
                    'outtmpl': f'{temp_dir}/%(id)s.%(ext)s',
                    'quiet': True,
                    'no_warnings': True,
                }
                
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = await asyncio.get_event_loop().run_in_executor(None, ydl.extract_info, url, False)
                    video_id = info.get('id', 'video')
                    ext = info.get('ext', 'mp4')
                    duration = int(info.get('duration', 0))
                    width = info.get('width', 0)
                    height = info.get('height', 0)
                    
                    # Download
                    await asyncio.get_event_loop().run_in_executor(None, ydl.download, [url])
                    
                    video_path = f"{temp_dir}/{video_id}.{ext}"
                
                logger.info(f"TikTok video downloaded successfully: {video_path}")
                
                # Send the video
                caption = ""
                if BOT_USERNAME:
                    caption = f"@{BOT_USERNAME}"
                
                video_attr = DocumentAttributeVideo(
                    duration=duration,
                    w=width if width > 0 else 720,
                    h=height if height > 0 else 1280,
                    supports_streaming=True
                )
                
                await event.respond(
                    caption,
                    file=video_path,
                    supports_streaming=True,
                    attributes=[video_attr]
                )
                
                # Delete the processing message
                await processing_msg.delete()
                
                # Clean up
                if os.path.exists(temp_dir):
                    shutil.rmtree(temp_dir)
                    
            except Exception:
                if os.path.exists(temp_dir):
                    shutil.rmtree(temp_dir)
                raise
        
        except Exception as e:
            logger.error(f"Error sending TikTok video: {e}")
            await event.respond(f"Произошла ошибка при обработке TikTok видео: {str(e)}")

@client.on(events.NewMessage(pattern='/start'))
async def start_handler(event: Message):
    """Handle /start command."""
    await event.respond(
        "👋 Привет! Я бот для скачивания видео и музыки с YouTube и TikTok.\n\n"
        "📺 **YouTube**: выбирайте качество видео и аудио\n"
        "🎵 **TikTok**: автоматическая загрузка видео\n\n"
        "Просто отправьте мне ссылку на видео!\n\n"
        "Для получения помощи используйте команду /help."
    )

@client.on(events.NewMessage(pattern='/help'))
async def help_handler(event: Message):
    """Handle /help command."""
    await event.respond(
        "🔍 **Как пользоваться ботом:**\n\n"
        "1. Отправьте мне ссылку на видео YouTube или TikTok\n"
        "2. Используйте /search для поиска видео на YouTube\n"
        "3. Для YouTube: выберите тип контента (видео или аудио) и качество\n"
        "4. Для TikTok: видео скачается автоматически\n"
        "5. Дождитесь загрузки и получите файл\n\n"
        "📌 **Доступные команды:**\n"
        "/start - Запустить бота\n"
        "/help - Показать справку\n"
        "/search <запрос> - Поиск видео на YouTube\n\n"
        "🎬 **Поддерживаемые платформы:**\n"
        "• YouTube (с выбором качества)\n"
        "• TikTok (автоматическая загрузка)"
    )

@client.on(events.NewMessage(pattern=r'^/search(?:\s+(.+))?'))
async def search_handler(event: Message):
    """Handle /search command."""
    # Extract search query
    match = re.match(r'^/search(?:\s+(.+))?', event.message.text)
    query = match.group(1) if match else None
    
    if not query:
        await event.respond("Пожалуйста, укажите поисковый запрос.\nПример: /search название песни")
        return
    
    # Send searching message
    searching_msg = await event.respond(f"🔍 Поиск: {query}...")
    
    # Search for videos
    results = await search_youtube(query, max_results=5)
    
    if not results:
        await searching_msg.edit("Ничего не найдено. Попробуйте изменить запрос.")
        return
    
    # Create buttons for each result
    buttons = []
    for i, result in enumerate(results, 1):
        duration = int(result['duration']) if result['duration'] else 0
        duration_min = duration // 60
        duration_sec = duration % 60
        button_text = f"{i}. {result['title'][:50]}{'...' if len(result['title']) > 50 else ''} ({duration_min}:{duration_sec:02d})"
        buttons.append([Button.inline(button_text, data=f"select_{result['url']}")])
    
    await searching_msg.edit("Выберите видео из результатов поиска:", buttons=buttons)

@client.on(events.NewMessage())
async def message_handler(event: Message):
    """Handle incoming messages with YouTube and TikTok links."""
    if event.message.text.startswith('/'):  # Skip other commands
        return
    
    # Check if the message contains a TikTok link
    tiktok_match = re.search(TIKTOK_REGEX, event.message.text)
    if tiktok_match:
        tiktok_url = tiktok_match.group(0)
        # For TikTok, download directly without options
        await send_tiktok_video(event, tiktok_url)
        return
    
    # Check if the message contains a YouTube link
    youtube_match = re.search(YOUTUBE_REGEX, event.message.text)
    if not youtube_match:
        await event.respond("Пожалуйста, отправьте корректную ссылку на видео YouTube или TikTok.")
        return
    
    youtube_url = youtube_match.group(0)
    
    # Create content type selection buttons
    buttons = [
        [
            Button.inline("🎬 Видео", data=f"content_video_{youtube_url}"),
            Button.inline("🎵 Аудио", data=f"content_audio_{youtube_url}")
        ]
    ]
    
    await event.respond("Выберите тип контента для загрузки:", buttons=buttons)

@client.on(events.CallbackQuery())
async def callback_handler(event):
    """Handle callback queries from inline buttons."""
    data = event.data.decode('utf-8')
    
    if data.startswith('select_'):
        # Handle video selection from search results
        url = data[7:]  # Remove 'select_' prefix
        
        # Create content type selection buttons
        buttons = [
            [
                Button.inline("🎬 Видео", data=f"content_video_{url}"),
                Button.inline("🎵 Аудио", data=f"content_audio_{url}")
            ]
        ]
        
        await event.edit("Выберите тип контента для загрузки:", buttons=buttons)
    
    elif data.startswith('content_'):
        parts = data.split('_', 2)
        if len(parts) == 3:
            content_type = parts[1]
            url = parts[2]
            
            if content_type == 'video':
                # Get available formats for this specific video
                await event.answer("Проверка доступных форматов...")
                logger.info(f"Getting available formats for: {url}")
                available_heights = await get_available_formats(url)
                logger.info(f"Available heights: {available_heights}")
                
                # Create buttons from actual available heights
                buttons = []
                row = []
                
                # Map each available height to a button
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
            
            elif content_type == 'audio':
                # Create audio quality selection buttons
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
    
    elif data.startswith('quality_'):
        parts = data.split('_', 2)
        if len(parts) == 3:
            quality = parts[1]
            url = parts[2]
            
            # Answer the callback query
            await event.answer(f"Загрузка видео в качестве {quality}...")
            
            # Send the video
            await send_youtube_video(event, url, quality)
    
    elif data.startswith('audio_'):
        parts = data.split('_', 2)
        if len(parts) == 3:
            quality = parts[1]
            url = parts[2]
            
            # Answer the callback query
            await event.answer(f"Загрузка аудио в качестве {quality}...")
            
            # Send the audio
            await send_youtube_audio(event, url, quality)

async def main():
    global BOT_USERNAME
    
    # Get and check required environment variables
    if not all([API_ID, API_HASH, BOT_TOKEN]):
        logger.error("Please set API_ID, API_HASH and BOT_TOKEN environment variables.")
        return
    
    # Start the bot
    await client.start(bot_token=BOT_TOKEN)
    
    # Get bot information to reference in messages
    me = await client.get_me()
    BOT_USERNAME = me.username
    
    logger.info(f"Bot started as @{BOT_USERNAME}!")
    
    # Handle graceful shutdown
    try:
        await client.run_until_disconnected()
    finally:
        await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())