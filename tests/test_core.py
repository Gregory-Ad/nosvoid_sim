"""
Smoke tests for the VERIFIED deterministic core. These don't need the game —
they prove the layers we live-verified this session work as coded.
Run: python -m tests.test_core   (from project root)
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nosvoid_sim import (
    Grid, WALKABLE, BLOCKED, bfs_path, chebyshev,
    SkillDef, CooldownTracker,
    AttackerStats, DefenderStats, compute_damage,
)


def test_grid_indexing_and_walkable():
    # 3x2: top row walkable, bottom row a wall in the middle
    g = Grid.from_rows([
        "...",
        ".#.",
    ])
    assert g.width == 3 and g.height == 2
    assert g.is_walkable(0, 0)
    assert not g.is_walkable(1, 1)      # the '#'
    assert g.cell(99, 99) == BLOCKED    # oob -> blocked
    print("grid indexing OK")


def test_grid_from_rle_roundtrip():
    # 0=walkable,1=wall ; matches the live extraction format
    g = Grid.from_rle(4, 2, "0:3,1:1,0:2,1:2")
    assert g.cells == bytes([0, 0, 0, 1, 0, 0, 1, 1])
    assert g.is_walkable(0, 0) and not g.is_walkable(3, 0)
    print("grid RLE roundtrip OK")


def test_bfs_routes_around_wall():
    g = Grid.from_rows([
        ".....",
        ".###.",
        ".....",
    ])
    path = bfs_path(g, (0, 0), (4, 0))
    assert path is not None
    assert path[0] == (0, 0) and path[-1] == (4, 0)
    # every step must be walkable
    assert all(g.is_walkable(x, y) for x, y in path)
    print(f"bfs path len={len(path)} OK")


def test_bfs_unreachable():
    g = Grid.from_rows([
        "...#...",
        "...#...",
        "...#...",
    ])
    # right side is walled off vertically -> still reachable around top/bottom? no,
    # wall spans full height -> unreachable
    assert bfs_path(g, (0, 1), (6, 1)) is None
    print("bfs unreachable detected OK")


def test_cooldown_mechanism():
    # Mirrors the verified mechanism: CD set on use, computed vs now, not ticked.
    ash = SkillDef(vnum=6032, name="Ash Storm", is_damage=True, cast_type=1,
                   mp_cost=50, cooldown_ms=70000, range_tiles=0, aoe_radius=4)
    cd = CooldownTracker()
    assert cd.is_ready(ash, now_ms=0)            # never used -> ready
    cd.mark_used(ash.vnum, now_ms=1000)
    assert not cd.is_ready(ash, now_ms=1000)
    assert cd.remaining_ms(ash, now_ms=1000) == 70000
    assert cd.remaining_ms(ash, now_ms=11000) == 60000   # 10s later -> 60s left
    assert cd.is_ready(ash, now_ms=71000)        # exactly at expiry
    print("cooldown mechanism OK")


def test_damage_known_form_matches_worked_example():
    # Reproduce the OpenNos worked example that matched official = 963.
    # weapon 236-236 (deterministic), skillDmg 85, fairy 80% light(70 attr),
    # mob lvl 0, def 15, attrFactor 1.3.
    atk = AttackerStats(level=99, weapon_min=236, weapon_max=236,
                        skill_damage=85, skill_attribute=70, fairy_percent=80.0)
    dfn = DefenderStats(level=0, defence=15, attribute_factor=1.3)
    dmg = compute_damage(atk, dfn)
    print(f"damage(known-form worked example) = {dmg} (expected 963)")
    assert dmg == 963, f"got {dmg}, expected 963"


def test_farm_2706_profiles_loaded():
    from nosvoid_sim import farm, estimate_hp, HpHit
    assert farm.MAP_ID == 2706
    assert farm.MAP_W == 180 and farm.MAP_H == 130
    assert set(farm.PROFILES.keys()) == {6232, 6233}
    jelly = farm.PROFILES[6232]
    golem = farm.PROFILES[6233]
    assert jelly.aggro_radius == 12 and golem.aggro_radius == 12   # CONFIRMED
    assert golem.hp_max == 345000                                  # CONFIRMED
    assert jelly.hp_max == 300000                                  # FITTED (not the bogus 250)
    assert jelly.name == "Ice Biome Bouncing Jelly"
    assert golem.name == "Ice Biome Ice Golem"
    # HP fitter reproduces the live Jelly estimate (~300k, not 250)
    est = estimate_hp([HpHit(98354, 100, 68), HpHit(98589, 68, 35)])
    assert 290000 < est < 310000, est
    print(f"farm 2706 profiles OK (jelly HP fit ~{round(est)}, golem {golem.hp_max})")


if __name__ == "__main__":
    test_grid_indexing_and_walkable()
    test_grid_from_rle_roundtrip()
    test_bfs_routes_around_wall()
    test_bfs_unreachable()
    test_cooldown_mechanism()
    test_damage_known_form_matches_worked_example()
    test_farm_2706_profiles_loaded()
    print("\nALL CORE TESTS PASSED")
