"""
nosvoid_sim/interface.py  —  THE SIM-TO-REAL INTERFACE CONTRACT
================================================================

This module is the SINGLE SOURCE OF TRUTH for what the RL agent SEES
(observation) and what it can DO (action). Both ends of the project import
THIS file and nothing else for obs/action, which guarantees they are byte-for-
byte identical:

    * the offline simulator       (training)        -> fast, millions of steps
    * the live read-only adapter  (showcase only)   -> the real NosVoid client

WHY THIS IS THE FOUNDATION (sim-to-real parity)
-----------------------------------------------
A policy trained in the sim only transfers to the live game if the observation
it receives and the actions it emits mean EXACTLY the same thing in both
places. If the sim feeds the agent something the live side cannot produce
(e.g. a mob's exact hidden HP), the policy learns to lean on information that
won't exist at showcase time and falls apart. So the observation below is built
ONLY from quantities that are readable on the live client, read-only:
positions, HP%, cooldown/ready state, the walkability grid, and mob positions.

SCOPE / BOUNDARY  (hard rule for this project — see STATE.md CURRENT DIRECTION)
------------------------------------------------------------------------------
    * Observations come from READ-ONLY reads of the client (the project's
      existing CE/Frida read path). No memory writes.
    * Actions are ABSTRACT INTENTS ("move one tile", "cast at target"). The
      live adapter MUST realise them as ORDINARY CLIENT INPUT (click-to-move,
      select target + press the skill key) — the same things a human does.
      NOT packet injection, NOT memory writes, NOT anything from `exploits/`
      or `bot/`.
This file deliberately contains NO client-reading and NO input-sending code.
It only defines the shared schema, the observation encoder, and the action
set. The two adapters (sim / live) implement the read + actuate ends against
this contract (see WorldAdapter at the bottom).

TIMING
------
This contract defines obs/action CONTENT only. The DURATION of actions (a cast
roots the player ~600 ms, recast cycle ~1356 ms, a move takes one tile-time)
is owned by the environment: the sim advances its clock, and the live loop must
pace actions so the agent never acts faster than a real client can
(action parity). Constants below describe geometry, not timing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import List, Optional, Protocol, Tuple

import numpy as np

# ---------------------------------------------------------------------------
# Geometry constants (measured on map 2706 — see data/farm-map-2706.py)
# ---------------------------------------------------------------------------
VIEW_RADIUS = 15                      # egocentric crop half-size...
VIEW_SIZE = 2 * VIEW_RADIUS + 1       # ...so the crop is 31x31 tiles
CAST_RANGE = 9                        # Magma Ball max target range (Chebyshev tiles)
AOE_RADIUS = 2                        # 5x5 AoE centred on the TARGET (Chebyshev)

GRID_CHANNELS = 3                     # [walkable, mob, in-range-mob]
SCALAR_FEATURES = 6                   # see encode_observation()
N_ACTIONS = 10

# Normalisers for the scalar vector (keep features ~0..1 for the network)
_MAX_MOBS_NORM = 10.0                 # ~max mobs we expect in cast range
_MAX_AOE_NORM = float((2 * AOE_RADIUS + 1) ** 2)  # 25 cells in a 5x5

Coord = Tuple[int, int]
Intent = Tuple                         # ("noop",) | ("move", dx, dy) | ("cast", tx, ty)


# ---------------------------------------------------------------------------
# Canonical world state — BOTH the sim and the live reader must fill this in
# IDENTICALLY. This is the parity guarantee: there is exactly one schema.
# ---------------------------------------------------------------------------
@dataclass
class MobView:
    x: int
    y: int
    alive: bool = True
    hp_frac: float = 1.0               # 0..1; live = HP% byte / 100, sim = exact


@dataclass
class WorldSnapshot:
    # Player (all live-readable)
    player_x: int
    player_y: int
    player_hp_frac: float              # 0..1
    skill_ready: bool                  # off cooldown AND not mid-cast -> can cast now
    cd_frac: float                     # 0.0 = ready, 1.0 = just cast (fraction of recast cycle left)
    rooted: bool                       # mid-cast: cannot act this step

    # Map (the client's own walkability mask — live-readable)
    map_w: int
    map_h: int
    grid: np.ndarray                   # shape (map_h, map_w), 1 = walkable, 0 = blocked

    # Entities
    mobs: List[MobView] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------
class Action(IntEnum):
    NOOP = 0
    MOVE_N = 1
    MOVE_NE = 2
    MOVE_E = 3
    MOVE_SE = 4
    MOVE_S = 5
    MOVE_SW = 6
    MOVE_W = 7
    MOVE_NW = 8
    CAST = 9


# y increases DOWNWARD (grid[y][x]); both sim and live must use this convention.
_MOVE_DELTAS = {
    Action.MOVE_N:  (0, -1),
    Action.MOVE_NE: (1, -1),
    Action.MOVE_E:  (1, 0),
    Action.MOVE_SE: (1, 1),
    Action.MOVE_S:  (0, 1),
    Action.MOVE_SW: (-1, 1),
    Action.MOVE_W:  (-1, 0),
    Action.MOVE_NW: (-1, -1),
}


# ---------------------------------------------------------------------------
# Small geometry helpers
# ---------------------------------------------------------------------------
def chebyshev(ax: int, ay: int, bx: int, by: int) -> int:
    return max(abs(ax - bx), abs(ay - by))


def in_bounds(x: int, y: int, snap: WorldSnapshot) -> bool:
    return 0 <= x < snap.map_w and 0 <= y < snap.map_h


def is_walkable(x: int, y: int, snap: WorldSnapshot) -> bool:
    if not in_bounds(x, y, snap):
        return False
    return bool(snap.grid[y, x])


def alive_mobs_in_range(snap: WorldSnapshot) -> List[MobView]:
    return [
        m for m in snap.mobs
        if m.alive and chebyshev(snap.player_x, snap.player_y, m.x, m.y) <= CAST_RANGE
    ]


def aoe_hit_count(snap: WorldSnapshot, tx: int, ty: int) -> int:
    """How many ALIVE mobs the 5x5 AoE centred on (tx, ty) would hit."""
    return sum(
        1 for m in snap.mobs
        if m.alive and chebyshev(tx, ty, m.x, m.y) <= AOE_RADIUS
    )


def best_cast_target(snap: WorldSnapshot) -> Optional[Coord]:
    """
    Deterministic target selection: among alive mobs within CAST_RANGE, pick the
    one whose 5x5 AoE covers the most alive mobs (tie-break: closest to player).
    Returns (x, y) or None if there is nothing castable.

    This is computed identically in sim and live, so the agent only has to learn
    WHERE to stand and WHEN to cast — not which pixel to click.
    """
    candidates = alive_mobs_in_range(snap)
    if not candidates:
        return None
    px, py = snap.player_x, snap.player_y
    best = max(
        candidates,
        key=lambda m: (aoe_hit_count(snap, m.x, m.y), -chebyshev(px, py, m.x, m.y)),
    )
    return (best.x, best.y)


# ---------------------------------------------------------------------------
# Observation encoder  —  THE shared function. Sim and live both call this.
# ---------------------------------------------------------------------------
def encode_observation(snap: WorldSnapshot) -> dict:
    """
    Returns a dict observation:
        "grid": float32 (GRID_CHANNELS, VIEW_SIZE, VIEW_SIZE)  egocentric, player at centre
            ch 0: walkable          (1 = can stand here, 0 = wall / off-map)
            ch 1: mob present       (1 = an alive mob is on this tile)
            ch 2: in-range mob      (1 = alive mob within CAST_RANGE of the player)
        "vec":  float32 (SCALAR_FEATURES,)
            [hp_frac, cd_frac, skill_ready, n_in_range_norm, best_aoe_norm, rooted]

    Every value here is derivable from a read-only client read, so the live
    adapter produces the identical tensor at showcase time.
    """
    grid = np.zeros((GRID_CHANNELS, VIEW_SIZE, VIEW_SIZE), dtype=np.float32)
    px, py = snap.player_x, snap.player_y

    # Channel 0: walkability crop (vectorised slice of the map grid)
    x0, y0 = px - VIEW_RADIUS, py - VIEW_RADIUS
    for cy in range(VIEW_SIZE):
        wy = y0 + cy
        if not (0 <= wy < snap.map_h):
            continue
        for cx in range(VIEW_SIZE):
            wx = x0 + cx
            if 0 <= wx < snap.map_w and snap.grid[wy, wx]:
                grid[0, cy, cx] = 1.0

    # Channels 1 & 2: mobs
    in_range = 0
    for m in snap.mobs:
        if not m.alive:
            continue
        cx, cy = m.x - x0, m.y - y0
        d = chebyshev(px, py, m.x, m.y)
        if d <= CAST_RANGE:
            in_range += 1
        if 0 <= cx < VIEW_SIZE and 0 <= cy < VIEW_SIZE:
            grid[1, cy, cx] = 1.0
            if d <= CAST_RANGE:
                grid[2, cy, cx] = 1.0

    target = best_cast_target(snap)
    best_aoe = aoe_hit_count(snap, *target) if target is not None else 0

    vec = np.array(
        [
            float(np.clip(snap.player_hp_frac, 0.0, 1.0)),
            float(np.clip(snap.cd_frac, 0.0, 1.0)),
            1.0 if snap.skill_ready else 0.0,
            min(in_range / _MAX_MOBS_NORM, 1.0),
            min(best_aoe / _MAX_AOE_NORM, 1.0),
            1.0 if snap.rooted else 0.0,
        ],
        dtype=np.float32,
    )
    return {"grid": grid, "vec": vec}


# ---------------------------------------------------------------------------
# Action masking + decoding
# ---------------------------------------------------------------------------
def action_mask(snap: WorldSnapshot) -> np.ndarray:
    """
    Boolean array (N_ACTIONS,): True = legal this step. Always feed this to the
    policy (masked PPO) so it never wastes capacity on impossible actions.
    """
    mask = np.zeros(N_ACTIONS, dtype=bool)
    if snap.rooted:
        mask[Action.NOOP] = True        # mid-cast: only wait
        return mask

    mask[Action.NOOP] = True
    for a, (dx, dy) in _MOVE_DELTAS.items():
        if is_walkable(snap.player_x + dx, snap.player_y + dy, snap):
            mask[a] = True
    if snap.skill_ready and best_cast_target(snap) is not None:
        mask[Action.CAST] = True
    return mask


def action_to_intent(action: int, snap: WorldSnapshot) -> Intent:
    """
    Translate a discrete action id into an abstract intent.
      ("move", dx, dy)  -> step one tile
      ("cast", tx, ty)  -> cast at the deterministic best AoE target
      ("noop",)
    The SIM applies the intent to its state; the LIVE adapter realises it as
    ordinary client input (click / keypress). Same intent, two actuators.
    """
    a = Action(action)
    if a in _MOVE_DELTAS:
        dx, dy = _MOVE_DELTAS[a]
        return ("move", dx, dy)
    if a == Action.CAST:
        target = best_cast_target(snap)
        if target is None:
            return ("noop",)            # defensive; masking should prevent this
        return ("cast", target[0], target[1])
    return ("noop",)


# ---------------------------------------------------------------------------
# Gymnasium spaces (lazy import so the core works with numpy alone)
# ---------------------------------------------------------------------------
def observation_space():
    from gymnasium import spaces
    return spaces.Dict(
        {
            "grid": spaces.Box(0.0, 1.0, (GRID_CHANNELS, VIEW_SIZE, VIEW_SIZE), np.float32),
            "vec": spaces.Box(0.0, 1.0, (SCALAR_FEATURES,), np.float32),
        }
    )


def action_space():
    from gymnasium import spaces
    return spaces.Discrete(N_ACTIONS)


# ---------------------------------------------------------------------------
# The two ends of the contract (documentation; implemented elsewhere)
# ---------------------------------------------------------------------------
class WorldAdapter(Protocol):
    """
    Both the sim and the live client implement this same tiny interface.

    SimAdapter (training): read_snapshot() builds a WorldSnapshot from the
    simulator's internal state; apply_intent() mutates that state.

    LiveAdapter (showcase ONLY): read_snapshot() builds the IDENTICAL
    WorldSnapshot from READ-ONLY client reads (positions, HP%, CD, grid, mobs);
    apply_intent() performs ORDINARY CLIENT INPUT (move = click/walk toward the
    tile; cast = select target + press skill key). It must NOT inject packets,
    write memory, or use anything from exploits/ or bot/.
    """

    def read_snapshot(self) -> WorldSnapshot: ...

    def apply_intent(self, intent: Intent) -> None: ...
