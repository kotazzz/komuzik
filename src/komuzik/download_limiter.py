"""Download limiter to control concurrent downloads per user."""
import logging
from typing import Dict, Set
import yaml
import os

logger = logging.getLogger(__name__)


class DownloadLimiter:
    """Manages download limits for users based on configuration."""
    
    def __init__(self, config_path: str = None):
        """Initialize the download limiter from config file.
        
        Args:
            config_path: Path to config.yaml file. If not provided, looks in parent directories.
        """
        self.config = self._load_config(config_path)
        self.download_config = self.config.get('downloads', {})
        
        # Load settings from config
        self.MAX_DOWNLOADS_PER_USER = self.download_config.get('max_concurrent_per_user', 1)
        self.UNLIMITED_USER_IDS = set(self.download_config.get('unlimited_user_ids', []))
        self.DOWNLOAD_TIMEOUT = self.download_config.get('download_timeout_seconds', 3600)
        self.CLEANUP_INTERVAL = self.download_config.get('cleanup_interval_seconds', 300)
        
        # Dictionary to track active downloads per user
        # Key: user_id, Value: set of download identifiers
        self._active_downloads: Dict[int, Set[str]] = {}
        
        logger.info(
            f"DownloadLimiter initialized: max_per_user={self.MAX_DOWNLOADS_PER_USER}, "
            f"unlimited_users={self.UNLIMITED_USER_IDS}"
        )
    
    @staticmethod
    def _load_config(config_path: str = None) -> dict:
        """Load configuration from YAML file.
        
        Args:
            config_path: Path to config.yaml. If None, searches in common locations.
            
        Returns:
            Configuration dictionary
        """
        # Determine config path
        if config_path is None:
            # Search in common locations
            possible_paths = [
                'config.yaml',
                '/mnt/d/prj/komuzik/config.yaml',
                os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'config.yaml'),
            ]
            
            for path in possible_paths:
                if os.path.exists(path):
                    config_path = path
                    break
            
            if config_path is None:
                logger.warning("Config file not found, using empty configuration")
                return {}
        
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f) or {}
                logger.info(f"Configuration loaded from {config_path}")
                return config
        except FileNotFoundError:
            logger.warning(f"Config file not found at {config_path}, using empty configuration")
            return {}
        except yaml.YAMLError as e:
            logger.error(f"Error parsing YAML config: {e}")
            return {}
    
    def can_download(self, user_id: int) -> bool:
        """Check if user can start a new download.
        
        Args:
            user_id: Telegram user ID
            
        Returns:
            True if user can download, False otherwise
        """
        # Unlimited users can always download
        if user_id in self.UNLIMITED_USER_IDS:
            return True
        
        # Check if user has reached the limit
        active_count = len(self._active_downloads.get(user_id, set()))
        can_proceed = active_count < self.MAX_DOWNLOADS_PER_USER
        
        if not can_proceed:
            logger.info(f"User {user_id} has reached download limit ({active_count}/{self.MAX_DOWNLOADS_PER_USER})")
        
        return can_proceed
    
    def start_download(self, user_id: int, download_id: str) -> bool:
        """Register a new download for a user.
        
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
        """Remove a download from active downloads.
        
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
        """Get the number of active downloads for a user.
        
        Args:
            user_id: Telegram user ID
            
        Returns:
            Number of active downloads
        """
        return len(self._active_downloads.get(user_id, set()))
    
    def is_unlimited_user(self, user_id: int) -> bool:
        """Check if user has unlimited downloads.
        
        Args:
            user_id: Telegram user ID
            
        Returns:
            True if user has unlimited downloads
        """
        return user_id in self.UNLIMITED_USER_IDS
