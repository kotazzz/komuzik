"""Load user-facing strings from messages.yaml."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


class _FormatDict(dict):
    """Leave unknown placeholders as ``{name}`` instead of raising."""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def _find_messages_file(explicit: str | None = None) -> Path:
    if explicit:
        path = Path(explicit)
        if path.is_file():
            return path
        raise FileNotFoundError(f"messages file not found: {explicit}")

    env = os.getenv("MESSAGES_PATH")
    if env:
        path = Path(env)
        if path.is_file():
            return path

    repo_root = Path(__file__).resolve().parents[2]
    candidates = [
        Path.cwd() / "messages.yaml",
        repo_root / "messages.yaml",
    ]
    for path in candidates:
        if path.is_file():
            return path
    raise FileNotFoundError(
        "messages.yaml not found (cwd or repo root). Set MESSAGES_PATH or copy the file."
    )


def _flatten(data: dict[str, Any], prefix: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in data.items():
        full = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict):
            out.update(_flatten(value, full))
        elif value is None:
            continue
        else:
            out[full] = str(value).rstrip("\n") if isinstance(value, str) else str(value)
    return out


def load_messages(path: str | None = None) -> dict[str, str]:
    file_path = _find_messages_file(path)
    with file_path.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"messages.yaml root must be a mapping, got {type(raw)}")
    flat = _flatten(raw)
    logger.info("Loaded %s message keys from %s", len(flat), file_path)
    return flat


_MESSAGES: dict[str, str] = load_messages()


def reload_messages(path: str | None = None) -> None:
    """Reload catalog (tests / hot path)."""
    global _MESSAGES
    _MESSAGES = load_messages(path)


def t(key: str, **kwargs: Any) -> str:
    """Return message for dotted ``key``, formatting with ``kwargs`` if given."""
    template = _MESSAGES.get(key)
    if template is None:
        logger.warning("Missing message key: %s", key)
        return key
    if not kwargs:
        return template
    return template.format_map(_FormatDict(kwargs))


def has_key(key: str) -> bool:
    return key in _MESSAGES
