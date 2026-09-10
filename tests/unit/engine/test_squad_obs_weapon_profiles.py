"""V11 §9.2.5 — l'observation squad expose les PROFILS D'ARMES et leurs RÈGLES (ids).

Trou fermé ici : depuis le 2026-07-26 toutes les règles d'armes du PDF 24 sont résolues dans le
chemin vif (tir ET mêlée), mais le vecteur squad (199-d) n'en contenait **aucune trace** — ni
NB/ATK/STR/AP/DMG/portée, ni un seul bit de règle. L'agent SUBISSAIT [MELTA], [DEVASTATING
WOUNDS], [RAPID FIRE]… sans les percevoir : impossible d'apprendre à s'en servir.

Ce que ces tests verrouillent :
- le regroupement par PROFIL avec le **nombre de porteurs vivants** (sans lui, 1 rokkit et
  9 shootas sont indiscernables) et sa décroissance quand une figurine meurt ;
- les caractéristiques brutes et les règles, à leur place documentée dans le layout ;
- les règles PARAMÉTRÉES exposées par leur valeur, et le **keyword ciblé** par [ANTI-X]
  (sans lui le seuil Y+ est du bruit — l'effet dépend des keywords de la cible, 24.03) ;
- la symétrie : les slots ENNEMIS portent les mêmes champs (choix de cible / menace) ;
- l'absence de troncature silencieuse (le dépassement de K est LOGUÉ) ;
- [INDIRECT FIRE] EST exposée depuis le 2026-08-16 : 10.07 est implémentée, et l'agent doit la
  percevoir pour pouvoir CHOISIR le tir indirect (10.02). Le critère n'a pas changé — exposer une
  règle inerte reste du bruit ; c'est la règle qui a cessé de l'être.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple
from unittest.mock import patch

import pytest

from engine.observation_builder import (
    ObservationBuilder,
    weapon_profile_obs_ids,
    weapon_rule_obs_ids,
)
from engine.observation_weapon_profiles import (
    COMBI_GROUP_MARKER_COUNT,
    COMBI_GROUP_MARKER_NAMES,
    COMBI_GROUP_MARKER_OBS_IDS,
    PROFILE_BIN_SIZE,
    PROFILE_CONT_SIZE,
    PROFILE_STAT_CONT,
    WEAPON_RULE_BITS,
    WEAPON_RULE_ID_SLOTS,
    WEAPON_RULE_OBS_VOCABULARY,
    WEAPON_RULE_PARAMS,
    assign_combi_group_markers,
    collect_weapon_profiles,
    profile_identity,
)
from engine.w40k_core import W40KEngine
from tests.unit.engine._config_helpers import build_engine_config

# Offsets DANS un profil (cf. observation_weapon_profiles, layout documenté).
P_NB, P_ATK, P_STR, P_AP, P_DMG, P_RNG, P_CARRIERS = range(PROFILE_STAT_CONT)
P_ANTI_Y = PROFILE_STAT_CONT + len(WEAPON_RULE_PARAMS)
B_MASK = PROFILE_BIN_SIZE - 1


def _param_index(rule_id: str) -> int:
    names = [name for name, _ in WEAPON_RULE_PARAMS]
    return PROFILE_STAT_CONT + names.index(rule_id)


def _rule_names(ids_row: Any) -> set:
    """Symboles écrits dans les slots d'ids d'un profil (0 = slot vide).

    Registre COMPLET (règles d'arme + marqueurs de groupe combi) : ces slots portent les deux
    vocabulaires, et un helper qui n'en connaîtrait qu'un lèverait un `KeyError` opaque sur le
    premier profil combi au lieu de dire ce qu'il a lu.
    """
    by_id = {obs_id: name for name, obs_id in weapon_profile_obs_ids().items()}
    return {by_id[int(v)] for v in ids_row if int(v) != 0}


def _weapon(**over: Any) -> Dict[str, Any]:
    base = {
        "ATK": 3, "STR": 4, "AP": 0, "DMG": 1, "NB": 1, "RNG": 24,
        "WEAPON_RULES": [], "code": "test_bolter", "display_name": "Test Bolter",
    }
    base.update(over)
    return base


def _melee(**over: Any) -> Dict[str, Any]:
    base = {"ATK": 3, "STR": 4, "AP": 0, "DMG": 1, "NB": 2,
            "WEAPON_RULES": [], "code": "test_blade", "display_name": "Test Blade"}
    base.update(over)
    return base


def _unit_cfg(
    uid: int, player: int, positions: List[Tuple[int, int]], *,
    rng_weapons: List[Dict[str, Any]] | None = None,
    cc_weapons: List[Dict[str, Any]] | None = None,
    per_model_rng: Dict[int, List[Dict[str, Any]]] | None = None,
    keywords: List[str] | None = None,
) -> Dict[str, Any]:
    specs: List[Dict[str, Any]] = []
    for idx, (c, r) in enumerate(positions):
        spec: Dict[str, Any] = {"col": c, "row": r, "HP_CUR": 1, "HP_MAX": 1, "VALUE": 10}
        if per_model_rng and idx in per_model_rng:
            spec["RNG_WEAPONS"] = per_model_rng[idx]
        specs.append(spec)
    return {
        "id": uid, "player": player, "col": positions[0][0], "row": positions[0][1],
        "unitType": "TestUnit", "DISPLAY_NAME": f"Unit {uid}",
        "HP_CUR": len(specs), "HP_MAX": 1, "MOVE": 6, "T": 4,
        "ARMOR_SAVE": 4, "INVUL_SAVE": 0,
        "RNG_WEAPONS": rng_weapons if rng_weapons is not None else [_weapon()],
        "CC_WEAPONS": cc_weapons if cc_weapons is not None else [_melee()],
        "UNIT_RULES": [],
        "UNIT_KEYWORDS": [{"keywordId": k} for k in (keywords or ["INFANTRY"])],
        "LD": 7, "OC": 2, "VALUE": 10 * len(specs),
        "ICON": "test", "ICON_SCALE": 1.0, "ILLUSTRATION_RATIO": 1.0,
        "BASE_SHAPE": "round", "BASE_SIZE": 1, "MODEL_HEIGHT": 2.5,
        "models": specs,
    }


def _config(units: List[Dict[str, Any]]) -> Dict[str, Any]:
    obs_params = {
        "obs_size": ObservationBuilder.SQUAD_OBS_SIZE_TARGET,
    }
    return {
        "board": {"default": {"cols": 200, "rows": 80, "hex_radius": 1.0, "margin": 0.0,
                              "wall_hexes": [], "inches_to_subhex": 1}},
        "game_rules": {
            "engagement_zone": 1, "engagement_zone_vertical": 5, "max_base_size_hex": 35,
            "unit_model_cohesion_range": 2, "unit_global_cohesion_range": 9,
            "squad_min_neighbors": 1, "cohesion_distance_mode": "euclidean",
        },
        "charge": {"charge_max_distance": 12},
        "move": {"can_move_through_enemy_engagement_zone": True,
                 "can_move_through_enemy_model": False,
                 "can_move_through_friendly_model": True},
        "pve_mode": False,
        "scenario_objectives": [],
        "observation_params": obs_params,
        "training_config": {"observation_params": obs_params, "max_turns_per_episode": 3},
        "units": units,
    }


def _make_engine(units: List[Dict[str, Any]]) -> W40KEngine:
    with patch("engine.w40k_core.load_weapon_damage_table", return_value={}), \
         patch.object(W40KEngine, "_build_reward_configs_for_current_units", return_value={}):
        eng = W40KEngine(config=build_engine_config(_config(units)))
    eng.reset()
    return eng


def _self_profile(engine: W40KEngine, slot: int) -> Tuple[Any, Any]:
    """(cont, bin) du slot de profil `slot` de MON escouade (0..K_ranged-1 = tir, puis mêlée)."""
    obs = engine.obs_builder.build_squad_observation(engine.game_state, "1")
    # Sous-registre « armes » de l'unite ACTIVE = ligne 0 des allies.
    return (obs["allies_wpn_cont"][0][slot], obs["allies_wpn_bin"][0][slot])


def _self_rules(engine: W40KEngine, slot: int) -> set:
    """Règles observées du slot de profil `slot` de MON escouade, par leur NOM."""
    obs = engine.obs_builder.build_squad_observation(engine.game_state, "1")
    return _rule_names(obs["allies_wpn_rule_ids"][0][slot])


def _melee_slot_index(slot_in_melee: int = 0) -> int:
    return ObservationBuilder.K_WEAPONS_RANGED + slot_in_melee


def _enemy_profile(engine: W40KEngine, enemy_slot: int, profile_slot: int) -> Tuple[Any, Any]:
    obs = engine.obs_builder.build_squad_observation(engine.game_state, "1")
    return (obs["enemies_wpn_cont"][enemy_slot][profile_slot],
            obs["enemies_wpn_bin"][enemy_slot][profile_slot])


# ---------------------------------------------------------------- regroupement


def test_profiles_group_by_identity_and_count_carriers():
    """Deux profils distincts dans une escouade -> deux entrées, avec leurs porteurs."""
    bulk = _weapon(display_name="Shoota", NB=2, STR=4, RNG=18)
    rokkit = _weapon(display_name="Rokkit", NB=1, STR=8, AP=-2, DMG=3, RNG=24)
    eng = _make_engine([
        _unit_cfg(1, 1, [(20, 20), (21, 20), (22, 20)],
                  rng_weapons=[bulk], per_model_rng={2: [rokkit]}),
        _unit_cfg(2, 2, [(60, 20)]),
    ])
    models = [eng.game_state["models_cache"][m] for m in eng.game_state["squad_models"]["1"]]
    profiles = collect_weapon_profiles(models, "RNG_WEAPONS")
    assert [(w["display_name"], n) for w, n in profiles] == [("Shoota", 2), ("Rokkit", 1)]


def test_carrier_count_is_exposed_and_drops_with_losses():
    """Le compteur de porteurs est la donnée qui distingue 1 rokkit de 9 shootas."""
    from engine.phase_handlers.shared_utils import destroy_model

    eng = _make_engine([
        _unit_cfg(1, 1, [(20, 20), (21, 20), (22, 20)]),
        _unit_cfg(2, 2, [(60, 20)]),
    ])
    assert _self_profile(eng, 0)[0][P_CARRIERS] == pytest.approx(3.0)
    destroy_model(eng.game_state, "1#2", reason="combat")
    assert _self_profile(eng, 0)[0][P_CARRIERS] == pytest.approx(2.0)


def test_profile_order_is_deterministic_by_carriers():
    """L'ordre des slots ne permute pas d'un step à l'autre : porteurs décroissants."""
    a = _weapon(display_name="A", NB=1, STR=4)
    b = _weapon(display_name="B", NB=1, STR=9)
    eng = _make_engine([
        _unit_cfg(1, 1, [(20, 20), (21, 20), (22, 20)],
                  rng_weapons=[a], per_model_rng={2: [b]}),
        _unit_cfg(2, 2, [(60, 20)]),
    ])
    first, second = _self_profile(eng, 0)[0], _self_profile(eng, 1)[0]
    assert first[P_CARRIERS] == pytest.approx(2.0) and first[P_STR] == pytest.approx(4.0)
    assert second[P_CARRIERS] == pytest.approx(1.0) and second[P_STR] == pytest.approx(9.0)
    # Stabilité : deux constructions successives donnent le même vecteur.
    assert list(_self_profile(eng, 0)[0]) == list(first)


def test_identical_stats_different_names_are_one_profile():
    """C'est le PROFIL qui décide de la résolution, pas le nom de l'arme."""
    w1 = _weapon(display_name="Bolter A")
    w2 = _weapon(display_name="Bolter B")
    assert profile_identity(w1) == profile_identity(w2)


# ---------------------------------------------------------------- contenu brut


def test_raw_characteristics_are_exposed():
    """NB / ATK / STR / AP / DMG / portée sortent en valeurs BRUTES, à leur offset documenté."""
    gun = _weapon(display_name="Melta", NB=2, ATK=3, STR=9, AP=-4, DMG="D6", RNG=12)
    eng = _make_engine([
        _unit_cfg(1, 1, [(20, 20)], rng_weapons=[gun]),
        _unit_cfg(2, 2, [(60, 20)]),
    ])
    cont, _ = _self_profile(eng, 0)
    inches = int(eng.game_state["inches_to_subhex"])
    assert cont[P_NB] == pytest.approx(2.0)
    assert cont[P_ATK] == pytest.approx(3.0)
    assert cont[P_STR] == pytest.approx(9.0)
    assert cont[P_AP] == pytest.approx(-4.0)
    assert cont[P_DMG] == pytest.approx(3.5)          # D6 -> espérance moteur
    assert cont[P_RNG] == pytest.approx(12.0 * inches)


def test_melee_profiles_live_in_their_own_slots():
    """Les deux registres sont exposés EN PERMANENCE (l'agent anticipe tir ET mêlée en move)."""
    eng = _make_engine([
        _unit_cfg(1, 1, [(20, 20)], cc_weapons=[_melee(display_name="Axe", NB=4, STR=7, AP=-2)]),
        _unit_cfg(2, 2, [(60, 20)]),
    ])
    cont, binv = _self_profile(eng, _melee_slot_index())
    assert cont[P_NB] == pytest.approx(4.0)
    assert cont[P_STR] == pytest.approx(7.0)
    assert cont[P_RNG] == pytest.approx(0.0)   # une arme de mêlée n'a pas de portée
    assert binv[B_MASK] == pytest.approx(1.0)


def test_empty_profile_slot_is_zero_padded_with_mask_off():
    """Un slot sans profil est identifiable par son mask, pas par des zéros ambigus."""
    eng = _make_engine([
        _unit_cfg(1, 1, [(20, 20)]),
        _unit_cfg(2, 2, [(60, 20)]),
    ])
    cont, binv = _self_profile(eng, 1)   # une seule arme de tir -> slot 1 vide
    assert binv[B_MASK] == pytest.approx(0.0)
    assert not any(cont)


# ---------------------------------------------------------------- règles


def test_boolean_rule_writes_its_obs_id():
    """Une règle booléenne résolue dans le vif écrit son `obs_id` dans un slot du profil."""
    eng = _make_engine([
        _unit_cfg(1, 1, [(20, 20)],
                  rng_weapons=[_weapon(WEAPON_RULES=["DEVASTATING_WOUNDS"])]),
        _unit_cfg(2, 2, [(60, 20)]),
    ])
    assert _self_rules(eng, 0) == {"DEVASTATING_WOUNDS"}


def test_rule_ids_are_sorted_and_zero_padded():
    """Ensemble d'ids, pas de positions : trié croissant, paddé à 0 (contrat `_fill_id_slots`)."""
    eng = _make_engine([
        _unit_cfg(1, 1, [(20, 20)],
                  rng_weapons=[_weapon(WEAPON_RULES=["TORRENT", "LETHAL_HITS", "HEAVY"])]),
        _unit_cfg(2, 2, [(60, 20)]),
    ])
    obs = eng.obs_builder.build_squad_observation(eng.game_state, "1")
    row = [int(v) for v in obs["allies_wpn_rule_ids"][0][0]]
    assert len(row) == WEAPON_RULE_ID_SLOTS
    written = [v for v in row if v != 0]
    assert written == sorted(written)
    assert row[len(written):] == [0] * (WEAPON_RULE_ID_SLOTS - len(written))
    assert _rule_names(row) == {"TORRENT", "LETHAL_HITS", "HEAVY"}


def test_empty_profile_slot_writes_no_rule_id():
    """Un slot de profil vide n'écrit AUCUN id : le padding ne doit pas devenir une règle."""
    eng = _make_engine([
        _unit_cfg(1, 1, [(20, 20)]),
        _unit_cfg(2, 2, [(60, 20)]),
    ])
    assert _self_rules(eng, 1) == set()


def test_more_rules_than_slots_raises_never_truncates():
    """Débordement = ERREUR. Une règle tronquée serait subie sans être perçue (§0.30)."""
    too_many = [name for name in WEAPON_RULE_BITS[: WEAPON_RULE_ID_SLOTS + 1]]
    with pytest.raises(ValueError, match="regles d'arme"):
        _make_engine([
            _unit_cfg(1, 1, [(20, 20)], rng_weapons=[_weapon(WEAPON_RULES=too_many)]),
            _unit_cfg(2, 2, [(60, 20)]),
        ])


def test_every_observed_rule_has_a_unique_obs_id():
    """Le vocabulaire observé est ENTIÈREMENT couvert par le registre, sans collision."""
    registry = weapon_rule_obs_ids()
    assert set(registry) == set(WEAPON_RULE_OBS_VOCABULARY)
    assert len(set(registry.values())) == len(registry)


@pytest.mark.parametrize("rule_id,declared,expected", [
    ("RAPID_FIRE", "RAPID_FIRE:2", 2.0),
    ("SUSTAINED_HITS", "SUSTAINED_HITS:1", 1.0),
    ("MELTA", "MELTA:4", 4.0),
    ("BLAST", "BLAST", 1.0),        # forme NUE légale : 1 dé par tranche de 5 (24.05)
    ("BLAST", "BLAST:2", 2.0),
])
def test_parameterised_rule_exposes_its_value(rule_id, declared, expected):
    """Une règle paramétrée sort en VALEUR, pas en bit : [RAPID FIRE 2] ≠ [RAPID FIRE 1]."""
    eng = _make_engine([
        _unit_cfg(1, 1, [(20, 20)], rng_weapons=[_weapon(WEAPON_RULES=[declared])]),
        _unit_cfg(2, 2, [(60, 20)]),
    ])
    cont, _ = _self_profile(eng, 0)
    assert cont[_param_index(rule_id)] == pytest.approx(expected)


def test_anti_rule_exposes_threshold_and_target_keyword():
    """[ANTI-X Y+] 24.03 : le seuil SEUL est du bruit — le keyword ciblé est exposé aussi."""
    eng = _make_engine([
        _unit_cfg(1, 1, [(20, 20)], rng_weapons=[_weapon(WEAPON_RULES=["ANTI_VEHICLE:2"])]),
        _unit_cfg(2, 2, [(60, 20)]),
    ])
    cont, _ = _self_profile(eng, 0)
    assert cont[P_ANTI_Y] == pytest.approx(2.0)
    assert _self_rules(eng, 0) == {"ANTI_VEHICLE"}


def test_anti_rules_do_not_stack_best_threshold_wins():
    """24.02 : deux [ANTI] sur la même arme ne se cumulent pas — le MEILLEUR seuil est exposé."""
    eng = _make_engine([
        _unit_cfg(1, 1, [(20, 20)],
                  rng_weapons=[_weapon(WEAPON_RULES=["ANTI_INFANTRY:4", "ANTI_VEHICLE:2"])]),
        _unit_cfg(2, 2, [(60, 20)]),
    ])
    cont, _ = _self_profile(eng, 0)
    assert cont[P_ANTI_Y] == pytest.approx(2.0)
    # Une SEULE identité de règle [ANTI] est écrite : celle du meilleur seuil.
    assert _self_rules(eng, 0) == {"ANTI_VEHICLE"}


def test_indirect_fire_est_observee_depuis_qu_elle_est_vive():
    """[INDIRECT FIRE] 24.19 est OBSERVÉE depuis le 2026-08-16, et c'est l'exact inverse de ce
    que ce test verrouillait jusque-là (« deliberately absent »).

    Ce n'est pas un revirement : la règle avait un id **interdit** tant qu'elle n'avait aucun
    effet de jeu — un id pour une règle morte est du bruit que l'agent doit apprendre à ignorer.
    Elle en a un maintenant qu'elle est résolue, et surtout parce que 10.02 confie au joueur le
    choix du type de tir : **un type de tir qu'on ne perçoit pas est un type de tir qu'on ne
    joue jamais**. L'agent ne peut pas choisir l'indirect s'il ne voit pas quelles armes le lui
    ouvrent.

    Le pendant du test supprimé est conservé : le fait que l'ajout ne coûte AUCUN paramètre.
    C'est ce qui rend la décision réversible et bon marché, et c'est tout l'objet des slots d'id.
    """
    assert "INDIRECT_FIRE" in WEAPON_RULE_BITS
    # Règle SANS paramètre : elle n'a rien à dire sur la dimension continue.
    assert "INDIRECT_FIRE" not in {name for name, _ in WEAPON_RULE_PARAMS}
    assert weapon_rule_obs_ids()["INDIRECT_FIRE"] > 0


def test_donner_un_id_a_indirect_fire_ne_change_pas_la_taille_de_l_observation():
    """VERROU du coût annoncé : le vocabulaire d'ids est PRÉ-DIMENSIONNÉ, il ne s'ajuste pas au
    nombre de règles. Ajouter [INDIRECT FIRE] ne touche donc ni `obs_size` ni les poids — le
    ré-entraînement de ce chantier vient du CHOIX exposé à l'agent, pas de l'observation.

    Sans ce test, l'affirmation « l'obs_id est gratuit » resterait une phrase de documentation ;
    elle a déjà été écrite à l'envers une fois (2026-08-15), ce qui a failli faire renoncer à la
    règle pour un coût imaginaire.
    """
    from engine.observation_entities import OBS_ID_MAX, OBS_ID_VOCAB_SIZE

    assert OBS_ID_VOCAB_SIZE == OBS_ID_MAX + 1, (
        "le vocabulaire doit rester pré-dimensionné, jamais ajusté au nombre de règles"
    )
    assert max(weapon_rule_obs_ids().values()) <= OBS_ID_MAX, (
        "un id au-delà du vocabulaire ferait, LUI, grossir les tables d'embedding"
    )


def test_every_weapon_rule_with_obs_id_is_in_the_vocabulary():
    """Reciproque de `test_every_observed_rule_has_a_unique_obs_id` : tout obs_id declare dans
    `config/weapon_rules.json` appartient a `WEAPON_RULE_OBS_VOCABULARY`.

    `weapon_rule_obs_ids()` est deja filtre au vocabulaire — il ne peut pas detecter un obs_id
    orphelin (une regle qui le porte sans etre dans le vocabulaire). Ce test lit le registre BRUT
    et leve si une telle regle existe. Cout d'entree dans le vocabulaire : zero scalaire.

    Miroir exact de `test_every_registered_obs_id_is_in_the_vocabulary` pour `unit_rules.json`.
    """
    from config_loader import get_config_loader

    registry = get_config_loader().load_weapon_rules_config()
    with_obs_id = {rule_id for rule_id, entry in registry.items() if "obs_id" in entry}
    assert len(with_obs_id) >= len(WEAPON_RULE_OBS_VOCABULARY)
    orphelins = sorted(with_obs_id - set(WEAPON_RULE_OBS_VOCABULARY))
    # VERT VACANT : un registre sans aucun obs_id laisserait `orphelins` vide et cette
    # assertion passerait sans rien verifier — la garde `>=` ci-dessus l'empeche.
    assert not orphelins, (
        f"regles d'armes portant un obs_id sans etre observees : {orphelins} — "
        f"soit elles entrent dans WEAPON_RULE_OBS_VOCABULARY (cout : zero scalaire), "
        f"soit leur obs_id doit disparaitre de config/weapon_rules.json"
    )


# ---------------------------------------------------------------- ennemis


def test_enemy_slots_expose_the_same_profile_fields():
    """Symétrie : choisir une cible et jauger une menace exigent les mêmes données brutes."""
    eng = _make_engine([
        _unit_cfg(1, 1, [(20, 20)]),
        _unit_cfg(2, 2, [(60, 20), (61, 20)],
                  rng_weapons=[_weapon(display_name="Big Shoota", NB=3, STR=6, AP=-1,
                                       WEAPON_RULES=["TWIN_LINKED"])]),
    ])
    cont, binv = _enemy_profile(eng, 0, 0)
    obs = eng.obs_builder.build_squad_observation(eng.game_state, "1")
    assert cont[P_NB] == pytest.approx(3.0)
    assert cont[P_STR] == pytest.approx(6.0)
    assert cont[P_CARRIERS] == pytest.approx(2.0)
    assert _rule_names(obs["enemies_wpn_rule_ids"][0][0]) == {"TWIN_LINKED"}
    assert binv[B_MASK] == pytest.approx(1.0)


def test_empty_enemy_slot_carries_no_profile():
    """Slot ennemi vide -> profils à zéro, mask à 0 (padding identifiable)."""
    eng = _make_engine([
        _unit_cfg(1, 1, [(20, 20)]),
        _unit_cfg(2, 2, [(60, 20)]),
    ])
    cont, binv = _enemy_profile(eng, 4, 0)   # slot 4 : aucune escouade ennemie
    assert not any(cont)
    assert binv[B_MASK] == pytest.approx(0.0)


# ---------------------------------------------------------------- troncature


def test_profile_truncation_is_logged_never_silent():
    """Plus de profils que de slots -> le dépassement est TRACÉ (§11, pas de cap silencieux).

    Troncature RÉELLE : une escouade porteuse de K+2 profils de tir distincts, observée par le
    vrai chemin `build_squad_observation`. Contre-épreuve intégrée : la même escouade avec K
    profils exactement ne loggue RIEN.
    """
    k = ObservationBuilder.K_WEAPONS_RANGED

    def _log_of(n_profiles: int) -> List[str]:
        # n_profiles armes de tir toutes différentes, une par figurine.
        per_model = {i: [_weapon(display_name=f"W{i}", STR=3 + i)] for i in range(n_profiles)}
        eng = _make_engine([
            _unit_cfg(1, 1, [(20 + i, 20) for i in range(n_profiles)],
                      rng_weapons=[_weapon(display_name="W0", STR=3)],
                      per_model_rng=per_model),
            _unit_cfg(2, 2, [(60, 20)]),
        ])
        captured: List[str] = []
        with patch("engine.game_utils.add_debug_file_log",
                   side_effect=lambda gs, msg: captured.append(msg)):
            eng.obs_builder.build_squad_observation(eng.game_state, "1")
        return [m for m in captured if "profils RNG_WEAPONS" in m]

    over = _log_of(k + 2)
    assert over, "troncature du bloc profils NON loguee"
    assert "ne sont pas observes" in over[0]
    assert not _log_of(k), "log de troncature emis alors qu'aucun profil n'est tronque"


# ------------------------------------------------- exclusivité des profils COMBI


def _markers(engine: W40KEngine, key: str = "allies_wpn_rule_ids", row: int = 0) -> Dict[int, str]:
    """{slot de profil -> nom du marqueur combi}, pour les seuls slots qui en portent un."""
    obs = engine.obs_builder.build_squad_observation(engine.game_state, "1")
    by_id = {obs_id: name for name, obs_id in COMBI_GROUP_MARKER_OBS_IDS.items()}
    out: Dict[int, str] = {}
    for slot, ids_row in enumerate(obs[key][row]):
        found = [by_id[int(v)] for v in ids_row if int(v) in by_id]
        assert len(found) <= 1, f"slot {slot} porte {len(found)} marqueurs combi : {found}"
        if found:
            out[slot] = found[0]
    return out


def _combi(group: str, **over: Any) -> Dict[str, Any]:
    """Une arme de tir déclarant son groupe d'arme PHYSIQUE (`COMBI_WEAPON`)."""
    return _weapon(COMBI_WEAPON=group, **over)


def test_two_profiles_of_one_combi_weapon_share_the_same_marker():
    """Le défaut fermé : deux profils d'UNE arme physique se lisaient comme deux armes.

    Le moteur, lui, n'en joue qu'un par figurine (`_pick_one_profile_per_weapon_group`, renvoi
    « Multiple Weapon Profiles » de 04.01) — l'observation le dit maintenant, par un id commun
    aux deux slots.
    """
    eng = _make_engine([
        _unit_cfg(1, 1, [(20, 20)], rng_weapons=[
            _combi("plasma", display_name="Plasma (Standard)", STR=7),
            _combi("plasma", display_name="Plasma (Supercharge)", STR=8),
        ]),
        _unit_cfg(2, 2, [(60, 20)]),
    ])
    marks = _markers(eng)
    assert sorted(marks) == [0, 1], f"les deux slots de tir doivent être marqués : {marks}"
    assert marks[0] == marks[1], "deux profils de la MÊME arme physique doivent partager leur id"


def test_two_combi_groups_of_one_squad_get_distinct_markers():
    """Un bit « je suis exclusif » ne dirait pas AVEC QUI : deux groupes, deux ids."""
    eng = _make_engine([
        _unit_cfg(1, 1, [(20, 20), (21, 20)], rng_weapons=[
            _combi("plasma", display_name="Plasma (Standard)", STR=7),
            _combi("plasma", display_name="Plasma (Supercharge)", STR=8),
        ], per_model_rng={1: [
            _combi("missile", display_name="Missile (Frag)", NB=1, STR=4, DMG=1),
            _combi("missile", display_name="Missile (Krak)", NB=1, STR=9, DMG="D6"),
        ]}),
        _unit_cfg(2, 2, [(60, 20)]),
    ])
    marks = _markers(eng)
    assert len(marks) == 4, f"quatre profils exclusifs attendus : {marks}"
    assert len(set(marks.values())) == 2, f"deux groupes = deux marqueurs : {marks}"
    # Les slots d'un même marqueur sont exactement les deux profils du même groupe physique.
    obs = eng.obs_builder.build_squad_observation(eng.game_state, "1")
    for marker in set(marks.values()):
        slots = [s for s, m in marks.items() if m == marker]
        assert len(slots) == 2, f"{marker} porté par {len(slots)} slots"
        strengths = {float(obs["allies_wpn_cont"][0][s][P_STR]) for s in slots}
        assert strengths in ({7.0, 8.0}, {4.0, 9.0}), strengths


def test_two_independent_weapons_carry_no_marker():
    """LE CAS DISCRIMINANT : bolt_rifle + bolt_pistol tirent TOUS LES DEUX (04.01, « one or more
    ranged weapons that model has ») et se présentaient exactement comme un combi à deux profils.

    Sans marqueur, ces deux slots restent nus — c'est ce qui rend le marqueur informatif.
    """
    eng = _make_engine([
        _unit_cfg(1, 1, [(20, 20)], rng_weapons=[
            _weapon(display_name="Bolt Rifle", STR=4, RNG=24),
            _weapon(display_name="Bolt Pistol", STR=4, RNG=12),
        ]),
        _unit_cfg(2, 2, [(60, 20)]),
    ])
    assert _markers(eng) == {}


def test_a_combi_group_with_a_single_profile_is_not_marked():
    """Un groupe qui n'occupe qu'un slot n'exclut rien : lui donner un id serait du bruit."""
    eng = _make_engine([
        _unit_cfg(1, 1, [(20, 20)], rng_weapons=[
            _combi("plasma", display_name="Plasma (Standard)", STR=7),
            _weapon(display_name="Bolt Pistol", STR=4, RNG=12),
        ]),
        _unit_cfg(2, 2, [(60, 20)]),
    ])
    assert _markers(eng) == {}


def test_markers_do_not_collide_between_ranged_and_melee():
    """La numérotation est PAR ESCOUADE, registres confondus : un marqueur ne peut pas désigner
    une arme au tir et une autre en mêlée."""
    eng = _make_engine([
        _unit_cfg(1, 1, [(20, 20)], rng_weapons=[
            _combi("plasma", display_name="Plasma (Standard)", STR=7),
            _combi("plasma", display_name="Plasma (Supercharge)", STR=8),
        ], cc_weapons=[
            _melee(display_name="Fist (Strike)", COMBI_WEAPON="fist", STR=8),
            _melee(display_name="Fist (Sweep)", COMBI_WEAPON="fist", STR=5, NB=6),
        ]),
        _unit_cfg(2, 2, [(60, 20)]),
    ])
    marks = _markers(eng)
    ranged = {s: m for s, m in marks.items() if s < ObservationBuilder.K_WEAPONS_RANGED}
    melee = {s: m for s, m in marks.items() if s >= ObservationBuilder.K_WEAPONS_RANGED}
    assert len(ranged) == 2 and len(melee) == 2, marks
    assert set(ranged.values()).isdisjoint(set(melee.values())), (
        f"le même marqueur désigne deux armes physiques différentes : {marks}"
    )


def test_enemy_slots_expose_the_same_markers():
    """Symétrie §3.3 : jauger une menace exige de savoir que deux profils ennemis s'excluent."""
    eng = _make_engine([
        _unit_cfg(1, 1, [(20, 20)]),
        _unit_cfg(2, 2, [(60, 20)], rng_weapons=[
            _combi("plasma", display_name="Plasma (Standard)", STR=7),
            _combi("plasma", display_name="Plasma (Supercharge)", STR=8),
        ]),
    ])
    marks = _markers(eng, key="enemies_wpn_rule_ids")
    assert sorted(marks) == [0, 1] and marks[0] == marks[1], marks


def test_marker_is_stable_while_the_composition_does_not_change():
    """À composition constante, aucun profil ne change de marqueur d'un step à l'autre."""
    eng = _make_engine([
        _unit_cfg(1, 1, [(20, 20), (21, 20)], rng_weapons=[
            _combi("plasma", display_name="Plasma (Standard)", STR=7),
            _combi("plasma", display_name="Plasma (Supercharge)", STR=8),
        ]),
        _unit_cfg(2, 2, [(60, 20)]),
    ])
    first = _markers(eng)
    assert first, "VERT VACANT : aucun marqueur écrit, la stabilité ne vérifierait rien"
    assert _markers(eng) == first
    assert _markers(eng) == first


def test_marker_survives_a_loss_and_still_pairs_the_two_profiles():
    """Une perte change les porteurs (donc la clé de cache) : l'exclusivité doit rester dite."""
    from engine.phase_handlers.shared_utils import destroy_model

    eng = _make_engine([
        _unit_cfg(1, 1, [(20, 20), (21, 20)], rng_weapons=[
            _combi("plasma", display_name="Plasma (Standard)", STR=7),
            _combi("plasma", display_name="Plasma (Supercharge)", STR=8),
        ]),
        _unit_cfg(2, 2, [(60, 20)]),
    ])
    assert _self_profile(eng, 0)[0][P_CARRIERS] == pytest.approx(2.0)
    destroy_model(eng.game_state, "1#1", reason="combat")
    assert _self_profile(eng, 0)[0][P_CARRIERS] == pytest.approx(1.0)
    marks = _markers(eng)
    assert sorted(marks) == [0, 1] and marks[0] == marks[1], marks


def test_more_combi_groups_than_markers_raises_never_truncates():
    """Débordement de la plage réservée = ERREUR. Un marqueur silencieusement omis remettrait
    deux profils exclusifs sous l'apparence de deux armes indépendantes."""
    profiles = []
    for i in range(COMBI_GROUP_MARKER_COUNT + 1):
        for variant in (0, 1):
            profiles.append((_combi(f"g{i}", display_name=f"W{i}_{variant}", STR=4 + variant), 1))
    with pytest.raises(ValueError, match="groupes combi exclusifs"):
        assign_combi_group_markers(profiles, {})


def test_marker_ids_are_disjoint_from_weapon_rule_ids():
    """Les deux vocabulaires partagent les MÊMES slots : un id commun ferait lire une règle là
    où l'observation écrit une exclusivité de profils."""
    rules = weapon_rule_obs_ids()
    assert set(rules).isdisjoint(set(COMBI_GROUP_MARKER_OBS_IDS))
    assert set(rules.values()).isdisjoint(set(COMBI_GROUP_MARKER_OBS_IDS.values()))
    merged = weapon_profile_obs_ids()
    assert len(set(merged.values())) == len(merged) == len(rules) + COMBI_GROUP_MARKER_COUNT
    assert set(COMBI_GROUP_MARKER_NAMES) <= set(merged)


def test_combi_markers_cost_no_observation_scalar():
    """VERROU du coût annoncé : le marqueur se pose dans les slots d'ids DÉJÀ réservés, et le
    vocabulaire d'embedding est pré-dimensionné. `obs_size` ne bouge pas — donc aucun retrain
    n'est imposé par la FORME de l'observation.

    18269 est la valeur acquittée par `test_deployment_observation_contract`
    (`_ACKNOWLEDGED_OBS_SIZE`) : ce test la reprend ici pour que le chantier des marqueurs ait
    son propre verrou, au même endroit que le code qu'il ajoute.
    """
    from engine.observation_entities import OBS_ID_MAX, OBS_ID_VOCAB_SIZE

    assert ObservationBuilder.SQUAD_OBS_SIZE_TARGET == 18269
    assert OBS_ID_VOCAB_SIZE == OBS_ID_MAX + 1
    assert max(COMBI_GROUP_MARKER_OBS_IDS.values()) <= OBS_ID_MAX, (
        "un marqueur au-delà du vocabulaire ferait, LUI, grossir les tables d'embedding"
    )


def test_a_combi_group_split_by_truncation_leaves_no_orphan_marker():
    """Un marqueur dont le PARTENAIRE est tronqué n'est pas émis.

    L'ordre de `collect_weapon_profiles` est celui des porteurs décroissants : il ne garde pas
    ensemble les deux profils d'une même arme physique, donc la troncature peut couper un groupe
    en deux. Le slot survivant affirmait alors « je suis exclusif » avec un partenaire absent de
    l'observation — un groupe à profil unique déguisé, que
    `test_a_combi_group_with_a_single_profile_is_not_marked` interdit par ailleurs.

    Contre-épreuve intégrée : la MÊME escouade, MÊME troncature, mais le second profil du groupe
    porté par assez de figurines pour rester dans les slots — les deux sont marqués. Sans elle,
    une escouade muette pour une autre raison rendrait le cas tronqué vert pour rien.
    """
    k = ObservationBuilder.K_WEAPONS_RANGED
    std = _combi("plasma", display_name="Plasma (Standard)", STR=7)
    sup = _combi("plasma", display_name="Plasma (Supercharge)", STR=8)

    def _marks_with(sup_carriers: int) -> Dict[int, str]:
        # Porteurs DÉCROISSANTS et strictement séparés : le tri ne dépend que d'eux, jamais de
        # l'ordre d'identité. `std` (3 porteurs) prend le slot 0 ; les k profils fillers en ont
        # 2 chacun ; `sup` en a `sup_carriers`, ce qui décide seul de sa place.
        per_model: Dict[int, List[Dict[str, Any]]] = {}
        for _ in range(3):
            per_model[len(per_model)] = [std]
        for i in range(k):
            for _ in range(2):
                per_model[len(per_model)] = [_weapon(display_name=f"F{i}", STR=3, AP=-i)]
        for _ in range(sup_carriers):
            per_model[len(per_model)] = [sup]
        eng = _make_engine([
            _unit_cfg(1, 1, [(20 + i, 20) for i in range(len(per_model))],
                      rng_weapons=[std], per_model_rng=per_model),
            _unit_cfg(2, 2, [(60, 20)]),
        ])
        captured: List[str] = []
        with patch("engine.game_utils.add_debug_file_log",
                   side_effect=lambda gs, msg: captured.append(msg)):
            marks = _markers(eng)
        assert [m for m in captured if "profils RNG_WEAPONS" in m], (
            "fixture SANS troncature : le cas testé ne serait pas mis en scène"
        )
        return marks

    paired = _marks_with(3)
    assert sorted(paired) == [0, 1] and paired[0] == paired[1], (
        f"contre-épreuve : les deux profils du groupe sont observés, ils doivent partager un "
        f"marqueur — obtenu {paired}"
    )
    orphan = _marks_with(1)
    assert orphan == {}, (
        f"marqueur orphelin émis : {orphan} — son partenaire est tronqué, donc rien dans "
        "l'observation ne dit avec QUI ce slot est exclusif"
    )
