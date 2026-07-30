"""Tests — versement du reward d'objectif par tour (reward_per_objective + objective_lead).

CE QUI A ETE MANQUE. `_calculate_objective_reward_per_turn` se declenche sur la fin de la phase
command (`phase_transition` + `next_phase == "move"`). Ce payload ne porte ni `unitId` ni
`action` : `calculate_reward` le classe en `is_system_response` et RETOURNE avant d'atteindre
l'appel. Les 10.0 par objectif et 10.0 par objectif d'avance de la config n'ont donc jamais ete
verses — mesure : 73 appels par episode, 0,00 de reward, sur 8 episodes complets. Aucun test ne
l'a vu parce qu'aucun ne passait le VRAI payload de transition a `calculate_reward` : les tests
de reward partaient tous d'un resultat d'action.

CE QUI REND CES TESTS PORTANTS.

Le payload n'est PAS ecrit a la main ici : il vient de `command_handlers.command_phase_end()`,
son unique producteur. Un test qui recopierait le dict passerait au vert le jour ou le
producteur changerait de forme — c'est-a-dire le jour ou le bug reviendrait. Meme discipline que
pour le montant : il est recalcule depuis la config d'agent REELLE, jamais code en dur.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from config_loader import get_config_loader
from engine.phase_handlers.command_handlers import command_phase_end
from engine.reward_calculator import RewardCalculator

AGENT = "ArmageddonAgent"

PRIMARY_OBJECTIVE: Dict[str, Any] = {
    "id": "objectives_control",
    "scoring": {"start_turn": 2, "max_points_per_turn": 15, "rules": []},
    "timing": {"default_phase": "command", "round5_second_player_phase": "fight"},
    "control": {"method": "oc_sum_greater", "control_method": "default", "tie_behavior": "no_control"},
}


def _objective_controllers(mine: int, theirs: int, controlled_player: int) -> Dict[str, Any]:
    """Etat 14.02 fige : `objective_controllers`, tel que le scoring vient de l'ecrire.

    Le reward le LIT, il ne le recalcule pas — `count_controlled_objectives` reecrirait le
    controle depuis un chemin de recompense, hors des frontieres autorisees par la regle.
    """
    opponent = 2 if controlled_player == 1 else 1
    controllers: Dict[str, Any] = {}
    index = 0
    for _ in range(mine):
        controllers[f"obj{index}"] = controlled_player
        index += 1
    for _ in range(theirs):
        controllers[f"obj{index}"] = opponent
        index += 1
    # Un objectif contesté (aucun controleur) : il ne doit compter pour personne.
    controllers[f"obj{index}"] = None
    return controllers


def _rewards_config() -> Dict[str, Any]:
    """Config de recompense REELLE de l'agent : les montants testes sont ceux de production."""
    return get_config_loader().load_agent_rewards_config(AGENT)


def _objective_rewards() -> Dict[str, Any]:
    return _rewards_config()[AGENT]["objective_rewards"]


def _system_response_penalty() -> float:
    calc = RewardCalculator(
        {"controlled_agent": AGENT, "controlled_player": 1, "quiet": True}, _rewards_config()
    )
    return float(calc._get_system_penalties()["system_response"])


def _expected_turn_reward(mine: int, theirs: int) -> float:
    """Formule du versement : par objectif tenu, PLUS un FORFAIT si j'en tiens plus que lui.

    Forfait et non proportionnel : la regle de score correspondante du primaire
    (`control_more_than_opponent`) accorde ses points en une fois, quelle que soit l'avance.
    """
    cfg = _objective_rewards()
    total = float(cfg["reward_per_objective"]) * mine
    if cfg["use_objective_lead"] is True and mine > theirs:
        total += float(cfg["reward_for_objective_lead"])
    return total


def _game_state(
    *, turn: int, current_player: int, controlled_player: int, mine: int = 0, theirs: int = 0
) -> Dict[str, Any]:
    units: List[Dict[str, Any]] = [
        {"id": "1", "player": controlled_player, "unitType": "Intercessor"},
        {"id": "2", "player": 2 if controlled_player == 1 else 1, "unitType": "Intercessor"},
    ]
    return {
        "turn": turn,
        "current_player": current_player,
        "phase": "command",
        "game_over": False,
        "primary_objective": PRIMARY_OBJECTIVE,
        "objective_controllers": _objective_controllers(mine, theirs, controlled_player),
        "objective_rewarded_turns": set(),
        "coherency_penalized_turns": set(),
        "units": units,
        # Index exige par get_unit_by_id (construit au reset dans le moteur).
        "unit_by_id": {str(unit["id"]): unit for unit in units},
        "units_cache": {
            "1": {"player": controlled_player, "col": 1, "row": 1, "HP_CUR": 6},
            "2": {"player": 2 if controlled_player == 1 else 1, "col": 9, "row": 9, "HP_CUR": 6},
        },
        # Escouades coherentes : la penalite de coherency partage la garde du reward d'objectif
        # et serait versee au meme instant. La neutraliser ici isole le montant teste.
        "squad_cache": {"1": {"is_coherent": True}, "2": {"is_coherent": True}},
        "command_activation_pool": [],
        "console_logs": [],
        "debug_logs": [],
    }


def _calculator(controlled_player: int) -> RewardCalculator:
    """Aucun state_manager : le reward d'objectif par tour LIT l'etat, il ne le recalcule pas.

    C'est ce qui rend le controle portant : si le calcul repassait par
    `state_manager.count_controlled_objectives`, ce test leverait au lieu de passer.
    """
    return RewardCalculator(
        {
            "controlled_agent": AGENT,
            "controlled_player": controlled_player,
            "quiet": True,
            # `game_rules` REEL (config de jeu de production) : `_enrich_unit_for_reward_mapper`
            # y lit `engagement_zone` pour trancher is_ranged/is_melee. Le recopier a la main
            # figerait ici une valeur que la config peut faire evoluer.
            "game_rules": get_config_loader().get_game_config()["game_rules"],
        },
        _rewards_config(),
    )


def _pay(calc: RewardCalculator, game_state: Dict[str, Any]) -> tuple[float, Dict[str, Any]]:
    """Joue le VRAI payload de fin de phase command dans calculate_reward."""
    payload = command_phase_end(game_state)
    total = calc.calculate_reward(True, payload, game_state)
    return total, game_state["last_reward_breakdown"]


def test_the_command_phase_transition_actually_pays_the_objective_reward() -> None:
    """LE defaut : le payload de transition doit etre paye, pas avale en reponse systeme."""
    calc = _calculator(controlled_player=1)
    state = _game_state(turn=2, current_player=1, controlled_player=1, mine=2, theirs=1)

    total, breakdown = _pay(calc, state)
    expected = _expected_turn_reward(2, 1)

    assert expected > 0.0, "config d'agent sans reward d'objectif : le test ne mesure rien"
    assert breakdown["objective"] == pytest.approx(expected)
    assert total == pytest.approx(_system_response_penalty() + expected)


def test_the_lead_term_is_included() -> None:
    """`reward_for_objective_lead` compte l'AVANCE : deux comptages differents, deux montants."""
    ahead, _ = _pay(
        _calculator(controlled_player=1),
        _game_state(turn=2, current_player=1, controlled_player=1, mine=2, theirs=0),
    )
    behind, _ = _pay(
        _calculator(controlled_player=1),
        _game_state(turn=2, current_player=1, controlled_player=1, mine=2, theirs=3),
    )

    assert ahead == pytest.approx(_system_response_penalty() + _expected_turn_reward(2, 0))
    assert behind == pytest.approx(_system_response_penalty() + _expected_turn_reward(2, 3))
    assert ahead > behind, "tenir autant d'objectifs avec plus d'avance doit rapporter plus"


def test_the_lead_bonus_is_flat_not_proportional() -> None:
    """Une avance de 1 et une avance de 3 rapportent le MEME forfait.

    La version proportionnelle (`lead * (mes objectifs - les siens)`) payait le triple pour une
    avance de 3, un signal que le jeu ne rend pas : la regle de score du primaire accorde ses
    points en une fois. Les deux montages tiennent le meme nombre d'objectifs, donc seul le
    terme d'avance peut expliquer un ecart.
    """
    lead_one, _ = _pay(
        _calculator(controlled_player=1),
        _game_state(turn=2, current_player=1, controlled_player=1, mine=3, theirs=2),
    )
    lead_three, _ = _pay(
        _calculator(controlled_player=1),
        _game_state(turn=2, current_player=1, controlled_player=1, mine=3, theirs=0),
    )

    assert lead_one == pytest.approx(lead_three)


def test_being_behind_costs_nothing_extra() -> None:
    """Etre en retard ne facture RIEN de plus : le retard coute deja les VP non marques.

    La version proportionnelle retirait `reward_for_objective_lead` par objectif de retard —
    une penalite que ni la config ni la regle de score ne prevoient.
    """
    calc = _calculator(controlled_player=1)
    state = _game_state(turn=2, current_player=1, controlled_player=1, mine=1, theirs=3)

    _total, breakdown = _pay(calc, state)
    per_objective = float(_objective_rewards()["reward_per_objective"])

    assert breakdown["objective"] == pytest.approx(per_objective * 1)
    assert breakdown["objective"] > 0.0, "tenir un objectif reste paye, meme en retard"


def test_paid_once_per_turn() -> None:
    """Deux transitions dans le meme tour : un seul versement."""
    calc = _calculator(controlled_player=1)
    state = _game_state(turn=2, current_player=1, controlled_player=1, mine=2, theirs=1)

    _first, first_breakdown = _pay(calc, state)
    _second, second_breakdown = _pay(calc, state)

    assert first_breakdown["objective"] == pytest.approx(_expected_turn_reward(2, 1))
    assert second_breakdown["objective"] == pytest.approx(0.0)


@pytest.mark.parametrize("controlled_player", [1, 2])
def test_not_paid_at_the_opponent_command_phase(controlled_player: int) -> None:
    """La transition command -> move existe pour les DEUX joueurs : ne payer qu'a la mienne.

    Sans ce filtre, le premier des deux passages du round arme `objective_rewarded_turns` et
    l'agent est paye pour les objectifs qu'il tient au debut du tour ADVERSE — un instant qu'il
    ne controle pas, et qui n'est pas celui ou le jeu lui attribue ses VP.
    """
    opponent = 2 if controlled_player == 1 else 1
    calc = _calculator(controlled_player=controlled_player)
    state = _game_state(
        turn=2, current_player=opponent, controlled_player=controlled_player, mine=2, theirs=1
    )

    _total, breakdown = _pay(calc, state)

    assert breakdown["objective"] == pytest.approx(0.0)
    # ... et le tour n'est pas consomme : mon propre passage doit encore payer.
    state["current_player"] = controlled_player
    _total2, breakdown2 = _pay(calc, state)
    assert breakdown2["objective"] == pytest.approx(_expected_turn_reward(2, 1))


def test_the_coherency_penalty_shares_the_repaired_site_and_now_applies() -> None:
    """La penalite de coherency partageait la garde MORTE : elle est reparee avec sa jumelle.

    Controle NON VACANT : la mesure sur 8 episodes joues donnait 0,00 pour cette penalite, mais
    parce qu'aucune escouade n'y etait incoherente. Ici l'incoherence est CONSTRUITE, donc un
    zero signifierait vraiment « pas verse ».
    """
    calc = _calculator(controlled_player=1)
    state = _game_state(turn=2, current_player=1, controlled_player=1)
    state["squad_cache"]["1"]["is_coherent"] = False

    _total, breakdown = _pay(calc, state)
    incoherent_weight = float(_rewards_config()[AGENT]["squad_shaping"]["incoherent_weight"])

    assert incoherent_weight > 0.0, "poids nul : le test ne mesure rien"
    assert breakdown["penalties"] == pytest.approx(-incoherent_weight)


def test_not_paid_before_the_scoring_start_turn() -> None:
    """Le primaire ne marque qu'a partir de `start_turn` : le reward suit la meme frontiere."""
    calc = _calculator(controlled_player=1)
    state = _game_state(turn=1, current_player=1, controlled_player=1, mine=3, theirs=0)

    _total, breakdown = _pay(calc, state)

    assert breakdown["objective"] == pytest.approx(0.0)


# --- Ventilation : la part d'objectif doit etre LISIBLE, pas seulement versee --------------
#
# Le versement de fin de tour ci-dessus n'est qu'UNE des deux sources d'objectif. L'autre, le
# bonus « se poser sur un objectif » (`_calculate_on_objective_reward`), entrait dans le total
# sur six chemins d'action (move, flee, fight, wait, advance, squad_*) sans jamais etre
# categorise : il etait compte dans `base_actions`, ou retranche de rien du tout. Impossible,
# donc, de repondre a « quelle part de la recompense vient du controle d'objectif ? » — la
# question qui decide si l'agent est paye pour gagner ou pour autre chose.


def _move_state(controlled_player: int = 1) -> Dict[str, Any]:
    """Etat de phase move avec UN objectif non controle, sur lequel l'unite 1 va se poser."""
    state = _game_state(turn=2, current_player=controlled_player, controlled_player=controlled_player)
    state["phase"] = "move"
    state["objectives"] = [{"id": "obj_move", "hexes": [{"col": 5, "row": 5}]}]
    # Zone non controlee : `get_objective_control` < 1.0 est la condition du bonus.
    state["objective_controllers"] = {}
    for unit in state["units"]:
        unit["battle_shocked"] = False
        # `_enrich_unit_for_reward_mapper` s'execute AVANT le dispatch par action et exige les
        # deux contrats d'armes. Listes vides : ce test porte sur la VENTILATION du reward
        # d'objectif, pas sur des degats — un armement invente ne rendrait pas le controle plus
        # portant, il ajouterait seulement une fiction a maintenir.
        unit["RNG_WEAPONS"] = []
        unit["CC_WEAPONS"] = []
    return state


def _on_objective_bonus() -> float:
    return float(_rewards_config()[AGENT]["objective_rewards"]["on_objective_bonus"])


def test_the_on_objective_bonus_is_categorised_as_objective_not_base_action() -> None:
    """Se poser sur un objectif doit apparaitre dans `objective`, JAMAIS dans `base_actions`.

    VERROU. En remettant `reward_breakdown['objective'] += on_obj_reward` en commentaire dans
    la branche move de `calculate_reward`, ce test passe au ROUGE sur la premiere assertion :
    le bonus retombe dans le total sans categorie, et la part d'objectif se lit 0.
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


def test_the_fight_path_does_not_count_the_on_objective_bonus_twice() -> None:
    """Chemin fight : `base_actions` retranche le bonus, il n'est compte QUE dans `objective`.

    VERROU. La branche fight construit `base_actions` par soustraction
    (`fight_reward - objective_turn_reward - on_obj_reward`). Retirer le `- on_obj_reward`
    fait passer ce test au ROUGE : le bonus apparait alors dans les deux categories, et la
    somme des parts depasse le total.
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


@pytest.mark.parametrize(
    "extra",
    [
        pytest.param({"waiting_for_player": True}, id="waiting_for_target_selection"),
        pytest.param({}, id="activation_ended_without_firing"),
    ],
)
def test_a_shoot_payload_carrying_the_transition_still_pays_the_objective(
    extra: Dict[str, Any],
) -> None:
    """Un tir SANS attaque qui porte la transition doit quand meme payer l'objectif.

    CE QUI ETAIT MANQUE. Un tir n'arrive pas toujours ici en payload « pur » : lorsqu'il vide
    le pool, la cascade du moteur le fait traverser les phases suivantes jusqu'a
    `command_phase_start`, qui hors tour agent rend `command_phase_end` — la transition
    `phase_transition` + `next_phase == "move"` qui declenche le versement. La cascade
    REINJECTE `action`/`unitId`/`all_attack_results` dans ce resultat (w40k_core, bloc
    `preserved_combat_data`), donc le payload atteint la branche `shoot` en portant la
    transition, au lieu de partir par le chemin « reponse systeme » qui, lui, payait.
    Les trois sorties anticipees de cette branche renvoyaient `0.0` sec : les points etaient
    perdus, et `objective` les comptait quand meme.

    VERROU. Remettre `return 0.0` a la place de `return objective_turn_reward` sur la sortie
    correspondante fait passer ce test au ROUGE.

    CONTROLE NON VACANT : le montant attendu est recalcule depuis la config reelle et l'etat
    d'objectifs construit ici ; l'assertion `expected > 0` garantit qu'un zero signifierait
    vraiment « pas verse » et non « rien a verser ».
    """
    calc = _calculator(controlled_player=1)
    state = _game_state(turn=2, current_player=1, controlled_player=1, mine=2, theirs=1)
    for unit in state["units"]:
        unit["battle_shocked"] = False
        unit["RNG_WEAPONS"] = []
        unit["CC_WEAPONS"] = []
    state["action_logs"] = []
    state["objectives"] = []

    # Le VRAI payload de transition, produit par son unique producteur, augmente des cles que
    # la cascade reinjecte. Le recopier a la main le figerait le jour ou le producteur change.
    payload: Dict[str, Any] = dict(command_phase_end(state))
    payload.update({"action": "shoot", "unitId": "1", "all_attack_results": []})
    payload.update(extra)

    total = calc.calculate_reward(True, payload, state)
    breakdown = state["last_reward_breakdown"]
    expected = _expected_turn_reward(2, 1)

    assert expected > 0.0, "config sans reward d'objectif : le test ne mesure rien"
    assert total == pytest.approx(expected), "recompense d'objectif perdue sur la sortie anticipee"
    assert breakdown["objective"] == pytest.approx(expected)
    # La ventilation ne doit plus annoncer des points que le total ne verse pas.
    assert breakdown["total"] == pytest.approx(total)


def test_the_coherency_penalty_is_never_imputed_to_the_objective() -> None:
    """`objective_turn_reward` TRANSPORTE la penalite de coherency : elle ne doit pas y entrer.

    VERROU. Deplacer `reward_breakdown['objective'] += objective_turn_reward` APRES la ligne
    `objective_turn_reward += coherency_penalty` fait passer ce test au ROUGE : la part
    d'objectif devient nette de la penalite, et une escouade incoherente ferait baisser une
    mesure qui ne parle que de controle de terrain.
    """
    calc = _calculator(controlled_player=1)
    state = _game_state(turn=2, current_player=1, controlled_player=1, mine=2, theirs=1)
    state["squad_cache"]["1"]["is_coherent"] = False

    _total, breakdown = _pay(calc, state)
    incoherent_weight = float(_rewards_config()[AGENT]["squad_shaping"]["incoherent_weight"])

    assert incoherent_weight > 0.0, "poids nul : le test ne mesure rien"
    assert breakdown["objective"] == pytest.approx(_expected_turn_reward(2, 1))
    assert breakdown["penalties"] == pytest.approx(-incoherent_weight)
