"""
NosVoid offline farm-map simulator (Phase 1: build + validate, no RL agent yet).

Layer status:
  grid, pathfind, cooldown  -> VERIFIED deterministic core
  damage                    -> KNOWN formula form; hidden mob stats are fit params
  mob_behavior              -> interface only; profiles fit from observed traces
  logging_schema            -> record shapes for passive normal-play logging
  engine                    -> wires it together; manual-drive step()
  gym_env, scripted_baseline-> Phase-2 scaffold: Gymnasium env + greedy baseline
                               (player side measured; mob dynamics are placeholders)

See the Obsidian vault: architecture/simulator-plan, architecture/logging-schema,
reference/nostale-damage-formula, systems/movement, systems/skills, core/entity.
"""

from .grid import Grid, WALKABLE, BLOCKED
from .pathfind import bfs_path, chebyshev, manhattan
from .entity import Entity, EntityKind, Buff
from .cooldown import SkillDef, CooldownTracker
from .damage import AttackerStats, DefenderStats, compute_damage, expected_hits_to_kill
from .mob_behavior import MobProfile, MobState
from .engine import Simulator, World, SimConfig
from .hp_fit import HpHit, estimate_hp
from . import farm_map_2706 as farm
from .gym_env import FarmClearEnv, EnvConfig          # Phase-2 scaffold (soft gymnasium dep)
from .scripted_baseline import scripted_action, evaluate

__all__ = [
    "Grid", "WALKABLE", "BLOCKED",
    "bfs_path", "chebyshev", "manhattan",
    "Entity", "EntityKind", "Buff",
    "SkillDef", "CooldownTracker",
    "AttackerStats", "DefenderStats", "compute_damage", "expected_hits_to_kill",
    "MobProfile", "MobState",
    "Simulator", "World", "SimConfig",
    "HpHit", "estimate_hp",
    "farm",
    "FarmClearEnv", "EnvConfig", "scripted_action", "evaluate",
]
