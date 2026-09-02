"""Ligne DEAD sans [MODELS:] retire le modèle de positions_by_model immédiatement.

Avant le fix, un modèle tué via ALLOC_MODEL restait dans `pending_model_removals` et
dans `positions_by_model` jusqu'à ce qu'un AUTRE acteur émette `[MODELS:]`. Si l'unité
n'avait qu'UN seul modèle et que personne d'autre n'agissait ensuite avec `[MODELS:]`,
le modèle restait indéfiniment comme « fantôme ».

Conséquence mesurée : au STATE snapshot, l'unité est absente du moteur mais l'analyzer
voit encore ses coordonnées dans `positions_by_model` (hp > 0, sur le terrain) → le
contrôle `dead_missed` incrémente. Avec le fix, le handler DEAD purge le socle avant
le STATE → `dead_missed == 0`.

Scénario 1 (dead_missed) :
  - Unit 1 (Warboss, 6HP) déployé avec [MODELS: 1#0@...]
  - Unit 102 (Intercessor) tire sur Unit 1 : Dmg:1HP → unit_hp["1"] = 5 (vivant côté analyzer)
  - Ligne DEAD: "Unit 1 DEAD model=1#0" SANS [MODELS:]  ← le ghost serait créé ici sans fix
  - T1 STATE: ne mentionne QUE unit 102 (unit 1 disparue côté moteur)
  - Sans fix : positions_by_model["1"] contient encore 1#0 → dead_missed = 1
  - Avec fix : positions_by_model["1"] est purgé par DEAD → dead_missed = 0

Scénario 2 (charge + dead + consolidation) :
  - Unit 1 (P1) charge Unit 101 (P2), CHARGED sans [MODELS:] → charge_handler vide
    positions_by_model["1"]. unit_hp["1"] > 0 (vivant). Ancre figée à (100,100).
  - DEAD unit 1 : _pbm = None (charge_handler a déjà purgé) → sans le fix,
    unit_hp["1"] reste > 0 et l'ancre (100,100) entre dans occupied_positions du BFS.
  - Unit 2 (P2) consolide de (100,92) à (100,107) : chemin direct = 15 subhex = budget.
    Le détour autour de (100,100) coûte 16 > 15 → faux positif fight_move_invalid sans fix.
  - Avec fix (elif _dead_uid in unit_hp and unit_hp > 0) : unit_hp["1"] = 0 → ancre ignorée
    par le BFS → chemin direct = 15 ≤ 15 → fight_move_invalid = 0.
"""
from __future__ import annotations

from tests.unit.ai._fabriques import entete_step_log

WARBOSS = (30, 20)
INTERCESSOR = (50, 50)
W = f"({WARBOSS[0]},{WARBOSS[1]})"
I = f"({INTERCESSOR[0]},{INTERCESSOR[1]})"

_UNITS = (
    "[10:00:00] Unit 1 (Warboss) P2: Starting position (-1,-1), HP_MAX=6 base=round/20\n"
    "[10:00:00] Unit 102 (Intercessor) P1: Starting position (-1,-1), HP_MAX=2 base=round/6\n"
)

_DEPLOY = (
    f"[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 1{W} DEPLOYED from (-1,-1) to {W}"
    f" [R:+0.0] [MODELS: 1#0@({WARBOSS[0]},{WARBOSS[1]},z0)] [SUCCESS]\n"
    f"[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 102{I} DEPLOYED from (-1,-1) to {I}"
    f" [R:+0.0] [MODELS: 102#0@({INTERCESSOR[0]},{INTERCESSOR[1]},z0)] [SUCCESS]\n"
)

# Tir avec Dmg:1HP → unit_hp["1"] = 5 (Warboss toujours vivant côté analyzer)
# ALLOC_MODEL présent mais n'entre pas dans pending_model_removals (grammar < 6)
_SHOOT = (
    f"[10:00:02] E1 T1 P1 SHOOT : Unit 102{I} SHOT Unit 1{W} with [Bolt Rifle]"
    " - Hit 5(3+) - Wound 4(4+) - Save 1(4+) - Dmg:1HP [R:+0.0]"
    f" [MODELS: 102#0@({INTERCESSOR[0]},{INTERCESSOR[1]},z0)]"
    " [SHOOTER_MODELS: 102#0] [SUCCESS]\n"
)

# DEAD sans [MODELS:] : c'est le seul modèle, unit 1 disparaît côté moteur
_DEAD = (
    f"[10:00:03] E1 T1 P2 SHOOT : Unit 1{W} DEAD model=1#0 reason=combat [SUCCESS]\n"
)

# T1 STATE: ne mentionne que unit 102 (unit 1 morte côté moteur)
# Format : <unit_id>[<model_id>@(col,row,z?):<pv>]
_STATE = (
    f"[10:00:04] T1 STATE:"
    f" 102[102#0@({INTERCESSOR[0]},{INTERCESSOR[1]}):2]\n"
)


def test_dead_event_retire_le_modele_de_positions_by_model(tmp_path):
    """Après DEAD sans [MODELS:], le fantôme n'est plus dans positions_by_model."""
    import ai.analyzer as an

    log = tmp_path / "step.log"
    log.write_text(
        entete_step_log(
            _DEPLOY + _SHOOT + _DEAD + _STATE,
            units=_UNITS,
            ez_vertical_inches=None,
        )
    )
    stats = an.parse_step_log(str(log))
    # dead_missed = unités vivantes côté analyzer (positions on-board) absentes du STATE.
    # Sans fix : 1#0 reste dans positions_by_model → unit 1 = ghost → dead_missed = 1.
    # Avec fix  : DEAD retire 1#0 → positions_by_model["1"] vide → dead_missed = 0.
    assert stats["state_resync"]["dead_missed"] == 0, (
        f"dead_missed={stats['state_resync']['dead_missed']} : "
        "le fantôme 1#0 est encore dans positions_by_model après la ligne DEAD"
    )


# ---------------------------------------------------------------------------
# Scénario 2 : CHARGED (sans [MODELS:]) + DEAD + CONSOLIDATED
# ---------------------------------------------------------------------------
# charge_handler.pop() vide positions_by_model["1"] avant les DEAD events.
# Sans le fix : unit_hp["1"] > 0 → ancre (100,100) dans occupied_positions du BFS.
# Chemin direct (100,92)→(100,107) = 15 subhex = budget 3"×5.
# Détour autour de (100,100) : +1 subhex = 16 > 15 → faux positif fight_move_invalid.

_CH_ANCHOR = (100, 100)   # ancre finale du chargeur P1
_CH_TARGET = (100, 92)    # cible de la charge (P2), aussi anchor_from de la consolidation
_CONS_DEST = (100, 107)   # destination de la consolidation (P2)
_CONS_DEPLOY = (100, 80)  # déploiement du consolidateur (P2)

CHA = f"({_CH_ANCHOR[0]},{_CH_ANCHOR[1]})"
CHT = f"({_CH_TARGET[0]},{_CH_TARGET[1]})"
CDST = f"({_CONS_DEST[0]},{_CONS_DEST[1]})"
CDPL = f"({_CONS_DEPLOY[0]},{_CONS_DEPLOY[1]})"

_UNITS_CH = (
    "[10:00:00] Unit 1 (AssaultIntercessor) P1: Starting position (-1,-1), HP_MAX=4 base=round/6\n"
    "[10:00:00] Unit 2 (AssaultIntercessor) P2: Starting position (-1,-1), HP_MAX=4 base=round/6\n"
    "[10:00:00] Unit 101 (AssaultIntercessor) P2: Starting position (-1,-1), HP_MAX=4 base=round/6\n"
)

_DEPLOY_CH = (
    f"[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1(100,110) DEPLOYED from (-1,-1) to (100,110)"
    f" [R:+0.0] [MODELS: 1#0@(100,110,z0)] [SUCCESS]\n"
    f"[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 101{CHT} DEPLOYED from (-1,-1) to {CHT}"
    f" [R:+0.0] [MODELS: 101#0@({_CH_TARGET[0]},{_CH_TARGET[1]},z0)] [SUCCESS]\n"
    f"[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 2{CDPL} DEPLOYED from (-1,-1) to {CDPL}"
    f" [R:+0.0] [MODELS: 2#0@({_CONS_DEPLOY[0]},{_CONS_DEPLOY[1]},z0)] [SUCCESS]\n"
)

# CHARGED sans [MODELS:] → charge_handler vide positions_by_model["1"].
# (100,110)→(100,100) = 10 subhex = 2" ; Roll:2 → budget 10. Distance ≤ budget ✓.
_CHARGED_CH = (
    f"[10:00:02] E1 T1 P1 CHARGE : Unit 1{CHA} CHARGED Unit 101{CHT}"
    f" from (100,110) to {CHA} [Roll: 2] [Dist: 2.0\" | Nearest: 2.0\"] [R:+0.0] [SUCCESS]\n"
)

# DEAD en phase FIGHT, player P1 (propriétaire de l'unité). _pbm = None → élif fix.
_DEAD_CH = (
    f"[10:00:03] E1 T1 P1 FIGHT : Unit 1{CHA} DEAD model=1#0 reason=combat [SUCCESS]\n"
)

# Consolidation P2 de (100,92) à (100,107) : 15 subhex direct, 16 avec ancre bloquée.
_CONSOLIDATED_CH = (
    f"[10:00:04] E1 T1 P2 FIGHT : Unit 2{CDST} CONSOLIDATED from {CHT} to {CDST}"
    f" [R:+0.0] [SUCCESS]\n"
)


def test_charge_dead_consolidated_no_fight_move_invalid(tmp_path):
    """CHARGED sans [MODELS:] + DEAD : l'ancre fantôme du chargeur ne bloque plus le BFS de consolidation."""
    import ai.analyzer as an

    log = tmp_path / "step.log"
    log.write_text(
        entete_step_log(
            _DEPLOY_CH + _CHARGED_CH + _DEAD_CH + _CONSOLIDATED_CH,
            units=_UNITS_CH,
            ez_vertical_inches=None,
        )
    )
    stats = an.parse_step_log(str(log))
    # Sans fix : unit_hp["1"] > 0 → ancre (100,100) dans occupied → BFS = 16 > 15 → violation.
    # Avec fix : unit_hp["1"] = 0 → ancre ignorée → BFS = 15 ≤ 15 → pas de violation.
    assert stats["fight_move_invalid"]["consolidation"][2] == 0, (
        f"fight_move_invalid consolidation P2={stats['fight_move_invalid']['consolidation'][2]} : "
        "l'ancre fantôme du chargeur (unit_hp non remis à 0 par l'elif) bloque le BFS de consolidation"
    )
