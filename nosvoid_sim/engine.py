"""
Phase-1 simulator engine: one farm map, two mob types, two-way combat.

PHASE 1 GOAL: build + validate the sim against the real game. NO RL agent / no
network yet. This engine exposes a clean step() so you (the user) can drive it
manually and check fidelity (does a mob die in the same #hits, aggro from the
same distance, move the same as in-game).

Layer status:
  - Deterministic core (movement, collision, cooldowns): VERIFIED, implemented.
  - Damage layer: autoattack is a TARGET-centred AoE (S21); per-mob damage uses
    MEASURED per-hit values (farm_map_2706), crit x2 rolled per target; the
    OpenNos formula (damage.py) stays as the fallback for un-measured mobs.
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
    # fitted defender stats per mob vnum (hidden, from logs) — formula fallback only
    defender_stats: dict[int, DefenderStats] = field(default_factory=dict)
    # SESSION 21: crit is x2, rolled independently per target in the AoE step.
    crit_rate: float = 0.0
    crit_mult: float = 2.0


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
        Player casts the (AoE) autoattack at a TARGET.

        SESSION 21 mechanic: you pick a TARGET within skill.range_tiles of the
        PLAYER (Chebyshev), and the blast damages every alive mob within
        skill.aoe_radius (Chebyshev) of the TARGET — NOT of the player. Crit
        (x2) is rolled independently per mob. Returns an outcome dict (the sim's
        analogue of one cast's `su` burst) or None if illegal.
        """
        if not self.can_cast(skill_vnum):
            return None
        skill = self.world.skills[skill_vnum]
        target = next((m for m in self.world.mobs if m.eid == target_eid and m.alive), None)
        if target is None:
            return None
        # targeting range is player -> chosen target
        if chebyshev((self.world.player.x, self.world.player.y),
                     (target.x, target.y)) > skill.range_tiles:
            return None

        self.cd.mark_used(skill_vnum, self.now_ms)
        if self.world.player.mp is not None:
            self.world.player.mp -= skill.mp_cost

        # AoE: every alive mob within aoe_radius (Chebyshev) of the TARGET tile.
        atk = self._player_attacker_stats(skill)
        hits: list[dict] = []
        for m in self.world.mobs:
            if not m.alive:
                continue
            if chebyshev((target.x, target.y), (m.x, m.y)) > skill.aoe_radius:
                continue
            crit = self.rng.random() < self.world.crit_rate
            dmg = self._hit_damage(m, atk, crit)
            killed = False
            if m.hp_max:                       # fitted absolute HP available
                m.hp = (m.hp if m.hp is not None else m.hp_max) - dmg
                if m.hp <= 0:
                    m.alive = False
                    self._mob_state[m.eid] = MobState.DEAD
                    killed = True
            hits.append({"eid": m.eid, "vnum": m.vnum, "damage": dmg,
                         "crit": crit, "killed": killed,
                         "hp_unfitted": m.hp_max is None})

        return {
            "t_ms": self.now_ms, "skill_vnum": skill_vnum, "target": target_eid,
            "hits": hits, "n_hit": len(hits),
            "killed": sum(1 for h in hits if h["killed"]),
        }

    def _hit_damage(self, mob: Entity, atk: AttackerStats, crit: bool) -> int:
        """
        Per-target damage. SESSION 21: prefer the MEASURED per-mob non-crit hit
        (profile.player_dmg_base) — the identifiable atk-vs-def combination —
        doubled on crit. Fall back to the hypothesised formula (damage.py) only
        when no measured value exists for this mob vnum.
        """
        prof = self.world.profiles.get(mob.vnum)
        if prof is not None and prof.player_dmg_base > 0:
            return int(prof.player_dmg_base * (self.world.crit_mult if crit else 1))
        dfn = self.world.defender_stats.get(mob.vnum, DefenderStats())
        return compute_damage(atk, dfn, self.rng, crit=crit, crit_mult=self.world.crit_mult)

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
