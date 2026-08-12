"""Pile-in AUTO (PvE/gym) : « each model that started engaged must still be engaged » (12.03).

LE DÉFAUT. `pile_in_move_destinations_12_03` — le pool d'ancres du pile-in automatique — vérifiait
la clause AFTER de 12.03 au niveau UNITÉ : il suffisait qu'une figurine QUELCONQUE de l'escouade
tienne encore l'engagement avec l'unité ennemie pour que l'ancre soit acceptée. La règle l'écrit
par figurine (« each model … must still be engaged with **that** enemy unit »), et le flux
par-figurine du PvP (`_fight_pile_in_preview_plan`) l'appliquait déjà ainsi. Les deux flux
rendaient donc deux verdicts différents sur la même situation.

LA SITUATION QUI DISCRIMINE. Le pool translate le bloc RIGIDEMENT. On place donc l'ennemi ENTRE les
deux figurines : en glissant le bloc, la figurine qui tenait l'engagement s'en éloigne pendant que
l'autre s'en rapproche. Au niveau unité, « l'escouade reste engagée avec l'ennemi » — mais la
figurine qui était engagée ne l'est plus, ce que 12.03 interdit.

Règles : Documentation/40k_rules/12 Fights phase (12.03 AFTER MOVING), /03 Moving (03.04).
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from engine.phase_handlers import fight_handlers as fh
from engine.phase_handlers.shared_utils import get_engagement_zone
from engine.spatial_relations import unit_entries_within_engagement_zone
from tests.unit.engine._state_builders import synthetic_state, synthetic_unit

ENGAGEMENT_ZONE = 2  # 2" (03.04) à x1 : 1 sous-hex = 1"
MODEL_HEIGHT = 2.5

#: Cible du pile-in. La figurine de TÊTE s'en rapproche : l'ancre est donc légale au regard du
#: WHILE (« end closer »), ce qui isole la clause AFTER comme seule cause possible de refus.
CIBLE = (10, 10)
TETE = (12, 10)          # à 2 de CIBLE (engagée), se rapproche à chaque glissement vers l'ouest
#: SECOND ennemi. Le glissement qui rapproche la tête de la CIBLE éloigne la figurine qui tenait
#: CET ennemi et rapproche une troisième : c'est ce qui sépare « l'unité reste engagée avec lui »
#: de « LA figurine qui le tenait reste engagée », sous une translation RIGIDE.
AUTRE_ENNEMI = (20, 12)
TENANTE = (19, 10)       # à 2 d'AUTRE_ENNEMI (engagée)
REPRENEUSE = (23, 10)    # hors zone au départ ; c'est elle qui « reprend » l'engagement
#: Glissement COURT : la tenante garde son ennemi → l'ancre doit rester proposée.
ANCRE_LEGALE = (11, 10)
#: Glissement LONG : la tenante perd son ennemi, la repreneuse le reprend → 12.03 AFTER l'interdit,
#: alors qu'au niveau unité « l'escouade est toujours engagée avec lui ».
ANCRE_CANDIDATE = (9, 10)


@pytest.fixture
def gs() -> Dict[str, Any]:
    """L'escouade ``S`` (tête + tenante + repreneuse), la CIBLE ``E`` et le second ennemi ``F``."""
    return synthetic_state(
        [
            synthetic_unit("S", 1, [
                {"col": TETE[0], "row": TETE[1]},
                {"col": TENANTE[0], "row": TENANTE[1]},
                {"col": REPRENEUSE[0], "row": REPRENEUSE[1]},
            ]),
            synthetic_unit("E", 2, [{"col": CIBLE[0], "row": CIBLE[1]}]),
            synthetic_unit("F", 2, [{"col": AUTRE_ENNEMI[0], "row": AUTRE_ENNEMI[1]}]),
        ],
        game_rules={"engagement_zone": ENGAGEMENT_ZONE},
        phase="fight",
    )


def _engagements_de_depart(state: Dict[str, Any]) -> Dict[str, List[str]]:
    """{model_id: [ids des unités ennemies avec lesquelles elle est engagée]} — lisible en message."""
    par_fig = fh._fight_model_start_engagements(state, state["unit_by_id"]["S"])
    return {mid: [eid for eid, _ce in entries] for mid, entries in par_fig.items()}


def test_la_premisse_tient_une_seule_figurine_est_engagee_au_depart(gs):
    """Sans cette prémisse, le test principal ne mesurerait rien : il faut UNE tenante, pas deux."""
    par_fig = _engagements_de_depart(gs)

    assert par_fig == {"S#0": ["E"], "S#1": ["F"]}, (
        f"engagements de départ par figurine : {par_fig} ; attendu la tête (S#0, en {TETE}) "
        f"engagée avec la CIBLE et la tenante (S#1, en {TENANTE}) avec le second ennemi. "
        f"S#2 (en {REPRENEUSE}) doit être hors zone au départ — c'est elle qui reprendra "
        "l'engagement après le glissement"
    )


def test_l_ancre_reste_engagee_au_niveau_unite_mais_change_de_figurine(gs):
    """Prémisse n°2 : à l'ancre candidate, l'ANCIEN contrôle d'unité passe.

    C'est ce qui rend le test principal discriminant — l'ancre n'est pas rejetée pour une autre
    raison (unité désengagée, pas assez proche), mais bien par la clause par figurine.
    """
    ez = int(get_engagement_zone(gs))
    ennemi = gs["units_cache"]["F"]  # celui dont l'engagement CHANGE de porteuse
    placements = fh._fight_rigid_model_placements(gs, "S", *ANCRE_CANDIDATE)
    synths = fh._fight_synth_cache_entries_at_footprint(
        gs["unit_by_id"]["S"], gs, *ANCRE_CANDIDATE, model_placements=placements
    )

    assert any(unit_entries_within_engagement_zone(s, ennemi, ez) for s in synths), (
        "à l'ancre candidate, l'escouade n'est plus engagée du tout : le contrôle de niveau unité "
        "rejetterait déjà l'ancre, et le test principal serait vert sans rien prouver"
    )
    assert not fh._fight_models_keep_start_engagements(
        gs, "S", fh._fight_model_start_engagements(gs, gs["unit_by_id"]["S"]), placements, ez
    ), (
        "la figurine qui tenait l'engagement le tient encore : la mise en scène ne discrimine pas "
        "les deux lectures de 12.03"
    )


def test_le_pool_auto_refuse_l_ancre_qui_perd_l_engagement_d_une_figurine(gs):
    """VERROU : au niveau unité, cette ancre passe ; par figurine, 12.03 l'interdit."""
    destinations = fh.pile_in_move_destinations_12_03(gs, gs["unit_by_id"]["S"], ["E"])

    assert ANCRE_CANDIDATE not in destinations, (
        f"l'ancre {ANCRE_CANDIDATE} est proposée : la figurine S#1, engagée avec F au départ, y "
        f"perd son engagement (c'est S#2 qui le reprend, et l'unité reste donc « engagée avec F » "
        f"au niveau escouade). 12.03 AFTER l'interdit. Pool rendu : {sorted(destinations)}"
    )


def test_le_pool_auto_garde_l_ancre_qui_conserve_tous_les_engagements(gs):
    """Contre-épreuve : un pool VIDE ferait passer le verrou ci-dessus sans rien vérifier.

    Le glissement COURT rapproche la tête de la cible sans faire sortir la tenante de la zone de
    son ennemi : aucune clause de 12.03 ne s'y oppose, il doit rester proposé.
    """
    destinations = fh.pile_in_move_destinations_12_03(gs, gs["unit_by_id"]["S"], ["E"])

    assert ANCRE_LEGALE in destinations, (
        f"l'ancre {ANCRE_LEGALE} conserve TOUS les engagements de départ et rapproche l'escouade : "
        f"la refuser vide le pool et rend le verrou précédent vacant. Pool rendu : "
        f"{sorted(destinations)}"
    )
