"""Verrouille les fonctions de mesure ajoutées le 2026-08-13 dans bot_zone_direct.py :
_avg_bot_enemy_distance, _count_alive_bot_squads, _turns_of_key, _loss_rate_by_turn,
et l'extension des paramètres optionnels de _episode_record.

Les fonctions _avg/_count importent paresseusement depuis engine — les tests montent un
game_state minimal conforme au format attendu (units + units_cache), sans base de données ni
session Flask.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict

import pytest

from tests._chargeur_script import charger_script

_SCRIPT = charger_script("scripts/bot_zone_direct.py")


# ---------------------------------------------------------------------------
# Helpers partagés
# ---------------------------------------------------------------------------


def _gs(
    units: list[dict],
    cache: dict[str, dict],
    controllers: dict | None = None,
) -> Dict[str, Any]:
    """Construit un game_state minimal pour les fonctions de mesure.

    `episode_number`/`turn` portent le marqueur que `_avg_focus_target_distance` confronte à
    celui du bot : sans eux, toute cible focalisée serait lue comme périmée.
    """
    return {
        "units": units,
        "units_cache": cache,
        "objective_controllers": controllers or {},
        "episode_number": 1,
        "turn": 1,
    }


def _unit(uid: str, player: int) -> dict:
    return {"id": uid, "player": player}


def _entry(col: int, row: int) -> dict:
    return {"col": col, "row": row}


_RESERVES = {"col": -1, "row": -1}


# ---------------------------------------------------------------------------
# _count_alive_bot_squads
# ---------------------------------------------------------------------------


def test_count_alive_bot_squads_toutes_vivantes():
    gs = _gs(
        [_unit("a", 1), _unit("b", 1), _unit("c", 2)],
        {"a": _entry(0, 0), "b": _entry(1, 1), "c": _entry(2, 2)},
    )
    assert _SCRIPT._count_alive_bot_squads(gs, 1) == 2


def test_count_alive_bot_squads_une_eliminee():
    gs = _gs(
        [_unit("a", 1), _unit("b", 1)],
        {"b": _entry(1, 1)},  # "a" absent du cache = éliminée
    )
    assert _SCRIPT._count_alive_bot_squads(gs, 1) == 1


def test_count_alive_bot_squads_toutes_eliminées():
    gs = _gs(
        [_unit("a", 1)],
        {},  # cache vide
    )
    assert _SCRIPT._count_alive_bot_squads(gs, 1) == 0


def test_count_alive_bot_squads_ignore_ennemis():
    gs = _gs(
        [_unit("a", 1), _unit("b", 2)],
        {"a": _entry(0, 0), "b": _entry(1, 1)},
    )
    assert _SCRIPT._count_alive_bot_squads(gs, 1) == 1


# ---------------------------------------------------------------------------
# _collect_live_enemies
# ---------------------------------------------------------------------------


def test_collect_live_enemies_vide_sans_ennemi():
    gs = _gs([_unit("bot", 1)], {"bot": _entry(0, 0)})
    assert _SCRIPT._collect_live_enemies(gs, 1) == []


def test_collect_live_enemies_exclut_mort():
    gs = _gs([_unit("bot", 1), _unit("en", 2)], {"bot": _entry(0, 0)})  # "en" absent du cache
    assert _SCRIPT._collect_live_enemies(gs, 1) == []


def test_collect_live_enemies_exclut_reserves():
    gs = _gs([_unit("bot", 1), _unit("en", 2)], {"bot": _entry(0, 0), "en": _RESERVES})
    assert _SCRIPT._collect_live_enemies(gs, 1) == []


def test_collect_live_enemies_retourne_sid_col_row():
    gs = _gs([_unit("bot", 1), _unit("en", 2)], {"bot": _entry(0, 0), "en": _entry(3, 5)})
    result = _SCRIPT._collect_live_enemies(gs, 1)
    assert len(result) == 1
    sid, col, row = result[0]
    assert sid == "en" and col == 3 and row == 5


def test_collect_live_enemies_plusieurs_ennemis():
    gs = _gs(
        [_unit("bot", 1), _unit("e1", 2), _unit("e2", 2)],
        {"bot": _entry(0, 0), "e1": _entry(1, 0), "e2": _entry(2, 0)},
    )
    result = _SCRIPT._collect_live_enemies(gs, 1)
    assert {r[0] for r in result} == {"e1", "e2"}


# ---------------------------------------------------------------------------
# _collect_live_bot_positions
# ---------------------------------------------------------------------------


def test_collect_live_bot_positions_vide_sans_bot_sur_table():
    gs = _gs([_unit("bot", 1)], {"bot": _RESERVES})
    assert _SCRIPT._collect_live_bot_positions(gs, 1) == []


def test_collect_live_bot_positions_exclut_mort():
    gs = _gs([_unit("bot", 1)], {})  # cache vide
    assert _SCRIPT._collect_live_bot_positions(gs, 1) == []


def test_collect_live_bot_positions_retourne_col_row():
    gs = _gs([_unit("bot", 1), _unit("en", 2)], {"bot": _entry(4, 7), "en": _entry(0, 0)})
    result = _SCRIPT._collect_live_bot_positions(gs, 1)
    assert result == [(4, 7)]


def test_collect_live_bot_positions_plusieurs_escouades():
    gs = _gs(
        [_unit("b1", 1), _unit("b2", 1), _unit("en", 2)],
        {"b1": _entry(0, 0), "b2": _entry(1, 1), "en": _entry(5, 5)},
    )
    result = _SCRIPT._collect_live_bot_positions(gs, 1)
    assert set(result) == {(0, 0), (1, 1)}


# ---------------------------------------------------------------------------
# _avg_bot_enemy_distance
# ---------------------------------------------------------------------------


def test_avg_bot_enemy_distance_none_sans_ennemi_sur_table():
    gs = _gs(
        [_unit("bot", 1)],
        {"bot": _entry(0, 0)},
    )
    assert _SCRIPT._avg_bot_enemy_distance(gs, 1) is None


def test_avg_bot_enemy_distance_none_si_ennemi_en_reserves():
    gs = _gs(
        [_unit("bot", 1), _unit("en", 2)],
        {"bot": _entry(0, 0), "en": _RESERVES},
    )
    assert _SCRIPT._avg_bot_enemy_distance(gs, 1) is None


def test_avg_bot_enemy_distance_calcul_simple():
    # bot en (0,0), ennemi en (0,4) : distance hex = 4
    gs = _gs(
        [_unit("bot", 1), _unit("en", 2)],
        {"bot": _entry(0, 0), "en": _entry(0, 4)},
    )
    result = _SCRIPT._avg_bot_enemy_distance(gs, 1)
    assert result is not None
    assert result == pytest.approx(4.0, abs=1.0)


def test_avg_bot_enemy_distance_moyenne_plusieurs_bots():
    # deux bots, un ennemi — chacun prend la distance min (= seul ennemi)
    gs = _gs(
        [_unit("b1", 1), _unit("b2", 1), _unit("en", 2)],
        {"b1": _entry(0, 0), "b2": _entry(0, 2), "en": _entry(0, 4)},
    )
    result = _SCRIPT._avg_bot_enemy_distance(gs, 1)
    assert result is not None
    # b1→en=4, b2→en=2 → moyenne=3
    assert result == pytest.approx(3.0, abs=1.0)


# ---------------------------------------------------------------------------
# _count_distinct_focus_targets
# ---------------------------------------------------------------------------


def test_count_distinct_focus_targets_none_sans_ennemi_sur_table():
    gs = _gs(
        [_unit("bot", 1), _unit("en", 2)],
        {"bot": _entry(0, 0)},  # "en" absent du cache = éliminé
    )
    assert _SCRIPT._count_distinct_focus_targets(gs, 1) is None


def test_count_distinct_focus_targets_none_sans_escouade_bot_sur_table():
    gs = _gs(
        [_unit("bot", 1), _unit("en", 2)],
        {"bot": _RESERVES, "en": _entry(0, 4)},
    )
    assert _SCRIPT._count_distinct_focus_targets(gs, 1) is None


def test_count_distinct_focus_targets_convergence_totale():
    # e1 en (0,0) est le plus proche des DEUX escouades bot ; e2 est loin
    gs = _gs(
        [_unit("b1", 1), _unit("b2", 1), _unit("e1", 2), _unit("e2", 2)],
        {
            "b1": _entry(0, 2),
            "b2": _entry(0, 4),
            "e1": _entry(0, 0),
            "e2": _entry(0, 40),
        },
    )
    assert _SCRIPT._count_distinct_focus_targets(gs, 1) == 1


def test_count_distinct_focus_targets_dispersion():
    # chaque escouade bot est collée à un ennemi différent
    gs = _gs(
        [_unit("b1", 1), _unit("b2", 1), _unit("e1", 2), _unit("e2", 2)],
        {
            "b1": _entry(0, 0),
            "b2": _entry(0, 40),
            "e1": _entry(0, 1),
            "e2": _entry(0, 41),
        },
    )
    assert _SCRIPT._count_distinct_focus_targets(gs, 1) == 2


def test_count_distinct_focus_targets_ennemi_en_reserves_exclu():
    # e2 est en réserves : les deux escouades bot ne peuvent élire que e1, alors même que b1 est
    # PLUS PROCHE de la case sentinel (-1,-1) que du seul ennemi réellement sur table.
    gs = _gs(
        [_unit("b1", 1), _unit("b2", 1), _unit("e1", 2), _unit("e2", 2)],
        {
            "b1": _entry(0, 0),
            "b2": _entry(0, 41),
            "e1": _entry(0, 40),
            "e2": _RESERVES,
        },
    )
    assert _SCRIPT._count_distinct_focus_targets(gs, 1) == 1


# ---------------------------------------------------------------------------
# _avg_focus_target_distance
# ---------------------------------------------------------------------------


def _bot(focus: str | None, marker: Any = (1, 1)) -> Any:
    """Bot factice.

    `_focus_turn` est aussi indispensable que `_focus_target` : le vrai `DecapitationBot` crée
    les deux ensemble et périme l'un PAR l'autre. Un double qui ne porterait que la cible
    modéliserait un objet qui n'existe pas, et laisserait passer la lecture d'une cible périmée.
    Le défaut par défaut est le marqueur À JOUR — l'état nominal ; le cas périmé se demande.
    """
    return SimpleNamespace(_focus_target=focus, _focus_turn=marker)


def test_avg_focus_target_distance_leve_si_focus_target_allie():
    # "allied" a player=1, même équipe que le bot, et le marqueur est À JOUR → RuntimeError
    gs = _gs([_unit("allied", 1)], {"allied": _entry(0, 4)})
    with pytest.raises(RuntimeError, match="bot-player"):
        _SCRIPT._avg_focus_target_distance(gs, _bot("allied"), 1)


def test_avg_focus_target_distance_none_si_cible_perimee_du_tour_precedent():
    """Le run de référence PLANTAIT ici (2026-08-13), et sur un bot parfaitement configuré.

    `_focus_target` est lu NU, donc il porte encore la cible de l'épisode précédent tant que le
    bot n'a pas rejoué. Or `agent_seat_mode` vaut « random » : au changement d'épisode le bot
    change de siège, et cette cible ennemie devient une escouade À LUI. Le garde de joueur levait
    alors « bot mal configuré » au 2e épisode de `decapitation` — marqueur relevé `(1, 5)` contre
    un état `episode=2, turn=1`.
    """
    gs = _gs([_unit("allied", 1)], {"allied": _entry(0, 4)})  # episode_number=1, turn=1
    perime = _bot("allied", marker=(0, 5))  # marqueur de l'épisode d'AVANT

    assert _SCRIPT._avg_focus_target_distance(gs, perime, 1) is None


def test_avg_focus_target_distance_none_si_meme_episode_mais_tour_precedent():
    """La péremption porte sur (épisode, TOUR), pas sur l'épisode seul.

    `DecapitationBot._focus` oublie sa cible à chaque changement de tour : une cible du tour 1
    lue au tour 2 n'a pas encore été réélue, et la mesurer prêterait au bot une intention qu'il
    n'a plus.
    """
    gs = _gs([_unit("bot", 1), _unit("en", 2)], {"bot": _entry(0, 0), "en": _entry(0, 4)})
    gs["turn"] = 2

    assert _SCRIPT._avg_focus_target_distance(gs, _bot("en", marker=(1, 1)), 1) is None


def test_avg_focus_target_distance_leve_si_focus_target_introuvable():
    # "phantom" n'existe pas dans gs['units']
    gs = _gs([_unit("bot", 1)], {"bot": _entry(0, 0)})
    with pytest.raises(RuntimeError, match="introuvable"):
        _SCRIPT._avg_focus_target_distance(gs, _bot("phantom"), 1)


def test_avg_focus_target_distance_none_sans_attribut():
    gs = _gs([_unit("bot", 1), _unit("en", 2)], {"bot": _entry(0, 0), "en": _entry(0, 4)})
    sans_attribut = SimpleNamespace()
    assert not hasattr(sans_attribut, "_focus_target")
    assert _SCRIPT._avg_focus_target_distance(gs, sans_attribut, 1) is None


def test_avg_focus_target_distance_none_si_focus_none():
    gs = _gs([_unit("bot", 1), _unit("en", 2)], {"bot": _entry(0, 0), "en": _entry(0, 4)})
    assert _SCRIPT._avg_focus_target_distance(gs, _bot(None), 1) is None


def test_avg_focus_target_distance_none_si_cible_eliminee():
    gs = _gs([_unit("bot", 1), _unit("en", 2)], {"bot": _entry(0, 0)})  # "en" hors cache
    assert _SCRIPT._avg_focus_target_distance(gs, _bot("en"), 1) is None


def test_avg_focus_target_distance_none_si_cible_en_reserves():
    gs = _gs([_unit("bot", 1), _unit("en", 2)], {"bot": _entry(0, 0), "en": _RESERVES})
    assert _SCRIPT._avg_focus_target_distance(gs, _bot("en"), 1) is None


def test_avg_focus_target_distance_calcul_simple():
    gs = _gs([_unit("bot", 1), _unit("en", 2)], {"bot": _entry(0, 0), "en": _entry(0, 4)})
    result = _SCRIPT._avg_focus_target_distance(gs, _bot("en"), 1)
    assert result is not None
    assert result == pytest.approx(4.0, abs=1.0)


def test_avg_focus_target_distance_ignore_la_cible_la_plus_proche():
    # e_proche est à 1 hex de b1, mais la cible focalisée est "en" : la moyenne suit "en", pas e_proche
    gs = _gs(
        [_unit("b1", 1), _unit("e_proche", 2), _unit("en", 2)],
        {"b1": _entry(0, 0), "e_proche": _entry(0, 1), "en": _entry(0, 4)},
    )
    result = _SCRIPT._avg_focus_target_distance(gs, _bot("en"), 1)
    assert result is not None
    assert result == pytest.approx(4.0, abs=1.0)


def test_avg_focus_target_distance_bot_en_reserves_exclu():
    # b2 est en réserves : la moyenne ne porte que sur b1 (distance 4), pas sur un couple
    gs = _gs(
        [_unit("b1", 1), _unit("b2", 1), _unit("en", 2)],
        {"b1": _entry(0, 0), "b2": _RESERVES, "en": _entry(0, 4)},
    )
    result = _SCRIPT._avg_focus_target_distance(gs, _bot("en"), 1)
    assert result is not None
    assert result == pytest.approx(4.0, abs=1.0)


def test_avg_focus_target_distance_none_si_aucun_bot_sur_table():
    gs = _gs(
        [_unit("b1", 1), _unit("en", 2)],
        {"b1": _RESERVES, "en": _entry(0, 4)},
    )
    assert _SCRIPT._avg_focus_target_distance(gs, _bot("en"), 1) is None


# ---------------------------------------------------------------------------
# _turns_of_key
# ---------------------------------------------------------------------------


def test_turns_of_key_extrait_les_valeurs_par_tour():
    records = [
        {"dist_by_turn": {"1": 3.5, "3": 7.0}},
        {"dist_by_turn": {"1": 4.5, "3": 6.0}},
    ]
    result = _SCRIPT._turns_of_key(records, "dist_by_turn")
    assert result == {1: [3.5, 4.5], 3: [7.0, 6.0]}


def test_turns_of_key_ignore_cle_absente():
    records = [
        {"dist_by_turn": {"1": 3.5}},
        {},  # pas de dist_by_turn
    ]
    result = _SCRIPT._turns_of_key(records, "dist_by_turn")
    assert result == {1: [3.5]}


def test_turns_of_key_vide_si_aucun_record():
    assert _SCRIPT._turns_of_key([], "dist_by_turn") == {}


# ---------------------------------------------------------------------------
# _loss_rate_by_turn
# ---------------------------------------------------------------------------


def test_loss_rate_by_turn_zero_au_premier_tour():
    records = [{"squads_by_turn": {"1": 3, "2": 2, "3": 1}}]
    result = _SCRIPT._loss_rate_by_turn(records)
    assert result[1] == [pytest.approx(0.0)]


def test_loss_rate_by_turn_progression():
    records = [{"squads_by_turn": {"1": 4, "2": 3, "3": 2, "4": 1}}]
    result = _SCRIPT._loss_rate_by_turn(records)
    assert result[2] == [pytest.approx(0.25)]
    assert result[3] == [pytest.approx(0.50)]
    assert result[4] == [pytest.approx(0.75)]


def test_loss_rate_by_turn_ignore_record_sans_squads():
    records = [{"squads_by_turn": {"1": 2, "2": 1}}, {}]
    result = _SCRIPT._loss_rate_by_turn(records)
    assert 1 in result and len(result[1]) == 1


def test_loss_rate_by_turn_baseline_zero_ignore():
    records = [{"squads_by_turn": {"1": 0, "2": 0}}]
    result = _SCRIPT._loss_rate_by_turn(records)
    assert result == {}


# ---------------------------------------------------------------------------
# _episode_record (paramètres optionnels)
# ---------------------------------------------------------------------------


def test_episode_record_sans_metriques_optionnelles():
    rec = _SCRIPT._episode_record("alpha", 0, 42, 1, {1: 2, 2: 3})
    assert "zones_by_turn" in rec
    assert "dist_by_turn" not in rec
    assert "squads_by_turn" not in rec
    assert "distinct_targets_by_turn" not in rec
    assert "focus_dist_by_turn" not in rec


def test_episode_record_avec_focus_snapshots():
    rec = _SCRIPT._episode_record(
        "decap", 0, 42, 1, {1: 2}, None, None, {1: 3, 2: 1}, {1: 8.5},
    )
    assert rec["distinct_targets_by_turn"] == {"1": 3, "2": 1}
    assert rec["focus_dist_by_turn"]["1"] == 8.5


def test_episode_record_avec_dist_snapshot():
    rec = _SCRIPT._episode_record("alpha", 0, 42, 1, {1: 2}, {1: 5.5})
    assert "dist_by_turn" in rec
    assert rec["dist_by_turn"]["1"] == 5.5


def test_episode_record_avec_squad_snapshot():
    rec = _SCRIPT._episode_record("alpha", 0, 42, 1, {1: 2}, None, {1: 3, 2: 2})
    assert "squads_by_turn" in rec
    assert rec["squads_by_turn"]["2"] == 2


def test_episode_record_champs_de_base():
    rec = _SCRIPT._episode_record("decap", 3, 99, 2, {1: 1})
    assert rec["bot"] == "decap"
    assert rec["episode"] == 3
    assert rec["seed"] == 99
    assert rec["bot_player"] == 2
