"""Repository layer for statistics tracking and data access."""

import logging
from dataclasses import dataclass

from .database import Database

logger = logging.getLogger(__name__)

DOWNLOAD_EVENT_TYPES = (
    "video_download",
    "audio_download",
    "tiktok_download",
    "pinterest_download",
)
VIDEO_LIKE_EVENT_TYPES = (
    "video_download",
    "tiktok_download",
    "pinterest_download",
)
AUDIO_EVENT_TYPES = ("audio_download",)


@dataclass(frozen=True)
class UserSettings:
    """Per-user media caption preferences."""

    user_id: int
    show_bot_caption: bool = True
    show_title: bool = True
    default_quality: str = "720p"
    last_mode: str | None = None  # video | audio
    last_quality: str | None = None


@dataclass(frozen=True)
class ChatSettings:
    """Per-chat group settings for platforms and captions."""

    chat_id: int
    allow_youtube: bool = True
    allow_tiktok: bool = True
    allow_twitter: bool = True
    allow_pinterest: bool = True
    show_bot_caption: bool = True
    show_title: bool = True
    default_quality: str = "720p"

    def allows_platform(self, platform: str) -> bool:
        """Return whether auto-download is enabled for a parsed platform key."""
        if platform in {"youtube", "youtube_shorts"}:
            return self.allow_youtube
        if platform == "tiktok":
            return self.allow_tiktok
        if platform == "twitter":
            return self.allow_twitter
        if platform == "pinterest":
            return self.allow_pinterest
        return True


CHAT_SETTING_KEYS = {
    "allow_youtube",
    "allow_tiktok",
    "allow_twitter",
    "allow_pinterest",
    "show_bot_caption",
    "show_title",
}

ALLOWED_DEFAULT_QUALITIES = ("360p", "480p", "720p", "1080p")


def _normalize_default_quality(value: str | None) -> str:
    if value in ALLOWED_DEFAULT_QUALITIES:
        return value
    return "720p"


class StatsRepository:
    """Repository for managing bot statistics."""

    def __init__(self, database: Database):
        """Initialize repository with database connection.

        Args:
            database: Database instance

        """
        self.db = database

    # === User tracking ===

    def track_user(self, user_id: int, username: str | None = None):
        """Track user activity (first seen or update last seen).

        Args:
            user_id: Telegram user ID
            username: Telegram username

        """
        try:
            # Check if user exists
            existing = self.db.fetchone("SELECT user_id FROM users WHERE user_id = ?", (user_id,))

            if existing:
                # Update last seen
                self.db.execute(
                    "UPDATE users SET last_seen = CURRENT_TIMESTAMP, username = ? WHERE user_id = ?",
                    (username, user_id),
                )
            else:
                # Insert new user
                self.db.execute(
                    "INSERT INTO users (user_id, username) VALUES (?, ?)", (user_id, username)
                )
            logger.debug(f"Tracked user: {user_id}")
        except Exception as e:
            logger.error(f"Failed to track user {user_id}: {e}")

    # === Event tracking ===

    def track_search(self, user_id: int, username: str | None = None):
        """Track a search event.

        Args:
            user_id: Telegram user ID
            username: Telegram username

        """
        self._track_event("search", user_id, username)

    def track_video_download(
        self,
        user_id: int,
        video_format: str,
        platform: str = "youtube",
        username: str | None = None,
        success: bool = True,
        error_message: str | None = None,
        source: str = "dm",
    ):
        """Track a video download event.

        Args:
            user_id: Telegram user ID
            video_format: Video format (e.g., '720p', '1080p')
            platform: Platform ('youtube' or 'tiktok')
            username: Telegram username
            success: Whether download was successful
            error_message: Error message if download failed
            source: Download source ('dm' or 'inline')

        """
        self._track_event(
            "video_download",
            user_id,
            username,
            video_format=video_format,
            platform=platform,
            success=success,
            error_message=error_message,
            source=source,
        )

    def track_audio_download(
        self,
        user_id: int,
        audio_quality: str,
        username: str | None = None,
        success: bool = True,
        error_message: str | None = None,
        source: str = "dm",
    ):
        """Track an audio download event.

        Args:
            user_id: Telegram user ID
            audio_quality: Audio quality (e.g., 'high', 'medium', 'low')
            username: Telegram username
            success: Whether download was successful
            error_message: Error message if download failed
            source: Download source ('dm' or 'inline')

        """
        self._track_event(
            "audio_download",
            user_id,
            username,
            video_format=audio_quality,
            platform="youtube",
            success=success,
            error_message=error_message,
            source=source,
        )

    def track_tiktok_download(
        self,
        user_id: int,
        username: str | None = None,
        success: bool = True,
        error_message: str | None = None,
        source: str = "dm",
    ):
        """Track a TikTok download event.

        Args:
            user_id: Telegram user ID
            username: Telegram username
            success: Whether download was successful
            error_message: Error message if download failed
            source: Download source ('dm' or 'inline')

        """
        self._track_event(
            "tiktok_download",
            user_id,
            username,
            platform="tiktok",
            success=success,
            error_message=error_message,
            source=source,
        )

    def track_pinterest_download(
        self,
        user_id: int,
        username: str | None = None,
        success: bool = True,
        error_message: str | None = None,
        source: str = "dm",
    ):
        """Track a Pinterest download event.

        Args:
            user_id: Telegram user ID
            username: Telegram username
            success: Whether download was successful
            error_message: Error message if download failed
            source: Download source ('dm' or 'inline')

        """
        self._track_event(
            "pinterest_download",
            user_id,
            username,
            platform="pinterest",
            success=success,
            error_message=error_message,
            source=source,
        )

    def track_error(
        self,
        user_id: int,
        error_type: str,
        error_message: str,
        username: str | None = None,
        source: str | None = None,
    ):
        """Track an error event.

        Args:
            user_id: Telegram user ID
            error_type: Type of error
            error_message: Error message
            username: Telegram username
            source: Download source if applicable

        """
        self._track_event(
            f"error_{error_type}",
            user_id,
            username,
            success=False,
            error_message=error_message,
            source=source,
        )

    def _track_event(
        self,
        event_type: str,
        user_id: int,
        username: str | None = None,
        video_format: str | None = None,
        platform: str | None = None,
        success: bool = True,
        error_message: str | None = None,
        source: str | None = None,
    ):
        """Internal method to track any event.

        Args:
            event_type: Type of event
            user_id: Telegram user ID
            username: Telegram username
            video_format: Video format or audio quality
            platform: Platform name
            success: Whether operation was successful
            error_message: Error message if failed
            source: Download source ('dm' or 'inline')

        """
        try:
            self.db.execute(
                """INSERT INTO statistics 
                   (event_type, user_id, username, video_format, platform, source, success, error_message)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    event_type,
                    user_id,
                    username,
                    video_format,
                    platform,
                    source,
                    success,
                    error_message,
                ),
            )
            logger.debug(f"Tracked event: {event_type} for user {user_id}")
        except Exception as e:
            logger.error(f"Failed to track event {event_type}: {e}")

    # === Statistics queries ===

    def get_statistics(self, period: str = "all") -> dict:
        """Get comprehensive statistics for a given period.

        Args:
            period: Time period ('day', 'month', 'all')

        Returns:
            Dictionary with statistics

        """
        date_filter = self._get_date_filter(period)

        stats = {
            "period": period,
            "total_users": self._get_user_count(date_filter),
            "total_searches": self._get_event_count("search", date_filter),
            "total_videos": self._get_event_count("video_download", date_filter),
            "total_audio": self._get_event_count("audio_download", date_filter),
            "total_tiktoks": self._get_event_count("tiktok_download", date_filter),
            "total_pinterest": self._get_event_count("pinterest_download", date_filter),
            "total_downloads": self._get_total_downloads(date_filter),
            "successful_downloads": self._get_successful_downloads(date_filter),
            "failed_downloads": self._get_failed_downloads(date_filter),
            "popular_video_formats": self._get_popular_formats("video_download", date_filter),
            "popular_audio_formats": self._get_popular_formats("audio_download", date_filter),
            "error_count": self._get_error_count(date_filter),
            "by_source": self._get_download_breakdown_by_source(date_filter),
            "by_content": self._get_download_breakdown_by_content(date_filter),
            "total_groups": 0,
        }

        return stats

    def _get_date_filter(self, period: str) -> str:
        """Get SQL date filter for the given period.

        Args:
            period: Time period ('day', 'month', 'all')

        Returns:
            SQL WHERE clause for date filtering or None

        """
        if period == "day":
            return "AND timestamp >= datetime('now', '-1 day')"
        if period == "month":
            return "AND timestamp >= datetime('now', '-1 month')"
        return ""

    def _get_user_count(self, date_filter: str) -> int:
        """Get count of unique users.

        Args:
            date_filter: SQL date filter clause

        Returns:
            Number of unique users

        """
        if date_filter:
            # Count users active in the period
            query = f"SELECT COUNT(DISTINCT user_id) FROM statistics WHERE 1=1 {date_filter}"
        else:
            # Count all registered users
            query = "SELECT COUNT(*) FROM users"

        result = self.db.fetchone(query)
        return result[0] if result else 0

    def _get_event_count(self, event_type: str, date_filter: str) -> int:
        """Get count of events of a specific type.

        Args:
            event_type: Type of event
            date_filter: SQL date filter clause

        Returns:
            Number of events

        """
        query = f"SELECT COUNT(*) FROM statistics WHERE event_type = ? {date_filter}"
        result = self.db.fetchone(query, (event_type,))
        return result[0] if result else 0

    def _download_event_filter(self) -> str:
        placeholders = ", ".join("?" * len(DOWNLOAD_EVENT_TYPES))
        return f"event_type IN ({placeholders})"

    def _get_total_downloads(self, date_filter: str) -> int:
        """Get total number of downloads (video + audio + tiktok + pinterest).

        Args:
            date_filter: SQL date filter clause

        Returns:
            Total downloads

        """
        query = f"""SELECT COUNT(*) FROM statistics 
                    WHERE {self._download_event_filter()}
                    {date_filter}"""
        result = self.db.fetchone(query, DOWNLOAD_EVENT_TYPES)
        return result[0] if result else 0

    def _get_successful_downloads(self, date_filter: str) -> int:
        """Get number of successful downloads.

        Args:
            date_filter: SQL date filter clause

        Returns:
            Number of successful downloads

        """
        query = f"""SELECT COUNT(*) FROM statistics 
                    WHERE {self._download_event_filter()}
                    AND success = 1
                    {date_filter}"""
        result = self.db.fetchone(query, DOWNLOAD_EVENT_TYPES)
        return result[0] if result else 0

    def _get_failed_downloads(self, date_filter: str) -> int:
        """Get number of failed downloads.

        Args:
            date_filter: SQL date filter clause

        Returns:
            Number of failed downloads

        """
        query = f"""SELECT COUNT(*) FROM statistics 
                    WHERE {self._download_event_filter()}
                    AND success = 0
                    {date_filter}"""
        result = self.db.fetchone(query, DOWNLOAD_EVENT_TYPES)
        return result[0] if result else 0

    def _get_download_breakdown_by_source(self, date_filter: str) -> dict[str, int]:
        """Count downloads by source (dm/inline/group). Missing source counts as dm."""
        query = f"""SELECT COALESCE(source, 'dm') AS src, COUNT(*) as count
                    FROM statistics
                    WHERE {self._download_event_filter()}
                    {date_filter}
                    GROUP BY COALESCE(source, 'dm')"""
        rows = self.db.fetchall(query, DOWNLOAD_EVENT_TYPES)
        result = {"dm": 0, "inline": 0, "group": 0}
        for row in rows or []:
            key = row[0] if row[0] in result else "dm"
            result[key] = row[1]
        return result

    def _get_download_breakdown_by_content(self, date_filter: str) -> dict[str, int]:
        """Count downloads by content kind (video-like vs audio)."""
        video_placeholders = ", ".join("?" * len(VIDEO_LIKE_EVENT_TYPES))
        audio_placeholders = ", ".join("?" * len(AUDIO_EVENT_TYPES))
        video_query = f"""SELECT COUNT(*) FROM statistics
                          WHERE event_type IN ({video_placeholders})
                          {date_filter}"""
        audio_query = f"""SELECT COUNT(*) FROM statistics
                          WHERE event_type IN ({audio_placeholders})
                          {date_filter}"""
        video_count = self.db.fetchone(video_query, VIDEO_LIKE_EVENT_TYPES)
        audio_count = self.db.fetchone(audio_query, AUDIO_EVENT_TYPES)
        return {
            "video": video_count[0] if video_count else 0,
            "audio": audio_count[0] if audio_count else 0,
        }

    def _get_popular_formats(self, event_type: str, date_filter: str, limit: int = 5) -> list:
        """Get most popular formats for a given event type.

        Args:
            event_type: Type of event
            date_filter: SQL date filter clause
            limit: Maximum number of results

        Returns:
            List of tuples (format, count)

        """
        query = f"""SELECT video_format, COUNT(*) as count 
                    FROM statistics 
                    WHERE event_type = ? AND video_format IS NOT NULL
                    {date_filter}
                    GROUP BY video_format
                    ORDER BY count DESC
                    LIMIT ?"""
        results = self.db.fetchall(query, (event_type, limit))
        return [(row[0], row[1]) for row in results] if results else []

    def _get_error_count(self, date_filter: str) -> int:
        """Get count of error events.

        Args:
            date_filter: SQL date filter clause

        Returns:
            Number of error events

        """
        query = f"""SELECT COUNT(*) FROM statistics 
                    WHERE event_type LIKE 'error_%'
                    {date_filter}"""
        result = self.db.fetchone(query)
        return result[0] if result else 0

    def get_all_users(self) -> list:
        """Get all tracked users.

        Returns:
            List of tuples (user_id, username)

        """
        try:
            results = self.db.fetchall("SELECT user_id, username FROM users")
            return [(row[0], row[1]) for row in results] if results else []
        except Exception as e:
            logger.error(f"Failed to get all users: {e}")
            return []

    # === Report tracking ===

    def save_user_report(self, user_id: int, username: str | None, report_text: str):
        """Save user report to database.

        Args:
            user_id: Telegram user ID
            username: Telegram username
            report_text: Report text

        """
        try:
            self.db.execute(
                "INSERT INTO reports (user_id, username, report_text) VALUES (?, ?, ?)",
                (user_id, username, report_text),
            )
            logger.info(f"Saved report from user {user_id}: {report_text[:50]}...")
        except Exception as e:
            logger.error(f"Failed to save report from {user_id}: {e}")

    def get_all_reports(self) -> list:
        """Get all reports from users.

        Returns:
            List of (user_id, username, report_text, timestamp) tuples

        """
        try:
            results = self.db.fetchall(
                "SELECT user_id, username, report_text, created_at FROM reports ORDER BY created_at DESC"
            )
            return results or []
        except Exception as e:
            logger.error(f"Failed to get reports: {e}")
            return []

    def save_report_thread(
        self,
        admin_id: int,
        header_msg_id: int,
        body_msg_id: int,
        user_id: int,
        user_report_msg_id: int,
    ) -> None:
        """Link admin header/body report messages to the user's original report."""
        try:
            self.db.execute(
                """INSERT INTO report_threads
                   (admin_id, header_msg_id, body_msg_id, user_id, user_report_msg_id)
                   VALUES (?, ?, ?, ?, ?)""",
                (admin_id, header_msg_id, body_msg_id, user_id, user_report_msg_id),
            )
        except Exception as e:
            logger.error(f"Failed to save report thread for admin {admin_id}: {e}")

    def get_report_thread_by_admin_msg(
        self, admin_id: int, message_id: int
    ) -> tuple[int, int] | None:
        """Resolve admin report message to (user_id, user_report_msg_id)."""
        try:
            row = self.db.fetchone(
                """SELECT user_id, user_report_msg_id FROM report_threads
                   WHERE admin_id = ? AND (header_msg_id = ? OR body_msg_id = ?)
                   ORDER BY id DESC LIMIT 1""",
                (admin_id, message_id, message_id),
            )
            if not row:
                return None
            return int(row[0]), int(row[1])
        except Exception as e:
            logger.error(f"Failed to lookup report thread: {e}")
            return None

    # === User settings ===

    def get_user_settings(self, user_id: int) -> UserSettings:
        """Return caption settings for a user (defaults: both enabled, 720p)."""
        try:
            row = self.db.fetchone(
                """SELECT show_bot_caption, show_title, default_quality,
                          last_mode, last_quality
                   FROM user_settings WHERE user_id = ?""",
                (user_id,),
            )
            if not row:
                return UserSettings(user_id=user_id)
            last_mode = row[3] if row[3] in {"video", "audio"} else None
            last_quality = str(row[4]) if row[4] else None
            if last_mode and not last_quality:
                last_mode = None
            return UserSettings(
                user_id=user_id,
                show_bot_caption=bool(row[0]),
                show_title=bool(row[1]),
                default_quality=_normalize_default_quality(row[2]),
                last_mode=last_mode,
                last_quality=last_quality,
            )
        except Exception as e:
            logger.error(f"Failed to get settings for {user_id}: {e}")
            return UserSettings(user_id=user_id)

    def _save_user_settings(
        self,
        user_id: int,
        *,
        show_bot_caption: bool,
        show_title: bool,
        default_quality: str,
        last_mode: str | None = None,
        last_quality: str | None = None,
    ) -> UserSettings:
        quality = _normalize_default_quality(default_quality)
        if last_mode not in {"video", "audio"}:
            last_mode = None
            last_quality = None
        try:
            self.db.execute(
                """INSERT INTO user_settings
                   (user_id, show_bot_caption, show_title, default_quality,
                    last_mode, last_quality, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                   ON CONFLICT(user_id) DO UPDATE SET
                     show_bot_caption = excluded.show_bot_caption,
                     show_title = excluded.show_title,
                     default_quality = excluded.default_quality,
                     last_mode = excluded.last_mode,
                     last_quality = excluded.last_quality,
                     updated_at = CURRENT_TIMESTAMP""",
                (
                    user_id,
                    int(show_bot_caption),
                    int(show_title),
                    quality,
                    last_mode,
                    last_quality,
                ),
            )
        except Exception as e:
            logger.error(f"Failed to save settings for {user_id}: {e}")
        return UserSettings(
            user_id=user_id,
            show_bot_caption=show_bot_caption,
            show_title=show_title,
            default_quality=quality,
            last_mode=last_mode,
            last_quality=last_quality,
        )

    def set_user_setting(self, user_id: int, key: str, value: bool) -> UserSettings:
        """Upsert a single user setting key ('show_bot_caption' or 'show_title')."""
        if key not in {"show_bot_caption", "show_title"}:
            raise ValueError(f"Unknown settings key: {key}")

        current = self.get_user_settings(user_id)
        show_bot = value if key == "show_bot_caption" else current.show_bot_caption
        show_title = value if key == "show_title" else current.show_title
        return self._save_user_settings(
            user_id,
            show_bot_caption=show_bot,
            show_title=show_title,
            default_quality=current.default_quality,
            last_mode=current.last_mode,
            last_quality=current.last_quality,
        )

    def set_user_default_quality(self, user_id: int, quality: str) -> UserSettings:
        """Set personal default YouTube quality for inline."""
        current = self.get_user_settings(user_id)
        return self._save_user_settings(
            user_id,
            show_bot_caption=current.show_bot_caption,
            show_title=current.show_title,
            default_quality=quality,
            last_mode=current.last_mode,
            last_quality=current.last_quality,
        )

    def set_user_last_format(self, user_id: int, mode: str, quality: str) -> UserSettings:
        """Remember last successful DM YouTube format for quick repeat."""
        if mode not in {"video", "audio"} or not quality:
            raise ValueError(f"Invalid last format: {mode}/{quality}")
        current = self.get_user_settings(user_id)
        return self._save_user_settings(
            user_id,
            show_bot_caption=current.show_bot_caption,
            show_title=current.show_title,
            default_quality=current.default_quality,
            last_mode=mode,
            last_quality=quality,
        )

    def toggle_user_setting(self, user_id: int, key: str) -> UserSettings:
        """Toggle a boolean user setting and return the updated settings."""
        current = self.get_user_settings(user_id)
        if key == "show_bot_caption":
            return self.set_user_setting(user_id, key, not current.show_bot_caption)
        if key == "show_title":
            return self.set_user_setting(user_id, key, not current.show_title)
        raise ValueError(f"Unknown settings key: {key}")

    # === Chat settings (groups) ===

    def get_chat_settings(self, chat_id: int) -> ChatSettings:
        """Return group settings (defaults: all enabled, 720p)."""
        try:
            row = self.db.fetchone(
                """SELECT allow_youtube, allow_tiktok, allow_twitter, allow_pinterest,
                          show_bot_caption, show_title, default_quality
                   FROM chat_settings WHERE chat_id = ?""",
                (chat_id,),
            )
            if not row:
                return ChatSettings(chat_id=chat_id)
            return ChatSettings(
                chat_id=chat_id,
                allow_youtube=bool(row[0]),
                allow_tiktok=bool(row[1]),
                allow_twitter=bool(row[2]),
                allow_pinterest=bool(row[3]),
                show_bot_caption=bool(row[4]),
                show_title=bool(row[5]),
                default_quality=_normalize_default_quality(row[6]),
            )
        except Exception as e:
            logger.error(f"Failed to get chat settings for {chat_id}: {e}")
            return ChatSettings(chat_id=chat_id)

    def _save_chat_settings(self, chat_id: int, settings: ChatSettings) -> ChatSettings:
        quality = _normalize_default_quality(settings.default_quality)
        saved = ChatSettings(
            chat_id=chat_id,
            allow_youtube=settings.allow_youtube,
            allow_tiktok=settings.allow_tiktok,
            allow_twitter=settings.allow_twitter,
            allow_pinterest=settings.allow_pinterest,
            show_bot_caption=settings.show_bot_caption,
            show_title=settings.show_title,
            default_quality=quality,
        )
        try:
            self.db.execute(
                """INSERT INTO chat_settings (
                       chat_id, allow_youtube, allow_tiktok, allow_twitter, allow_pinterest,
                       show_bot_caption, show_title, default_quality, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                   ON CONFLICT(chat_id) DO UPDATE SET
                     allow_youtube = excluded.allow_youtube,
                     allow_tiktok = excluded.allow_tiktok,
                     allow_twitter = excluded.allow_twitter,
                     allow_pinterest = excluded.allow_pinterest,
                     show_bot_caption = excluded.show_bot_caption,
                     show_title = excluded.show_title,
                     default_quality = excluded.default_quality,
                     updated_at = CURRENT_TIMESTAMP""",
                (
                    chat_id,
                    int(saved.allow_youtube),
                    int(saved.allow_tiktok),
                    int(saved.allow_twitter),
                    int(saved.allow_pinterest),
                    int(saved.show_bot_caption),
                    int(saved.show_title),
                    saved.default_quality,
                ),
            )
        except Exception as e:
            logger.error(f"Failed to save chat settings for {chat_id}: {e}")
        return saved

    def set_chat_setting(self, chat_id: int, key: str, value: bool) -> ChatSettings:
        """Upsert a single chat setting key."""
        if key not in CHAT_SETTING_KEYS:
            raise ValueError(f"Unknown chat settings key: {key}")

        current = self.get_chat_settings(chat_id)
        updated = {
            "allow_youtube": current.allow_youtube,
            "allow_tiktok": current.allow_tiktok,
            "allow_twitter": current.allow_twitter,
            "allow_pinterest": current.allow_pinterest,
            "show_bot_caption": current.show_bot_caption,
            "show_title": current.show_title,
            "default_quality": current.default_quality,
        }
        updated[key] = value
        return self._save_chat_settings(chat_id, ChatSettings(chat_id=chat_id, **updated))

    def set_chat_default_quality(self, chat_id: int, quality: str) -> ChatSettings:
        """Set group default YouTube quality for auto-download."""
        current = self.get_chat_settings(chat_id)
        return self._save_chat_settings(
            chat_id,
            ChatSettings(
                chat_id=chat_id,
                allow_youtube=current.allow_youtube,
                allow_tiktok=current.allow_tiktok,
                allow_twitter=current.allow_twitter,
                allow_pinterest=current.allow_pinterest,
                show_bot_caption=current.show_bot_caption,
                show_title=current.show_title,
                default_quality=quality,
            ),
        )

    def toggle_chat_setting(self, chat_id: int, key: str) -> ChatSettings:
        """Toggle a boolean chat setting and return the updated settings."""
        if key not in CHAT_SETTING_KEYS:
            raise ValueError(f"Unknown chat settings key: {key}")
        current = self.get_chat_settings(chat_id)
        return self.set_chat_setting(chat_id, key, not getattr(current, key))

    # === Bot config (storage group) ===

    STORAGE_CHAT_ID_KEY = "storage_chat_id"

    def get_storage_chat_id(self) -> int | None:
        try:
            row = self.db.fetchone(
                "SELECT value FROM bot_config WHERE key = ?",
                (self.STORAGE_CHAT_ID_KEY,),
            )
            if not row or row[0] is None:
                return None
            return int(row[0])
        except Exception as e:
            logger.error(f"Failed to get storage_chat_id: {e}")
            return None

    def set_storage_chat_id(self, chat_id: int) -> None:
        try:
            self.db.execute(
                """INSERT INTO bot_config(key, value) VALUES(?, ?)
                   ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
                (self.STORAGE_CHAT_ID_KEY, str(int(chat_id))),
            )
        except Exception as e:
            logger.error(f"Failed to set storage_chat_id: {e}")
            raise

    def clear_storage_chat_id(self) -> None:
        try:
            self.db.execute(
                "DELETE FROM bot_config WHERE key = ?",
                (self.STORAGE_CHAT_ID_KEY,),
            )
        except Exception as e:
            logger.error(f"Failed to clear storage_chat_id: {e}")
            raise
