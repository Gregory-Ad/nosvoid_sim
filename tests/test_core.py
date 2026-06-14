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
    assert jelly.aggro_radius == 12 and golem.aggro_radius == 12   # MEASURED-S26 (~12, distance-only/through-walls)
    # S24: both 307705 HP (CONFIRMED via st maxHP); difference between mobs is DAMAGE TAKEN.
    assert jelly.hp_max == 307705 and golem.hp_max == 307705
    assert jelly.player_dmg_base == 101000                         # MEASURED-S21 (non-crit)
    assert golem.player_dmg_base == 52000                          # MEASURED-S21 (~half -> ~2x hits)
    assert jelly.name == "Ice Biome Bouncing Jelly"
    assert golem.name == "Ice Biome Ice Golem"
    # HP fitter reproduces a ~306k estimate from the live hits
    est = estimate_hp([HpHit(98354, 100, 68), HpHit(98589, 68, 35)])
    assert 290000 < est < 312000, est
    print(f"farm 2706 profiles OK (both HP ~306k; jelly fit ~{round(est)})")


def test_autoattack_skill_params():
    # S27: targeted AoE "Magma Ball"; recast cycle 1356ms (cast+CD), ROOTED cast 600ms, range 9, AoE r2.
    from nosvoid_sim import farm
    aa = farm.AUTOATTACK
    assert aa.cooldown_ms == 1356 and aa.cast_time_ms == 600
    assert aa.range_tiles == 9 and aa.aoe_radius == 2
    assert farm.CRIT_MULTIPLIER == 2.0
    print("autoattack params OK (recast 1356, rooted cast 600, range 9, AoE r2, crit x2)")


def test_targeted_aoe_hits_cluster_not_player():
    # SESSION 21: the blast hits mobs within radius 2 of the TARGET, not the player.
    from nosvoid_sim import Simulator, World, Entity, EntityKind, farm
    from nosvoid_sim.grid import Grid
    g = Grid.from_rows(["." * 40] * 40)
    player = Entity(eid=0, kind=EntityKind.PLAYER, vnum=0, x=10, y=10,
                    hp=farm.PLAYER_HP_MAX, hp_max=farm.PLAYER_HP_MAX, level=99)
    mk = lambda eid, vn, x, y: Entity(eid=eid, kind=EntityKind.MONSTER, vnum=vn, x=x, y=y,
                                      hp=farm.PROFILES[vn].hp_max, hp_max=farm.PROFILES[vn].hp_max)
    mobs = [
        mk(1, 6232, 16, 10),   # the TARGET (dist 6 from player, within range 9)
        mk(2, 6233, 17, 11),   # dist 1 from target -> hit
        mk(3, 6232, 18, 10),   # dist 2 from target -> hit
        mk(4, 6232, 19, 10),   # dist 3 from target -> NOT hit
        mk(5, 6232, 10, 11),   # right next to PLAYER, dist 6 from target -> NOT hit
    ]
    world = World(grid=g, player=player, mobs=mobs,
                  skills={farm.AUTOATTACK.vnum: farm.AUTOATTACK},
                  profiles=farm.PROFILES, crit_rate=0.0, crit_mult=2.0)
    out = Simulator(world).cast(farm.AUTOATTACK.vnum, target_eid=1)
    hit_eids = {h["eid"] for h in out["hits"]}
    assert hit_eids == {1, 2, 3}, hit_eids          # only within r2 of the TARGET
    assert 5 not in hit_eids                          # mob next to player NOT hit
    print(f"targeted AoE OK (hit {sorted(hit_eids)}, target-centred, r2)")


def test_per_target_crit_and_damage():
    # crit_rate=0 -> exactly base; crit_rate=1 -> exactly 2x base; per mob type.
    from nosvoid_sim import Simulator, World, Entity, EntityKind, farm
    from nosvoid_sim.grid import Grid
    g = Grid.from_rows(["." * 10] * 10)
    def dmg(vn, crit_rate):
        player = Entity(eid=0, kind=EntityKind.PLAYER, vnum=0, x=1, y=1,
                        hp=farm.PLAYER_HP_MAX, hp_max=farm.PLAYER_HP_MAX, level=99)
        mob = Entity(eid=1, kind=EntityKind.MONSTER, vnum=vn, x=2, y=1,
                     hp=farm.PROFILES[vn].hp_max, hp_max=farm.PROFILES[vn].hp_max)
        w = World(grid=g, player=player, mobs=[mob],
                  skills={farm.AUTOATTACK.vnum: farm.AUTOATTACK},
                  profiles=farm.PROFILES, crit_rate=crit_rate, crit_mult=2.0)
        return Simulator(w).cast(farm.AUTOATTACK.vnum, 1)["hits"][0]["damage"]
    assert dmg(6232, 0.0) == 101000 and dmg(6232, 1.0) == 202000   # Jelly
    assert dmg(6233, 0.0) == 52000 and dmg(6233, 1.0) == 104000    # Golem
    print("per-target crit OK (Jelly 101k/202k, Golem 52k/104k)")


def test_build_world_runs():
    from nosvoid_sim import Simulator, farm
    w = farm.build_world()
    assert len(w.mobs) == farm.MOB_COUNT
    assert farm.AUTOATTACK.vnum in w.skills
    assert Simulator(w).mobs_remaining() == 90
    print("build_world OK (90 mobs, autoattack wired)")


def test_gym_env_and_baseline_smoke():
    # Phase-2 scaffold: env resets, scripted baseline clears a tiny clustered world.
    import random
    from nosvoid_sim import Entity, EntityKind, Grid, World, farm
    from nosvoid_sim.gym_env import FarmClearEnv, EnvConfig, OBS_DIM
    from nosvoid_sim.scripted_baseline import scripted_action

    def tiny():
        g = Grid.from_rows(["." * 24] * 24)
        player = Entity(eid=0, kind=EntityKind.PLAYER, vnum=0, x=12, y=12,
                        hp=farm.PLAYER_HP_MAX, hp_max=farm.PLAYER_HP_MAX, level=99)
        R = random.Random(3); mobs = []; eid = 1
        for _ in range(6):
            vn = R.choice([6232, 6233]); x = 12 + R.randint(-2, 2); y = 12 + R.randint(-2, 2)
            mobs.append(Entity(eid=eid, kind=EntityKind.MONSTER, vnum=vn, x=x, y=y,
                               hp=farm.PROFILES[vn].hp_max, hp_max=farm.PROFILES[vn].hp_max)); eid += 1
        return World(grid=g, player=player, mobs=mobs,
                     skills={farm.AUTOATTACK.vnum: farm.AUTOATTACK}, profiles=farm.PROFILES,
                     crit_rate=0.0, crit_mult=2.0)

    env = FarmClearEnv(world_factory=tiny, config=EnvConfig(max_steps=500))
    obs, info = env.reset(seed=0)
    assert len(obs) == OBS_DIM
    terminated = truncated = False; total_kills = 0; ret = 0.0
    while not (terminated or truncated):
        obs, r, terminated, truncated, info = env.step(scripted_action(env))
        ret += r; total_kills += info["killed"]
    assert info["cleared"], info          # a clustered tiny world should clear
    assert total_kills == 6
    print(f"gym env + baseline smoke OK (cleared 6 mobs, return {ret:.0f})")


if __name__ == "__main__":
    test_grid_indexing_and_walkable()
    test_grid_from_rle_roundtrip()
    test_bfs_routes_around_wall()
    test_bfs_unreachable()
    test_cooldown_mechanism()
    test_damage_known_form_matches_worked_example()
    test_farm_2706_profiles_loaded()
    test_autoattack_skill_params()
    test_targeted_aoe_hits_cluster_not_player()
    test_per_target_crit_and_damage()
    test_build_world_runs()
    test_gym_env_and_baseline_smoke()
    print("\nALL CORE TESTS PASSED")
