"""Chantier 02 — points de commandement (08.02), battle-shock (08.03/01.06/01.07), effectifs (25).

Ce que chaque verrou attrape, et pourquoi il ne pouvait pas être écrit autrement :

- **Meilleur Ld (01.06)** : « if the result is equal to or greater than ONE OR MORE of the Ld
  characteristics in that unit ». Le moteur lisait `unit["LD"]`, c'est-à-dire le Ld du BODYGUARD :
  un Warboss (`LD 6+`) replié dans des Boyz (`LD 7+`) laissait l'unité tester à 7+. Le test passe
  par le VRAI chargement (`_fold_attached_characters`), pas par une unité fabriquée à la main :
  le défaut était précisément que la datasheet du character n'était lue nulle part.

- **Demi-effectif impair (appendice 25)** : « if a unit's starting strength cannot be evenly
  divided in half, that unit CANNOT be at half-strength (but can be below half-strength) ». Une
  implémentation en `<=` sur une division entière classe une escouade de 5 réduite à 2 comme
  « à demi-effectif ». Le test balaie TOUS les effectifs restants possibles, pas un seul.

- **Force de départ attachée (25)** : « the starting strength of an attached unit is the number
  of models that unit contains at the start of the first battle round » — l'exemple littéral du
  PDF (Captain + 5 Intercessors = 6) est le cas de test.

- **OC (01.07/02.02)** : le battle-shock met l'OC de toutes les figurines à '-', donc l'unité
  cesse de contribuer au contrôle et celui-ci BASCULE. Vérifié sur le contrôle réel
  (`sum_objective_control_oc_multi`), pas sur le drapeau.

- **Gain de CP (08.02)** : les DEUX joueurs. Le jet de 08.03, lui, ne concerne que l'ACTIF —
  c'est la confusion que ces deux tests séparent.

- **Thievin' Scavengers** : un dé par objectif, mais UN SEUL CP au total.

Les états sont CONSTRUITS (positions, effectifs, dés forcés) : aucun test ici ne dépend d'une
graine, d'un ordre d'exécution ou d'une configuration absente.
"""
from __future__ import annotations

import json
import random
import tempfile
from pathlib import Path
from typing import Any, Dict, List

import pytest

from engine.game_state import GameStateManager, initial_command_points
from engine.phase_handlers import command_handlers, movement_handlers
from engine.phase_handlers.shared_utils import (
    build_units_cache, destroy_model, is_unit_at_half_strength,
    is_unit_at_or_below_half_strength, is_unit_below_half_strength,
    is_unit_below_starting_strength, unit_effective_leadership,
)
from shared.data_validation import ConfigurationError
from tests._state_invariants import turn_state_invariants
from tests.unit.engine._config_helpers import build_engine_config


# ─────────────────────────────────────────────────────────────────────────────
# Chargement RÉEL (repli 19.04 compris)
# ─────────────────────────────────────────────────────────────────────────────

def _load(units: List[Dict[str, Any]]):
    from ai.unit_registry import UnitRegistry
    from engine.w40k_core import W40KEngine

    scenario = {
        "board_ref": "44x60x5",
        "primary_objectives": ["objectives_control"],
        "wall_ref": "walls-none.json",
        "units": units,
    }
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "chantier02.json"
        path.write_text(json.dumps(scenario))
        eng = W40KEngine(
            rewards_config="ArmageddonAgent", training_config_name="x1_debug",
            controlled_agent="ArmageddonAgent", scenario_file=str(path),
            unit_registry=UnitRegistry(), quiet=True, gym_training_mode=True,
        )
        eng.reset(seed=0)
        return eng


def _models(count: int, col: int, row: int) -> List[Dict[str, int]]:
    return [{"col": col + i, "row": row} for i in range(count)]


_ENEMY = {"id": 1, "unit_type": "Intercessor", "player": 1, "col": 3, "row": 3}


# ─────────────────────────────────────────────────────────────────────────────
# VERROU 01.06 — 2D6 contre le MEILLEUR Ld
# ─────────────────────────────────────────────────────────────────────────────

def test_le_seuil_de_lunite_attachee_est_le_meilleur_ld_de_ses_figurines():
    """Boyz (`LD 7+`) + Warboss (`LD 6+`) → l'unité teste à 6+, pas à 7+.

    PREUVE DU ROUGE (2026-08-04) : en remplaçant le corps d'`unit_effective_leadership` par
    `return int(require_key(unit, "LD"))` — la lecture d'avant le chantier — ce test échoue sur
    `assert 7 == 6`. La contre-épreuve sans Warboss reste verte dans les deux versions : c'est
    elle qui prouve que le test mesure bien l'apport du character et pas la datasheet des Boyz.
    """
    eng = _load([
        {"id": 101, "unit_type": "Boyz", "player": 2, "col": 12, "row": 10,
         "models": _models(3, 12, 10)},
        {"id": 102, "unit_type": "Warboss", "player": 2, "attached_squad": 101,
         "col": 15, "row": 10},
        _ENEMY,
    ])
    assert unit_effective_leadership("101", eng.game_state) == 6


def test_sans_character_lunite_teste_a_son_propre_ld():
    """Contre-épreuve : sans Warboss, les mêmes Boyz testent à 7+."""
    eng = _load([
        {"id": 101, "unit_type": "Boyz", "player": 2, "col": 12, "row": 10,
         "models": _models(3, 12, 10)},
        _ENEMY,
    ])
    assert unit_effective_leadership("101", eng.game_state) == 7


def test_le_seuil_remonte_quand_le_character_meurt():
    """19.04 : la source morte, son Ld disparaît avec elle — l'unité repasse à 7+."""
    eng = _load([
        {"id": 101, "unit_type": "Boyz", "player": 2, "col": 12, "row": 10,
         "models": _models(3, 12, 10)},
        {"id": 102, "unit_type": "Warboss", "player": 2, "attached_squad": 101,
         "col": 15, "row": 10},
        _ENEMY,
    ])
    gs = eng.game_state
    warboss_model = next(
        mid for mid in gs["squad_models"]["101"]
        if gs["models_cache"][mid]["unitType"] == "Warboss"
    )
    assert unit_effective_leadership("101", gs) == 6
    destroy_model(gs, warboss_model, reason="combat")
    assert unit_effective_leadership("101", gs) == 7


def test_le_jet_de_battle_shock_est_bien_2d6():
    """01.06 : 2D6, pas 1D6. Un seuil de 7+ est INATTEIGNABLE à 1D6 — c'est ce que ce test dit.

    Dés forcés à 3 et 3 : 6 < 7 → échec. Puis 4 et 3 : 7 >= 7 → succès. Aucun résultat de 1D6 ne
    peut produire ce couple de verdicts sur le même seuil.
    """
    from engine.phase_handlers import shared_utils

    eng = _load([
        {"id": 101, "unit_type": "Boyz", "player": 2, "col": 12, "row": 10,
         "models": _models(3, 12, 10)},
        _ENEMY,
    ])
    gs = eng.game_state

    dice = iter([3, 3])
    original = random.randint
    random.randint = lambda a, b: next(dice)
    try:
        assert shared_utils.roll_battle_shock("101", gs) is True
        dice = iter([4, 3])
        assert shared_utils.roll_battle_shock("101", gs) is False
    finally:
        random.randint = original


def test_une_unite_battle_shocked_qui_reussit_cesse_de_letre():
    """08.03, clause de sortie : « if a unit WAS battle-shocked […] and its roll succeeds, it is
    no longer battle-shocked »."""
    from engine.phase_handlers import shared_utils

    eng = _load([
        {"id": 101, "unit_type": "Boyz", "player": 2, "col": 12, "row": 10,
         "models": _models(3, 12, 10)},
        _ENEMY,
    ])
    gs = eng.game_state
    gs["unit_by_id"]["101"]["battle_shocked"] = True

    original = random.randint
    random.randint = lambda a, b: 6  # 12 >= 7 : succès garanti
    try:
        assert shared_utils.roll_battle_shock("101", gs) is False
    finally:
        random.randint = original
    assert gs["unit_by_id"]["101"]["battle_shocked"] is False


# ─────────────────────────────────────────────────────────────────────────────
# VERROU appendice 25 — force de départ et demi-effectif
# ─────────────────────────────────────────────────────────────────────────────

def _kill_down_to(gs: Dict[str, Any], unit_id: str, remaining: int) -> None:
    """Réduit l'escouade à ``remaining`` figurines vivantes, par le vrai chemin de destruction."""
    while len(gs["squad_models"][unit_id]) > remaining:
        destroy_model(gs, gs["squad_models"][unit_id][-1], reason="combat")


def test_une_escouade_de_force_de_depart_impaire_nest_jamais_a_demi_effectif():
    """Appendice 25 : force de départ 5 → « cannot be at half-strength ».

    Le balayage porte sur TOUS les effectifs restants (5 → 1) : un test sur un seul effectif
    laisserait passer une implémentation qui ne se trompe que sur 2 ou 3.

    PREUVE DU ROUGE (2026-08-04) : en remplaçant le corps d'`is_unit_at_half_strength` par
    `return remaining <= start / 2` — la lecture d'avant le chantier — ce test échoue sur
    l'effectif 2 (`5 figurines réduites à 2 sont classées « à demi-effectif »`).
    """
    eng = _load([
        {"id": 101, "unit_type": "Boyz", "player": 2, "col": 12, "row": 10,
         "models": _models(5, 12, 10)},
        _ENEMY,
    ])
    gs = eng.game_state
    assert int(gs["squad_cache"]["101"]["model_count_at_start"]) == 5

    for remaining in (5, 4, 3, 2, 1):
        _kill_down_to(gs, "101", remaining)
        assert is_unit_at_half_strength("101", gs) is False, (
            f"{remaining} figurines sur une force de départ de 5 sont classées "
            f"« à demi-effectif » alors que 5 n'est pas divisible en deux (appendice 25)"
        )


def test_sous_le_demi_effectif_avec_une_force_de_depart_impaire():
    """5 réduite à 2 : SOUS le demi-effectif (2 < 2,5). À 3, elle ne l'est pas encore."""
    eng = _load([
        {"id": 101, "unit_type": "Boyz", "player": 2, "col": 12, "row": 10,
         "models": _models(5, 12, 10)},
        _ENEMY,
    ])
    gs = eng.game_state

    _kill_down_to(gs, "101", 3)
    assert is_unit_below_starting_strength("101", gs) is True
    assert is_unit_below_half_strength("101", gs) is False
    assert is_unit_at_or_below_half_strength("101", gs) is False

    _kill_down_to(gs, "101", 2)
    assert is_unit_below_half_strength("101", gs) is True
    assert is_unit_at_or_below_half_strength("101", gs) is True


def test_force_de_depart_paire_le_demi_effectif_exact_existe():
    """Contre-épreuve de la clause de parité : sur une force de départ de 6, 3 EST le demi-effectif.

    Sans elle, `is_unit_at_half_strength` pourrait renvoyer False partout et les deux tests
    précédents resteraient verts — c'est le « vert vacant » de cette famille de prédicats.
    """
    eng = _load([
        {"id": 101, "unit_type": "Boyz", "player": 2, "col": 12, "row": 10,
         "models": _models(6, 12, 10)},
        _ENEMY,
    ])
    gs = eng.game_state
    _kill_down_to(gs, "101", 3)
    assert is_unit_at_half_strength("101", gs) is True
    assert is_unit_below_half_strength("101", gs) is False


def test_la_force_de_depart_dune_unite_attachee_compte_le_character():
    """Exemple littéral du PDF 25 : Captain (1) + Intercessors (5) → force de départ 6, pas 5.

    Le corollaire est vérifié dans la foulée : à 3 figurines l'unité est EXACTEMENT à
    demi-effectif (6/2), ce qui serait faux si la force de départ valait 5.
    """
    eng = _load([
        {"id": 101, "unit_type": "Intercessor", "player": 2, "col": 12, "row": 10,
         "models": _models(5, 12, 10)},
        {"id": 102, "unit_type": "CaptainPowerWeaponBolter", "player": 2,
         "attached_squad": 101, "col": 17, "row": 10},
        _ENEMY,
    ])
    gs = eng.game_state
    assert int(gs["squad_cache"]["101"]["model_count_at_start"]) == 6

    _kill_down_to(gs, "101", 3)
    assert is_unit_at_half_strength("101", gs) is True


# ─────────────────────────────────────────────────────────────────────────────
# VERROU 01.07 / 02.02 — l'OC d'une unité battle-shocked
# ─────────────────────────────────────────────────────────────────────────────

def _oc_unit(uid: int, player: int, col: int, row: int, oc: int) -> Dict[str, Any]:
    return {
        "id": uid, "player": player, "col": col, "row": row, "OC": oc, "LD": 7,
        "battle_shocked": False, "HP_CUR": 3, "HP_MAX": 3, "VALUE": 100, "MOVE": 6,
        "T": 4, "ARMOR_SAVE": 4, "INVUL_SAVE": 7, "SHOOT_LEFT": 1, "ATTACK_LEFT": 1,
        "RNG_WEAPONS": [], "CC_WEAPONS": [], "UNIT_RULES": [],
        "BASE_SHAPE": "round", "BASE_SIZE": 1, "MODEL_HEIGHT": 2.5,
    }


def _oc_gs(units: List[Dict[str, Any]]) -> Dict[str, Any]:
    gs: Dict[str, Any] = {
        **turn_state_invariants(),
        "units": units,
        "unit_by_id": {str(u["id"]): u for u in units},
        "turn": 2,
        "current_player": 1,
        "phase": "command",
        "victory_points": {1: 0, 2: 0},
        "command_points": {1: 0, 2: 0},
        # `roll_battle_shock` journalise son jet (append_action_log) : ces deux cles sont
        # posees par `W40KEngine`, une doublure qui joue 08.03 doit les porter.
        "action_logs": [],
        "action_log_seq": 0,
        "console_logs": [],
        "primary_objective": None,
        "primary_objective_scored_turns": set(),
        "objective_rewarded_turns": set(),
        "objective_controllers": {},
        # Marqueur d'étape « début de phase de mouvement » déjà résolue (posé au reset moteur).
        "cp_gain_on_objective_resolved": set(),
        "objectives": [{"id": 1, "name": "Alpha", "hexes": [[5, 5]]}],
        "board_cols": 15,
        "board_rows": 13,
        "wall_hexes": set(),
        "turn_limit_reached": False,
        "controlled_objective_samples_scoring_turns": [],
        "opponent_objective_samples_scoring_turns": [],
        # `build_engine_config` : le checkpoint 14.02 (`cp_gain_on_objective`, phase de
        # mouvement) lit `objective_control_check` en `require_key` — un game_state qui traverse
        # les handlers porte le CONTRAT moteur complet, pas un sous-ensemble.
        "config": build_engine_config({
            "game_rules": {
                "engagement_zone": 1, "engagement_zone_vertical": 5, "max_base_size_hex": 35,
                # Cohesion 03.03 : lue des qu'une escouade MULTI-figurines entre dans le cache.
                "unit_model_cohesion_range": 2, "unit_global_cohesion_range": 9,
                "squad_min_neighbors": 1, "cohesion_distance_mode": "euclidean",
            },
            "board": {"default": {"hex_radius": 1.0, "margin": 0.0}},
        }),
    }
    build_units_cache(gs)
    return gs


def test_le_battle_shock_fait_basculer_le_controle_dobjectif():
    """01.07 : OC modifié à '-' → l'unité ne compte plus, et le contrôle passe à l'adversaire.

    PREUVE DU ROUGE (2026-08-04) : en retirant le `continue` sur `battle_shocked` de
    `sum_objective_control_oc_multi`, ce test échoue — le contrôleur reste 1 (OC 3 contre 1)
    au lieu de basculer sur 2.
    """
    from engine.game_state import sum_objective_control_oc_multi, objective_hex_sets

    strong = _oc_unit(1, 1, 5, 5, oc=3)
    weak = _oc_unit(2, 2, 5, 5, oc=1)
    gs = _oc_gs([strong, weak])
    zones = objective_hex_sets(gs)

    assert sum_objective_control_oc_multi(gs, zones) == [(3, 1)]

    strong["battle_shocked"] = True
    assert sum_objective_control_oc_multi(gs, zones) == [(0, 1)], (
        "une unité battle-shocked contribue encore à l'OC (01.07 / 02.02 non appliquée)"
    )

    manager = GameStateManager({
        "game_rules": {"engagement_zone": 1, "engagement_zone_vertical": 5, "max_base_size_hex": 35},
        "board": {"default": {"hex_radius": 1.0, "margin": 0.0}},
        "controlled_player": 1,
    }, unit_registry=None)
    gs["primary_objective"] = {
        "id": "obj1", "type": "objectives_control", "condition": "control_at_least_one",
        "points_per_scoring": 5, "max_points": 5,
        "scoring": {"start_turn": 2, "default_phase": "command", "round5_second_player_phase": "command"},
        "control": {"method": "oc_sum_greater", "control_method": "default", "tie_behavior": "no_control"},
        "objective_hexes": [[5, 5]],
    }
    control = manager.calculate_objective_control(gs)
    assert control[1]["controller"] == 2, (
        "le contrôle n'a pas basculé alors que le seul contributeur du joueur 1 est choqué"
    )


# ─────────────────────────────────────────────────────────────────────────────
# VERROU 08.02 / 08.03 — qui gagne, qui jette
# ─────────────────────────────────────────────────────────────────────────────

def test_les_deux_joueurs_gagnent_un_cp():
    """08.02 : « BOTH players gain 1 Command Point », pas seulement le joueur actif."""
    gs = _oc_gs([_oc_unit(1, 1, 5, 5, oc=1), _oc_unit(2, 2, 9, 9, oc=1)])
    gs["console_logs"] = []
    command_handlers.command_step_gain_core_cp(gs)
    assert gs["command_points"] == {1: 1, 2: 1}


def test_la_dotation_de_depart_est_lue_en_config_sans_valeur_par_defaut():
    """Clé absente → erreur explicite. Une dotation dépend du format de partie, pas d'un défaut."""
    assert initial_command_points({"game_rules": {"starting_command_points": 3}}) == {1: 3, 2: 3}
    with pytest.raises(ConfigurationError):
        initial_command_points({"game_rules": {}})


def test_seule_larmee_du_joueur_actif_jette_le_battle_shock():
    """08.03 : « the ACTIVE player must now make one battle-shock roll for each unit in THEIR army ».

    Les deux unités sont battle-shocked au départ, donc les deux REMPLISSENT la condition de
    l'étape ; seul le dé du joueur actif doit être lancé. Le dé est forcé au succès : l'unité
    active en sort, l'unité adverse reste choquée — deux verdicts opposés produits par un seul
    état, ce qu'un simple compteur d'appels ne prouverait pas.
    """
    mine = _oc_unit(1, 1, 5, 5, oc=1)
    theirs = _oc_unit(2, 2, 9, 9, oc=1)
    mine["battle_shocked"] = True
    theirs["battle_shocked"] = True
    gs = _oc_gs([mine, theirs])
    gs["current_player"] = 1

    original = random.randint
    random.randint = lambda a, b: 6  # 12 >= 7 : succès garanti
    try:
        command_handlers.command_step_battle_shock(gs)
    finally:
        random.randint = original

    assert mine["battle_shocked"] is False
    assert theirs["battle_shocked"] is True, (
        "une unité de l'armée ADVERSE a jeté son battle-shock (08.03 : joueur actif seulement)"
    )


def test_lenumeration_de_08_03_rend_reellement_des_unites():
    """VERT VACANT : une liste vide ferait passer tous les tests de battle-shock ci-dessus.

    On observe le VRAI jet (espion sur `roll_battle_shock`) : l'étape doit retenir l'escouade
    sous le demi-effectif, et ELLE SEULE — l'escouade intacte du même joueur est ignorée. Deux
    verdicts opposés sur le même appel, ce qu'un simple « au moins un jet » ne prouverait pas.
    """
    from engine.phase_handlers import shared_utils

    eng = _load([
        {"id": 101, "unit_type": "Boyz", "player": 2, "col": 12, "row": 10,
         "models": _models(4, 12, 10)},
        {"id": 103, "unit_type": "Boyz", "player": 2, "col": 12, "row": 20,
         "models": _models(4, 12, 20)},
        _ENEMY,
    ])
    gs = eng.game_state
    gs["current_player"] = 2
    _kill_down_to(gs, "101", 1)  # 1 sur 4 : sous le demi-effectif

    rolled: List[str] = []
    original_roll = shared_utils.roll_battle_shock

    def _spy(unit_id, game_state):
        rolled.append(str(unit_id))
        return original_roll(unit_id, game_state)

    shared_utils.roll_battle_shock = _spy
    original_randint = random.randint
    random.randint = lambda a, b: 6
    try:
        command_handlers.command_step_battle_shock(gs)
    finally:
        random.randint = original_randint
        shared_utils.roll_battle_shock = original_roll

    assert rolled == ["101"], (
        f"l'étape 08.03 a retenu {rolled} : elle doit retenir l'escouade sous le demi-effectif, "
        f"et elle SEULE (une liste vide ferait passer tous les autres tests)"
    )


# ─────────────────────────────────────────────────────────────────────────────
# VERROU Thievin' Scavengers — un dé par objectif, UN SEUL CP
# ─────────────────────────────────────────────────────────────────────────────

def _thievin_gs() -> Dict[str, Any]:
    """Deux objectifs, contrôlés par le joueur 1, chacun tenu par des Gretchin."""
    grots_a = _oc_unit(1, 1, 5, 5, oc=2)
    grots_b = _oc_unit(2, 1, 9, 9, oc=2)
    for unit in (grots_a, grots_b):
        unit["UNIT_RULES"] = [
            {"ruleId": "cp_gain_on_objective", "displayName": "Thievin' Scavengers"}
        ]
    gs = _oc_gs([grots_a, grots_b])
    gs["objectives"] = [
        {"id": 1, "name": "Alpha", "hexes": [[5, 5]]},
        {"id": 2, "name": "Beta", "hexes": [[9, 9]]},
    ]
    gs["objective_controllers"] = {"1": 1, "2": 1}
    gs["current_player"] = 1
    gs["console_logs"] = []
    return gs


def test_thievin_scavengers_donne_un_seul_cp_pour_deux_objectifs():
    """« If ONE OR MORE of those rolls is a 4+, you gain 1CP » — le gain est GLOBAL.

    Deux objectifs contrôlés avec Gretchin, les DEUX dés forcés à 4+ → +1 CP, pas +2.

    PREUVE DU ROUGE (2026-08-04) : en remplaçant le gain global par un `gain_command_points(…, 1)`
    à l'intérieur de la boucle sur les objectifs — le défaut « un CP par objectif » — ce test
    échoue sur `assert 2 == 1`.
    """
    gs = _thievin_gs()
    original = random.randint
    random.randint = lambda a, b: 4
    try:
        rolled = movement_handlers.movement_step_cp_gain_on_objective(gs)
    finally:
        random.randint = original

    assert rolled == 2, "un dé par objectif contrôlé et tenu, donc deux dés attendus"
    assert gs["command_points"][1] == 1, "le gain de Thievin' Scavengers est GLOBAL, pas par objectif"


def test_thievin_scavengers_ne_rejoue_pas_dans_la_meme_phase():
    """`movement_phase_start` est ré-invoquée par `execute_action` sur un pool vide : la capacité
    ne doit pas relancer ses dés.

    PREUVE DU ROUGE (2026-08-04) : en retirant le marqueur `(tour, joueur)`, le second appel
    relance 2 dés et verse un second CP — `assert 1 == 1` devient `assert 2 == 1`.
    """
    gs = _thievin_gs()
    original = random.randint
    random.randint = lambda a, b: 4
    try:
        first = movement_handlers.movement_step_cp_gain_on_objective(gs)
        second = movement_handlers.movement_step_cp_gain_on_objective(gs)
    finally:
        random.randint = original

    assert (first, second) == (2, 0), "le second appel a relancé des dés"
    assert gs["command_points"][1] == 1

    # Tour suivant : l'étape se rejoue, le marqueur est bien par (tour, joueur).
    gs["turn"] = 3
    random.randint = lambda a, b: 4
    try:
        assert movement_handlers.movement_step_cp_gain_on_objective(gs) == 2
    finally:
        random.randint = original
    assert gs["command_points"][1] == 2


def test_thievin_scavengers_ne_donne_rien_sans_4_plus():
    """Contre-épreuve : les dés lancés mais tous ratés → aucun CP (le test ci-dessus ne mesure
    donc pas simplement « la fonction ajoute toujours 1 »)."""
    gs = _thievin_gs()
    original = random.randint
    random.randint = lambda a, b: 3
    try:
        rolled = movement_handlers.movement_step_cp_gain_on_objective(gs)
    finally:
        random.randint = original

    assert rolled == 2
    assert gs["command_points"][1] == 0


def test_thievin_scavengers_ignore_une_unite_battle_shocked():
    """« one or more friendly NON-BATTLE-SHOCKED units with this ability » : une unité choquée ne
    déclenche rien. Sans battle-shock implémenté, la condition serait toujours vraie."""
    gs = _thievin_gs()
    for unit in gs["units"]:
        unit["battle_shocked"] = True

    original = random.randint
    random.randint = lambda a, b: 6
    try:
        rolled = movement_handlers.movement_step_cp_gain_on_objective(gs)
    finally:
        random.randint = original

    assert rolled == 0
    assert gs["command_points"][1] == 0


def test_thievin_scavengers_ignore_un_objectif_non_controle():
    """« for each objective YOU CONTROL » : un objectif tenu mais non contrôlé ne donne pas de dé."""
    gs = _thievin_gs()
    gs["objective_controllers"] = {"1": 1, "2": 2}

    original = random.randint
    random.randint = lambda a, b: 4
    try:
        rolled = movement_handlers.movement_step_cp_gain_on_objective(gs)
    finally:
        random.randint = original

    assert rolled == 1, "seul l'objectif contrôlé par le joueur actif donne un dé"
    assert gs["command_points"][1] == 1
