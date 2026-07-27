"""YouTube playlist preview and batch download."""

import asyncio
import logging
import uuid
from typing import Any, cast

from telethon import Button
from telethon.tl.custom import Message

from ..downloaders import (
    download_hls_host_video,
    download_pinterest_content,
    download_tiktok_video,
    download_twitter_video,
    download_youtube_audio,
    download_youtube_video,
    enrich_youtube_search_stats,
    probe_media_for_playlist,
    send_audio_content,
    send_image_content,
    send_playlist_album,
    send_video_content,
)
from ..i18n import t
from ..link_extract import ParsedLink
from ..playlist import (
    MIX_YT_ONLY,
    PLAYLIST_BATCH_SIZE,
    PLAYLIST_MAX_ENTRIES,
    PLAYLIST_PAGE_SIZE,
    PlaylistEntry,
    PlaylistSession,
    classify_mix_kind,
    entry_to_collage_item,
    extract_playlist,
    format_preview_page,
    parse_exclusion_ops,
    selected_entries,
)
from ..search_preview import render_search_preview_async
from ..storage import PartialCopyError, copy_messages_to_chat, delete_staging, stage_media
from .common import PLAYLIST_STATES, media_title

logger = logging.getLogger(__name__)

class PlaylistMixin:
    """Mixin for BotHandlers."""

    def _playlist_buttons(self, session: PlaylistSession) -> list:
        total = len(session.entries)
        pages = max(1, (total + PLAYLIST_PAGE_SIZE - 1) // PLAYLIST_PAGE_SIZE)
        selected = total - len(session.excluded)
        nav: list = []
        if session.page > 0:
            nav.append(Button.inline("⬅️", data="pl_prev"))
        if session.page < pages - 1:
            nav.append(Button.inline("➡️", data="pl_next"))
        rows: list = []
        if nav:
            rows.append(nav)

        kind = session.mix_kind
        if kind == MIX_YT_ONLY:
            rows.append(
                [
                    Button.inline(t("playlist.buttons.video"), data="pl_video"),
                    Button.inline(t("playlist.buttons.audio"), data="pl_audio"),
                ]
            )
            settings = self.stats.get_user_settings(session.user_id)
            if settings.last_mode and settings.last_quality:
                mode_label = (
                    t("download.mode.audio")
                    if settings.last_mode == "audio"
                    else t("download.mode.video")
                )
                rows.append(
                    [
                        Button.inline(
                            t(
                                "playlist.buttons.repeat",
                                mode=mode_label,
                                quality=settings.last_quality,
                            ),
                            data="pl_repeat",
                        )
                    ]
                )
        else:
            # non_yt_only / mixed — single download (no quality grid)
            rows.append(
                [
                    Button.inline(
                        t("playlist.buttons.download", count=selected),
                        data="pl_download",
                    )
                ]
            )

        rows.append([Button.inline(t("playlist.buttons.preview"), data="pl_preview")])
        return rows

    async def _start_playlist_session(
        self, event: Message, user_id: int, url: str, is_music: bool
    ) -> None:
        """Load playlist and show first preview page."""
        status = await event.respond(t("playlist.reading"))
        try:
            title, entries, truncated = await extract_playlist(url, is_music=is_music)
        except Exception as e:
            logger.error(f"Playlist extract failed: {e}")
            await event.respond(t("playlist.open_failed", error=str(e)))
            try:
                await status.delete()
            except Exception:
                pass
            return

        if not entries:
            await event.respond(t("playlist.empty"))
            try:
                await status.delete()
            except Exception:
                pass
            return

        settings = self.stats.get_user_settings(user_id)
        session = PlaylistSession(
            user_id=user_id,
            playlist_url=url,
            title=title,
            is_music=is_music,
            entries=entries,
            truncated=truncated,
            source="youtube_playlist",
            mix_kind=MIX_YT_ONLY,
            default_quality=settings.default_quality or "720p",
        )
        PLAYLIST_STATES[user_id] = session
        text = format_preview_page(session)
        try:
            await status.edit(text, buttons=self._playlist_buttons(session), link_preview=False)
            session.preview_msg_id = int(status.id)
        except Exception:
            msg = await event.respond(
                text, buttons=self._playlist_buttons(session), link_preview=False
            )
            session.preview_msg_id = int(msg.id)

    async def _start_multi_link_session(
        self, event: Message, user_id: int, links: list[ParsedLink]
    ) -> None:
        """Build a synthetic playlist from multiple media URLs."""
        status = await event.respond(t("playlist.reading_links"))
        capped = links[:PLAYLIST_MAX_ENTRIES]
        truncated = len(links) > PLAYLIST_MAX_ENTRIES

        async def _one(i: int, link: ParsedLink) -> PlaylistEntry:
            return await probe_media_for_playlist(
                link.url, platform=link.platform, index=i + 1
            )

        try:
            entries = list(
                await asyncio.gather(
                    *[_one(i, link) for i, link in enumerate(capped)]
                )
            )
        except Exception as e:
            logger.error(f"Multi-link probe failed: {e}")
            await event.respond(t("playlist.open_failed", error=str(e)))
            try:
                await status.delete()
            except Exception:
                pass
            return

        if not entries:
            await event.respond(t("playlist.multi_empty"))
            try:
                await status.delete()
            except Exception:
                pass
            return

        settings = self.stats.get_user_settings(user_id)
        mix_kind = classify_mix_kind(entries)
        session = PlaylistSession(
            user_id=user_id,
            playlist_url="multi_links",
            title=t("playlist.multi_title", count=len(entries)),
            is_music=False,
            entries=entries,
            truncated=truncated,
            source="multi_links",
            mix_kind=mix_kind,
            default_quality=settings.default_quality or "720p",
        )
        PLAYLIST_STATES[user_id] = session
        text = format_preview_page(session)
        try:
            await status.edit(text, buttons=self._playlist_buttons(session), link_preview=False)
            session.preview_msg_id = int(status.id)
        except Exception:
            msg = await event.respond(
                text, buttons=self._playlist_buttons(session), link_preview=False
            )
            session.preview_msg_id = int(msg.id)

    async def _maybe_handle_playlist_exclusion_reply(
        self, event: Message, message_obj: Any, user_id: int
    ) -> bool:
        """If user replies to playlist preview with exclusion ops, apply them."""
        session = PLAYLIST_STATES.get(user_id)
        if session is None or session.preview_msg_id is None:
            return False
        if bool(getattr(event, "is_group", False)):
            return False

        reply = getattr(message_obj, "reply_to", None) if message_obj is not None else None
        reply_id = getattr(reply, "reply_to_msg_id", None) if reply is not None else None
        if reply_id != session.preview_msg_id:
            return False

        text = None
        if message_obj is not None:
            text = getattr(message_obj, "raw_text", None) or getattr(message_obj, "message", None)
            if not isinstance(text, str):
                text = getattr(message_obj, "text", None)
        if not isinstance(text, str):
            return False

        new_excluded = parse_exclusion_ops(text, len(session.entries), session.excluded)
        if new_excluded is None:
            await event.respond(
                t("playlist.exclusion_help"),
                reply_to=session.preview_msg_id,
            )
            return True

        session.excluded = new_excluded
        try:
            await self.client.edit_message(
                event.chat_id,
                session.preview_msg_id,
                format_preview_page(session),
                buttons=self._playlist_buttons(session),
                link_preview=False,
            )
        except Exception as e:
            logger.error(f"Failed to update playlist preview: {e}")
        try:
            await message_obj.delete()
        except Exception:
            pass
        return True

    async def _refresh_playlist_preview(self, event, session: PlaylistSession) -> None:
        text = format_preview_page(session)
        buttons = self._playlist_buttons(session)
        try:
            await event.edit(text, buttons=buttons, link_preview=False)
        except Exception as e:
            logger.error(f"Failed to refresh playlist preview: {e}")

    async def _handle_playlist_callback(self, event, data: str) -> None:
        """Pagination / type / quality / download for playlist session."""
        user_id = cast("int | None", event.sender_id)
        if user_id is None:
            await event.answer()
            return
        session = PLAYLIST_STATES.get(user_id)
        if session is None:
            await event.answer(t("playlist.session_expired"), alert=True)
            return

        if data == "pl_stop":
            session.cancel_requested = True
            await event.answer(t("playlist.stopping"))
            return

        if data == "pl_download":
            if session.mix_kind == MIX_YT_ONLY:
                await event.answer(t("playlist.hint"), alert=True)
                return
            await event.answer(
                t("playlist.downloading_video", quality=session.default_quality)
            )
            await self._download_playlist(
                event, session, mode="video", quality=session.default_quality
            )
            return

        if data == "pl_repeat":
            if session.mix_kind != MIX_YT_ONLY:
                await event.answer()
                return
            settings = self.stats.get_user_settings(user_id)
            if not settings.last_mode or not settings.last_quality:
                await event.answer(t("playlist.preview.no_last_format"), alert=True)
                return
            mode = settings.last_mode
            quality = settings.last_quality
            key = (
                "playlist.downloading_audio"
                if mode == "audio"
                else "playlist.downloading_video"
            )
            await event.answer(t(key, quality=quality))
            await self._download_playlist(event, session, mode=mode, quality=quality)
            return

        if data == "pl_preview":
            await self._send_playlist_collage(event, session)
            return

        if data == "pl_prev":
            session.page = max(0, session.page - 1)
            await self._refresh_playlist_preview(event, session)
            await event.answer()
            return

        if data == "pl_next":
            pages = max(
                1, (len(session.entries) + PLAYLIST_PAGE_SIZE - 1) // PLAYLIST_PAGE_SIZE
            )
            session.page = min(pages - 1, session.page + 1)
            await self._refresh_playlist_preview(event, session)
            await event.answer()
            return

        if data == "pl_video":
            if session.mix_kind != MIX_YT_ONLY:
                await event.answer()
                return
            buttons = [
                [
                    Button.inline("360p", data="pl_vq_360p"),
                    Button.inline("480p", data="pl_vq_480p"),
                ],
                [
                    Button.inline("720p", data="pl_vq_720p"),
                    Button.inline("1080p", data="pl_vq_1080p"),
                ],
                [Button.inline(t("common.back"), data="pl_back")],
            ]
            await event.edit(
                t(
                    "playlist.quality_video",
                    title=session.title,
                    count=len(selected_entries(session)),
                ),
                buttons=buttons,
            )
            await event.answer()
            return

        if data == "pl_audio":
            if session.mix_kind != MIX_YT_ONLY:
                await event.answer()
                return
            buttons = [
                [
                    Button.inline(t("playlist.buttons.quality_high"), data="pl_aq_high"),
                    Button.inline(t("playlist.buttons.quality_medium"), data="pl_aq_medium"),
                ],
                [Button.inline(t("playlist.buttons.quality_low"), data="pl_aq_low")],
                [Button.inline(t("common.back"), data="pl_back")],
            ]
            await event.edit(
                t(
                    "playlist.quality_audio",
                    title=session.title,
                    count=len(selected_entries(session)),
                ),
                buttons=buttons,
            )
            await event.answer()
            return

        if data == "pl_back":
            await self._refresh_playlist_preview(event, session)
            await event.answer()
            return

        if data.startswith("pl_vq_"):
            quality = data.removeprefix("pl_vq_")
            await event.answer(t("playlist.downloading_video", quality=quality))
            await self._download_playlist(event, session, mode="video", quality=quality)
            return

        if data.startswith("pl_aq_"):
            quality = data.removeprefix("pl_aq_")
            await event.answer(t("playlist.downloading_audio", quality=quality))
            await self._download_playlist(event, session, mode="audio", quality=quality)
            return

        await event.answer()

    async def _download_playlist(
        self, event, session: PlaylistSession, *, mode: str, quality: str
    ) -> None:
        """Download in batches of 10; progress per file; video albums / audio singles."""
        user_id = session.user_id
        username = None
        try:
            sender = await event.get_sender()
            username = getattr(sender, "username", None)
        except Exception:
            pass

        entries = selected_entries(session)
        if not entries:
            await event.edit(t("playlist.nothing_to_download"))
            return

        is_admin = user_id in self.download_limiter.ADMIN_USER_IDS
        is_unlimited = user_id in self.download_limiter.UNLIMITED_USER_IDS
        remaining = self.stats.remaining_playlist_quota(
            user_id, is_admin=is_admin, is_unlimited=is_unlimited
        )
        if remaining is not None and len(entries) > remaining:
            await event.edit(
                t(
                    "playlist.quota_exceeded",
                    selected=len(entries),
                    remaining=remaining,
                )
            )
            return

        download_id = str(uuid.uuid4())
        if not await self._check_download_limit(event, user_id, download_id):
            return

        session.downloading = True
        session.cancel_requested = False
        total = len(entries)
        done = 0
        fail = 0
        sent = 0
        caption_kw = self._caption_kwargs(user_id)
        stop_btn = [[Button.inline(t("common.stop"), data="pl_stop")]]

        def quota_status() -> str:
            if is_admin or is_unlimited:
                return ""
            limit = self.stats.effective_playlist_limit(
                user_id, is_admin=False, is_unlimited=False
            )
            if limit is None:
                return ""
            used = self.stats.get_playlist_usage(user_id)
            return t("playlist.quota_suffix", used=used, limit=limit)

        async def update_progress(text: str) -> None:
            try:
                await event.edit(text, buttons=stop_btn, link_preview=False)
            except Exception:
                try:
                    await event.respond(text, buttons=stop_btn, link_preview=False)
                except Exception:
                    pass

        await update_progress(
            t(
                "playlist.progress_start",
                title=session.title,
                total=total,
                quota=quota_status(),
                mode=mode,
                quality=quality,
            )
        )

        batch: list[tuple[str, dict]] = []
        cancelled = False
        storage_chat_id = self.stats.get_storage_chat_id() if mode == "audio" else None
        use_storage = mode == "audio" and storage_chat_id is not None

        async def flush_batch() -> None:
            nonlocal sent, batch
            if not batch:
                return
            paths = [p for p, _ in batch]
            if use_storage:
                staging: list = []
                try:
                    for path, metadata in batch:
                        msg = await stage_media(
                            self.client,
                            storage_chat_id,
                            path,
                            "audio",
                            metadata,
                            self.bot_username,
                            **caption_kw,
                        )
                        staging.append(msg)
                    remaining = [
                        m
                        for m in staging
                        if m is not None and getattr(m, "media", None) is not None
                    ]
                    delivered = 0
                    try:
                        delivered += await copy_messages_to_chat(
                            self.client, event.chat_id, remaining
                        )
                        remaining = []
                    except PartialCopyError as e:
                        delivered += e.sent
                        remaining = remaining[e.sent:]
                        try:
                            delivered += await copy_messages_to_chat(
                                self.client, event.chat_id, remaining
                            )
                            remaining = []
                        except PartialCopyError as e2:
                            delivered += e2.sent
                            remaining = remaining[e2.sent:]
                            for msg in remaining:
                                try:
                                    delivered += await copy_messages_to_chat(
                                        self.client, event.chat_id, [msg]
                                    )
                                except PartialCopyError as e3:
                                    if e3.sent:
                                        delivered += e3.sent
                                    logger.error(
                                        "Playlist track delivery failed after retries: %s",
                                        e3.__cause__,
                                    )
                    if delivered:
                        sent += delivered
                        self.stats.set_user_last_format(user_id, "audio", quality)
                        if not is_admin:
                            self.stats.increment_playlist_usage(user_id, delivered)
                except Exception as e:
                    logger.error(f"Playlist batch send failed: {e}")
                    try:
                        await event.respond(
                            t("playlist.batch_send_failed", count=len(batch), error=str(e))
                        )
                    except Exception:
                        pass
                finally:
                    await delete_staging(self.client, storage_chat_id, staging)
                    for path in paths:
                        self._cleanup_download_file(path)
                    batch = []
                return
            try:
                await send_playlist_album(
                    self.client,
                    event.chat_id,
                    batch,
                    mode=mode,
                    bot_username=self.bot_username,
                    **caption_kw,
                )
                sent += len(batch)
                if not is_admin:
                    self.stats.increment_playlist_usage(user_id, len(batch))
                if mode == "audio":
                    self.stats.set_user_last_format(user_id, "audio", quality)
                else:
                    self.stats.set_user_last_format(user_id, "video", quality)
            except Exception as e:
                logger.error(f"Playlist batch send failed: {e}")
                try:
                    await event.respond(
                        t("playlist.batch_send_failed", count=len(batch), error=str(e))
                    )
                except Exception:
                    pass
            finally:
                for path in paths:
                    self._cleanup_download_file(path)
                batch = []

        try:
            for i, entry in enumerate(entries, start=1):
                if session.cancel_requested:
                    cancelled = True
                    break

                safe_title = entry.title.replace("[", "(").replace("]", ")")[:70]
                await update_progress(
                    t(
                        "playlist.progress_current",
                        title=session.title,
                        done=done,
                        total=total,
                        sent=sent,
                        fail=fail,
                        quota=quota_status(),
                        mode=mode,
                        quality=quality,
                        item_title=safe_title,
                        url=entry.url,
                        index=i,
                    )
                )

                file_path = None
                try:
                    # Non-YouTube items cannot join a YT album batch — flush first.
                    if entry.platform != "youtube" and batch:
                        batch_progress = t("playlist.batch_sending", count=len(batch))
                        await update_progress(
                            t(
                                "playlist.progress_batch",
                                title=session.title,
                                done=done,
                                total=total,
                                batch_progress=batch_progress,
                            )
                        )
                        await flush_batch()

                    file_path, metadata, media_kind = await self._download_playlist_entry(
                        entry, mode=mode, quality=quality
                    )
                    self._track_playlist_entry(
                        entry,
                        user_id=user_id,
                        username=username,
                        mode=mode,
                        quality=quality,
                        success=True,
                        metadata=metadata,
                    )

                    if entry.platform != "youtube":
                        await self._send_single_playlist_item(
                            event, file_path, metadata, media_kind, caption_kw
                        )
                        self._cleanup_download_file(file_path)
                        file_path = None
                        sent += 1
                        if not is_admin:
                            self.stats.increment_playlist_usage(user_id, 1)
                    else:
                        batch.append((file_path, metadata))
                        file_path = None

                    done += 1

                    await update_progress(
                        t(
                            "playlist.progress_downloaded",
                            title=session.title,
                            done=done,
                            total=total,
                            sent=sent,
                            fail=fail,
                            quota=quota_status(),
                            mode=mode,
                            quality=quality,
                            item_title=safe_title,
                            url=entry.url,
                            batch_size=len(batch),
                            batch_max=PLAYLIST_BATCH_SIZE,
                        )
                    )
                except Exception as e:
                    fail += 1
                    logger.error(f"Playlist item failed {entry.url}: {e}")
                    self._track_playlist_entry(
                        entry,
                        user_id=user_id,
                        username=username,
                        mode=mode,
                        quality=quality,
                        success=False,
                        error_message=str(e),
                    )
                    try:
                        await event.respond(
                            t(
                                "playlist.skip_item",
                                index=i,
                                total=total,
                                title=safe_title,
                                error=str(e),
                            )
                        )
                    except Exception:
                        pass
                finally:
                    if file_path:
                        self._cleanup_download_file(file_path)

                if len(batch) >= PLAYLIST_BATCH_SIZE:
                    batch_progress = (
                        t("playlist.batch_from_storage", count=len(batch))
                        if use_storage
                        else t("playlist.batch_sending", count=len(batch))
                    )
                    await update_progress(
                        t(
                            "playlist.progress_batch",
                            title=session.title,
                            done=done,
                            total=total,
                            batch_progress=batch_progress,
                        )
                    )
                    await flush_batch()
                    await update_progress(
                        t(
                            "playlist.progress_after_batch",
                            title=session.title,
                            done=done,
                            total=total,
                            sent=sent,
                            fail=fail,
                            quota=quota_status(),
                            mode=mode,
                            quality=quality,
                        )
                    )

                if session.cancel_requested:
                    cancelled = True
                    break

            if batch:
                remainder_progress = (
                    t("playlist.remainder_from_storage", count=len(batch))
                    if use_storage
                    else t("playlist.remainder_sending", count=len(batch))
                )
                await update_progress(
                    t(
                        "playlist.progress_batch",
                        title=session.title,
                        done=done,
                        total=total,
                        batch_progress=remainder_progress,
                    )
                )
                await flush_batch()

            if cancelled:
                summary = t(
                    "playlist.cancelled_summary",
                    done=done,
                    total=total,
                    sent=sent,
                    fail=fail,
                )
            else:
                summary = t("playlist.done_summary", sent=sent, total=total)
                if fail:
                    summary += t("playlist.done_with_errors", fail=fail)
            try:
                await event.edit(summary)
            except Exception:
                await event.respond(summary)
        finally:
            session.downloading = False
            await self.download_limiter.finish_download(user_id, download_id)
            PLAYLIST_STATES.pop(user_id, None)

    async def _download_playlist_entry(
        self, entry: PlaylistEntry, *, mode: str, quality: str
    ) -> tuple[str, dict, str]:
        """Download one playlist row; return (path, metadata, media_kind)."""
        platform = entry.platform
        if platform == "youtube":
            if mode == "audio":
                path, meta = await self._bounded(download_youtube_audio(entry.url, quality))
                return path, meta, "audio"
            path, meta = await self._bounded(download_youtube_video(entry.url, quality))
            return path, meta, "video"
        if platform == "tiktok":
            path, meta = await self._bounded(download_tiktok_video(entry.url))
            return path, meta, "video"
        if platform == "twitter":
            path, meta = await self._bounded(download_twitter_video(entry.url))
            kind = "photo" if meta.get("content_type") == "photo" else "video"
            return path, meta, kind
        if platform == "pinterest":
            path, meta = await self._bounded(download_pinterest_content(entry.url))
            kind = "photo" if meta.get("content_type") == "photo" else "video"
            return path, meta, kind
        if platform == "hls_host":
            path, meta = await self._bounded(download_hls_host_video(entry.url))
            return path, meta, "video"
        raise ValueError(f"unsupported playlist platform: {platform}")

    def _track_playlist_entry(
        self,
        entry: PlaylistEntry,
        *,
        user_id: int,
        username: str | None,
        mode: str,
        quality: str,
        success: bool,
        metadata: dict | None = None,
        error_message: str | None = None,
    ) -> None:
        title = entry.title or media_title(metadata)
        platform = entry.platform
        if platform == "youtube" and mode == "audio":
            self.stats.track_audio_download(
                user_id,
                quality,
                username,
                success=success,
                error_message=error_message,
                source="dm",
                url=entry.url,
                title=title,
            )
            return
        if platform == "youtube":
            self.stats.track_video_download(
                user_id,
                quality,
                "youtube",
                username,
                success=success,
                error_message=error_message,
                source="dm",
                url=entry.url,
                title=title,
            )
            return
        if platform == "tiktok":
            self.stats.track_tiktok_download(
                user_id,
                username,
                success=success,
                error_message=error_message,
                source="dm",
                url=entry.url,
                title=title,
            )
            return
        if platform == "twitter":
            self.stats.track_twitter_download(
                user_id,
                username,
                success=success,
                error_message=error_message,
                source="dm",
                url=entry.url,
                title=title,
            )
            return
        if platform == "pinterest":
            self.stats.track_pinterest_download(
                user_id,
                username,
                success=success,
                error_message=error_message,
                source="dm",
                url=entry.url,
                title=title,
            )
            return
        self.stats.track_video_download(
            user_id,
            "best",
            platform,
            username,
            success=success,
            error_message=error_message,
            source="dm",
            url=entry.url,
            title=title,
        )

    async def _send_single_playlist_item(
        self, event, file_path: str, metadata: dict, media_kind: str, caption_kw: dict
    ) -> None:
        """Send one non-album playlist item (TikTok / photo / etc.)."""
        chat_id = event.chat_id

        class _Shim:
            def __init__(self, client, chat_id):
                self.client = client
                self.chat_id = chat_id

            async def respond(self, *args, **kwargs):
                return await self.client.send_message(self.chat_id, *args, **kwargs)

        shim = _Shim(self.client, chat_id)
        if media_kind == "audio":
            await send_audio_content(
                shim, file_path, metadata, self.bot_username, **caption_kw
            )
            return
        if media_kind == "photo":
            await send_image_content(
                shim, file_path, self.bot_username, metadata=metadata, **caption_kw
            )
            return
        await send_video_content(
            shim, file_path, metadata, self.bot_username, **caption_kw
        )

    async def _send_playlist_collage(self, event, session: PlaylistSession) -> None:
        """Render a /search-style collage for the current (non-excluded) entries."""
        entries = selected_entries(session)
        if not entries:
            await event.answer(t("playlist.preview.collage_empty"), alert=True)
            return
        await event.answer(t("playlist.preview.collage_busy"))
        items = [entry_to_collage_item(e) for e in entries[:PLAYLIST_PAGE_SIZE]]
        try:
            items = await enrich_youtube_search_stats(items, timeout=12.0)
        except Exception as e:
            logger.debug("playlist collage enrich failed: %s", e)
        try:
            image_path = await render_search_preview_async(
                items, session.title, start_index=1
            )
            await event.respond(
                file=str(image_path),
                buttons=self._playlist_buttons(session),
            )
        except Exception as e:
            logger.error(f"Playlist collage failed: {e}")
            try:
                await event.answer(
                    t("playlist.preview.collage_failed", error=str(e)), alert=True
                )
            except Exception:
                await event.respond(t("playlist.preview.collage_failed", error=str(e)))

