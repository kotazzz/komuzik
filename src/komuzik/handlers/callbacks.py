"""Top-level inline-button callback router."""

import logging
import re
from typing import Any, cast

from ..i18n import t
from .common import (
    ACTIVE_BROADCASTS,
    ADMIN_PENDING,
    ADMIN_USERS_KIND_KNOWN,
    REPORT_STATES,
    CallbackHandler,
)

logger = logging.getLogger(__name__)

class CallbacksMixin:
    """Mixin for BotHandlers."""

    async def callback_handler(self, event):
        """Handle callback queries from inline buttons."""
        data = event.data.decode("utf-8")
        user_id = cast("int | None", event.sender_id)

        # Dummy keyboard on inline placeholder — needed for inline_message_id
        if data == "noop":
            await event.answer()
            return

        # Handle report cancel (allowlist for banned users)
        if data == "report_cancel":
            if user_id is None:
                await event.edit(t("common.user_unknown"))
                return
            REPORT_STATES.pop(user_id, None)
            await event.edit(t("report.cancel"))
            return

        if data == "post_cancel":
            if user_id is None or not self._is_bot_admin(user_id):
                await event.answer(t("errors.no_access"), alert=True)
                return
            control = ACTIVE_BROADCASTS.get(user_id)
            if control is None:
                await event.answer(t("admin.broadcast.no_active"), alert=True)
                return
            control.cancel_requested = True
            await event.answer(t("admin.broadcast.stopping"))
            return

        if user_id is not None and await self._reject_if_banned(
            event, user_id, chat_is_group=not bool(getattr(event, "is_private", True))
        ):
            await event.answer()
            return

        if data.startswith("help_"):
            await self._handle_help_callback(event, data)
            return

        if data.startswith("settings_"):
            await self._handle_settings_callback(event, data)
            return

        if data.startswith("chatset_"):
            await self._handle_chat_settings_callback(event, data)
            return

        if data.startswith("pl_"):
            await self._handle_playlist_callback(event, data)
            return

        if data in {"admin_set_concurrent", "admin_set_playlist"}:
            if user_id is None or not self._is_bot_admin(user_id):
                await event.answer(t("errors.no_access"), alert=True)
                return
            ADMIN_PENDING[user_id] = "concurrent" if data == "admin_set_concurrent" else "playlist"
            label = (
                t("admin.limits.prompt_concurrent")
                if data == "admin_set_concurrent"
                else t("admin.limits.prompt_playlist")
            )
            await event.answer()
            await event.respond(t("admin.limits.enter_value", label=label))
            return

        users_page_match = re.fullmatch(r"admin_users_(known|anon)_p_(\d+)", data)
        if users_page_match or data.startswith("admin_users_p_"):
            if user_id is None or not self._is_bot_admin(user_id):
                await event.answer(t("errors.no_access"), alert=True)
                return
            if users_page_match:
                kind = users_page_match.group(1)
                page = int(users_page_match.group(2))
            else:
                # legacy callback from older messages
                kind = ADMIN_USERS_KIND_KNOWN
                page = int(data.removeprefix("admin_users_p_"))
            text, buttons = self._format_admin_users_page(page, kind=kind)
            kwargs: dict[str, Any] = {"link_preview": False}
            if buttons:
                kwargs["buttons"] = buttons
            await event.edit(text, **kwargs)
            await event.answer()
            return

        admin_user_match = re.fullmatch(r"admin_user_(\d+)", data)
        if admin_user_match:
            if user_id is None or not self._is_bot_admin(user_id):
                await event.answer(t("errors.no_access"), alert=True)
                return
            target_id = int(admin_user_match.group(1))
            if not await self._send_admin_history_page(event, target_id, 0, edit=True):
                await event.answer(t("common.no_data"), alert=True)
                return
            await event.answer()
            return

        admin_hist_match = re.fullmatch(r"admin_hist_(\d+)_p_(\d+)", data)
        if admin_hist_match:
            if user_id is None or not self._is_bot_admin(user_id):
                await event.answer(t("errors.no_access"), alert=True)
                return
            target_id = int(admin_hist_match.group(1))
            page = int(admin_hist_match.group(2))
            if not await self._send_admin_history_page(event, target_id, page, edit=True):
                await event.answer(t("common.no_data"), alert=True)
                return
            await event.answer()
            return

        # Route callbacks using dictionary
        handlers: dict[str, CallbackHandler] = {
            "select_": self._handle_select_callback,
            "searchprev_": self._handle_search_preview_callback,
            "searchmore_": self._handle_search_more_callback,
            "content_": self._handle_content_callback,
            "quality_": self._handle_quality_callback,
            "audio_": self._handle_audio_callback,
            "stats_": self._handle_stats_callback,
        }

        for prefix, handler in handlers.items():
            if data.startswith(prefix):
                await handler(event, data)
                return

        logger.warning(f"Unknown callback data: {data}")
