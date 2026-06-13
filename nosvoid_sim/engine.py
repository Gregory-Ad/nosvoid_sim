"""
Phase-1 simulator engine: one farm map, two mob types, two-way combat.

PHASE 1 GOAL: build + validate the sim against the real game. NO RL agent / no
network yet. This engine exposes a clean step() so you (the user) can drive it
manually and check fidelity (does a mob die in the same #hits, aggro from the
same distance, move the same as in-game).

Layer status:
  - Deterministic core (movement, collision, cooldowns): VERIFIED, implemented.
  - Damage layer: KNOWN FORM, hidden mob stats are FIT params (damage.py).
  - Mob behavior: INTERFACE ONLY, profiles fit from traces (mob_behavior.py).

Time is modelled in milliseconds. One "tick" advances dt_ms.
"""

from __future__ import annotations
from dataclasses import dataclass, field
import random

from .grid import Grid
from .pathfind import bfs_path, chebyshev
from .entity import Entity, EntityKind
from .cooldown import SkillDef, CooldownTracker
from .damage import AttackerStats, DefenderStats, compute_damage
from .mob_behavior import MobProfile, MobState


@dataclass
class SimConfig:
    map_id: int = -1                       # TBD: confirm farm map in-game
    dt_ms: int = 100                       # tick granularity
    seed: int = 0


@dataclass
class World:
    grid: Grid
    player: Entity
    mobs: list[Entity] = field(default_factory=list)
    skills: dict[int, SkillDef] = field(default_factory=dict)        # vnum -> def
    profiles: dict[int, MobProfile] = field(default_factory=dict)    # vnum -> profile
    # fitted defender stats per mob vnum (hidden, from logs)
    defender_stats: dict[int, DefenderStats] = field(default_factory=dict)


class Simulator:
    def __init__(self, world: World, config: SimConfig | None = None):
        self.world = world
        self.cfg = config or SimConfig()
        self.now_ms = 0
        self.rng = random.Random(self.cfg.seed)
        self.cd = CooldownTracker()
        self._mob_state: dict[int, MobState] = {m.eid: MobState.IDLE for m in world.mobs}

    # ---- deterministic core (verified) ----------------------------------

    def can_cast(self, skill_vnum: int) -> bool:
        skill = self.world.skills.get(skill_vnum)
        if skill is None:
            return False
        if not self.cd.is_ready(skill, self.now_ms):
            return False
        if self.world.player.mp is not None and self.world.player.mp < skill.mp_cost:
            return False
        return True

    def cast(self, skill_vnum: int, target_eid: int) -> dict | None:
        """
        Player casts a skill at a target. Returns an outcome dict (the sim's
        analogue of the 'su' record) or None if illegal.
        Damage uses the HYPOTHESISED formula with fitted defender stats.
        """
        if not self.can_cast(skill_vnum):
            return None
        skill = self.world.skills[skill_vnum]
        target = next((m for m in self.world.mobs if m.eid == target_eid and m.alive), None)
        if target is None:
            return None
        if chebyshev((self.world.player.x, self.world.player.y),
                     (target.x, target.y)) > skill.range_tiles:
            return None

        self.cd.mark_used(skill_vnum, self.now_ms)
        if self.world.player.mp is not None:
            self.world.player.mp -= skill.mp_cost

        # --- damage (model output; validate vs logs) ---
        atk = self._player_attacker_stats(skill)
        dfn = self.world.defender_stats.get(target.vnum, DefenderStats())
        dmg = compute_damage(atk, dfn, self.rng)

        killed = False
        if target.hp_max:                     # fitted absolute HP available
            target.hp = (target.hp if target.hp is not None else target.hp_max) - dmg
            if target.hp <= 0:
                target.alive = False
                self._mob_state[target.eid] = MobState.DEAD
                killed = True
        # else: without fitted HP we can't resolve a kill — flagged below

        return {
            "t_ms": self.now_ms, "skill_vnum": skill_vnum, "target": target_eid,
            "damage": dmg, "killed": killed,
            "hp_unfitted": target.hp_max is None,   # True => need log data to resolve
        }

    def _player_attacker_stats(self, skill: SkillDef) -> AttackerStats:
        # TODO: source weapon_min/max, fairy_percent, skill_attribute from the
        # logged player state. Placeholders until wired to real readouts.
        return AttackerStats(
            level=self.world.player.level,
            weapon_min=0, weapon_max=0,
            skill_damage=0, skill_attribute=0, fairy_percent=0.0,
        )

    def move_player_toward(self, goal: tuple[int, int]) -> bool:
        """One-tile step along BFS path toward goal. Returns True if moved."""
        path = bfs_path(self.world.grid, (self.world.player.x, self.world.player.y), goal)
        if not path or len(path) < 2:
            return False
        self.world.player.x, self.world.player.y = path[1]
        return True

    # ---- mob behavior (INTERFACE — fit from traces before trusting) ------

    def _step_mobs(self) -> None:
        """
        Placeholder mob update. Uses MobProfile params which are FIT from traces.
        Until profiles are fitted (profile.fitted == False) this is not faithful;
        it's wired so the structure is testable.
        """
        p = self.world.player
        for m in self.world.mobs:
            if not m.alive:
                continue
            prof = self.world.profiles.get(m.vnum)
            if prof is None or not prof.fitted:
                continue  # don't fake behavior we haven't measured
            dist = chebyshev((m.x, m.y), (p.x, p.y))
            state = self._mob_state[m.eid]
            if state == MobState.IDLE and dist <= prof.aggro_radius:
                self._mob_state[m.eid] = MobState.AGGRO
            # ... full FSM (chase/attack/leash/return) filled once profiles exist

    # ---- main loop -------------------------------------------------------

    def step(self) -> None:
        self.now_ms += self.cfg.dt_ms
        self._step_mobs()

    def mobs_remaining(self) -> int:
        return sum(1 for m in self.world.mobs if m.alive)
