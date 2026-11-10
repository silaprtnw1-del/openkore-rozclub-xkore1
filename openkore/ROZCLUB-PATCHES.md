# OpenKore in this repo

Copied on 2026-11-10 from the working copy the bots ran from (`C:\Users\silap\openkore`).

- **Base:** upstream https://github.com/OpenKore/openkore `master` plus one local commit,
  `24d812040 fix(xkore1): correct stale CH_ENTER session IDs on double login`
  (1 ahead of `origin/master` at copy time).
- **ROZCLUB patches** (uncommitted edits in that working copy, now tracked here; see the git
  history of this folder for the exact diff):
  - `src/`: `AI.pm`, `AI/CoreLogic.pm`, `Base/Ragnarok/CharServer.pm`, `Base/Ragnarok/MapServer.pm`,
    `Network/Receive.pm`, `Network/Receive/tRO.pm`, `Network/Send/tRO.pm`, `Network/XKore.pm`,
    `Network/XKore2/MapServer.pm`, `Poseidon/RagnarokServer.pm`, `Poseidon/servertypes.txt`, `Utils.pm`,
    `auto/XSTools/win32/{common.h,netredirect.cpp,utils-netredirect.cpp}`, test `Network/test/rozclub_char_block.t`
  - `tables/`: `item_weights.txt`, `npc_shops.txt`, `portals.txt`, `servers.txt`, `tRO/portals.txt`
- **Not copied:** `control/` edits (each bot has its own `bots\<name>\control`; this folder keeps the
  stock files as fallbacks), `.bak` / `.before-*` backups, logs, local experiment scripts, the
  temporary `crashtrace` debug plugin, and `rozclub_guard` (not used with XKore 1).
- Built binaries (`*.exe`, `*.dll`) and OpenKore's generated caches (`fields/*.dist`, `*.weight`,
  `tables/portalsLOS.txt`, ...) stay out of git (see `.gitignore` here and at the repo root).

License: GPL v2 (`LICENSE` in this folder).
