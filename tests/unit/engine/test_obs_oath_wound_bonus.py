"""Les deux bits d'observation de la clause du +1 Wound d'Oath of Moment (08.04).

POURQUOI CES BITS. La clause (« Codex Detachment » ET aucune unité BLOOD ANGELS / DARK ANGELS /
DEATHWATCH / SPACE WOLVES) dépend du ROSTER, que l'agent ne construit pas et qu'aucune autre
feature ne lui donne : les mots-clés de sous-faction des unités ALLIÉES ne sont pas observés, et
la clause compte les unités MORTES. Sans ces bits, deux parties identiques à l'écran n'ont pas la
même règle d'attaque, et l'agent ne peut pas distinguer un Oath « faible » (relance de touche
seule) d'un Oath « fort » (relance + 1 au jet de blessure) — alors que le second rend une cible
coriace nettement plus rentable à désigner, et que c'est ce choix qu'il joue par `OATH_SLOT_i`.

CE QUE CE FICHIER CONSTRUIT, plutôt que de l'espérer d'une fixture : les DEUX régimes, en ne
faisant varier qu'une chose à la fois — le mot-clé d'une unité, puis le champ de détachement.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple
from unittest.mock import patch

from engine.observation_builder import ObservationBuilder
from engine.observation_entities import global_bin_index
from engine.w40k_core import W40KEngine
from tests.unit.engine._config_helpers import build_engine_config

MY_BONUS = global_bin_index("my_oath_wound_bonus_active")
ENEMY_BONUS = global_bin_index("enemy_oath_wound_bonus_active")
MY_SELECTED = global_bin_index("my_oath_target_selected")


def _weapon() -> Dict[str, Any]:
    return {"ATK": 3, "STR": 4, "AP": 0, "DMG": 1, "NB": 1, "RNG": 24,
            "WEAPON_RULES": [], "code": "test_weapon", "display_name": "Test Bolter"}


def _unit(uid: int, player: int, pos: Tuple[int, int], faction_keywords: List[Any]) -> Dict[str, Any]:
    return {
        "id": uid, "player": player, "col": pos[0], "row": pos[1],
        "unitType": "TestUnit", "DISPLAY_NAME": f"Unit {uid}",
        "HP_CUR": 1, "HP_MAX": 1, "MOVE": 6, "T": 4,
        "ARMOR_SAVE": 4, "INVUL_SAVE": 0,
        "RNG_WEAPONS": [_weapon()], "CC_WEAPONS": [_weapon()],
        "UNIT_RULES": [], "UNIT_KEYWORDS": [{"keywordId": "INFANTRY"}],
        "FACTION_KEYWORDS": faction_keywords,
        "LD": 7, "OC": 2, "VALUE": 10,
        "ICON": "test", "ICON_SCALE": 1.0, "ILLUSTRATION_RATIO": 1.0,
        "BASE_SHAPE": "round", "BASE_SIZE": 1, "MODEL_HEIGHT": 2.5,
        "models": [{"col": pos[0], "row": pos[1], "HP_CUR": 1, "HP_MAX": 1, "VALUE": 10}],
    }


def _engine(units: List[Dict[str, Any]], *, codex: Dict[str, bool]) -> W40KEngine:
    obs_params = {"obs_size": ObservationBuilder.SQUAD_OBS_SIZE_TARGET}
    config = {
        "board": {"default": {"cols": 60, "rows": 40, "hex_radius": 1.0, "margin": 0.0,
                              "wall_hexes": [], "inches_to_subhex": 1}},
        "pve_mode": False,
        "scenario_objectives": [],
        "observation_params": obs_params,
        "training_config": {"observation_params": obs_params, "max_turns_per_episode": 3},
        # Faction d'Armée DÉCLARÉE : P1 est ADEPTUS ASTARTES (il a donc l'Oath), P2 non.
        "army_faction": {"1": "ADEPTUS ASTARTES", "2": "TYRANIDS"},
        "uses_codex_detachment": codex,
        "units": units,
    }
    with patch("engine.w40k_core.load_weapon_damage_table", return_value={}), \
         patch.object(W40KEngine, "_build_reward_configs_for_current_units", return_value={}):
        engine = W40KEngine(config=build_engine_config(config))
    engine.reset()
    return engine


ASTARTES = [{"keywordId": "ADEPTUS ASTARTES"}]
ASTARTES_SPACE_WOLVES = [{"keywordId": "ADEPTUS ASTARTES"}, {"keywordId": "SPACE WOLVES"}]
TYRANIDS = [{"keywordId": "TYRANIDS"}]


def _global_bin(engine: W40KEngine, squad_id: str = "1"):
    return engine.obs_builder.build_squad_observation(engine.game_state, squad_id)["global_bin"]


def _armee_astartes(p1_extra_keywords: List[Any]) -> List[Dict[str, Any]]:
    """P1 : deux escouades ASTARTES, dont la seconde porte les mots-clés passés. P2 : TYRANIDS."""
    return [
        _unit(1, 1, (10, 10), ASTARTES),
        _unit(2, 1, (11, 10), p1_extra_keywords),
        _unit(3, 2, (40, 30), TYRANIDS),
    ]


def test_le_bonus_est_actif_sans_unite_de_sous_faction():
    """PRÉMISSE du test suivant : le même roster, sans le mot-clé, a bien le +1."""
    engine = _engine(_armee_astartes(ASTARTES), codex={"1": True, "2": True})

    g_bin = _global_bin(engine)

    assert float(g_bin[MY_BONUS]) == 1.0
    # L'ennemi TYRANIDS n'a pas l'Oath du tout : jamais de +1 de son côté.
    assert float(g_bin[ENEMY_BONUS]) == 0.0


def test_une_seule_unite_space_wolves_eteint_le_bonus():
    """LE cas mesuré sur `scenario_pvp_test.json` : un unique FenrisianWolf dans MON armée.

    Une seule chose change par rapport au test précédent — le mot-clé de l'escouade 2.
    """
    engine = _engine(_armee_astartes(ASTARTES_SPACE_WOLVES), codex={"1": True, "2": True})

    g_bin = _global_bin(engine)

    assert float(g_bin[MY_BONUS]) == 0.0, "SPACE WOLVES dans l'armée : le +1 tombe"
    # Discrimination : c'est bien le BONUS qui tombe, pas l'Oath entier. La désignation reste
    # armée (la relance de touche, elle, ne dépend d'aucune moitié de la clause).
    assert float(g_bin[MY_SELECTED]) == 0.0, (
        "prémisse : aucune cible désignée tant que l'agent n'a pas joué son OATH_SLOT"
    )
    assert engine.game_state["pending_oath_selection"] == 1, (
        "l'Oath reste ARMÉ : seule la clause conditionnelle du +1 est éteinte"
    )


def test_le_detachement_hors_codex_eteint_le_bonus_aussi():
    """L'AUTRE moitié de la clause, isolée : même roster, seul `uses_codex_detachment` change."""
    engine = _engine(_armee_astartes(ASTARTES), codex={"1": False, "2": True})

    assert float(_global_bin(engine)[MY_BONUS]) == 0.0


def test_une_armee_sans_astartes_n_exige_pas_le_champ_de_detachement():
    """GARDE d'appel : `oath_wound_bonus_applies` LÈVE si `uses_codex_detachment` manque.

    Ce champ est légitimement absent d'une partie sans ADEPTUS ASTARTES — l'observation ne doit
    donc pas l'interroger pour un joueur qui n'a pas la capacité. Sans la garde, construire
    l'observation d'une partie ORKS vs TYRANIDS lèverait.
    """
    obs_params = {"obs_size": ObservationBuilder.SQUAD_OBS_SIZE_TARGET}
    config = {
        "board": {"default": {"cols": 60, "rows": 40, "hex_radius": 1.0, "margin": 0.0,
                              "wall_hexes": [], "inches_to_subhex": 1}},
        "pve_mode": False,
        "scenario_objectives": [],
        "observation_params": obs_params,
        "training_config": {"observation_params": obs_params, "max_turns_per_episode": 3},
        "army_faction": {"1": "TYRANIDS", "2": "TYRANIDS"},
        # PAS de `uses_codex_detachment` : aucune armée ADEPTUS ASTARTES en jeu.
        "units": [_unit(1, 1, (10, 10), TYRANIDS), _unit(2, 2, (40, 30), TYRANIDS)],
    }
    with patch("engine.w40k_core.load_weapon_damage_table", return_value={}), \
         patch.object(W40KEngine, "_build_reward_configs_for_current_units", return_value={}):
        engine = W40KEngine(config=build_engine_config(config))
    engine.reset()

    g_bin = _global_bin(engine)

    assert float(g_bin[MY_BONUS]) == 0.0
    assert float(g_bin[ENEMY_BONUS]) == 0.0
