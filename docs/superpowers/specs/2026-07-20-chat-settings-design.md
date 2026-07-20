# Chat settings — design (phase 2)

## Goal

Per-group settings for auto-download platforms and captions, editable only by chat admins via `/settings` in the group. Private `/settings` unchanged.

## Behavior

| Context | Result |
|---|---|
| `/settings` in private | Personal caption settings (existing) |
| `/settings` in group, admin | Inline menu for this chat |
| `/settings` in group, not admin | Error: only admins |
| Platform toggle OFF | Bot ignores that platform’s links silently |
| Captions | `show_bot_caption` / `show_title` apply only to media sent in this group |

## Defaults (all ON)

`youtube`, `tiktok`, `twitter`, `pinterest`, `show_bot_caption`, `show_title`

YouTube Shorts follow the YouTube toggle.

## Technical

- Table `chat_settings(chat_id PK, allow_youtube, allow_tiktok, allow_twitter, allow_pinterest, show_bot_caption, show_title, updated_at)`
- Admin check: any chat admin (`ChannelParticipantAdmin` / `ChannelParticipantCreator` / `ChatAdminRights` participant)
- Re-check admin on every callback
- Group download path reads chat settings before download; captions from chat settings not user settings
