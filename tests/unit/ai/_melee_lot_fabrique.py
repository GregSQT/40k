"""Fabrique partagée des quatre contrôles analyzer du lot melee-100 (PROJ.1.3.contact,
PROJ.1.4.engagees_inactives, PROJ.1.4.pile_in_engage, PROJ.1.4.conso_toutes_selectionnees).

Géométrie x1 (`inches_to_subhex=1`, socles `round/1`, plateau 44×60) : une case = un pouce,
la zone d'engagement vaut 2 cases, le contact / « within 1" » une case. Les distances hex des
positions utilisées sont MESURÉES par `calculate_hex_distance` dans chaque test (prémisses).
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, Sequence, Tuple

from tests.unit.ai._fabriques import entete_step_log

Cell = Tuple[int, int]


def unit_header(uid: str, player: int, unit_type: str = "AssaultIntercessor", hp_max: int = 4) -> str:
    return (
        f"[10:00:00] Unit {uid} ({unit_type}) P{player}: Starting position (-1,-1), "
        f"HP_MAX={hp_max} base=round/1\n"
    )


def models_segment(uid: str, cells: Sequence[Cell]) -> str:
    return "[MODELS: " + " ".join(f"{uid}#{i}@({c},{r},z0)" for i, (c, r) in enumerate(cells)) + "]"


def deployed(uid: str, player: int, cells: Sequence[Cell]) -> str:
    c, r = cells[0]
    return (
        f"[10:00:01] E1 T1 P{player} DEPLOYMENT : Unit {uid}({c},{r}) DEPLOYED from (-1,-1) to ({c},{r})"
        f" [R:+0.0] {models_segment(uid, cells)} [SUCCESS]\n"
    )


def fought(
    fighter: str, fighter_anchor: Cell, target: str, target_anchor: Cell,
    fighter_cells: Sequence[Cell], shooters: Iterable[str], target_models: Sequence[Cell], player: int = 1,
) -> str:
    fc, fr = fighter_anchor
    tc, tr = target_anchor
    return (
        f"[10:00:03] E1 T1 P{player} FIGHT : Unit {fighter}({fc},{fr}) FOUGHT Unit {target}({tc},{tr})"
        f" with [Close Combat Weapon] - Hit 1(3+) - Wound 1(4+) - Save 6(3+) - Dmg:0HP [R:+0.0]"
        f" [FIGHT_SUBPHASE:fight] {models_segment(fighter, fighter_cells)}"
        f" [SHOOTER_MODELS: {' '.join(shooters)}] [TARGET_DECL:{len(target_models)}] [SUCCESS]\n"
    )


def parse(tmp_path: Any, headers: str, body: str) -> Dict[str, Any]:
    import ai.analyzer as an

    log = tmp_path / "step.log"
    log.write_text(entete_step_log(body, units=headers, inches_to_subhex=1, board="cols=44 rows=60"))
    return an.parse_step_log(str(log))
