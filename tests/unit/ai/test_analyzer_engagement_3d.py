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
  - elle reste 2D — et ne lève pas — quand la donnée verticale manque.
"""

from __future__ import annotations

from typing import Dict, Tuple

import pytest

import ai.analyzer as an
from ai.analyzer_perfig import parse_models_heights, parse_models_segment
from ai.analyzer_state import AnalyzerState


ENGAGEMENT_ZONE = 20     # 2" à inches_to_subhex=10, déjà scalé (contrat moteur)
VERTICAL_ZONE = 5.0      # 5" (§03.04), en POUCES — jamais scalé
MODEL_HEIGHT = 2.5
FLOOR_HEIGHT = 10.0      # 10" > 5" + 2,5" → hors zone verticale


# ─────────────────────────────────────────────────────────────────────────────
# Le journal : l'altitude voyage avec la position
# ─────────────────────────────────────────────────────────────────────────────

def test_the_models_segment_carries_a_floor_height_per_model():
    line = "Unit 1(20,20) FOUGHT [MODELS: 1#0@(20,20,z0) 1#1@(21,20,z10.5)] [SUCCESS]"

    assert parse_models_segment(line) == {"1": {"1#0": (20, 20), "1#1": (21, 20)}}, (
        "les positions doivent rester PLANES : la couche per-figurine est horizontale"
    )
    assert parse_models_heights(line) == {"1": {"1#0": 0.0, "1#1": 10.5}}


def test_a_segment_without_height_is_refused_rather_than_read_as_ground_level():
    """Un step.log antérieur à l'altitude ne doit pas se faire lire comme un plateau plat :
    ce serait un verdict d'engagement silencieusement 2D, exactement ce qu'on corrige."""
    with pytest.raises(ValueError, match=r"\[MODELS:\]"):
        parse_models_segment("Unit 1(20,20) FOUGHT [MODELS: 1#0@(20,20)] [SUCCESS]")


# ─────────────────────────────────────────────────────────────────────────────
# Le prédicat : la hauteur sépare
# ─────────────────────────────────────────────────────────────────────────────

def _duel(attacker_height: float) -> Dict[str, object]:
    """Attaquant « 1 » en (20,20), défenseur « 2 » au sol en (21,20) — adjacents à l'horizontale."""
    positions: Dict[str, Tuple[int, int]] = {"1": (20, 20), "2": (21, 20)}
    return {
        "unit_player": {"1": 1, "2": 2},
        "unit_positions": positions,
        "unit_hp": {"1": 3, "2": 3},
        "heights_by_model": {"1": {"1#0": attacker_height}, "2": {"2#0": 0.0}},
        "unit_model_height": {"1": MODEL_HEIGHT, "2": MODEL_HEIGHT},
    }


def _engaged(duel: Dict[str, object], **over) -> bool:
    kwargs = dict(duel)
    kwargs.update(over)
    return an.is_within_engine_engagement_zone(
        "1",
        kwargs["unit_player"],          # type: ignore[arg-type]
        kwargs["unit_positions"],       # type: ignore[arg-type]
        kwargs["unit_hp"],              # type: ignore[arg-type]
        engagement_zone=ENGAGEMENT_ZONE,
        heights_by_model=kwargs["heights_by_model"],        # type: ignore[arg-type]
        unit_model_height=kwargs["unit_model_height"],      # type: ignore[arg-type]
        vertical_zone_inches=VERTICAL_ZONE,
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
    """Une escouade à cheval : c'est le niveau le plus bas qui la met au contact."""
    duel = _duel(attacker_height=0.0)
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
        "1", duel["unit_player"], duel["unit_positions"], duel["unit_hp"],  # type: ignore[arg-type]
        engagement_zone=ENGAGEMENT_ZONE,
    ) is True, "sans altitude, le verdict doit rester le verdict horizontal"


def test_a_single_unit_missing_its_height_disables_the_gate_for_everyone():
    """Tout ou rien : un gate vertical partiel comparerait une unité réelle à une altitude
    supposée. Ici l'ennemi n'a pas d'altitude connue → verdict horizontal (engagés)."""
    duel = _duel(attacker_height=FLOOR_HEIGHT)
    duel["heights_by_model"] = {"1": {"1#0": FLOOR_HEIGHT}}  # « 2 » absente
    assert _engaged(duel) is True


def test_the_two_height_fronts_do_not_mix():
    """Les altitudes suivent le MÊME décalage d'une ligne que les positions.

    Plusieurs contrôles mesurent l'engagement à l'ancre d'AVANT le mouvement
    (``position_override=start_pos``). Leur servir l'altitude d'APRÈS inverse le gate vertical :
    une unité qui DESCEND d'une ruine serait évaluée à son ancre de ruine avec sa hauteur de sol,
    donc déclarée engagée avec un ennemi qu'elle surplombait. D'où deux fronts, et deux accesseurs.
    """
    state = AnalyzerState(stats={})
    state.unit_model_height = {"1": MODEL_HEIGHT}
    state.heights_by_model = {"1": {"1#0": FLOOR_HEIGHT}}      # avant la ligne : sur la ruine
    state.current_line_heights = {"1": {"1#0": 0.0}}            # après la ligne : descendue au sol

    assert state.engagement_3d_kwargs_at_start()["heights_by_model"] == {"1": {"1#0": FLOOR_HEIGHT}}
    assert state.engagement_3d_kwargs()["heights_by_model"] == {"1": {"1#0": 0.0}}


def test_a_unit_absent_from_the_current_line_keeps_its_height():
    """Le front courant ne remplace que les unités que la ligne mentionne."""
    state = AnalyzerState(stats={})
    state.heights_by_model = {"1": {"1#0": 0.0}, "2": {"2#0": FLOOR_HEIGHT}}
    state.current_line_heights = {"1": {"1#0": FLOOR_HEIGHT}}

    assert state.engagement_3d_kwargs()["heights_by_model"] == {
        "1": {"1#0": FLOOR_HEIGHT},
        "2": {"2#0": FLOOR_HEIGHT},
    }
