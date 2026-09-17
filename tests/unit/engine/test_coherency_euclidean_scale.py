"""03.03 en mode euclidien (x5) — les seuils 2" / 9" sont à l'ÉCHELLE DU MOVE.

`_coherency_flags_euclidean` mesure bord à bord dans les unités de rendu de `_hex_center`
(1 sous-hexe = `ENGAGEMENT_NORM_HEX_WIDTH` = 1,5 en abscisse), comme le budget de move
(`budget × 1,5`), la zone d'engagement (`engagement_minimum_clearance_norm`) et les rayons de
socle. Les seuils, eux, étaient convertis en `× √3` (1,732) : 2" et 9" toléraient ~15 % de plus
que le move n'en compte. Mesuré sur la checklist PvP x5 : une ligne de 10 Hormagaunts sur 9"
dont le dernier socle est poussé de 2" (écart 11" centre à centre, ~10" socle à socle) restait
`coherency_ok`, et il fallait 3" de poussée pour un refus.

Scène : deux figurines sur la MÊME ligne (la mesure horizontale est exactement `Δcol × 1,5`),
socles de 5 cases (25 mm à x5, rayon 3,75 unités chacun), seuils 10 et 45 sous-hexes.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from engine.hex_utils import ENGAGEMENT_NORM_HEX_WIDTH
from engine.phase_handlers.shared_utils import coherency_violation_flags

_INCHES_TO_SUBHEX = 5
_BASE = 5  # cases de diamètre → rayon 3,75 unités de rendu, 7,5 pour la paire


def _gs() -> Dict[str, Any]:
    return {
        "config": {
            "game_rules": {
                "unit_model_cohesion_range": 2 * _INCHES_TO_SUBHEX,
                "unit_global_cohesion_range": 9 * _INCHES_TO_SUBHEX,
                "cohesion_distance_mode": "euclidean",
                "squad_min_neighbors": 1,
            }
        },
        "inches_to_subhex": _INCHES_TO_SUBHEX,
    }


def _row(cols: List[int]) -> List[Dict[str, Any]]:
    return [{"col": c, "row": 10, "BASE_SIZE": _BASE, "BASE_SHAPE": "round"} for c in cols]


def _edge_to_edge_norm(delta_cols: int) -> float:
    return delta_cols * ENGAGEMENT_NORM_HEX_WIDTH - 2 * (_BASE * 1.5 / 2.0)


@pytest.mark.parametrize(
    "last_col, violated",
    [
        # 2e puce, 9" = 45 sous-hexes = 67,5 unités bord à bord. Colonnes PAIRES : une colonne
        # impaire décale la ligne d'une demi-hauteur et la mesure n'est plus `Δcol × 1,5`.
        (50, False),  # 75 − 7,5 = 67,5 : exactement 9", cohérente
        (52, True),   # 78 − 7,5 = 70,5 > 67,5 : refusée — tolérée jusqu'à 77,9 à l'échelle √3
    ],
)
def test_l_ecart_maximal_de_9_pouces_est_mesure_a_l_echelle_du_move(last_col: int, violated: bool):
    edge = _edge_to_edge_norm(last_col)
    assert (edge > 45 * ENGAGEMENT_NORM_HEX_WIDTH) is violated, edge
    # Chaîne de 6 figurines à 10 colonnes (7,5 unités bord à bord : voisines) : la 1re puce est
    # vraie pour tout le monde, seule la 2e (« every other model ») peut sonner, sur la paire
    # extrême uniquement.
    models = _row([0, 10, 20, 30, 40, last_col])
    flags = coherency_violation_flags(models, _gs())
    assert flags == [violated, False, False, False, False, violated], flags


@pytest.mark.parametrize(
    "delta_cols, violated",
    [
        # 1re puce, 2" = 10 sous-hexes = 15 unités bord à bord (colonnes paires, cf. ci-dessus).
        (14, False),  # 21 − 7,5 = 13,5 : voisines
        (16, True),   # 24 − 7,5 = 16,5 > 15 : isolées — tolérées jusqu'à 17,3 à l'échelle √3
    ],
)
def test_le_voisinage_de_2_pouces_est_mesure_a_l_echelle_du_move(delta_cols: int, violated: bool):
    models = _row([0, delta_cols])
    flags = coherency_violation_flags(models, _gs())
    assert flags == [violated, violated], flags
