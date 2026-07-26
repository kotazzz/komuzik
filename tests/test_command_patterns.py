"""Command regexes must not bleed into each other.

Telethon dispatches an update to *every* handler whose pattern matches, so an
under-anchored regex silently runs a second handler.
"""

import re

import pytest

from komuzik.handlers import BotHandlers

COMMANDS = [
    "start",
    "help",
    "info",
    "privacy",
    "limits",
    "settings",
    "stats",
    "post",
    "setstorage",
    "unsetstorage",
    "admin",
    "ban",
    "unban",
    "setconcurrent",
    "setplaylistlimit",
    "setuserlimit",
    "unsetuserlimit",
    "users",
    "user",
    "report",
    "search",
]


def _matching(text: str) -> set[str]:
    return {cmd for cmd in COMMANDS if re.match(BotHandlers.command_pattern(cmd), text)}


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("/users", {"users"}),
        ("/users@komuzik_bot", {"users"}),
        ("/user 123456789", {"user"}),
        ("/user", {"user"}),
        ("/ban 1 причина", {"ban"}),
        ("/unban 1", {"unban"}),
        ("/setuserlimit 1 2", {"setuserlimit"}),
        ("/unsetuserlimit 1", {"unsetuserlimit"}),
        ("/setstorage", {"setstorage"}),
        ("/unsetstorage", {"unsetstorage"}),
        ("/stats", {"stats"}),
        ("/start", {"start"}),
        ("/help", {"help"}),
        ("/search кошки", {"search"}),
    ],
)
def test_exactly_one_command_matches(text, expected):
    assert _matching(text) == expected


@pytest.mark.parametrize(
    "text",
    ["/banana", "/helpme", "/username", "/starting", "/searching", "/statsy", "/userx"],
)
def test_lookalike_words_match_nothing(text):
    """Regression: /banana used to trigger ban_handler, /users also hit user_handler."""
    assert _matching(text) == set()


def test_no_command_pattern_is_a_prefix_of_another():
    """Guards against a future command being added without the boundary."""
    for cmd in COMMANDS:
        others = _matching(f"/{cmd}") - {cmd}
        assert others == set(), f"/{cmd} also matches {others}"


@pytest.mark.parametrize(
    ("text", "command", "expected"),
    [
        ("/ban 123 причина", "ban", "123 причина"),
        ("/ban@komuzik_bot 123 причина", "ban", "123 причина"),
        ("/ban 123 причина\nвторая строка", "ban", "123 причина\nвторая строка"),
        ("/search  кошки  ", "search", "кошки"),
        ("/user", "user", None),
        ("/user   ", "user", None),
        ("/users", "user", None),
        (None, "user", None),
    ],
)
def test_command_args_extraction(text, command, expected):
    assert BotHandlers.command_args(text, command) == expected


def test_multiline_ban_reason_still_matches_pattern():
    """A lookahead boundary keeps multi-line arguments working."""
    text = "/ban 123 причина\nподробности"
    assert re.match(BotHandlers.command_pattern("ban"), text)
