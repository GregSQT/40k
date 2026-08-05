"""Verrou : la clause de détachement d'Oath atteint le moteur par le chemin API, et le suit.

Le chemin API/PvP ne charge PAS le scénario dans le moteur : `_build_scenario_engine_config`
assemble la config lui-même et la passe à `W40KEngine(config=…)`, qui prend alors la branche
`else` — celle qui ne relit aucun scénario (`w40k_core.py`, deux branches de construction). Toute
donnée de scénario non recopiée dans ce dict est donc INERTE en partie, même déclarée dans le
JSON. Mesuré : `uses_codex_detachment` déclaré dans les 16 scénarios ne traversait pas, et la
partie levait au premier jet de blessure d'un marine sous Oath (`game_state.uses_codex_detachment`)
— soit après plusieurs tours de jeu humain.

Second maillon, même donnée : la clause appartient à l'ARMÉE. Changer de roster en déploiement
change l'armée, donc la clause de ce joueur — et d'aucun autre.

Les deux tests relisent la valeur avec le LECTEUR du moteur, pas avec un `in config` : c'est la
lecture qui lève en partie, donc c'est elle qui doit être verte ici.
"""

import copy
import json
import pathlib

import pytest

from engine.game_state import uses_codex_detachment
from shared.data_validation import ConfigurationError

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]


@pytest.fixture(autouse=True)
def _run_from_repo_root(monkeypatch):
    """`api_server` résout ses chemins depuis la racine (c'est ce que fait `initialize_engine`).

    Sans ce `chdir`, le verrou ne tiendrait que si pytest est lancé depuis la racine — un test
    dont le résultat dépend du répertoire courant de l'appelant ne verrouille rien.
    """
    assert (_REPO_ROOT / "services" / "api_server.py").is_file(), (
        f"racine du depot mal calculee : {_REPO_ROOT}"
    )
    monkeypatch.chdir(_REPO_ROOT)


@pytest.mark.parametrize("scenario_name", ["scenario_pvp.json", "scenario_pve.json"])
def test_la_config_api_porte_la_clause_de_detachement(scenario_name: str) -> None:
    from services.api_server import _build_scenario_engine_config, _default_board_scenario_path

    scenario_file = _default_board_scenario_path(scenario_name)
    config, _registry, _loader, _agents = _build_scenario_engine_config(scenario_file)

    # VERT VACANT : une config vide passerait un simple « la lecture ne lève pas ».
    assert config["units"], f"{scenario_name} : config construite sans aucune unité"

    for player in (1, 2):
        assert uses_codex_detachment({"config": config}, player) is True, (
            f"{scenario_name} : la clause de détachement n'atteint pas le moteur pour le joueur "
            f"{player} — le +1 au jet de blessure d'Oath of Moment lèvera en pleine partie"
        )


def test_changer_de_roster_remplace_la_clause_du_seul_joueur_concerne(monkeypatch) -> None:
    """Le fichier d'armée décide pour SON joueur ; l'autre garde la sienne.

    La situation est CONSTRUITE : les trois fichiers de `config/armies/` déclarent tous `true`,
    donc aucun d'eux ne distinguerait « la valeur de l'armée est propagée » de « la valeur du
    scénario est restée ». Le fichier chargé est donc renvoyé avec `false`, seule forme qui rend
    le défaut visible.
    """
    import services.api_server as api

    api.initialize_engine(api._default_board_scenario_path("scenario_pvp.json"))
    engine = api.engine
    engine.reset()
    game_state = engine.game_state
    # La phase de déploiement est la seule où `change_roster` est recevable : sans elle le test
    # observerait un refus, pas une propagation.
    assert game_state["phase"] == "deployment", "le scénario ne démarre plus en déploiement"
    assert uses_codex_detachment(game_state, 1) is True, "état de départ non discriminant"
    assert uses_codex_detachment(game_state, 2) is True, "état de départ non discriminant"

    real_loader = api._load_army_file
    monkeypatch.setattr(
        api,
        "_load_army_file",
        lambda name: {
            **copy.deepcopy(real_loader(name)),
            "uses_codex_detachment": False,
        },
    )

    ok, result = api._execute_change_roster_action(
        engine, {"army_file": "v10_space_marines.json", "player": 1}
    )
    assert ok, f"change_roster refusé : {result}"

    assert uses_codex_detachment(game_state, 1) is False, (
        "l'armée entrante déclare ne PAS utiliser de détachement Codex, et le joueur garde "
        "quand même le +1 au jet de blessure d'Oath of Moment"
    )
    assert uses_codex_detachment(game_state, 2) is True, (
        "le roster de l'adversaire n'a pas changé : sa clause ne doit pas bouger"
    )


def _fake_armies_dir(tmp_path: pathlib.Path, payload: dict) -> pathlib.Path:
    """Un dossier `config/armies` de substitution portant UN fichier d'armée."""
    armies = tmp_path / "config" / "armies"
    armies.mkdir(parents=True)
    (armies / "invalide.json").write_text(json.dumps(payload), encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize(
    "declaration, attendu",
    [
        ({}, ConfigurationError),                            # clé absente
        ({"uses_codex_detachment": {"1": True, "2": True}}, TypeError),  # dict : forme du SCENARIO
        ({"uses_codex_detachment": "false"}, TypeError),     # chaîne : `bool("false")` vaut True
    ],
)
def test_un_fichier_d_armee_sans_clause_lisible_est_refuse_au_chargement(
    tmp_path, monkeypatch, declaration: dict, attendu: type
) -> None:
    """`_list_armies` expose TOUT `config/armies` à l'interface : un fichier ajouté à la main
    ne doit pas pouvoir entrer en partie avec une clause illisible."""
    import services.api_server as api

    monkeypatch.setattr(
        api,
        "abs_parent",
        str(_fake_armies_dir(tmp_path, {
            "faction": "spaceMarine", "display_name": "X", "description": "X",
            "units": [{"unit_type": "Intercessor", "count": 1}],
            **declaration,
        })),
    )
    with pytest.raises(attendu):
        api._load_army_file("invalide.json")


def test_un_fichier_d_armee_invalide_ne_laisse_pas_la_partie_a_moitie_echangee(
    tmp_path, monkeypatch
) -> None:
    """La validation précède la MUTATION.

    `_execute_change_roster_action` remplace puis renumérote les unités avant de toucher à la
    clause ; lever après cette réécriture laisserait `deployment_state` et `units_cache` sur les
    anciens ids. Ce qu'on observe ici, c'est donc l'état du plateau APRÈS l'échec.
    """
    import services.api_server as api

    api.initialize_engine(api._default_board_scenario_path("scenario_pvp.json"))
    engine = api.engine
    engine.reset()
    game_state = engine.game_state
    avant = [str(u["id"]) for u in game_state["units"]]
    assert avant, "état de départ vide : le test ne regarderait rien"

    monkeypatch.setattr(
        api,
        "abs_parent",
        str(_fake_armies_dir(tmp_path, {
            "faction": "spaceMarine", "display_name": "X", "description": "X",
            "units": [{"unit_type": "Intercessor", "count": 1}],
        })),
    )
    with pytest.raises(ConfigurationError):
        api._execute_change_roster_action(engine, {"army_file": "invalide.json", "player": 1})

    assert [str(u["id"]) for u in game_state["units"]] == avant, (
        "les unités ont été remplacées avant que le fichier d'armée soit jugé"
    )
