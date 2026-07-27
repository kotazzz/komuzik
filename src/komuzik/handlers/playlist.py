"""YouTube playlist preview and batch download."""

import logging
import uuid

from telethon import Button
from telethon.tl.custom import Message
from typing import Any, cast

from ..downloaders import (
    download_youtube_audio,
    download_youtube_video,
    send_playlist_album,
)
from ..playlist import (
    PLAYLIST_BATCH_SIZE,
    PLAYLIST_PAGE_SIZE,
    PlaylistSession,
    extract_playlist,
    format_preview_page,
    parse_exclusion_ops,
    selected_entries,
)
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
        rows.append(
            [
                Button.inline("🎬 Видео", data="pl_video"),
                Button.inline("🎵 Аудио", data="pl_audio"),
            ]
        )
        rows.append(
            [Button.inline(f"✅ Скачать выбранное ({selected})", data="pl_hint")]
        )
        return rows

    async def _start_playlist_session(
        self, event: Message, user_id: int, url: str, is_music: bool
    ) -> None:
        """Load playlist and show first preview page."""
        status = await event.respond("📃 Читаю плейлист…")
        try:
            title, entries, truncated = await extract_playlist(url, is_music=is_music)
        except Exception as e:
            logger.error(f"Playlist extract failed: {e}")
            await event.respond(f"❌ Не удалось открыть плейлист: {e!s}")
            try:
                await status.delete()
            except Exception:
                pass
            return

        if not entries:
            await event.respond("Плейлист пуст или недоступен.")
            try:
                await status.delete()
            except Exception:
                pass
            return

        session = PlaylistSession(
            user_id=user_id,
            playlist_url=url,
            title=title,
            is_music=is_music,
            entries=entries,
            truncated=truncated,
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
                "Не понял команду.\n\n"
                "Ответьте **reply** на превью плейлиста, например:\n"
                "• `-5` — убрать 5-й\n"
                "• `-1,3,8` — убрать несколько\n"
                "• `-1-20` — убрать диапазон\n"
                "• `+5` — вернуть 5-й\n"
                "• `+11,13,15` — вернуть несколько",
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
            await event.answer("Сессия плейлиста истекла. Пришлите ссылку снова.", alert=True)
            return

        if data == "pl_hint":
            await event.answer(
                "Сначала Видео или Аудио → качество. "
                "Чтобы убрать треки — reply на превью (см. инструкцию в сообщении).",
                alert=True,
            )
            return

        if data == "pl_stop":
            session.cancel_requested = True
            await event.answer("⏹ Останавливаю… дошлю уже скачанное.")
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
            buttons = [
                [
                    Button.inline("360p", data="pl_vq_360p"),
                    Button.inline("480p", data="pl_vq_480p"),
                ],
                [
                    Button.inline("720p", data="pl_vq_720p"),
                    Button.inline("1080p", data="pl_vq_1080p"),
                ],
                [Button.inline("← Назад", data="pl_back")],
            ]
            await event.edit(
                f"📃 **{session.title}**\n\n"
                f"К загрузке: **{len(selected_entries(session))}**\n"
                "Выберите качество видео для всего плейлиста:",
                buttons=buttons,
            )
            await event.answer()
            return

        if data == "pl_audio":
            buttons = [
                [
                    Button.inline("Высокое", data="pl_aq_high"),
                    Button.inline("Среднее", data="pl_aq_medium"),
                ],
                [Button.inline("Низкое", data="pl_aq_low")],
                [Button.inline("← Назад", data="pl_back")],
            ]
            await event.edit(
                f"📃 **{session.title}**\n\n"
                f"К загрузке: **{len(selected_entries(session))}**\n"
                "Выберите качество аудио для всего плейлиста:",
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
            await event.answer(f"Качаю видео {quality}…")
            await self._download_playlist(event, session, mode="video", quality=quality)
            return

        if data.startswith("pl_aq_"):
            quality = data.removeprefix("pl_aq_")
            await event.answer(f"Качаю аудио {quality}…")
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
            await event.edit("Нечего скачивать — всё исключено.")
            return

        is_admin = user_id in self.download_limiter.ADMIN_USER_IDS
        is_unlimited = user_id in self.download_limiter.UNLIMITED_USER_IDS
        remaining = self.stats.remaining_playlist_quota(
            user_id, is_admin=is_admin, is_unlimited=is_unlimited
        )
        if remaining is not None and len(entries) > remaining:
            await event.edit(
                f"⚠️ Выбрано {len(entries)}, доступно {remaining} до конца дня (МСК). "
                "Уменьши выбор (исключения) или подожди завтра."
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
        stop_btn = [[Button.inline("⏹ Стоп", data="pl_stop")]]

        def quota_status() -> str:
            if is_admin or is_unlimited:
                return ""
            limit = self.stats.effective_playlist_limit(
                user_id, is_admin=False, is_unlimited=False
            )
            if limit is None:
                return ""
            used = self.stats.get_playlist_usage(user_id)
            return f" · лимит: {used}/{limit}"

        async def update_progress(text: str) -> None:
            try:
                await event.edit(text, buttons=stop_btn, link_preview=False)
            except Exception:
                try:
                    await event.respond(text, buttons=stop_btn, link_preview=False)
                except Exception:
                    pass

        await update_progress(
            f"⏳ Плейлист **{session.title}**\n"
            f"Готово: **0/{total}** · отправлено: 0{quota_status()}\n"
            f"Режим: {mode} {quality}\n\n"
            "Начинаю…"
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
                        await event.respond(f"⚠️ Не удалось отправить пачку ({len(batch)}): {e!s}")
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
                    await event.respond(f"⚠️ Не удалось отправить пачку ({len(batch)}): {e!s}")
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
                    f"⏳ Плейлист **{session.title}**\n"
                    f"Готово: **{done}/{total}** · отправлено: {sent} · ошибок: {fail}{quota_status()}\n"
                    f"Режим: {mode} {quality}\n\n"
                    f"Сейчас: [{safe_title}]({entry.url})\n"
                    f"({i}/{total})"
                )

                file_path = None
                try:
                    if mode == "audio":
                        file_path, metadata = await self._bounded(download_youtube_audio(entry.url, quality))
                        self.stats.track_audio_download(
                            user_id,
                            quality,
                            username,
                            success=True,
                            source="dm",
                            url=entry.url,
                            title=entry.title or media_title(metadata),
                        )
                    else:
                        file_path, metadata = await self._bounded(download_youtube_video(entry.url, quality))
                        self.stats.track_video_download(
                            user_id,
                            quality,
                            "youtube",
                            username,
                            success=True,
                            source="dm",
                            url=entry.url,
                            title=entry.title or media_title(metadata),
                        )
                    batch.append((file_path, metadata))
                    done += 1
                    file_path = None

                    await update_progress(
                        f"⏳ Плейлист **{session.title}**\n"
                        f"Готово: **{done}/{total}** · отправлено: {sent} · ошибок: {fail}{quota_status()}\n"
                        f"Режим: {mode} {quality}\n\n"
                        f"✅ Скачан: [{safe_title}]({entry.url})\n"
                        f"В пачке: {len(batch)}/{PLAYLIST_BATCH_SIZE}"
                    )
                except Exception as e:
                    fail += 1
                    logger.error(f"Playlist item failed {entry.url}: {e}")
                    if mode == "audio":
                        self.stats.track_audio_download(
                            user_id,
                            quality,
                            username,
                            success=False,
                            error_message=str(e),
                            source="dm",
                            url=entry.url,
                            title=entry.title,
                        )
                    else:
                        self.stats.track_video_download(
                            user_id,
                            quality,
                            "youtube",
                            username,
                            success=False,
                            error_message=str(e),
                            source="dm",
                            url=entry.url,
                            title=entry.title,
                        )
                    try:
                        await event.respond(
                            f"⚠️ Пропуск {i}/{total}: {entry.title[:60]} — {e!s}"
                        )
                    except Exception:
                        pass
                finally:
                    if file_path:
                        self._cleanup_download_file(file_path)

                if len(batch) >= PLAYLIST_BATCH_SIZE:
                    batch_progress = (
                        f"отправляю пачку {len(batch)} из хранилища…"
                        if use_storage
                        else f"отправляю пачку {len(batch)}…"
                    )
                    await update_progress(
                        f"⏳ Плейлист **{session.title}**\n"
                        f"Готово: **{done}/{total}** · {batch_progress}"
                    )
                    await flush_batch()
                    await update_progress(
                        f"⏳ Плейлист **{session.title}**\n"
                        f"Готово: **{done}/{total}** · отправлено: {sent} · ошибок: {fail}{quota_status()}\n"
                        f"Режим: {mode} {quality}"
                    )

                if session.cancel_requested:
                    cancelled = True
                    break

            if batch:
                remainder_progress = (
                    f"отправляю остаток ({len(batch)}) из хранилища…"
                    if use_storage
                    else f"отправляю остаток ({len(batch)})…"
                )
                await update_progress(
                    f"⏳ Плейлист **{session.title}**\n"
                    f"Готово: **{done}/{total}** · {remainder_progress}"
                )
                await flush_batch()

            if cancelled:
                summary = (
                    f"⏹ Остановлено.\n"
                    f"Скачано: {done}/{total} · отправлено: {sent} · ошибок: {fail}"
                )
            else:
                summary = f"✅ Плейлист готов: отправлено {sent}/{total}"
                if fail:
                    summary += f" (ошибок: {fail})"
            try:
                await event.edit(summary)
            except Exception:
                await event.respond(summary)
        finally:
            session.downloading = False
            await self.download_limiter.finish_download(user_id, download_id)
            PLAYLIST_STATES.pop(user_id, None)
