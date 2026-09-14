"""Tests — ledger de marge VP (B6) et bonus sur objectif.

DÉCISION B6 (2026-09-14) : remplace objective_reward_factor × VP_propres par un ledger
différentiel. À chaque appel à calculate_reward, le moteur compare la marge courante
(VP_moi − VP_lui) à game_state["vp_margin_paid"] (filigrane) et verse
vp_margin_factor × delta. Somme télescopique = factor × marge finale.

Aucun filtre current_player : les VP tombent pendant n'importe quel tour, accumulés
par BotControlledEnv (accumulate_reward=True). KeyError si "vp_margin_paid" absent (T1).
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from config_loader import get_config_loader
from engine.phase_handlers.command_handlers import command_phase_end
from engine.reward_calculator import RewardCalculator
from shared.data_validation import ConfigurationError

AGENT = "ArmageddonAgent_x1"


def _rewards_config() -> Dict[str, Any]:
    return get_config_loader().load_agent_rewards_config(AGENT)


def _vp_margin_factor() -> float:
    return float(_rewards_config()[AGENT]["objective_rewards"]["vp_margin_factor"])


def _calculator(controlled_player: int = 1) -> RewardCalculator:
    return RewardCalculator(
        {
            "controlled_agent": AGENT,
            "controlled_player": controlled_player,
            "quiet": True,
            "game_rules": get_config_loader().get_game_config()["game_rules"],
        },
        _rewards_config(),
    )


def _game_state(
    *,
    turn: int = 2,
    current_player: int = 1,
    controlled_player: int = 1,
    my_vp: float = 0.0,
    opp_vp: float = 0.0,
    vp_margin_paid: float = 0.0,
) -> Dict[str, Any]:
    units: List[Dict[str, Any]] = [
        {"id": "1", "player": controlled_player, "unitType": "Intercessor", "UNIT_RULES": []},
        {"id": "2", "player": 2 if controlled_player == 1 else 1, "unitType": "Intercessor", "UNIT_RULES": []},
    ]
    opponent = 2 if controlled_player == 1 else 1
    return {
        "turn": turn,
        "current_player": current_player,
        "phase": "command",
        "game_over": False,
        "units": units,
        "unit_by_id": {str(unit["id"]): unit for unit in units},
        "units_cache": {
            "1": {"player": controlled_player, "col": 1, "row": 1, "HP_CUR": 6, "HP_MAX": 6},
            "2": {"player": opponent, "col": 9, "row": 9, "HP_CUR": 6, "HP_MAX": 6},
        },
        "squad_cache": {"1": {"is_coherent": True}, "2": {"is_coherent": True}},
        "objective_controllers": {},
        "command_activation_pool": [],
        "console_logs": [],
        "debug_logs": [],
        "victory_points": {controlled_player: my_vp, opponent: opp_vp},
        "vp_margin_paid": vp_margin_paid,
    }


def _pay(calc: RewardCalculator, game_state: Dict[str, Any]) -> tuple[float, Dict[str, Any]]:
    """Joue le payload de fin de phase command dans calculate_reward."""
    payload = command_phase_end(game_state)
    total = calc.calculate_reward(True, payload, game_state)
    return total, game_state["last_reward_breakdown"]


# ---- Ledger de marge VP (B6) ---------------------------------------------------------


def test_versement_egal_facteur_fois_delta_marge() -> None:
    """versement = vp_margin_factor × Δ(VP_moi − VP_lui).

    VERROU. Remettre objective_reward_factor × VP_propres dans _calculate_vp_margin_reward
    fait passer ce test au ROUGE : le montant dépend alors des VP absolus, pas du delta.
    CONTRÔLE NON VACANT : assert factor > 0 garantit qu'un résultat nul ne serait pas
    confondu avec un calcul correct.
    """
    factor = _vp_margin_factor()
    assert factor > 0.0, "facteur nul en config : le test ne mesure rien"

    # Marge courante = 5 − 2 = +3, filigrane = 0 → delta = 3
    calc = _calculator(controlled_player=1)
    state = _game_state(my_vp=5.0, opp_vp=2.0, vp_margin_paid=0.0)

    reward = calc._calculate_vp_margin_reward(state)

    assert reward == pytest.approx(factor * 3.0)
    assert state["vp_margin_paid"] == pytest.approx(3.0)


def test_versement_negatif_quand_marge_recule() -> None:
    """Un adversaire qui marque des VP est versé négativement — le ledger est symétrique."""
    factor = _vp_margin_factor()
    # Filigrane = +2, marge actuelle = 0 (adversaire a rattrapé) → delta = -2
    calc = _calculator(controlled_player=1)
    state = _game_state(my_vp=2.0, opp_vp=2.0, vp_margin_paid=2.0)

    reward = calc._calculate_vp_margin_reward(state)

    assert reward == pytest.approx(-factor * 2.0)
    assert state["vp_margin_paid"] == pytest.approx(0.0)


def test_delta_adverse_verse_sans_filtre_current_player() -> None:
    """Les VP de l'adversaire tombent pendant SON tour : aucun filtre current_player.

    Le wrapper BotControlledEnv accumule les rewards (accumulate_reward=True) : le terme
    négatif est crédité au bon step même si current_player != controlled_player.

    VERROU. Réintroduire `if game_state["current_player"] != controlled_player: return 0.0`
    dans _calculate_vp_margin_reward fait passer ce test au ROUGE : le delta reste non versé
    pendant le tour adverse, et la somme télescopique manque les VP concédés.
    """
    factor = _vp_margin_factor()
    # Tour de l'adversaire (current_player=2), contrôlé=1
    # Adversaire vient de marquer 3 VP → marge = 0 - 3 = -3, delta = -3 - 0 = -3
    calc = _calculator(controlled_player=1)
    state = _game_state(current_player=2, my_vp=0.0, opp_vp=3.0, vp_margin_paid=0.0)

    reward = calc._calculate_vp_margin_reward(state)

    assert reward == pytest.approx(-factor * 3.0)


def test_deux_appels_sans_changement_vp_second_nul() -> None:
    """Deux appels sans changement de VP : le second retourne 0.

    VERROU. Retirer `game_state["vp_margin_paid"] = current_margin` dans
    _calculate_vp_margin_reward fait passer ce test au ROUGE : le filigrane n'est pas
    mis à jour et le même delta est versé deux fois.
    """
    calc = _calculator(controlled_player=1)
    state = _game_state(my_vp=4.0, opp_vp=1.0, vp_margin_paid=0.0)

    first = calc._calculate_vp_margin_reward(state)
    second = calc._calculate_vp_margin_reward(state)  # VP inchangés

    assert first != pytest.approx(0.0), "premier versement nul : le test ne discrimine pas"
    assert second == pytest.approx(0.0)


def test_vp_margin_paid_absent_leve_erreur() -> None:
    """Clé vp_margin_paid absente → ConfigurationError explicite (T1, aucun fallback)."""
    calc = _calculator(controlled_player=1)
    state = _game_state(my_vp=3.0, opp_vp=0.0)
    del state["vp_margin_paid"]

    with pytest.raises(ConfigurationError):
        calc._calculate_vp_margin_reward(state)


def test_somme_telescopique_egale_facteur_fois_marge_finale() -> None:
    """La somme de tous les versements = factor × marge finale (propriété télescopique).

    C'est le contrat qui rend la courbe TensorBoard interprétable : la recompense accumulée
    sur un épisode = vp_margin_factor × (VP_moi_final − VP_lui_final), y compris élimination.

    CONTRÔLE NON VACANT : la séquence construit une marge finale non nulle et un total
    calculé indépendamment ; une somme nulle serait détectée par assert != 0.
    """
    factor = _vp_margin_factor()
    calc = _calculator(controlled_player=1)
    state = _game_state(my_vp=0.0, opp_vp=0.0, vp_margin_paid=0.0)

    total = 0.0
    # Séquence : marge +2, puis +3 (moi score), puis adversaire rattrape (+1 lui)
    for my_vp, opp_vp in [(3.0, 1.0), (5.0, 2.0), (5.0, 3.0)]:
        state["victory_points"] = {1: my_vp, 2: opp_vp}
        total += calc._calculate_vp_margin_reward(state)

    marge_finale = 5.0 - 3.0  # 2
    assert total == pytest.approx(factor * marge_finale)
    assert total != pytest.approx(0.0), "somme nulle : la séquence ne construit rien"


def test_vp_margin_categorise_dans_breakdown_pas_dans_objective() -> None:
    """Le versement de marge VP apparaît dans 'vp_margin', jamais dans 'objective'.

    VERROU. Écrire reward_breakdown['objective'] += vp_margin_reward à la place fait passer
    ce test au ROUGE : objective monte et vp_margin reste nul, alors que la métrique
    TensorBoard reward/vp_margin_total ne reflète rien.
    """
    factor = _vp_margin_factor()
    assert factor > 0.0

    calc = _calculator(controlled_player=1)
    state = _game_state(my_vp=5.0, opp_vp=2.0, vp_margin_paid=0.0)
    # Payload système : déclenche calculate_reward sans action
    payload = command_phase_end(state)
    calc.calculate_reward(True, payload, state)
    breakdown = state["last_reward_breakdown"]

    assert breakdown["vp_margin"] == pytest.approx(factor * 3.0)
    assert breakdown["objective"] == pytest.approx(0.0)


# ---- Cohérence escouade — penalite indépendante du ledger VP -------------------------


def _system_response_penalty() -> float:
    calc = _calculator(controlled_player=1)
    return float(calc._get_system_penalties()["system_response"])


def test_the_coherency_penalty_applies_at_command_boundary() -> None:
    """La pénalité de cohérence (squad_shaping) est versée à la frontière command→move.

    CONTRÔLE NON VACANT : l'incohérence est construite explicitement dans l'état ;
    un zéro signifierait vraiment « pas versé » et non « escouade cohérente ».
    """
    calc = _calculator(controlled_player=1)
    state = _game_state()
    state["squad_cache"]["1"]["is_coherent"] = False

    _total, breakdown = _pay(calc, state)
    incoherent_weight = float(_rewards_config()[AGENT]["squad_shaping"]["incoherent_weight"])

    assert incoherent_weight > 0.0, "poids nul : le test ne mesure rien"
    assert breakdown["penalties"] == pytest.approx(-incoherent_weight)


def test_coherency_penalty_not_imputed_to_vp_margin() -> None:
    """La pénalité de cohérence va dans 'penalties', jamais dans 'vp_margin'.

    Le calcul absorbe coherency_penalty dans vp_margin_reward pour le propager vers le
    total sur chaque chemin de retour, mais reward_breakdown['vp_margin'] est renseigné
    AVANT cette absorption. Écrire breakdown['vp_margin'] après l'absorption contaminerait
    la métrique de marge avec une pénalité sans rapport.

    VERROU. Déplacer `reward_breakdown['vp_margin'] += vp_margin_reward` APRÈS la ligne
    `vp_margin_reward += coherency_penalty` fait passer ce test au ROUGE : vp_margin devient
    net de la pénalité, et penalties reçoit la même valeur en double.
    """
    factor = _vp_margin_factor()
    calc = _calculator(controlled_player=1)
    # Marge = +3 pour que vp_margin soit non nul et isolable
    state = _game_state(my_vp=5.0, opp_vp=2.0, vp_margin_paid=0.0)
    state["squad_cache"]["1"]["is_coherent"] = False

    _total, breakdown = _pay(calc, state)
    incoherent_weight = float(_rewards_config()[AGENT]["squad_shaping"]["incoherent_weight"])

    assert incoherent_weight > 0.0, "poids nul : le test ne mesure rien"
    assert breakdown["vp_margin"] == pytest.approx(factor * 3.0)
    assert breakdown["penalties"] == pytest.approx(-incoherent_weight)


# ---- Bonus sur objectif (on_objective_bonus) ----------------------------------------
# Ces tests couvrent _calculate_on_objective_reward, indépendant du ledger VP.


def _move_state(controlled_player: int = 1, model_col: int = 5, model_row: int = 5) -> Dict[str, Any]:
    """État de phase move avec un objectif non contrôlé, une figurine positionnée.

    Le bonus « sur un objectif » se juge PAR FIGURINE (14.02, empreinte de socle) et non sur
    l'ancre d'escouade : l'état doit porter models_cache / squad_models, sinon le lecteur lève.
    C'est model_col/model_row qui décide de la présence dans la zone — l'ancre de units_cache
    reste volontairement AILLEURS (1,1), pour que ce fichier casse si quelqu'un revenait à une
    lecture par ancre.
    """
    state = _game_state(turn=2, current_player=controlled_player, controlled_player=controlled_player)
    state["phase"] = "move"
    state["objectives"] = [{"id": "obj_move", "hexes": [{"col": 5, "row": 5}]}]
    # Zone non contrôlée : get_objective_control < 1.0 est la condition du bonus.
    state["objective_controllers"] = {}
    state["units_cache"]["1"]["orientation"] = 0
    state["units_cache"]["2"]["orientation"] = 0
    state["squad_models"] = {"1": ["m1"], "2": ["m2"]}
    opponent = 2 if controlled_player == 1 else 1
    state["models_cache"] = {
        "m1": {
            "player": controlled_player, "col": model_col, "row": model_row,
            "HP_CUR": 6, "BASE_SHAPE": "round", "BASE_SIZE": 1,
        },
        "m2": {
            "player": opponent, "col": 20, "row": 20,
            "HP_CUR": 6, "BASE_SHAPE": "round", "BASE_SIZE": 1,
        },
    }
    for unit in state["units"]:
        unit["battle_shocked"] = False
        unit["RNG_WEAPONS"] = []
        unit["CC_WEAPONS"] = []
    return state


def _on_objective_bonus() -> float:
    return float(_rewards_config()[AGENT]["objective_rewards"]["on_objective_bonus"])


def test_the_on_objective_bonus_is_categorised_as_objective_not_base_action() -> None:
    """Se poser sur un objectif doit apparaître dans 'objective', jamais dans 'base_actions'.

    VERROU. En remettant reward_breakdown['objective'] += on_obj_reward en commentaire dans
    la branche move de calculate_reward, ce test passe au ROUGE sur la première assertion :
    le bonus retombe dans le total sans catégorie, et la part d'objectif se lit 0.
    """
    calc = _calculator(controlled_player=1)
    state = _move_state()
    bonus = _on_objective_bonus()

    assert bonus > 0.0, "on_objective_bonus nul en config : le test ne mesure rien"

    total = calc.calculate_reward(
        True, {"action": "move", "unitId": "1", "toCol": 5, "toRow": 5}, state
    )
    breakdown = state["last_reward_breakdown"]

    assert breakdown["objective"] == pytest.approx(bonus)
    assert breakdown["base_actions"] == pytest.approx(0.0)
    assert total == pytest.approx(bonus)


def test_the_on_objective_bonus_reads_the_models_not_the_squad_anchor() -> None:
    """Une FIGURINE dans la zone suffit, même si l'ancre d'escouade est ailleurs (14.02).

    LE DÉFAUT CORRIGÉ. Le bonus comparait la DESTINATION d'escouade à un hexe d'objectif par
    égalité stricte de coordonnées. L'ancre n'est pas une figurine, et l'égalité de centre
    ignore l'empreinte de socle — alors que le décompte de contrôle du même moteur
    (sum_objective_control_oc_multi) compte une figurine dès qu'une case de son socle recouvre
    la zone. Une escouade étalée était donc COMPTÉE par le moteur et PAS payée par la
    récompense, dans le même état de jeu.

    VERROU. En remettant la comparaison `h_col == to_col and h_row == to_row` dans
    _calculate_on_objective_reward, ce test passe au ROUGE : la destination (1,1) ne tombe sur
    aucun hexe d'objectif, donc le bonus vaut 0.
    """
    calc = _calculator(controlled_player=1)
    state = _move_state(model_col=5, model_row=5)  # figurine DANS la zone
    bonus = _on_objective_bonus()

    # Destination d'escouade HORS de la zone d'objectif : seule la figurine y est.
    total = calc.calculate_reward(
        True, {"action": "move", "unitId": "1", "toCol": 1, "toRow": 1}, state
    )
    breakdown = state["last_reward_breakdown"]

    assert bonus > 0.0, "on_objective_bonus nul en config : le test ne mesure rien"
    assert breakdown["objective"] == pytest.approx(bonus)
    assert total == pytest.approx(bonus)


def test_the_on_objective_bonus_is_not_paid_when_no_model_stands_in_the_zone() -> None:
    """Miroir : destination sur l'hexe d'objectif, mais aucune figurine dedans → rien.

    C'est l'autre moitié du défaut d'ancre : l'ancienne lecture payait dès que la DESTINATION
    tombait sur la zone, y compris quand aucune figurine vivante ne s'y trouvait. Sans ce
    contrôle, un lecteur qui rendrait « vrai » en permanence passerait le test précédent.
    """
    calc = _calculator(controlled_player=1)
    state = _move_state(model_col=30, model_row=30)  # figurine LOIN de la zone

    total = calc.calculate_reward(
        True, {"action": "move", "unitId": "1", "toCol": 5, "toRow": 5}, state
    )
    breakdown = state["last_reward_breakdown"]

    assert breakdown["objective"] == pytest.approx(0.0)
    assert total == pytest.approx(0.0)


def test_the_fight_path_does_not_count_the_on_objective_bonus_twice() -> None:
    """Chemin fight : base_actions retranche le bonus, il n'est compté QUE dans 'objective'.

    VERROU. La branche fight construit base_actions par soustraction
    (fight_reward - vp_margin_reward - on_obj_reward). Retirer le - on_obj_reward
    fait passer ce test au ROUGE : le bonus apparaît dans les deux catégories, et la
    somme des parts dépasse le total.
    """
    calc = _calculator(controlled_player=1)
    state = _move_state()
    bonus = _on_objective_bonus()

    total = calc.calculate_reward(
        True,
        {
            "action": "fight",
            "unitId": "1",
            "targetId": "2",
            "toCol": 5,
            "toRow": 5,
            "all_attack_results": [],
        },
        state,
    )
    breakdown = state["last_reward_breakdown"]

    assert breakdown["objective"] == pytest.approx(bonus)
    assert breakdown["base_actions"] + breakdown["objective"] == pytest.approx(total)


def test_combat_action_v11_reaches_fight_branch_not_system_response() -> None:
    """action="combat" (V11 auto) doit atteindre la branche fight, pas être absorbé en system_response.

    VERROU. En retirant "combat" de is_action_result dans reward_calculator.py, le payload
    V11 porte "waiting_for_player" (indicateur système) et est absorbé comme réponse système :
    calculate_reward retourne 0.0 au lieu du base_reward mêlée (0.3). Chaque step de combat
    en training V11 payait alors 0.0 de reward offensif. Ce test passe au ROUGE si "combat"
    disparaît de is_action_result OU si targetId est absent du payload moteur.
    """
    calc = _calculator(controlled_player=1)
    state = _move_state()

    base_melee = float(_rewards_config()[AGENT]["base_actions"]["melee_attack"])
    assert base_melee > 0.0, "melee_attack nul en config : le test ne discrimine pas les deux chemins"

    reward = calc.calculate_reward(
        True,
        {
            "action": "combat",
            "unitId": "1",
            "targetId": "2",
            "all_attack_results": [],
            "waiting_for_player": False,
        },
        state,
    )

    assert reward == pytest.approx(base_melee), (
        '"combat" absorbé en system_response (reward=0.0) au lieu de la branche fight'
    )
