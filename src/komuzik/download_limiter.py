"""Download limiter to control concurrent downloads per user."""
import logging
from typing import Dict, Set

logger = logging.getLogger(__name__)


class DownloadLimiter:
    """Manages download limits for users."""
    
    # User ID who has unlimited downloads
    UNLIMITED_USER_ID = 782491733
    
    # Maximum concurrent downloads for regular users
    MAX_DOWNLOADS_PER_USER = 1
    
    def __init__(self):
        """Initialize the download limiter."""
        # Dictionary to track active downloads per user
        # Key: user_id, Value: set of download identifiers
        self._active_downloads: Dict[int, Set[str]] = {}
    
    def can_download(self, user_id: int) -> bool:
        """
        Check if user can start a new download.
        
        Args:
            user_id: Telegram user ID
            
        Returns:
            True if user can download, False otherwise
        """
        # Unlimited user can always download
        if user_id == self.UNLIMITED_USER_ID:
            return True
        
        # Check if user has reached the limit
        active_count = len(self._active_downloads.get(user_id, set()))
        can_proceed = active_count < self.MAX_DOWNLOADS_PER_USER
        
        if not can_proceed:
            logger.info(f"User {user_id} has reached download limit ({active_count}/{self.MAX_DOWNLOADS_PER_USER})")
        
        return can_proceed
    
    def start_download(self, user_id: int, download_id: str) -> bool:
        """
        Register a new download for a user.
        
        Args:
            user_id: Telegram user ID
            download_id: Unique identifier for this download
            
        Returns:
            True if download was registered, False if limit reached
        """
        if not self.can_download(user_id):
            return False
        
        if user_id not in self._active_downloads:
            self._active_downloads[user_id] = set()
        
        self._active_downloads[user_id].add(download_id)
        logger.info(f"User {user_id} started download {download_id}. Active: {len(self._active_downloads[user_id])}")
        
        return True
    
    def finish_download(self, user_id: int, download_id: str):
        """
        Remove a download from active downloads.
        
        Args:
            user_id: Telegram user ID
            download_id: Unique identifier for this download
        """
        if user_id in self._active_downloads:
            self._active_downloads[user_id].discard(download_id)
            
            # Clean up empty sets
            if not self._active_downloads[user_id]:
                del self._active_downloads[user_id]
            
            logger.info(f"User {user_id} finished download {download_id}. Active: {len(self._active_downloads.get(user_id, set()))}")
    
    def get_active_count(self, user_id: int) -> int:
        """
        Get the number of active downloads for a user.
        
        Args:
            user_id: Telegram user ID
            
        Returns:
            Number of active downloads
        """
        return len(self._active_downloads.get(user_id, set()))
    
    def is_unlimited_user(self, user_id: int) -> bool:
        """
        Check if user has unlimited downloads.
        
        Args:
            user_id: Telegram user ID
            
        Returns:
            True if user is unlimited, False otherwise
        """
        return user_id == self.UNLIMITED_USER_ID
