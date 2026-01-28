"""Configuration loader for YAML config file."""
import logging
import os
import yaml
from typing import Any, Dict

logger = logging.getLogger(__name__)


class ConfigLoader:
    """Loads and manages application configuration from YAML file."""
    
    def __init__(self, config_path: str = None):
        """Initialize config loader.
        
        Args:
            config_path: Path to config.yaml file. If not provided, searches in common locations.
        """
        self.config_path = config_path
        self.config = self._load_config()
    
    @staticmethod
    def _find_config_file(config_path: str = None) -> str:
        """Find config file in common locations.
        
        Args:
            config_path: Explicit path to config file
            
        Returns:
            Path to config file if found, None otherwise
        """
        if config_path and os.path.exists(config_path):
            return config_path
        
        # Search in common locations
        possible_paths = [
            'config.yaml',
            '/mnt/d/prj/komuzik/config.yaml',
            os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'config.yaml'),
        ]
        
        for path in possible_paths:
            if os.path.exists(path):
                return path
        
        return None
    
    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from YAML file.
        
        Returns:
            Configuration dictionary
        """
        config_path = self._find_config_file(self.config_path)
        
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
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value by key.
        
        Args:
            key: Configuration key (e.g., 'downloads.max_concurrent_per_user')
            default: Default value if key not found
            
        Returns:
            Configuration value or default
        """
        keys = key.split('.')
        value = self.config
        
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
                if value is None:
                    return default
            else:
                return default
        
        return value
    
    def get_section(self, section: str) -> Dict[str, Any]:
        """Get entire configuration section.
        
        Args:
            section: Section name (e.g., 'downloads')
            
        Returns:
            Dictionary with section configuration
        """
        return self.config.get(section, {})
