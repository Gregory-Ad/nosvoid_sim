"""
Scripted baseline policy for FarmClearEnv — the bar RL must beat.

Greedy heuristic, expressed in the env's own action space (0=attack, 1..8=move):
  1. KITE: if HP is low and mobs are adjacent, step directly away from the
     nearest mob (survival first).
  2. ATTACK: if the cooldown is ready and standing here already covers >=1 mob
     and is at least as good as any one-tile reposition, fire the AoE.
  3. REPOSITION: otherwise move one tile toward the position that maximises AoE
     coverage; if nothing is in targeting range, approach the nearest mob.
  While on cooldown it keeps repositioning (movement overlaps the CD for free).

Per the review, treat this as the baseline and only invest in RL if it
*measurably* beats this script (compare "RL minus script" clear-time).
`evaluate()` reports clear-rate, mean clear-time, death-rate and mean return.
"""

from __future__ import annotations
import statistics as st

from .pathfind import chebyshev, bfs_path
from .gym_env import FarmClearEnv, EnvConfig, MOVES, ATTACK

# (dx,dy) -> action index (1..8)
_DIR_TO_ACTION = {d: i + 1 for i, d in enumerate(MOVES)}


def _sign(a: int) -> int:
    return (a > 0) - (a < 0)


def _walkable(env, x, y) -> bool:
    return env.sim.world.grid.is_walkable(x, y)


def _move_action_toward(env, p, tx, ty) -> int:
    """A walkable one-tile step toward (tx,ty); falls back to axis-only moves."""
    dx, dy = _sign(tx - p.x), _sign(ty - p.y)
    for cand in ((dx, dy), (dx, 0), (0, dy)):
        if cand != (0, 0) and cand in _DIR_TO_ACTION and _walkable(env, p.x + cand[0], p.y + cand[1]):
            return _DIR_TO_ACTION[cand]
    # last resort: any walkable neighbour
    for d in MOVES:
        if _walkable(env, p.x + d[0], p.y + d[1]):
            return _DIR_TO_ACTION[d]
    return ATTACK


def _move_action_away(env, p, mob) -> int:
    """The move that maximises Chebyshev distance from `mob` (prefers walkable)."""
    best_a, best_d = ATTACK, -1
    for d, a in _DIR_TO_ACTION.items():
        nx, ny = p.x + d[0], p.y + d[1]
        if not _walkable(env, nx, ny):
            continue
        dist = chebyshev((nx, ny), (mob.x, mob.y))
        if dist > best_d:
            best_d, best_a = dist, a
    return best_a


def _best_neighbor_coverage(env, p):
    """(coverage, action) of the best one-tile reposition by AoE coverage."""
    best_cov, best_a = -1, ATTACK
    for d, a in _DIR_TO_ACTION.items():
        nx, ny = p.x + d[0], p.y + d[1]
        if not _walkable(env, nx, ny):
            continue
        cov = env.coverage_from(nx, ny)
        if cov > best_cov:
            best_cov, best_a = cov, a
    return best_cov, best_a


def _approach_bfs(env, p) -> int:
    """Step along a BFS path toward the nearest REACHABLE mob (avoids the
    greedy wall-stuck failure). Falls back to a greedy step if BFS finds none."""
    w = env.sim.world
    alive = [m for m in w.mobs if m.alive]
    if not alive:
        return ATTACK
    alive.sort(key=lambda m: chebyshev((p.x, p.y), (m.x, m.y)))
    for m in alive[:20]:                       # bound BFS calls to the 20 nearest
        path = bfs_path(w.grid, (p.x, p.y), (m.x, m.y))
        if path and len(path) >= 2:
            d = (path[1][0] - p.x, path[1][1] - p.y)
            if d in _DIR_TO_ACTION:
                return _DIR_TO_ACTION[d]
    return _move_action_toward(env, p, alive[0].x, alive[0].y)


def scripted_action(env: FarmClearEnv) -> int:
    w = env.sim.world
    p = w.player
    hp_frac = (p.hp or 0) / (p.hp_max or 1)

    # 1) kite when low and pressured
    if hp_frac < env.cfg.kite_hp_frac and env.n_adjacent() > 0:
        nm, _ = env.nearest_mob()
        if nm is not None:
            return _move_action_away(env, p, nm)

    cov_now = env.coverage_from(p.x, p.y)
    best_cov, best_dir = _best_neighbor_coverage(env, p)

    if env.attack_ready():
        if cov_now >= 1 and cov_now >= best_cov:
            return ATTACK
        if best_cov > cov_now:
            return best_dir
        # nothing worth hitting nearby -> walk (BFS) to the nearest reachable mob
        return _approach_bfs(env, p)

    # on cooldown: reposition for free toward better coverage / nearest mob
    if best_cov > cov_now:
        return best_dir
    return _approach_bfs(env, p)


def evaluate(env: FarmClearEnv | None = None, episodes: int = 5, seed0: int = 0,
             verbose: bool = True) -> dict:
    env = env or FarmClearEnv()
    clear_times, returns, kills_list = [], [], []
    cleared_n = dead_n = 0
    for ep in range(episodes):
        obs, info = env.reset(seed=seed0 + ep)
        ep_ret = 0.0
        kills = 0
        terminated = truncated = False
        while not (terminated or truncated):
            a = scripted_action(env)
            obs, r, terminated, truncated, info = env.step(a)
            ep_ret += r
            kills += info["killed"]
        returns.append(ep_ret)
        kills_list.append(kills)
        if info["cleared"]:
            cleared_n += 1
            clear_times.append(info["t_ms"] / 1000.0)
        if info["dead"]:
            dead_n += 1
        if verbose:
            tag = "CLEARED" if info["cleared"] else ("DIED" if info["dead"] else "timeout")
            print(f"  ep {ep}: {tag:8s}  t={info['t_ms']/1000:6.1f}s  "
                  f"kills={kills:3d}  left={info['mobs_remaining']:3d}  return={ep_ret:8.1f}")
    out = {
        "episodes": episodes,
        "clear_rate": cleared_n / episodes,
        "death_rate": dead_n / episodes,
        "mean_clear_time_s": (st.mean(clear_times) if clear_times else None),
        "mean_return": st.mean(returns),
        "mean_kills": st.mean(kills_list),
    }
    if verbose:
        ct = out["mean_clear_time_s"]
        print(f"\nBASELINE over {episodes} eps: clear_rate={out['clear_rate']:.0%}  "
              f"death_rate={out['death_rate']:.0%}  "
              f"mean_clear_time={ct:.1f}s" if ct is not None else
              f"\nBASELINE over {episodes} eps: clear_rate={out['clear_rate']:.0%}  "
              f"death_rate={out['death_rate']:.0%}  mean_clear_time=n/a")
        print(f"           mean_return={out['mean_return']:.1f}  mean_kills={out['mean_kills']:.1f}")
    return out


if __name__ == "__main__":
    evaluate(FarmClearEnv(), episodes=3)
