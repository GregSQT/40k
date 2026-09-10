"""Scénario de mêlée garantie, partagé par les tests qui jouent de VRAIS épisodes.

Une paire pré-engagée (ScreamerKiller vs Termagant) et un Carnifex à portée de charge : c'est
le seul scénario du dépôt où la phase fight se déclenche à coup sûr, sans dépendre d'un tirage.
Dix fichiers de test s'appuient dessus (parité de cible squad/fight, créneau d'arme, clé
périmée, compteurs de charge, overrun de resélection, invariants d'état V11).

ORIGINE. Ce littéral vivait dans `scripts/smoke_t5_bare.py`, supprimé le 2026-09-10 : ses deux
volets exécutables étaient morts — le volet A cherchait `scenario_training_bot-01..03.json`
dans une banque retirée en juillet, et le volet B construisait le moteur sur l'agent
`CoreAgent`, dont la config a disparu le 2026-07-19 (`config_loader` lève dessus). Ce que le
smoke prouvait est déjà porté par des tests rejouables, ce qui vaut mieux qu'un script à lancer
à la main (T4) : `test_t5_bare_loop.py` est le portage pytest de ses deux volets (invariant R7
`mask.any() or game_over`, terminaison, pertes de mêlée par FIGHT_CTX, sur trois graines), et
R6 — l'éligibilité de charge d'un socle ovale — est verrouillé sur ses deux sites par
`test_charge_oval_base_reverse_bfs.py`. Seule la DONNÉE avait donc une valeur permanente.

⚠️ `test_t5_bare_loop.py` porte sa PROPRE copie de ce scénario (`_SCENARIO`, mêmes quatre
unités aux mêmes positions, sans `uses_codex_detachment`). La duplication est antérieure à ce
fichier — elle existait entre le smoke et ce test — et n'est pas résorbée ici : fusionner
changerait l'entrée d'un test d'invariant sans nécessité causale.
"""

from __future__ import annotations

from typing import Any

MELEE_SCENARIO: dict[str, Any] = {
    "primary_objectives": ["objectives_control"],
    # Inerte ici (roster 100 % Tyranids) mais declare comme dans tout scenario : la clause de
    # detachement d'Oath of Moment est OBLIGATOIRE des qu'une armee ADEPTUS ASTARTES entre.
    "uses_codex_detachment": {"1": True, "2": True},
    # Faction d'Armee des deux camps : ce scenario est 100 % Tyranids des deux cotes. Champ
    # OBLIGATOIRE — 08.04 le lit a chaque phase de commandement, quelle que soit la faction.
    "army_faction": {"1": "TYRANIDS", "2": "TYRANIDS"},
    "board_ref": "44x60x5",
    "terrain_ref": "terrain-mc1.json",
    "deployment_type": "fixed",
    "units": [
        {"id": "1", "player": 1, "unit_type": "ScreamerKiller", "col": 60, "row": 200},
        {"id": "2", "player": 2, "unit_type": "Termagant", "col": 60, "row": 214},
        {"id": "3", "player": 1, "unit_type": "Carnifex", "col": 60, "row": 250},
        {"id": "4", "player": 2, "unit_type": "Termagant", "col": 60, "row": 272},
    ],
}
