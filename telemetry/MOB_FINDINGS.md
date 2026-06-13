# Mob & survival dynamics — map 2706 (measured 2026-06-13, Session 22)

Source: passive read-only Cheat Engine position polling of normal play (no injection).
Telemetry + parsers live in this folder. `n` in logs = mobs IN VIEW (client cull), not alive.

## Mob behaviour (CONFIDENCE)
- **Pathing [HIGH]** — full server pathfinding; mobs route AROUND walls. 0/51412 samples on
  blocked tiles; pursuit paths 432/432 walkable; 0 wall-blocked chord frames while pursuing.
- **Idle wander [HIGH]** — ~1 tile / 350 ms (~2.9 tiles/s), ~73% of time stationary,
  roam radius ~17 tiles from spawn.
- **Chase (aggroed) [HIGH]** — ~6.4 tiles/s (~157 ms/tile), ≈ **2.2× idle speed**
  (mobs speed up on aggro — player-confirmed).
- **Chase vs player [MED-HIGH]** — mob 6.4 vs player-walk 5.4 tiles/s (×1.19):
  **cannot be out-walked → kiting fails. Survival is potion/regen-bound, not kite-bound.**
- **Leash [MED]** — none observed; engaged mobs persist (median ~31 s) until killed/out-of-view.
- **Max simultaneous aggro [HIGH]** — NO cap. All 90 pulled at once; up to 77 within melee (<=2).
- **Aggro radius [LOW — NOT cleanly remeasured]** — keep 12 (from packets). Micro-test failed
  (persistent leftover aggro contaminates; needs full de-aggro then slow approach, or aggro packet).
- **Respawn [LOW-MED, 1 sample]** — ~45 s after wipe (full 90 by ~54 s); same entity ids reused.

## Player survival (Session 22c)
- **maxHP = 54754** (confirmed). curHP/maxHP in a character struct on the writable heap:
  maxHP @ +0x00, curHP @ +0x04 (re-find via AOBScan 'E2 D5 00 00' +W, aligned hit, +4 in HP range).
- **Potion = instant heal to 100%.**
- **Passive regen out of combat** (slow; rate not precisely timed).
- **Mobs miss often** → effective incoming DPS << cadence x damage.
- Incoming hit ~465 (S21). Effective DPS = hit_rate x 465 x adjacent_mobs (hit_rate TBD).

## Memory (this build; heap resolve fresh each session)
- Entity id +0x08, kind +0x04 (1=player,2=monster), pos x/y +0x0C/+0x0E, vnum +0x1C2,
  hp%% byte +0xC8 (LAGS — not raw HP). Scene entity does NOT hold raw HP.
- Char-stats struct (separate heap obj): maxHP+0x00 / curHP+0x04.

## Sim updates applied to gym_env.py EnvConfig
- player_step_ms=185, mob_step_ms=157 (was 600), mob_idle_step_ms=350,
  respawn_delay_s=45, heal_to_full_hp=True, potion_cooldown_ms=0 (flagged), leash_radius=0.
- PLAYER_HP_MAX stays 54754 (confirmed correct).

## STILL UNMEASURED (next session)
1. **Mob attack cadence + hit/miss rate + per-hit damage** — use the PACKET sniffer
   (mob su/at packets fire on every swing with hit/miss/damage; HP-polling can't see misses).
2. **Potion throughput** (cooldown) and **regen rate** (HP/s) — now that curHP addr is findable.
3. **True aggro radius** — de-aggro fully, slow-approach a lone mob, or read the aggro packet.
4. Optional: stable static->curHP pointer path (pointer scan).
