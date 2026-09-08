"""13.09 Hidden — le statut est CONTINU, donc rafraîchi à chaque perte de figurine.

Règle lue (Documentation/40k_rules/13 Terrain.pdf, 13.09) : « A model is hidden **while** all of
the following apply to it » — un état maintenu, pas un instantané. Le moteur ne le calculait qu'au
début de la phase de tir (`shooting_phase_start`), si bien qu'une escouade dont la dernière
figurine exposée mourait EN COURS de phase restait ciblable au-delà de la detection range par
tous les tireurs suivants.

Ce n'est pas un cas de bord : `_select_allocation_model` alloue les pertes, à tier de rôle égal,
à la figurine la plus proche de l'ennemi — donc précisément à celle qui dépasse de la zone
obscurante. Une escouade à cheval sur le bord d'une ruine perd d'abord ses figurines découvertes.

Le rafraîchissement vit au choke-point de retrait (`destroy_model`), et NON sur les sites d'appel
du tir : toutes les causes de mort y passent (tir, mêlée, hazard, cohérence, déploiement,
réserves 20.04). `test_hidden_refresh_covers_every_death_cause` verrouille ce choix — un appel
posé dans le seul chemin de tir laisserait la mêlée muette.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from engine.phase_handlers.shared_utils import destroy_model
from engine.phase_handlers.shooting_handlers import (
    shooting_build_valid_target_pool,
    shooting_phase_start,
)
from tests.unit.engine.test_squad_obs_terrain_flags import (
    _make_engine,
    _unit_cfg,
)
from engine.observation_builder import ObservationBuilder

#: Zone obscurante de la fixture importée : colonnes 28..36, lignes 18..22.
#: La figurine CACHÉE y est ; l'EXPOSÉE est deux colonnes plus loin, hors zone.
HIDDEN_MODEL_HEX = (36, 20)
EXPOSED_MODEL_HEX = (38, 20)

#: Les deux tireurs sont hors detection range (15") de CHAQUE figurine cible, mais dans la portée
#: de leur arme (24") — c'est la bande où 13.09 décide seule de l'éligibilité.
#:   tireur A → exposée 18, → cachée 20
#:   tireur B → exposée 20, → cachée 22
SHOOTER_A_HEX = (56, 20)
SHOOTER_B_HEX = (58, 20)

TARGET_ID = "2"
SHOOTER_B_ID = "3"


def _config_two_shooters() -> Dict[str, Any]:
    obs_params = {"obs_size": ObservationBuilder.SQUAD_OBS_SIZE_TARGET}
    return {
        "board": {
            "default": {
                "cols": 120, "rows": 80, "hex_radius": 1.0, "margin": 0.0,
                "wall_hexes": [], "inches_to_subhex": 1,
            }
        },
        "game_rules": {
            "engagement_zone": 1, "engagement_zone_vertical": 5, "max_base_size_hex": 35,
            "unit_model_cohesion_range": 2, "unit_global_cohesion_range": 9,
            "squad_min_neighbors": 1, "cohesion_distance_mode": "euclidean",
        },
        "charge": {"charge_max_distance": 12},
        "move": {
            "can_move_through_enemy_engagement_zone": True,
            "can_move_through_enemy_model": False,
            "can_move_through_friendly_model": True,
        },
        "pve_mode": False,
        "scenario_objectives": [],
        "observation_params": obs_params,
        "training_config": {"observation_params": obs_params, "max_turns_per_episode": 3},
        "units": [
            _unit_cfg(1, 1, [SHOOTER_A_HEX], ["INFANTRY"]),
            _unit_cfg(2, 2, [HIDDEN_MODEL_HEX, EXPOSED_MODEL_HEX], ["INFANTRY"]),
            _unit_cfg(3, 1, [SHOOTER_B_HEX], ["INFANTRY"]),
        ],
    }


def _enter_shooting_phase(eng) -> Dict[str, Any]:
    gs = eng.game_state
    gs["phase"] = "shoot"
    gs["current_player"] = 1
    shooting_phase_start(gs)
    return gs


def _model_id_at(gs: Dict[str, Any], squad_id: str, hex_pos: Tuple[int, int]) -> str:
    col, row = hex_pos
    for mid in gs["squad_models"][squad_id]:
        m = gs["models_cache"][mid]
        if (int(m["col"]), int(m["row"])) == (col, row):
            return str(mid)
    raise AssertionError(f"fixture : aucune figurine de {squad_id} en {hex_pos}")


def test_squad_becomes_hidden_mid_phase_and_leaves_the_target_pool() -> None:
    """La dernière figurine exposée meurt → l'escouade sort du pool des tireurs suivants.

    Avant le correctif, `unit['hidden']` restait figé à la valeur du début de phase (False, une
    figurine dépassant de la zone) et le tireur B gardait la cible dans son pool alors qu'il est
    à 22" — hors des 15" de detection range.
    """
    eng = _make_engine(_config_two_shooters())
    gs = _enter_shooting_phase(eng)
    target = gs["unit_by_id"][TARGET_ID]

    # État de départ : une figurine hors zone obscurante → l'escouade n'est PAS cachée, donc
    # elle est légitimement ciblable au-delà de la detection range.
    assert target["hidden"] is False, "fixture : la figurine exposée doit empêcher le statut caché"
    pool_before = shooting_build_valid_target_pool(gs, SHOOTER_B_ID)
    assert TARGET_ID in pool_before, (
        "VERT VACANT : sans la cible dans le pool de départ, le test ne mesurerait rien"
    )

    destroy_model(gs, _model_id_at(gs, TARGET_ID, EXPOSED_MODEL_HEX), reason="combat")

    # Le POOL d'abord : c'est l'invariant de production, et l'ordre importe. Vérifier le drapeau
    # en premier ferait échouer le test avant d'atteindre cette ligne, qui deviendrait alors un
    # vert vacant — jamais discriminante. Mesuré : sans le refresh, c'est bien ICI que ça casse.
    pool_after = shooting_build_valid_target_pool(gs, SHOOTER_B_ID)
    assert TARGET_ID not in pool_after, (
        "13.09 : une escouade cachée n'est ciblable que dans la detection range (15\"), "
        "or ce tireur est à 22\""
    )
    # 13.09 : il ne reste que des figurines dans la zone obscurante → escouade cachée MAINTENANT.
    assert target["hidden"] is True, "13.09 : le statut doit suivre la perte, pas la fin de phase"


def test_hidden_refresh_covers_every_death_cause() -> None:
    """Le refresh vit au choke-point de retrait, donc hors de toute phase de tir.

    Contre-épreuve du choix d'implémentation : un appel posé dans le chemin de tir laisserait la
    phase de combat — qui retire aussi des figurines — servir un statut périmé. Ici la mort
    survient en phase `fight`, sans qu'aucun pool de tir ne soit construit.
    """
    eng = _make_engine(_config_two_shooters())
    gs = _enter_shooting_phase(eng)
    target = gs["unit_by_id"][TARGET_ID]
    assert target["hidden"] is False

    gs["phase"] = "fight"
    destroy_model(gs, _model_id_at(gs, TARGET_ID, EXPOSED_MODEL_HEX), reason="combat")

    assert target["hidden"] is True
    assert [str(m) for m in target["hidden_models"]] == gs["squad_models"][TARGET_ID], (
        "hidden_models doit lister les figurines VIVANTES cachées, sans la morte"
    )
