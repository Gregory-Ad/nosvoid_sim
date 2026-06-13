# NosVoid Offline Farm-Map Simulator — Phase 1 skeleton

**Phase 1 goal:** build the simulator and **validate it against the real game** by hand. No RL agent / no neural network yet — that's Phase 2, decided after this sandbox matches reality.

This skeleton was generated from reverse-engineering findings that were **live-visually co-verified** against the running game (session 2026-06-12). Where a value is server-side and not in the client, it is left as a **fit parameter**, not a guess.

## Layer status

| Layer | File | Status |
|---|---|---|
| Collision grid | `grid.py` | ✅ **Verified** (render matched in-game minimap exactly) |
| Pathfinding (BFS, 8-dir) | `pathfind.py` | ✅ Verified mechanism (client uses BFS over this grid) |
| Entity model + 3-way classify | `entity.py` | ✅ Verified (pet vs NPC vs object, live co-verified) |
| Cooldown / skill timing | `cooldown.py` | ✅ Verified mechanism (CD set on use, computed vs clock; the 0x77A860 fix) |
| Damage | `damage.py` | ⚠️ **Known formula form** (OpenNos, official) — hidden mob stats are **fit params**. Hypothesis for NosVoid until validated against logged `su` damage. |
| Mob behavior | `mob_behavior.py` | ⛔ **Interface only** — profiles (aggro/leash/attack) must be **fit from observed traces**. Not faked. |
| Logging schema | `logging_schema.py` | ✅ Record shapes for passive normal-play logging (`su`=damage source of truth) |
| Engine | `engine.py` | wires verified core; damage/behavior call the fit layers |

## What's proven to work now (offline, no game needed)
`python -m tests.test_core` — exercises grid indexing, RLE roundtrip (the exact live-extraction format), BFS routing/unreachable, the cooldown mechanism, and reproduces the **OpenNos worked damage example exactly (963)**.

## What must be filled from the game (open items)
- Farm **map id** + the **two mob names/VNUMs** (TBD — confirm in-game).
- **Cast/animation timing** per skill (`SkillDef.cast_time_ms`) — not yet live-verified; needed for time-to-kill.
- **Hidden mob stats** (`DefenderStats`: defence/level/resist, and `MobProfile.hp_max`) — fit from logged `su` Token[12] damage.
- **Mob behavior profiles** (`MobProfile`) — fit from observed movement/attack traces.
- **Element matchup factor table** — for Ice mobs; `attribute_factor` until then.
- Player attacker stats wiring (`_player_attacker_stats`) — source weapon/fairy/attribute from readouts.

## Validation method (Phase 1)
Drive the engine manually and compare to the game (same memory-vs-screen method used during RE):
does a mob die in the same number of hits, take/deal the same damage, aggro from the same distance, move the same on the grid? Build rough → test vs game → fix → repeat. Each verified RE finding is one less thing the sim has to guess.

## Provenance discipline
- **Grid geometry** = NosVoid-actual (the client's real pathfinding mask).
- **Damage formula form** = official NosTale = *hypothesis* for NosVoid; validate.
- **Static tables** (if imported later) = inherited-baseline, NOT NosVoid-actual.
- **Logged dynamics** (su/die/drop/move from your own play) = NosVoid-actual ground truth.
