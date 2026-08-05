"""V11 §0.40 — l'observation de la phase de déploiement (points 1, 2, 4 et 5).

Quatre défauts vérifiés dans le code puis corrigés. Les points 4 et 5 ont été trouvés en
VÉRIFIANT les correctifs précédents, pas en relisant la spec : chacun est le même défaut racine
— des grandeurs géométriques calculées sur une unité qui n'est pas sur le plateau — vu une
couche plus loin.

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

**Point 4 — le VECTEUR mesurait aussi depuis la sentinelle.**
Son origine est le centroïde de l'escouade active, qui vaut (-1,-1) tant qu'elle n'est pas posée :
distances et directions aux objectifs, et positions relatives de toutes les entités, partaient du
coin hors plateau. L'ORDRE des objectifs en était inversé.

**Point 5 — une unité pas encore mise en place se déclarait engagée au contact.**
Toutes les unités non posées partagent la sentinelle, donc leurs empreintes se recouvrent et la
primitive d'engagement les déclarait mutuellement engagées. Contraire à la règle 03.04
(`Documentation/40k_rules/03 Moving.pdf`) : l'engagement range est une aire DU CHAMP DE BATAILLE.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import numpy as np
import pytest

from _config_helpers import assert_deployment_phase, pin_active_deployment

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
    # Déploiement ACTIF garanti. Lu par épisode → doit précéder le `reset`. Le scénario, la
    # graine et la géométrie sont inchangés : seul le tirage du MODE est forcé à la valeur que
    # ce fichier a toujours supposée. POURQUOI dans `_config_helpers.pin_active_deployment`.
    pin_active_deployment(eng)
    eng.reset(seed=seed)
    assert_deployment_phase(eng)  # sinon ce fichier ne teste rien
    return eng


def _first_deploy_action(mask) -> int:
    actions = [a for a in range(4, 9) if mask[a]]
    assert actions, "aucune action de déploiement dans le masque"
    return actions[0]


def _is_on_battlefield(gs, sid: str) -> bool:
    """Prédicat MOTEUR de « sur le champ de bataille » : ``deployed_on_turn is not None``.

    Même source que `ObservationBuilder` (`on_battlefield`) et que `entry_is_on_battlefield`.
    """
    unit = next(u for u in gs["units"] if str(u["id"]) == str(sid))
    return unit["deployed_on_turn"] is not None


def _obs_ally_rows(gs, active_squad_id: str, active_player: int, k_ally_slots: int = 8):
    """Les lignes ALLIÉES de l'obs, DANS L'ORDRE QUE L'OBS ÉCRIT.

    POURQUOI CE HELPER EXISTE. Trois tests de ce fichier reconstruisaient ces lignes depuis
    `units_cache` SANS le filtre « sur le champ de bataille » que l'obs applique
    (`friendly_sids`, observation_builder). Tant que les unités non posées se trouvaient trier
    APRÈS les posées, le préfixe coïncidait et les tests lisaient la bonne ligne — par chance.
    Une unité en RÉSERVES 20.01 reste hors table tout l'épisode : elle sort en tête du tri, tout
    le mapping se décale d'un cran, et les tests lisaient la ligne d'une AUTRE escouade. Mesuré
    le 2026-08-05 : liste du test ['1','2','4','5'] contre liste de l'obs ['2'] — le slot 1,
    attribué à l'unité 1 (hors table), portait en fait la position de l'unité 2 (posée, col=215),
    d'où un `col_rel = 90.0` attribué à une unité sans position.

    Une entité hors table N'A PAS de ligne alliée : l'information qu'elle existe passe par les
    slots ENNEMIS (eux non filtrés) et par le bit `deploy_not_on_board`.
    """
    others = sorted(
        (
            s
            for s, e in gs["units_cache"].items()
            if int(e["player"]) == active_player
            and s != active_squad_id
            and _is_on_battlefield(gs, s)
        ),
        key=str,
    )
    return [(0, str(active_squad_id))] + [
        (i + 1, str(s)) for i, s in enumerate(others[: k_ally_slots - 1])
    ]


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

    # Signature IDENTIQUE a celle de `build_squad_observation` (nom du 2e parametre compris) :
    # un espion qui renomme un parametre n'est plus substituable a la methode qu'il remplace, et
    # un appel par mot-cle passerait a cote sans que le test le voie.
    def _spy(game_state: Dict[str, Any], active_squad_id: str):
        described.append(str(active_squad_id))
        return original(game_state, active_squad_id)

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
        pools = gs["deployment_pools"]
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

    checked = off_table = 0
    for uid, entry in gs["units_cache"].items():
        # Une unité en RÉSERVES 20.01 est encore hors table à la fin du déploiement : son ancre
        # est celle de sa ZONE (§0.40 point 2), pas sa sentinelle. Ce test porte sur les
        # escouades POSÉES — c'est son titre. Le cas hors table est vérifié juste après.
        if not _is_on_battlefield(gs, uid):
            off_table += 1
            assert eng.obs_builder.squad_grid_anchor(gs, uid) != (-1, -1), (
                f"escouade {uid} hors table : la grille est centrée sur la sentinelle, donc hors "
                "plateau — l'agent n'y voit ni mur, ni objectif, ni ennemi"
            )
            continue
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


# ============================================================================
# POINT 4 — origine de mesure du VECTEUR
# ============================================================================


def test_objective_distances_are_measured_from_the_deployment_zone():
    """Les distances/directions aux objectifs partent de la zone, pas de la sentinelle.

    Mesuré avant correctif : l'agent voyait l'objectif 0 à 38,3 (le plus proche) alors qu'il est
    à 178,9 de sa zone, et ne voyait pas l'objectif 4 à 11,3 — l'ORDRE des objectifs était
    inversé. Les trois actions `zone_intent` s'appuient sur ces nombres.
    """
    import engine.observation_entities as oe

    eng = _load()
    gs = eng.game_state
    uid = str(eng.action_decoder.get_deployment_active_unit(gs)["id"])
    anchor = eng.obs_builder.squad_grid_anchor(gs, uid)

    obs = eng.obs_builder.build_squad_observation(gs, uid)
    seen = np.array(
        [obs["global_cont"][oe.global_cont_index(f"objective_distance_{i}")] for i in range(5)]
    )
    from_zone = np.array(
        eng.obs_builder._squad_objective_geometry(gs, float(anchor[0]), float(anchor[1]))[0]
    )
    from_sentinel = np.array(eng.obs_builder._squad_objective_geometry(gs, -1.0, -1.0)[0])

    assert np.allclose(seen, from_zone), (
        f"distances vues {np.round(seen, 1)} ≠ distances depuis la zone {np.round(from_zone, 1)}"
    )
    # Le scénario doit réellement distinguer les deux origines, sinon le test ne prouve rien.
    assert int(np.argmin(from_zone)) != int(np.argmin(from_sentinel)), (
        "sur ce scénario les deux origines désignent le même objectif le plus proche — "
        "le test ne discrimine pas"
    )


def test_relative_positions_are_measured_from_the_zone_and_null_for_unplaced_units():
    """`col_rel`/`row_rel` : mesurés depuis l'ancre de zone pour les entités POSÉES, exactement
    nuls pour celles qui ne le sont pas (leur bit `deploy_not_on_board` porte l'information).

    Sans la seconde moitié, déplacer l'origine empilerait toutes les unités non posées à une
    distance absurde au nord-ouest — elles sont toutes à la sentinelle (-1,-1).
    """
    import engine.observation_entities as oe
    from engine.hex_utils import _hex_center

    eng = _load()
    gs = eng.game_state
    dec = eng.action_decoder
    i_col, i_row = oe.unit_cont_index("col_rel"), oe.unit_cont_index("row_rel")

    # Avance jusqu'à ce que les DEUX camps aient des unités posées et d'autres non.
    for _ in range(6):
        mask, _ = dec.get_squad_action_mask_and_eligible_units(gs)
        eng.step(_first_deploy_action(mask))
    assert gs.get("phase") == "deployment", "déploiement terminé trop tôt pour ce test"

    uid = str(dec.get_deployment_active_unit(gs)["id"])
    anchor = eng.obs_builder.squad_grid_anchor(gs, uid)
    ax, ay = _hex_center(*anchor)
    obs = eng.obs_builder.build_squad_observation(gs, uid)

    active_player = int(gs["units_cache"][uid]["player"])
    from engine.phase_handlers.shared_utils import get_enemy_slot_mapping

    rows = [("allies_cont", slot, sid) for slot, sid in _obs_ally_rows(gs, uid, active_player)]
    # Les slots ennemis vides portent None : ils sont laissés à zéro par contrat (bit `present`),
    # ce n'est pas ce que ce test mesure.
    rows += [
        ("enemies_cont", i, str(s))
        for i, s in enumerate(get_enemy_slot_mapping(gs, active_player)[:20])
        if s is not None and str(s) in gs["units_cache"]
    ]

    checked_placed = checked_unplaced = 0
    for key, slot, sid in rows:
        unit = next(u for u in gs["units"] if str(u["id"]) == sid)
        got = (float(obs[key][slot][i_col]), float(obs[key][slot][i_row]))
        if unit["deployed_on_turn"] is None:
            assert got == (0.0, 0.0), (
                f"{sid} n'est pas posée mais porte une position relative {got}"
            )
            checked_unplaced += 1
        else:
            # La feature prend la figurine la PLUS PROCHE de l'origine (V11 §9.2).
            best = min(
                (_hex_center(int(m["col"]), int(m["row"])) for m in
                 (gs["models_cache"][mid] for mid in gs["squad_models"][sid])),
                key=lambda p: (p[0] - ax) ** 2 + (p[1] - ay) ** 2,
            )
            expected = (best[0] - ax, best[1] - ay)
            assert np.allclose(got, expected), (
                f"{sid} : position relative {got}, attendu {expected} depuis l'ancre {anchor}"
            )
            checked_placed += 1

    assert checked_placed >= 3, f"trop peu d'entités posées vérifiées ({checked_placed})"
    assert checked_unplaced >= 3, f"trop peu d'entités non posées vérifiées ({checked_unplaced})"


def test_self_models_have_no_position_before_placement():
    """Les figurines de l'escouade non posée ne sont nulle part : positions relatives nulles."""
    eng = _load()
    gs = eng.game_state
    uid = str(eng.action_decoder.get_deployment_active_unit(gs)["id"])
    obs = eng.obs_builder.build_squad_observation(gs, uid)
    assert not np.any(obs["self_models_cont"]), (
        "l'escouade pas encore posée porte des positions de figurines non nulles"
    )


def test_measurement_origin_is_the_centroid_once_deployed():
    """Non-régression : une fois le déploiement fini, l'origine redevient le CENTROÏDE.

    Le correctif du point 4 ne doit toucher que les escouades non posées. « Hors déploiement,
    aucune unité vivante n'en est là » N'EST PLUS VRAI : une unité en réserves 20.01 reste hors
    table jusqu'à son ingress 20.04, et son centroïde est la sentinelle. Le test prend donc une
    escouade RÉELLEMENT posée — c'est le cas qu'il annonce mesurer.
    """
    import engine.observation_entities as oe

    eng = _load()
    gs = eng.game_state
    dec = eng.action_decoder
    steps = 0
    while gs.get("phase") == "deployment" and steps < 1000:
        mask, _ = dec.get_squad_action_mask_and_eligible_units(gs)
        eng.step(_first_deploy_action(mask))
        steps += 1

    uid = next(
        (sid for sid in gs["units_cache"] if _is_on_battlefield(gs, sid)),
        None,
    )
    assert uid is not None, "aucune escouade posée après le déploiement — test sans valeur"
    sq = gs["squad_cache"][uid]
    obs = eng.obs_builder.build_squad_observation(gs, uid)
    seen = np.array(
        [obs["global_cont"][oe.global_cont_index(f"objective_distance_{i}")] for i in range(5)]
    )
    from_centroid = np.array(
        eng.obs_builder._squad_objective_geometry(
            gs, float(sq["centroid_col"]), float(sq["centroid_row"])
        )[0]
    )
    assert np.allclose(seen, from_centroid), (
        "hors déploiement, l'origine de mesure n'est plus le centroïde de l'escouade"
    )


# ============================================================================
# POINT 5 — une unité pas encore mise en place n'est pas sur le champ de bataille
# ============================================================================

#: Features qui affirment une RELATION géométrique à l'ennemi ou au terrain. Règle 03.04
#: (`Documentation/40k_rules/03 Moving.pdf`) : « A model's engagement range is the area OF THE
#: BATTLEFIELD within 2" horizontally and 5" vertically of it ». Une unité pas encore mise en
#: place n'est pas sur le champ de bataille — aucune de ces affirmations ne peut être vraie pour
#: elle. `coherent` n'en fait PAS partie : 03.03 conditionne le test de cohérence à « if that
#: unit is on the battlefield », il ne déclare pas incohérente une unité hors table — et 0
#: signifierait « escouade éparpillée », une pathologie, donc un mensonge pire que le silence.
GEOMETRIC_BIN_FIELDS = ("engaged", "los_can_see", "cover_vs_observer", "charge_reachable_max_roll")
GEOMETRIC_CONT_FIELDS = (
    "col_rel", "row_rel", "edge_distance",
    "n_fight_eligible", "n_in_enemy_ez", "n_models_engaging",
)


def test_unplaced_units_assert_no_geometric_relation():
    """Aucune feature géométrique n'est vraie pour une entité pas encore mise en place.

    Mesuré avant correctif, pendant le déploiement : l'escouade active portait `engaged = 1`,
    `n_in_enemy_ez = 6` et `n_fight_eligible = 6` — elle se croyait au contact de l'ennemi alors
    qu'elle n'était pas sur la table — et `los_can_see = 1` sur les 6 slots ennemis, y compris
    les 3 pas encore posés. Cause : toutes les unités non posées partagent la sentinelle
    (-1,-1), donc leurs empreintes se recouvrent et la primitive d'engagement les déclarait
    mutuellement engagées.
    """
    import engine.observation_entities as oe
    from engine.phase_handlers.shared_utils import get_enemy_slot_mapping

    eng = _load()
    gs = eng.game_state
    dec = eng.action_decoder

    checked = steps = 0
    while gs.get("phase") == "deployment" and steps < 1000:
        mask, eligible = dec.get_squad_action_mask_and_eligible_units(gs)
        uid = str(eligible[0]["id"])
        active_player = int(gs["units_cache"][uid]["player"])
        obs = eng.obs_builder.build_squad_observation(gs, uid)

        rows = [("allies", slot, sid) for slot, sid in _obs_ally_rows(gs, uid, active_player)]
        rows += [
            ("enemies", i, str(s))
            for i, s in enumerate(get_enemy_slot_mapping(gs, active_player)[:20])
            if s is not None and str(s) in gs["units_cache"]
        ]

        for prefix, slot, sid in rows:
            unit = next(u for u in gs["units"] if str(u["id"]) == sid)
            if unit["deployed_on_turn"] is not None:
                continue
            for f in GEOMETRIC_BIN_FIELDS:
                v = float(obs[f"{prefix}_bin"][slot][oe.unit_bin_index(f)])
                assert v == 0.0, (
                    f"step {steps} : {sid} n'est pas sur le champ de bataille mais affirme "
                    f"{f} = {v} (règle 03.04)"
                )
            for f in GEOMETRIC_CONT_FIELDS:
                v = float(obs[f"{prefix}_cont"][slot][oe.unit_cont_index(f)])
                assert v == 0.0, (
                    f"step {steps} : {sid} n'est pas sur le champ de bataille mais affirme "
                    f"{f} = {v} (règle 03.04)"
                )
            checked += 1

        eng.step(_first_deploy_action(mask))
        steps += 1

    assert checked >= 10, f"trop peu d'entités non posées vérifiées ({checked})"


def test_unplaced_unit_is_not_engaged_by_an_enemy_standing_near_the_sentinel():
    """Le cas que la sentinelle rend atteignable : un ennemi POSÉ près de l'origine du plateau.

    Vérifié sur ce scénario : la zone de déploiement du joueur 2 contient `(0,0)` — 81 de ses
    hexes sont à ≤ 8 de l'origine — et l'engagement range vaut **10 subhex**. Une unité posée là
    est donc à portée d'engagement de la sentinelle `(-1,-1)`, et une unité pas encore mise en
    place s'y déclarerait « engagée » alors qu'elle n'est pas sur la table (03.04).

    Ce test existe parce qu'une contre-épreuve par mutation l'a exigé : retirer le filtre
    `on_battlefield` sur les escouades amies laissait la suite VERTE, l'heuristique de
    déploiement ne posant jamais d'unité assez près du coin. Un filtre non couvert n'est pas
    un filtre prouvé.
    """
    import engine.observation_entities as oe
    from engine.combat_utils import set_unit_coordinates
    from engine.phase_handlers.shared_utils import build_units_cache

    eng = _load()
    gs = eng.game_state
    dec = eng.action_decoder

    # Déroule jusqu'à ce qu'un ennemi soit posé ET que l'active ne le soit pas encore.
    # `uid` et `enemies_placed` sont liés AVANT la boucle : sortir sans être passé par le corps
    # (phase déjà finie, garde de steps) laisserait sinon le reste du test lire des noms non
    # définis, et l'échec sortirait en `NameError` au lieu du message qui explique le cas.
    uid = ""
    enemies_placed: list[str] = []
    steps = 0
    while gs.get("phase") == "deployment" and steps < 1000:
        mask, eligible = dec.get_squad_action_mask_and_eligible_units(gs)
        uid = str(eligible[0]["id"])
        active_player = int(gs["units_cache"][uid]["player"])
        enemies_placed = [
            str(s) for s, e in gs["units_cache"].items()
            if int(e["player"]) != active_player and int(e["col"]) >= 0
        ]
        if enemies_placed:
            break
        eng.step(_first_deploy_action(mask))
        steps += 1
    assert uid, "le déploiement ne s'est jamais ouvert — cas non construit"
    assert enemies_placed, "aucun ennemi posé pendant le déploiement — cas non construit"

    # Amène cet ennemi au contact de la sentinelle, par la voie du moteur : écrire la position
    # puis RECONSTRUIRE les caches, comme le fait `W40KEngine` au chargement. Un simple
    # `update_units_cache_position` laisserait `occupied_hexes_by_model` périmé, et le pruning
    # d'engagement — qui lit précisément cette clé — éliminerait la victime : le test serait vert
    # sans jamais construire le cas (constaté en écrivant ce test).
    victim = sorted(enemies_placed, key=str)[0]
    victim_unit = next(u for u in gs["units"] if str(u["id"]) == victim)
    # Le delta se prend sur `unit["models"]` (que `build_units_cache` compare à l'ancre), pas sur
    # `models_cache` : les deux ne portent pas les mêmes coordonnées hors d'un rebuild.
    d_col = 0 - int(victim_unit["models"][0]["col"])
    d_row = 0 - int(victim_unit["models"][0]["row"])
    for m in victim_unit["models"]:
        m["col"] = int(m["col"]) + d_col
        m["row"] = int(m["row"]) + d_row
    set_unit_coordinates(victim_unit, 0, 0)
    build_units_cache(gs)
    assert int(gs["units_cache"][victim]["col"]) == 0
    # Le cas doit être RÉEL : géométriquement, la sentinelle `(-1,-1)` EST à portée d'engagement
    # du socle posé en (0,0). La preuve se prend sur la géométrie NUE et non sur la primitive :
    # celle-ci lève désormais sur une entrée hors table (`require_entry_on_battlefield`) au lieu
    # de rendre le verdict inventé qui rendait ce cas atteignable. C'est ce refus qui est vérifié
    # juste après — les deux ensemble disent « le cas existe, et aucune mesure ne l'invente ».
    from engine.hex_utils import min_distance_between_sets
    from engine.spatial_relations import get_engagement_zone, unit_entries_within_engagement_zone

    ez = get_engagement_zone(gs)
    sentinel_hexes = set(gs["units_cache"][uid]["occupied_hexes_by_model"].values())
    assert sentinel_hexes == {(-1, -1)}, sentinel_hexes
    assert min_distance_between_sets(
        sentinel_hexes, gs["units_cache"][victim]["occupied_hexes"], max_distance=ez
    ) <= ez, "montage invalide : la sentinelle n'est pas à portée du posé, le test ne prouverait rien"
    with pytest.raises(ValueError, match="HORS TABLE"):
        unit_entries_within_engagement_zone(
            gs["units_cache"][uid], gs["units_cache"][victim], ez, metric="hex"
        )

    obs = eng.obs_builder.build_squad_observation(gs, uid)
    assert float(obs["allies_bin"][0][oe.unit_bin_index("engaged")]) == 0.0, (
        f"l'escouade {uid}, pas encore mise en place, se déclare engagée avec {victim} posé "
        f"en (0,0) — la sentinelle (-1,-1) est à portée d'engagement (03.04)"
    )
    assert float(obs["allies_cont"][0][oe.unit_cont_index("n_in_enemy_ez")]) == 0.0, (
        "ses figurines se déclarent dans la zone d'engagement ennemie sans être sur la table"
    )


def test_deployed_units_still_report_engagement_after_deployment():
    """Non-régression : le filtre 03.04 ne doit rien retirer aux unités RÉELLEMENT sur la table.

    Sans ce verrou, neutraliser l'engagement des unités non posées pourrait passer inaperçu s'il
    neutralisait aussi tout le reste — le test précédent resterait vert sur une obs morte.
    """
    import engine.observation_entities as oe
    from engine.spatial_relations import (
        get_engagement_zone,
        unit_entries_within_engagement_zone,
    )

    eng = _load()
    gs = eng.game_state
    dec = eng.action_decoder
    steps = 0
    while gs.get("phase") == "deployment" and steps < 1000:
        mask, _ = dec.get_squad_action_mask_and_eligible_units(gs)
        eng.step(_first_deploy_action(mask))
        steps += 1

    # Le calcul d'engagement de l'obs doit être celui de la primitive moteur, escouade par
    # escouade. « Toutes les unités sont posées » N'EST PLUS VRAI : une unité en réserves 20.01
    # est encore hors table ici. L'oracle prend donc une escouade POSÉE et énumère ses ennemis
    # avec `enemy_entries_on_battlefield` — l'énumération FILTRÉE du moteur, celle que le message
    # d'erreur de `require_entry_on_battlefield` désigne. Le réimplémenter sans filtre faisait
    # mesurer une géométrie depuis la sentinelle, ce que la primitive refuse (à raison).
    from engine.spatial_relations import enemy_entries_on_battlefield

    ez = get_engagement_zone(gs)
    uc = gs["units_cache"]
    uid = next((sid for sid in uc if _is_on_battlefield(gs, sid)), None)
    assert uid is not None, "aucune escouade posée après le déploiement — test sans valeur"
    active_player = int(uc[uid]["player"])
    obs = eng.obs_builder.build_squad_observation(gs, uid)
    # Métrique NON épinglée, des deux côtés : c'est tout l'objet du verrou. Ce test figeait
    # `metric="hex"` pour recopier l'épinglage de l'obs — il validait donc la divergence au lieu
    # de la détecter (à x5 le moteur résout en euclidien). Laisser la primitive résoudre.
    expected = any(
        unit_entries_within_engagement_zone(uc[uid], e, ez)
        for _sid, e in enemy_entries_on_battlefield(uc, active_player)
    )
    got = bool(obs["allies_bin"][0][oe.unit_bin_index("engaged")])
    assert got == expected, (
        f"escouade posée {uid} : l'obs dit engaged={got}, la primitive moteur dit {expected}"
    )


def test_squad_obs_size_target_matches_the_schema():
    """Les points 1, 2, 4 et 5 ne changent PAS `obs_size` ; le point 3, lui, l'a changé.

    Il valait 20828 jusqu'au 2026-08-04 : la suppression de la clause « buddy » (04.02 WHILE
    FIGHTING — seule une figurine ENGAGÉE frappe ; le relais par une alliée au contact venait
    d'une édition antérieure) emporte les deux champs qui la décrivaient, `ez_relayed_by_ally`
    (self_models_bin) et `n_relayed_ez` (unit_cont) — d'où 20780.

    Puis le chantier 01 (2026-08-04) a remplacé les 13 bits `rule_<id>` par 8 slots d'ids de
    capacité + 4 slots d'ids de statut : 13 bits x 28 entités remplacés par 12 entiers x 28,
    d'où 20780 -> 20752.

    Le chantier 01 avait aussi la charge de déclarer les DEUX emplacements de CP attendus par le
    chantier 02 (`global_cont`, règle 08.02) — il ne l'a pas fait. L'oubli est réparé au début du
    chantier 02 : `my_command_points` / `enemy_command_points`, d'où 20752 -> 20754. Le retrain
    `--new` reste unique (celui du chantier 01, du même jour, invalidait déjà les `.zip`).

    Toujours le chantier 02 : le registre du bloc `decision_options_bin` a été DÉCOUPLÉ du
    vocabulaire observé (`DECISION_GRANTABLE_EFFECT_IDS`). Il portait un bit `grants_*` par effet
    OBSERVABLE, alors que 6 des 13 ne sont accordables par aucun roster — 36 scalaires qui ne
    pouvaient jamais valoir 1, et 6 de plus à chaque capacité ajoutée à l'observation. D'où
    20754 -> 20718, et surtout : allonger le vocabulaire observé ne bouge PLUS `obs_size`, ce
    que le gel du chantier 01 promettait sans le tenir.

    Le chantier 03 (2026-08-05) a trouvé le MÊME oubli que le chantier 02, et deux fois : le
    chantier 01 annonce que les capacités de FACTION vont dans `global_bin` (« voir chantier
    03 ») mais n'y a déclaré aucun emplacement, et il n'a pas non plus déclaré le type de
    décision du Waaagh!. Réparé ici : 6 drapeaux de `GLOBAL_BIN_FIELDS`
    (`my`/`enemy_waaagh_available`, `my`/`enemy_waaagh_active`,
    `my`/`enemy_oath_target_selected`) et une entrée de plus dans `AGENT_DECISION_TYPE_IDS`
    (`waaagh_call`, +1 bit de `decision_ctx_bin`), d'où 20718 -> 20725. Le retrain `--new` reste
    UNIQUE : les `.zip` existants datent d'avant le gel du 2026-08-04 et étaient déjà invalidés.

    QUATRE bits pour le Waaagh! et non deux : sa durée court « until the start of your next
    Command phase », donc elle enjambe le tour adverse. L'identité de la cible d'Oath, elle,
    n'est PAS ici : elle est portée par le statut `oath_target` de l'entité visée — coût zéro.

    C'est le DERNIER changement d'`obs_size` de la séquence : les chantiers 04 à 06 n'utilisent
    que des dimensions déjà déclarées.

    Ce verrou valait 20768 tant que le point 3 restait ouvert : les quatre autres points ne
    touchent QUE le contenu de l'observation de déploiement, jamais sa taille — donc aucun modèle
    n'était invalidé par eux. Le point 3 ajoute le bloc « candidats de déploiement »
    (5 slots x 12 scalaires) et impose, par construction, un retrain `--new`.
    """
    from engine.observation_builder import ObservationBuilder
    from engine.observation_entities import (
        DEPLOY_CAND_BIN_SIZE, DEPLOY_CAND_CONT_SIZE, N_DEPLOY_SLOTS,
    )

    assert ObservationBuilder.SQUAD_OBS_SIZE_TARGET == 20725
    assert N_DEPLOY_SLOTS * (DEPLOY_CAND_CONT_SIZE + DEPLOY_CAND_BIN_SIZE) == 60, (
        "le bloc candidat de déploiement a changé de taille : mettre à jour `obs_size` dans les "
        "5 profils de la config d'agent, et l'historique d'AI_OBSERVATION.md"
    )
