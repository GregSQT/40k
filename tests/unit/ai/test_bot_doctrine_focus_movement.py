"""`DecapitationBot` MARCHE vers la cible qu'il a élue, pas vers l'ennemi le plus proche.

LE défaut que ce fichier verrouille, mesuré le 2026-08-13 sur 60 épisodes (board/44x60x1) : les
cinq escouades convergeaient chacune vers un ennemi DIFFÉRENT, le bot finissait à 14,9 hexes du
plus proche ennemi et perdait 10,7 % de ses escouades par tour. La cause n'était pas un réglage :
la cible du tour était enregistrée depuis le TIR, or la phase move le précède dans le tour et le
changement de tour venait d'effacer celle du tour d'avant. Le déplacement ne lisait donc jamais
qu'un focus vide, et « faire porter le terme d'ennemi sur la cible focalisée » aurait été un
no-op tant que l'élection restait accrochée au premier tir.

⚠️ CE QUE CE FICHIER DOIT TENIR EN PLUS DU CAS NOMINAL : que l'élection ait bien lieu SANS
qu'aucun tir n'ait eu lieu (c'est tout le défaut), que les escouades suivantes du tour la
reprennent au lieu d'en élire une chacune, et que les cinq autres styles gardent le terme
`min(distance)` sur toutes les ancres — `select_movement_destination` reste commun.
"""
from __future__ import annotations

from typing import Any, Dict, List, Sequence, Tuple

import pytest

import ai.bot_doctrines as doc

#: Poids réduits au TERME D'ENNEMI : `w_objective = 0` (et aucun objectif sur la table), `w_fire`
#: et `w_risk` nuls pour court-circuiter la seconde passe. La destination ne dépend alors QUE des
#: ancres rendues par `movement_enemy_anchors`, qui est exactement ce que ce fichier observe.
POIDS_ENNEMI_SEUL = (0.0, 1.0, 0.0, 0.0, 0.0, 0.0)

#: L'escouade qui décide, et les deux ennemis. `FAIBLE` est le plus PROCHE d'elle, `JUTEUX` le
#: plus loin : sans focus le bot va vers le premier, avec focus vers le second. Deux positions
#: équidistantes rendraient le test vert quelle que soit la liste d'ancres.
MOI = (5, 5)
FAIBLE = (4, 4)
JUTEUX = (11, 11)

#: Une destination collée à chaque ennemi.
VERS_FAIBLE = (3, 3)
VERS_JUTEUX = (9, 9)

#: Dégâts espérés imposés par ennemi (cf. `_degats`). `JUTEUX` gagne l'élection dans les deux
#: modes : ce fichier ne mesure pas le critère d'élection, il mesure ce que le déplacement en fait.
DEGATS = {"101": 1.0, "102": 9.0}

HORS_TABLE = (-1, -1)


def _state(
    turn: int = 1,
    *,
    ennemis: Sequence[Tuple[str, Tuple[int, int]]] = (("101", FAIBLE), ("102", JUTEUX)),
) -> Dict[str, Any]:
    """État moteur minimal : mon escouade `2` (joueur 1) et les ennemis passés (joueur 2).

    `HP_CUR` est posé à 10, au-dessus du meilleur dégât (9.0) : aucune cible n'est « tuable ce
    tour », donc le bonus de 1000 de `_score_kill_now` ne peut pas masquer l'ordre des dégâts.
    Aucun objectif sur la table : la carte de distance est alors `None` et le score se réduit au
    terme d'ennemi.
    """
    units: List[Dict[str, Any]] = [{"id": "2", "player": 1}]
    units_cache: Dict[str, Any] = {
        "2": {"player": 1, "col": MOI[0], "row": MOI[1], "HP_CUR": 10},
    }
    for sid, (col, row) in ennemis:
        units.append({"id": sid, "player": 2})
        units_cache[sid] = {"player": 2, "col": col, "row": row, "HP_CUR": 10}
    return {
        "turn": turn,
        "episode_number": 1,
        "units": units,
        "unit_by_id": {str(unit["id"]): unit for unit in units},
        "units_cache": units_cache,
    }


def _moi(state: Dict[str, Any]) -> Dict[str, Any]:
    return state["unit_by_id"]["2"]


@pytest.fixture(autouse=True)
def _degats(monkeypatch: pytest.MonkeyPatch) -> None:
    """Table de dégâts imposée : c'est une pure ENTRÉE de l'élection, comme les cartes de
    distance le sont du terme d'objectif. La calculer vraiment exigerait des profils d'armes
    complets, qui ne changeraient rien à ce que ce fichier observe."""
    monkeypatch.setattr(
        doc, "_damage_on",
        lambda game_state, attacker_id, target_id, is_ranged: DEGATS[str(target_id)],
    )


class _Decapitation(doc.DecapitationBot):
    """`DecapitationBot` avec ses poids FIXÉS : le fichier de config ne doit pas décider du test."""

    def movement_weights(self, unit, game_state):
        return POIDS_ENNEMI_SEUL


class _Controle(doc._DoctrineBot):
    """Un style quelconque, MÊMES poids : il ne connaît pas le focus et garde toutes les ancres.

    C'est le témoin qui distingue « la correction agit » de « la géométrie du test penchait déjà
    de ce côté » — sans lui, une erreur de placement rendrait le test vert sans rien prouver.
    """

    def movement_weights(self, unit, game_state):
        return POIDS_ENNEMI_SEUL


def test_the_other_styles_still_walk_towards_the_nearest_enemy() -> None:
    """Le témoin : `min(distance)` sur TOUTES les ancres, donc la destination près du plus proche.

    Verrou du jumeau : si la restriction au focus avait été posée dans
    `select_movement_destination` au lieu du point d'extension, les cinq autres styles la
    subiraient — et ce test tomberait.
    """
    state = _state()

    choisie = _Controle().select_movement_destination(
        _moi(state), [VERS_FAIBLE, VERS_JUTEUX], state
    )

    assert choisie == VERS_FAIBLE


def test_decapitation_walks_towards_its_focused_target_instead() -> None:
    """LE verrou. Même état, même géométrie, mêmes poids : seule la doctrine change la réponse."""
    state = _state()

    choisie = _Decapitation().select_movement_destination(
        _moi(state), [VERS_FAIBLE, VERS_JUTEUX], state
    )

    assert choisie == VERS_JUTEUX


def test_the_target_is_elected_during_the_move_phase_without_any_shot() -> None:
    """LA correction de fond : l'élection n'attend plus le premier tir.

    Avant, `_focus` rendait `None` tant que `_shoot`/`_fight` n'avaient pas enregistré une cible —
    donc toujours `None` en phase move, puisque le changement de tour venait de l'effacer.
    """
    bot = _Decapitation()
    state = _state()

    assert bot._focus_target is None, "rien n'est élu avant la première lecture"
    bot.select_movement_destination(_moi(state), [VERS_FAIBLE, VERS_JUTEUX], state)

    assert bot._focus_target == "102"


def test_the_second_squad_of_the_turn_keeps_the_elected_target() -> None:
    """CONCENTRATION : la doctrine ne vaut que si les escouades suivantes reprennent la cible.

    L'escouade qui active en second a ici une table de dégâts INVERSÉE — si elle réélisait pour
    son compte, elle choisirait `101`. Elle doit garder `102`.
    """
    bot = _Decapitation()
    state = _state()
    bot.select_movement_destination(_moi(state), [VERS_FAIBLE, VERS_JUTEUX], state)

    doc._damage_on = lambda game_state, attacker_id, target_id, is_ranged: {
        "101": 9.0, "102": 1.0,
    }[str(target_id)]

    assert bot._focus(state, _moi(state)) == "102"


def test_a_new_turn_elects_again() -> None:
    """VERT VACANT : vérifier que la cible CHANGE quand elle doit changer.

    Un fichier qui n'observerait que la concentration passerait sur un focus figé pour la partie
    entière — le défaut exact que `_focus_turn` existe pour empêcher.
    """
    bot = _Decapitation()
    bot._focus(_state(turn=1), _moi(_state(turn=1)))

    tour_deux = _state(turn=2, ennemis=(("101", FAIBLE),))

    assert bot._focus(tour_deux, _moi(tour_deux)) == "101", "la cible du tour 1 n'est plus là"


def test_a_focused_target_off_the_table_falls_back_to_every_anchor() -> None:
    """Repli fonctionnel (T1) : une cible en réserves (20.01) n'a pas d'ancre à viser.

    Le terme d'ennemi doit alors retomber sur toutes les ancres présentes — « pas encore
    arrivée » n'est pas une erreur, et laisser le bot marcher vers `(-1, -1)` en serait une.
    """
    state = _state(ennemis=(("101", FAIBLE), ("102", HORS_TABLE)))
    bot = _Decapitation()
    bot._focus_target = "102"
    bot._focus_turn = (1, 1)

    choisie = bot.select_movement_destination(_moi(state), [VERS_FAIBLE, VERS_JUTEUX], state)

    assert choisie == VERS_FAIBLE
