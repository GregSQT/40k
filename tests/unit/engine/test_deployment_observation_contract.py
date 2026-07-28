"""V11 §0.40 points 1 & 2 — l'observation de la phase de déploiement.

Deux défauts vérifiés dans le code le 2026-07-28, corrigés ici :

**Point 1 — l'obs décrivait une AUTRE unité que celle sur laquelle le masque agit.**
`_build_observation` prenait `next(iter(units_cache.keys()))` : la 1re clé du cache d'unités,
tous joueurs confondus et unités déjà posées comprises. Le masque, lui, ouvre les slots 4-8 pour
`deployment_state["deployable_units"][current_deployer][0]`. Rien ne garantissait que les deux
désignent la même unité — l'agent décrivait A et posait B (même motif que le désalignement
obs ↔ action des slots ennemis, D1).

**Point 2 — la grille égocentrique était centrée hors plateau.**
Une unité pas encore posée porte `deployed_on_turn is None` / `col < 0` : `build_squad_grid`
centrait la fenêtre sur (-1,-1), donc TOUS les canaux (murs, alliés, ennemis, objectifs, couvert)
étaient vides ou tronqués à l'instant précis où l'agent choisit son point d'entrée dans la
partie. La grille est désormais ancrée sur la ZONE DE DÉPLOIEMENT du joueur — la même collection
d'hexes que celle où le décodeur choisit l'hexe, aucune géométrie recalculée.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCENARIO = (
    PROJECT_ROOT
    / "config" / "agents" / "ArmageddonAgent" / "scenarios" / "training"
    / "scenario_training_armageddon.json"
)


def _load(seed: int = 0):
    from ai.unit_registry import UnitRegistry
    from engine.w40k_core import W40KEngine

    eng = W40KEngine(
        rewards_config="ArmageddonAgent", training_config_name="x1_debug",
        controlled_agent="ArmageddonAgent", scenario_file=str(SCENARIO),
        unit_registry=UnitRegistry(), quiet=True, gym_training_mode=True,
    )
    eng.reset(seed=seed)
    assert eng.game_state.get("phase") == "deployment", (
        "le scénario doit démarrer en déploiement actif — sinon ce fichier ne teste rien"
    )
    return eng


def _first_deploy_action(mask) -> int:
    actions = [a for a in range(4, 9) if mask[a]]
    assert actions, "aucune action de déploiement dans le masque"
    return actions[0]


# ============================================================================
# POINT 1 — contrat obs ↔ masque
# ============================================================================


def test_deployment_observation_describes_the_unit_the_mask_acts_on():
    """À CHAQUE état de déploiement, l'unité décrite par l'obs == celle du masque.

    Le contrat est vérifié en espionnant l'argument `squad_id` que `_build_observation` passe au
    constructeur d'observation : c'est littéralement l'unité décrite, pas une reconstruction.
    """
    eng = _load()
    gs = eng.game_state
    dec = eng.action_decoder

    described: list[str] = []
    original = eng.obs_builder.build_squad_observation

    def _spy(game_state, squad_id):
        described.append(str(squad_id))
        return original(game_state, squad_id)

    eng.obs_builder.build_squad_observation = _spy

    checked = 0
    steps = 0
    while gs.get("phase") == "deployment" and steps < 1000:
        mask, eligible = dec.get_squad_action_mask_and_eligible_units(gs)
        assert eligible, "pool de déploiement vide alors que la phase est 'deployment'"
        masked_unit_id = str(eligible[0]["id"])

        described.clear()
        eng._build_observation()
        assert described == [masked_unit_id], (
            f"step {steps} : l'observation décrit {described} alors que le masque agit sur "
            f"{masked_unit_id} — désalignement obs ↔ action (§0.40 point 1)"
        )

        # L'unité décrite doit appartenir au joueur qui déploie ET ne pas être déjà posée.
        entry = gs["units_cache"][masked_unit_id]
        assert int(entry["player"]) == dec._get_current_deployer(gs), (
            f"step {steps} : l'obs décrit une unité du joueur {entry['player']} alors que "
            f"{dec._get_current_deployer(gs)} déploie"
        )
        unit = next(u for u in gs["units"] if str(u["id"]) == masked_unit_id)
        assert unit["deployed_on_turn"] is None, (
            f"step {steps} : l'obs décrit une unité DÉJÀ posée pendant le déploiement"
        )
        checked += 1

        eng.step(_first_deploy_action(mask))
        steps += 1

    assert gs.get("phase") != "deployment", "déploiement non terminé (deadlock)"
    # Les deux joueurs doivent avoir déployé : c'est le passage au joueur 2 qui distingue la
    # source du masque de la 1re clé de `units_cache` (qui reste une unité du joueur 1).
    assert checked >= 4, f"trop peu d'états de déploiement observés ({checked})"


def test_deployment_active_unit_raises_on_empty_pool():
    """Pool vide en phase de déploiement = état incohérent → erreur explicite, pas d'obs nulle.

    Une obs de zéros décrirait un plateau vide à un agent à qui l'on demande quand même d'agir,
    et le masque correspondant serait tout-faux (injouable). L'erreur est le seul signal correct.
    """
    eng = _load()
    gs = eng.game_state
    deployer = eng.action_decoder._get_current_deployer(gs)
    gs["deployment_state"]["deployable_units"][deployer] = []

    with pytest.raises(ValueError, match="aucune unité déployable"):
        eng.action_decoder.get_deployment_active_unit(gs)


# ============================================================================
# POINT 2 — ancre de la grille égocentrique
# ============================================================================


def test_deployment_grid_shows_the_terrain_where_the_unit_will_be_placed():
    """Pendant le déploiement, la grille est ancrée SUR le plateau, dans la zone du joueur, et
    la fenêtre CONTIENT les hexes que les 5 stratégies de déploiement peuvent choisir.

    Avant le correctif l'ancre valait (-1,-1) (marqueur « pas sur le board ») : la fenêtre
    tombait sur le coin (0,0) du plateau, à ~250 lignes de la zone de déploiement du joueur 1.
    Elle contenait donc bien « du terrain » — mais celui d'une autre région : l'agent choisissait
    son point d'entrée en regardant ailleurs. Le verrou porte donc sur les hexes RÉELLEMENT
    atteignables par les slots 4-8, pas sur la simple non-vacuité des canaux.
    """
    from engine.spatial_grid import (
        GRID_CH_OBJECTIVE,
        GRID_CH_WALL,
        hex_arrays_to_cells,
        grid_half_extent_subhex,
    )

    eng = _load()
    gs = eng.game_state
    dec = eng.action_decoder

    checked = 0
    steps = 0
    while gs.get("phase") == "deployment" and steps < 1000:
        mask, eligible = dec.get_squad_action_mask_and_eligible_units(gs)
        uid = str(eligible[0]["id"])
        entry = gs["units_cache"][uid]
        assert int(entry["col"]) < 0, "l'unité à déployer doit être hors plateau (col < 0)"

        anchor_col, anchor_row = eng.obs_builder.squad_grid_anchor(gs, uid)
        assert 0 <= anchor_col < int(gs["board_cols"]), f"ancre hors plateau : col={anchor_col}"
        assert 0 <= anchor_row < int(gs["board_rows"]), f"ancre hors plateau : row={anchor_row}"

        # L'ancre doit être DANS la zone de déploiement du joueur (une zone concave a un
        # barycentre potentiellement hors zone — on ancre sur l'hex du pool le plus proche).
        player = int(entry["player"])
        pools = gs["deployment_state"]["deployment_pools"]
        pool = pools.get(player, pools.get(str(player)))
        pool_set = {(int(h[0]), int(h[1])) for h in pool}
        assert (anchor_col, anchor_row) in pool_set, (
            f"ancre ({anchor_col},{anchor_row}) hors de la zone de déploiement du joueur {player}"
        )

        # La fenêtre doit couvrir la ZONE où l'unité va être posée, pas une autre région du
        # plateau. Mesuré sur ce scénario : 96 % du pool du joueur 1 et 78 % de celui du joueur 2
        # tombent dans la fenêtre avec l'ancre corrigée, contre 0 % et 25 % avec l'ancre (-1,-1).
        # Le seuil est à 50 % : la géométrie de la grille est FIXE (demi-étendue = budget Advance,
        # `engine.spatial_grid`, source unique partagée avec le masque) et la zone de déploiement
        # est plus large qu'elle — les hexes de flanc extrêmes restent hors champ, c'est une
        # limite assumée de la géométrie, pas de l'ancrage.
        _gx, _gy, in_window = hex_arrays_to_cells(
            np.array([c for c, _ in pool_set], dtype=np.int64),
            np.array([r for _, r in pool_set], dtype=np.int64),
            anchor_col, anchor_row,
            grid_half_extent_subhex(gs, uid),
        )
        visible_ratio = float(in_window.mean())
        assert visible_ratio >= 0.5, (
            f"step {steps} : seuls {visible_ratio:.1%} des hexes de la zone de déploiement du "
            f"joueur {player} sont dans la fenêtre de la grille — l'agent choisit son point "
            f"d'entrée en regardant ailleurs (§0.40 point 2)"
        )

        # Et la grille RÉELLEMENT produite doit être rasterisée sur cette ancre-là : on
        # reconstruit le canal MURS attendu (peinture directe, sans dilatation) et on exige
        # l'égalité exacte. C'est ce qui verrouille le câblage dans `build_squad_grid`, pas
        # seulement la fonction d'ancrage.
        grid = eng.obs_builder.build_squad_grid(gs, uid)
        wall_cols = np.array([int(h[0]) for h in gs["wall_hexes"]], dtype=np.int64)
        wall_rows = np.array([int(h[1]) for h in gs["wall_hexes"]], dtype=np.int64)
        wgx, wgy, wvalid = hex_arrays_to_cells(
            wall_cols, wall_rows, anchor_col, anchor_row, grid_half_extent_subhex(gs, uid)
        )
        expected_walls = np.zeros_like(grid[GRID_CH_WALL])
        expected_walls[wgy[wvalid], wgx[wvalid]] = 1.0
        assert expected_walls.any(), "aucun mur visible depuis la zone — scénario inattendu"
        assert np.array_equal(grid[GRID_CH_WALL], expected_walls), (
            f"step {steps} : le canal MURS de la grille ne correspond pas à une rasterisation "
            f"depuis l'ancre ({anchor_col},{anchor_row}) — la grille est centrée ailleurs "
            f"(§0.40 point 2)"
        )
        assert grid[GRID_CH_OBJECTIVE].any(), (
            "canal OBJECTIFS vide pendant le déploiement — la grille ne voit pas les objectifs"
        )
        checked += 1

        eng.step(_first_deploy_action(mask))
        steps += 1

    assert checked >= 4, f"trop peu d'états de déploiement observés ({checked})"


def test_grid_anchor_unchanged_for_a_deployed_squad():
    """Hors déploiement, l'ancre reste EXACTEMENT celle de l'escouade — géométrie inchangée."""
    eng = _load()
    gs = eng.game_state
    dec = eng.action_decoder

    steps = 0
    while gs.get("phase") == "deployment" and steps < 1000:
        mask, _ = dec.get_squad_action_mask_and_eligible_units(gs)
        eng.step(_first_deploy_action(mask))
        steps += 1

    checked = 0
    for uid, entry in gs["units_cache"].items():
        assert eng.obs_builder.squad_grid_anchor(gs, uid) == (
            int(entry["col"]),
            int(entry["row"]),
        ), f"escouade posée {uid} : l'ancre de grille a été détournée"
        checked += 1
    assert checked > 0, "aucune escouade posée après le déploiement"


def test_deployment_grid_self_channel_is_empty_before_placement():
    """L'escouade pas encore posée n'a AUCUNE figurine sur le plateau : canal SELF vide.

    Verrou de cohérence : l'ancre déplacée ne doit pas faire croire à l'agent que l'unité est
    déjà quelque part.
    """
    from engine.spatial_grid import GRID_CH_SELF

    eng = _load()
    gs = eng.game_state
    uid = str(eng.action_decoder.get_deployment_active_unit(gs)["id"])
    grid = eng.obs_builder.build_squad_grid(gs, uid)
    assert not np.any(grid[GRID_CH_SELF]), (
        "canal SELF non vide pour une escouade pas encore déployée"
    )


def test_squad_obs_size_target_unchanged():
    """§0.40 point 3 (décrire les hexes candidats) est HORS périmètre : `obs_size` ne bouge pas."""
    from engine.observation_builder import ObservationBuilder

    assert ObservationBuilder.SQUAD_OBS_SIZE_TARGET == 20768
