"""Verrou : l'observation squad expose les REGLES D'UNITE, amies comme ennemies.

Trou ferme ici (constat verifie le 2026-07-27). Les regles d'armes etaient devenues visibles
(V11 §9.2.5), pas celles d'unite : `UNIT_CONT_FIELDS`/`UNIT_BIN_FIELDS` n'avaient aucun champ
de regle, et `unit_has_rule_effect` n'apparaissait qu'a UN endroit de tout l'encodage —
`_encode_rule_features`, appelee uniquement par `build_observation`, le pipeline mono-figurine
LEGACY. Le routage envoie le pipeline squad sur `build_squad_observation`, qui n'y passe jamais.
L'agent subissait donc `reroll_charge`, `closest_target_penetration`, `move_after_shooting`…
sans les percevoir, exactement le constat qui avait motive la tranche des regles d'armes.

Ce que ces tests verrouillent :
  - les bits decrivent les EFFETS, donc captent aussi les capacites composites des datasheets
    (`cunning_hunters`, `targeted_intercession`, `target_priority`…) ;
  - ils valent pour les entites ENNEMIES (choix de cible et evaluation de menace) ;
  - **19.04** : une escouade menee par un character porte les regles de son leader, et le bit
    S'ETEINT a sa mort — c'est le point qui rendait ce trou couteux depuis la tranche 19.04 ;
  - les marqueurs de ROLE ne sont pas dupliques (le bloc TYPES les porte deja) ;
  - une regle sans effet n'a pas de bit (meme critere que [INDIRECT FIRE] cote armes).
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List

import numpy as np

from ai.unit_registry import UnitRegistry
from engine.observation_builder import ObservationBuilder
from engine.observation_entities import UNIT_RULE_EFFECT_IDS, unit_bin_index
from engine.w40k_core import W40KEngine

PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
TEMPLATE = os.path.join(
    PROJECT_ROOT,
    "config/agents/ArmageddonAgent/scenarios/training/scenario_training_armageddon.json",
)

# Memes fixtures que test_attached_units_abilities_19_04 : `AssaultIntercessor` porte
# `targeted_intercession` et PAS `reroll_charge` ; `CaptainPowerWeaponBolter` l'inverse.
_BODYGUARD = {
    "id": 101, "unit_type": "AssaultIntercessor", "player": 2, "col": 12, "row": 10,
    "models": [{"col": 12, "row": 10}, {"col": 13, "row": 10}, {"col": 14, "row": 10}],
}
_LEADER = {
    "id": 102, "unit_type": "CaptainPowerWeaponBolter", "player": 2,
    "attached_squad": 101, "col": 15, "row": 10,
}
_ENEMY = {"id": 1, "unit_type": "Intercessor", "player": 1, "col": 3, "row": 3}


def _load(units: List[Dict[str, Any]]) -> W40KEngine:
    scenario = {
        "board_ref": "44x60x5",
        "primary_objectives": ["objectives_control"],
        "wall_ref": "walls-none.json",
        "units": units,
    }
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "rules_obs.json"
        path.write_text(json.dumps(scenario))
        eng = W40KEngine(
            rewards_config="ArmageddonAgent", training_config_name="x1_debug",
            controlled_agent="ArmageddonAgent", scenario_file=str(path),
            unit_registry=UnitRegistry(), quiet=True, gym_training_mode=True,
        )
        eng.reset(seed=0)
        return eng


def _rule_bits(obs, family: str, row: int) -> set:
    """Regles allumees sur un slot d'entite."""
    b = obs[f"{family}_bin"][row]
    return {r for r in UNIT_RULE_EFFECT_IDS if b[unit_bin_index(f"rule_{r}")] == 1.0}


def test_active_squad_rules_are_observed():
    """L'escouade observee expose ses propres regles (ligne 0 du bloc amis)."""
    eng = _load([_BODYGUARD, _ENEMY])
    obs = eng.obs_builder.build_squad_observation(eng.game_state, "101")
    # `targeted_intercession` se resout en DEUX effets — ce sont les effets qui sont exposes.
    assert _rule_bits(obs, "allies", 0) == {
        "reroll_1_towound", "reroll_towound_target_on_objective"
    }


def test_enemy_squad_rules_are_observed():
    """Les regles de l'ENNEMI sont visibles : elles portent la menace autant que ses armes."""
    eng = _load([_BODYGUARD, _ENEMY])
    obs = eng.obs_builder.build_squad_observation(eng.game_state, "1")
    slot = next(
        i for i in range(ObservationBuilder.K_ENEMY_SLOTS)
        if obs["enemies_bin"][i][unit_bin_index("present")] == 1.0
    )
    assert _rule_bits(obs, "enemies", slot) == {
        "reroll_1_towound", "reroll_towound_target_on_objective"
    }


def test_attached_leader_rule_is_observed_then_extinguished_on_his_death():
    """19.04 dans l'observation : le bit du leader apparait, puis DISPARAIT a sa mort.

    Le cas qui rendait ce trou couteux : depuis 19.04 l'union en vigueur change en cours de
    partie, et l'agent n'en voyait rien.
    """
    from engine.phase_handlers.shared_utils import destroy_model

    eng = _load([_BODYGUARD, _LEADER, _ENEMY])
    before = _rule_bits(eng.obs_builder.build_squad_observation(eng.game_state, "101"), "allies", 0)
    assert "reroll_charge" in before, "regle du Captain attache invisible"

    leader_mid = next(
        mid for mid in eng.game_state["squad_models"]["101"]
        if "attached_from" in eng.game_state["models_cache"][mid]
    )
    destroy_model(eng.game_state, leader_mid, "combat")

    after = _rule_bits(eng.obs_builder.build_squad_observation(eng.game_state, "101"), "allies", 0)
    assert "reroll_charge" not in after, "regle du leader mort toujours observee"
    assert "reroll_1_towound" in after, "l'escouade a perdu ses propres regles au passage"


def test_role_markers_are_not_duplicated_as_rule_bits():
    """`leader`/`sergeant`/`support`/`special_weapon` restent au bloc TYPES, pas ici."""
    for marker in ("leader", "sergeant", "support", "special_weapon"):
        assert marker not in UNIT_RULE_EFFECT_IDS
        assert f"rule_{marker}" not in [f"rule_{r}" for r in UNIT_RULE_EFFECT_IDS]


def test_only_rules_with_a_real_effect_have_a_bit():
    """Aucune regle inerte exposee — meme critere que [INDIRECT FIRE] cote armes.

    `adrenalised_onslaught` est un CHOIX de joueur (Aggression OU Preservation Imperative) que
    le moteur ne resout pas : sans le mecanisme generique de decision agent (P2) elle ne produit
    aucun effet, donc aucun bit. Contre-epreuve : ses deux effets possibles, eux, SONT exposes.
    """
    assert "adrenalised_onslaught" not in UNIT_RULE_EFFECT_IDS
    assert "target_priority" not in UNIT_RULE_EFFECT_IDS  # capacite source, exposee par ses effets
    assert "reroll_1_tohit_fight" in UNIT_RULE_EFFECT_IDS
    assert "reroll_1_save_fight" in UNIT_RULE_EFFECT_IDS


def test_composite_datasheet_abilities_are_captured_through_their_effects():
    """Les capacites nommees des datasheets remontent bien en bits d'EFFET.

    Ancre DONNEE (pas une reimplementation) : ces unites existent dans le registry et portent
    ces capacites. Sans la resolution source -> effet, tous ces bits seraient a zero.
    """
    from engine.phase_handlers.shared_utils import unit_has_rule_effect

    registry = UnitRegistry()
    expected = {
        "GreyHunterPlasmaGun": {"shoot_after_advance", "shoot_after_flee"},   # cunning_hunters
        "AssaultIntercessor": {"reroll_1_towound", "reroll_towound_target_on_objective"},
        "TyranidWarriorRanged": {"charge_after_flee", "shoot_after_flee"},    # adaptable_predators
        "LieutenantStormShield": {"charge_after_flee", "shoot_after_flee"},   # target_priority
        "Boyz": {"reroll_charge"},
        "AggressorFlamestorm": {"closest_target_penetration"},
        "Gargoyle": {"move_after_shooting"},
        "Termagant": {"reactive_move"},
        "Neurogaunt": {"charge_after_advance"},
    }
    for unit_type, wanted in expected.items():
        unit = dict(registry.get_unit_data(unit_type))
        unit.setdefault("id", unit_type)
        got = {r for r in UNIT_RULE_EFFECT_IDS if unit_has_rule_effect(unit, r)}
        assert got == wanted, f"{unit_type}: {got} != {wanted}"


def test_real_training_roster_lights_the_expected_bit():
    """Sur le VRAI scenario de training, les Orks allument `reroll_charge` et les SM non.

    Discrimination reelle, pas un montage : c'est la seule des 13 regles portee par les rosters
    SM/Orks actuels — les autres attendent des rosters qui les declarent (Tyranides, Loups…).
    """
    eng = W40KEngine(
        rewards_config="ArmageddonAgent", training_config_name="x5_new",
        controlled_agent="ArmageddonAgent", scenario_file=TEMPLATE,
        unit_registry=UnitRegistry(), quiet=True, gym_training_mode=True,
    )
    lit = 0
    for _ in range(4):
        obs, _ = eng.reset()
        for family in ("allies", "enemies"):
            b = obs[f"{family}_bin"]
            lit += int(b[:, unit_bin_index("rule_reroll_charge")].sum())
    assert lit > 0, "aucune escouade Ork n'allume reroll_charge sur 4 resets"

    # Contre-epreuve : une regle qu'aucun roster de training ne porte reste eteinte.
    obs, _ = eng.reset()
    assert np.all(obs["allies_bin"][:, unit_bin_index("rule_reactive_move")] == 0.0)
