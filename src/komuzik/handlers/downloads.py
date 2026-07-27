"""Link message handling and platform download flows."""

import logging
import re
import shutil
import uuid
from pathlib import Path
from typing import Any, cast

from telethon import Button
from telethon.tl.custom import Message

from ..config import (
    DEFAULT_SEARCH_RESULTS,
    HLS_HOST_REGEX,
    PINTEREST_REGEX,
    TIKTOK_REGEX,
    TWITTER_REGEX,
    YOUTUBE_REGEX,
)
from ..downloaders import (
    download_hls_host_video,
    download_pinterest_content,
    download_tiktok_video,
    download_twitter_video,
    download_youtube_audio,
    download_youtube_video,
    enrich_youtube_search_stats,
    get_available_formats,
    search_youtube,
    send_audio_content,
    send_image_content,
    send_video_content,
)
from ..inline_query import parse_inline_query
from ..playlist import find_playlist_url
from ..search_preview import render_search_preview_async
from ..user_errors import format_download_error
from .common import (
    ADMIN_PENDING,
    CALLBACK_URLS,
    REPORT_STATES,
    SEARCH_SESSIONS,
    media_title,
)

logger = logging.getLogger(__name__)

class DownloadsMixin:
    """Mixin for BotHandlers."""

    async def message_handler(self, event: Message):
        """Handle incoming messages with YouTube, TikTok, Twitter and Pinterest links."""
        message_obj = event.message
        user_id, username = self._get_user_info(event)
        chat_is_group = bool(getattr(event, "is_group", False))

        # Admin reply to a report → copy 1:1 to the reporter (quote their report)
        if await self._maybe_handle_report_reply(event, message_obj, user_id):
            return

        if await self._maybe_handle_admin_pending(event, message_obj, user_id):
            return

        # Check if user is in report state
        if REPORT_STATES.get(user_id):
            raw_report_text = (
                getattr(message_obj, "text", None) if message_obj is not None else None
            )
            report_text = raw_report_text if isinstance(raw_report_text, str) else ""

            # Ignore if user sends another command while in report state
            if report_text.startswith("/"):
                # Handle /cancel command
                if report_text.strip() == "/cancel":
                    REPORT_STATES.pop(user_id, None)
                    await event.respond("❌ Отправка отчета отменена.")
                return

            # Save report to database
            db_text = report_text or "[Медиафайл]"
            self.stats.save_user_report(user_id, username, db_text)

            # Send report to admins (header + 1:1 copy without "forwarded from")
            header_text = (
                f"📋 **Новый отчет**\nОт: @{username or user_id} (номер: {user_id})"
            )
            user_report_msg_id = int(message_obj.id) if message_obj is not None else 0

            for admin_id in self.download_limiter.ADMIN_USER_IDS:
                try:
                    header = await self.client.send_message(admin_id, header_text)
                    if message_obj is None:
                        continue
                    body = await self.client.send_message(admin_id, message_obj)
                    self.stats.save_report_thread(
                        admin_id=int(admin_id),
                        header_msg_id=int(header.id),
                        body_msg_id=int(body.id),
                        user_id=user_id,
                        user_report_msg_id=user_report_msg_id,
                    )
                except Exception as e:
                    logger.error(f"Failed to send report to admin {admin_id}: {e}")

            # Confirm to user
            await event.respond("✅ Спасибо! Ваш отчет отправлен администраторам.")

            # Clear state
            REPORT_STATES.pop(user_id, None)
            return

        text = getattr(message_obj, "text", None) if message_obj is not None else None
        if isinstance(text, str) and re.match(self.command_pattern("report"), text):
            pass
        elif await self._reject_if_banned(event, user_id, chat_is_group=chat_is_group):
            return

        # Playlist exclusion reply (must reply to preview message)
        if await self._maybe_handle_playlist_exclusion_reply(event, message_obj, user_id):
            return

        if not isinstance(text, str) or not text:
            return

        if text.startswith("/"):
            return

        # Groups/supergroups: auto-download links (silent if no URL)
        if bool(getattr(event, "is_group", False)):
            await self._handle_group_link_message(event, text)
            return

        self._track_user(event)

        # Playlists (DM only) — before single-video YouTube match
        playlist_hit = find_playlist_url(text)
        if playlist_hit is not None:
            await self._start_playlist_session(event, user_id, playlist_hit[0], playlist_hit[1])
            return

        # Check for Twitter/X
        twitter_match = TWITTER_REGEX.search(text)
        if twitter_match:
            await self._handle_twitter(event, twitter_match.group(0))
            return

        # Check for Pinterest
        pinterest_match = PINTEREST_REGEX.search(text)
        if pinterest_match:
            await self._handle_pinterest(event, pinterest_match.group(0))
            return

        # Check for TikTok
        tiktok_match = TIKTOK_REGEX.search(text)
        if tiktok_match:
            await self._handle_tiktok(event, tiktok_match.group(0))
            return

        # Check for HLS host
        hls_match = HLS_HOST_REGEX.search(text)
        if hls_match:
            url = hls_match.group(0)
            if not url.startswith(("http://", "https://")):
                url = "https://" + url
            await self._handle_hls_host(event, url)
            return

        # Check for YouTube (including Shorts)
        youtube_match = YOUTUBE_REGEX.search(text)
        if not youtube_match:
            await event.respond(
                "Пожалуйста, отправьте корректную ссылку на видео YouTube, YouTube Shorts, "
                "плейлист YouTube / Music, TikTok, Twitter/X или Pinterest."
            )
            return

        matched_url = youtube_match.group(0)

        # Check if it's a YouTube Shorts
        if "/shorts/" in matched_url:
            await self._handle_youtube_shorts(event, matched_url)
        else:
            await self._show_content_type_selection(event, matched_url)

    async def _handle_group_link_message(self, event: Message, text: str) -> None:
        """Auto-download a supported link in a group (reply to the link message)."""
        if bool(getattr(event, "out", False)):
            return

        chat_id = int(event.chat_id)
        chat_settings = self.stats.get_chat_settings(chat_id)
        parsed = parse_inline_query(text, default_quality=chat_settings.default_quality)
        if parsed is None:
            return

        if not chat_settings.allows_platform(parsed.platform):
            return

        user_id, username = self._get_user_info(event)
        self._track_user(event)
        download_id = str(uuid.uuid4())

        if not await self._check_download_limit(event, user_id, download_id):
            return

        reply_to = int(event.message.id) if event.message is not None else None
        processing_msg = None
        file_path = None
        try:
            client = event.client
            if client is None:
                await event.respond(
                    "Произошла ошибка: клиент Telegram недоступен.",
                    reply_to=reply_to,
                )
                return

            action = "audio" if parsed.mode == "audio" else "video"
            async with client.action(event.chat_id, action):
                processing_msg = await event.respond(
                    f"Загрузка ({parsed.description})…",
                    reply_to=reply_to,
                )
                file_path, metadata, media_kind = await self._download_for_inline(parsed)
                caption_kwargs = {
                    "show_bot_caption": chat_settings.show_bot_caption,
                    "show_title": chat_settings.show_title,
                    "reply_to": reply_to,
                }
                if media_kind == "audio":
                    await send_audio_content(
                        event, file_path, metadata, self.bot_username, **caption_kwargs
                    )
                elif media_kind == "photo":
                    await send_image_content(
                        event,
                        file_path,
                        self.bot_username,
                        metadata=metadata,
                        **caption_kwargs,
                    )
                else:
                    await send_video_content(
                        event, file_path, metadata, self.bot_username, **caption_kwargs
                    )
                self._track_parsed_download(
                    parsed,
                    user_id,
                    username,
                    success=True,
                    source="group",
                    metadata=metadata,
                )
        except Exception as e:
            logger.error(f"Group download failed for {parsed.url}: {e}")
            self._track_parsed_download(
                parsed,
                user_id,
                username,
                success=False,
                error_message=str(e),
                source="group",
            )
            try:
                await event.respond(
                    format_download_error(e, context="❌ Не удалось загрузить:"),
                    reply_to=reply_to,
                )
            except Exception as send_error:
                logger.error(f"Failed to send group error reply: {send_error}")
        finally:
            await self._discard_status(processing_msg)
            if file_path:
                self._cleanup_download_file(file_path)
            await self.download_limiter.finish_download(user_id, download_id)

    async def _handle_tiktok(self, event: Message, url: str):
        """Handle TikTok video download."""
        await self._download_and_send_content(
            event,
            url,
            status_text="Загрузка TikTok видео... Пожалуйста, подождите.",
            error_context="Произошла ошибка при обработке TikTok видео:",
            download=lambda: download_tiktok_video(url),
            send=self._send_video_media,
            track=self.stats.track_tiktok_download,
            action="video",
            log_label="TikTok video",
        )

    async def _handle_hls_host(self, event: Message, url: str):
        """Handle an HLS host video download."""

        def track(user_id, username, *, success, error_message=None, url=None, title=None):
            self.stats.track_video_download(
                user_id,
                "best",
                "hls_host",
                username,
                success=success,
                error_message=error_message,
                url=url,
                title=title,
            )

        await self._download_and_send_content(
            event,
            url,
            status_text="Загрузка видео... Пожалуйста, подождите.",
            error_context="Произошла ошибка при загрузке:",
            download=lambda: download_hls_host_video(url),
            send=self._send_video_media,
            track=track,
            action="video",
            log_label="hls_host video",
        )

    async def _show_content_type_selection(self, event: Message, url: str):
        """Show content type selection buttons for YouTube (+ last format repeat)."""
        token = self._store_callback_url(url)
        buttons = [
            [
                Button.inline("🎬 Видео", data=f"content_video_{token}"),
                Button.inline("🎵 Аудио", data=f"content_audio_{token}"),
            ]
        ]
        user_id = cast("int | None", event.sender_id)
        if user_id is not None:
            settings = self.stats.get_user_settings(user_id)
            if settings.last_mode and settings.last_quality:
                if settings.last_mode == "audio":
                    label = f"🔄 Аудио {settings.last_quality}"
                else:
                    label = f"🔄 Видео {settings.last_quality}"
                buttons.append([Button.inline(label, data=f"content_repeat_{token}")])
        await event.respond("Выберите тип контента для загрузки:", buttons=buttons)

    async def _handle_youtube_shorts(self, event: Message, url: str):
        """Handle YouTube Shorts download."""

        def track(user_id, username, *, success, error_message=None, url=None, title=None):
            self.stats.track_video_download(
                user_id,
                "auto",
                "youtube_shorts",
                username,
                success=success,
                error_message=error_message,
                url=url,
                title=title,
            )

        await self._download_and_send_content(
            event,
            url,
            status_text="Загрузка YouTube Short... Пожалуйста, подождите.",
            error_context="Произошла ошибка при обработке YouTube Short:",
            download=lambda: download_youtube_video(url, quality="best"),
            send=self._send_video_media,
            track=track,
            action="video",
            log_label="YouTube Short",
        )

    async def _handle_select_callback(self, event, data: str):
        """Handle video selection from search results."""
        token = data[7:]  # Remove 'select_' prefix
        url = self._resolve_callback_url(token)
        if not url:
            await event.edit("Ссылка для этого результата больше недоступна. Повторите поиск.")
            return
        CALLBACK_URLS.pop(token, None)
        await self._show_content_type_selection(event, url)

    async def _handle_search_preview_callback(self, event, data: str):
        """Render and send a YouTube-like Pillow collage for /search results."""
        token = data.removeprefix("searchprev_")
        session = SEARCH_SESSIONS.get(token)
        if not session:
            await event.answer("Сессия поиска устарела — повторите /search.", alert=True)
            return

        await event.answer()
        results = list(session.get("results") or [])
        query = str(session.get("query") or "")
        image_path: Path | None = None
        status = None
        try:
            status = await event.respond("⏳ Собираю превью…")
            enriched = await enrich_youtube_search_stats(results, timeout=12.0)
            session["results"] = enriched
            start_index = int(session.get("offset") or 0) + 1
            image_path = await render_search_preview_async(
                enriched, query, start_index=start_index
            )
            reply_to = None
            try:
                origin = await event.get_message()
                if origin is not None:
                    reply_to = origin.id
            except Exception:
                pass
            await self.client.send_file(
                event.chat_id,
                str(image_path),
                caption=f"🖼 Превью поиска: {query}",
                reply_to=reply_to,
            )
            if status is not None:
                try:
                    await status.delete()
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"Failed to render search preview: {e}")
            if status is not None:
                try:
                    await status.edit("Не удалось собрать превью.")
                except Exception:
                    pass
            else:
                await event.answer("Не удалось собрать превью.", alert=True)
        finally:
            if image_path is not None:
                try:
                    shutil.rmtree(image_path.parent, ignore_errors=True)
                except Exception:
                    pass

    async def _handle_search_more_callback(self, event, data: str):
        """Load the next page of /search results."""
        token = data.removeprefix("searchmore_")
        session = SEARCH_SESSIONS.get(token)
        if not session:
            await event.answer("Сессия поиска устарела — повторите /search.", alert=True)
            return

        query = str(session.get("query") or "")
        page_size = int(session.get("page_size") or DEFAULT_SEARCH_RESULTS)
        offset = int(session.get("offset") or 0) + page_size

        await event.answer("Ищу ещё…")
        results = await search_youtube(query, max_results=page_size, offset=offset)
        if not results:
            session["has_more"] = False
            try:
                await event.edit(
                    self._format_search_page_text(token) + "\n\nБольше результатов нет.",
                    buttons=self._search_page_buttons(token),
                )
            except Exception:
                await event.answer("Больше результатов нет.", alert=True)
            return

        session["offset"] = offset
        session["results"] = results
        session["has_more"] = len(results) >= page_size
        await event.edit(
            self._format_search_page_text(token),
            buttons=self._search_page_buttons(token),
        )

    async def _handle_content_callback(self, event, data: str):
        """Handle content type selection (video/audio/repeat last)."""
        parts = data.split("_", 2)
        if len(parts) != 3:
            return

        content_type, token = parts[1], parts[2]
        url = self._resolve_callback_url(token)
        if not url:
            await event.edit("Ссылка для этого выбора больше недоступна. Повторите поиск.")
            return

        if content_type == "repeat":
            user_id = cast("int | None", event.sender_id)
            if user_id is None:
                await event.answer("Не удалось определить пользователя.", alert=True)
                return
            settings = self.stats.get_user_settings(user_id)
            if not settings.last_mode or not settings.last_quality:
                await event.answer("Нет сохранённого формата — выберите вручную.", alert=True)
                return
            mode = settings.last_mode
            quality = settings.last_quality
            await event.answer(
                f"Повтор: {'аудио' if mode == 'audio' else 'видео'} {quality}..."
            )
            if mode == "audio":
                await self._download_and_send_audio(event, url, quality)
            else:
                await self._download_and_send_video(event, url, quality)
            return

        if content_type == "video":
            await self._show_video_quality_selection(event, token)
        elif content_type == "audio":
            await self._show_audio_quality_selection(event, token)

    async def _show_video_quality_selection(self, event, token: str):
        """Show video quality selection buttons."""
        url = self._resolve_callback_url(token)
        if not url:
            await event.edit("Ссылка для этого выбора больше недоступна. Повторите поиск.")
            return

        await event.answer("Проверка доступных форматов...")
        logger.info(f"Getting available formats for: {url}")

        available_heights = await get_available_formats(url)
        logger.info(f"Available heights: {available_heights}")

        buttons = []
        row = []

        for height in available_heights:
            # Create label based on height
            if height >= 2160:
                label = f"{height}p 4K"
            elif height >= 1440:
                label = f"{height}p 2K"
            elif height >= 720:
                label = f"{height}p HD"
            else:
                label = f"{height}p"

            quality_id = f"{height}p"
            row.append(Button.inline(label, data=f"quality_{quality_id}_{token}"))

            # Two buttons per row
            if len(row) == 2:
                buttons.append(row)
                row = []

        # Add remaining buttons
        if row:
            buttons.append(row)

        if not buttons:
            logger.warning(f"No buttons created for available heights: {available_heights}")
            await event.edit(
                "К сожалению, для этого видео нет доступных форматов. Попробуйте другое видео."
            )
            return

        await event.edit("Выберите качество видео:", buttons=buttons)

    async def _show_audio_quality_selection(self, event, token: str):
        """Show audio quality selection buttons."""
        buttons = [
            [
                Button.inline("Высокое качество", data=f"audio_high_{token}"),
                Button.inline("Среднее качество", data=f"audio_medium_{token}"),
            ],
            [Button.inline("Низкое качество", data=f"audio_low_{token}")],
        ]
        await event.edit("Выберите качество аудио:", buttons=buttons)

    async def _handle_quality_callback(self, event, data: str):
        """Handle video quality selection."""
        parts = data.split("_", 2)
        if len(parts) != 3:
            return

        quality, token = parts[1], parts[2]
        url = self._resolve_callback_url(token)
        if not url:
            await event.edit("Ссылка для этой загрузки больше недоступна. Повторите поиск.")
            return
        await event.answer(f"Загрузка видео в качестве {quality}...")
        # Keep the token: users often try another quality from the same keyboard.
        # CALLBACK_URLS is a TTLCache and will expire on its own.
        await self._download_and_send_video(event, url, quality)

    async def _handle_audio_callback(self, event, data: str):
        """Handle audio quality selection."""
        parts = data.split("_", 2)
        if len(parts) != 3:
            return

        quality, token = parts[1], parts[2]
        url = self._resolve_callback_url(token)
        if not url:
            await event.edit("Ссылка для этой загрузки больше недоступна. Повторите поиск.")
            return
        await event.answer(f"Загрузка аудио в качестве {quality}...")
        await self._download_and_send_audio(event, url, quality)

    async def _download_and_send_video(self, event, url: str, quality: str):
        """Download and send YouTube video."""

        def track(user_id, username, *, success, error_message=None, url=None, title=None):
            self.stats.track_video_download(
                user_id,
                quality,
                "youtube",
                username,
                success=success,
                error_message=error_message,
                url=url,
                title=title,
            )
            if success and not bool(getattr(event, "is_group", False)):
                try:
                    self.stats.set_user_last_format(user_id, "video", quality)
                except Exception as e:
                    logger.error(f"Failed to save last format: {e}")

        await self._download_and_send_content(
            event,
            url,
            status_text="Загрузка видео... Пожалуйста, подождите.",
            error_context="Произошла ошибка при обработке видео:",
            download=lambda: download_youtube_video(url, quality),
            send=self._send_video_media,
            track=track,
            action="video",
            log_label=f"видео ({quality})",
        )

    async def _download_and_send_audio(self, event, url: str, quality: str):
        """Download and send YouTube audio."""

        def track(user_id, username, *, success=True, error_message=None, url=None, title=None):
            self.stats.track_audio_download(
                user_id,
                quality,
                username,
                success=success,
                error_message=error_message,
                url=url,
                title=title,
            )
            if success and not bool(getattr(event, "is_group", False)):
                try:
                    self.stats.set_user_last_format(user_id, "audio", quality)
                except Exception as e:
                    logger.error(f"Failed to save last format: {e}")

        await self._download_and_send_content(
            event,
            url,
            status_text="Загрузка аудио... Пожалуйста, подождите.",
            error_context="Произошла ошибка при обработке аудио:",
            download=lambda: download_youtube_audio(url, quality),
            send=self._send_audio_media,
            track=track,
            action="audio",
            log_label=f"аудио ({quality})",
        )

    async def _handle_twitter(self, event: Message, url: str):
        """Handle Twitter/X video and photo download."""
        await self._download_and_send_content(
            event,
            url,
            status_text="Загрузка с Twitter... Пожалуйста, подождите.",
            error_context="Произошла ошибка при обработке контента:",
            download=lambda: download_twitter_video(url),
            send=self._send_media_by_content_type,
            track=self.stats.track_twitter_download,
            action="video",
            log_label="Twitter content",
        )

    async def _handle_pinterest(self, event: Message, url: str):
        """Handle Pinterest video and photo download."""
        await self._download_and_send_content(
            event,
            url,
            status_text="Загрузка с Pinterest... Пожалуйста, подождите.",
            error_context="Произошла ошибка при обработке Pinterest:",
            download=lambda: download_pinterest_content(url),
            send=self._send_media_by_content_type,
            track=self.stats.track_pinterest_download,
            action="document",
            log_label="Pinterest content",
        )
