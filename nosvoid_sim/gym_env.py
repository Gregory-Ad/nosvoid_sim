"""
Phase-2 scaffold: a Gymnasium-style environment for the "clear the farm map as
fast as possible" task, wrapping the validated Phase-1 simulator.

DESIGN (per the review):
  * SEMI-MDP / options framing. A `step` is ONE macro-action taken at a decision
    point, not a fixed 100 ms tick. The dominant loop is "attack the same cluster
    every ~0.7 s", so the macro-actions are:
        0       = ATTACK  (cast the AoE at the best reachable target; the env waits
                            out any remaining cooldown, then the blast resolves)
        1..8    = MOVE one tile (N,S,E,W,NE,NW,SE,SW)
    Between/the duration of each macro-action the mob simulation is advanced in
    fine sub-steps, so chasing + incoming damage still happen.
  * reset()/step(action) -> (obs, reward, terminated, truncated, info), so
    SB3 / CleanRL / RLlib + vectorisation come for free.

WHAT IS MEASURED vs PLACEHOLDER (be honest):
  MEASURED (authoritative, from Session 21 / farm_map_2706):
    - autoattack = TARGET-centred AoE, range 9, radius 2 (Chebyshev, 5x5)
    - recast ~1.36 s [S27] (cast ~0.6 s ROOTED + CD; move+cast mutually exclusive), per-mob damage (Jelly ~101k / Golem ~52k), crit x2 @ ~0.65 [S24]
    - both mobs 307705 HP, incoming 465/hit @ 53% (cadence ~3.5-4s), player 54754 HP, aggro 12
  PLACEHOLDER (flagged; the load-bearing unknowns for the positioning problem):
    - player_step_ms (move cadence), mob_step_ms (chase), mob_attack_ms, leash
  => The PLAYER side is faithful; the SURVIVAL/kiting side depends on the
     placeholders. Measure those three next, then this env becomes trustworthy.

This module is a soft dependency on gymnasium: it runs (and the scripted baseline
runs) even if gymnasium/numpy are absent, so the scaffold is testable anywhere.
"""

from __future__ import annotations
from dataclasses import dataclass
import math
import random

from .engine import Simulator, World
from .entity import Entity, EntityKind
from .pathfind import chebyshev
from . import farm_map_2706 as farm

# ---- soft gymnasium / numpy ------------------------------------------------
try:
    import gymnasium as gym
    from gymnasium import spaces
    _HAS_GYM = True
except Exception:                                   # pragma: no cover
    _HAS_GYM = False

    class _Box:
        def __init__(self, low, high, shape, dtype=float):
            self.low, self.high, self.shape, self.dtype = low, high, shape, dtype

    class _Discrete:
        def __init__(self, n): self.n = n
        def sample(self): return random.randrange(self.n)

    class spaces:            # type: ignore
        Box = _Box
        Discrete = _Discrete

    class _EnvBase:          # minimal gym.Env stand-in
        metadata: dict = {}

    class gym:               # type: ignore
        Env = _EnvBase

try:
    import numpy as np
    _HAS_NP = True
except Exception:                                   # pragma: no cover
    _HAS_NP = False

# 8-direction moves for actions 1..8
MOVES = [(0, -1), (0, 1), (1, 0), (-1, 0), (1, -1), (-1, -1), (1, 1), (-1, 1)]
ATTACK = 0

# obs normalisation constants
_COVER_NORM = 16.0      # mobs per cast (live max ~28 w/ stacking; clip to 1)
_DIST_NORM = 12.0       # aggro radius
_COUNT_NORM = float(farm.MOB_COUNT)
OBS_LABELS = [
    "hp_frac", "cd_ready", "alive_frac", "n_in_range", "cover_now",
    "nearest_dist", "n_aggro", "n_adjacent", "incoming_threat", "pos_x", "pos_y",
]
OBS_DIM = len(OBS_LABELS)


@dataclass
class EnvConfig:
    # --- UNMEASURED timings (PLACEHOLDERS â€” measure live next) ---
    player_step_ms: int = 185          # time to walk one tile (tie to walk speed 15 later)
    mob_step_ms: int = 157             # mob chase-step cadence (placeholder)
    mob_attack_ms: int = 3500          # MEASURED-S24 (swing floor 3427ms, mode 4000ms; tail=aggro loss)
    mob_hit_chance: float = 0.53       # MEASURED-S24 (273 hit / 242 miss). Miss => 0 dmg this swing.
    leash_radius: int = 0              # 0 = no leash / chase forever (placeholder)
    sub_dt_ms: int = 100               # fine sub-step granularity for the mob sim
    # --- reward shaping (objective = clear fastest, stay alive) ---
    time_cost_per_s: float = 1.0       # penalty per second elapsed
    kill_bonus: float = 1.0            # shaping bonus per kill (helps learning)
    clear_bonus: float = 50.0          # terminal bonus for clearing the map
    death_penalty: float = 50.0        # terminal penalty for dying
    max_steps: int = 6000              # truncation
    # scripted-baseline knobs (also handy defaults for envs)
    kite_hp_frac: float = 0.35
    # --- MEASURED-S22 mob dynamics (telemetry map 2706) ---
    mob_idle_step_ms: int = 350        # idle wander ~1 tile/350ms (~2.9 t/s), radius ~17 from spawn
    respawn_delay_s: int = 45          # ~45s after wipe mobs respawn (rough,1 sample); same ids reused
    heal_to_full_hp: bool = True       # S28: model the human always potting (survival is potion-bound, not kiting)
    potion_threshold_frac: float = 0.5 # S28: HP below this fraction of max heals INSTANTLY to full (100%)
    potion_cooldown_ms: int = 0        # UNMEASURED placeholder (no potion-throughput data; instant heal assumed)


class FarmClearEnv(gym.Env):
    """Gymnasium env: clear map 2706 of all 90 mobs as fast as possible."""
    metadata = {"render_modes": []}

    def __init__(self, world_factory=farm.build_world, config: EnvConfig | None = None):
        super().__init__()
        self._make_world = world_factory
        self.cfg = config or EnvConfig()
        self.action_space = spaces.Discrete(9)
        self.observation_space = spaces.Box(low=0.0, high=1.0, shape=(OBS_DIM,),
                                            dtype=(np.float32 if _HAS_NP else float))
        self.sim: Simulator | None = None
        self._n0 = 1
        self.reset()

    # ---- gym API --------------------------------------------------------
    def reset(self, *, seed: int | None = None, options=None):
        if seed is not None:
            random.seed(seed)
        world = self._make_world()
        self.sim = Simulator(world)
        if seed is not None:
            self.sim.rng.seed(seed)
        self._aggro: set[int] = set()
        self._last_step: dict[int, int] = {}
        self._last_atk: dict[int, int] = {}
        self._steps = 0
        self._n0 = max(1, self._alive())
        return self._obs(), {"mobs_remaining": self._alive()}

    def step(self, action: int):
        assert self.sim is not None
        self._steps += 1
        w = self.sim.world
        p = w.player
        killed = 0
        dt = 0

        if action == ATTACK:
            # wait out remaining cooldown (player stands; mobs act), then cast
            aa = w.skills[farm.AUTOATTACK.vnum]
            rem = self.sim.cd.remaining_ms(aa, self.sim.now_ms)
            if rem > 0:
                self._advance(rem); dt += rem
            tgt, _cov = self.best_target()
            if tgt is not None:
                out = self.sim.cast(aa.vnum, tgt)
                if out:
                    killed = out["killed"]
                    # S27: the cast ROOTS the player for cast_time_ms — advance time with the
                    # player stationary while mobs keep chasing/attacking. Move + cast are
                    # mutually exclusive (verified: 0/49 casts had any player-mv mid-cast).
                    if aa.cast_time_ms > 0:
                        self._advance(aa.cast_time_ms); dt += aa.cast_time_ms
            if dt == 0:
                # ready + (maybe) no target: spend a minimum slice to guarantee progress
                self._advance(self.cfg.sub_dt_ms); dt += self.cfg.sub_dt_ms
        else:
            dx, dy = MOVES[action - 1]
            nx, ny = p.x + dx, p.y + dy
            if w.grid.is_walkable(nx, ny):
                p.x, p.y = nx, ny
            self._advance(self.cfg.player_step_ms); dt += self.cfg.player_step_ms

        # ---- reward ----
        dead = (p.hp is not None and p.hp <= 0)
        cleared = (self._alive() == 0)
        reward = self.cfg.kill_bonus * killed - self.cfg.time_cost_per_s * (dt / 1000.0)
        terminated = bool(cleared or dead)
        if cleared:
            reward += self.cfg.clear_bonus
        if dead:
            reward -= self.cfg.death_penalty
        truncated = self._steps >= self.cfg.max_steps
        info = {"mobs_remaining": self._alive(), "killed": killed, "dt_ms": dt,
                "t_ms": self.sim.now_ms, "dead": dead, "cleared": cleared}
        return self._obs(), float(reward), terminated, truncated, info

    # ---- mob simulation (PLACEHOLDER dynamics; flagged) -----------------
    def _advance(self, dt_ms: int) -> None:
        """Advance the mob FSM over dt_ms in sub_dt_ms slices: aggro within 12,
        chase at mob_step_ms, attack (465) at mob_attack_ms, optional leash."""
        sim = self.sim; w = sim.world; p = w.player
        sub = max(1, self.cfg.sub_dt_ms)
        elapsed = 0
        while elapsed < dt_ms:
            step = min(sub, dt_ms - elapsed)
            sim.now_ms += step
            elapsed += step
            now = sim.now_ms
            for m in w.mobs:
                if not m.alive:
                    continue
                prof = w.profiles.get(m.vnum)
                if prof is None:
                    continue
                d = chebyshev((m.x, m.y), (p.x, p.y))
                if m.eid not in self._aggro:
                    if d <= prof.aggro_radius:
                        self._aggro.add(m.eid)
                    else:
                        continue
                # leash (placeholder; only if configured)
                if self.cfg.leash_radius and d > self.cfg.leash_radius:
                    self._aggro.discard(m.eid)
                    continue
                if d <= prof.attack_range:
                    if now - self._last_atk.get(m.eid, -10**9) >= self.cfg.mob_attack_ms:
                        self._last_atk[m.eid] = now
                        # MEASURED-S24: mob lands only ~53% of swings (miss => 0 dmg)
                        if p.hp is not None and random.random() < self.cfg.mob_hit_chance:
                            p.hp = max(0, p.hp - prof.incoming_damage_max)
                            # S28: the human always potted — HP below the threshold heals
                            # instantly to full. Death is effectively off the table (a single
                            # 465 hit can't cross from >50% to 0), matching real play.
                            if (self.cfg.heal_to_full_hp and p.hp_max
                                    and p.hp < self.cfg.potion_threshold_frac * p.hp_max):
                                p.hp = p.hp_max
                else:
                    if now - self._last_step.get(m.eid, -10**9) >= self.cfg.mob_step_ms:
                        self._last_step[m.eid] = now
                        sx = (p.x > m.x) - (p.x < m.x)
                        sy = (p.y > m.y) - (p.y < m.y)
                        if w.grid.is_walkable(m.x + sx, m.y + sy):
                            m.x += sx; m.y += sy
                        elif w.grid.is_walkable(m.x + sx, m.y):
                            m.x += sx
                        elif w.grid.is_walkable(m.x, m.y + sy):
                            m.y += sy
            if p.hp is not None and p.hp <= 0:
                break

    # ---- helpers (used by obs + scripted baseline) ----------------------
    def _alive(self) -> int:
        return sum(1 for m in self.sim.world.mobs if m.alive)

    def attack_ready(self) -> bool:
        aa = self.sim.world.skills[farm.AUTOATTACK.vnum]
        return self.sim.cd.is_ready(aa, self.sim.now_ms)

    def best_target(self, from_xy: tuple[int, int] | None = None):
        """The (eid, coverage) of the in-range target whose AoE (radius 2) covers
        the most alive mobs, attacking from `from_xy` (default = player tile)."""
        w = self.sim.world
        px, py = from_xy if from_xy else (w.player.x, w.player.y)
        rng = w.skills[farm.AUTOATTACK.vnum].range_tiles
        aoe = w.skills[farm.AUTOATTACK.vnum].aoe_radius
        alive = [m for m in w.mobs if m.alive]
        best_eid, best_cov = None, 0
        for t in alive:
            if chebyshev((px, py), (t.x, t.y)) > rng:
                continue
            cov = sum(1 for m in alive if chebyshev((t.x, t.y), (m.x, m.y)) <= aoe)
            if cov > best_cov:
                best_cov, best_eid = cov, t.eid
        return best_eid, best_cov

    def coverage_from(self, x: int, y: int) -> int:
        return self.best_target((x, y))[1]

    def n_adjacent(self) -> int:
        """Mobs currently within their own attack range of the player (the
        incoming-damage threat)."""
        w = self.sim.world; p = w.player; n = 0
        for m in w.mobs:
            if not m.alive:
                continue
            prof = w.profiles.get(m.vnum)
            if prof and chebyshev((m.x, m.y), (p.x, p.y)) <= prof.attack_range:
                n += 1
        return n

    def nearest_mob(self):
        w = self.sim.world; p = w.player
        best, bd = None, 10**9
        for m in w.mobs:
            if not m.alive:
                continue
            d = chebyshev((m.x, m.y), (p.x, p.y))
            if d < bd:
                bd, best = d, m
        return best, bd

    # ---- observation ----------------------------------------------------
    def _obs(self):
        w = self.sim.world; p = w.player
        alive = [m for m in w.mobs if m.alive]
        rng = w.skills[farm.AUTOATTACK.vnum].range_tiles
        n_in_range = sum(1 for m in alive if chebyshev((p.x, p.y), (m.x, m.y)) <= rng)
        _, cover_now = self.best_target()
        _, nd = self.nearest_mob()
        n_adj = self.n_adjacent()
        # incoming threat ~ adjacent mobs * dmg/sec / player max hp, normalised
        threat = (n_adj * farm.PROFILES[6232].incoming_damage_max * self.cfg.mob_hit_chance *
                  (1000.0 / max(1, self.cfg.mob_attack_ms))) / max(1, p.hp_max or 1)
        feats = [
            (p.hp or 0) / (p.hp_max or 1),
            1.0 if self.attack_ready() else 0.0,
            len(alive) / self._n0,
            min(1.0, n_in_range / _COVER_NORM),
            min(1.0, cover_now / _COVER_NORM),
            min(1.0, nd / _DIST_NORM),
            min(1.0, len(self._aggro) / _COUNT_NORM),
            min(1.0, n_adj / _COVER_NORM),
            min(1.0, threat),
            p.x / max(1, w.grid.width),
            p.y / max(1, w.grid.height),
        ]
        if _HAS_NP:
            return np.asarray(feats, dtype=np.float32)
        return [float(x) for x in feats]

    def summary(self) -> str:
        p = self.sim.world.player
        return (f"t={self.sim.now_ms/1000:6.1f}s  mobs_left={self._alive():3d}  "
                f"hp={p.hp}/{p.hp_max}  aggro={len(self._aggro)}  steps={self._steps}")
