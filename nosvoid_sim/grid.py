"""
Collision grid for one map.

GROUND TRUTH (live-visually-verified 2026-06-12, Session 20):
  Source struct in client: SceneManager + 0x20 -> grid object
    grid + 0x00 : width   (uint16)
    grid + 0x02 : height  (uint16)
    grid + 0x04 : cells[] (byte array, row-major)
  cell value: 0 = walkable, 1 = blocked (wall/water/obstacle)
  index formula: cell(x, y) = cells[y * width + x]
  axes: x = west->east (left->right), y = north->south (top->bottom), origin top-left (0,0)

The render of this exact layout matched the in-game minimap exactly (shape,
player position, orientation, origin). So this representation is trustworthy.

For NosVoid custom maps the grid is NosVoid-actual geometry (the client must
hold the real walkable mask to pathfind), unlike stat tables which are baseline.
"""

from __future__ import annotations
from dataclasses import dataclass


WALKABLE = 0
BLOCKED = 1


@dataclass
class Grid:
    width: int
    height: int
    cells: bytes  # length == width * height, row-major

    def __post_init__(self) -> None:
        expected = self.width * self.height
        if len(self.cells) != expected:
            raise ValueError(
                f"cells length {len(self.cells)} != width*height {expected}"
            )

    def in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self.width and 0 <= y < self.height

    def is_walkable(self, x: int, y: int) -> bool:
        if not self.in_bounds(x, y):
            return False
        return self.cells[y * self.width + x] == WALKABLE

    def cell(self, x: int, y: int) -> int:
        """Raw cell value; out-of-bounds treated as BLOCKED."""
        if not self.in_bounds(x, y):
            return BLOCKED
        return self.cells[y * self.width + x]

    # ---- constructors ----------------------------------------------------

    @classmethod
    def from_rle(cls, width: int, height: int, rle: str) -> "Grid":
        """
        Rebuild from the RLE dump format used during live extraction:
        comma-separated "value:count" tokens, row-major.
        (This is exactly how the grid was pulled from CE this session.)
        """
        out = bytearray()
        for tok in rle.split(","):
            v, c = tok.split(":")
            out.extend(int(v) for _ in range(int(c)))
        return cls(width=width, height=height, cells=bytes(out))

    @classmethod
    def from_rows(cls, rows: list[str], walkable_char: str = ".") -> "Grid":
        """Build from ASCII rows (handy for tests / hand-made maps)."""
        height = len(rows)
        width = len(rows[0]) if rows else 0
        cells = bytearray()
        for r in rows:
            if len(r) != width:
                raise ValueError("ragged rows")
            for ch in r:
                cells.append(WALKABLE if ch == walkable_char else BLOCKED)
        return cls(width=width, height=height, cells=bytes(cells))

    def ascii(self, mark: dict[tuple[int, int], str] | None = None) -> str:
        """Render to ASCII for eyeballing. mark maps (x,y)->char overlay."""
        mark = mark or {}
        lines = []
        for y in range(self.height):
            row = []
            for x in range(self.width):
                if (x, y) in mark:
                    row.append(mark[(x, y)])
                else:
                    row.append("." if self.cells[y * self.width + x] == WALKABLE else "#")
            lines.append("".join(row))
        return "\n".join(lines)
