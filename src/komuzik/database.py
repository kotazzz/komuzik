"""SQLite database module for statistics tracking."""
import sqlite3
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class Database:
    """SQLite database manager for bot statistics."""
    
    def __init__(self, db_path: str = "komuzik_stats.db"):
        """Initialize database connection.
        
        Args:
            db_path: Path to the SQLite database file
        """
        self.db_path = db_path
        self.conn: Optional[sqlite3.Connection] = None
        
    def connect(self):
        """Establish database connection and create tables if needed."""
        try:
            # Create database directory if it doesn't exist
            db_dir = Path(self.db_path).parent
            if db_dir != Path('.'):
                db_dir.mkdir(parents=True, exist_ok=True)
            
            self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self.conn.row_factory = sqlite3.Row
            logger.info(f"Connected to database: {self.db_path}")
            self._create_tables()
        except Exception as e:
            logger.error(f"Failed to connect to database: {e}")
            raise
    
    def _create_tables(self):
        """Create database tables if they don't exist."""
        cursor = self.conn.cursor()
        
        # Statistics table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS statistics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                user_id INTEGER,
                username TEXT,
                video_format TEXT,
                platform TEXT,
                success BOOLEAN NOT NULL DEFAULT 1,
                error_message TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Users table (to track unique users)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
                last_seen DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Reports table (to store user reports about problems)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT,
                report_text TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Create indexes for better query performance
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_statistics_event_type 
            ON statistics(event_type)
        ''')
        
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_statistics_timestamp 
            ON statistics(timestamp)
        ''')
        
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_statistics_success 
            ON statistics(success)
        ''')
        
        self.conn.commit()
        logger.info("Database tables created successfully")
    
    def close(self):
        """Close database connection."""
        if self.conn:
            self.conn.close()
            logger.info("Database connection closed")
    
    def execute(self, query: str, params: tuple = ()):
        """Execute a database query.
        
        Args:
            query: SQL query to execute
            params: Query parameters
            
        Returns:
            Cursor object with query results
        """
        cursor = self.conn.cursor()
        cursor.execute(query, params)
        self.conn.commit()
        return cursor
    
    def fetchone(self, query: str, params: tuple = ()):
        """Fetch one result from query.
        
        Args:
            query: SQL query to execute
            params: Query parameters
            
        Returns:
            Single row result or None
        """
        cursor = self.conn.cursor()
        cursor.execute(query, params)
        return cursor.fetchone()
    
    def fetchall(self, query: str, params: tuple = ()):
        """Fetch all results from query.
        
        Args:
            query: SQL query to execute
            params: Query parameters
            
        Returns:
            List of row results
        """
        cursor = self.conn.cursor()
        cursor.execute(query, params)
        return cursor.fetchall()
