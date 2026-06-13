"""
Mob behavior layer.

This is the WEAKEST-COVERAGE layer (you only observe situations you were in).
It is intentionally written as a parameterised FSM whose numbers are FIT from
observed traces per mob type (VNUM), not hardcoded. Per the plan, randomize
within observed bounds so the agent doesn't overfit one exact pattern.

Per-mob-type behavior profile (all to be measured from normal play):
    aggro_radius     : how close before it aggros (user: aggro on approach)
    leash_radius     : how far it chases before returning
    move_speed       : tiles per second (entity +0xAA speed; verify)
    attack_range     : melee vs ranged reach
    attack_cadence_ms: how often it hits
    incoming_damage  : damage it deals to the agent (fit from 'su' where target=agent)
    respawn_ms       : if farming cyclically
States: IDLE/PATROL -> AGGRO(chase) -> ATTACK (in range) -> RETURN(leash) -> IDLE
"""

from __future__ import annotations
from dataclasses import dataclass
from enum import Enum


class MobState(Enum):
    IDLE = "idle"
    AGGRO = "aggro"
    ATTACK = "attack"
    RETURN = "return"
    DEAD = "dead"


@dataclass
class MobProfile:
    """Per-VNUM behavior profile. All fields TO BE FIT from observed traces."""
    vnum: int
    name: str = "TBD"            # confirm in-game (the two Ice-* mob names)
    hp_max: int | None = None    # hidden/server-side -> fit from damage logs
    aggro_radius: int = 0
    leash_radius: int = 0
    move_speed_tps: float = 0.0  # tiles per second
    attack_range: int = 1
    attack_cadence_ms: int = 0
    incoming_damage_min: int = 0
    incoming_damage_max: int = 0
    # SESSION 21: player's NON-CRIT hit ON this mob. This is the identifiable
    # (player_atk - mob_def + level-diff) COMBINATION measured from `su` Token[12],
    # NOT a pure defence value (defence and level are not separately identifiable
    # from damage alone). Crit = x2 of this. Build-specific (SP/gear/element).
    player_dmg_base: int = 0
    respawn_ms: int = 0
    spawn_x: int = 0             # leash anchor / spawn point
    spawn_y: int = 0
    # marks how much of this profile is real-data-backed vs placeholder
    fitted: bool = False
