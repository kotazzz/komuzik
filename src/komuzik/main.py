"""Main entry point for the Komuzik Telegram bot."""

from __future__ import annotations

import asyncio
import logging
import signal
from pathlib import Path

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


def build_client() -> TelegramClient:
    """Create the Telegram client (no network I/O). Safe to call after import."""
    Path("session").mkdir(parents=True, exist_ok=True)
    if SESSION_STRING:
        logger.info("Using StringSession for authentication")
        return TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH or "")
    session_file = str(Path.cwd() / "session" / "komuzik_bot_session")
    logger.info("Using file-based session at %s", session_file)
    return TelegramClient(session_file, API_ID, API_HASH or "")


async def main():
    """Start and run the bot."""
    # Check required environment variables
    if not all([API_ID, API_HASH, BOT_TOKEN]):
        logger.error("Please set API_ID, API_HASH and BOT_TOKEN environment variables.")
        return

    client = build_client()

    # Initialize database
    db_path = str(Path.cwd() / "data" / "komuzik_stats.db")
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

    loop = asyncio.get_running_loop()

    def _request_shutdown() -> None:
        logger.info("Shutdown signal received — disconnecting…")
        # disconnect() is sync-or-async depending on Telethon version; schedule either way.
        result = client.disconnect()
        if asyncio.iscoroutine(result):
            loop.create_task(result)

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _request_shutdown)
        except NotImplementedError:
            # Windows / restricted event loops: fall back to default KeyboardInterrupt.
            signal.signal(sig, lambda *_: _request_shutdown())

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
