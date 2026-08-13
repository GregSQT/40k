"""§12.11 — `DecapitationBot` se DÉPLACE vers sa cible focalisée, pas vers l'ennemi le plus proche.

Le style concentrait déjà ses TIRS sur une cible unique (`target_score` + `_focus`), mais son
déplacement passait par le socle : `w_enemy` tirait chaque escouade vers l'ennemi le plus proche
d'ELLE. La doctrine se contredisait donc à chaque tour — on tire tous sur A, on marche tous vers
un B différent, et au tour suivant plus personne n'est à portée de A.

⚠️ PIÈGE D'ORDRE DES PHASES, la raison d'être de ces tests : le mouvement précède le tir (07.01)
et un `turn` couvre les DEUX joueurs (`fight_handlers` ne l'incrémente qu'après la mêlée de J2).
Une mémoire alimentée seulement par le tir et la mêlée est donc VIDE pendant tout le déplacement
du camp qui joue en premier. Les tests qui posent `_focus_target` à la main avant un mouvement
prouvent un chemin que la production n'atteint pas : ici la cible est ÉLUE par le mouvement
lui-même (`_elect`), et c'est cet état-là — mémoire vierge — que chaque test part de.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import pytest

import ai.bot_doctrines as doctrines
import ai.evaluation_bots as evaluation_bots
import engine.macro_intents as mi
import engine.phase_handlers.shared_utils as shared_utils
from ai.bot_doctrines import DecapitationBot, RacerBot

# La cible la plus PAYANTE est LOIN, un autre ennemi est collé à l'escouade : les deux
# comportements (socle / focalisé) rendent donc des ancres différentes, sinon rien n'est prouvé.
UNIT = {"id": "me", "player": 1}
OTHER_UNIT = {"id": "me2", "player": 1}
FOCUS_POS = (30, 40)
NEAREST_POS = (6, 5)

#: Dégâts espérés par cible, indépendants de la position (cf. `_firepower_profile`).
DAMAGE = {"focus": 5.0, "nearest": 1.0}
HP = 10.0


def _state(turn: int = 2) -> Dict[str, Any]:
    return {
        "turn": turn,
        "units": [
            {"id": "me", "player": 1},
            {"id": "me2", "player": 1},
            {"id": "focus", "player": 2},
            {"id": "nearest", "player": 2},
        ],
        "units_cache": {
            "me": {"id": "me", "col": 5, "row": 5, "player": 1},
            "me2": {"id": "me2", "col": 7, "row": 6, "player": 1},
            "focus": {"id": "focus", "col": FOCUS_POS[0], "row": FOCUS_POS[1], "player": 2},
            "nearest": {"id": "nearest", "col": NEAREST_POS[0], "row": NEAREST_POS[1],
                        "player": 2},
        },
    }


def _anchors(bot, state, unit=UNIT) -> List[Tuple[int, int]]:
    """Appelle le hook comme le fait `select_movement_destination` : `enemies` est fourni."""
    enemies = doctrines._living_enemies_on_table(unit, state)
    return sorted(bot._enemy_anchors(unit, state, enemies))


@pytest.fixture(autouse=True)
def _scoring_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    """Vivant = présent au cache ; dégâts et PV pilotés par le test, jamais par le roster réel."""
    monkeypatch.setattr(
        doctrines, "is_unit_alive", lambda sid, gs: str(sid) in gs["units_cache"],
    )
    monkeypatch.setattr(
        doctrines, "_damage_on", lambda gs, att, sid, is_ranged: DAMAGE[str(sid)],
    )
    monkeypatch.setattr(doctrines, "_hp_left", lambda sid, gs: HP)


def test_the_first_move_of_the_turn_elects_the_focus() -> None:
    """MÉMOIRE VIERGE — l'état RÉEL du premier déplacement du tour, celui où l'ancien code
    retombait sur le socle. La cible est élue ici, pas attendue du tir."""
    bot = DecapitationBot()

    assert _anchors(bot, _state()) == [FOCUS_POS]
    assert bot._focus_target == "focus"


def test_every_squad_of_the_turn_converges_on_the_target_elected_by_the_first() -> None:
    """C'est la mémoire PARTAGÉE qui fait la concentration : la 2de escouade lit l'élection de la
    1re au lieu d'en refaire une — et sans elle, collée à `nearest`, elle irait vers `nearest`."""
    bot = DecapitationBot()
    state = _state()
    elections: List[str] = []
    original = bot._elect
    bot._elect = lambda unit, gs, enemies: (  # type: ignore[method-assign]
        elections.append(str(unit["id"])) or original(unit, gs, enemies)
    )

    assert _anchors(bot, state, UNIT) == [FOCUS_POS]
    assert _anchors(bot, state, OTHER_UNIT) == [FOCUS_POS]
    assert elections == ["me"]
    assert _anchors(RacerBot(), state, OTHER_UNIT) == sorted([FOCUS_POS, NEAREST_POS])


def test_the_election_holds_for_the_turn_and_is_redone_at_the_next() -> None:
    """La cible du tour ne se rejuge pas en cours de tour (sinon les escouades divergent), et ne
    se traîne pas au tour suivant (`_focus` la périme sur le marqueur de tour)."""
    bot = DecapitationBot()
    assert _anchors(bot, _state(turn=2)) == [FOCUS_POS]

    DAMAGE["nearest"] = 50.0
    try:
        assert _anchors(bot, _state(turn=2)) == [FOCUS_POS]
        assert _anchors(bot, _state(turn=3)) == [NEAREST_POS]
    finally:
        DAMAGE["nearest"] = 1.0


def test_a_target_killed_mid_turn_is_replaced_not_abandoned() -> None:
    """La cible meurt : on en élit une autre. Rendre la main au socle ferait repartir chaque
    escouade vers SON plus proche voisin — l'éparpillement que le style existe pour éviter."""
    bot = DecapitationBot()
    state = _state()
    assert _anchors(bot, state) == [FOCUS_POS]

    del state["units_cache"]["focus"]
    state["units"] = [u for u in state["units"] if u["id"] != "focus"]

    assert _anchors(bot, state) == [NEAREST_POS]
    assert bot._focus_target == "nearest"


def test_a_focus_that_left_the_table_is_replaced() -> None:
    """20.01 : vivante hors table = sentinelle `(-1,-1)`. Elle est hors de `enemies`, donc traitée
    comme une cible perdue — sans garde, toutes les escouades marchaient vers le coin du plateau."""
    bot = DecapitationBot()
    state = _state()
    assert _anchors(bot, state) == [FOCUS_POS]

    state["units_cache"]["focus"]["col"] = -1
    state["units_cache"]["focus"]["row"] = -1

    assert _anchors(bot, state) == [NEAREST_POS]
    assert bot._focus_target == "nearest"


def test_no_enemy_on_the_table_gives_no_anchor() -> None:
    """Plus rien à viser : aucune ancre, et `w_enemy` s'efface au lieu de lire une cible morte."""
    bot = DecapitationBot()
    state = _state()
    for sid in ("focus", "nearest"):
        del state["units_cache"][sid]
    state["units"] = [u for u in state["units"] if u["player"] == 1]

    assert _anchors(bot, state) == []
    assert bot._focus_target is None


def test_the_movement_really_walks_toward_the_elected_target() -> None:
    """VERT VACANT : le chemin de PRODUCTION, `select_movement_destination`, bout en bout. Un
    hook corrigé mais jamais atteint par le vrai chemin ne corrige rien (T4 JUMEAU). `(10,10)`
    est la destination du socle (proche de `nearest`), `(25,35)` celle de la cible élue."""
    bot = DecapitationBot()
    state = _state()
    # Seul `w_enemy` est en jeu : pas d'objectifs (`distance_map` nulle), pas de 2de passe.
    bot.movement_weights = lambda unit, gs: (0.0, 1.0, 0.0, 0.0, 0.0, 0.0)  # type: ignore[method-assign]

    original_terms = doctrines._objective_terms
    doctrines._objective_terms = lambda *a, **k: (None, [])  # type: ignore[assignment]
    try:
        dest = bot.select_movement_destination(UNIT, [(10, 10), (25, 35)], state)
    finally:
        doctrines._objective_terms = original_terms  # type: ignore[assignment]

    assert dest == (25, 35)
    assert bot._focus_target == "focus"


def test_the_elected_target_also_steers_the_shooting() -> None:
    """L'intérêt de l'élection au mouvement : le TIR du même tour hérite de la cible, au lieu
    d'en choisir une autre — c'est toute la phase qui pointe vers une seule escouade."""
    bot = DecapitationBot()
    state = _state()
    assert _anchors(bot, state) == [FOCUS_POS]

    score = bot.target_score(UNIT, True, state)
    on_focus = score("focus", state["units_cache"]["focus"], state)
    on_nearest = score("nearest", state["units_cache"]["nearest"], state)

    assert on_focus is not None and on_nearest is not None
    assert on_focus > on_nearest + 1_000.0


#: Slots de tir, dans l'ordre rendu par `get_enemy_slot_mapping`.
SLOT_MAPPING = ["focus", "nearest"]


@pytest.fixture
def _slot_mapping(monkeypatch: pytest.MonkeyPatch) -> None:
    """Le mapping slot -> escouade ennemie, aux DEUX points qui le lisent.

    `_target_slot_entries` (choix de la cible) le lit depuis `ai.evaluation_bots`, `_remember`
    (mémoire du tour) depuis `engine.phase_handlers.shared_utils` par un import local : ne
    stubber qu'un des deux ferait tirer sur une cible et en mémoriser une autre.
    """
    mapping = lambda gs, player: list(SLOT_MAPPING)  # noqa: E731
    monkeypatch.setattr(evaluation_bots, "get_enemy_slot_mapping", mapping)
    monkeypatch.setattr(shared_utils, "get_enemy_slot_mapping", mapping)


def _shoot(bot, state, targets: List[str], unit=UNIT) -> Optional[str]:
    """Joue le TIR de production (`_shoot` -> `_best_slot_action` -> `_remember`).

    `targets` = les escouades que le masque ouvre à cette activation ; c'est le seul levier qui
    sépare « l'élue est atteignable » de « elle ne l'est pas ». Rend la cible réellement tirée.
    """
    valid = [mi.SHOOT_SLOT_BASE + SLOT_MAPPING.index(sid) for sid in targets]
    action = bot._shoot(valid, state, unit)
    assert action in mi.SHOOT_SLOTS, f"le bot n'a pas tiré : {action}"
    return SLOT_MAPPING[action - mi.SHOOT_SLOT_BASE]


def test_an_elected_target_the_mask_never_opens_is_replaced_by_the_first_shot(
    _slot_mapping: None,
) -> None:
    """LE TROU DE L'ÉLECTION AU MOUVEMENT : `_elect` classe sur les dégâts espérés, qui ne
    dépendent PAS de la position — l'élue peut donc être hors de portée de tout le monde. Sans
    reprise, `target_score` n'accordait son bonus à personne et chaque escouade repartait sur sa
    propre cible : une dispersion pire que celle du socle, dans le style qui existe pour la
    supprimer. Le premier tir réel tranche."""
    bot = DecapitationBot()
    state = _state()
    assert _anchors(bot, state) == [FOCUS_POS]  # `focus` élue au mouvement, la plus payante
    assert bot._focus_target == "focus" and bot._focus_confirmed is False

    assert _shoot(bot, state, ["nearest"]) == "nearest"  # `focus` hors masque
    assert bot._focus_target == "nearest" and bot._focus_confirmed is True


def test_the_second_squad_converges_on_the_target_the_first_actually_shot(
    _slot_mapping: None,
) -> None:
    """La reprise ne sert à rien si elle ne concentre pas : la 2de escouade, qui voit LES DEUX
    cibles, doit suivre celle que la 1re a pu tirer — pas relire l'élection périmée."""
    bot = DecapitationBot()
    state = _state()
    _anchors(bot, state)
    _shoot(bot, state, ["nearest"], UNIT)

    assert _shoot(bot, state, ["focus", "nearest"], OTHER_UNIT) == "nearest"


def test_the_target_shot_first_is_locked_for_the_rest_of_the_turn(_slot_mapping: None) -> None:
    """VERROU : sans lui, deux escouades aux portées disjointes se voleraient la cible à chaque
    activation et aucune troisième n'aurait de cap. Une seule attaque confirme, définitivement."""
    bot = DecapitationBot()
    state = _state()
    _anchors(bot, state)
    _shoot(bot, state, ["nearest"], UNIT)

    assert _shoot(bot, state, ["focus"], OTHER_UNIT) == "focus"  # seule cible ouverte
    assert bot._focus_target == "nearest", "la cible du tour a été volée après confirmation"


def test_the_elected_target_is_kept_when_it_is_the_one_actually_shot(_slot_mapping: None) -> None:
    """Le cas nominal : l'élue est atteignable, le bonus joue, la confirmation ne change rien
    d'autre que le verrou."""
    bot = DecapitationBot()
    state = _state()
    _anchors(bot, state)

    assert _shoot(bot, state, ["focus", "nearest"]) == "focus"
    assert bot._focus_target == "focus" and bot._focus_confirmed is True


def test_a_confirmed_target_that_dies_lets_the_next_shot_re_elect(_slot_mapping: None) -> None:
    """La confirmation s'oublie AVEC la cible, jamais séparément : une cible morte en cours de
    tour laissée `confirmée` ferait sortir `_remember` trop tôt, et plus personne n'écrirait de
    cible jusqu'au tour suivant."""
    bot = DecapitationBot()
    state = _state()
    _anchors(bot, state)
    _shoot(bot, state, ["focus"])
    assert bot._focus_confirmed is True

    del state["units_cache"]["focus"]
    state["units"] = [u for u in state["units"] if u["id"] != "focus"]

    assert _shoot(bot, state, ["nearest"], OTHER_UNIT) == "nearest"
    assert bot._focus_target == "nearest" and bot._focus_confirmed is True


def test_the_base_style_still_sees_every_enemy() -> None:
    """Le hook du socle n'est pas touché par la concentration : `w_enemy` y agit sur le plus
    proche de TOUTES les escouades ennemies sur table."""
    assert _anchors(RacerBot(), _state()) == sorted([FOCUS_POS, NEAREST_POS])
