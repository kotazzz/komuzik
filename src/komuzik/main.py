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

# YouTube URL regex pattern
YOUTUBE_REGEX = r'(https?://)?(www\.)?(youtube|youtu|youtube-nocookie)\.(com|be)/(watch\?v=|embed/|v/|.+\?v=)?([^&=%\?]{11})'

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

async def download_youtube_content(url: str, quality: str = 'best', content_type: str = 'video'):
    """Download a YouTube video or audio and return the path to the downloaded file."""
    temp_dir = tempfile.mkdtemp()
    try:
        format_option = ''
        ext = 'mp4'
        
        if content_type == 'audio':
            # Always use mp3 for audio to ensure compatibility with thumbnail embedding
            if quality == 'high':
                format_option = 'bestaudio/best'
                ext = 'mp3'
            elif quality == 'medium':
                format_option = 'bestaudio[abr<=128]/best[abr<=128]'
                ext = 'mp3'
            elif quality == 'low':
                format_option = 'bestaudio[abr<=96]/best[abr<=96]'
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
                    {'key': 'FFmpegMetadata', 'add_metadata': True},
                    {'key': 'EmbedThumbnail'}  # This will now work with mp3
                ],
                'writethumbnail': True,
            }
        else:  # video
            if quality == '1080p':
                format_option = 'bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080][ext=mp4]/best'
            elif quality == '720p':
                format_option = 'bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best'
            elif quality == '480p':
                format_option = 'bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[height<=480][ext=mp4]/best'
            elif quality == '360p':
                format_option = 'bestvideo[height<=360][ext=mp4]+bestaudio[ext=m4a]/best[height<=360][ext=mp4]/best'
            elif quality == '240p':
                format_option = 'bestvideo[height<=240][ext=mp4]+bestaudio[ext=m4a]/best[height<=240][ext=mp4]/best'
            else:
                format_option = 'best[ext=mp4]/best'
            
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
            
            return file_path, info.get('title', 'Video'), duration, width, height
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
            
            # Download the video
            video_path, video_title, duration, width, height = await download_youtube_content(url, quality, 'video')
            
            # Send the video with bot reference
            caption = f"**{video_title}**\n\nЗапрошено: {event.sender.first_name}"
            if BOT_USERNAME:
                caption += f"\n\n📥 @{BOT_USERNAME}"
            
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
            
            # Download the audio
            audio_path, audio_title, duration, _, _ = await download_youtube_content(url, quality, 'audio')
            
            # Send the audio with bot reference
            caption = f"**{audio_title}**\n\nЗапрошено: {event.sender.first_name}"
            if BOT_USERNAME:
                caption += f"\n\n📥 @{BOT_USERNAME}"
            
            # Create proper Telethon DocumentAttributeAudio object
            audio_attr = DocumentAttributeAudio(
                duration=duration,
                title=audio_title,
                performer="YouTube Music"
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

@client.on(events.NewMessage(pattern='/start'))
async def start_handler(event: Message):
    """Handle /start command."""
    await event.respond(
        "👋 Привет! Я бот для скачивания видео и музыки с YouTube.\n\n"
        "Просто отправьте мне ссылку на видео, и я предложу варианты загрузки.\n\n"
        "Для получения помощи используйте команду /help."
    )

@client.on(events.NewMessage(pattern='/help'))
async def help_handler(event: Message):
    """Handle /help command."""
    await event.respond(
        "🔍 **Как пользоваться ботом:**\n\n"
        "1. Отправьте мне ссылку на видео YouTube\n"
        "2. Выберите тип контента (видео или аудио) и качество с помощью кнопок\n"
        "3. Дождитесь загрузки и получите файл\n\n"
        "📌 **Доступные команды:**\n"
        "/start - Запустить бота\n"
        "/help - Показать справку"
    )

@client.on(events.NewMessage())
async def message_handler(event: Message):
    """Handle incoming messages with YouTube links."""
    if event.message.text.startswith('/'):  # Skip other commands
        return
    
    # Check if the message contains a YouTube link
    youtube_match = re.search(YOUTUBE_REGEX, event.message.text)
    if not youtube_match:
        await event.respond("Пожалуйста, отправьте корректную ссылку на видео YouTube.")
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
    
    if data.startswith('content_'):
        parts = data.split('_', 2)
        if len(parts) == 3:
            content_type = parts[1]
            url = parts[2]
            
            if content_type == 'video':
                # Create video quality selection buttons
                buttons = [
                    [
                        Button.inline("1080p HD", data=f"quality_1080p_{url}"),
                        Button.inline("720p HD", data=f"quality_720p_{url}")
                    ],
                    [
                        Button.inline("480p", data=f"quality_480p_{url}"),
                        Button.inline("360p", data=f"quality_360p_{url}")
                    ],
                    [
                        Button.inline("240p", data=f"quality_240p_{url}")
                    ]
                ]
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