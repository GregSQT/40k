"""La taille de bataille du scénario atteint le plafond de réserves 20.01 sur le chemin API/PvP.

Le chemin PvP ne charge pas le scénario dans le moteur : `services/api_server.py` appelle le
loader lui-même et reforwarde le résultat via le dict `config`. Tant que `points_limit` n'était
pas dans ce dict, le moteur voyait `None`, `strategic_reserves_usage` rendait `cap = 0`, et
AUCUNE unité ne pouvait être mise en réserves en partie — alors que le scénario déclarait bien
sa `scale` et que le contrôle au chargement, lui, l'utilisait. Rien ne le signalait : `cap = 0`
est aussi la valeur légitime d'un scénario sans `scale`.

Deux volets, parce que la chaîne a deux maillons distincts et qu'un seul testé ne prouve rien :
le moteur doit CONSOMMER la clé, l'API doit la TRANSMETTRE.
"""

import ast
import pathlib
from typing import Any, Dict
from unittest.mock import patch

import pytest

from engine.phase_handlers.deployment_handlers import strategic_reserves_usage
from engine.observation_builder import ObservationBuilder
from engine.w40k_core import W40KEngine
from tests.unit.engine._config_helpers import build_engine_config

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]


def _weapon_cfg() -> Dict[str, Any]:
    return {
        "ATK": 2, "STR": 4, "AP": 0, "DMG": 1, "NB": 1, "RNG": 24,
        "WEAPON_RULES": [], "display_name": "Test Bolter",
    }


def _unit_cfg(uid: int, player: int, col: int, row: int) -> Dict[str, Any]:
    return {
        "id": uid, "player": player, "col": col, "row": row,
        "unitType": "TestUnit", "DISPLAY_NAME": f"Unit {uid}",
        "HP_CUR": 3, "HP_MAX": 3, "MOVE": 6, "T": 4,
        "ARMOR_SAVE": 4, "INVUL_SAVE": 0,
        "RNG_WEAPONS": [_weapon_cfg()], "CC_WEAPONS": [],
        "UNIT_RULES": [], "UNIT_KEYWORDS": [],
        "LD": 7, "OC": 1, "VALUE": 120,
        "ICON": "test", "ICON_SCALE": 1.0, "ILLUSTRATION_RATIO": 1.0,
        "BASE_SHAPE": "round", "BASE_SIZE": 1, "MODEL_HEIGHT": 2.5,
    }


def _engine(**config_extra: Any) -> W40KEngine:
    obs_params = {"obs_size": ObservationBuilder.SQUAD_OBS_SIZE_TARGET}
    cfg = {
        "board": {
            "default": {
                "cols": 15, "rows": 13, "hex_radius": 1.0, "margin": 0.0,
                "wall_hexes": [], "inches_to_subhex": 1,
            }
        },
        "game_rules": {
            "engagement_zone": 1, "engagement_zone_vertical": 5, "max_base_size_hex": 35,
            "max_turns": 3, "max_actions_per_model_per_turn": 7, "step_limit_margin": 1.5,
        },
        "move": {
            "can_move_through_enemy_engagement_zone": True,
            "can_move_through_enemy_model": False,
            "can_move_through_friendly_model": True,
        },
        "charge": {"charge_max_distance": 12},
        "pve_mode": False,
        "controlled_player": 1,
        "scenario_objectives": [],
        "observation_params": obs_params,
        "training_config": {"observation_params": obs_params},
        "units": [_unit_cfg(1, 1, 3, 3), _unit_cfg(2, 2, 10, 10)],
        **config_extra,
    }
    with patch("engine.w40k_core.load_weapon_damage_table", return_value={}), patch.object(
        W40KEngine, "_build_reward_configs_for_current_units", return_value={}
    ):
        return W40KEngine(config=build_engine_config(cfg))


def test_points_limit_du_config_alimente_le_plafond_de_reserves():
    engine = _engine(points_limit=1000)

    assert engine.game_state["points_limit"] == 1000
    used, cap = strategic_reserves_usage(engine.game_state, 1)
    assert (used, cap) == (0, 500), "plafond 20.01 = 50 % de la taille de bataille"


def test_sans_points_limit_la_regle_ferme():
    """Absence de `scale` = règle invérifiable = aucun dépôt. C'est un état métier, pas un trou."""
    engine = _engine()

    assert engine.game_state["points_limit"] is None
    assert strategic_reserves_usage(engine.game_state, 1)[1] == 0


def test_roster_info_du_config_est_pose_sur_le_moteur():
    roster_info = {"agent_roster_id": "sm_a", "opponent_roster_id": "orks_b"}
    assert _engine(roster_info=roster_info)._scenario_roster_info == roster_info


def test_api_server_transmet_points_limit_et_roster_info_au_moteur():
    """L'API construit la config de scénario en UN seul endroit, qui porte les deux clés.

    Volet symétrique du précédent : le moteur peut consommer la clé sans que personne ne la
    fournisse. Le test vaut aussi comme garde anti-jumeau — PvP et PvE partageaient jusqu'ici
    68 lignes recopiées, et c'est cette copie qui avait laissé les deux clés en route. Un
    deuxième dict de config de scénario ferait donc rougir ici, avant de faire perdre une clé.

    Source lue sur DISQUE (motif de `test_debug_trace_guard`) : importer `services.api_server`
    tirerait Flask et toute son init de module dans un worker qui n'en a aucun besoin — le test
    ne regarde que du texte.
    """
    source = (_REPO_ROOT / "services" / "api_server.py").read_text(encoding="utf-8")
    dicts_scenario = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Dict):
            continue
        cles = {
            k.value for k in node.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)
        }
        # Signature d'une CONFIG D'ENTRÉE de moteur, pas d'une simple clé : un dict de réponse
        # d'API qui nommerait `scenario_objectives` ne porte pas les trois autres. Reconnaître
        # sur une seule clé faisait rougir ce test sur du code sans rapport.
        if {"units", "board", "scenario_objectives", "scenario_wall_hexes"} <= cles:
            dicts_scenario.append((node.lineno, cles))

    assert len(dicts_scenario) == 1, (
        "il doit exister exactement UNE construction de config de scénario dans api_server "
        f"(trouvées : {[l for l, _ in dicts_scenario]}). Zéro = le test ne regarde plus rien ; "
        "deux = le jumeau est revenu, et avec lui le risque qu'une clé ne soit ajoutée que d'un côté"
    )
    lineno, cles = dicts_scenario[0]
    manquantes = {"points_limit", "roster_info"} - cles
    assert not manquantes, (
        f"api_server.py:{lineno} : config de scénario sans {sorted(manquantes)} — le moteur "
        "verra None, donc plafond de réserves nul (20.01) alors que le loader connaît la valeur"
    )


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__])
