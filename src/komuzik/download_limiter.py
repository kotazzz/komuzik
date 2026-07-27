"""Download limiter to control concurrent downloads per user."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from .config_loader import ConfigLoader

if TYPE_CHECKING:
    from .repository import StatsRepository

logger = logging.getLogger(__name__)


class DownloadLimiter:
    """Manages download limits for users based on configuration."""

    def __init__(
        self,
        config_loader: ConfigLoader | None = None,
        config_path: str | None = None,
        stats_repo: StatsRepository | None = None,
        timer=time.monotonic,
    ):
        """Initialize the download limiter from config file.

        Args:
            config_loader: Reusable configuration loader instance.
            config_path: Path to config.yaml file. Used when config_loader is not provided.
            stats_repo: Repository for reading effective concurrent limit from DB.
            timer: Monotonic clock, injectable for tests.

        """
        self.config = config_loader.config if config_loader else ConfigLoader(config_path).config
        self.download_config = self.config.get("downloads", {})

        self.yaml_concurrent = self.download_config.get("max_concurrent_per_user", 1)
        self._stats = stats_repo
        self._timer = timer
        self.UNLIMITED_USER_IDS = set(self.download_config.get("unlimited_user_ids", []))
        self.ADMIN_USER_IDS = set(self.download_config.get("admin_user_ids", []))
        self.DOWNLOAD_TIMEOUT = self.download_config.get("download_timeout_seconds", 3600)

        # Active downloads per user: user_id -> {download_id: started_at}.
        # Start times let us reap slots whose owning task died without running
        # its finally block (loop shutdown, hard cancellation).
        self._active_downloads: dict[int, dict[str, float]] = {}
        self._lock: asyncio.Lock | None = None

        logger.info(
            f"DownloadLimiter initialized: max_per_user={self.get_max_per_user()}, "
            f"unlimited_users={self.UNLIMITED_USER_IDS}"
        )

    def get_max_per_user(self) -> int:
        """Return effective concurrent download limit for a normal user."""
        if self._stats is None:
            return self.yaml_concurrent
        return self._stats.get_max_concurrent(default=self.yaml_concurrent)

    @property
    def MAX_DOWNLOADS_PER_USER(self) -> int:
        """Compatibility alias for handlers that read the limit as an attribute."""
        return self.get_max_per_user()

    def prune_stale(self) -> int:
        """Release slots held longer than ``DOWNLOAD_TIMEOUT``.

        Normally ``finish_download`` frees the slot in a ``finally``. That does
        not run if the owning task is destroyed outright — loop shutdown, a hard
        cancellation — and the user would then be locked out of downloads until
        the process restarts. Pruning lazily on every check keeps this correct
        without a background task to supervise.

        Returns:
            Number of slots released.

        """
        if not self._active_downloads:
            return 0

        cutoff = self._timer() - self.DOWNLOAD_TIMEOUT
        released = 0
        for user_id in list(self._active_downloads):
            downloads = self._active_downloads[user_id]
            for download_id in [d for d, started in downloads.items() if started <= cutoff]:
                del downloads[download_id]
                released += 1
                logger.warning(
                    f"Released stale download slot {download_id} of user {user_id} "
                    f"(older than {self.DOWNLOAD_TIMEOUT}s)"
                )
            if not downloads:
                del self._active_downloads[user_id]
        return released

    def can_download(self, user_id: int) -> bool:
        """Check if user can start a new download.

        Args:
            user_id: Telegram user ID

        Returns:
            True if user can download, False otherwise

        """
        # Unlimited users (admins and unlimited_user_ids) can always download
        if user_id in self.UNLIMITED_USER_IDS or user_id in self.ADMIN_USER_IDS:
            return True

        self.prune_stale()

        # Check if user has reached the limit
        active_count = len(self._active_downloads.get(user_id, {}))
        max_per_user = self.get_max_per_user()
        can_proceed = active_count < max_per_user

        if not can_proceed:
            logger.info(
                f"User {user_id} has reached download limit ({active_count}/{max_per_user})"
            )

        return can_proceed

    async def start_download(self, user_id: int, download_id: str) -> bool:
        """Register a new download for a user.

        Args:
            user_id: Telegram user ID
            download_id: Unique identifier for this download

        Returns:
            True if download was registered, False if limit reached

        """
        if self._lock is None:
            self._lock = asyncio.Lock()

        async with self._lock:
            if not self.can_download(user_id):
                return False

            if user_id not in self._active_downloads:
                self._active_downloads[user_id] = {}

            self._active_downloads[user_id][download_id] = self._timer()
            logger.info(
                f"User {user_id} started download {download_id}. Active: {len(self._active_downloads[user_id])}"
            )

            return True

    async def finish_download(self, user_id: int, download_id: str):
        """Remove a download from active downloads.

        Args:
            user_id: Telegram user ID
            download_id: Unique identifier for this download

        """
        if self._lock is None:
            self._lock = asyncio.Lock()

        async with self._lock:
            if user_id in self._active_downloads:
                self._active_downloads[user_id].pop(download_id, None)

                # Clean up empty entries
                if not self._active_downloads[user_id]:
                    del self._active_downloads[user_id]

                logger.info(
                    f"User {user_id} finished download {download_id}. Active: {len(self._active_downloads.get(user_id, {}))}"
                )

    def get_active_count(self, user_id: int) -> int:
        """Get the number of active downloads for a user.

        Args:
            user_id: Telegram user ID

        Returns:
            Number of active downloads

        """
        self.prune_stale()
        return len(self._active_downloads.get(user_id, {}))

    def is_unlimited_user(self, user_id: int) -> bool:
        """Check if user has unlimited downloads.

        Args:
            user_id: Telegram user ID

        Returns:
            True if user has unlimited downloads

        """
        return user_id in self.UNLIMITED_USER_IDS or user_id in self.ADMIN_USER_IDS

    def is_admin(self, user_id: int) -> bool:
        """Check if user is an admin.

        Args:
            user_id: Telegram user ID

        Returns:
            True if user is admin

        """
        return user_id in self.ADMIN_USER_IDS
