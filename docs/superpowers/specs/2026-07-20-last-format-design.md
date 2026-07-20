# Last format repeat — design (phase 4)

## Goal

In DM YouTube flow, on the first chooser ([Video][Audio]), show a third button to repeat the last successful YouTube format so users can download many videos without re-picking quality.

## Behavior

- Persist after successful DM YouTube video/audio download: `last_mode` (`video`|`audio`) + `last_quality` (e.g. `480p`, `high`)
- Content-type screen: if last exists → `🔄 Видео 480p` / `🔄 Аудио …` → start download immediately
- Shorts / TikTok / etc. unchanged
- Inline / group do not update or use this button

## Storage

`user_settings.last_mode TEXT`, `user_settings.last_quality TEXT` (nullable until first success)
