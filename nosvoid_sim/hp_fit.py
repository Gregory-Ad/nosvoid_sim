"""
Fit hidden mob HP from logged `su` records.

This is the method that just worked live: a hit deals known `damage` and drops
the target from one HP% to another. damage / (pct_drop/100) estimates max HP.
Average several hits to reduce the HP%-byte rounding error.

Use this instead of trusting NpcDataEntry maxHP (which proved WRONG for the
Jelly: table 250 vs real ~300000).
"""

from __future__ import annotations
from dataclasses import dataclass


@dataclass
class HpHit:
    damage: int
    hp_pct_before: int   # 0-100
    hp_pct_after: int    # 0-100


def estimate_hp(hits: list[HpHit]) -> float | None:
    """
    Average max-HP estimate from hits that produced a measurable %% drop.
    Skips kills (after==0) and no-change/miss hits.
    """
    ests = []
    for h in hits:
        drop = h.hp_pct_before - h.hp_pct_after
        if drop <= 0 or h.damage <= 0 or h.hp_pct_after == 0:
            continue  # skip misses and the killing blow (overkill skews it)
        ests.append(h.damage / (drop / 100.0))
    if not ests:
        return None
    return sum(ests) / len(ests)


# Worked from the live capture (sanity check / regression):
#   Jelly: hit 98354 took 100->68 (drop 32) => 307356
#          hit 98589 took  68->35 (drop 33) => 298755
#   mean ~= 303000  (table said 250 => WRONG; real ~300k)
if __name__ == "__main__":
    jelly = [HpHit(98354, 100, 68), HpHit(98589, 68, 35)]
    print("Jelly HP estimate:", round(estimate_hp(jelly)))
