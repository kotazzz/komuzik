"""Main entry point for the Komuzik Telegram bot."""
import os
import asyncio
import logging
from telethon import TelegramClient
from telethon.sessions import StringSession

from .config import API_ID, API_HASH, BOT_TOKEN, SESSION_STRING
from .handlers import BotHandlers
from .database import Database
from .repository import StatsRepository

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Ensure session directory exists
os.makedirs("session", exist_ok=True)

# Initialize the Telegram client
if SESSION_STRING:
    client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
    logger.info("Using StringSession for authentication")
else:
    session_file = os.path.join(os.getcwd(), "session", "komuzik_bot_session")
    client = TelegramClient(session_file, API_ID, API_HASH)
    logger.info(f"Using file-based session at {session_file}")


async def main():
    """Start and run the bot."""
    # Check required environment variables
    if not all([API_ID, API_HASH, BOT_TOKEN]):
        logger.error("Please set API_ID, API_HASH and BOT_TOKEN environment variables.")
        return
    
    # Initialize database
    db_path = os.path.join(os.getcwd(), "data", "komuzik_stats.db")
    db = Database(db_path)
    db.connect()
    logger.info("Database initialized successfully")
    
    # Initialize repository
    stats_repo = StatsRepository(db)
    
    # Start the bot
    await client.start(bot_token=BOT_TOKEN)
    
    # Get bot information
    me = await client.get_me()
    bot_username = me.username
    logger.info(f"Bot started as @{bot_username}!")
    
    # Register all handlers
    BotHandlers(client, stats_repo, bot_username)
    
    # Run until disconnected
    try:
        await client.run_until_disconnected()
    finally:
        db.close()
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
