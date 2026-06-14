"""
Farm map 2706 — concrete, LIVE-VERIFIED data for the Phase-1 simulator.

Values captured live on NosVoid and cross-checked against the running game.
Each field is tagged with how trustworthy it is:

  CONFIRMED      = live-verified against the game (highest confidence)
  FITTED         = computed from logged `su` damage + HP% drops
  MEASURED-S21   = directly measured live in Session 21 (CE pos+HP% poll / packet log)
  TABLE-WRONG    = the client NpcDataEntry value is FALSE (server overrides it)
  TABLE-BASELINE = read from NpcDataEntry, plausibly NosVoid-actual but NOT
                   independently confirmed — treat as a hint, verify later

KEY LESSON (do not forget): the client static table is a MIX of real and stale
values, and so were some earlier *fits*. Session 21 corrected TWO things:
  * Golem HP is NOT 345000. BOTH mobs are ~306000 HP (fitted from exact `su`
    damage + HP% drops). The mobs differ by DAMAGE TAKEN (defence), not HP.
  * The autoattack is a TARGET-centred AoE, not single-target, and its CD is
    0.7s (su Token[5]=7) — the old skillslot+0x20=10 was a RED HERRING.
So HP and combat mechanics must be MEASURED, never trusted from the table.
"""

from __future__ import annotations
from .mob_behavior import MobProfile
from .cooldown import SkillDef

MAP_ID = 2706
MAP_W, MAP_H = 180, 130            # CONFIRMED (grid render matched minimap)
MOB_COUNT = 90                     # CONFIRMED (45 Jelly + 45 Golem; live list count = 90)
PLAYER_HP_MAX = 54754              # CONFIRMED (matches HUD)
PLAYER_WALK_SPEED = 15             # CONFIRMED (cond Token[4]); tps mapping TODO

# ---------------------------------------------------------------------------
# AUTOATTACK = "Magma Ball" (Red Magician, fire). TARGET-centred AoE.   [S21]
# You attack a TARGET within TARGET_RANGE_TILES; the blast damages every mob
# within AOE_RADIUS_TILES (Chebyshev) of the TARGET — NOT of the player.
# Measured live: 0/17 "disk-around-target" violations; up to 28 mobs per cast.
# ---------------------------------------------------------------------------
TARGET_RANGE_TILES = 9             # MEASURED-S21 (SkillDataEntry range=9; targeting reach)
AOE_RADIUS_TILES   = 2             # MEASURED-S21 (Chebyshev radius around target = 5x5)
PLAYER_CD_MS       = 700           # MEASURED-S21 (su Token[5]=7). slot+0x20=10 was a RED HERRING.
CAST_MS            = 654           # MEASURED-S21 (ct->su gap). Effective cycle ~max(CD,cast)=700.

CRIT_MULTIPLIER = 2.0              # MEASURED-S21 (crit = x2)
CRIT_RATE       = 0.65             # MEASURED-S24 (871-su sample; BUILD-DEPENDENT — S21 was 0.42)
MOB_HIT_RATE    = 0.53             # MEASURED-S24 (273 hit / 242 miss, mob->player). Miss => 0 dmg.

# Packet skill id of the autoattack is 1078 (and -1 for repeats); 6022 is the
# CLIENT skill-bar slot vnum. Identity comes from the packet, not the slot.
AUTOATTACK = SkillDef(
    vnum=1078,                     # packet skill id (client slot shows 6022)
    name="Magma Ball",
    is_damage=True,
    cast_type=0,
    mp_cost=50,                    # TABLE-BASELINE (+0x48)
    cooldown_ms=PLAYER_CD_MS,      # MEASURED-S21
    range_tiles=TARGET_RANGE_TILES,
    aoe_radius=AOE_RADIUS_TILES,
    cast_time_ms=CAST_MS,          # MEASURED-S21
)

# DEPRECATED (pre-S21): a single global player-hit range conflated both mob
# types AND crit-vs-noncrit. Superseded by per-mob `player_dmg_base` (non-crit)
# + CRIT_MULTIPLIER below. Kept only so old references don't break.
PLAYER_HIT_MIN = 52000
PLAYER_HIT_MAX = 202000

# Two mob types, 45 each.
PROFILES: dict[int, MobProfile] = {
    6232: MobProfile(
        vnum=6232,
        name="Ice Biome Bouncing Jelly",   # CONFIRMED (NpcDataEntry +0x4)
        hp_max=307705,                      # CONFIRMED-S24 (st maxHP=307705; S21 fit ~306k was close)
        aggro_radius=7,                     # MEASURED-S25 (~6-7; 58 onsets, median 6). Old 12 = untested table.
        leash_radius=0,                     # CONFIRMED-S25 no leash (chased 59-104 tiles, 124s, no de-aggro)
        move_speed_tps=0.0,                 # TODO observe (table speed=6; mv token ~29, needs scaling)
        attack_range=1,                     # TABLE-BASELINE (basicRange=1, melee)
        attack_cadence_ms=3500,             # MEASURED-S24 (swing floor 3427ms, mode 4000ms; tail=aggro loss)
        incoming_damage_min=465,            # CONFIRMED (su Token[12] mob->player = 465; 0 = miss)
        incoming_damage_max=465,            # CONFIRMED (constant 465 observed)
        player_dmg_base=101000,             # CONFIRMED-S24 (non-crit median ~100k; crit ~200k)
        respawn_ms=600_000,                 # TABLE-BASELINE (respawn=600 = 10 min; not yet confirmed)
        fitted=True,
    ),
    6233: MobProfile(
        vnum=6233,
        name="Ice Biome Ice Golem",         # CONFIRMED
        hp_max=307705,                      # CONFIRMED-S24 (st maxHP=307705; NOT 345k)
        aggro_radius=7,                     # MEASURED-S25 (~6-7)
        leash_radius=0,                     # CONFIRMED-S25 no leash
        move_speed_tps=0.0,                 # TODO observe (table speed=10)
        attack_range=2,                     # TABLE-BASELINE (basicRange=2)
        attack_cadence_ms=3500,             # MEASURED-S24 (same swing ~3.5-4.0s)
        incoming_damage_min=465,            # CONFIRMED (mob->player 465)
        incoming_damage_max=465,            # CONFIRMED
        player_dmg_base=52000,              # CONFIRMED-S24 (non-crit median ~50k; crit ~100k -> ~2x Jelly's hits)
        respawn_ms=600_000,                 # TABLE-BASELINE
        fitted=True,
    ),
}

# NOTE on the two mobs: SAME HP (~306k), DIFFERENT damage taken. Jelly takes
# ~101k/hit, Golem ~52k/hit -> Golem needs ~2x the hits to kill. The difference
# is defence/resistance, NOT HP. `player_dmg_base` is the measured, identifiable
# combination; do not split it back into a fake "defence" number.

# Other NpcDataEntry fields (TABLE-BASELINE — hints, not confirmed NosVoid-actual):
#   6232: level 92, element 2(water), closeDef 112, distDef 0, speed 6
#   6233: level 97, element 2(water), closeDef 950, distDef 500, speed 10
# Both mobs are water/ice element; the autoattack is fire (Magma Ball / Red Mage).
# Element matchup likely contributes to the high damage, but the MEASURED per-hit
# values already bake it in -> they are valid for THIS build only (re-measure if
# SP / gear / element change). Map 2706 = "Ice Dungeon" (ice zone).

# su packet token layout (CONFIRMED live):
#   su [0]atkType [1]atkID [2]tgtType [3]tgtID(server id, != entity+0x00)
#      [4]skillVNUM(1078=primary / -1=AoE-splash) [5]cooldown(1/10s) [6]? [7]anim
#      [8]posX [9]posY [10]alive [11]targetHP%_after [12]DAMAGE [13]hitType [14]?
#   [13] hitType (CONFIRMED-S24): 4=MISS, 0=direct hit, 5=AoE-splash hit. NOT crit.
#        Crit is a separate x2 damage bimodality (rate ~0.65), not flagged here.
#   NosVoid su = 15 fields: NO Hp/MaxHp tail. Target HP only as % (token[11]);
#        absolute HP via stat(player) / st(target). st: ... curHP curMP maxHP maxMP.
SU_TOKEN_DAMAGE = 12
SU_TOKEN_HP_PCT_AFTER = 11
SU_TOKEN_ALIVE = 10
SU_TOKEN_COOLDOWN = 5
SU_TOKEN_HITFLAG = 13


def build_world(seed_eid: int = 1):
    """
    Construct a ready-to-run World for map 2706 from the live-extracted grid +
    spawns (`_map2706_data`) with the AUTOATTACK skill, mob profiles and the
    measured crit params wired in. Lazy imports avoid any module load-order cycle.
    """
    from .engine import World
    from .entity import Entity, EntityKind
    from .grid import Grid
    from . import _map2706_data as M

    grid = Grid.from_rle(M.MAP_W, M.MAP_H, M.GRID_RLE)
    px, py = M.PLAYER_START
    player = Entity(eid=0, kind=EntityKind.PLAYER, vnum=0, x=px, y=py,
                    hp=PLAYER_HP_MAX, hp_max=PLAYER_HP_MAX, level=99)
    mobs: list[Entity] = []
    eid = seed_eid
    for (vnum, x, y) in M.SPAWNS:
        prof = PROFILES[vnum]
        mobs.append(Entity(eid=eid, kind=EntityKind.MONSTER, vnum=vnum, x=x, y=y,
                           hp=prof.hp_max, hp_max=prof.hp_max))
        eid += 1
    return World(
        grid=grid, player=player, mobs=mobs,
        skills={AUTOATTACK.vnum: AUTOATTACK},
        profiles=PROFILES,
        crit_rate=CRIT_RATE, crit_mult=CRIT_MULTIPLIER,
    )
