"""Les scénarios que l'API choisit par DÉFAUT se chargent réellement.

Le mode PvE ne démarrait plus : son défaut pointait `config/scenario_pve.json`, copie restée à
la racine après la migration des scénarios sous `config/board/<board>/scenario/`, donc au format
antérieur (clé `objectives` en dur, remplacée par les zones de terrain `"objective": true`). Le
loader la refusait. Rien ne le disait : aucun test ne chargeait un scénario par le chemin que
l'API construit — ils passaient tous un chemin explicite, forcément valide.

C'est ce maillon-là que ce fichier verrouille : le chemin RÉSOLU par le serveur, pas un chemin
choisi par le test. Un scénario déplacé, renommé, ou revenu à un format périmé rougit ici.

PORTÉE EXACTE — les scénarios passés à `_default_board_scenario_path`, soit les modes "pvp" et
"pve". Ce qui N'EST PAS couvert, et pourquoi, plutôt qu'un titre qui laisserait croire à une
couverture totale :
- `ED_SCENARIO_DEFAULT` (Endless Duty) pointe encore `config/scenario_endless_duty.json`, à la
  racine et au format antérieur : il échouerait ici. Sa remise en service appartient au chantier
  Documentation/Chantiers/backlog/Endless_duty_etat_mesure.md, qui liste d'autres obstacles que
  l'emplacement — l'inclure rendrait ce fichier rouge sans rien réparer.
- les chemins "pvp_test"/"pve_test", construits en ligne dans `start_game` à partir du
  `board_path` de la requête : ils dépendent d'un paramètre client, pas d'un défaut serveur.
  `scenario_pve_test.json` échouerait aussi l'assertion d'objectifs ci-dessous (il déclare
  `primary_objectives` sans `terrain_ref`, donc zéro objectif contrôlable).
"""

import ast
import os
import pathlib

import pytest

from ai.unit_registry import UnitRegistry
from config_loader import get_config_loader
from engine.game_state import GameStateManager
from services.api_server import _default_board_scenario_path

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]


def _scenario_names_demandes() -> list[str]:
    """Noms de scénario que `api_server` passe RÉELLEMENT au résolveur.

    Lus dans le source plutôt que recopiés ici : une liste en dur vérifierait que des fichiers
    que le TEST connaît existent, pas que ceux que le SERVEUR demande existent. Les deux se
    ressemblent jusqu'au jour où un mode change de scénario — et ce jour-là, la liste en dur
    reste verte pendant que le mode ne démarre plus.
    """
    source = (_REPO_ROOT / "services" / "api_server.py").read_text(encoding="utf-8")
    noms = set()
    for node in ast.walk(ast.parse(source)):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_default_board_scenario_path"
            and node.args
            and isinstance(node.args[0], ast.Constant)
        ):
            noms.add(node.args[0].value)
    assert noms, "aucun appel à _default_board_scenario_path trouvé — le test ne regarde plus rien"
    return sorted(noms)


@pytest.mark.parametrize("scenario_name", _scenario_names_demandes())
def test_le_scenario_par_defaut_du_mode_se_charge(scenario_name: str):
    path = _default_board_scenario_path(scenario_name)
    assert os.path.exists(path), (
        f"api_server demande {scenario_name!r}, résolu en {path!r}, qui n'existe pas — un "
        "scénario déplacé ou renommé sans mettre à jour l'appelant laisse le mode inutilisable"
    )

    unit_registry = UnitRegistry()
    manager = GameStateManager({"board": get_config_loader().get_board_config()}, unit_registry)
    result = manager.load_units_from_scenario(path, unit_registry)

    # VERT VACANT : un scénario vide passerait le simple « ça charge ».
    assert result["units"], f"{scenario_name} : scénario chargé mais sans aucune unité"
    assert result["objectives"], (
        f"{scenario_name} : aucun objectif — les objectifs viennent des zones de terrain marquées "
        '"objective": true (`terrain_ref`), leur absence signale un scénario au format antérieur'
    )
