# Group auto-download — design (phase 1)

## Goal

If the bot is in a group/supergroup and a message contains a supported media URL, download and reply with media. Optional quality/music prefixes at the **start** of the message work like inline mode. DM behavior unchanged.

## Out of scope (later phases)

- Chat settings (per-platform toggles, captions)
- Default quality settings (groups / inline)
- DM “repeat last format” button

## Behavior

| Context | Action |
|---|---|
| Group, no supported URL | Silent ignore |
| Group, supported URL | Download → reply to that message |
| Group, YouTube without prefix | Video **720p** |
| Group, prefix `360`/`480`/`720`/`1080` (+ optional `p`) at start | That video quality |
| Group, prefix `music`/`audio` at start | Audio (high) |
| Group, Shorts / TikTok / X / Pinterest | Auto-download as today |
| Group, download error | Short error reply |
| Rate limit | Per message author (same as DM) |
| Private chat | Unchanged (format buttons) |

URL may appear anywhere in the message; prefix must be at the beginning (same rules as inline).

## Technical

- Reuse / extract prefix+URL parsing from `inline_query.py`.
- Branch in `message_handler` on private vs group/supergroup.
- Stats `source=group` when recording downloads from groups.
- Captions: for phase 1 use **user** settings of the message author (chat settings come in phase 2).

## Ops (manual)

1. BotFather `/setprivacy` → **Disable**
2. Add bot to group with permission to send messages
