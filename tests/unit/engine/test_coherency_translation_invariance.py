"""Coherency 03.03 — le verdict ne dépend QUE de la formation, jamais de sa position.

Deux fonctions du moteur reposent sur cette propriété **par écrit**, sans qu'aucun test ne la
mesurait :
  - ``erode_move_pool_by_squad_block`` : « require_coherency reste INVARIANT par translation
    rigide (positions RELATIVES préservées) → déjà garanti par le pool d'ancre » — c'est pour ça
    que l'érosion ne filtre PAS la coherency ;
  - ``explain_move_plan_rejection`` : « si le plan est incohérent, la formation ACTUELLE l'est
    déjà ».

Elle était FAUSSE en mode euclidien : le « cercle d'étalement » est centré sur le milieu de la
paire de figurines la plus éloignée, et sur grille hex plusieurs paires sont souvent à distance
maximale EXACTEMENT égale (d² entier identique). Le départage se faisait sur les flottants, dont
les derniers bits changent quand la formation est translatée → le centre sautait sur l'autre paire
et une figurine passait « dans » à « hors » du cercle. Conséquence mesurée : le masque de move
offrait une destination que ``validate_move_plan`` refusait, et le training mourait sur
``execute_squad_move a échoué … coherency du plan invalide (formation actuelle coherente)``.

La formation ci-dessous est celle du crash (escouade de 11 figurines, board x1).
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

import pytest

from engine.phase_handlers.shared_utils import coherency_violation_flags

# Formation relevée dans le crash (squad 101, 11 figurines vivantes après pertes).
CRASH_FORMATION: List[Tuple[int, int]] = [
    (18, 40), (17, 39), (19, 39), (19, 37), (17, 36), (16, 38),
    (16, 42), (17, 40), (22, 40), (21, 38), (23, 40),
]

# Translations CUBE (delta_col pair → parité de colonne préservée, donc translation rigide du
# réseau hex ; c'est ce que produit `build_rigid_plan`).
TRANSLATIONS: List[Tuple[int, int]] = [(8, 1), (2, 0), (0, 3), (-4, -2), (12, 5), (6, -3)]


def _game_state(mode: str, inches_to_subhex: int) -> Dict[str, Any]:
    return {
        "inches_to_subhex": inches_to_subhex,
        "config": {
            "game_rules": {
                # Valeurs réelles de config/game_config.json, pré-scalées comme le fait w40k_core.
                "unit_model_cohesion_range": 2 * inches_to_subhex,
                "unit_global_cohesion_range": 9 * inches_to_subhex,
                "squad_min_neighbors": 1,
                "cohesion_distance_mode": mode,
                "engagement_zone": 2 * inches_to_subhex,
            }
        },
        "board_cols": 60,
        "board_rows": 60,
    }


def _models(positions: List[Tuple[int, int]], base_size: int) -> List[Dict[str, Any]]:
    return [
        {"col": c, "row": r, "BASE_SHAPE": "round", "BASE_SIZE": base_size, "orientation": 0}
        for c, r in positions
    ]


@pytest.mark.parametrize("d_col,d_row", TRANSLATIONS)
def test_x1_coherency_is_translation_invariant(d_col: int, d_row: int) -> None:
    """x1, mode de la config (euclidien) : le verdict doit rester celui de la FORMATION.

    C'est le cas exact du crash. La bascule du mode a x1 vers 'footprint' (centre d'hex) est un
    arbitrage ouvert — cf. `coherency_violation_flags` — donc l'invariance doit tenir dans le mode
    reellement utilise aujourd'hui.
    """
    gs = _game_state("euclidean", 1)
    here = coherency_violation_flags(_models(CRASH_FORMATION, 1), gs)
    there = coherency_violation_flags(
        _models([(c + d_col, r + d_row) for c, r in CRASH_FORMATION], 1), gs
    )
    assert here == there, (
        f"verdict de coherency modifié par une translation de ({d_col},{d_row}) : "
        f"{here} -> {there}"
    )


@pytest.mark.parametrize("d_col,d_row", TRANSLATIONS)
def test_euclidean_mode_is_translation_invariant(d_col: int, d_row: int) -> None:
    """Mode euclidien (bord d'empreinte, x5+) : le cercle d'étalement doit rester déterminé par la
    FORMATION seule — d'où le choix de la paire-diamètre en arithmétique ENTIÈRE exacte.

    On appelle ici la fonction de mode DIRECTEMENT, avec les nombres exacts du crash (2"/9",
    socles mono-cellule) : c'est cette formation qui porte l'égalité parfaite entre deux paires
    (figs (16,38)-(23,40) et (17,36)-(23,40), d² = 129 toutes deux) que le flottant départageait
    au hasard des bits. Passer par `coherency_violation_flags` à x5 route vers le même code mais
    en re-scalant les seuils, ce qui écarterait les figurines du bord du cercle et ne mesurerait
    plus rien.
    """
    from engine.phase_handlers.shared_utils import _coherency_flags_euclidean

    here = _coherency_flags_euclidean(_models(CRASH_FORMATION, 1), 2, 9, 1)
    there = _coherency_flags_euclidean(
        _models([(c + d_col, r + d_row) for c, r in CRASH_FORMATION], 1), 2, 9, 1
    )
    assert here == there, (
        f"verdict de coherency modifié par une translation de ({d_col},{d_row}) : "
        f"{here} -> {there}"
    )


def test_x1_crash_formation_is_coherent_everywhere() -> None:
    """La formation du crash est cohérente : c'est bien l'invariance qui manquait, pas la
    formation qui était fautive (le message d'erreur du moteur disait déjà « formation actuelle
    coherente »)."""
    gs = _game_state("euclidean", 1)
    for d_col, d_row in TRANSLATIONS:
        flags = coherency_violation_flags(
            _models([(c + d_col, r + d_row) for c, r in CRASH_FORMATION], 1), gs
        )
        assert not any(flags), f"translation ({d_col},{d_row}) : {flags}"
