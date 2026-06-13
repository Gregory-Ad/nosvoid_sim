"""
Logging schema (concrete form of architecture/logging-schema.md).

Source-of-truth principle: DYNAMICS come from the packet stream you receive
during normal play, NOT from entity-memory polling. Damage = 'su' Token[12],
NOT the HP% byte. These dataclasses define the replayable event log you collect
while playing, which then feeds the fit / calibration of the simulator.

This module defines the RECORD SHAPES only. The actual capture (reading your
own client's received packets/memory while you play) is done separately and is
passive observation — no automation, no injection.
"""

from __future__ import annotations
from dataclasses import dataclass, asdict
import json


@dataclass
class SuRecord:
    """
    'su' skill-use / damage result — the core combat tuple (already labelled).

    Token layout CONFIRMED live with a reference target (2026-06-12):
      su [0]atkType [1]atkID [2]tgtType [3]tgtID [4]skillVNUM [5]cooldown
         [6]? [7]const(4523 player/4806 mob) [8]posX [9]posY [10]?
         [11]targetHP%_after [12]DAMAGE [13]hitFlag [14]?

    ⚠️ tgt_id / atk_id are the SERVER entity id (e.g. 36322), which is NOT the
       same as entity+0x00 in memory (that read 4781032 for the same mob). Do
       NOT join packet ids to entity+0x00. Correlate by position/timing, or find
       the offset where the client stores the server id.
    """
    t_ms: int
    atk_type: int      # [0] 1 player / 2 npc / 3 monster
    atk_id: int        # [1] server id of attacker
    tgt_type: int      # [2]
    tgt_id: int        # [3] server id of target (NOT entity+0x00)
    skill_vnum: int    # [4] join to SkillDef
    cooldown: int      # [5]
    pos_x: int         # [8] CONFIRMED = position
    pos_y: int         # [9]
    hp_pct_after: int  # [11] CONFIRMED = target HP% after the hit
    damage: int        # [12] CONFIRMED = the real server-computed damage
    hit_flag: int      # [13] miss/crit classifier (0 normal-ish, 4 seen on misses) — decode later
    # context snapshot (from memory at log time) for fitting:
    atk_level: int | None = None
    tgt_vnum: int | None = None
    tgt_level: int | None = None
    tgt_hp_pct_before: int | None = None


@dataclass
class DieRecord:
    t_ms: int
    victim_type: int
    victim_id: int
    killer_type: int
    killer_id: int


@dataclass
class DropRecord:
    t_ms: int
    item_vnum: int
    is_gold: bool
    x: int
    y: int


@dataclass
class MoveRecord:
    """Other-entity movement over time (mob traces) — for behavior fitting."""
    t_ms: int
    eid: int
    x: int
    y: int


def to_jsonl(records: list) -> str:
    """Serialize a list of record dataclasses to JSON-lines (replayable log)."""
    return "\n".join(json.dumps({"type": type(r).__name__, **asdict(r)}) for r in records)
