"""Guards de move_handler.py : invariants introduits par le fix des findings code-review.

Deux invariants vérifiés (les findings 1 et 2 sont inatteignables via le pipeline normal :
require_key(state.unit_types, actor_id) dans analyzer_core.py lève avant que _handle_fled /
_handle_move ne soit appelé — unit_types et unit_hp sont peuplés de la même ligne header) :

3. FLED avec hp=0 → aucune entrée unit_position_collisions pour l'unité morte
   (avant le fix, la boucle collision tournait hors du guard hp>0 et incluait move_unit_id).

4. Prémisse de 3 : même scénario avec hp>0 → collision bien détectée (le contrôle est vivant).
"""
from __future__ import annotations

import ai.analyzer as an
from tests.unit.ai._fabriques import entete_step_log

# Géométrie x5 (inches_to_subhex=5) — distances volontairement loin des seuils.
P1_START     = (50, 50)
P1_DEST      = (50, 80)   # 30 subhex du départ, dans le budget move M=6"
ENEMY_POS    = (50, 30)   # loin du chemin de P1 (pas d'engagement parasite)
ALLY_AT_DEST = (80, 50)   # allié posé À la destination de P1

OBJECTIVES = ";".join(f"(200,{r})" for r in range(150, 156))

_UNITS_FULL = (
    "[10:00:00] Unit 1 (AssaultIntercessor) P1:"
    " Starting position (-1,-1), HP_MAX=2 base=round/6\n"
    "[10:00:00] Unit 2 (AssaultIntercessor) P1:"
    " Starting position (-1,-1), HP_MAX=2 base=round/6\n"
    "[10:00:00] Unit 101 (AssaultIntercessor) P2:"
    " Starting position (-1,-1), HP_MAX=2 base=round/6\n"
)


_END = (
    "[10:00:09] T2 OBJECTIVE CONTROL: VP1=0 VP2=0 CP1=0 CP2=0 ZONES=rect b NW:Ctrl=none\n"
    "[10:00:10] EPISODE END: Winner=1, Method=objectives, Actions=0, Steps=0, "
    "Total=0, Duration=1.000s\n"
)


def _xy(p):
    return f"({p[0]},{p[1]})"


def _deploy(uid, pos, player=1):
    return (
        f"[10:00:01] E1 T1 P{player} DEPLOYMENT : Unit {uid}{_xy(pos)}"
        f" DEPLOYED from (-1,-1) to {_xy(pos)} [R:+0.0] [SUCCESS]\n"
    )


def _fled_line(uid, frm, to):
    return (
        f"[10:00:02] E1 T2 P1 MOVE : Unit {uid}{_xy(frm)}"
        f" FLED from {_xy(frm)} to {_xy(to)} [R:+0.0] [SUCCESS]\n"
    )


def _move_line(uid, frm, to, player=1):
    return (
        f"[10:00:02] E1 T2 P{player} MOVE : Unit {uid}{_xy(to)}"
        f" MOVED from {_xy(frm)} to {_xy(to)} [R:+0.0] [SUCCESS]\n"
    )


def _build_log(body, units=_UNITS_FULL):
    deploy = (
        _deploy("1", P1_START, player=1)
        + _deploy("2", ALLY_AT_DEST, player=1)
        + _deploy("101", ENEMY_POS, player=2)
    )
    return entete_step_log(
        deploy + body + _END,
        units=units,
        rosters="scale=5 AGENT_PLAYER=1 AGENT=sm (ref) OPPONENT=sm (ref)",
        objectives=OBJECTIVES,
        ez_vertical_inches=None,
        inches_to_subhex=5,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Finding 3 : FLED avec hp=0 → aucune collision spurious
# ─────────────────────────────────────────────────────────────────────────────

def test_fled_dead_unit_does_not_produce_position_collision(tmp_path):
    """Unité morte (hp=0 via state_resync) qui fuit vers un hex occupé par un allié.

    Avant le fix : la boucle de collision (lignes 307-345) tournait hors du guard hp>0 et
    incluait move_unit_id dans l'entrée collision même si l'unité était morte et n'avait jamais
    atteint dest.
    Après le fix : tout le bloc history+collision est dans if unit_hp_value > 0 → 0 collision.

    Scénario :
    1. Unit 1 déployée à P1_START, unit 2 (allié) à ALLY_AT_DEST.
    2. MOVED no-op avec [MODELS:] pour peupler positions_by_model (requis par state_resync).
    3. STATE snapshot omettant unit 1 → state_resync → unit_hp['1']=0.
    4. FLED de unit 1 vers ALLY_AT_DEST (hex occupé par l'allié vivant unit 2).
    """
    move_noop = (
        f"[10:00:01b] E1 T1 P1 MOVE : Unit 1{_xy(P1_START)} MOVED from {_xy(P1_START)}"
        f" to {_xy(P1_START)} [R:+0.0]"
        f" [MODELS: 1#0@({P1_START[0]},{P1_START[1]},z0)] [SUCCESS]\n"
    )
    # STATE sans unit 1 : state_resync → unit_hp['1']=0.
    state_line = (
        f"[10:00:02] T1 STATE:"
        f" 2[2#0@({ALLY_AT_DEST[0]},{ALLY_AT_DEST[1]},z0):2]"
        f" 101[101#0@({ENEMY_POS[0]},{ENEMY_POS[1]},z0):2]\n"
    )
    fled = _fled_line("1", P1_START, ALLY_AT_DEST)

    log = tmp_path / "step.log"
    log.write_text(_build_log(move_noop + state_line + fled))
    stats = an.parse_step_log(str(log))

    spurious = [c for c in stats["unit_position_collisions"] if "1" in c.get("units", [])]
    assert not spurious, (
        f"Une unité morte (hp=0) ne doit pas apparaître dans unit_position_collisions ; "
        f"trouvé : {spurious}"
    )


def test_fled_live_unit_to_occupied_hex_does_produce_position_collision(tmp_path):
    """Prémisse : une unité VIVANTE qui fuit vers un hex allié occupé → collision détectée.

    Sans cette prémisse, 0 collision dans le test dead ne prouve rien (le contrôle pourrait
    être mort). Le scénario est identique au test précédent sans state_resync.
    """
    fled = _fled_line("1", P1_START, ALLY_AT_DEST)

    log = tmp_path / "step.log"
    log.write_text(_build_log(fled))
    stats = an.parse_step_log(str(log))

    has_collision = any("1" in c.get("units", []) for c in stats["unit_position_collisions"])
    assert has_collision, (
        "Une unité VIVANTE qui fuit vers un hex allié occupé doit produire "
        "une entrée unit_position_collisions"
    )
