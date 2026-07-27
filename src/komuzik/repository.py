"""Repository layer for statistics tracking and data access."""

import logging
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from .database import Database
from .i18n import t
from .timeutil import MSK, today_msk

logger = logging.getLogger(__name__)

DOWNLOAD_EVENT_TYPES = (
    "video_download",
    "audio_download",
    "tiktok_download",
    "twitter_download",
    "pinterest_download",
)
VIDEO_LIKE_EVENT_TYPES = (
    "video_download",
    "tiktok_download",
    "twitter_download",
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


def _escape_markdown_title(title: str) -> str:
    """Strip markdown-sensitive characters from a history link title."""
    for ch in "[]()":
        title = title.replace(ch, "")
    return title.strip()


def _format_history_timestamp(timestamp: str | None) -> str:
    if not timestamp:
        return ""
    try:
        dt = datetime.fromisoformat(str(timestamp).replace(" ", "T"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo("UTC")).astimezone(MSK)
        else:
            dt = dt.astimezone(MSK)
        return dt.strftime("%d.%m %H:%M")
    except (TypeError, ValueError):
        text = str(timestamp)
        return text[:16] if len(text) >= 16 else text


def _history_platform_label(platform: str | None) -> str:
    key = (platform or "").strip().lower()
    if key == "hls_host":
        return ""
    msg_key = f"admin.history.platform.{key}"
    label = t(msg_key)
    if label != msg_key:
        return label
    return platform.strip() if platform else ""


def _history_quality_label(fmt: str | None) -> str:
    key = (fmt or "").strip().lower()
    msg_key = f"admin.history.quality.{key}"
    label = t(msg_key)
    if label != msg_key:
        return label
    return (fmt or "").strip()


def _history_type_label(event_type: str | None, video_format: str | None) -> str:
    quality = _history_quality_label(video_format)
    if event_type == "video_download":
        if quality:
            return t("admin.history.type.video_with_quality", quality=quality)
        return t("admin.history.type.video")
    if event_type == "audio_download":
        if quality:
            return t("admin.history.type.audio_with_quality", quality=quality)
        return t("admin.history.type.audio")
    if event_type == "tiktok_download":
        return t("admin.history.type.video")
    if event_type in {"twitter_download", "pinterest_download"}:
        return t("admin.history.type.media")
    return quality


def format_download_history_line(row: dict) -> str:
    """Format one download history row as a Markdown bullet line."""
    success = row.get("success", True)
    prefix = "✗ " if not success else ""
    bullet = f"{prefix}• "

    url = row.get("url")
    title = row.get("title")
    platform = _history_platform_label(row.get("platform"))
    type_label = _history_type_label(row.get("event_type"), row.get("video_format"))
    ts = _format_history_timestamp(row.get("timestamp"))

    detail_parts: list[str] = []
    if platform:
        detail_parts.append(platform)
    if type_label:
        detail_parts.append(type_label)
    if ts:
        detail_parts.append(ts)

    if url and title:
        safe_title = _escape_markdown_title(str(title))
        line = f"{bullet}[{safe_title}]({url})"
        if detail_parts:
            line += " · " + " · ".join(detail_parts)
        return line

    if detail_parts:
        return bullet + " · ".join(detail_parts)
    return bullet.rstrip()


def format_user_label(user: dict) -> str:
    """Format a user for admin list/buttons (no raw id — use 'аноним')."""
    username = (user.get("username") or "").strip().lstrip("@") or None
    display_name = (user.get("display_name") or "").strip() or None

    if display_name and username:
        return f"{display_name} (@{username})"
    if display_name:
        return display_name
    if username:
        return f"@{username}"
    return t("admin.user_anonymous")


class StatsRepository:
    """Repository for managing bot statistics."""

    def __init__(self, database: Database):
        """Initialize repository with database connection.

        Args:
            database: Database instance

        """
        self.db = database

    # === User tracking ===

    def track_user(
        self,
        user_id: int,
        username: str | None = None,
        display_name: str | None = None,
    ):
        """Track user activity (first seen or update last seen).

        Args:
            user_id: Telegram user ID
            username: Telegram username
            display_name: User display name (first + last) when known

        """
        try:
            existing = self.db.fetchone("SELECT user_id FROM users WHERE user_id = ?", (user_id,))

            if existing:
                if display_name is not None:
                    self.db.execute(
                        """UPDATE users
                           SET last_seen = CURRENT_TIMESTAMP, username = ?, display_name = ?
                           WHERE user_id = ?""",
                        (username, display_name, user_id),
                    )
                else:
                    self.db.execute(
                        """UPDATE users
                           SET last_seen = CURRENT_TIMESTAMP, username = ?
                           WHERE user_id = ?""",
                        (username, user_id),
                    )
            else:
                self.db.execute(
                    "INSERT INTO users (user_id, username, display_name) VALUES (?, ?, ?)",
                    (user_id, username, display_name),
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
        url: str | None = None,
        title: str | None = None,
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
            url: Source page URL when available
            title: Media title when available

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
            url=url,
            title=title,
        )

    def track_audio_download(
        self,
        user_id: int,
        audio_quality: str,
        username: str | None = None,
        success: bool = True,
        error_message: str | None = None,
        source: str = "dm",
        url: str | None = None,
        title: str | None = None,
    ):
        """Track an audio download event.

        Args:
            user_id: Telegram user ID
            audio_quality: Audio quality (e.g., 'high', 'medium', 'low')
            username: Telegram username
            success: Whether download was successful
            error_message: Error message if download failed
            source: Download source ('dm' or 'inline')
            url: Source page URL when available
            title: Media title when available

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
            url=url,
            title=title,
        )

    def track_tiktok_download(
        self,
        user_id: int,
        username: str | None = None,
        success: bool = True,
        error_message: str | None = None,
        source: str = "dm",
        url: str | None = None,
        title: str | None = None,
    ):
        """Track a TikTok download event.

        Args:
            user_id: Telegram user ID
            username: Telegram username
            success: Whether download was successful
            error_message: Error message if download failed
            source: Download source ('dm' or 'inline')
            url: Source page URL when available
            title: Media title when available

        """
        self._track_event(
            "tiktok_download",
            user_id,
            username,
            platform="tiktok",
            success=success,
            error_message=error_message,
            source=source,
            url=url,
            title=title,
        )

    def track_twitter_download(
        self,
        user_id: int,
        username: str | None = None,
        success: bool = True,
        error_message: str | None = None,
        source: str = "dm",
        url: str | None = None,
        title: str | None = None,
    ):
        """Track a Twitter/X download event.

        Args:
            user_id: Telegram user ID
            username: Telegram username
            success: Whether download was successful
            error_message: Error message if download failed
            source: Download source ('dm', 'inline' or 'group')
            url: Source page URL when available
            title: Media title when available

        """
        self._track_event(
            "twitter_download",
            user_id,
            username,
            platform="twitter",
            success=success,
            error_message=error_message,
            source=source,
            url=url,
            title=title,
        )

    def track_pinterest_download(
        self,
        user_id: int,
        username: str | None = None,
        success: bool = True,
        error_message: str | None = None,
        source: str = "dm",
        url: str | None = None,
        title: str | None = None,
    ):
        """Track a Pinterest download event.

        Args:
            user_id: Telegram user ID
            username: Telegram username
            success: Whether download was successful
            error_message: Error message if download failed
            source: Download source ('dm' or 'inline')
            url: Source page URL when available
            title: Media title when available

        """
        self._track_event(
            "pinterest_download",
            user_id,
            username,
            platform="pinterest",
            success=success,
            error_message=error_message,
            source=source,
            url=url,
            title=title,
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
        url: str | None = None,
        title: str | None = None,
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
            url: Source page URL when available
            title: Media title when available

        """
        try:
            self.db.execute(
                """INSERT INTO statistics
                   (event_type, user_id, username, video_format, platform, source,
                    success, error_message, url, title)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    event_type,
                    user_id,
                    username,
                    video_format,
                    platform,
                    source,
                    success,
                    error_message,
                    url,
                    title,
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
            "total_twitter": self._get_event_count("twitter_download", date_filter),
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
        """Get SQL date filter for the given period (MSK calendar boundaries).

        SQLite ``CURRENT_TIMESTAMP`` / stored timestamps are UTC. Playlist quotas
        and the UI talk in Moscow time, so "за день" means since midnight MSK —
        not a rolling 24h window from UTC ``now``.
        """
        if period == "day":
            start = datetime.now(MSK).replace(hour=0, minute=0, second=0, microsecond=0)
        elif period == "month":
            now = datetime.now(MSK)
            start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        else:
            return ""
        start_utc = start.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%d %H:%M:%S")
        return f"AND timestamp >= '{start_utc}'"

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

    def list_users(
        self, offset: int = 0, limit: int = 15, *, kind: str = "all"
    ) -> list[dict]:
        """Return users sorted by last_seen DESC with pagination.

        kind: ``all`` | ``known`` (username or display_name) | ``anonymous`` (neither).
        """
        where = self._users_kind_where(kind)
        try:
            rows = self.db.fetchall(
                f"""SELECT user_id, username, display_name, last_seen
                   FROM users
                   WHERE {where}
                   ORDER BY last_seen DESC
                   LIMIT ? OFFSET ?""",
                (limit, offset),
            )
            return [
                {
                    "id": row["user_id"],
                    "username": row["username"],
                    "display_name": row["display_name"],
                    "last_seen": row["last_seen"],
                }
                for row in rows or []
            ]
        except Exception as e:
            logger.error(f"Failed to list users (kind={kind}): {e}")
            return []

    def count_users(self, *, kind: str = "all") -> int:
        """Return number of tracked users, optionally filtered by kind."""
        where = self._users_kind_where(kind)
        try:
            row = self.db.fetchone(f"SELECT COUNT(*) FROM users WHERE {where}")
            return int(row[0]) if row else 0
        except Exception as e:
            logger.error(f"Failed to count users (kind={kind}): {e}")
            return 0

    @staticmethod
    def _users_kind_where(kind: str) -> str:
        known = (
            "("
            "(username IS NOT NULL AND TRIM(username) != '')"
            " OR "
            "(display_name IS NOT NULL AND TRIM(display_name) != '')"
            ")"
        )
        if kind == "known":
            return known
        if kind in {"anonymous", "anon"}:
            return f"NOT {known}"
        return "1=1"

    def get_user(self, user_id: int) -> dict | None:
        """Return one user row by id, or None."""
        try:
            row = self.db.fetchone(
                """SELECT user_id, username, display_name, last_seen
                   FROM users WHERE user_id = ?""",
                (user_id,),
            )
            if not row:
                return None
            return {
                "id": row["user_id"],
                "username": row["username"],
                "display_name": row["display_name"],
                "last_seen": row["last_seen"],
            }
        except Exception as e:
            logger.error(f"Failed to get user {user_id}: {e}")
            return None

    def list_user_downloads(self, user_id: int, offset: int = 0, limit: int = 10) -> list[dict]:
        """Return download events for a user, newest first."""
        try:
            placeholders = ", ".join("?" * len(DOWNLOAD_EVENT_TYPES))
            rows = self.db.fetchall(
                f"""SELECT id, event_type, platform, video_format, url, title,
                           success, timestamp, source
                    FROM statistics
                    WHERE user_id = ? AND event_type IN ({placeholders})
                    ORDER BY timestamp DESC, id DESC
                    LIMIT ? OFFSET ?""",
                (user_id, *DOWNLOAD_EVENT_TYPES, limit, offset),
            )
            return [
                {
                    "id": row["id"],
                    "event_type": row["event_type"],
                    "platform": row["platform"],
                    "video_format": row["video_format"],
                    "url": row["url"],
                    "title": row["title"],
                    "success": bool(row["success"]),
                    "timestamp": row["timestamp"],
                    "source": row["source"],
                }
                for row in rows or []
            ]
        except Exception as e:
            logger.error(f"Failed to list downloads for user {user_id}: {e}")
            return []

    def count_user_downloads(self, user_id: int) -> int:
        """Return total download events for a user (UI may cap at 50)."""
        try:
            placeholders = ", ".join("?" * len(DOWNLOAD_EVENT_TYPES))
            row = self.db.fetchone(
                f"""SELECT COUNT(*) FROM statistics
                    WHERE user_id = ? AND event_type IN ({placeholders})""",
                (user_id, *DOWNLOAD_EVENT_TYPES),
            )
            return int(row[0]) if row else 0
        except Exception as e:
            logger.error(f"Failed to count downloads for user {user_id}: {e}")
            return 0

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

    # === Bot config (limits) ===

    MAX_CONCURRENT_KEY = "max_concurrent_per_user"
    PLAYLIST_DAILY_LIMIT_KEY = "playlist_daily_limit"
    DEFAULT_PLAYLIST_DAILY_LIMIT = 50

    def get_bot_config_int(self, key: str, default: int) -> int:
        try:
            row = self.db.fetchone(
                "SELECT value FROM bot_config WHERE key = ?",
                (key,),
            )
            if not row or row[0] is None:
                return default
            return int(row[0])
        except Exception as e:
            logger.error(f"Failed to get bot_config key {key}: {e}")
            return default

    def set_bot_config_int(self, key: str, value: int) -> None:
        try:
            self.db.execute(
                """INSERT INTO bot_config(key, value) VALUES(?, ?)
                   ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
                (key, str(int(value))),
            )
        except Exception as e:
            logger.error(f"Failed to set bot_config key {key}: {e}")
            raise

    def get_playlist_daily_limit(self) -> int:
        return self.get_bot_config_int(
            self.PLAYLIST_DAILY_LIMIT_KEY,
            self.DEFAULT_PLAYLIST_DAILY_LIMIT,
        )

    def set_playlist_daily_limit(self, n: int) -> None:
        self.set_bot_config_int(self.PLAYLIST_DAILY_LIMIT_KEY, n)

    def get_max_concurrent(self, *, default: int = 1) -> int:
        """Return configured concurrent limit; do not write on read."""
        return self.get_bot_config_int(self.MAX_CONCURRENT_KEY, default)

    def set_max_concurrent(self, n: int) -> None:
        self.set_bot_config_int(self.MAX_CONCURRENT_KEY, n)

    def get_user_playlist_limit(self, user_id: int) -> int | None:
        try:
            row = self.db.fetchone(
                "SELECT daily_limit FROM user_playlist_limits WHERE user_id = ?",
                (user_id,),
            )
            if not row or row[0] is None:
                return None
            return int(row[0])
        except Exception as e:
            logger.error(f"Failed to get user playlist limit for {user_id}: {e}")
            return None

    def set_user_playlist_limit(self, user_id: int, n: int) -> None:
        try:
            self.db.execute(
                """INSERT INTO user_playlist_limits (user_id, daily_limit, updated_at)
                   VALUES (?, ?, CURRENT_TIMESTAMP)
                   ON CONFLICT(user_id) DO UPDATE SET
                     daily_limit = excluded.daily_limit,
                     updated_at = CURRENT_TIMESTAMP""",
                (user_id, int(n)),
            )
        except Exception as e:
            logger.error(f"Failed to set user playlist limit for {user_id}: {e}")
            raise

    def clear_user_playlist_limit(self, user_id: int) -> None:
        try:
            self.db.execute(
                "DELETE FROM user_playlist_limits WHERE user_id = ?",
                (user_id,),
            )
        except Exception as e:
            logger.error(f"Failed to clear user playlist limit for {user_id}: {e}")
            raise

    def get_playlist_usage(self, user_id: int, day: str | None = None) -> int:
        day_key = day if day is not None else today_msk()
        try:
            row = self.db.fetchone(
                "SELECT count FROM playlist_usage WHERE user_id = ? AND day = ?",
                (user_id, day_key),
            )
            if not row or row[0] is None:
                return 0
            return int(row[0])
        except Exception as e:
            logger.error(f"Failed to get playlist usage for {user_id} on {day_key}: {e}")
            return 0

    def increment_playlist_usage(self, user_id: int, amount: int = 1) -> None:
        day_key = today_msk()
        try:
            self.db.execute(
                """INSERT INTO playlist_usage (user_id, day, count)
                   VALUES (?, ?, ?)
                   ON CONFLICT(user_id, day) DO UPDATE SET
                     count = count + excluded.count""",
                (user_id, day_key, int(amount)),
            )
        except Exception as e:
            logger.error(f"Failed to increment playlist usage for {user_id}: {e}")
            raise

    def effective_playlist_limit(
        self, user_id: int, *, is_admin: bool, is_unlimited: bool = False
    ) -> int | None:
        if is_admin or is_unlimited:
            return None
        user_limit = self.get_user_playlist_limit(user_id)
        if user_limit is not None:
            return user_limit
        return self.get_playlist_daily_limit()

    def remaining_playlist_quota(
        self, user_id: int, *, is_admin: bool, is_unlimited: bool = False
    ) -> int | None:
        effective = self.effective_playlist_limit(
            user_id, is_admin=is_admin, is_unlimited=is_unlimited
        )
        if effective is None:
            return None
        usage = self.get_playlist_usage(user_id)
        return max(0, effective - usage)

    # === User bans ===

    def get_ban(self, user_id: int) -> str | None:
        """Return ban reason for user_id or None if not banned."""
        try:
            row = self.db.fetchone(
                "SELECT reason FROM user_bans WHERE user_id = ?",
                (user_id,),
            )
            if not row or row[0] is None:
                return None
            return str(row[0])
        except Exception as e:
            logger.error(f"Failed to get ban for {user_id}: {e}")
            return None

    def is_banned(self, user_id: int) -> bool:
        """Return whether user_id is currently banned."""
        return self.get_ban(user_id) is not None

    def ban_user(self, user_id: int, reason: str, banned_by: int | None = None) -> None:
        """Ban user or update reason on re-ban."""
        try:
            self.db.execute(
                """INSERT INTO user_bans (user_id, reason, banned_by, created_at)
                   VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                   ON CONFLICT(user_id) DO UPDATE SET
                     reason = excluded.reason,
                     banned_by = excluded.banned_by,
                     created_at = CURRENT_TIMESTAMP""",
                (user_id, reason, banned_by),
            )
        except Exception as e:
            logger.error(f"Failed to ban user {user_id}: {e}")
            raise

    def unban_user(self, user_id: int) -> bool:
        """Remove ban. Returns True if a row was deleted."""
        try:
            cursor = self.db.execute(
                "DELETE FROM user_bans WHERE user_id = ?",
                (user_id,),
            )
            return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Failed to unban user {user_id}: {e}")
            raise

    def count_bans(self) -> int:
        """Return total number of active bans."""
        try:
            row = self.db.fetchone("SELECT COUNT(*) FROM user_bans")
            return int(row[0]) if row else 0
        except Exception as e:
            logger.error(f"Failed to count bans: {e}")
            return 0
