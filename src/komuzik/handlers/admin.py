"""Admin panel, bans, storage and reports."""

import logging
import re
from typing import Any, cast

from telethon import Button
from telethon.tl.custom import Message

from ..broadcast import (
    BroadcastConfig,
    BroadcastControl,
    broadcast_messages,
    format_broadcast_progress,
    format_broadcast_result,
)
from ..i18n import t
from ..repository import format_download_history_line, format_user_label
from .common import (
    ACTIVE_BROADCASTS,
    ADMIN_HISTORY_MAX,
    ADMIN_HISTORY_PAGE_SIZE,
    ADMIN_PENDING,
    ADMIN_USERS_KIND_ANON,
    ADMIN_USERS_KIND_KNOWN,
    ADMIN_USERS_PAGE_SIZE,
    REPORT_STATES,
    format_ban_message,
)

logger = logging.getLogger(__name__)

class AdminMixin:
    """Mixin for BotHandlers."""

    async def post_handler(self, event: Message):
        """Handle /post command for admin broadcast."""
        user_id, _username = self._get_user_info(event)

        if user_id not in self.download_limiter.ADMIN_USER_IDS:
            await event.respond(t("admin.no_access"))
            return

        if user_id in ACTIVE_BROADCASTS:
            await event.respond(t("admin.broadcast_in_progress"))
            return

        message_obj = cast("Message", event.message)

        # Check if it's a reply
        if not message_obj or not getattr(message_obj, "is_reply", False):
            await event.respond(t("admin.post_usage"))
            return

        try:
            reply_msg = await message_obj.get_reply_message()
            users = self.stats.get_all_users()
            user_ids = [uid for uid, _ in users]
            cfg = BroadcastConfig.from_mapping(
                self.download_limiter.config.get("broadcast")
            )
            control = BroadcastControl()
            ACTIVE_BROADCASTS[user_id] = control

            processing_msg = await event.respond(
                t("admin.broadcast_start", total=len(user_ids)),
                buttons=[[Button.inline(t("common.stop"), data="post_cancel")]],
            )

            async def _send(target_id: int) -> None:
                await self.client.send_message(target_id, reply_msg)

            async def _progress(result) -> None:
                if processing_msg is None:
                    return
                try:
                    await processing_msg.edit(
                        format_broadcast_progress(result),
                        buttons=[[Button.inline(t("common.stop"), data="post_cancel")]],
                    )
                except Exception as e:
                    logger.debug("Could not update broadcast progress: %s", e)

            try:
                result = await broadcast_messages(
                    _send,
                    user_ids,
                    config=cfg,
                    control=control,
                    on_progress=_progress,
                )
            finally:
                ACTIVE_BROADCASTS.pop(user_id, None)

            if processing_msg is not None:
                await processing_msg.edit(format_broadcast_result(result), buttons=None)

        except Exception as e:
            ACTIVE_BROADCASTS.pop(user_id, None)
            logger.error(f"Error in post handler: {e}")
            await event.respond(t("common.generic_error", error=str(e)))

    def _is_bot_admin(self, user_id: int) -> bool:
        return user_id in self.download_limiter.ADMIN_USER_IDS

    async def _reject_if_banned(
        self, event: Any, user_id: int, *, chat_is_group: bool
    ) -> bool:
        """Return True if the handler should stop (user is banned)."""
        if self._is_bot_admin(user_id):
            return False
        reason = self.stats.get_ban(user_id)
        if reason is None:
            return False
        if chat_is_group:
            return True
        msg = format_ban_message(reason)
        try:
            if hasattr(event, "respond"):
                await event.respond(msg)
            elif hasattr(event, "edit"):
                await event.edit(msg)
            else:
                logger.warning("Cannot notify banned user: unsupported event type")
        except Exception as e:
            logger.error(f"Failed to send ban message to {user_id}: {e}")
        return True

    def _parse_positive_int(self, text: str | None) -> int | None:
        if text is None:
            return None
        raw = text.strip()
        if not re.fullmatch(r"\d+", raw):
            return None
        value = int(raw)
        if value < 1:
            return None
        return value

    def _format_admin_panel(self) -> str:
        concurrent = self.stats.get_max_concurrent(
            default=self.download_limiter.yaml_concurrent
        )
        playlist_limit = self.stats.get_playlist_daily_limit()
        ban_count = self.stats.count_bans()
        return t(
            "admin.panel",
            concurrent=concurrent,
            playlist_limit=playlist_limit,
            ban_count=ban_count,
        )

    def _admin_panel_buttons(self) -> list:
        return [
            [
                Button.inline(t("admin.buttons.concurrent"), data="admin_set_concurrent"),
                Button.inline(t("admin.buttons.playlist_limit"), data="admin_set_playlist"),
            ],
            [Button.inline(t("admin.buttons.users"), data="admin_users_known_p_0")],
        ]

    def _admin_user_profile_link(self, user_id: int) -> str:
        return t("common.open_profile", user_id=user_id)

    def _truncate_button_label(self, label: str, max_len: int = 60) -> str:
        if len(label) <= max_len:
            return label
        return label[: max_len - 3] + "..."

    def _format_admin_users_page(
        self, page: int, *, kind: str = ADMIN_USERS_KIND_KNOWN
    ) -> tuple[str, list]:
        if kind not in {ADMIN_USERS_KIND_KNOWN, ADMIN_USERS_KIND_ANON}:
            kind = ADMIN_USERS_KIND_KNOWN

        offset = page * ADMIN_USERS_PAGE_SIZE
        users = self.stats.list_users(offset=offset, limit=ADMIN_USERS_PAGE_SIZE, kind=kind)
        total = self.stats.count_users(kind=kind)
        known_total = self.stats.count_users(kind=ADMIN_USERS_KIND_KNOWN)
        anon_total = self.stats.count_users(kind=ADMIN_USERS_KIND_ANON)

        tab_title = (
            t("admin.users.known")
            if kind == ADMIN_USERS_KIND_KNOWN
            else t("admin.users.anon")
        )
        if total == 0:
            lines = [
                t("admin.users.header", tab=tab_title),
                t("admin.users.empty"),
            ]
        else:
            end = offset + len(users)
            lines = [
                t(
                    "admin.users.header_page",
                    tab=tab_title,
                    start=offset + 1,
                    end=end,
                    total=total,
                )
            ]
            for user in users:
                lines.append(f"• {format_user_label(user)}")

        known_mark = "✅ " if kind == ADMIN_USERS_KIND_KNOWN else ""
        anon_mark = "✅ " if kind == ADMIN_USERS_KIND_ANON else ""
        buttons: list[list] = [
            [
                Button.inline(
                    t("admin.users.tab_known", mark=known_mark, count=known_total),
                    data="admin_users_known_p_0",
                ),
                Button.inline(
                    t("admin.users.tab_anon", mark=anon_mark, count=anon_total),
                    data="admin_users_anon_p_0",
                ),
            ]
        ]

        for user in users:
            btn_label = self._truncate_button_label(format_user_label(user))
            buttons.append([Button.inline(btn_label, data=f"admin_user_{user['id']}")])

        nav: list = []
        if page > 0:
            nav.append(Button.inline("◀️", data=f"admin_users_{kind}_p_{page - 1}"))
        if total > 0 and (offset + len(users)) < total:
            nav.append(Button.inline("▶️", data=f"admin_users_{kind}_p_{page + 1}"))
        if nav:
            buttons.append(nav)

        return "\n".join(lines), buttons

    def _format_admin_history_page(self, target_user_id: int, page: int) -> tuple[str | None, list]:
        user = self.stats.get_user(target_user_id)
        total_raw = self.stats.count_user_downloads(target_user_id)
        total = min(total_raw, ADMIN_HISTORY_MAX)

        if total == 0 and user is None:
            return None, []

        max_page = max(0, (total - 1) // ADMIN_HISTORY_PAGE_SIZE) if total > 0 else 0
        page = min(max(page, 0), max_page)
        offset = page * ADMIN_HISTORY_PAGE_SIZE
        remaining = max(0, total - offset)
        limit = min(ADMIN_HISTORY_PAGE_SIZE, remaining)
        downloads = (
            self.stats.list_user_downloads(target_user_id, offset=offset, limit=limit)
            if limit > 0
            else []
        )

        user_record = user or {"id": target_user_id}
        back_kind = (
            ADMIN_USERS_KIND_ANON
            if not (user_record.get("username") or user_record.get("display_name"))
            else ADMIN_USERS_KIND_KNOWN
        )
        lines = [
            t("admin.history.header"),
            f"👤 {format_user_label(user_record)}",
            t("admin.history.user_id", user_id=target_user_id),
            self._admin_user_profile_link(target_user_id),
        ]

        ban_reason = self.stats.get_ban(target_user_id)
        if ban_reason:
            lines.append(t("admin.history.banned", reason=ban_reason))

        if total == 0:
            lines.append("\n" + t("admin.history.empty"))
        else:
            lines.append(
                "\n"
                + t(
                    "admin.history.page",
                    start=offset + 1,
                    end=offset + len(downloads),
                    total=total,
                )
                + "\n"
            )
            lines.extend(format_download_history_line(row) for row in downloads)

        buttons: list[list] = []
        nav: list = []
        if page > 0:
            nav.append(
                Button.inline("◀️", data=f"admin_hist_{target_user_id}_p_{page - 1}")
            )
        if offset + len(downloads) < total:
            nav.append(
                Button.inline("▶️", data=f"admin_hist_{target_user_id}_p_{page + 1}")
            )
        if nav:
            buttons.append(nav)
        buttons.append(
            [Button.inline(t("common.back_to_list"), data=f"admin_users_{back_kind}_p_0")]
        )

        return "\n".join(lines), buttons

    async def _send_admin_users_page(
        self, event, page: int, *, kind: str = ADMIN_USERS_KIND_KNOWN, edit: bool = False
    ) -> None:
        text, buttons = self._format_admin_users_page(page, kind=kind)
        kwargs: dict[str, Any] = {"link_preview": False}
        if buttons:
            kwargs["buttons"] = buttons
        if edit:
            await event.edit(text, **kwargs)
        else:
            await event.respond(text, **kwargs)

    async def _send_admin_history_page(
        self, event, target_user_id: int, page: int, *, edit: bool = False
    ) -> bool:
        text, buttons = self._format_admin_history_page(target_user_id, page)
        if text is None:
            return False
        kwargs: dict[str, Any] = {"link_preview": False}
        if buttons:
            kwargs["buttons"] = buttons
        if edit:
            await event.edit(text, **kwargs)
        else:
            await event.respond(text, **kwargs)
        return True

    async def users_handler(self, event: Message):
        user_id, _ = self._get_user_info(event)
        if not self._is_bot_admin(user_id):
            return
        await self._send_admin_users_page(event, 0, kind=ADMIN_USERS_KIND_KNOWN)

    async def user_handler(self, event: Message):
        user_id, _ = self._get_user_info(event)
        if not self._is_bot_admin(user_id):
            return
        text = getattr(event.message, "text", None) or ""
        target_id = self._parse_positive_int(self.command_args(text, "user"))
        if target_id is None:
            await event.respond(t("admin.examples.user"))
            return
        if not await self._send_admin_history_page(event, target_id, 0):
            await event.respond(t("common.no_data"))

    async def admin_handler(self, event: Message):
        user_id, _ = self._get_user_info(event)
        if not self._is_bot_admin(user_id):
            return
        await event.respond(
            self._format_admin_panel(),
            buttons=self._admin_panel_buttons(),
        )

    async def ban_handler(self, event: Message):
        user_id, _ = self._get_user_info(event)
        if not self._is_bot_admin(user_id):
            return
        args = self.command_args(getattr(event.message, "text", None), "ban") or ""
        match = re.match(r"^(\d+)\s+(.+)", args, re.DOTALL)
        if not match:
            await event.respond(t("admin.examples.ban"))
            return
        target_id = int(match.group(1))
        reason = match.group(2).strip()
        if not reason:
            await event.respond(t("admin.examples.ban"))
            return
        if target_id in self.download_limiter.ADMIN_USER_IDS:
            await event.respond(t("admin.ban.admin_protected"))
            return
        self.stats.ban_user(target_id, reason, banned_by=user_id)
        await event.respond(t("admin.ban.success", target_id=target_id, reason=reason))

    async def unban_handler(self, event: Message):
        user_id, _ = self._get_user_info(event)
        if not self._is_bot_admin(user_id):
            return
        args = self.command_args(getattr(event.message, "text", None), "unban") or ""
        match = re.match(r"^(\d+)", args)
        if not match:
            await event.respond(t("admin.examples.unban"))
            return
        target_id = int(match.group(1))
        if self.stats.unban_user(target_id):
            await event.respond(t("admin.unban.success", target_id=target_id))
        else:
            await event.respond(t("admin.unban.not_banned", target_id=target_id))

    async def setconcurrent_handler(self, event: Message):
        user_id, _ = self._get_user_info(event)
        if not self._is_bot_admin(user_id):
            return
        n = self._parse_positive_int(
            self.command_args(getattr(event.message, "text", None), "setconcurrent")
        )
        if n is None:
            await event.respond(t("admin.examples.setconcurrent"))
            return
        self.stats.set_max_concurrent(n)
        _ = self.download_limiter.get_max_per_user()
        await event.respond(t("admin.limits.concurrent_set", n=n))

    async def setplaylistlimit_handler(self, event: Message):
        user_id, _ = self._get_user_info(event)
        if not self._is_bot_admin(user_id):
            return
        n = self._parse_positive_int(
            self.command_args(getattr(event.message, "text", None), "setplaylistlimit")
        )
        if n is None:
            await event.respond(t("admin.examples.setplaylistlimit"))
            return
        self.stats.set_playlist_daily_limit(n)
        await event.respond(t("admin.limits.playlist_set", n=n))

    async def setuserlimit_handler(self, event: Message):
        user_id, _ = self._get_user_info(event)
        if not self._is_bot_admin(user_id):
            return
        args = self.command_args(getattr(event.message, "text", None), "setuserlimit") or ""
        parts = args.split()
        if len(parts) != 2:
            await event.respond(t("admin.examples.setuserlimit"))
            return
        target_id = self._parse_positive_int(parts[0])
        n = self._parse_positive_int(parts[1])
        if target_id is None or n is None:
            await event.respond(t("admin.examples.setuserlimit"))
            return
        self.stats.set_user_playlist_limit(target_id, n)
        limit = self.stats.get_user_playlist_limit(target_id)
        await event.respond(t("admin.limits.user_set", target_id=target_id, limit=limit))

    async def unsetuserlimit_handler(self, event: Message):
        user_id, _ = self._get_user_info(event)
        if not self._is_bot_admin(user_id):
            return
        target_id = self._parse_positive_int(
            self.command_args(getattr(event.message, "text", None), "unsetuserlimit")
        )
        if target_id is None:
            await event.respond(t("admin.examples.unsetuserlimit"))
            return
        self.stats.clear_user_playlist_limit(target_id)
        await event.respond(t("admin.limits.user_cleared", target_id=target_id))

    async def _maybe_handle_admin_pending(
        self, event: Message, message_obj: Any, user_id: int
    ) -> bool:
        """Apply pending admin limit edit when admin sends a pure integer in DM."""
        if not self._is_bot_admin(user_id):
            return False
        pending = ADMIN_PENDING.get(user_id)
        if pending is None:
            return False
        if bool(getattr(event, "is_group", False)):
            return False

        text = getattr(message_obj, "text", None) if message_obj is not None else None
        if not isinstance(text, str):
            return False
        stripped = text.strip()
        if stripped.startswith("/"):
            ADMIN_PENDING.pop(user_id, None)
            return False
        if not re.fullmatch(r"\d+", stripped):
            return False

        n = int(stripped)
        if n < 1:
            await event.respond(t("admin.limits.invalid_number"))
            return True

        ADMIN_PENDING.pop(user_id, None)
        if pending == "concurrent":
            self.stats.set_max_concurrent(n)
            _ = self.download_limiter.get_max_per_user()
            await event.respond(t("admin.limits.concurrent_set", n=n))
        elif pending == "playlist":
            self.stats.set_playlist_daily_limit(n)
            await event.respond(t("admin.limits.playlist_set", n=n))
        return True

    async def setstorage_handler(self, event: Message):
        user_id, _ = self._get_user_info(event)
        if user_id not in self.download_limiter.ADMIN_USER_IDS:
            return
        if not event.is_group:
            await event.respond(t("admin.storage.group_only"))
            return
        chat_id = event.chat_id
        probe = await event.respond(t("admin.storage.checking"))
        try:
            await self.client.delete_messages(chat_id, [probe.id])
        except Exception as e:
            try:
                await self.client.delete_messages(chat_id, [probe.id])
            except Exception:
                pass
            await event.respond(t("admin.storage.no_delete", error=str(e)))
            return
        self.stats.set_storage_chat_id(int(chat_id))
        await event.respond(t("admin.storage.set_ok", chat_id=chat_id))

    async def unsetstorage_handler(self, event: Message):
        user_id, _ = self._get_user_info(event)
        if user_id not in self.download_limiter.ADMIN_USER_IDS:
            return
        prev = self.stats.get_storage_chat_id()
        self.stats.clear_storage_chat_id()
        if prev is None:
            await event.respond(t("admin.storage.not_set"))
        else:
            await event.respond(t("admin.storage.cleared", prev=prev))

    async def report_handler(self, event: Message):
        """Handle /report command for user reports."""
        user_id, username = self._get_user_info(event)

        REPORT_STATES[user_id] = True

        await event.respond(
            t("report.prompt"),
            buttons=[[Button.inline(t("common.cancel"), data="report_cancel")]],
        )

    async def _maybe_handle_report_reply(
        self, event: Message, message_obj: Any, user_id: int
    ) -> bool:
        """If admin replies to a report message, copy the reply to the reporter.

        Returns True when the event was handled as a report reply.
        """
        if user_id not in self.download_limiter.ADMIN_USER_IDS:
            return False
        if message_obj is None:
            return False

        reply = getattr(message_obj, "reply_to", None)
        reply_msg_id = getattr(reply, "reply_to_msg_id", None) if reply is not None else None
        if not isinstance(reply_msg_id, int):
            return False

        thread = self.stats.get_report_thread_by_admin_msg(user_id, reply_msg_id)
        if thread is None:
            return False

        reporter_id, user_report_msg_id = thread
        try:
            await self.client.send_message(
                reporter_id,
                message_obj,
                reply_to=user_report_msg_id,
            )
            await event.respond(t("report.reply_sent"))
        except Exception as e:
            logger.error(f"Failed to deliver report reply to {reporter_id}: {e}")
            await event.respond(t("report.reply_failed", error=str(e)))
        return True
