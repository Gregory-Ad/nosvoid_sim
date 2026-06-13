"""
Cooldown bookkeeping + static skill params.

GROUND TRUTH (live-verified 2026-06-12, Session 20 — corrected from March notes):

  Cooldown is NOT decremented in real time in the client. On a successful skill
  use ('su' packet) the client stores:
      slot+0x20 : cooldown in 1/10 second units (e.g. 300 = 30.0s)
      slot+0x24 : timestamp of cast, stamped from the game tick clock
  Remaining time is computed on demand:
      remaining_ms = slot+0x20 * 100 - (game_tick - slot+0x24)

  ** The game tick clock is at 0x77A860, NOT 0x75A860 (March-notes typo). **
  With the correct clock the formula counts down exactly in real time
  (verified: 70s skill 69.3->61.3 over 2s steps; 30s skill 27.5->19.5).

  Static per-skill params come from SkillDataEntry, keyed by VNUM:
      +0x14  name (ptr)
      +0x2C  isDamage (0 = buff/utility, 1 = damage)
      +0x38  castType
      +0x48  mp cost
      +0xFC  cooldown base (1/10 s)
      +0x108 range
      +0x10A aoe radius
  Live VNUMs are NosVoid-actual (SP 6022+, base 5001+), NOT base-NosTale.
  CD (when you can recast) and buff effect DURATION are DIFFERENT quantities
  (e.g. Power of the Volcano: 30s CD, ~5min effect duration). Duration is read
  from the buff slot widget, not the skill slot.

  ** SESSION 21 caveat: for the basic AUTOATTACK, the client does NOT track its
  CD in skillslot+0x20 (it stayed 0/10 through a real cast — RED HERRING). The
  authoritative autoattack CD is the `su` packet Token[5] (1/10 s) = 0.7 s, and
  cast/animation time ≈ 654 ms (ct->su gap). Use packet-sourced CD for the
  autoattack; +0x20 is reliable only for the longer SP/utility skills it was
  verified on. **

In the simulator we model game time in milliseconds directly; no raw clock
address. The mechanism (CD set on use, computed against a monotonic clock) is
what we replicate.
"""

from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class SkillDef:
    """Static skill definition — sourced from SkillDataEntry by VNUM (NosVoid)."""
    vnum: int
    name: str
    is_damage: bool
    cast_type: int
    mp_cost: int
    cooldown_ms: int          # base cooldown (from +0xFC * 100)
    range_tiles: int
    aoe_radius: int
    # cast/animation time before damage lands. MEASURED-S21 for the autoattack
    # ("Magma Ball") ≈ 654 ms (ct->su gap). Default stays 0; set per skill
    # instance (see farm_map_2706.AUTOATTACK).
    cast_time_ms: int = 0


class CooldownTracker:
    """
    Mirrors the client mechanism: a skill is 'ready' when
        now_ms - last_cast_ms >= cooldown_ms
    Cooldowns are not ticked down; readiness is computed against now_ms.
    """

    def __init__(self) -> None:
        self._last_cast: dict[int, int] = {}   # vnum -> last cast time (ms)

    def mark_used(self, vnum: int, now_ms: int) -> None:
        self._last_cast[vnum] = now_ms

    def remaining_ms(self, skill: SkillDef, now_ms: int) -> int:
        last = self._last_cast.get(skill.vnum)
        if last is None:
            return 0
        rem = skill.cooldown_ms - (now_ms - last)
        return max(0, rem)

    def is_ready(self, skill: SkillDef, now_ms: int) -> bool:
        return self.remaining_ms(skill, now_ms) == 0
