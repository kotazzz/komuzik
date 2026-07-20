# Default quality — design (phase 3)

## Goal

Personal default YouTube quality for inline; per-chat default for groups. Separate settings screens with size hints. DM direct-link picker unchanged. Prefixes override defaults.

## Defaults

`720p` until changed. Allowed: `360p`, `480p`, `720p`, `1080p`.

## UI

- `/settings` main → button to quality screen (personal or chat)
- Quality screen: size hints + 4 quality buttons + Back

## Application

- `parse_inline_query(..., default_quality=...)` for YouTube without height/audio prefix
- Inline: user `default_quality`
- Group: chat `default_quality`
- Explicit prefix wins
