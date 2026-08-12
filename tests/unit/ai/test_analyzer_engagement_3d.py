"""Engagement 3D côté ANALYZER (§03.04 : 2" horizontal ET 5" vertical).

Pourquoi ce fichier existe. Le moteur mesure désormais l'engagement du fight en 3D. L'analyzer,
lui, reconstruit un état depuis `step.log` et appelait la primitive d'engagement **sans seuil
vertical** : sur un plateau à étages, il aurait signalé « combat depuis une position non
adjacente » là où le moteur, lui, refuse tout simplement le combat — un contrôle qui contredit
le système qu'il contrôle produit des faux positifs à trier à la main (le dépôt en a déjà payé
deux, cf. LoS 06.01 et « Fight from non-adjacent »).

Ce que ces tests verrouillent :
  - le segment `[MODELS:]` transporte l'altitude par socle (`z<hauteur>`, en pouces) ;
  - `is_within_engine_engagement_zone` applique le gate vertical quand elle la reçoit ;
  - elle reste 2D — et ne lève pas — quand la donnée verticale manque, d'un seul côté comme
    des deux ;
  - les deux fronts d'altitude (avant / après la ligne courante) ne se mélangent pas.
"""

from __future__ import annotations

from typing import Any, Dict, Tuple

import pytest

import ai.analyzer as an
from ai.analyzer_perfig import parse_models_heights, parse_models_segment
from tests.unit.ai._fabriques import pose_etat_du_run


ENGAGEMENT_ZONE = 20     # 2" à inches_to_subhex=10, déjà scalé (contrat moteur)
VERTICAL_ZONE = 5.0      # 5" (§03.04), en POUCES — jamais scalé
MODEL_HEIGHT = 2.5
FLOOR_HEIGHT = 10.0      # 10" > 5" + 2,5" → hors zone verticale


@pytest.fixture(autouse=True)
def _regles_du_run():
    """Hors `parse_step_log`, les règles du run se posent à la main : les getters lèvent plutôt
    que de retomber sur le config courant (une règle absente n'a pas de repli JUSTE)."""
    pose_etat_du_run(10, ez_subhex=ENGAGEMENT_ZONE, ez_vertical_inches=VERTICAL_ZONE)


# ─────────────────────────────────────────────────────────────────────────────
# Le journal : l'altitude voyage avec la position
# ─────────────────────────────────────────────────────────────────────────────

def test_the_models_segment_carries_a_floor_height_per_model():
    line = "Unit 1(20,20) FOUGHT [MODELS: 1#0@(20,20,z0) 1#1@(21,20,z10.5)] [SUCCESS]"

    assert parse_models_segment(line) == {"1": {"1#0": (20, 20), "1#1": (21, 20)}}, (
        "les positions doivent rester PLANES : la couche per-figurine est horizontale"
    )
    assert parse_models_heights(line) == {"1": {"1#0": 0.0, "1#1": 10.5}}


def test_a_segment_without_height_yields_positions_but_no_altitude():
    """Un step.log antérieur à l'altitude reste LISIBLE — ses positions sont exactes, et sur un
    plateau plat un verdict horizontal est le bon verdict. Ce qu'il ne doit surtout pas faire,
    c'est rendre `0.0` : ce serait une altitude INVENTÉE, donc un gate vertical appliqué à des
    données qui n'existent pas. D'où « positions oui, hauteurs None », et pas « hauteurs = sol ».
    """
    line = "Unit 1(20,20) FOUGHT [MODELS: 1#0@(20,20)] [SUCCESS]"

    assert parse_models_segment(line) == {"1": {"1#0": (20, 20)}}
    assert parse_models_heights(line) is None


def test_a_mixed_segment_only_reports_the_models_that_carry_a_height():
    """Le socle muet est ABSENT de la carte, pas posé au sol : c'est ce qui permet au prédicat
    de le laisser en 2D au lieu de le comparer à une altitude supposée."""
    line = "Unit 1(20,20) FOUGHT [MODELS: 1#0@(20,20,z4) 1#1@(21,20)] [SUCCESS]"

    assert parse_models_heights(line) == {"1": {"1#0": 4.0}}


# ─────────────────────────────────────────────────────────────────────────────
# Le prédicat : la hauteur sépare
# ─────────────────────────────────────────────────────────────────────────────

def _duel(attacker_height: float) -> Dict[str, Any]:
    """Attaquant « 1 » en (20,20), défenseur « 2 » en (21,20) — adjacents à l'horizontale."""
    positions: Dict[str, Tuple[int, int]] = {"1": (20, 20), "2": (21, 20)}
    return {
        "unit_player": {"1": 1, "2": 2},
        "unit_positions": positions,
        "unit_hp": {"1": 3, "2": 3},
        "positions_by_model": {"1": {"1#0": (20, 20)}, "2": {"2#0": (21, 20)}},
        "heights_by_model": {"1": {"1#0": attacker_height}, "2": {"2#0": 0.0}},
        "unit_model_height": {"1": MODEL_HEIGHT, "2": MODEL_HEIGHT},
    }


def _engaged(duel: Dict[str, Any], **over: Any) -> bool:
    kwargs = dict(duel)
    kwargs.update(over)
    return an.is_within_engine_engagement_zone(
        "1",
        kwargs["unit_player"],
        kwargs["unit_positions"],
        kwargs["unit_hp"],
        engagement_zone=ENGAGEMENT_ZONE,
        positions_by_model=kwargs.get("positions_by_model"),
        heights_by_model=kwargs.get("heights_by_model"),
        unit_model_height=kwargs.get("unit_model_height"),
    )


def test_two_units_on_the_ground_are_engaged():
    """Contre-épreuve : le gate vertical ne doit pas tout refuser. Au sol des deux côtés, une
    seule classe verticale → le verdict est EXACTEMENT celui du 2D."""
    assert _engaged(_duel(attacker_height=0.0)) is True


def test_a_unit_two_floors_above_an_enemy_is_not_engaged_with_it():
    """§03.04 : intervalles verticaux [plancher, plancher+MODEL_HEIGHT] séparés de 7,5" > 5"."""
    assert _engaged(_duel(attacker_height=FLOOR_HEIGHT)) is False


def test_a_unit_on_a_low_floor_is_still_engaged():
    """Le gate est un SEUIL, pas un « même étage » : 3" de plancher → séparation 0,5" ≤ 5"."""
    assert _engaged(_duel(attacker_height=3.0)) is True


def test_a_squad_straddling_two_floors_is_engaged_by_its_lower_models():
    """Une escouade à cheval : c'est le socle le plus bas qui la met au contact."""
    duel = _duel(attacker_height=0.0)
    duel["positions_by_model"] = {"1": {"1#0": (20, 20), "1#1": (20, 20)}, "2": {"2#0": (21, 20)}}
    duel["heights_by_model"] = {"1": {"1#0": FLOOR_HEIGHT, "1#1": 0.0}, "2": {"2#0": 0.0}}
    assert _engaged(duel) is True


# ─────────────────────────────────────────────────────────────────────────────
# Dégradation : pas de donnée verticale → 2D, jamais une exception ni une altitude supposée
# ─────────────────────────────────────────────────────────────────────────────

def test_without_vertical_data_the_check_stays_2d_instead_of_raising():
    """La primitive moteur LÈVE sur une entrée sans données verticales. L'analyzer ne doit ni
    propager ce crash sur un vieux journal, ni supposer « au sol » — il reste horizontal."""
    duel = _duel(attacker_height=FLOOR_HEIGHT)
    assert an.is_within_engine_engagement_zone(
        "1", duel["unit_player"], duel["unit_positions"], duel["unit_hp"],
        engagement_zone=ENGAGEMENT_ZONE,
        positions_by_model=duel["positions_by_model"],
    ) is True, "sans altitude, le verdict doit rester le verdict horizontal"


def test_a_single_unit_missing_its_height_disables_the_gate_for_that_pair():
    """Tout ou rien PAR PAIRE : un gate vertical partiel comparerait une unité réelle à une
    altitude supposée. Ici l'ennemi n'a pas d'altitude connue → verdict horizontal (engagés),
    alors même que l'attaquant, lui, est bien à 10" du sol."""
    duel = _duel(attacker_height=FLOOR_HEIGHT)
    duel["heights_by_model"] = {"1": {"1#0": FLOOR_HEIGHT}}  # « 2 » absente
    assert _engaged(duel) is True


def test_the_gate_needs_the_unit_model_height_too():
    """`MODEL_HEIGHT` est la borne HAUTE de l'intervalle : sans elle le socle n'a pas d'épaisseur
    et `_vertical_classes` lèverait. Son absence désarme donc le gate au même titre qu'une
    hauteur de plancher manquante — même contrat « tout ou rien »."""
    duel = _duel(attacker_height=FLOOR_HEIGHT)
    duel["unit_model_height"] = {"1": MODEL_HEIGHT}  # « 2 » absente
    assert _engaged(duel) is True


# ─────────────────────────────────────────────────────────────────────────────
# Les deux fronts d'altitude ne se mélangent pas
# ─────────────────────────────────────────────────────────────────────────────

def test_the_start_heights_are_the_default_and_the_arrival_heights_are_explicit():
    """Les altitudes suivent le MÊME décalage d'une ligne que les positions.

    Plusieurs contrôles mesurent l'engagement aux socles d'AVANT le mouvement ; d'autres à ceux
    d'ARRIVÉE (`current_line_*`). Servir aux premiers l'altitude d'APRÈS inverse le gate : une
    unité qui DESCEND d'une ruine serait évaluée à son ancre de ruine avec sa hauteur de sol,
    donc déclarée engagée avec un ennemi qu'elle surplombait. D'où le défaut (front de DÉPART) et
    le paramètre explicite `subject_heights` (front d'ARRIVÉE).

    Ici l'attaquant DESCEND : à 10" il n'est pas engagé, au sol il l'est. Le même appel doit
    donc rendre deux verdicts opposés selon le front servi — c'est ce qui prouve que les deux ne
    sont pas confondus.
    """
    duel = _duel(attacker_height=FLOOR_HEIGHT)   # front de DÉPART : sur la ruine

    assert _engaged(duel) is False, "front de départ : l'attaquant surplombe, aucun engagement"
    assert an.is_within_engine_engagement_zone(
        "1", duel["unit_player"], duel["unit_positions"], duel["unit_hp"],
        engagement_zone=ENGAGEMENT_ZONE,
        positions_by_model=duel["positions_by_model"],
        heights_by_model=duel["heights_by_model"],
        unit_model_height=duel["unit_model_height"],
        subject_heights={"1#0": 0.0},            # front d'ARRIVÉE : descendu au sol
    ) is True, "front d'arrivée : l'attaquant est redescendu, il engage"
