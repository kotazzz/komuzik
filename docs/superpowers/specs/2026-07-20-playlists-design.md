# YouTube playlists — design (phase 1)

## Scope

DM only. Preview + exclusions + one-shot type/quality + sequential download. Max **200** entries. Batches of 10 for progress reporting. Daily limit / admin — later phases.

## Flow

1. User sends playlist URL (`youtube.com/playlist?list=…`, `music.youtube.com/playlist?list=…`).
2. Bot flat-extracts entries (cap 200), shows paginated preview (10/page).
3. Reply to preview with exclusion syntax updates excluded set and message.
4. Buttons: prev/next, Video, Audio → quality once → download all non-excluded.
5. Progress `k/N`; one failure skips; one concurrent slot for the whole job.

## Exclusion syntax

`-1` · `-1,2,5` · `-1-20` · `-1-10,15,20-30` · `+1` (1-based indices).
