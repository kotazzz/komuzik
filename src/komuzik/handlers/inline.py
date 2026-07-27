"""Inline query and chosen-result download flows."""

import asyncio
import logging
import uuid
from typing import cast

from telethon import Button
from telethon.errors import QueryIdInvalidError
from telethon.tl.types import UpdateBotInlineSend

from ..config import DOWNLOAD_TIMEOUT_SECONDS
from ..downloaders import (
    download_hls_host_video,
    download_pinterest_content,
    download_tiktok_video,
    download_twitter_video,
    download_youtube_audio,
    download_youtube_video,
    search_youtube,
)
from ..i18n import t
from ..inline_media import (
    PM_UNAVAILABLE_MESSAGE,
    delete_staging_message,
    edit_inline_text,
    edit_inline_with_media,
    is_pm_unavailable_error,
    stage_media_to_user,
)
from ..inline_query import ParsedInlineQuery, parse_inline_query
from ..storage import delete_staging, stage_media
from ..user_errors import format_download_error
from .common import INLINE_JOBS, INLINE_SEARCH_MAX, _entity_display_name, format_ban_message, media_title

logger = logging.getLogger(__name__)

class InlineMixin:
    """Mixin for BotHandlers."""

    async def _safe_inline_answer(self, event, articles: list) -> None:
        """Answer inline query; ignore stale query_id and log other failures."""
        # Note: no thumbs/gallery here — preview collage exists only in DM /search.
        try:
            await event.answer(articles, cache_time=0)
        except QueryIdInvalidError:
            logger.info("Inline answer skipped: query_id already invalid (user typed further)")
        except Exception as e:
            logger.warning(f"Inline answer failed: {e}")

    async def inline_query_handler(self, event):
        """Answer inline queries: URL download or YouTube text search.

        Keep this path fast: Telegram cancels unanswered queries in ~1-2s while typing.
        No preview/thumbs in inline — use /search in DM for Pillow preview.
        """
        t0 = asyncio.get_running_loop().time()
        query_text = event.text or ""
        user_id = cast("int | None", event.sender_id)
        logger.info(f"Inline query user={user_id} text={query_text!r}")

        try:
            if user_id is not None and not self._is_bot_admin(user_id):
                reason = self.stats.get_ban(user_id)
                if reason is not None:
                    builder = event.builder
                    blocked = await builder.article(
                        title=t("inline.access_restricted"),
                        description=reason[:64],
                        text=format_ban_message(reason),
                        id="banned",
                    )
                    await self._safe_inline_answer(event, [blocked])
                    return

            default_quality = "720p"
            if user_id is not None:
                try:
                    default_quality = self.stats.get_user_settings(user_id).default_quality
                except Exception:
                    pass

            parsed = parse_inline_query(query_text, default_quality=default_quality)
            builder = event.builder

            # --- URL / link path: answer immediately ---
            if parsed:
                token = uuid.uuid4().hex[:16]
                INLINE_JOBS[token] = parsed
                result = await builder.article(
                    title=parsed.description[:64],
                    description=(parsed.url[:64] if parsed.url else parsed.description),
                    text=t("common.loading"),
                    buttons=[Button.inline("⏳", b"noop")],
                    id=token,
                )
                await self._safe_inline_answer(event, [result])
                logger.info(
                    f"Inline URL answered in {asyncio.get_running_loop().time() - t0:.2f}s"
                )
                return

            query = query_text.strip()
            if not query:
                hint = await builder.article(
                    title=t("inline.hint_title"),
                    description=t("inline.hint_description"),
                    text=t("inline.hint_text"),
                    buttons=[Button.inline("⏳", b"noop")],
                    id="hint",
                )
                await self._safe_inline_answer(event, [hint])
                return

            # Too-short queries: don't hit YouTube on every keystroke
            if len(query) < 3:
                hint = await builder.article(
                    title=t("inline.short_title"),
                    description=t("inline.short_description"),
                    text=t("inline.short_text"),
                    id="hint_short",
                )
                await self._safe_inline_answer(event, [hint])
                return

            if user_id is not None:
                try:
                    sender = getattr(event, "sender", None)
                    username = getattr(sender, "username", None) if sender else None
                    self.stats.track_user(user_id, username)
                    self.stats.track_search(user_id, username)
                except Exception:
                    pass

            try:
                results = await asyncio.wait_for(
                    search_youtube(query, max_results=INLINE_SEARCH_MAX),
                    timeout=2.8,
                )
            except TimeoutError:
                logger.warning(f"Inline search timeout query={query!r}")
                slow = await builder.article(
                    title=t("inline.timeout_title"),
                    description=t("inline.timeout_description"),
                    text=t("inline.timeout_text"),
                    id="search_timeout",
                )
                await self._safe_inline_answer(event, [slow])
                return

            if not results:
                empty = await builder.article(
                    title=t("inline.empty_title"),
                    description=t("inline.empty_description"),
                    text=t("inline.empty_text"),
                    id="search_empty",
                )
                await self._safe_inline_answer(event, [empty])
                return

            articles = []
            for item in results:
                url = str(item.get("url") or "")
                job = parse_inline_query(url, default_quality=default_quality)
                if job is None:
                    continue
                token = uuid.uuid4().hex[:16]
                INLINE_JOBS[token] = job

                title = str(item.get("title") or t("common.untitled"))
                if len(title) > 64:
                    title = title[:61] + "..."

                duration = int(item["duration"]) if item.get("duration") else 0
                duration_label = (
                    f"{duration // 60}:{duration % 60:02d}" if duration else "?:??"
                )
                channel = str(item.get("channel") or "")
                description = " · ".join(
                    p for p in (channel, duration_label, default_quality) if p
                )[:64]

                articles.append(
                    await builder.article(
                        title=title,
                        description=description,
                        text=t("common.loading"),
                        buttons=[Button.inline("⏳", b"noop")],
                        id=token,
                    )
                )

            if not articles:
                empty = await builder.article(
                    title=t("inline.empty_title"),
                    description=t("inline.empty_description"),
                    text=t("inline.empty_text"),
                    id="search_empty",
                )
                await self._safe_inline_answer(event, [empty])
                return

            await self._safe_inline_answer(event, articles)
            logger.info(
                f"Inline search answered n={len(articles)} "
                f"in {asyncio.get_running_loop().time() - t0:.2f}s query={query!r}"
            )
        except QueryIdInvalidError:
            logger.info("Inline handler: stale query_id")
        except Exception:
            logger.exception(f"Inline handler crashed text={query_text!r}")
            try:
                fail = await event.builder.article(
                    title=t("inline.error_title"),
                    description=t("inline.error_description"),
                    text=t("inline.error_text"),
                    id="inline_crash",
                )
                await self._safe_inline_answer(event, [fail])
            except Exception:
                pass

    async def chosen_inline_handler(self, event: UpdateBotInlineSend):
        """Download media after user picks an inline result and edit the via-message."""
        token = event.id
        inline_msg_id = event.msg_id
        user_id = event.user_id

        if not self._is_bot_admin(user_id):
            reason = self.stats.get_ban(user_id)
            if reason is not None and inline_msg_id is not None:
                await edit_inline_text(
                    self.client, inline_msg_id, format_ban_message(reason)
                )
                return

        parsed = INLINE_JOBS.pop(token, None)

        if parsed is None:
            logger.warning(f"Unknown inline job token: {token}")
            return

        if inline_msg_id is None:
            logger.warning("Chosen inline result without msg_id (enable /setinlinefeedback)")
            return

        username = None
        display_name = None
        try:
            user = await self.client.get_entity(user_id)
            username = getattr(user, "username", None)
            display_name = _entity_display_name(user)
        except Exception:
            pass

        self.stats.track_user(user_id, username, display_name=display_name)

        download_id = str(uuid.uuid4())
        if not await self.download_limiter.start_download(user_id, download_id):
            active_count = self.download_limiter.get_active_count(user_id)
            await edit_inline_text(
                self.client,
                inline_msg_id,
                t(
                    "download.active_limit_short",
                    active=active_count,
                    max=self.download_limiter.MAX_DOWNLOADS_PER_USER,
                ),
            )
            return

        file_path = None
        try:
            await edit_inline_text(self.client, inline_msg_id, t("common.loading"))
            file_path, metadata, media_kind = await self._download_for_inline(parsed)
            storage_chat_id = self.stats.get_storage_chat_id()
            if storage_chat_id is not None:
                staging_msg = await stage_media(
                    self.client,
                    storage_chat_id,
                    file_path,
                    media_kind,
                    metadata,
                    self.bot_username,
                    **self._caption_kwargs(user_id),
                )
                try:
                    await edit_inline_with_media(self.client, inline_msg_id, staging_msg)
                    self._track_inline_download(
                        parsed, user_id, username, success=True, metadata=metadata
                    )
                finally:
                    await delete_staging(self.client, storage_chat_id, [staging_msg])
            else:
                try:
                    staging_msg = await stage_media_to_user(
                        self.client,
                        user_id,
                        file_path,
                        media_kind,
                        metadata,
                        self.bot_username,
                        **self._caption_kwargs(user_id),
                    )
                except Exception as e:
                    if is_pm_unavailable_error(e):
                        await edit_inline_text(self.client, inline_msg_id, PM_UNAVAILABLE_MESSAGE)
                        self._track_inline_download(
                            parsed,
                            user_id,
                            username,
                            success=False,
                            error_message=str(e),
                        )
                        return
                    raise

                await edit_inline_with_media(self.client, inline_msg_id, staging_msg)
                await delete_staging_message(self.client, user_id, staging_msg)
                self._track_inline_download(
                    parsed, user_id, username, success=True, metadata=metadata
                )

        except Exception as e:
            logger.error(f"Inline download failed for {parsed.url}: {e}")
            try:
                await edit_inline_text(
                    self.client,
                    inline_msg_id,
                    format_download_error(e, context=t("download.failed_context")),
                )
            except Exception as edit_error:
                logger.error(f"Failed to edit inline error text: {edit_error}")
            self._track_inline_download(
                parsed, user_id, username, success=False, error_message=str(e)
            )
        finally:
            if file_path:
                self._cleanup_download_file(file_path)
            await self.download_limiter.finish_download(user_id, download_id)

    async def _download_for_inline(self, parsed: ParsedInlineQuery) -> tuple[str, dict, str]:
        """Download media for an inline job. Returns (path, metadata, media_kind)."""
        if parsed.platform == "youtube" and parsed.mode == "audio":
            file_path, metadata = await self._bounded(
                download_youtube_audio(parsed.url, parsed.quality)
            )
            return file_path, metadata, "audio"

        if parsed.platform in {"youtube", "youtube_shorts"}:
            quality = parsed.quality if parsed.platform == "youtube" else "best"
            file_path, metadata = await self._bounded(
                download_youtube_video(parsed.url, quality)
            )
            return file_path, metadata, "video"

        if parsed.platform == "tiktok":
            file_path, metadata = await self._bounded(download_tiktok_video(parsed.url))
            return file_path, metadata, "video"

        if parsed.platform == "twitter":
            file_path, metadata = await self._bounded(download_twitter_video(parsed.url))
            kind = "photo" if metadata.get("content_type") == "photo" else "video"
            return file_path, metadata, kind

        if parsed.platform == "pinterest":
            file_path, metadata = await self._bounded(download_pinterest_content(parsed.url))
            kind = "photo" if metadata.get("content_type") == "photo" else "video"
            return file_path, metadata, kind

        if parsed.platform == "hls_host":
            file_path, metadata = await self._bounded(download_hls_host_video(parsed.url))
            return file_path, metadata, "video"

        raise ValueError(f"Unsupported platform: {parsed.platform}")

    def _track_inline_download(
        self,
        parsed: ParsedInlineQuery,
        user_id: int,
        username: str | None,
        *,
        success: bool,
        error_message: str | None = None,
        metadata: dict | None = None,
    ):
        """Record inline download stats with source=inline."""
        self._track_parsed_download(
            parsed,
            user_id,
            username,
            success=success,
            error_message=error_message,
            source="inline",
            metadata=metadata,
        )

    def _track_parsed_download(
        self,
        parsed: ParsedInlineQuery,
        user_id: int,
        username: str | None,
        *,
        success: bool,
        source: str,
        error_message: str | None = None,
        metadata: dict | None = None,
    ):
        """Record download stats for a parsed media link."""
        title = media_title(metadata) or parsed.description
        if parsed.platform == "youtube" and parsed.mode == "audio":
            self.stats.track_audio_download(
                user_id,
                parsed.quality,
                username,
                success=success,
                error_message=error_message,
                source=source,
                url=parsed.url,
                title=title,
            )
        elif parsed.platform in {"youtube", "youtube_shorts"}:
            platform = "youtube_shorts" if parsed.platform == "youtube_shorts" else "youtube"
            self.stats.track_video_download(
                user_id,
                parsed.quality,
                platform,
                username,
                success=success,
                error_message=error_message,
                source=source,
                url=parsed.url,
                title=title,
            )
        elif parsed.platform == "pinterest":
            self.stats.track_pinterest_download(
                user_id,
                username,
                success=success,
                error_message=error_message,
                source=source,
                url=parsed.url,
                title=title,
            )
        elif parsed.platform == "hls_host":
            self.stats.track_video_download(
                user_id,
                parsed.quality,
                "hls_host",
                username,
                success=success,
                error_message=error_message,
                source=source,
                url=parsed.url,
                title=title,
            )
        elif parsed.platform == "twitter":
            self.stats.track_twitter_download(
                user_id,
                username,
                success=success,
                error_message=error_message,
                source=source,
                url=parsed.url,
                title=title,
            )
        else:
            self.stats.track_tiktok_download(
                user_id,
                username,
                success=success,
                error_message=error_message,
                source=source,
                url=parsed.url,
                title=title,
            )
