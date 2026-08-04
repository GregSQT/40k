"""Chantier 04c — le bot FAIT ARRIVER ses reserves, et le win-rate se lit par roster.

Trois verrous, dans l'ordre des trois etapes du chantier :
  1. le bot joue un slot d'INGRESS (20.04) au lieu de renoncer, et jamais un slot ferme ;
  2. une variante de liste depassant le plafond 20.01 leve AU CHARGEMENT ;
  3. la ventilation du win-rate par roster somme bien au win-rate global.

Le verrou « une unite en reserves ARRIVE vraiment sur le plateau » est un episode complet :
il vit dans `test_bot_ingress_end_to_end`, en fin de fichier, et c'est le seul qui charge un
moteur — les autres sont des tests d'unite sur les fonctions de decision.
"""

from typing import Any, Dict, List

import pytest

import engine.macro_intents as mi
from ai.evaluation_bots import (
    AdaptiveBot,
    ControlBot,
    DefensiveBot,
    GreedyBot,
    RandomBot,
    TacticalBot,
    ValueTradeBot,
    WAIT_ACTION,
)

ALL_BOTS = [RandomBot, GreedyBot, DefensiveBot, ControlBot, AdaptiveBot, ValueTradeBot, TacticalBot]


#: `randomness` NON NULLE, et c'est le coeur du verrou. Les bots ont une clause d'exploration
#: qui court-circuite leur doctrine (`_random_escape_action`), et 5 d'entre eux l'evaluaient
#: AVANT leur branche `deployment` : leur tirage tombait alors sur `WAIT_ACTION`, c'est-a-dire
#: sur la decision 20.01 de mise en reserves. Un test a `randomness=0.0` ne peut pas le voir —
#: il ne traverse jamais cette clause. Valeur superieure aux `randomness` configures (0.15 en
#: entrainement, 0.05 pour le holdout) pour que la fuite, si elle revenait, soit certaine.
#:
#: Depuis le routage de la mise en place par le wrapper, cette clause ne PEUT plus voir un masque
#: de deploiement : c'est ce que verrouille `test_wrapper_never_offers_wait_at_deployment`, et
#: c'est pour cela qu'il ne s'appuie plus sur une liste de bots tenue a la main.
EXPLORATION_RANDOMNESS = 0.5


def _bot(cls, randomness: float = EXPLORATION_RANDOMNESS):
    """RandomBot n'a pas de `randomness` : il EST le tirage uniforme."""
    return cls() if cls is RandomBot else cls(randomness=randomness)


def _deployment_state() -> Dict[str, Any]:
    return {"phase": "deployment", "episode_number": 1}


# --------------------------------------------------------------------------------------
# Etape 1 — politique de mise en place des bots
# --------------------------------------------------------------------------------------


def _bare_wrapper():
    """`BotControlledEnv` nu : la mise en place ne lit ni le moteur ni le masque memoise."""
    from ai.env_wrappers import BotControlledEnv

    return BotControlledEnv.__new__(BotControlledEnv)


@pytest.mark.parametrize("bot_cls", ALL_BOTS, ids=lambda c: c.__name__)
def test_no_bot_ever_puts_a_unit_in_strategic_reserves(bot_cls) -> None:
    """20.01 est une decision de LISTE, jamais une decision de bot.

    Le masque de deploiement ouvre `SQUAD_ACTION_WAIT` des qu'une unite tient sous le plafond
    de 50 % (`ActionDecoder.get_squad_action_mask_and_eligible_units`) : jouer WAIT y MET
    L'UNITE EN RESERVES. TacticalBot, faute de branche `deployment`, tombait sur sa clause de
    repli `WAIT if WAIT in valid_actions` et reservait donc 100 % de ce qu'il pouvait.

    Le test passe par le WRAPPER (`_select_bot_deploy_action`) et non plus par
    `select_action_with_state` : c'est lui qui porte desormais l'invariant, et c'est le chemin
    reellement joue en entrainement. Un bot n'a plus l'occasion de se tromper.
    """
    valid_actions = list(mi.DEPLOY_SLOTS) + [WAIT_ACTION]
    wrapper = _bare_wrapper()
    bot = _bot(bot_cls)
    chosen = {
        wrapper._select_bot_deploy_action(_deployment_state(), valid_actions, bot=bot)
        for _ in range(2000)
    }
    assert WAIT_ACTION not in chosen, (
        f"{bot_cls.__name__} met une unite en reserves stratégiques de sa propre initiative"
    )
    assert chosen <= set(mi.DEPLOY_SLOTS)


def test_wrapper_never_offers_wait_at_deployment() -> None:
    """L'invariant STRUCTUREL, celui qui ne depend d'aucune liste de bots.

    Le test ci-dessus enumere `ALL_BOTS` — une liste tenue a la main, donc un 8e bot oublie la
    contournerait. Celui-ci verifie ce que le wrapper TRANSMET : quel que soit le bot, il ne voit
    que des slots de pose. C'est ce qui rend l'oubli impossible, et non plus seulement detecte.
    """
    spy = _SpyBot(answer=mi.DEPLOY_SLOT_BASE + 2)
    valid_actions = [mi.DEPLOY_SLOT_BASE, mi.DEPLOY_SLOT_BASE + 2, WAIT_ACTION]

    chosen = _bare_wrapper()._select_bot_deploy_action(
        _deployment_state(), valid_actions, bot=spy
    )

    assert chosen == mi.DEPLOY_SLOT_BASE + 2
    assert spy.seen == [[mi.DEPLOY_SLOT_BASE, mi.DEPLOY_SLOT_BASE + 2]], (
        "WAIT (= mise en reserves 20.01) ne doit jamais etre propose au bot"
    )


def test_wrapper_raises_at_deployment_without_any_open_slot() -> None:
    """Deploiement sans slot de pose = defaut MOTEUR, jamais un repli en WAIT.

    Difference assumee avec l'ingress, ou le pool vide est un etat de jeu normal (l'unite reste
    en reserves et retentera au round suivant, cf. `test_wrapper_waits_when_no_ingress_slot_is_open`).
    Au deploiement le decodeur leve « Deployment deadlock » avant ; se replier sur WAIT ici
    mettrait justement l'unite en reserves — le defaut qu'on corrige.
    """
    spy = _SpyBot(answer=mi.DEPLOY_SLOT_BASE)
    with pytest.raises(RuntimeError, match="deploiement"):
        _bare_wrapper()._select_bot_deploy_action(_deployment_state(), [WAIT_ACTION], bot=spy)
    assert spy.seen == [], "aucun slot ouvert : le bot ne doit pas etre interroge"


@pytest.mark.parametrize("bot_cls", ALL_BOTS, ids=lambda c: c.__name__)
def test_placement_never_returns_a_closed_slot(bot_cls) -> None:
    """Un slot FERME ne doit jamais etre joue.

    `open_deploy_slot_count = min(5, nb_hexes_valides)` : un pool d'ingress de 2 hexes n'ouvre
    que les slots 4 et 5. Le bot ne choisit que dans ce qu'on lui passe, et l'appelant ne lui
    passe que les bits a True du masque.
    """
    open_slots = [mi.DEPLOY_SLOT_BASE, mi.DEPLOY_SLOT_BASE + 1]
    bot = _bot(bot_cls)
    chosen = {
        bot.select_placement_action(open_slots, _deployment_state()) for _ in range(200)
    }
    assert chosen <= set(open_slots), f"{bot_cls.__name__} a joue un slot ferme : {chosen}"


@pytest.mark.parametrize("bot_cls", ALL_BOTS, ids=lambda c: c.__name__)
def test_placement_refuses_a_pool_it_has_not_been_promised(bot_cls) -> None:
    """CONTRAT d'entree : un pool non vide de slots 4-8, et rien d'autre.

    Le nettoyage se fait une seule fois chez l'appelant (`BotControlledEnv._ask_bot_placement`).
    Les bots ne le refont pas — ils VERIFIENT. Un appelant qui transmettrait le masque brut leve
    donc ici, au lieu de laisser un bot tirer `WAIT_ACTION` (= mise en reserves 20.01) en silence :
    filtrer sans rien dire reproduirait le defaut du chantier 04c sous une autre forme.
    """
    with pytest.raises(ValueError):
        _bot(bot_cls).select_placement_action([WAIT_ACTION], _deployment_state())
    with pytest.raises(ValueError):
        _bot(bot_cls).select_placement_action([], _deployment_state())


def test_tactical_bot_placement_is_frozen_on_the_first_open_slot() -> None:
    """TacticalBot est le HOLDOUT, le metre etalon : sa politique de pose est GELEE.

    « Premier slot ouvert » est exactement ce qu'il jouait avant que le masque n'ouvre WAIT.
    Lui donner une table de poids comme aux autres bots changerait le metre et rendrait
    incomparables toutes les mesures anterieures (cf. config/bot_movement_weights.json).
    """
    # randomness=0.0 ICI, et seulement ici : ce test decrit la doctrine DETERMINISTE du holdout,
    # pas le comportement sous exploration (couvert par le test de non-mise-en-reserves).
    bot = TacticalBot(randomness=0.0)
    state = _deployment_state()
    assert {bot.select_placement_action(list(mi.DEPLOY_SLOTS), state) for _ in range(50)} == {
        mi.DEPLOY_SLOT_BASE
    }
    later_slots = [mi.DEPLOY_SLOT_BASE + 2, mi.DEPLOY_SLOT_BASE + 4]
    assert bot.select_placement_action(later_slots, state) == mi.DEPLOY_SLOT_BASE + 2


def test_weighted_bots_spread_their_placement_over_the_open_slots() -> None:
    """VERT VACANT : un bot qui repondrait toujours le meme slot passerait les tests ci-dessus.

    On verifie que la politique ponderee est REELLEMENT tiree — sans quoi « le bot garde sa
    personnalite a l'ingress » serait une affirmation sans mesure.
    """
    bot = GreedyBot(randomness=0.0)
    state = _deployment_state()
    chosen = {bot.select_placement_action(list(mi.DEPLOY_SLOTS), state) for _ in range(300)}
    assert len(chosen) >= 3, f"politique degeneree : {chosen}"


# --------------------------------------------------------------------------------------
# Etape 1 (suite) — le wrapper route l'ingress vers la politique de pose
# --------------------------------------------------------------------------------------


class _SpyBot:
    """Bot minimal qui ENREGISTRE ce que le wrapper lui transmet."""

    def __init__(self, answer: int) -> None:
        self.answer = answer
        self.seen: List[List[int]] = []

    def select_placement_action(self, valid_actions, game_state) -> int:
        self.seen.append(list(valid_actions))
        return self.answer

    def select_movement_destination(self, unit, valid_destinations, game_state=None):
        raise AssertionError(
            "une escouade en reserves n'a pas de destination de move : le wrapper ne doit "
            "jamais passer par select_movement_destination"
        )


def _wrapper_with_reserves(monkeypatch, in_reserves: bool):
    """`BotControlledEnv` nu — on n'exerce que `_select_bot_move_action`, pas un episode."""
    from ai.env_wrappers import BotControlledEnv
    import engine.phase_handlers.shared_utils as shared_utils

    monkeypatch.setattr(
        shared_utils, "unit_is_in_strategic_reserves", lambda game_state, squad_id: in_reserves
    )
    return BotControlledEnv.__new__(BotControlledEnv)


def test_wrapper_sends_only_the_open_slots_to_the_bot(monkeypatch) -> None:
    """Le bot ne recoit QUE les slots a True dans le masque.

    C'est ce qui rend impossible le jeu d'un slot ferme, meme par un bot qui ignorerait la
    liste transmise : `validate_action_against_mask` le rattraperait, mais en abattant le run.
    """
    wrapper = _wrapper_with_reserves(monkeypatch, in_reserves=True)
    spy = _SpyBot(answer=mi.DEPLOY_SLOT_BASE + 1)
    # Masque d'ingress realiste : deux slots ouverts sur cinq, plus WAIT (renoncer est legal).
    valid_actions = [mi.DEPLOY_SLOT_BASE, mi.DEPLOY_SLOT_BASE + 1, mi.ACTION_WAIT]

    chosen = wrapper._select_bot_move_action(
        {"phase": "move"}, {"id": "101"}, valid_actions, bot=spy
    )

    assert chosen == mi.DEPLOY_SLOT_BASE + 1
    assert spy.seen == [[mi.DEPLOY_SLOT_BASE, mi.DEPLOY_SLOT_BASE + 1]], (
        "WAIT et les slots fermes ne doivent pas etre proposes au bot"
    )


def test_wrapper_waits_when_no_ingress_slot_is_open(monkeypatch) -> None:
    """Pool d'ingress vide = etat de jeu NORMAL : l'unite reste en reserves, WAIT.

    `ingress_slot_candidates` rend {} quand aucune destination legale n'existe a ce round.
    """
    wrapper = _wrapper_with_reserves(monkeypatch, in_reserves=True)
    spy = _SpyBot(answer=mi.DEPLOY_SLOT_BASE)

    chosen = wrapper._select_bot_move_action(
        {"phase": "move"}, {"id": "101"}, [mi.ACTION_WAIT], bot=spy
    )

    assert chosen == mi.ACTION_WAIT
    assert spy.seen == [], "aucun slot ouvert : le bot ne doit pas etre interroge"


def test_wrapper_raises_when_the_bot_cannot_place(monkeypatch) -> None:
    """Bot sans politique de pose = erreur explicite, jamais un renoncement silencieux."""

    class _MuteBot:
        def select_movement_destination(self, unit, valid_destinations, game_state=None):
            raise AssertionError("chemin de move interdit ici")

    wrapper = _wrapper_with_reserves(monkeypatch, in_reserves=True)
    with pytest.raises(RuntimeError, match="select_placement_action"):
        wrapper._select_bot_move_action(
            {"phase": "move"}, {"id": "101"}, [mi.DEPLOY_SLOT_BASE], bot=_MuteBot()
        )


def test_deploy_slot_ids_overlap_move_cell_ids() -> None:
    """Le fait qui rendait le defaut invisible, verrouille pour qu'il ne se reperde pas.

    Les ids 4-8 sont A LA FOIS des slots de mise en place et des cellules de move : « la liste
    des cellules de move est-elle vide » NE PEUT PAS distinguer une escouade en reserves d'une
    escouade posee et bloquee. Seul `unit_is_in_strategic_reserves` le peut. Si ce recouvrement
    disparaissait un jour, la branche d'ingress du wrapper devrait etre relue.
    """
    assert set(mi.DEPLOY_SLOTS) <= set(mi.MOVE_CELLS)


# --------------------------------------------------------------------------------------
# Etape 2 — le plafond 20.01 refuse une variante illegale AU CHARGEMENT
# --------------------------------------------------------------------------------------


def _unit(uid: int, player: int, value: int, in_reserves: bool) -> Dict[str, Any]:
    return {
        "id": uid,
        "player": player,
        "VALUE": value,
        "unitType": f"Unit{uid}",
        "in_strategic_reserves": in_reserves,
    }


def test_reserve_cap_names_the_units_and_the_total() -> None:
    """Depassement = erreur NOMMANT les unites et le total. Tronquer la liste deciderait a la
    place du joueur et masquerait une liste illegale."""
    from engine.game_state import validate_strategic_reserves_cap

    units = [
        _unit(1, 1, 180, in_reserves=True),
        _unit(2, 1, 150, in_reserves=True),
        _unit(3, 1, 200, in_reserves=False),
    ]
    with pytest.raises(ValueError) as excinfo:
        validate_strategic_reserves_cap(units, points_limit=500, context="test")

    message = str(excinfo.value)
    assert "330" in message, "le total engage doit apparaitre"
    assert "250" in message, "le plafond doit apparaitre"
    assert "Unit1" in message and "Unit2" in message, "les unites en cause doivent etre nommees"
    assert "Unit3" not in message, "une unite HORS reserves n'a pas a etre nommee"


def test_reserve_cap_accepts_exactly_the_cap() -> None:
    """Le plafond est un « > », pas un « >= » : 250/250 est une liste legale."""
    from engine.game_state import validate_strategic_reserves_cap

    validate_strategic_reserves_cap(
        [_unit(1, 1, 250, in_reserves=True)], points_limit=500, context="test"
    )


def test_reserve_cap_is_per_player() -> None:
    """Le plafond porte sur CHAQUE joueur : deux camps a 200 ne se cumulent pas a 400."""
    from engine.game_state import validate_strategic_reserves_cap

    validate_strategic_reserves_cap(
        [_unit(1, 1, 200, in_reserves=True), _unit(101, 2, 200, in_reserves=True)],
        points_limit=500,
        context="test",
    )


# --------------------------------------------------------------------------------------
# Etape 3 — la ventilation par roster somme au win-rate global
# --------------------------------------------------------------------------------------


def _task_result(bot_name: str, wins: int, total: int, agent_roster: str, opp_roster: str):
    return {
        "bot_name": bot_name,
        "wins": wins,
        "losses": total - wins,
        "draws": 0,
        "faction_stats": {},
        "roster_stats": {
            "agent": {agent_roster: {"wins": wins, "total": total}},
            "opponent": {opp_roster: {"wins": wins, "total": total}},
        },
    }


def test_roster_win_rates_sum_back_to_the_global_win_rate() -> None:
    """CONTROLE DE COHERENCE exige par le chantier : la ventilation par roster ne peut pas
    raconter autre chose que l'agregat, puisqu'elle derive du MEME comptage d'episodes."""
    import ai.bot_evaluation as be

    results = [
        _task_result("greedy", wins=6, total=10, agent_roster="ros_a", opp_roster="opp_a"),
        _task_result("greedy", wins=2, total=10, agent_roster="ros_b", opp_roster="opp_b"),
    ]
    tally = be._roster_bot_tally(results, ("greedy",), "agent")
    per_roster = be._compute_bot_win_rates(tally)

    assert per_roster == {"ros_a": {"greedy": 0.6}, "ros_b": {"greedy": 0.2}}

    total_wins = sum(w for per_bot in tally.values() for w, _ in per_bot.values())
    total_played = sum(t for per_bot in tally.values() for _, t in per_bot.values())
    global_wins = sum(r["wins"] for r in results)
    global_played = sum(r["wins"] + r["losses"] + r["draws"] for r in results)
    assert (total_wins, total_played) == (global_wins, global_played)


def test_roster_win_rates_separate_the_two_sides() -> None:
    """Les deux cotes repondent a deux questions differentes : UTILISER ses reserves (roster de
    l'agent) et ENCAISSER une arrivee (roster de l'adversaire). Les melanger les rend illisibles."""
    import ai.bot_evaluation as be

    results = [_task_result("greedy", 3, 4, agent_roster="ros_sm", opp_roster="opp_ork_reserves")]
    assert set(be._roster_bot_tally(results, ("greedy",), "agent")) == {"ros_sm"}
    assert set(be._roster_bot_tally(results, ("greedy",), "opponent")) == {"opp_ork_reserves"}
    with pytest.raises(ValueError):
        be._roster_bot_tally(results, ("greedy",), "both")


def test_roster_win_rates_skip_cells_without_episodes() -> None:
    """Un couple (roster, bot) sans episode joue n'est pas publie : un 0.0 y serait invente."""
    import ai.bot_evaluation as be

    assert be._compute_bot_win_rates({"ros_a": {"greedy": [0, 0]}}) == {"ros_a": {}}


def test_failed_task_result_carries_both_roster_sides() -> None:
    """Un TIMEOUT n'est pas un bug : le training CONTINUE. Les deux cotes doivent donc exister
    meme vides, sinon `_roster_bot_tally` tuerait le run sur un require_key."""
    import ai.bot_evaluation as be

    failed = be._failed_task_result({"n_episodes": 4, "bot_name": "greedy"}, "sc", timeout=True)
    assert failed["roster_stats"] == {"agent": {}, "opponent": {}}
    assert be._roster_bot_tally([failed], ("greedy",), "agent") == {}


# --------------------------------------------------------------------------------------
# VERT VACANT — l'unite en reserves arrive VRAIMENT sur le plateau
# --------------------------------------------------------------------------------------


@pytest.mark.integration
def test_bot_ingress_end_to_end() -> None:
    """Episode COMPLET : une unite en reserves du bot doit finir POSEE sur le plateau.

    Le reste du fichier prouve que le code de decision est correct ; seul ce test prouve qu'il
    est ATTEINT par le vrai chemin, et que l'arrivee est commitee dans l'etat. Sans lui, « le
    bot fait son ingress » resterait une affirmation sur du code, pas sur une partie.

    Verrou verifie a la main sur le code d'origine : sans la branche d'ingress du wrapper,
    l'episode leve `read_squad_move_cell_map: aucune carte de cellules pour squad 101` au
    step 30 — les slots d'ingress 4-8 etant lus comme des cellules de move.
    """
    import random

    import numpy as np

    from ai.bot_evaluation import _create_eval_env

    scenario = "config/agents/ArmageddonAgent/scenarios/training/reserves_ingress_fixture.json"
    env = _create_eval_env(
        bot_name="greedy",
        bot_type="greedy",
        randomness_config={"greedy": 0.0},
        scenario_file=scenario,
        training_config_name="x1",
        rewards_config_name="default",
        controlled_agent="ArmageddonAgent",
        base_agent_key="ArmageddonAgent",
        debug_mode=False,
        agent_seat_mode="p1",
        agent_seat_seed=1234,
    )
    try:
        random.seed(7)
        np.random.seed(7)
        env.reset()

        bot_player = env.bot_player
        reserve_ids = [
            str(u["id"])
            for u in env.engine.game_state["units"]
            if u.get("in_strategic_reserves") and int(u["player"]) == int(bot_player)
        ]
        # VERT VACANT : sans cette assertion, un roster sans reserves ferait passer le test.
        assert reserve_ids, (
            "la liste de l'adversaire ne declare aucune reserve : le test ne prouverait rien"
        )

        done = False
        steps = 0
        while not done and steps < 8000:
            mask = np.asarray(env.action_masks())
            legal = np.flatnonzero(mask).tolist()
            assert legal, "masque vide : le moteur doit avancer la phase"
            _, _, terminated, truncated, _ = env.step(int(random.choice(legal)))
            done = terminated or truncated
            steps += 1
        assert done, "l'episode n'a pas termine dans le budget de steps"

        by_id = {str(u["id"]): u for u in env.engine.game_state["units"]}
        arrived = []
        for uid in reserve_ids:
            unit = by_id.get(uid)
            if unit is None:
                continue  # detruite en cours de partie : elle etait bien sur le plateau avant
            if unit.get("deployed_on_turn") is not None:
                assert not unit["in_strategic_reserves"], (
                    f"unite {uid} posee mais toujours marquee en reserves"
                )
                assert int(unit["col"]) >= 0 and int(unit["row"]) >= 0, (
                    f"unite {uid} posee sans position reelle : {unit.get('col')},{unit.get('row')}"
                )
                arrived.append(uid)

        assert arrived, (
            f"aucune des reserves du bot {reserve_ids} n'est arrivee sur le plateau — le bot "
            f"decline son ingress move (20.04)"
        )
    finally:
        env.close()


@pytest.mark.integration
def test_bot_deployment_never_reserves_on_the_real_path(monkeypatch) -> None:
    """VRAI CHEMIN du deploiement : le bot ne met JAMAIS une unite en reserves de lui-meme.

    Le reste du fichier prouve que `_select_bot_deploy_action` est correct ; seul ce test prouve
    qu'il est ATTEINT par `_get_bot_action` en phase de deploiement, et que le bot y decide
    vraiment. Deux conditions doivent etre reunies pour que le defaut soit VISIBLE, et les deux
    sont ASSERTEES plus bas — sans elles le test serait un vert vacant :
      1. le deploiement doit etre ACTIF. Le scheduler par-episode (rampe fixed<->active) rend
         « fixed » en debut de training : la phase de deploiement n'existe alors pas du tout et
         `_get_bot_action` n'y est jamais appele. D'ou l'imposition du mode.
      2. `WAIT_ACTION` doit etre OUVERT dans le masque de deploiement du bot. Il ne l'est que
         sous le plafond 20.01 (50 % des points) : une liste qui declare deja ses reserves — la
         fixture d'ingress ci-dessus, par exemple — le ferme, et le bot ne peut alors PAS se
         tromper.

    MESURE du defaut, branche `deployment` du wrapper retiree, 5 episodes de ce scenario : WAIT
    ouvert 9 fois sur 27 deploiements du bot, et JOUE 8 fois. Branche remise : ouvert 25 fois sur
    28, joue 0. Ce test tourne sur le meme montage.
    """
    import random

    import numpy as np

    from ai.bot_evaluation import _create_eval_env
    from ai.env_wrappers import BotControlledEnv
    from engine.w40k_core import W40KEngine

    # (1) Deploiement ACTIF impose : sans cela il n'y a pas de phase de deploiement a observer.
    monkeypatch.setattr(
        W40KEngine, "_configure_deployment_mode_for_episode", lambda self: "active"
    )

    wait_was_open = 0
    original = BotControlledEnv._get_bot_action

    def spy(self, debug=False, decision=None, bot=None):
        nonlocal wait_was_open
        game_state = self.engine.game_state
        if game_state["phase"] == "deployment":
            if decision is not None:
                mask = decision.action_mask
            else:
                mask, _ = self.engine.action_decoder.get_squad_action_mask_and_eligible_units(
                    game_state
                )
            if bool(np.asarray(mask, dtype=bool)[WAIT_ACTION]):
                wait_was_open += 1
        return original(self, debug=debug, decision=decision, bot=bot)

    monkeypatch.setattr(BotControlledEnv, "_get_bot_action", spy)

    scenario = "config/agents/ArmageddonAgent/scenarios/training/scenario_training_armageddon.json"
    env = _create_eval_env(
        bot_name="tactical",
        bot_type="tactical",
        randomness_config={"tactical": 0.05},
        scenario_file=scenario,
        training_config_name="x1",
        rewards_config_name="default",
        controlled_agent="ArmageddonAgent",
        base_agent_key="ArmageddonAgent",
        debug_mode=False,
        agent_seat_mode="p1",
        agent_seat_seed=1234,
    )
    try:
        random.seed(11)
        np.random.seed(11)
        env.reset()
        assert env.engine.game_state["phase"] == "deployment", (
            "le scenario ne demarre pas en deploiement : le test n'observerait rien"
        )
        bot_player = int(env.bot_player)
        assert not [
            u
            for u in env.engine.game_state["units"]
            if int(u["player"]) == bot_player and u.get("in_strategic_reserves")
        ], "la liste du bot declare deja des reserves : impossible de distinguer sa decision"

        # On ne joue QUE la phase de deploiement : le reste de la partie n'apporte rien a cet
        # invariant, et l'agent y joue au hasard.
        steps = 0
        while env.engine.game_state["phase"] == "deployment" and steps < 400:
            mask = np.asarray(env.action_masks())
            legal = np.flatnonzero(mask).tolist()
            assert legal, "masque vide : le moteur doit avancer la phase"
            _, _, terminated, truncated, _ = env.step(int(random.choice(legal)))
            steps += 1
            if terminated or truncated:
                break

        # (2) VERT VACANT : sans WAIT ouvert au moins une fois, le bot n'a jamais eu l'occasion
        # de se tromper et l'assertion finale ne prouverait rien.
        assert wait_was_open > 0, (
            "WAIT (= mise en reserves 20.01) n'a jamais ete ouvert dans un masque de "
            "deploiement du bot : le test ne prouve rien"
        )
        reserved = [
            str(u["id"])
            for u in env.engine.game_state["units"]
            if int(u["player"]) == bot_player and u.get("in_strategic_reserves")
        ]
        assert not reserved, (
            f"le bot a mis {reserved} en reserves stratégiques de sa propre initiative : la "
            "decision 20.01 appartient a la LISTE, jamais au bot"
        )
    finally:
        env.close()
