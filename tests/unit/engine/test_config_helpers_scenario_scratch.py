"""`load_engine_from_scenario` (tests/unit/engine/_config_helpers.py) — les deux contraintes
qu'un scénario de test matérialisé doit respecter, et que sa première version violait.

Ce helper a été extrait le 2026-08-10 de deux `_load` locaux qui écrivaient dans un
`tempfile.TemporaryDirectory()` refermé aussitôt. Les deux fichiers d'origine survivaient par
chance — un seul `reset()`, aucun StepLogger. Hisser ce code dans un helper PARTAGÉ transformait
cette chance en piège pour tout appelant suivant, d'où ce fichier : les contraintes sont
vérifiées là où elles vivent, pas dans chaque consommateur.

Les deux clauses viennent du moteur, pas d'une préférence de test :
  - `repo_relative_scenario_path` (`engine/w40k_core.py`) LÈVE sur un chemin hors dépôt ;
  - `_current_scenario_file` est RELU à tout `reset()` qui recharge le scénario.
"""

from __future__ import annotations

import os
from pathlib import Path

from engine.w40k_core import repo_relative_scenario_path
from tests.unit.engine._config_helpers import (
    ATTACHED_BODYGUARD,
    ATTACHED_ENEMY,
    attached_scenario,
    load_engine_from_scenario,
)

_SCENARIO = attached_scenario([ATTACHED_BODYGUARD, ATTACHED_ENEMY])


def test_le_scenario_est_journalisable_pour_le_replay():
    """Contrainte 1 : sous le dépôt. Un chemin dans `/tmp` fait LEVER le moteur.

    `reset()` appelle `repo_relative_scenario_path` dès qu'un StepLogger est actif : un scénario
    hors dépôt tuait donc l'épisode au démarrage de tout test qui journalise. On interroge ici
    le VRAI validateur du moteur, pas une reformulation de sa règle.
    """
    eng = load_engine_from_scenario(_SCENARIO)
    chemin = _scenario_file_of(eng)

    relatif = repo_relative_scenario_path(chemin)
    assert relatif is not None
    assert not relatif.startswith(".."), f"scénario hors dépôt : {chemin}"
    # Contre-épreuve : le validateur refuse bien un chemin `/tmp`, donc l'assertion ci-dessus
    # n'est pas satisfaite par n'importe quoi.
    try:
        repo_relative_scenario_path("/tmp/scenario.json")
    except ValueError:
        pass
    else:
        raise AssertionError(
            "repo_relative_scenario_path accepte /tmp : la contrainte testée n'existe plus, "
            "ce test ne vérifie plus rien"
        )


def test_le_scenario_survit_a_un_second_reset():
    """Contrainte 2 : le fichier vit aussi longtemps que le moteur.

    Le moteur RELIT `_current_scenario_file` à tout `reset()` qui recharge — ici parce que le
    joueur contrôlé a changé (`_scenario_loaded_for_controlled_player`, `w40k_core.py`), l'un
    des quatre déclencheurs. Avec un `TemporaryDirectory` refermé à la sortie du helper, ce
    second `reset()` mourait en `FileNotFoundError`.
    """
    eng = load_engine_from_scenario(_SCENARIO)
    # Les joueurs sont 1 et 2 (`w40k_core`), d'où `3 - x` : un `1 - x` donnerait 0, un id
    # qu'aucun joueur ne porte — le rechargement se déclencherait quand même, mais sur un état
    # que le moteur ne produit jamais.
    eng.config["controlled_player"] = 3 - int(eng.config["controlled_player"])

    eng.reset(seed=1)  # relit le scénario : ne doit pas lever

    assert Path(_scenario_file_of(eng)).exists(), "le scénario a disparu sous le moteur"


def test_le_fichier_est_bien_sur_disque_et_sous_config():
    """VERT VACANT : les deux tests ci-dessus ne prouvent rien si aucun fichier n'est écrit."""
    eng = load_engine_from_scenario(_SCENARIO)
    chemin = Path(_scenario_file_of(eng))

    assert chemin.is_file(), f"aucun scénario matérialisé en {chemin}"
    assert chemin.stat().st_size > 0, "scénario matérialisé vide"
    # `config/local/` est gitignoré et hors de l'énumération des agents (cf. ai/scenario_scratch).
    assert "config" in chemin.parts and "local" in chemin.parts, (
        f"scénario hors de config/local/ : {chemin} — /api/config/board le refuserait"
    )


def _scenario_file_of(engine) -> str:
    """Chemin du scénario que le moteur RELIRA — `_current_scenario_file`, et lui seul.

    Un seul attribut, sans repli : c'est CELUI que `reset()` repasse à `_reload_scenario`. Lire
    un autre porteur du chemin (celui du constructeur, par exemple) validerait un fichier que le
    moteur ne relit jamais, et le test resterait vert avec le piège intact.
    """
    valeur = getattr(engine, "_current_scenario_file", None)
    if not valeur:
        raise AssertionError(
            "le moteur n'expose plus `_current_scenario_file` : ces tests ne peuvent plus "
            "vérifier ce qu'ils prétendent"
        )
    return str(valeur)


def test_les_appels_partagent_un_seul_repertoire():
    """Pas un répertoire de travail PAR APPEL : ils ne sont repris qu'au bout de 24 h.

    La première version en créait un à chaque construction de moteur — 37 s'étaient accumulés
    dans ce dépôt, et `_purge_stale` les re-balayait tous à chaque appel suivant. Le nettoyage
    `atexit` ne rattrape pas ça : il ne supprime que le répertoire de CE processus.
    """
    premier = Path(_scenario_file_of(load_engine_from_scenario(_SCENARIO)))
    second = Path(_scenario_file_of(load_engine_from_scenario(_SCENARIO)))

    assert premier.parent == second.parent, (
        f"deux répertoires pour deux appels : {premier.parent} vs {second.parent}"
    )
    assert premier != second, "les deux scénarios s'écrasent : le second appel a perdu le sien"


def test_le_repertoire_de_travail_est_partage_avec_la_production():
    """Le helper de test et les runs réels matérialisent au MÊME endroit.

    Sans ça, la contrainte serait réapprise séparément des deux côtés — c'est précisément ce qui
    l'avait fait payer deux fois (`ai/bot_evaluation.py` et `ai/train.py` écrivaient chacun dans
    `/tmp` avant que `ai/scenario_scratch` n'existe).
    """
    from ai.scenario_scratch import repo_root

    eng = load_engine_from_scenario(_SCENARIO)
    attendu = os.path.join(repo_root(), "config", "local", "scenario_scratch")
    assert str(Path(_scenario_file_of(eng))).startswith(attendu), (
        f"{_scenario_file_of(eng)} n'est pas sous {attendu}"
    )
