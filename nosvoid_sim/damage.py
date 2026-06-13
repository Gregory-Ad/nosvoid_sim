"""
Damage layer.

The formula FORM is publicly known (OpenNos, ~98-99% accurate vs official PvE).
See reference/nostale-damage-formula.md. It is the OFFICIAL form and is a
HYPOTHESIS for NosVoid (private server may differ) — so it must be validated
against logged 'su' damage before being trusted.

Three independent components (physical / fairy(element) / attribute):
    attackDamage    = weaponDamage + skillDamage + 15
                      (weaponDamage = random in [main_min, main_max])
    fairyDamage     = (attackDamage + 100) * (fairyPercent / 100)
    attributeDamage = (fairyDamage + skillAttribute) * attributeFactor
    final           = (playerLevel - mobLevel + attackDamage - mobDefence)
                      + attributeDamage

Worked example (matched official = 963):
    lvl99, weapon 236-236, skillDmg 85, light attr 70, 80% light fairy,
    mob lvl 0, mob def 15, attrFactor 1.3  -> 963.

DESIGN INTENT:
  - Player-side inputs come from client memory (we can read them).
  - HIDDEN mob stats (mob_level, mob_defence, resistances, attrFactor) are FIT
    from logged damage. They are parameters here, NOT hardcoded NosVoid values.
  - attributeFactor depends on the element matchup table (OPEN ITEM: not yet
    gathered). For Ice mobs element matters; until we have the table, pass it
    explicitly / fit it.
  - Crit/buffs/+levels/SP are extra multipliers to identify later.

This module computes the *hypothesised* damage. The calibration loop compares
its output to logged 'su' Token[12] and either fits the hidden params or flags
that the form itself is wrong on NosVoid.
"""

from __future__ import annotations
from dataclasses import dataclass
import random


@dataclass
class AttackerStats:
    """All readable from client memory (player side)."""
    level: int
    weapon_min: int
    weapon_max: int
    skill_damage: int
    skill_attribute: int          # element damage contribution of the skill
    fairy_percent: float          # e.g. 80.0


@dataclass
class DefenderStats:
    """
    Mob side. These are the HIDDEN, server-side values to be FIT from logs.
    Defaults are placeholders, not NosVoid truth.
    """
    level: int = 0
    defence: int = 0              # the relevant defence (close/ranged/magic)
    # attribute factor for this attacker-element vs this mob-element.
    # 1.0 = neutral; >1 strong matchup (~1.3 in the worked example). To be fit
    # or taken from the (not-yet-gathered) element table.
    attribute_factor: float = 1.0


def compute_damage(atk: AttackerStats, dfn: DefenderStats,
                   rng: random.Random | None = None,
                   crit: bool = False, crit_mult: float = 2.0) -> int:
    """
    Returns a single hypothesised damage number using the known form.
    Marked clearly as the *model* output — validate against logs.
    """
    r = rng or random
    weapon_damage = r.randint(atk.weapon_min, atk.weapon_max)
    attack_damage = weapon_damage + atk.skill_damage + 15
    # OpenNos truncates (floor) at each intermediate stage — reproduce that order
    # so the worked example lands on 963 exactly, not 964.
    fairy_damage = int((attack_damage + 100) * (atk.fairy_percent / 100.0))
    attribute_damage = int((fairy_damage + atk.skill_attribute) * dfn.attribute_factor)
    final = (atk.level - dfn.level + attack_damage - dfn.defence) + attribute_damage
    final = max(1, int(final))    # NosTale-style min 1; confirm on NosVoid
    if crit:
        final = int(final * crit_mult)   # crit handling: placeholder, identify later
    return final


def expected_hits_to_kill(atk: AttackerStats, dfn: DefenderStats,
                          mob_hp: int, samples: int = 2000) -> float:
    """
    Monte-Carlo estimate of hits-to-kill for time-to-kill modelling.
    mob_hp is itself a fitted hidden value. Useful once params are fit from logs.
    """
    rng = random.Random(0)
    total = 0
    for _ in range(samples):
        hp = mob_hp
        hits = 0
        while hp > 0:
            hp -= compute_damage(atk, dfn, rng)
            hits += 1
        total += hits
    return total / samples
