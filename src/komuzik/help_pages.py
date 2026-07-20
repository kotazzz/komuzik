"""Paginated /help texts and /info — bodies from messages.yaml via t()."""

from __future__ import annotations

from telethon import Button

from .i18n import t

USER_SLUGS: tuple[str, ...] = (
    "start",
    "platforms",
    "playlists",
    "inline",
    "groups",
    "commands",
)
ADMIN_SLUGS: tuple[str, ...] = (
    "panel",
    "limits",
    "bans",
    "users",
    "storage",
    "post",
)

INFO_GITHUB_URL = t("info.github_url")
INFO_TEXT = t("info.body")


def user_toc_text() -> str:
    return t("help.toc")


def admin_toc_text() -> str:
    return t("help.admin_toc")


def user_page_text(slug: str) -> str:
    if slug not in USER_SLUGS:
        raise KeyError(slug)
    return t(f"help.pages.{slug}")


def admin_page_text(slug: str) -> str:
    if slug not in ADMIN_SLUGS:
        raise KeyError(slug)
    return t(f"help.admin_pages.{slug}")


def _chunk_buttons(items: list, per_row: int = 2) -> list:
    rows: list = []
    for i in range(0, len(items), per_row):
        rows.append(items[i : i + per_row])
    return rows


def user_toc_buttons(*, is_admin: bool) -> list:
    items = [
        Button.inline(t(f"help.buttons.{slug}"), data=f"help_u_{slug}")
        for slug in USER_SLUGS
    ]
    rows = _chunk_buttons(items, 2)
    if is_admin:
        rows.append([Button.inline(t("help.buttons.for_admin"), data="help_a_toc")])
    return rows


def admin_toc_buttons() -> list:
    items = [
        Button.inline(t(f"help.buttons.{slug}"), data=f"help_a_{slug}")
        for slug in ADMIN_SLUGS
    ]
    rows = _chunk_buttons(items, 2)
    rows.append([Button.inline(t("help.buttons.back"), data="help_toc")])
    return rows


def user_page_buttons() -> list:
    return [[Button.inline(t("help.buttons.back"), data="help_toc")]]


def admin_page_buttons() -> list:
    return [[Button.inline(t("help.buttons.back"), data="help_a_toc")]]


def resolve_help_callback(data: str) -> tuple[str, str | None]:
    if data == "help_toc":
        return "user_toc", None
    if data == "help_a_toc":
        return "admin_toc", None
    if data.startswith("help_u_"):
        slug = data.removeprefix("help_u_")
        if slug in USER_SLUGS:
            return "user_page", slug
        return "unknown", None
    if data.startswith("help_a_"):
        slug = data.removeprefix("help_a_")
        if slug in ADMIN_SLUGS:
            return "admin_page", slug
        return "unknown", None
    return "unknown", None
