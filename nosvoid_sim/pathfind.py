"""
Pathfinding over the collision grid.

The client uses a BFS pathfinder over the same grid (documented in
systems/movement.md). We mirror that: BFS gives the same shortest-path
behaviour on an unweighted walkable/blocked grid, which is what we want for
fidelity with how the game routes movement.

8-directional movement (the client supports diagonal steps). Diagonal moves
are only allowed when not cutting through a blocked corner (standard rule);
revisit if live observation shows the client allows corner-cutting.
"""

from __future__ import annotations
from collections import deque

from .grid import Grid


# 8 directions: (dx, dy). Order roughly matches the client's documented dir table;
# adjust if a live trace shows a different tie-break order matters.
DIRS_8 = [
    (0, -1),   # N
    (1, -1),   # NE
    (1, 0),    # E
    (1, 1),    # SE
    (0, 1),    # S
    (-1, 1),   # SW
    (-1, 0),   # W
    (-1, -1),  # NW
]


def neighbors(grid: Grid, x: int, y: int, allow_diagonal: bool = True):
    for dx, dy in DIRS_8:
        if not allow_diagonal and dx != 0 and dy != 0:
            continue
        nx, ny = x + dx, y + dy
        if not grid.is_walkable(nx, ny):
            continue
        # no corner cutting on diagonals
        if dx != 0 and dy != 0:
            if not grid.is_walkable(x + dx, y) or not grid.is_walkable(x, y + dy):
                continue
        yield nx, ny


def bfs_path(grid: Grid, start: tuple[int, int], goal: tuple[int, int],
             allow_diagonal: bool = True) -> list[tuple[int, int]] | None:
    """Shortest path (list of tiles incl. start and goal) or None if unreachable."""
    if start == goal:
        return [start]
    if not grid.is_walkable(*goal):
        return None
    came_from: dict[tuple[int, int], tuple[int, int]] = {start: start}
    q = deque([start])
    while q:
        cur = q.popleft()
        if cur == goal:
            break
        for nx, ny in neighbors(grid, cur[0], cur[1], allow_diagonal):
            if (nx, ny) not in came_from:
                came_from[(nx, ny)] = cur
                q.append((nx, ny))
    if goal not in came_from:
        return None
    # reconstruct
    path = [goal]
    while path[-1] != start:
        path.append(came_from[path[-1]])
    path.reverse()
    return path


def chebyshev(a: tuple[int, int], b: tuple[int, int]) -> int:
    """Tile distance with diagonals (Chebyshev). Useful for aggro radius checks."""
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


def manhattan(a: tuple[int, int], b: tuple[int, int]) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])
