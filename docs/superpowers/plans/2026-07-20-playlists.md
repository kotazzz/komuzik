# Playlists Implementation Plan

> Spec: `docs/superpowers/specs/2026-07-20-playlists-design.md`

**Goal:** DM YouTube/Music playlist preview, exclusions, download.

**Files:**
- `src/komuzik/playlist.py` — URL detect, extract, exclusion parse, preview text
- `src/komuzik/downloaders.py` — flat playlist extract helper if needed
- `src/komuzik/handlers.py` — DM branch, state, callbacks, download loop
- `src/komuzik/config.py` — playlist regex if useful

### Tasks
1. `playlist.py` core (detect, extract, exclusions, page render)
2. Handler state + preview UI + reply exclusions
3. Quality once → sequential download with progress
4. Commit / push / deploy
