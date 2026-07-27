"""Main entry point for the Komuzik Telegram bot."""

import asyncio
import logging
import os

from telethon import TelegramClient
from telethon.sessions import StringSession

from . import executors
from .config import API_HASH, API_ID, BOT_TOKEN, SESSION_STRING
from .config_loader import ConfigLoader
from .database import Database
from .download_limiter import DownloadLimiter
from .handlers import BotHandlers
from .repository import StatsRepository

# Setup logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Ensure session directory exists
os.makedirs("session", exist_ok=True)

# Initialize the Telegram client
if SESSION_STRING:
    client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH or "")
    logger.info("Using StringSession for authentication")
else:
    session_file = os.path.join(os.getcwd(), "session", "komuzik_bot_session")
    client = TelegramClient(session_file, API_ID, API_HASH or "")
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
    config_loader = ConfigLoader()
    download_limiter = DownloadLimiter(config_loader=config_loader, stats_repo=stats_repo)

    # Start the bot
    start_result = client.start(bot_token=BOT_TOKEN or "")
    if asyncio.iscoroutine(start_result):
        await start_result

    # Get bot information
    me = await client.get_me()
    bot_username = getattr(me, "username", "") or ""
    logger.info(f"Bot started as @{bot_username}!")

    # Register all handlers
    BotHandlers(client, stats_repo, bot_username, download_limiter=download_limiter)

    # Run until disconnected
    try:
        run_result = client.run_until_disconnected()
        if asyncio.iscoroutine(run_result):
            await run_result
    finally:
        db.close()
        executors.shutdown(wait=False)
        disconnect_result = client.disconnect()
        if asyncio.iscoroutine(disconnect_result):
            await disconnect_result


if __name__ == "__main__":
    asyncio.run(main())
