"""Verrou : DEAD après charge+pile-in ne laisse pas d'ancre-fantôme dans le BFS.

SCÉNARIO
  Unit 1 (A, P1) charge Unit 101 (B, P2).
  charge_handler efface positions_by_model["1"] (charge_handler.py:348).
  A pile-in : fight_handler efface positions_by_model["1"] à nouveau (fight_handler.py:605).
  B attaque A (FOUGHT line, [MODELS: B]) → A's last model dies (DEAD event) :
    _pbm = positions_by_model.get("1") → None (effacé par pile-in, non restauré)
    AVANT FIX : la branche `if _pbm is not None` ne s'exécute pas → unit_hp["1"] reste > 0
    APRÈS FIX : elif unit_models_alive atteint 0 → unit_hp["1"] = 0
  B consolide de (54,50) à (52,50), seul chemin disponible = (54,50)→(53,50)→(52,50).
    AVANT FIX : (53,50) fantôme dans occupied_positions (unit_hp["1"] > 0) → transit bloqué
                → BFS ne trouve aucun chemin ≤ 3 → fight_move_invalid : faux positif.
    APRÈS FIX : A morte → (53,50) pas dans occupied_positions → BFS réussit → 0 violation.

Géométrie (scale x1 : 1 subhex = 1 inch, EZ = 2 subhex, col 54 pair) :
  Voisins de (54,50) [col pair] : (54,49)N, (55,49)NE, (55,50)SE, (54,51)S, (53,50)SW, (53,49)NW.
  Voisins de (52,50) [col pair] : (52,49)N, (53,49)NE, (53,50)SE, (52,51)S, (51,50)SW, (51,49)NW.
  Les deux seuls hex à 1 pas de (54,50) ET adjacents à (52,50) sont (53,50) et (53,49).
  Mur en (53,49) → l'unique chemin ≤ 3 vers (52,50) passe par (53,50).
"""
from __future__ import annotations

import ai.analyzer as an
from tests.unit.ai._fabriques import entete_step_log, EPISODE_TAIL

_UNITS = (
    "[10:00:00] Unit 1 (Intercessor) P1: Starting position (-1,-1), HP_MAX=2 "
    "[MODELS: 1#0@(50,50,z0)]\n"
    "[10:00:00] Unit 101 (AssaultIntercessor) P2: Starting position (-1,-1), HP_MAX=2 "
    "[MODELS: 101#0@(54,50,z0)]\n"
)

_BODY = (
    # Déploiements
    "[10:00:01] E1 T1 P1 DEPLOYMENT : Unit 1(50,50) DEPLOYED from (-1,-1) to (50,50) "
    "[MODELS: 1#0@(50,50,z0)] [R:+0.0] [SUCCESS]\n"
    "[10:00:01] E1 T1 P2 DEPLOYMENT : Unit 101(54,50) DEPLOYED from (-1,-1) to (54,50) "
    "[MODELS: 101#0@(54,50,z0)] [R:+0.0] [SUCCESS]\n"
    # A charge B — charge_handler efface positions_by_model["1"]
    # [MODELS:] sur la ligne CHARGED → current_line_models["1"] = {1#0@(52,50)}
    "[10:00:03] E1 T1 P1 CHARGE : Unit 1(52,50) CHARGED Unit 101(54,50) "
    "from (50,50) to (52,50) [Roll:2] [R:+0.0] [MODELS: 1#0@(52,50,z0)] [SUCCESS]\n"
    # A pile-in vers (53,50) — fight_handler.py:605 efface positions_by_model["1"]
    # La ligne PILED IN ne porte PAS de [MODELS:] (comment fight_handler.py:603).
    # Au début du traitement de cette ligne, current_line_models["1"] (de la ligne
    # CHARGED) est fusionné → positions_by_model["1"] = {1#0@(52,50)}.
    # Puis fight_handler pop → positions_by_model["1"] = None de nouveau.
    # Format correct : pas de cible dans PILED IN (contrairement à FOUGHT).
    "[10:00:04] E1 T1 P1 FIGHT : Unit 1(53,50) PILED IN "
    "from (52,50) to (53,50) [R:+0.0] [SUCCESS]\n"
    # B attaque A (FOUGHT) — la ligne porte [MODELS:] de B uniquement.
    # Au début du traitement : current_line_models (vide, pas de [MODELS:] sur PILED IN)
    # → rien fusionné pour "1" → positions_by_model["1"] reste None.
    # A's last model dies on this line.
    "[10:00:05] E1 T1 P2 FIGHT : Unit 101(54,50) FOUGHT Unit 1(53,50) "
    "[R:+0.0] [MODELS: 101#0@(54,50,z0)] [SUCCESS]\n"
    "[10:00:05] E1 T1 P1 FIGHT : Unit 1(53,50) DEAD model=1#0 reason=combat [SUCCESS]\n"
    # B consolide de (54,50) à (52,50). Seul chemin ≤ 3 disponible : (54,50)→(53,50)→(52,50).
    # (53,49) est muré → pas d'alternative. Sans le fix : (53,50) dans occupied_positions
    # (unit_hp["1"] > 0) → transit bloqué → BFS échoue → fight_move_invalid : faux positif.
    "[10:00:06] E1 T1 P2 FIGHT : Unit 101(52,50) CONSOLIDATED "
    "from (54,50) to (52,50) [R:+0.0] [SUCCESS]\n"
)


# (53,49) est le seul hex voisin de (54,50) ET adjacent à (52,50) autre que (53,50).
# Le murer force l'unique chemin ≤ 3 vers (52,50) à transiter par (53,50) — l'ancre fantôme.
_LOG = entete_step_log(
    _BODY + EPISODE_TAIL,
    inches_to_subhex=1,
    units=_UNITS,
    objectives=None,
    ez_vertical_inches=None,
    rosters="scale=100pts AGENT_PLAYER=1 AGENT=a (a.json) OPPONENT=o (o.json)",
    walls="(53,49)",
)


def test_dead_unit_after_charge_pile_in_does_not_block_consolidation_bfs(tmp_path):
    """VERROU : aucun fight_move_invalid quand B consolide après avoir tué A (charge+pile-in)."""
    log = tmp_path / "step.log"
    log.write_text(_LOG, encoding="utf-8")
    stats = an.parse_step_log(str(log))

    # Aucune violation de move fight : l'ancre fantôme de A ne doit pas bloquer le BFS de B.
    # B est P2 → key 2 dans le dict des violations.
    consol_p2 = stats["fight_move_invalid"]["consolidation"].get(2, 0)
    assert consol_p2 == 0, (
        f"fight_move_invalid consolidation P2 = {consol_p2} (attendu 0) — "
        "l'ancre fantôme de A (unit_hp > 0 malgré la mort) bloque le BFS de B"
    )
