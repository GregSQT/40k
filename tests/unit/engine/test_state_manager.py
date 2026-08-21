"""Tests unitaires — GameStateManager en isolation (engine/game_state.py).

Cible les méthodes publiques sans passer par W40KEngine.
"""

from __future__ import annotations

from typing import Any, Dict

import pytest

from engine.constants import DRAW_WINNER
from engine.game_state import GameStateManager
from engine.phase_handlers.shared_utils import build_units_cache
from tests._state_invariants import unit_invariants


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

_MINIMAL_CONFIG = {"board": {"default": {"inches_to_subhex": 1}}}

_FULL_UNIT_CFG: Dict[str, Any] = {
    "id": 1, "player": 1, "col": 3, "row": 3,
    "unitType": "T", "DISPLAY_NAME": "TestUnit",
    "HP_CUR": 3, "HP_MAX": 3, "MOVE": 6, "T": 4,
    "ARMOR_SAVE": 4, "INVUL_SAVE": 0,
    "RNG_WEAPONS": [], "CC_WEAPONS": [],
    # `FACTION_KEYWORDS` : exigé par `_build_enhanced_unit` (la datasheet le porte toujours,
    # même vide), donc une config d'entrée complète le déclare — comme `UNIT_KEYWORDS`.
    "UNIT_RULES": [], "UNIT_KEYWORDS": [], "FACTION_KEYWORDS": [],
    "LD": 7, "OC": 1, "VALUE": 100, "ICON": "t",
    "ICON_SCALE": 1.0, "ILLUSTRATION_RATIO": 1.0,
    "BASE_SHAPE": "round", "BASE_SIZE": 1, "MODEL_HEIGHT": 2.5,
}


def _sm(config: Dict[str, Any] | None = None) -> GameStateManager:
    return GameStateManager(config or _MINIMAL_CONFIG)


def _raw_unit(uid: int, player: int, value: int = 100) -> Dict[str, Any]:
    return {**unit_invariants(), "id": uid, "player": player, "col": uid, "row": 0,
            "HP_CUR": 3, "HP_MAX": 3, "VALUE": value, "OC": 1,
            "T": 4, "ARMOR_SAVE": 3, "INVUL_SAVE": 7,
            "SHOOT_LEFT": 1, "ATTACK_LEFT": 1,
            "RNG_WEAPONS": [], "CC_WEAPONS": [], "UNIT_RULES": [],
            "BASE_SHAPE": "round", "BASE_SIZE": 1, "MODEL_HEIGHT": 2.5}


def _make_gs(p1_vp: int, p2_vp: int,
             p1_value: int = 100, p2_value: int = 100,
             turn_limit_reached: bool = True) -> Dict[str, Any]:
    units = [_raw_unit(1, 1, p1_value), _raw_unit(2, 2, p2_value)]
    gs: Dict[str, Any] = {
        "turn_limit_reached": turn_limit_reached,
        "victory_points": {1: p1_vp, 2: p2_vp},
        "units": units,
        "unit_by_id": {str(u["id"]): u for u in units},
        "config": {"game_rules": {
            "max_turns": 5, "engagement_zone": 1, "engagement_zone_vertical": 5}},
    }
    build_units_cache(gs)
    return gs


# ─────────────────────────────────────────────────────────────────────────────
# Tests — create_unit
# ─────────────────────────────────────────────────────────────────────────────

class TestCreateUnit:

    def test_create_unit_has_hp_cur(self) -> None:
        """sm_create_hp : create_unit() → champ HP_CUR présent."""
        unit = _sm().create_unit(_FULL_UNIT_CFG)
        assert "HP_CUR" in unit and unit["HP_CUR"] == 3

    def test_create_unit_has_uppercase_stats(self) -> None:
        """sm_create_upper : create_unit() → tous les champs UPPERCASE requis présents."""
        unit = _sm().create_unit(_FULL_UNIT_CFG)
        for field in ("HP_CUR", "HP_MAX", "MOVE", "T", "ARMOR_SAVE", "INVUL_SAVE",
                      "LD", "OC", "VALUE", "ICON", "ICON_SCALE"):
            assert field in unit, f"Champ manquant : {field}"

    def test_create_unit_identity_fields(self) -> None:
        """sm_create_id : id, player, col, row correctement copiés."""
        unit = _sm().create_unit(_FULL_UNIT_CFG)
        assert unit["id"] == 1
        assert unit["player"] == 1
        assert unit["col"] == 3
        assert unit["row"] == 3


# ─────────────────────────────────────────────────────────────────────────────
# Tests — validate_uppercase_fields
# ─────────────────────────────────────────────────────────────────────────────

class TestValidateUppercaseFields:

    def test_valid_unit_does_not_raise(self) -> None:
        """sm_valid_ok : unité complète → pas d'exception."""
        unit = _sm().create_unit(_FULL_UNIT_CFG)
        _sm().validate_uppercase_fields(unit)  # should not raise

    def test_missing_field_raises_value_error(self) -> None:
        """sm_valid_miss : champ manquant → ValueError."""
        unit = _sm().create_unit(_FULL_UNIT_CFG)
        del unit["HP_CUR"]
        with pytest.raises(ValueError, match=r"missing required UPPERCASE field"):
            _sm().validate_uppercase_fields(unit)


# ─────────────────────────────────────────────────────────────────────────────
# Tests — determine_winner / determine_winner_with_method
# ─────────────────────────────────────────────────────────────────────────────

class TestDetermineWinner:

    def test_returns_none_when_not_reached(self) -> None:
        """sm_win_none : turn_limit_reached=False → None."""
        result = _sm().determine_winner(_make_gs(3, 1, turn_limit_reached=False))
        assert result is None

    def test_p1_wins(self) -> None:
        """sm_win_p1 : p1_vp > p2_vp → 1."""
        assert _sm().determine_winner(_make_gs(5, 2)) == 1

    def test_p2_wins(self) -> None:
        """sm_win_p2 : p2_vp > p1_vp → 2."""
        assert _sm().determine_winner(_make_gs(1, 4)) == 2

    def test_draw_returns_minus_1(self) -> None:
        """sm_win_draw : VP et VALUE égaux → -1."""
        assert _sm().determine_winner(_make_gs(2, 2)) == DRAW_WINNER


# ─────────────────────────────────────────────────────────────────────────────
# Tests — check_game_over
# ─────────────────────────────────────────────────────────────────────────────

class TestCheckGameOver:

    def test_false_when_turn_limit_not_reached(self) -> None:
        """sm_cgo_false : turn_limit_reached=False → False."""
        # La duree de bataille vient de game_rules.max_turns : le state doit la porter.
        gs = {"turn_limit_reached": False, "turn": 1,
              "config": {"game_rules": {"max_turns": 5}}}
        assert _sm().check_game_over(gs) is False

    def test_true_when_turn_limit_reached(self) -> None:
        """sm_cgo_true : turn_limit_reached=True → True."""
        gs = {"turn_limit_reached": True, "turn": 1,
              "config": {"game_rules": {"max_turns": 5}}}
        assert _sm().check_game_over(gs) is True


# ─────────────────────────────────────────────────────────────────────────────
# Verrou du socle d'unité (tests/_state_invariants.py)
# ─────────────────────────────────────────────────────────────────────────────

class TestUnitInvariantsConformity:
    """Verrou de dérive du socle ``unit_invariants()``.

    Même découpage que son jumeau ``TestTurnStateInvariantsConformity``
    (tests/unit/engine/test_engine_reset.py) : clés / valeurs / exhaustivité. Le socle
    **réplique** les champs d'état qu'une unité de production porte toujours — une fixture
    unitaire ne peut pas faire tourner un chargement de scénario. Ces tests sont ce qui empêche
    la copie de diverger du moteur : si un constructeur change une valeur, ajoute ou renomme un
    champ constant, ils rougissent ici et pas dans les fixtures, en silence.

    Les DEUX constructeurs sont exercés : ``create_unit`` (API build army, fixtures) et
    ``_build_enhanced_unit`` (chargement de scénario et changement de roster). Le second ne
    demande ni board ni registre — position injectée, ``unit_registry`` n'étant lu que pour un
    override ``unit_type`` par figurine — donc rien ne justifiait de le laisser diverger.
    """

    #: Champs que les constructeurs DÉRIVENT d'autres champs de l'unité : leur valeur dépend du
    #: roster (armes, mots-clés, règles), donc un socle les figerait à une valeur fausse. La
    #: classification faisant autorité est la docstring de ``unit_invariants()``.
    DERIVE = {
        "selectedRngWeaponIndex", "selectedCcWeaponIndex", "SHOOT_LEFT", "ATTACK_LEFT",
        "hideable", "_UNIT_RULES_OWN",
    }

    def test_socle_keys_all_posed_by_create_unit(self) -> None:
        """unit_conformity_keys : toute clé du socle existe dans l'unité construite."""
        unit = _sm().create_unit(_FULL_UNIT_CFG)

        absentes = sorted(k for k in unit_invariants() if k not in unit)
        assert absentes == [], f"Le socle réplique des champs que create_unit() ne pose pas : {absentes}"

    def test_socle_values_match_create_unit(self) -> None:
        """unit_conformity_values : chaque valeur du socle == la valeur posée par create_unit()."""
        unit = _sm().create_unit(_FULL_UNIT_CFG)

        socle = unit_invariants()
        # Les clés absentes sont le sujet du test précédent : ici on ne juge que les valeurs,
        # sinon un champ fantôme du socle remonterait en KeyError illisible.
        divergentes = {
            k: (v, unit[k])
            for k, v in socle.items()
            if k in unit and (unit[k] != v or type(unit[k]) is not type(v))
        }
        assert divergentes == {}, f"Socle d'unité désaligné de create_unit() : {divergentes}"

    def test_socle_values_match_build_enhanced_unit(self) -> None:
        """unit_conformity_second_builder : le socle vaut aussi pour le chemin du chargement.

        ``_build_enhanced_unit`` construit TOUTES les unités du moteur (scénario, change_roster)
        et duplique le bloc de champs d'état de ``create_unit``. Sans ce test, il pouvait
        diverger sans que rien ne rougisse — les fixtures décrivant alors une unité que le
        chemin de production majoritaire ne produit plus.
        """
        unit = _sm()._build_enhanced_unit(
            unit_data={"id": 1, "player": 1},
            full_unit_data=_FULL_UNIT_CFG,
            unit_type="T",
            unit_player=1,
            player_deployment_type="fixed",
            chosen_col=3,
            chosen_row=3,
            unit_registry=None,   # lu uniquement pour un override `unit_type` par figurine
        )

        socle = unit_invariants()
        divergentes = {
            k: (v, unit[k] if k in unit else "<ABSENT>")
            for k, v in socle.items()
            if k not in unit or unit[k] != v or type(unit[k]) is not type(v)
        }
        assert divergentes == {}, (
            f"Socle d'unité désaligné de _build_enhanced_unit() : {divergentes}"
        )

    def test_les_deux_constructeurs_posent_les_memes_champs(self) -> None:
        """unit_conformity_same_fields : create_unit et _build_enhanced_unit, MÊME jeu de clés.

        Les deux constructeurs dupliquent le même bloc de champs d'état, et ``initialize_units``
        repasse chaque unité enrichie par ``create_unit`` : un champ ajouté d'un seul côté est
        soit perdu en production (posé par l'enrichissement, effacé par ``create_unit``), soit
        absent du socle sans que l'exhaustivité ne le voie — c'est la dérive déjà vécue avec
        ``in_strategic_reserves`` (cf. game_state.py, commentaire des deux sources).
        """
        cree = _sm().create_unit(_FULL_UNIT_CFG)
        enrichie = _sm()._build_enhanced_unit(
            unit_data={"id": 1, "player": 1},
            full_unit_data=_FULL_UNIT_CFG,
            unit_type="T",
            unit_player=1,
            player_deployment_type="fixed",
            chosen_col=3,
            chosen_row=3,
            unit_registry=None,
        )

        assert sorted(set(cree) - set(enrichie)) == [], "champs que seul create_unit pose"
        assert sorted(set(enrichie) - set(cree)) == [], (
            "champs que seul _build_enhanced_unit pose : create_unit les effacera"
        )

    def test_create_unit_poses_no_unclassified_field(self) -> None:
        """unit_conformity_exhaustive : tout champ posé par create_unit() est classé.

        Filet de dérive inverse : un champ d'état ajouté au moteur doit entrer dans le socle
        (constant) ou dans ``DERIVE`` (calculé depuis le roster). Sans ce test, il n'entrerait
        nulle part et les fixtures recommenceraient à décrire une unité impossible.
        """
        unit = _sm().create_unit(_FULL_UNIT_CFG)

        socle = unit_invariants()
        non_classes = sorted(
            k for k in unit
            if k not in _FULL_UNIT_CFG and k not in socle and k not in self.DERIVE
        )
        assert non_classes == [], (
            f"create_unit() pose des champs ni dans le socle ni dans DERIVE : {non_classes}"
        )
