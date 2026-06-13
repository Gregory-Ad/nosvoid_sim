"""
Visual validation environment for the NosVoid farm-map simulator (Phase 1).

A top-down, manually-controlled window (like the schematic views in RL demos).
You drive the agent; mobs aggro/chase/attack using the LIVE-VERIFIED numbers.
Put this window next to the real game and check they behave the same.

CONTROLS
  Arrow keys / WASD ... move the agent one tile (hold to repeat)
  SPACE .............. attack the nearest mob in range
  R .................. reset (respawn all mobs, restore HP)
  ESC ................ quit

WHAT'S MODELLED (all from live-verified data — see farm_map_2706.py / vault):
  - real collision grid of map 2706 (walkable vs blocked)
  - 90 mobs (45 Bouncing Jelly 6232, 45 Ice Golem 6233) at real spawn points
  - aggro radius = 12 tiles (confirmed): a mob starts chasing within 12
  - chase: aggroed mob steps toward you; attacks when adjacent
  - your damage ~98k-197k/hit (random in range); mob HP Jelly~300k, Golem 345k
  - mob damage to you = 465/hit; your HP = 54754
  - skill cooldown respected (basic skill ~ short CD)

This is a VALIDATION tool, not the agent. No RL here. Run:
    pip install pygame
    python -m nosvoid_sim.visualize       (from the project root)
"""

from __future__ import annotations
import random
import sys

try:
    import pygame
except ImportError:
    print("pygame not installed. Run:  pip install pygame")
    sys.exit(1)

from .grid import Grid
from .pathfind import chebyshev
from . import _map2706_data as M

# ---- tuning (from verified data) ----
AGGRO = 12                 # CONFIRMED tiles
PLAYER_HP_MAX = 54754      # CONFIRMED
PLAYER_DMG = (98000, 197000)   # CONFIRMED range per hit
MOB_DMG = 465              # CONFIRMED per hit
HP = {6232: 300000, 6233: 345000}     # 6232 FITTED, 6233 CONFIRMED
NAME = {6232: "Bouncing Jelly", 6233: "Ice Golem"}
COLOR = {6232: (90, 200, 255), 6233: (170, 95, 225)}
ATTACK_RANGE = {6232: 1, 6233: 2}      # TABLE-BASELINE basicRange
PLAYER_ATTACK_RANGE = 3                # your skill reach (approx; tune vs game)
MOB_STEP_MS = 600          # how often an aggroed mob steps (rough; tune)
MOB_ATTACK_MS = 1000       # how often a mob hits you when adjacent (TODO measure)
PLAYER_CD_MS = 700         # your basic-skill cooldown (rough; tune)

CELL = 6                   # pixels per tile
HUD_H = 96
BG = (16, 18, 24)
WALK = (40, 44, 54)
WALL = (70, 80, 100)
PLAYER_COL = (255, 220, 0)


class Mob:
    __slots__ = ("vnum", "x", "y", "hp", "hp_max", "alive", "aggro", "last_step", "last_atk")
    def __init__(self, vnum, x, y):
        self.vnum = vnum
        self.x, self.y = x, y
        self.hp_max = HP[vnum]
        self.hp = self.hp_max
        self.alive = True
        self.aggro = False
        self.last_step = 0
        self.last_atk = 0


class VizWorld:
    def __init__(self):
        self.grid = Grid.from_rle(M.MAP_W, M.MAP_H, M.GRID_RLE)
        self.reset()

    def reset(self):
        self.px, self.py = M.PLAYER_START
        # ensure player starts on a walkable tile
        if not self.grid.is_walkable(self.px, self.py):
            self.px, self.py = self._nearest_walkable(self.px, self.py)
        self.php = PLAYER_HP_MAX
        self.mobs = [Mob(v, x, y) for (v, x, y) in M.SPAWNS]
        self.last_cast = -99999
        self.log = ["reset — clear the map!"]

    def _nearest_walkable(self, x, y):
        for r in range(1, 20):
            for dx in range(-r, r + 1):
                for dy in range(-r, r + 1):
                    if self.grid.is_walkable(x + dx, y + dy):
                        return x + dx, y + dy
        return x, y

    def alive_mobs(self):
        return [m for m in self.mobs if m.alive]

    def try_move(self, dx, dy):
        nx, ny = self.px + dx, self.py + dy
        if self.grid.is_walkable(nx, ny):
            self.px, self.py = nx, ny

    def attack(self, now):
        if now - self.last_cast < PLAYER_CD_MS:
            return
        # nearest alive mob within player range
        target = None
        best = 999
        for m in self.alive_mobs():
            d = chebyshev((self.px, self.py), (m.x, m.y))
            if d <= PLAYER_ATTACK_RANGE and d < best:
                best, target = d, m
        if not target:
            return
        self.last_cast = now
        dmg = random.randint(*PLAYER_DMG)
        target.hp -= dmg
        if target.hp <= 0:
            target.alive = False
            self.log.append(f"killed {NAME[target.vnum]} (hit {dmg})")
        else:
            pct = int(target.hp / target.hp_max * 100)
            self.log.append(f"hit {NAME[target.vnum]} {dmg} -> {pct}%")
        self.log = self.log[-6:]

    def update_mobs(self, now):
        for m in self.alive_mobs():
            d = chebyshev((self.px, self.py), (m.x, m.y))
            if not m.aggro and d <= AGGRO:
                m.aggro = True
            if not m.aggro:
                continue
            rng = ATTACK_RANGE[m.vnum]
            if d <= rng:
                # in range: attack on cadence
                if now - m.last_atk >= MOB_ATTACK_MS:
                    m.last_atk = now
                    self.php = max(0, self.php - MOB_DMG)
                    if self.php == 0:
                        self.log.append("YOU DIED — press R")
                        self.log = self.log[-6:]
            else:
                # chase: step toward player on cadence
                if now - m.last_step >= MOB_STEP_MS:
                    m.last_step = now
                    sx = (self.px > m.x) - (self.px < m.x)
                    sy = (self.py > m.y) - (self.py < m.y)
                    if self.grid.is_walkable(m.x + sx, m.y + sy):
                        m.x += sx; m.y += sy
                    elif self.grid.is_walkable(m.x + sx, m.y):
                        m.x += sx
                    elif self.grid.is_walkable(m.x, m.y + sy):
                        m.y += sy


def run():
    pygame.init()
    w = VizWorld()
    W = M.MAP_W * CELL
    H = M.MAP_H * CELL + HUD_H
    screen = pygame.display.set_mode((W, H))
    pygame.display.set_caption("NosVoid Sim — Map 2706 (Phase 1 validation)")
    font = pygame.font.SysFont("consolas", 13)
    bigfont = pygame.font.SysFont("consolas", 16, bold=True)
    clock = pygame.time.Clock()

    # pre-render the static grid to a surface (fast)
    grid_surf = pygame.Surface((W, M.MAP_H * CELL))
    grid_surf.fill(BG)
    for y in range(M.MAP_H):
        for x in range(M.MAP_W):
            col = WALK if w.grid.is_walkable(x, y) else WALL
            pygame.draw.rect(grid_surf, col, (x * CELL, y * CELL, CELL - 1, CELL - 1))

    move_cd = 0
    running = True
    while running:
        now = pygame.time.get_ticks()
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                running = False
            elif e.type == pygame.KEYDOWN:
                if e.key == pygame.K_ESCAPE:
                    running = False
                elif e.key == pygame.K_r:
                    w.reset()
                elif e.key == pygame.K_SPACE:
                    w.attack(now)

        # held movement keys (repeat with a small cooldown)
        keys = pygame.key.get_pressed()
        if now - move_cd > 90:
            dx = dy = 0
            if keys[pygame.K_LEFT] or keys[pygame.K_a]:  dx = -1
            if keys[pygame.K_RIGHT] or keys[pygame.K_d]: dx = 1
            if keys[pygame.K_UP] or keys[pygame.K_w]:    dy = -1
            if keys[pygame.K_DOWN] or keys[pygame.K_s]:  dy = 1
            if dx or dy:
                w.try_move(dx, dy)
                move_cd = now

        w.update_mobs(now)

        # ---- draw ----
        screen.fill(BG)
        screen.blit(grid_surf, (0, 0))

        # aggro radius ring around player (visual aid)
        pygame.draw.circle(screen, (60, 70, 90),
                           (w.px * CELL + CELL // 2, w.py * CELL + CELL // 2),
                           AGGRO * CELL, 1)

        for m in w.mobs:
            if not m.alive:
                continue
            cx, cy = m.x * CELL + CELL // 2, m.y * CELL + CELL // 2
            col = COLOR[m.vnum]
            if m.aggro:
                pygame.draw.circle(screen, (255, 60, 60), (cx, cy), CELL // 2 + 2, 1)
            pygame.draw.circle(screen, col, (cx, cy), CELL // 2 + 1)
            # tiny HP bar if damaged
            if m.hp < m.hp_max:
                fr = m.hp / m.hp_max
                pygame.draw.rect(screen, (50, 50, 50), (cx - 6, cy - 8, 12, 2))
                pygame.draw.rect(screen, (90, 220, 90), (cx - 6, cy - 8, int(12 * fr), 2))

        # player
        pcx, pcy = w.px * CELL + CELL // 2, w.py * CELL + CELL // 2
        pygame.draw.circle(screen, PLAYER_COL, (pcx, pcy), CELL // 2 + 2)
        pygame.draw.circle(screen, (0, 0, 0), (pcx, pcy), CELL // 2 + 2, 1)

        # ---- HUD ----
        hud_y = M.MAP_H * CELL
        pygame.draw.rect(screen, (10, 11, 15), (0, hud_y, W, HUD_H))
        alive = len(w.alive_mobs())
        jelly = sum(1 for m in w.alive_mobs() if m.vnum == 6232)
        golem = sum(1 for m in w.alive_mobs() if m.vnum == 6233)
        # player HP bar
        hpfr = w.php / PLAYER_HP_MAX
        pygame.draw.rect(screen, (60, 30, 30), (10, hud_y + 10, 240, 16))
        pygame.draw.rect(screen, (220, 70, 70), (10, hud_y + 10, int(240 * hpfr), 16))
        screen.blit(font.render(f"HP {w.php}/{PLAYER_HP_MAX}", True, (255, 255, 255)), (14, hud_y + 11))
        cd_left = max(0, PLAYER_CD_MS - (now - w.last_cast))
        screen.blit(font.render(f"pos ({w.px},{w.py})   attack CD {cd_left}ms", True, (200, 200, 210)), (260, hud_y + 11))
        screen.blit(bigfont.render(f"mobs left: {alive}   (Jelly {jelly} / Golem {golem})", True, (255, 230, 120)), (10, hud_y + 34))
        # event log
        for i, line in enumerate(w.log[-3:]):
            screen.blit(font.render(line, True, (170, 200, 170)), (10, hud_y + 56 + i * 13))
        # controls hint
        screen.blit(font.render("WASD/arrows move | SPACE attack | R reset | ESC quit",
                                True, (120, 130, 140)), (W - 430, hud_y + 11))

        pygame.display.flip()
        clock.tick(60)

    pygame.quit()


if __name__ == "__main__":
    run()
