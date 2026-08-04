"""T5 — contacts par figurine : bord-à-bord brut → zone d'engagement (règle 03.04).

Refonte V11 (Documentation/Implementation/V11_audit_observation.md §9.2) : le drapeau
par figurine « au contact d'un ennemi » était calculé par `calculate_hex_distance(...) == BASE_TO_BASE_SUBHEX`, c'est-à-dire une distance
d'ANCRE à ANCRE égale à 1 subhex. Ils passent à la primitive d'engagement du moteur
(`unit_entries_within_engagement_zone` sur des entrées synthétiques par figurine, exactement
comme `get_fighting_models`), qui mesure BORD À BORD et tient compte de la taille des socles.

Contre-épreuve intégrée : `test_large_bases_in_ez_are_seen` place deux figurines à grande base
dont les ANCRES sont à 2 subhex — donc invisibles pour l'ancien test `== 1` — mais dont les
socles se touchent : la règle 03.04 les déclare engagées, et le pool de combat du moteur
(`get_fighting_models`) les compte. L'ancien code sortait 0 là où le moteur disait « combat ».
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple
from unittest.mock import patch

import pytest

from engine.observation_builder import ObservationBuilder
from engine.phase_handlers.shared_utils import get_fighting_models
from engine.w40k_core import W40KEngine

# Le bloc figurine ne porte plus que l'individuel : les 3 drapeaux d'engagement (le profil et le
# role sont au niveau TYPE, cf. layout build_squad_observation).
BIN_FIGHT_ELIGIBLE = 0
BIN_IN_ENEMY_EZ = 1


def _weapon_cfg() -> Dict[str, Any]:
    return {
        "ATK": 3, "STR": 4, "AP": 0, "DMG": 1, "NB": 1, "RNG": 24,
        "WEAPON_RULES": [], "display_name": "Test Bolter",
    }


def _unit_cfg(uid: int, player: int, positions: List[Tuple[int, int]], base_size: int) -> Dict[str, Any]:
    specs = [{"col": c, "row": r, "HP_CUR": 1, "HP_MAX": 1, "VALUE": 10} for c, r in positions]
    return {
        "id": uid, "player": player, "col": positions[0][0], "row": positions[0][1],
        "unitType": "TestUnit", "DISPLAY_NAME": f"Unit {uid}",
        "HP_CUR": len(specs), "HP_MAX": 1, "MOVE": 6, "T": 4,
        "ARMOR_SAVE": 4, "INVUL_SAVE": 0,
        "RNG_WEAPONS": [_weapon_cfg()], "CC_WEAPONS": [_weapon_cfg()],
        "UNIT_RULES": [], "UNIT_KEYWORDS": [{"keywordId": "INFANTRY"}],
        "LD": 7, "OC": 2, "VALUE": 10 * len(specs),
        "ICON": "test", "ICON_SCALE": 1.0, "ILLUSTRATION_RATIO": 1.0,
        "BASE_SHAPE": "round", "BASE_SIZE": base_size, "MODEL_HEIGHT": 2.5,
        "models": specs,
    }


def _config(
    my_positions: List[Tuple[int, int]],
    enemy_positions: List[Tuple[int, int]],
    base_size: int = 1,
) -> Dict[str, Any]:
    obs_params = {
        "obs_size": ObservationBuilder.SQUAD_OBS_SIZE_TARGET,
    }
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
            _unit_cfg(1, 1, my_positions, base_size),
            _unit_cfg(2, 2, enemy_positions, base_size),
        ],
    }


def _make_engine(cfg: Dict[str, Any]) -> W40KEngine:
    with patch("engine.w40k_core.load_weapon_damage_table", return_value={}), \
         patch.object(W40KEngine, "_build_reward_configs_for_current_units", return_value={}):
        eng = W40KEngine(config=cfg)
    eng.reset()
    return eng


def _model_flags(engine, k_idx: int) -> Dict[str, float]:
    binv = engine.obs_builder.build_squad_observation(engine.game_state, "1")["self_models_bin"][k_idx]
    return {
        "fight": float(binv[BIN_FIGHT_ELIGIBLE]),
        "in_ez": float(binv[BIN_IN_ENEMY_EZ]),
    }


def test_model_adjacent_to_enemy_is_in_ez():
    """Figurine 0 collée à l'ennemi : dans l'EZ ; figurine 1 (loin, isolée) : rien."""
    eng = _make_engine(_config([(30, 20), (50, 20)], [(31, 20)]))
    assert _model_flags(eng, 0)["in_ez"] == 1.0
    far = _model_flags(eng, 1)
    assert far["in_ez"] == 0.0 and far["fight"] == 0.0


def test_a_model_behind_an_engaged_ally_does_not_fight():
    """04.02 WHILE FIGHTING : « Each target must be engaged with the model that has that weapon. »

    La figurine 1 est hors de l'EZ ennemie mais au contact de sa camarade, elle, engagée. Jusqu'au
    2026-08-04 une clause « buddy » lui accordait le droit de frapper par relais — une règle d'une
    édition antérieure de 40K, absente de ce corpus (`base-contact` n'y apparaît que pour dire
    qu'une figurine au contact NE BOUGE PAS au pile-in, 12.03/12.08 WHILE MOVING).

    Le verrou porte sur les DEUX faces : le drapeau d'observation et le pool du moteur doivent
    dire la même chose — c'est leur désaccord qui ferait annoncer à l'agent un volume d'attaques
    que la résolution ne produit pas.
    """
    # (28,20) et non (29,20) : à (29,20) la figurine est ENGAGÉE sous la métrique résolue
    # (bord-à-bord 1,5 = le seuil exact), la prémisse « non engagée » serait fausse. À (28,20)
    # les deux métriques s'accordent — elle n'est pas engagée — et elle reste dans l'EZ de sa
    # camarade, ce qui est précisément la configuration que le relais couvrait.
    eng = _make_engine(_config([(30, 20), (28, 20)], [(31, 20)]))
    first = _model_flags(eng, 0)
    second = _model_flags(eng, 1)
    pool = set(get_fighting_models(eng.game_state, "1"))
    from engine.phase_handlers.shared_utils import _synth_model_entry, get_engagement_zone
    from engine.spatial_relations import unit_entries_within_engagement_zone
    _gs, _mc = eng.game_state, eng.game_state["models_cache"]

    def _synth(mid: str) -> Dict[str, Any]:
        m = _mc[mid]
        return _synth_model_entry(
            _gs, "1", m, int(m["col"]), int(m["row"]), level=int(m["level"])
        )

    assert unit_entries_within_engagement_zone(
        _synth("1#1"), _synth("1#0"), get_engagement_zone(_gs)
    ), "prémisse : la figurine 1 doit être dans l'EZ de sa camarade — sinon le relais n'aurait rien relayé"
    alive = [m for m in eng.game_state["squad_models"]["1"] if m in eng.game_state["models_cache"]]

    # Prémisse CONSTRUITE : la 0 est bien engagée, la 1 ne l'est pas.
    assert first["in_ez"] == 1.0, "prémisse : la figurine 0 doit être engagée"
    assert second["in_ez"] == 0.0, "prémisse : la figurine 1 ne doit PAS être engagée"

    assert second["fight"] == 0.0, "une figurine non engagée ne frappe pas (04.02)"
    assert alive[1] not in pool, "le pool moteur ne doit pas non plus la retenir"
    assert first["fight"] == 1.0 and alive[0] in pool, (
        "contre-épreuve : la figurine ENGAGÉE, elle, frappe — le correctif ne refuse pas tout"
    )


def test_large_bases_in_ez_are_seen():
    """Contre-épreuve du bord-à-bord : ancres à 2 subhex, socles au contact.

    L'ancien test `calculate_hex_distance(ancre, ancre) == 1` renvoyait 0 ici ; la règle 03.04
    (bord à bord) et le pool de combat du moteur disent « engagée ».
    """
    eng = _make_engine(_config([(30, 20)], [(32, 20)], base_size=16))
    gs = eng.game_state
    from engine.combat_utils import calculate_hex_distance
    from engine.phase_handlers.shared_utils import BASE_TO_BASE_SUBHEX

    assert calculate_hex_distance(30, 20, 32, 20) != BASE_TO_BASE_SUBHEX, (
        "fixture invalide : les ancres doivent être HORS du test bord-à-bord brut"
    )
    assert "1#0" in set(get_fighting_models(gs, "1")), "fixture : le moteur doit voir l'engagement"
    assert _model_flags(eng, 0)["in_ez"] == 1.0


def _engine_x5(my_positions, enemy_positions, base_size: int = 6) -> W40KEngine:
    """Moteur monté à **x5** — la seule résolution où la métrique d'engagement est en jeu.

    Les autres fixtures de ce fichier tournent à `inches_to_subhex=1`, où `geometry_is_hex`
    impose « hex » quoi qu'en dise la config : elles ne peuvent PAS voir un épinglage de
    métrique. `engagement_zone` est donné en POUCES (w40k_core le scale au chargement) ;
    `base_size=6` = la datasheet Boyz (13, unités ×10) à x5.
    """
    cfg = _config(my_positions, enemy_positions, base_size=base_size)
    cfg["board"]["default"]["inches_to_subhex"] = 5
    cfg["game_rules"]["engagement_zone"] = 2
    return _make_engine(cfg)


def test_in_enemy_ez_follows_the_resolved_metric_not_a_pinned_one():
    """VERROU de métrique : l'obs mesure l'EZ comme le MOTEUR, pas dans une métrique figée.

    Jusqu'au 2026-08-04, `in_enemy_ez` et `engaged` étaient calculés avec `metric="hex"` épinglé
    (« feature d'observation IA, retrain hors périmètre migration »). Sans effet à x1 — la
    résolution y impose hex — mais à x5 le moteur résout en EUCLIDIEN : l'agent lisait un verdict
    hex pendant que la résolution du MÊME step en appliquait un autre. Balayage de 2501 positions
    autour d'une escouade ennemie : 61 divergences, dont 49 figurines que le moteur faisait
    combattre et que l'obs déclarait hors zone d'engagement.

    La position (45,60) vs ennemi en (60,60) est l'une d'elles, CONSTRUITE et non espérée : la
    prémisse ci-dessous vérifie que les deux métriques y désaccordent réellement. Sans elle, ce
    test resterait vert sur n'importe quelle position banale — le mode d'échec exact du verrou
    précédent (`test_deployment_observation_contract`, qui recopiait l'épinglage).
    """
    from engine.phase_handlers.shared_utils import _synth_model_entry, get_engagement_zone
    from engine.spatial_relations import geometry_is_hex, unit_entries_within_engagement_zone

    eng = _engine_x5([(45, 60)], [(60, 60)])
    gs = eng.game_state
    ez = get_engagement_zone(gs)
    assert not geometry_is_hex(gs), "prémisse : à x5 la géométrie doit être euclidienne"

    m = gs["models_cache"]["1#0"]
    synth = _synth_model_entry(gs, "1", m, int(m["col"]), int(m["row"]), level=int(m["level"]))
    enemy = gs["units_cache"]["2"]
    verdict_hex = unit_entries_within_engagement_zone(synth, enemy, ez, metric="hex")
    verdict_euclid = unit_entries_within_engagement_zone(synth, enemy, ez, metric="euclidean")
    assert verdict_hex != verdict_euclid, (
        "prémisse : cette position doit être un DÉSACCORD entre les deux métriques, sinon le "
        f"test ne vérifie rien (hex={verdict_hex}, euclidean={verdict_euclid})"
    )

    pool = set(get_fighting_models(gs, "1"))
    assert ("1#0" in pool) == verdict_euclid, (
        "prémisse : le pool du moteur suit la métrique RÉSOLUE (euclidean à x5)"
    )
    flags = _model_flags(eng, 0)
    assert flags["in_ez"] == (1.0 if verdict_euclid else 0.0), (
        "l'obs doit suivre la métrique résolue par le moteur, pas une métrique épinglée"
    )
    assert flags["fight"] == (1.0 if "1#0" in pool else 0.0)

    # Le drapeau d'ESCOUADE `engaged` portait le même épinglage, sur la même primitive : il est
    # couvert par la même position (l'escouade n'a qu'une figurine, son verdict est le sien).
    import engine.observation_entities as oe

    obs = eng.obs_builder.build_squad_observation(gs, "1")
    engaged = float(obs["allies_bin"][0][oe.unit_bin_index("engaged")])
    assert engaged == (1.0 if verdict_euclid else 0.0), (
        "le drapeau d'escouade `engaged` doit suivre la même métrique résolue"
    )


def test_flags_agree_with_engine_fight_pool():
    """Cohérence : toute figurine dans l'EZ ennemie est dans le pool de combat du moteur (12.04)."""
    eng = _make_engine(_config([(30, 20), (29, 20), (50, 20)], [(31, 20)]))
    gs = eng.game_state
    pool = set(get_fighting_models(gs, "1"))
    alive = [m for m in gs["squad_models"]["1"] if m in gs["models_cache"]]
    for k_idx, mid in enumerate(alive):
        flags = _model_flags(eng, k_idx)
        if flags["in_ez"] == 1.0:
            assert mid in pool, f"{mid} vu engagé par l'obs mais absent du pool moteur"
        assert flags["fight"] == (1.0 if mid in pool else 0.0)
