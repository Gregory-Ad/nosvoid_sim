"""
Entity state model.

GROUND TRUTH (live-verified 2026-06-12, Session 20). Offsets are documented in
core/entity.md (DLL v4.1). We don't replicate raw offsets in the sim's logic —
we model the *meaning*. Offsets are kept here only as provenance comments so the
sim's schema can be traced back to what was read from the client.

Entity lists live on the SceneManager:
    SM+0x0C : players   (mem type byte +0x04 == 1)
    SM+0x10 : monsters  (mem type byte +0x04 == 2)   <- packet 'in 3'
    SM+0x14 : NPC/pet/object catch-all (mem type +0x04 == 3)   <- packet 'in 2'
    SM+0x18 : drops

Per-entity (selected, verified):
    +0x0C / +0x0E : tile x / y (uint16)
    +0xA8         : direction
    +0xAA         : speed
    +0xC8 / +0xC9 : HP% / MP% (byte 0-100)   <- NOTE: % only; absolute HP is server-side
    +0x150/0x151  : level / jobLevel (byte)
    +0x158        : dialog/shop id (NPC discriminator)
    +0x164        : owner entity id (pet/nosmate discriminator)
    +0x1C2        : VNUM (uint16)
    +0x1C4        : NpcDataEntry ptr (baseline static data)
    +0xD4 / +0xD8 : buff vnum list / level list (NOTE: player list can duplicate;
                    for the player use the buff slot widget instead)

CLASSIFICATION (live visually co-verified — pet vs NPC vs object all sit in the
SM+0x14 catch-all, so a THREE-way test is required):
    if owner == a player id   -> PET / NOSMATE
    elif dialog_id > 0        -> interactive NPC
    else                      -> static object / decoration
Monsters are their own list (SM+0x10); players their own (SM+0x0C).
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum


class EntityKind(Enum):
    PLAYER = "player"
    MONSTER = "monster"
    NPC = "npc"
    PET = "pet"
    OBJECT = "object"
    DROP = "drop"


@dataclass
class Buff:
    vnum: int
    remaining_ms: int          # from buff slot widget +0x10C/+0x114 (player)
    duration_ms: int


@dataclass
class Entity:
    eid: int
    kind: EntityKind
    vnum: int
    x: int
    y: int
    # resources. For the PLAYER we hold absolute values (readable: StatsWidget bars).
    # For mobs the client only exposes hp_pct; absolute mob HP is server-side and
    # must be FIT from logged damage (see reference/nostale-damage-formula.md).
    hp_pct: float = 100.0
    mp_pct: float = 100.0
    hp: int | None = None       # absolute, player only (or fitted mob max)
    hp_max: int | None = None
    mp: int | None = None
    mp_max: int | None = None
    level: int = 1
    job_level: int = 0
    direction: int = 0
    owner_eid: int | None = None     # set for pets/nosmates
    dialog_id: int = 0               # >0 for interactive NPCs
    buffs: list[Buff] = field(default_factory=list)
    alive: bool = True

    @staticmethod
    def classify(mem_type: int, owner_eid: int | None, dialog_id: int) -> EntityKind:
        """The verified three-way (plus list-type) classifier."""
        if mem_type == 1:
            return EntityKind.PLAYER
        if mem_type == 2:
            return EntityKind.MONSTER
        # mem_type == 3 : catch-all list -> disambiguate
        if owner_eid is not None and owner_eid != 0:
            return EntityKind.PET
        if dialog_id > 0:
            return EntityKind.NPC
        return EntityKind.OBJECT
