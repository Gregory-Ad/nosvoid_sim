"""
Farm map 2706 — concrete, LIVE-VERIFIED data for the Phase-1 simulator.

All values captured live on NosVoid 2026-06-12 (PID 6020) and cross-checked
against the running game. Each field is tagged with how trustworthy it is:

  CONFIRMED      = live-verified against the game (highest confidence)
  FITTED         = computed from logged `su` damage + HP% drops
  TABLE-WRONG    = the client NpcDataEntry value is FALSE (server overrides it)
  TABLE-BASELINE = read from NpcDataEntry, plausibly NosVoid-actual but NOT
                   independently confirmed — treat as a hint, verify later

KEY LESSON (do not forget): the client static table is a MIX of real and stale
values. noticeRange=12 and Golem HP=345000 proved NosVoid-actual; Jelly HP=250
proved FALSE (real ≈ 300000). So HP especially must be FITTED, never trusted
from the table.
"""

from __future__ import annotations
from .mob_behavior import MobProfile

MAP_ID = 2706
MAP_W, MAP_H = 180, 130            # CONFIRMED (grid render matched minimap)
MOB_COUNT = 90                     # CONFIRMED (45 + 45)

# Damage the player currently deals (THIS build/SP/gear), from captured `su` Token[12].
# Varies per hit (~98k vs ~197k) — likely crit vs non-crit / skill variant. Range kept.
PLAYER_HIT_MIN = 98000             # CONFIRMED (observed 98354 / 98589 / 101468)
PLAYER_HIT_MAX = 197000            # CONFIRMED (observed 197098)
PLAYER_HP_MAX = 54754              # CONFIRMED (matches HUD)

# Two mob types, 45 each. Profiles below.
PROFILES: dict[int, MobProfile] = {
    6232: MobProfile(
        vnum=6232,
        name="Ice Biome Bouncing Jelly",   # CONFIRMED (NpcDataEntry +0x4)
        hp_max=300000,                      # FITTED (~307k & ~299k from two hits; TABLE said 250 = WRONG)
        aggro_radius=12,                    # CONFIRMED (started chase at exactly dist 12)
        leash_radius=0,                     # TODO observe (not yet measured)
        move_speed_tps=0.0,                 # TODO observe (table speed=6, unconfirmed)
        attack_range=1,                     # TABLE-BASELINE (basicRange=1, melee)
        attack_cadence_ms=0,                # TODO observe
        incoming_damage_min=465,            # CONFIRMED (su Token[12] mob->player = 465; 0 = miss)
        incoming_damage_max=465,            # CONFIRMED (constant 465 observed)
        respawn_ms=600_000,                 # TABLE-BASELINE (respawn=600 = 10 min; not yet confirmed)
        fitted=True,                        # core combat fields are real-data-backed
    ),
    6233: MobProfile(
        vnum=6233,
        name="Ice Biome Ice Golem",         # CONFIRMED
        hp_max=345000,                      # CONFIRMED (table value cross-checked via hits-to-kill)
        aggro_radius=12,                    # CONFIRMED (chase began at dist 12)
        leash_radius=0,                     # TODO observe
        move_speed_tps=0.0,                 # TODO observe (table speed=10; chase ~3-5 tiles/0.6s rough)
        attack_range=2,                     # TABLE-BASELINE (basicRange=2)
        attack_cadence_ms=0,                # TODO observe
        incoming_damage_min=465,            # CONFIRMED (mob->player 465)
        incoming_damage_max=465,            # CONFIRMED
        respawn_ms=600_000,                 # TABLE-BASELINE
        fitted=True,
    ),
}

# Other NpcDataEntry fields (TABLE-BASELINE — hints, not confirmed NosVoid-actual):
#   6232: level 92, element 2(water), closeDef 112, distDef 0, damageMax 47,
#         speed 6, defDodge 40, basicSkill 654, concentrate 1
#   6233: level 97, element 2(water), closeDef 950, distDef 500, damageMax 700,
#         speed 10, defDodge 200, basicSkill 3108, concentrate 97
# NOTE: damageMax (47/700) does NOT match observed incoming damage (465 for both),
#       so damageMax is NOT the incoming-damage number directly — another reason to
#       trust observed `su` damage over table fields.

# Element: both are water (element=2). Player attack-element vs water sets the
# damage attribute_factor — element matchup table still an OPEN ITEM.

# su packet token layout (CONFIRMED live with reference target):
#   su [0]atkType [1]atkID [2]tgtType [3]tgtID(server id, != entity+0x00)
#      [4]skillVNUM [5]cooldown [6]? [7]const(4523 player/4806 mob)
#      [8]posX [9]posY [10]? [11]targetHP%_after [12]DAMAGE [13]hitFlag [14]?
SU_TOKEN_DAMAGE = 12
SU_TOKEN_HP_PCT_AFTER = 11
SU_TOKEN_POS_X = 8
SU_TOKEN_POS_Y = 9
