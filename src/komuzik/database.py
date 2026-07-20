"""SQLite database module for statistics tracking."""

import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)


class Database:
    """SQLite database manager for bot statistics."""

    def __init__(self, db_path: str = "komuzik_stats.db"):
        """Initialize database connection.

        Args:
            db_path: Path to the SQLite database file

        """
        self.db_path = db_path
        self.conn: sqlite3.Connection | None = None

    def _connection(self) -> sqlite3.Connection:
        """Return an active DB connection or raise if not connected."""
        if self.conn is None:
            raise RuntimeError("Database connection is not initialized")
        return self.conn

    def connect(self):
        """Establish database connection and create tables if needed."""
        try:
            # Create database directory if it doesn't exist
            db_dir = Path(self.db_path).parent
            if db_dir != Path():
                db_dir.mkdir(parents=True, exist_ok=True)

            self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self.conn.row_factory = sqlite3.Row
            self.conn.execute("PRAGMA journal_mode=WAL;")
            self.conn.execute("PRAGMA busy_timeout=5000;")
            self.conn.execute("PRAGMA foreign_keys=ON;")
            logger.info(f"Connected to database: {self.db_path}")
            self._create_tables()
        except Exception as e:
            logger.error(f"Failed to connect to database: {e}")
            raise

    def _create_tables(self):
        """Create database tables if they don't exist."""
        conn = self._connection()
        cursor = conn.cursor()

        # Statistics table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS statistics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                user_id INTEGER,
                username TEXT,
                video_format TEXT,
                platform TEXT,
                source TEXT,
                success BOOLEAN NOT NULL DEFAULT 1,
                error_message TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        self._ensure_statistics_source_column(cursor)

        # Users table (to track unique users)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
                last_seen DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Reports table (to store user reports about problems)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT,
                report_text TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Links admin report messages to the original user report (for replies)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS report_threads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_id INTEGER NOT NULL,
                header_msg_id INTEGER NOT NULL,
                body_msg_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                user_report_msg_id INTEGER NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_report_threads_admin_header
            ON report_threads(admin_id, header_msg_id)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_report_threads_admin_body
            ON report_threads(admin_id, body_msg_id)
        """)

        # Per-user caption preferences (defaults: both enabled)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_settings (
                user_id INTEGER PRIMARY KEY,
                show_bot_caption INTEGER NOT NULL DEFAULT 1,
                show_title INTEGER NOT NULL DEFAULT 1,
                default_quality TEXT NOT NULL DEFAULT '720p',
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Per-chat settings for groups (platforms + captions)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS chat_settings (
                chat_id INTEGER PRIMARY KEY,
                allow_youtube INTEGER NOT NULL DEFAULT 1,
                allow_tiktok INTEGER NOT NULL DEFAULT 1,
                allow_twitter INTEGER NOT NULL DEFAULT 1,
                allow_pinterest INTEGER NOT NULL DEFAULT 1,
                show_bot_caption INTEGER NOT NULL DEFAULT 1,
                show_title INTEGER NOT NULL DEFAULT 1,
                default_quality TEXT NOT NULL DEFAULT '720p',
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS bot_config (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_playlist_limits (
                user_id INTEGER PRIMARY KEY,
                daily_limit INTEGER NOT NULL,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS playlist_usage (
                user_id INTEGER NOT NULL,
                day TEXT NOT NULL,
                count INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (user_id, day)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_bans (
                user_id INTEGER PRIMARY KEY,
                reason TEXT NOT NULL,
                banned_by INTEGER,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        self._ensure_column(cursor, "user_settings", "default_quality", "TEXT NOT NULL DEFAULT '720p'")
        self._ensure_column(cursor, "chat_settings", "default_quality", "TEXT NOT NULL DEFAULT '720p'")
        self._ensure_column(cursor, "user_settings", "last_mode", "TEXT")
        self._ensure_column(cursor, "user_settings", "last_quality", "TEXT")
        self._ensure_column(cursor, "statistics", "url", "TEXT")
        self._ensure_column(cursor, "statistics", "title", "TEXT")
        self._ensure_column(cursor, "users", "display_name", "TEXT")

        # Create indexes for better query performance
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_statistics_event_type 
            ON statistics(event_type)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_statistics_timestamp 
            ON statistics(timestamp)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_statistics_success 
            ON statistics(success)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_statistics_source
            ON statistics(source)
        """)

        conn.commit()
        logger.info("Database tables created successfully")

    def _ensure_statistics_source_column(self, cursor: sqlite3.Cursor):
        """Add source column to existing statistics tables (migration)."""
        columns = {row[1] for row in cursor.execute("PRAGMA table_info(statistics)").fetchall()}
        if "source" not in columns:
            cursor.execute("ALTER TABLE statistics ADD COLUMN source TEXT")
            logger.info("Migrated statistics table: added source column")

    def _ensure_column(
        self, cursor: sqlite3.Cursor, table: str, column: str, column_def: str
    ) -> None:
        """Add a column to an existing table if missing."""
        columns = {row[1] for row in cursor.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in columns:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_def}")
            logger.info(f"Migrated {table}: added {column}")

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
        conn = self._connection()
        cursor = conn.cursor()
        cursor.execute(query, params)
        conn.commit()
        return cursor

    def fetchone(self, query: str, params: tuple = ()):
        """Fetch one result from query.

        Args:
            query: SQL query to execute
            params: Query parameters

        Returns:
            Single row result or None

        """
        conn = self._connection()
        cursor = conn.cursor()
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
        conn = self._connection()
        cursor = conn.cursor()
        cursor.execute(query, params)
        return cursor.fetchall()
