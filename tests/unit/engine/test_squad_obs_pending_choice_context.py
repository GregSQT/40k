"""Verrou : l'observation porte le CONTEXTE des points d'arrêt joueur à DEUX temps.

Deux mécanismes demandent à l'agent un choix dont la moitié est DÉJÀ fixée :

- sélection d'arme CC (V11 §0.69) — la cible est désignée, l'arme reste à choisir ;
- tir fractionné (P3-8), sous-état CIBLE — l'arme est armée, la cible reste à choisir.

S'y ajoute ce que le tir fractionné a DÉJÀ décidé : les couples arme -> cible de l'activation
en cours (`split_assigned_w0..9`, un bit par slot de profil de tir). Ils existent dans les DEUX
sous-états et ne changent l'état d'aucune cible, la résolution n'ayant lieu qu'une fois toutes
les armes assignées — mesuré le 2026-09-09 : ces bits mis à 0, deux états ne différant que par
la cible déjà assignée rendent des observations IDENTIQUES sur les 28 clés.

Trou fermé ici, MESURÉ le 2026-09-09 avant correction : dans les deux cas, deux états ne
différant que par la moitié déjà fixée produisaient des observations STRICTEMENT IDENTIQUES
(28 clés comparées, écart maximal 0,0). L'observation n'encodait qu'un seul des sept points
d'arrêt du registre `PLAYER_CHOICE_MECHANISMS` — la décision d'agent. La politique n'est pas
récurrente (`MaskablePPO`) : elle ne se souvient pas de l'action jouée au step précédent, donc
l'arme se choisissait sans voir la cible et la cible sans voir l'arme.

Les deux drapeaux (`fight_target_selected` sur l'entité, `shoot_weapon_selected` sur le profil
d'arme) sont AUTO-PORTEURS : aucun bit de contexte global ne les accompagne, parce que personne
ne les porte hors de leur point d'arrêt — ce que vérifient
`test_no_enemy_carries_the_fight_bit_outside_the_stop` et son jumeau côté armes.

Les deux volets passent par le CHEMIN DE PRODUCTION (`_process_squad_action` puis
`_build_observation_and_mask`), et non par un `game_state` monté à la main : c'est le seul moyen
de prouver que l'observation que l'agent reçoit vraiment — celle dont l'observateur est choisi
par `pending_choice_observer_squad_id` — porte le contexte.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import patch

import numpy as np
import pytest

from engine.observation_builder import ObservationBuilder
from engine.observation_entities import (
    K_WEAPONS_RANGED,
    UNIT_BIN_FIELDS,
    split_assigned_field,
    unit_bin_index,
)
from engine.observation_weapon_profiles import profile_bin_index
from engine.w40k_core import W40KEngine
from tests.unit.engine._config_helpers import build_engine_config

BIN_FIGHT_TARGET = unit_bin_index("fight_target_selected")
BIN_PRESENT = unit_bin_index("present")
PROFILE_SELECTED = profile_bin_index("shoot_weapon_selected")
PROFILE_PRESENT = profile_bin_index("present")


def _weapon_cfg(code: str, rng: int, strength: int) -> Dict[str, Any]:
    return {
        "ATK": 2, "STR": strength, "AP": 0, "DMG": 1, "NB": 1, "RNG": rng,
        "WEAPON_RULES": [], "code": code, "display_name": code,
    }


def _unit_cfg(
    uid: int,
    player: int,
    positions: List[Tuple[int, int]],
    *,
    ranged: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Escouade de test. `ranged` : une arme de tir par figurine (profils DISTINCTS)."""
    specs: List[Dict[str, Any]] = []
    for idx, (col, row) in enumerate(positions):
        spec: Dict[str, Any] = {"col": col, "row": row, "HP_CUR": 1, "HP_MAX": 1, "VALUE": 10}
        if ranged is not None:
            spec["RNG_WEAPONS"] = [ranged[idx]]
        specs.append(spec)
    rng_weapons = ranged if ranged is not None else [_weapon_cfg("test_bolter", 24, 4)]
    return {
        "id": uid, "player": player, "col": positions[0][0], "row": positions[0][1],
        "unitType": "TestUnit", "DISPLAY_NAME": f"Unit {uid}",
        "HP_CUR": len(specs), "HP_MAX": 1, "MOVE": 6, "T": 4,
        "ARMOR_SAVE": 4, "INVUL_SAVE": 0,
        "RNG_WEAPONS": rng_weapons,
        "CC_WEAPONS": [_weapon_cfg("test_blade", 0, 4)],
        "UNIT_RULES": [], "UNIT_KEYWORDS": [{"keywordId": "INFANTRY"}],
        "LD": 7, "OC": 2, "VALUE": 10 * len(specs),
        "ICON": "test", "ICON_SCALE": 1.0, "ILLUSTRATION_RATIO": 1.0,
        "BASE_SHAPE": "round", "BASE_SIZE": 1, "MODEL_HEIGHT": 2.5,
        "models": specs,
    }


def _config(units: List[Dict[str, Any]]) -> Dict[str, Any]:
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
        "units": units,
    }


def _make_engine(units: List[Dict[str, Any]]) -> W40KEngine:
    with patch("engine.w40k_core.load_weapon_damage_table", return_value={}), \
         patch.object(W40KEngine, "_build_reward_configs_for_current_units", return_value={}):
        eng = W40KEngine(config=build_engine_config(_config(units)))
    eng.reset()
    return eng


def _enemy_slot_of(engine: W40KEngine, observer: str, target_id: str) -> int:
    from engine.phase_handlers.shared_utils import get_enemy_slot_mapping

    gs = engine.game_state
    our_player = int(gs["units_cache"][observer]["player"])
    mapping = get_enemy_slot_mapping(gs, our_player)
    slot = mapping.index(target_id)
    return int(slot)


def _obs_copy(engine: W40KEngine) -> Dict[str, np.ndarray]:
    """Observation du CHEMIN DE PRODUCTION, copiée (le builder rend un scratch réutilisé)."""
    obs, _mask = engine._build_observation_and_mask()
    assert obs is not None, "aucune observation construite"
    return {key: np.array(value, copy=True) for key, value in obs.items()}


# ── Volet mêlée : la cible désignée pendant la sélection d'arme CC ────────────


def _melee_engine() -> W40KEngine:
    """Escouade 1 au contact de DEUX ennemis frappables (2 et 3)."""
    eng = _make_engine([
        _unit_cfg(1, 1, [(30, 20), (32, 20)]),
        _unit_cfg(2, 2, [(31, 20)]),
        _unit_cfg(3, 2, [(33, 20)]),
    ])
    gs = eng.game_state
    gs["phase"] = "fight"
    gs["current_player"] = 1
    gs["units_fought"] = set()
    # Chemin squad (`_process_squad_action`, driver `_fight_v11_gym_settle`) = sièges
    # PROGRAMMATIQUES : avec des sièges humains, le driver rend la main au premier groupe
    # sans rien dérouler et `squad_fight` n'a pas d'étape FIGHT à sélectionner.
    gs["player_types"] = {"1": "ai", "2": "ai"}

    from engine.phase_handlers import fight_handlers

    result = fight_handlers.fight_phase_start(gs)
    eng._fight_v11_gym_after_phase_start(result)
    return eng


def _arm_fight_weapon_select(engine: W40KEngine, target_id: str) -> None:
    """Joue le VRAI `squad_fight` sur `target_id` — c'est lui qui arme le point d'arrêt."""
    from engine.action_decoder import PENDING_FIGHT_WEAPON_KEY

    slot = _enemy_slot_of(engine, "1", target_id)
    ok, result = engine._process_squad_action(
        {"action": "squad_fight", "squad_id": "1", "target_slot": slot}
    )
    assert ok is True, f"squad_fight refusé : {result!r}"
    assert result.get("waiting_for_weapon_select") is True, (
        f"le point d'arrêt de sélection d'arme n'est pas armé : {result!r}"
    )
    pending = engine.game_state[PENDING_FIGHT_WEAPON_KEY]
    assert str(pending["target_id"]) == target_id


def test_fight_weapon_select_marks_the_designated_target():
    """Le bit tombe sur le slot ennemi de la cible désignée, et sur lui seul."""
    for target_id in ("2", "3"):
        eng = _melee_engine()
        _arm_fight_weapon_select(eng, target_id)
        obs = _obs_copy(eng)

        marked = [
            slot for slot in range(ObservationBuilder.K_ENEMY_SLOTS)
            if float(obs["enemies_bin"][slot][BIN_FIGHT_TARGET]) == 1.0
        ]
        assert marked == [_enemy_slot_of(eng, "1", target_id)], (
            f"cible {target_id} : slots marqués {marked}"
        )


def test_two_targets_no_longer_give_the_same_observation():
    """LE défaut mesuré : deux cibles, même observation au moment du choix d'arme.

    Contre-épreuve directe du bug — sans le drapeau, les deux passes rendent des tenseurs
    identiques clé par clé, et l'agent choisit son arme sans savoir contre qui il frappe.
    """
    obs_by_target = {}
    for target_id in ("2", "3"):
        eng = _melee_engine()
        _arm_fight_weapon_select(eng, target_id)
        obs_by_target[target_id] = _obs_copy(eng)

    differing = [
        key for key in obs_by_target["2"]
        if not np.array_equal(obs_by_target["2"][key], obs_by_target["3"][key])
    ]
    assert differing == ["enemies_bin"], (
        f"clés distinguant les deux cibles : {differing} (attendu : enemies_bin seule)"
    )


def test_no_enemy_carries_the_fight_bit_outside_the_stop():
    """Hors point d'arrêt, aucune entité ne porte le bit — c'est ce qui le rend auto-porteur."""
    eng = _melee_engine()
    obs = _obs_copy(eng)
    assert not obs["enemies_bin"][:, BIN_FIGHT_TARGET].any()
    assert not obs["allies_bin"][:, BIN_FIGHT_TARGET].any()


def test_the_bit_is_not_written_in_another_squad_observation():
    """L'observation d'une AUTRE escouade ne désigne personne : la cible n'y a pas de référent."""
    eng = _melee_engine()
    _arm_fight_weapon_select(eng, "2")
    obs = eng.obs_builder.build_squad_observation(eng.game_state, "3")
    assert not obs["enemies_bin"][:, BIN_FIGHT_TARGET].any()


def test_target_outside_the_enemy_slots_raises():
    """Cible du pending absente des slots ennemis -> erreur explicite, jamais un bit muet."""
    from engine.action_decoder import PENDING_FIGHT_WEAPON_KEY

    eng = _melee_engine()
    _arm_fight_weapon_select(eng, "2")
    eng.game_state[PENDING_FIGHT_WEAPON_KEY]["target_id"] = "999"

    with pytest.raises(RuntimeError, match="absente des .* slots ennemis"):
        eng.obs_builder.build_squad_observation(eng.game_state, "1")


# ── Volet tir : l'arme armée pendant le sous-état CIBLE du split-fire ─────────


def _split_fire_engine(*, third_weapon: bool = False, ally_squad: bool = False) -> W40KEngine:
    """Escouade 1 avec DEUX profils de tir distincts (trois sur demande), deux ennemis à portée.

    `third_weapon` : une arme de plus, donc une assignation de plus AVANT la résolution — le seul
    moyen d'observer une activation qui a déjà assigné deux armes.

    `ally_squad` : une SECONDE escouade du joueur 1. Elle seule met la garde d'observateur à
    l'épreuve : ses slots ennemis contiennent « 2 » et « 3 », donc un bit fuiterait chez elle si
    la garde tombait. Observer une escouade du camp d'en face ne prouve rien — les cibles du
    split-fire n'y figurent pas du tout.
    """
    positions = [(30, 20), (31, 20)]
    weapons = [_weapon_cfg("test_bolter", 24, 4), _weapon_cfg("test_melta", 12, 9)]
    if third_weapon:
        positions.append((32, 20))
        weapons.append(_weapon_cfg("test_plasma", 18, 7))
    units = [
        _unit_cfg(1, 1, positions, ranged=weapons),
        _unit_cfg(2, 2, [(30, 28)]),
        _unit_cfg(3, 2, [(33, 28)]),
    ]
    if ally_squad:
        units.append(_unit_cfg(4, 1, [(20, 20)], ranged=weapons))
    eng = _make_engine(units)
    gs = eng.game_state
    gs["phase"] = "shoot"
    gs["current_player"] = 1
    gs["units_shot"] = set()
    gs["shoot_activation_pool"] = ["1"]
    return eng


def _arm_shoot_weapon(engine: W40KEngine, weapon_slot: int) -> str:
    """Joue le VRAI `squad_shoot_weapon_sel` : l'arme est armée, la cible reste à choisir."""
    ok, result = engine._process_squad_action(
        {"action": "squad_shoot_weapon_sel", "squad_id": "1", "weapon_slot": weapon_slot}
    )
    assert ok is True, f"squad_shoot_weapon_sel refusé : {result!r}"
    assert result.get("waiting_for_target_select") is True, (
        f"le sous-état CIBLE n'est pas armé : {result!r}"
    )
    return str(result["weapon_code"])


def test_split_fire_marks_the_armed_weapon_profile():
    """Le drapeau tombe sur le profil de l'arme armée, et sur lui seul."""
    for weapon_slot in (0, 1):
        eng = _split_fire_engine()
        _arm_shoot_weapon(eng, weapon_slot)
        obs = _obs_copy(eng)

        marked = [
            slot for slot in range(ObservationBuilder.K_WEAPONS)
            if float(obs["allies_wpn_bin"][0][slot][PROFILE_SELECTED]) == 1.0
        ]
        assert marked == [weapon_slot], f"arme {weapon_slot} : profils marqués {marked}"
        assert float(obs["allies_wpn_bin"][0][weapon_slot][PROFILE_PRESENT]) == 1.0


def test_two_armed_weapons_no_longer_give_the_same_observation():
    """Jumeau tir du défaut mesuré : deux armes armées, même observation au choix de cible."""
    obs_by_slot = {}
    for weapon_slot in (0, 1):
        eng = _split_fire_engine()
        _arm_shoot_weapon(eng, weapon_slot)
        obs_by_slot[weapon_slot] = _obs_copy(eng)

    differing = [
        key for key in obs_by_slot[0]
        if not np.array_equal(obs_by_slot[0][key], obs_by_slot[1][key])
    ]
    assert "allies_wpn_bin" in differing, (
        f"l'arme armée ne distingue pas les deux observations (clés : {differing})"
    )


def test_no_profile_carries_the_weapon_bit_outside_the_stop():
    """Hors sous-état CIBLE, aucun profil n'est marqué — ni chez moi ni en face."""
    eng = _split_fire_engine()
    obs = _obs_copy(eng)
    assert not obs["allies_wpn_bin"][..., PROFILE_SELECTED].any()
    assert not obs["enemies_wpn_bin"][..., PROFILE_SELECTED].any()


def test_the_weapon_bit_never_enters_the_profile_cache():
    """Le drapeau suit le point d'arrêt, pas la composition : le cache de profils l'ignore.

    Contre-épreuve du piège d'implémentation : les profils d'armes sont mis en cache par
    (escouade, figurines vivantes). Écrit dans ce cache, le drapeau resterait allumé après la
    fin du point d'arrêt, sur une escouade dont plus rien n'attend de cible.
    """
    from engine.action_decoder import PENDING_SHOOT_WEAPON_SEL_KEY

    eng = _split_fire_engine()
    _arm_shoot_weapon(eng, 1)
    assert _obs_copy(eng)["allies_wpn_bin"][0][1][PROFILE_SELECTED] == 1.0

    del eng.game_state[PENDING_SHOOT_WEAPON_SEL_KEY]
    assert not _obs_copy(eng)["allies_wpn_bin"][..., PROFILE_SELECTED].any()


def test_armed_weapon_slot_without_profile_raises():
    """Slot armé sans profil -> erreur explicite : l'obs décrirait une autre arme que le commit."""
    from engine.action_decoder import PENDING_SHOOT_WEAPON_SEL_KEY

    eng = _split_fire_engine()
    _arm_shoot_weapon(eng, 0)
    eng.game_state[PENDING_SHOOT_WEAPON_SEL_KEY]["pending_weapon_slot"] = 9

    with pytest.raises(RuntimeError, match="ne porte aucun profil"):
        eng.obs_builder.build_squad_observation(eng.game_state, "1")


# ── Volet tir, 2e temps : les couples arme→cible DÉJÀ commités ────────────────
#
# Le volet ci-dessus ne couvrait que la PREMIÈRE arme du split-fire, quand `assignments` est
# encore vide. Trou mesuré le 2026-09-09 une fois un premier couple commité : deux états ne
# différant que par la cible déjà assignée rendaient des observations identiques (0 clé sur 28),
# et aux DEUX sous-états. 04.02 demande toutes les cibles avant la moindre résolution et 04.03
# cumule les dés des armes faisant des attaques identiques sur une même cible : l'agent choisit
# donc son 2e couple sans voir ce que le 1er a déjà engagé.


def _assign_target(engine: W40KEngine, target_id: str) -> None:
    """Joue le VRAI `squad_shoot_split_target` : le couple arme→cible est commité."""
    slot = _enemy_slot_of(engine, "1", target_id)
    ok, result = engine._process_squad_action(
        {"action": "squad_shoot_split_target", "squad_id": "1", "target_slot": slot}
    )
    assert ok is True, f"squad_shoot_split_target refusé : {result!r}"
    assert result.get("waiting_for_next_weapon_sel") is True, (
        f"le split-fire ne rend pas la main pour l'arme suivante : {result!r}"
    )


def _bits_of(obs: Dict[str, np.ndarray], slot: int) -> List[int]:
    """Slots d'armes marqués `split_assigned_w<i>` sur la ligne ennemie `slot`."""
    return [
        widx for widx in range(ObservationBuilder.K_WEAPONS_RANGED)
        if float(obs["enemies_bin"][slot][unit_bin_index(split_assigned_field(widx))]) == 1.0
    ]


def test_split_assigned_bits_cover_every_ranged_slot():
    """Clôture de la liste : un bit par slot de profil de tir, ni plus ni moins.

    Les noms sont littéraux dans `UNIT_BIN_FIELDS` (la cardinalité est définie plus bas dans ce
    module-là). Sans ce verrou, changer `K_WEAPONS_RANGED` laisserait des slots d'armes sans bit
    — donc des assignations muettes — sans qu'aucun test ne tombe.
    """
    declared = [f for f in UNIT_BIN_FIELDS if f.startswith("split_assigned_w")]
    assert declared == [split_assigned_field(i) for i in range(K_WEAPONS_RANGED)]
    assert UNIT_BIN_FIELDS[-1] == "present", "le masque d'entité doit rester le DERNIER champ"


def test_assigned_weapon_lands_on_its_target_row_only():
    """Le bit du slot d'arme assigné tombe sur la ligne de SA cible, et sur elle seule."""
    for weapon_slot in (0, 1):
        for target_id in ("2", "3"):
            eng = _split_fire_engine()
            _arm_shoot_weapon(eng, weapon_slot)
            _assign_target(eng, target_id)
            obs = _obs_copy(eng)

            marked = {
                slot: _bits_of(obs, slot)
                for slot in range(ObservationBuilder.K_ENEMY_SLOTS)
                if _bits_of(obs, slot)
            }
            assert marked == {_enemy_slot_of(eng, "1", target_id): [weapon_slot]}, (
                f"arme {weapon_slot} -> cible {target_id} : marquage {marked}"
            )


def test_the_second_choice_no_longer_sees_the_same_observation():
    """LE défaut mesuré : après un 1er couple commité, la cible déjà prise était invisible.

    Contre-épreuve aux DEUX sous-états — celui qui demande l'arme suivante ET celui qui demande
    sa cible. Sans les bits, les deux passes rendent des tenseurs identiques clé par clé.
    """
    obs_weapon_stop: Dict[str, Dict[str, np.ndarray]] = {}
    obs_target_stop: Dict[str, Dict[str, np.ndarray]] = {}
    for first_target in ("2", "3"):
        eng = _split_fire_engine()
        _arm_shoot_weapon(eng, 0)
        _assign_target(eng, first_target)
        obs_weapon_stop[first_target] = _obs_copy(eng)   # sous-état ARME
        _arm_shoot_weapon(eng, 1)
        obs_target_stop[first_target] = _obs_copy(eng)   # sous-état CIBLE

    for label, obs_by_target in (("ARME", obs_weapon_stop), ("CIBLE", obs_target_stop)):
        differing = [
            key for key in obs_by_target["2"]
            if not np.array_equal(obs_by_target["2"][key], obs_by_target["3"][key])
        ]
        assert differing == ["enemies_bin"], (
            f"sous-état {label} : clés distinguant les deux cibles déjà assignées {differing} "
            f"(attendu : enemies_bin seule)"
        )


def test_no_enemy_carries_a_split_bit_outside_split_fire():
    """Hors split-fire, aucune entité ne porte ces bits — ce qui les rend auto-porteurs."""
    eng = _split_fire_engine()
    obs = _obs_copy(eng)
    for widx in range(ObservationBuilder.K_WEAPONS_RANGED):
        idx = unit_bin_index(split_assigned_field(widx))
        assert not obs["enemies_bin"][:, idx].any(), f"slot {widx} marqué hors split-fire"
        assert not obs["allies_bin"][:, idx].any(), f"slot {widx} marqué sur une alliée"


def test_split_bits_are_absent_from_an_allied_squad_observation():
    """L'observation d'une AUTRE escouade ne désigne personne : le split-fire n'est pas le sien.

    L'observatrice est une ALLIÉE de la tireuse, et c'est la seule version portante du test : chez
    une escouade du camp d'en face, les cibles du split-fire ne figurent pas dans les slots
    ennemis, si bien que l'assertion passerait même sans garde d'observateur. La précondition
    ci-dessous refuse ce vert vacant.
    """
    eng = _split_fire_engine(ally_squad=True)
    _arm_shoot_weapon(eng, 0)
    _assign_target(eng, "2")
    obs = eng.obs_builder.build_squad_observation(eng.game_state, "4")

    target_slot = _enemy_slot_of(eng, "4", "2")
    assert float(obs["enemies_bin"][target_slot][BIN_PRESENT]) == 1.0, (
        "précondition : la cible assignée doit occuper un slot ennemi de l'observatrice, sinon "
        "l'assertion suivante ne prouve rien"
    )
    for widx in range(ObservationBuilder.K_WEAPONS_RANGED):
        idx = unit_bin_index(split_assigned_field(widx))
        assert not obs["enemies_bin"][:, idx].any(), f"slot {widx} marqué chez une autre escouade"


def test_assigned_weapon_slot_out_of_range_raises():
    """Slot assigné hors du bloc d'armes -> erreur explicite, jamais un bit posé ailleurs."""
    from engine.action_decoder import PENDING_SHOOT_WEAPON_SEL_KEY

    eng = _split_fire_engine()
    code = _arm_shoot_weapon(eng, 0)
    _assign_target(eng, "2")
    eng.game_state[PENDING_SHOOT_WEAPON_SEL_KEY]["assignments"][code]["weapon_slot"] = 10

    with pytest.raises(RuntimeError, match="hors des .* slots de profils de tir"):
        eng.obs_builder.build_squad_observation(eng.game_state, "1")


def test_two_weapons_on_the_same_target_mark_two_bits():
    """Deux armes sur la MÊME cible -> DEUX bits sur sa ligne : c'est le sur-tir rendu visible.

    Un bit unique « déjà visée » aurait rendu la même valeur qu'avec une seule arme, et l'agent
    aurait continué d'empiler. Trois profils sont nécessaires : à la DERNIÈRE assignation, le
    moteur résout l'activation et l'état disparaît — il n'y a alors plus de choix à éclairer.
    """
    eng = _split_fire_engine(third_weapon=True)
    _arm_shoot_weapon(eng, 0)
    _assign_target(eng, "2")
    _arm_shoot_weapon(eng, 1)
    _assign_target(eng, "2")
    obs = _obs_copy(eng)

    target_slot = _enemy_slot_of(eng, "1", "2")
    assert float(obs["enemies_bin"][target_slot][BIN_PRESENT]) == 1.0
    assert _bits_of(obs, target_slot) == [0, 1], "les deux armes assignées doivent être lisibles"
    assert _bits_of(obs, _enemy_slot_of(eng, "1", "3")) == []
