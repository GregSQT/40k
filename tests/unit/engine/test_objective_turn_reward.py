"""Tests — versement du reward d'objectif par tour (multiple exact des VP du primaire).

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
from engine.game_state import primary_objective_points
from engine.phase_handlers.command_handlers import command_phase_end
from engine.reward_calculator import RewardCalculator

AGENT = "ArmageddonAgent"

# La mission REELLE, pas une recopie. Le versement vaut `facteur x VP marques` : un `rules: []`
# code en dur ici — ce qu'il y avait avant, du temps ou seule la formule lineaire etait testee —
# ferait valoir 0 a chaque versement et rendrait tout ce fichier vert sans rien mesurer.
PRIMARY_OBJECTIVE: Dict[str, Any] = get_config_loader().load_primary_objective_config(
    "objectives_control"
)


def _objective_controllers(mine: int, theirs: int, controlled_player: int) -> Dict[str, Any]:
    """Etat 14.02 fige : `objective_controllers`, tel que le scoring vient de l'ecrire.

    Le reward le LIT, il ne le recalcule pas — un recomptage reecrirait le
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
    """Le versement vaut `objective_reward_factor x VP marques ce tour`.

    Le montant n'est PAS recalcule ici a partir des regles : il passe par la meme fonction que le
    moteur de scoring et que le versement (`primary_objective_points`). Une seconde
    implementation dans le test rendrait vert le jour ou les deux autres divergeraient — c'est
    precisement le defaut qu'on vient de corriger.
    """
    factor = float(_objective_rewards()["objective_reward_factor"])
    return factor * primary_objective_points(PRIMARY_OBJECTIVE["scoring"], mine, theirs)


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
    un recomptage via `calculate_objective_control`, ce test leverait au lieu de passer.
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
    """La regle `control_more_than_opponent` compte : meme nombre tenu, deux montants."""
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

    La version proportionnelle retirait le montant d'avance par objectif de retard — une
    penalite que ni la config ni la regle de score ne prevoient.
    """
    calc = _calculator(controlled_player=1)
    state = _game_state(turn=2, current_player=1, controlled_player=1, mine=1, theirs=3)

    _total, breakdown = _pay(calc, state)

    assert breakdown["objective"] == pytest.approx(_expected_turn_reward(1, 3))
    assert breakdown["objective"] > 0.0, "tenir un objectif reste paye, meme en retard"


def test_the_payout_is_a_staircase_capped_like_the_mission() -> None:
    """Tenir 2, 3, 4 ou 5 objectifs avec la meme avance rapporte EXACTEMENT la meme chose.

    LE DEFAUT CORRIGE. Le versement etait `reward_per_objective * mes_objectifs`, LINEAIRE et
    sans plafond, alors que la mission est un escalier plafonne : 5 VP si >=1, 5 si >=2, 5 si
    j'en tiens plus que lui, 15 au maximum. Au-dela de 2 objectifs le jeu ne paie plus rien et
    la recompense continuait de monter de 10 par zone — l'agent etait paye pour s'etaler sur des
    objectifs que la mission ne compte pas, au lieu de consolider et de priver l'adversaire.

    VERROU. En remettant `total_reward = reward_per_objective * controlled_objectives` dans
    `_calculate_objective_reward_per_turn`, ce test passe au ROUGE : les quatre montants
    deviennent 20 / 30 / 40 / 50 au lieu d'etre egaux.

    CONTROLE NON VACANT : `expected > 0` garantit qu'une egalite a zero (mission sans regle,
    versement mort) ne passerait pas pour une egalite valide.
    """
    expected = _expected_turn_reward(2, 1)
    assert expected > 0.0, "versement nul : l'egalite testee ne prouverait rien"

    payouts = []
    for mine in (2, 3, 4, 5):
        _total, breakdown = _pay(
            _calculator(controlled_player=1),
            _game_state(turn=2, current_player=1, controlled_player=1, mine=mine, theirs=1),
        )
        payouts.append(breakdown["objective"])

    for mine, paid in zip((2, 3, 4, 5), payouts):
        assert paid == pytest.approx(expected), f"{mine} objectifs paye {paid}, attendu {expected}"


def test_the_payout_is_exactly_the_scored_vp_times_the_factor() -> None:
    """Le montant verse est le multiple exact des VP que le moteur attribue au meme instant.

    C'est ce qui rend `01_VP/f_obj_rewards` lisible sur les VP au lieu de rejouer une formule :
    si cette identite tombe, la courbe ment. On compare donc au scoring REEL du moteur
    (`primary_objective_points`, la fonction qu'appelle `_apply_primary_objective_scoring_single`
    pour ecrire les VP), pas a une formule reecrite ici.
    """
    factor = float(_objective_rewards()["objective_reward_factor"])
    for mine, theirs in ((0, 2), (1, 1), (2, 1), (2, 3), (3, 0)):
        _total, breakdown = _pay(
            _calculator(controlled_player=1),
            _game_state(turn=2, current_player=1, controlled_player=1, mine=mine, theirs=theirs),
        )
        scored_vp = primary_objective_points(PRIMARY_OBJECTIVE["scoring"], mine, theirs)
        assert breakdown["objective"] == pytest.approx(factor * scored_vp), (
            f"{mine} contre {theirs} : verse {breakdown['objective']}, "
            f"VP marques {scored_vp} x {factor}"
        )


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


def _move_state(controlled_player: int = 1, model_col: int = 5, model_row: int = 5) -> Dict[str, Any]:
    """Etat de phase move avec UN objectif non controle, ou l'unite 1 a une FIGURINE posee.

    Le bonus « sur un objectif » se juge PAR FIGURINE (14.02, empreinte de socle) et non sur
    l'ancre d'escouade : l'etat doit donc porter `models_cache` / `squad_models`, sinon le
    lecteur leve. C'est `model_col`/`model_row` qui decide de la presence dans la zone — l'ancre
    de `units_cache` reste volontairement AILLEURS (1,1), pour que ce fichier casse si quelqu'un
    revenait a une lecture par ancre.
    """
    state = _game_state(turn=2, current_player=controlled_player, controlled_player=controlled_player)
    state["phase"] = "move"
    state["objectives"] = [{"id": "obj_move", "hexes": [{"col": 5, "row": 5}]}]
    # Zone non controlee : `get_objective_control` < 1.0 est la condition du bonus.
    state["objective_controllers"] = {}
    opponent = 2 if controlled_player == 1 else 1
    state["units_cache"]["1"]["orientation"] = 0
    state["units_cache"]["2"]["orientation"] = 0
    state["squad_models"] = {"1": ["m1"], "2": ["m2"]}
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


def test_the_on_objective_bonus_reads_the_models_not_the_squad_anchor() -> None:
    """Une FIGURINE dans la zone suffit, meme si l'ancre d'escouade est ailleurs (14.02).

    LE DEFAUT CORRIGE. Le bonus comparait la DESTINATION d'escouade a un hexe d'objectif par
    egalite stricte de coordonnees. Deux erreurs cumulees : l'ancre n'est pas une figurine, et
    l'egalite de centre ignore l'empreinte de socle — alors que le decompte de controle du meme
    moteur (`sum_objective_control_oc_multi`) compte une figurine des qu'une case de son socle
    recouvre la zone. Une escouade etalee etait donc COMPTEE par le moteur et PAS payee par la
    recompense, dans le meme etat de jeu.

    VERROU. En remettant la comparaison `h_col == to_col and h_row == to_row` dans
    `_calculate_on_objective_reward`, ce test passe au ROUGE : la destination (1,1) ne tombe sur
    aucun hexe d'objectif, donc le bonus vaut 0.

    Le cas MIROIR est verifie juste apres : ancre sur la zone, aucune figurine dedans -> rien.
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
    """Miroir : destination sur l'hexe d'objectif, mais aucune figurine dedans -> rien.

    C'est l'autre moitie du defaut d'ancre : l'ancienne lecture payait des que la DESTINATION
    tombait sur la zone, y compris quand aucune figurine vivante ne s'y trouvait. Sans ce
    controle, un lecteur qui rendrait « vrai » en permanence passerait le test precedent.
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


def test_an_opponent_action_that_ends_the_game_still_pays_the_objective() -> None:
    """Partie terminee par l'ADVERSAIRE : le versement d'objectif du tour doit etre paye.

    CE QUI ETAIT MANQUE. Sur le chemin « action adverse », la sortie `game_over` renvoyait
    `situational + defensive_penalty` — sans `objective_turn_reward`, alors que la sortie
    jumelle deux lignes plus bas (partie non terminee) l'inclut. Les points etaient perdus POUR
    DE BON : `objective_rewarded_turns` a deja consomme le tour, donc aucun autre chemin ne les
    versera, et `breakdown['objective']` les a deja credites — la ventilation annoncait une part
    que le total ne payait pas. Meme defaut que sur les trois sorties anticipees du tir.

    VERROU. En retirant `+ objective_turn_reward` de cette sortie, ce test passe au ROUGE :
    le total tombe a la seule recompense terminale.

    CONTROLE NON VACANT : `expected_objective > 0` garantit qu'un total egal au terminal seul ne
    puisse pas passer pour un versement correct, et la penalite defensive est nulle par
    construction (aucun evenement de degats) pour isoler le terme mesure.
    """
    controlled = 1
    calc = _calculator(controlled_player=controlled)
    # Le vainqueur vient du state_manager, comme en production (`_determine_winner` lui delegue).
    # Sans lui, la logique de repli tranche a l'ELIMINATION : il faudrait tuer toutes les unites
    # de l'agent pour obtenir un vainqueur, or une partie sans unite controlee ne verse aucun
    # objectif — le test ne mesurerait plus rien. Ici la partie se termine avec les deux camps
    # vivants (fin de tour 5), le cas exact ou le versement d'objectif est en jeu.
    class _WinnerStateManager:
        def determine_winner_with_method(self, _game_state: Dict[str, Any]):
            return controlled, "primary_objective"

    calc.state_manager = _WinnerStateManager()
    state = _game_state(
        turn=2, current_player=controlled, controlled_player=controlled, mine=2, theirs=1
    )
    state["game_over"] = True

    # Payload d'une action ADVERSE portant la transition de fin de phase command — la cascade
    # du moteur reinjecte `action`/`unitId` dans ce resultat (cf. le test du tir ci-dessus).
    payload: Dict[str, Any] = dict(command_phase_end(state))
    payload.update({
        "action": "squad_shoot",
        "unitId": "2",  # unite de l'adversaire : c'est ce qui aiguille vers le chemin teste
        "shoot_result": {"events": [], "squads_wiped": [], "targets_meta": {}},
    })

    total = calc.calculate_reward(True, payload, state)
    breakdown = state["last_reward_breakdown"]
    expected_objective = _expected_turn_reward(2, 1)

    assert expected_objective > 0.0, "versement nul : le test ne mesure rien"
    assert breakdown["penalties"] == pytest.approx(0.0), "penalite defensive non nulle : terme parasite"
    assert breakdown["objective"] == pytest.approx(expected_objective)
    assert total == pytest.approx(breakdown["situational"] + expected_objective)
    assert breakdown["total"] == pytest.approx(total), "la ventilation annonce ce que le total verse"


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
