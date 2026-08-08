"""
Verrous du shaping zone-intent : l'intent est paye sur son RESULTAT, pas sur l'etat herite.

LE DEFAUT CORRIGE ICI. `compute_zone_intent_shaping` lisait `get_objective_control` en COMMAND
PHASE, au moment meme ou l'agent declarait ses intents — donc avant qu'il ait joue son tour, et
sur un controle fige a la fin du tour precedent (14.02 : le controle n'est reevalue qu'aux
frontieres de phase/tour). Le versement etait entierement determine par l'etat herite :
declarer DEFEND sur une zone deja tenue rapportait +0.2 que l'agent la defende OU l'abandonne.

Le terme recompensait donc la DESCRIPTION de l'etat, pas sa TRANSFORMATION. Sa politique
optimale consistait a recopier `objective_controllers` en intents sans changer une seule action
tactique — et cette politique creuse produit exactement la signature qu'une bonne politique
produirait sur `00_critical/o_intent_control_dependency`. Le reward rendait donc la metrique
inexploitable, pas l'inverse.

SECOND DEFAUT, meme fonction : la boucle parcourait les MAX_OBJECTIVES entrees de
`zone_intents`, alors que `get_objective_control` rend 0.0 pour un zone_idx hors liste. Les
zones INEXISTANTES tombaient dans la branche "INVADE sur neutre" et versaient
`invade_neutral_bonus` a chaque tour, gratuitement (+0.2/tour sur un scenario a 3 objectifs
avec MAX_OBJECTIVES=5, l'intent par defaut etant INVADE). Ce revenu passif disparait avec
l'evaluation sur resultat elle-meme — une zone inexistante n'est jamais prise — et non avec la
borne posee dans le code : le test ci-dessous verrouille le SYMPTOME, pas cette ligne.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from engine.macro_intents import INTENT_ATTACK, INTENT_DEFEND, INTENT_INVADE, MAX_OBJECTIVES
from engine.reward_calculator import RewardCalculator

DEFEND_HELD = 0.2
INVADE_SUCCESS = 0.3
INVADE_NEUTRAL = 0.1
INVADE_OWN = -0.1


def _calculator() -> RewardCalculator:
    """RewardCalculator sans __init__ : seuls la config et le bareme sont utiles ici."""
    calc = RewardCalculator.__new__(RewardCalculator)
    calc.config = {"controlled_agent": "TestAgent"}  # type: ignore[assignment]
    calc.rewards_config = {  # type: ignore[assignment]
        "TestAgent": {
            "zone_intent_shaping": {
                "defend_held_bonus": DEFEND_HELD,
                "invade_success_bonus": INVADE_SUCCESS,
                "invade_neutral_bonus": INVADE_NEUTRAL,
                "invade_lost_penalty": INVADE_OWN,
            }
        }
    }
    return calc


def _game_state(controllers: List[Any], current_player: int = 1) -> Dict[str, Any]:
    """Plateau a N objectifs, `controllers[i]` = joueur controlant l'objectif i (None = neutre)."""
    return {
        "objectives": [{"id": f"obj{i}", "hexes": [[i, 0]]} for i in range(len(controllers))],
        "objective_controllers": {f"obj{i}": c for i, c in enumerate(controllers)},
        "current_player": current_player,
    }


def _settle(
    intents: List[int],
    control_at_declaration: List[float],
    controllers_now: List[Any],
    player: int = 1,
    current_player: int = 1,
) -> float:
    """Solde vu par `player`. `current_player` est volontairement DISSOCIE : le solde ne doit
    plus dependre du joueur dont c'est le tour (cf. test du point de vue plus bas)."""
    return _calculator().settle_zone_intent_declaration(
        _game_state(controllers_now, current_player=current_player),
        {"intents": intents, "control": control_at_declaration},
        player,
    )


def test_defend_is_paid_only_when_the_objective_is_actually_kept() -> None:
    """
    LE verrou du chantier. Meme declaration (DEFEND sur zone tenue), deux issues opposees :
    l'ancienne implementation versait le bonus dans les DEUX cas puisqu'elle ne regardait que
    l'etat au moment de la declaration.
    """
    kept = _settle([INTENT_DEFEND], [1.0], controllers_now=[1])
    lost = _settle([INTENT_DEFEND], [1.0], controllers_now=[2])

    assert kept == pytest.approx(DEFEND_HELD)
    assert lost == pytest.approx(0.0), (
        "objectif perdu : l'intention DEFEND n'a pas ete realisee, rien n'est du"
    )


def test_defend_on_a_zone_not_held_at_declaration_pays_nothing() -> None:
    """DEFEND n'est pas un ordre de conquete : prendre la zone ne declenche pas son bonus."""
    assert _settle([INTENT_DEFEND], [-1.0], controllers_now=[1]) == pytest.approx(0.0)
    assert _settle([INTENT_DEFEND], [0.0], controllers_now=[1]) == pytest.approx(0.0)


def test_invade_is_paid_only_when_the_zone_is_actually_taken() -> None:
    """Symetrique de DEFEND : INVADE se juge sur la prise, pas sur la cible visee."""
    taken_from_enemy = _settle([INTENT_INVADE], [-1.0], controllers_now=[1])
    failed_on_enemy = _settle([INTENT_INVADE], [-1.0], controllers_now=[2])
    taken_from_neutral = _settle([INTENT_INVADE], [0.0], controllers_now=[1])
    failed_on_neutral = _settle([INTENT_INVADE], [0.0], controllers_now=[None])

    assert taken_from_enemy == pytest.approx(INVADE_SUCCESS)
    assert failed_on_enemy == pytest.approx(0.0)
    # Prendre une zone neutre vaut moins que la reprendre a l'adversaire.
    assert taken_from_neutral == pytest.approx(INVADE_NEUTRAL)
    assert failed_on_neutral == pytest.approx(0.0)
    assert taken_from_neutral < taken_from_enemy


def test_invade_on_own_zone_is_penalised_whatever_the_outcome() -> None:
    """
    Declarer une invasion sur sa PROPRE zone est une incoherence de declaration : elle se juge
    sans attendre le resultat, et le resultat ne doit pas pouvoir la racheter.
    """
    still_held = _settle([INTENT_INVADE], [1.0], controllers_now=[1])
    lost_meanwhile = _settle([INTENT_INVADE], [1.0], controllers_now=[2])

    assert still_held == pytest.approx(INVADE_OWN)
    assert lost_meanwhile == pytest.approx(INVADE_OWN)


def test_attack_intent_carries_no_shaping() -> None:
    """ATTACK n'a jamais eu de terme de shaping — il ne doit pas en gagner un par accident."""
    for control in (-1.0, 0.0, 1.0):
        for controller in (1, 2, None):
            assert _settle([INTENT_ATTACK], [control], controllers_now=[controller]) == 0.0


def test_nonexistent_zones_are_never_paid() -> None:
    """
    SECOND DEFAUT. `zone_intents` compte MAX_OBJECTIVES entrees quel que soit le scenario, et
    l'intent par defaut est INVADE. Sur un plateau a 3 objectifs, les 2 zones fantomes
    versaient `invade_neutral_bonus` chaque tour — un revenu que l'agent encaisse sans jouer.

    Ce test rougit sous l'ANCIENNE semantique (verifie), pas sous la seule suppression de la
    borne `num_zones` : c'est l'evaluation sur resultat qui elimine le symptome, la borne n'est
    qu'une garde. Le distinguo est note pour qu'un lecteur ne croie pas la borne verrouillee.
    """
    intents = [INTENT_INVADE] * MAX_OBJECTIVES
    control = [0.0] * MAX_OBJECTIVES

    # 3 objectifs reels, aucun pris : le total doit etre STRICTEMENT nul.
    assert _settle(intents, control, controllers_now=[None, None, None]) == pytest.approx(0.0)

    # Et un seul objectif reel pris ne doit rapporter que le sien.
    assert _settle(intents, control, controllers_now=[1, None, None]) == pytest.approx(
        INVADE_NEUTRAL
    )


def test_zones_are_summed_independently() -> None:
    """Le solde porte sur toutes les zones reelles, chacune avec sa propre issue."""
    total = _settle(
        [INTENT_DEFEND, INTENT_INVADE, INTENT_INVADE, INTENT_ATTACK],
        [1.0, -1.0, 1.0, 0.0],
        controllers_now=[1, 1, 1, 1],
    )
    assert total == pytest.approx(DEFEND_HELD + INVADE_SUCCESS + INVADE_OWN)


def test_the_old_tautology_is_gone() -> None:
    """
    Preuve directe que la politique creuse ne paie plus : recopier l'etat en intents (DEFEND sur
    ce qu'on tient, INVADE sur le reste) SANS rien changer au plateau rapportait, avant,
    2*DEFEND_HELD + INVADE_SUCCESS + INVADE_NEUTRAL. Elle rapporte maintenant 0.
    """
    controllers = [1, 1, 2, None]
    intents = [INTENT_DEFEND, INTENT_DEFEND, INTENT_INVADE, INTENT_INVADE]
    control = [1.0, 1.0, -1.0, 0.0]

    # Plateau inchange pendant le tour : les DEFEND tiennent, les INVADE echouent.
    unchanged = _settle(intents, control, controllers_now=controllers)
    assert unchanged == pytest.approx(2 * DEFEND_HELD), (
        "seules les zones effectivement conservees sont payees"
    )

    # Et si l'agent perd tout ce qu'il avait declare defendre, il ne touche plus rien.
    collapsed = _settle(intents, control, controllers_now=[2, 2, 2, None])
    assert collapsed == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Cycle declaration -> solde sur le VRAI moteur.
#
# Les tests ci-dessus verrouillent le bareme ; ceux-ci verrouillent l'INSTANT du versement,
# qui est precisement ce qui etait faux. `calculate_reward` est neutralise a 0.0 : la
# recompense observee est alors le shaping zone-intent SEUL, sans quoi rien ne serait
# distinguable du bruit tactique.
# ---------------------------------------------------------------------------

from unittest.mock import patch  # noqa: E402

import numpy as np  # noqa: E402

from engine.macro_intents import decode_zone_intent_action, is_zone_intent_action  # noqa: E402
from engine.phase_handlers.shared_utils import SQUAD_ACTION_WAIT  # noqa: E402
from engine.w40k_core import W40KEngine  # noqa: E402

from test_objective_held_samples import _config  # noqa: E402
from tests.unit.engine._config_helpers import build_engine_config


def _engine() -> W40KEngine:
    """
    Moteur reel avec le bareme de shaping REEL branche.

    Le harnais `_config` ne porte pas de config d'agent, et le fichier voisin contournait cela
    en neutralisant la fonction de shaping. Impossible ici : c'est elle qu'on mesure. On injecte
    donc le bareme dans le RewardCalculator du moteur — seule `calculate_reward` est
    neutralisee, pour que la recompense observee soit le shaping SEUL.
    """
    with patch.object(RewardCalculator, "calculate_reward", lambda self, *a, **kw: 0.0), \
         patch("engine.w40k_core.load_weapon_damage_table", return_value={}), \
         patch.object(W40KEngine, "_build_reward_configs_for_current_units", return_value={}):
        engine = W40KEngine(config=build_engine_config(_config(1)), gym_training_mode=True, quiet=True)
        engine.reset()
    reference = _calculator()
    engine.reward_calculator.config["controlled_agent"] = "TestAgent"
    engine.reward_calculator.rewards_config = reference.rewards_config
    return engine


def _play_declaring_defend(engine: W40KEngine, max_steps: int = 2000) -> List[Dict[str, Any]]:
    """
    Declare DEFEND sur toutes les zones puis ATTEND — personne ne bouge, donc le controle acquis
    au deploiement est conserve et les intentions DEFEND sont effectivement realisees.

    UNE ZONE DIFFERENTE PAR FREE STEP. Prendre bêtement la premiere action DEFEND legale
    redeclarait les MAX_OBJECTIVES free steps sur la zone 0 : les autres zones gardaient l'intent
    par defaut (INVADE), le solde valait 0.2 (DEFEND tenu) - 0.1 (INVADE sur zone deja possedee)
    = 0.1, et ce 0.1 se lisait comme « le bonus DEFEND » alors qu'il etait une difference de deux
    termes contraires. Le harnais ne declarait donc pas ce que son nom annonce, et le montant que
    les tests ci-dessous observent ne se deduisait d'aucune intention.

    Rend un journal par step GYM. `_pending_zone_shaping` est lu AVANT et APRES le step : depuis
    `_drain_forced_waits`, un step gym recouvre plusieurs steps moteur et `reward` les CUMULE
    (cf. la docstring de `W40KEngine.step_with_mask`), donc le reward rendu n'est plus la
    recompense de l'action nommee par `info["action"]`. Le solde reporte est le seul terme qui
    peut y entrer sans venir de l'action elle-meme, et son NIVEAU ne dirait rien : il est pose au
    premier free step du tour (`_process_command_phase`) et reste en attente jusqu'a ce qu'un step
    non-zone_intent le poppe, donc les free steps intermediaires le voient sans y toucher.
    """
    journal: List[Dict[str, Any]] = []
    declaration_key: Any = None
    declared_zones: set[int] = set()
    with patch.object(RewardCalculator, "calculate_reward", lambda self, *a, **kw: 0.0):
        for _ in range(max_steps):
            mask = engine.get_action_mask()
            legal = [int(a) for a in np.flatnonzero(mask)]
            key = (engine.game_state["turn"], int(engine.game_state["current_player"]))
            if key != declaration_key:
                declaration_key, declared_zones = key, set()
            defend_actions = {
                decode_zone_intent_action(a)[0]: a
                for a in legal
                if is_zone_intent_action(a) and decode_zone_intent_action(a)[1] == INTENT_DEFEND
            }
            undeclared = sorted(set(defend_actions) - declared_zones)
            if defend_actions:
                # Une fois toutes les zones couvertes, on REDECLARE au lieu de sortir : les free
                # steps restants doivent etre consommes jusqu'a
                # `zone_intent_free_steps_remaining == 0`, sinon le masque de sortie n'est jamais
                # reduit a `wait`, le moteur ne draine rien, et le cumul que ces tests observent
                # n'existe pas. Redeclarer DEFEND sur une zone deja DEFEND ne change aucun intent.
                zone = undeclared[0] if undeclared else max(defend_actions)
                declared_zones.add(zone)
                action = defend_actions[zone]
            elif mask[SQUAD_ACTION_WAIT]:
                action = SQUAD_ACTION_WAIT
            else:
                action = legal[0] if legal else SQUAD_ACTION_WAIT
            turn_before = engine.game_state["turn"]
            pending_before = float(engine.game_state["_pending_zone_shaping"])
            _obs, reward, terminated, truncated, info = engine.step(int(action))
            journal.append({
                "turn": turn_before,
                "action": info.get("action"),
                "acting_player": info.get("acting_player"),
                "reward": float(reward),
                "pending_before": pending_before,
                "pending_after": float(engine.game_state["_pending_zone_shaping"]),
                "terminal": bool(terminated or truncated),
            })
            if terminated or truncated:
                break
    return journal


def test_no_shaping_is_paid_during_the_turn_of_the_declaration() -> None:
    """
    LE verrou d'instant. Avant, le shaping tombait dans le tour meme de la declaration : sur la
    premiere action tactique qui suivait les free steps. Il ne doit plus rien y avoir avant que
    le tour soit joue et le controle reevalue.
    """
    journal = _play_declaring_defend(_engine())
    assert journal, "aucun step joue"

    first_declaration = next(
        (i for i, entry in enumerate(journal) if entry["action"] == "zone_intent"), None
    )
    assert first_declaration is not None, "aucune declaration jouee : le test ne mesurerait rien"

    declaration_turn = journal[first_declaration]["turn"]
    paid_same_turn = [
        entry for entry in journal[first_declaration:]
        if entry["turn"] == declaration_turn and entry["reward"] != 0.0
    ]
    assert not paid_same_turn, (
        f"shaping verse dans le tour de la declaration: {paid_same_turn}"
    )


def test_the_declaration_is_eventually_settled() -> None:
    """
    Contre-epreuve du test precedent : reporter le versement ne doit pas revenir a le SUPPRIMER.
    Un verrou qui exige seulement "rien pendant le tour" passerait si le shaping avait disparu.
    """
    journal = _play_declaring_defend(_engine())

    declarations = [e for e in journal if e["action"] == "zone_intent"]
    assert declarations, "aucune declaration jouee"
    payments = [e for e in journal if e["reward"] != 0.0]

    assert payments, "aucune declaration soldee : le shaping a disparu au lieu d'etre reporte"
    # Le versement est POSTERIEUR au tour de la premiere declaration.
    assert max(e["turn"] for e in payments) > min(e["turn"] for e in declarations)
    # DEFEND sur zones conservees : le solde est positif.
    assert sum(e["reward"] for e in payments) > 0.0


def test_a_free_step_itself_is_never_rewarded() -> None:
    """Un free step ne produit AUCUNE recompense de son propre chef.

    OBSERVATOIRE. Ce test lisait le reward du step gym et l'attribuait a `info["action"]`. Ce
    raccourci est mort avec `_drain_forced_waits` : le dernier `zone_intent` d'un tour met
    `zone_intent_free_steps_remaining` a 0, donc le masque de sortie n'ouvre plus que `wait`, et le
    moteur joue lui-meme cette attente DANS le step de l'agent en cumulant son reward. C'est cette
    attente auto-jouee — pas le free step — qui poppe `_pending_zone_shaping` (le pop est dans la
    branche NON-zone_intent de `step_with_mask`). Mesure sur ce harnais : 3 steps gym `zone_intent`
    a 0.4 (= 2 x DEFEND_HELD, les deux zones tenues et declarees DEFEND), dont le step moteur
    `zone_intent` valait 0.0 et le step moteur draine 0.4.

    `info["reward_breakdown"]` ayant ete supprime du moteur, la recompense d'UN step moteur n'est
    plus observable de l'exterieur. On decompose donc le cumul par son seul autre terme possible
    ici : `_pending_zone_shaping` (`calculate_reward` est neutralise a 0.0, donc rien d'autre ne
    peut entrer dans le total). Un free step n'a droit qu'au solde deja EN ATTENTE a son entree et
    que ce step VIDE — ni au solde que sa propre command phase vient de calculer (l'ancien defaut
    du moteur : il n'etait alors pas encore en attente), ni a celui qu'il laisse en attente.
    """
    journal = _play_declaring_defend(_engine())
    # Le solde TERMINAL est un versement distinct (`settle_pending_zone_intent_declaration` a la
    # terminaison), verrouille par `test_no_declaration_survives_the_end_of_the_episode` : il ne
    # transite pas par `_pending_zone_shaping` et n'est donc pas decomposable ici.
    free_steps = [e for e in journal if e["action"] == "zone_intent" and not e["terminal"]]
    assert free_steps, "aucun free step joue : le test ne mesurerait rien"

    def _drained(entry: Dict[str, Any]) -> float:
        """Solde en attente que ce step a VIDE — 0.0 s'il n'a rien vide.

        `pending_after == 0.0` est le seul marqueur du pop (`step_with_mask` remet la cle a 0.0,
        il ne la decremente pas), et il ne se confond avec aucun autre cas : un step qui POSE un
        solde le laisse non nul, un step qui le traverse sans y toucher aussi. Aucune comparaison
        de SIGNE ici : un solde negatif (INVADE declare sur ses propres zones) se draine
        exactement comme un positif, et un solde nul ne se pose meme pas.
        """
        return entry["pending_before"] if entry["pending_after"] == 0.0 else 0.0

    # Un free step vaut EXACTEMENT ce qu'il a vide du solde en attente, donc 0.0 partout sauf sur
    # celui dont l'attente auto-jouee le vide. Payer un solde que le step vient de CALCULER (ce
    # que faisait le moteur avant le report) rougit : ce solde-la n'etait pas encore en attente.
    surplus = [e for e in free_steps if e["reward"] != pytest.approx(_drained(e))]
    assert not surplus, f"free step recompense au-dela du solde en attente qu'il vide: {surplus}"

    # NON VACANT : au moins un free step vide reellement un solde. Sans ce controle, un moteur qui
    # ne verserait plus rien du tout passerait l'assertion ci-dessus les yeux fermes.
    assert any(_drained(e) != 0.0 for e in free_steps), (
        "aucun solde en attente vide par un free step : la decomposition n'est pas exercee"
    )


def test_no_declaration_survives_the_end_of_the_episode() -> None:
    """
    SOLDE TERMINAL. La declaration du dernier tour n'atteint jamais la command phase suivante :
    sans rattrapage a la terminaison, le dernier tour de CHAQUE episode serait muet — et c'est
    celui qui decide la partie.
    """
    engine = _engine()
    journal = _play_declaring_defend(engine)
    assert journal, "aucun step joue"

    if not engine.game_state["game_over"]:
        pytest.skip("episode tronque avant la fin : le solde terminal n'est pas exerce ici")

    remaining = engine.game_state.get("_zone_intent_declarations") or {}
    controlled_player = int(engine.config["controlled_player"])
    assert controlled_player not in remaining, (
        "la declaration du dernier tour de l'agent n'a pas ete soldee"
    )


def test_declarations_do_not_leak_across_episodes() -> None:
    """
    `reset()` fait un `update()` de game_state, PAS une recreation : sans remise a zero
    explicite, une declaration non soldee (celle de l'adversaire, ou celle de l'agent sur un
    episode tronque) serait soldee au tour 1 de l'episode SUIVANT, contre un plateau sans aucun
    rapport avec elle.
    """
    engine = _engine()
    _play_declaring_defend(engine, max_steps=60)

    # On force une declaration en attente pour les DEUX joueurs.
    engine.game_state["_zone_intent_declarations"] = {
        1: {"turn": 1, "intents": [INTENT_DEFEND] * MAX_OBJECTIVES, "control": [1.0] * MAX_OBJECTIVES},
        2: {"turn": 1, "intents": [INTENT_DEFEND] * MAX_OBJECTIVES, "control": [1.0] * MAX_OBJECTIVES},
    }
    engine.reset()

    assert engine.game_state["_zone_intent_declarations"] == {}


def test_settlement_does_not_depend_on_whose_turn_it_is() -> None:
    """
    VERROU DU POINT DE VUE. `get_objective_control` est relatif a `current_player`. Le solde
    TERMINAL porte sur le joueur controle, or la partie se termine pendant le tour de
    l'adversaire — mesure sur le harnais moteur : 6 terminaisons sur 6 avec `current_player=2`
    pour `controlled_player=1`.

    Utiliser le helper relatif y inversait le signe de TOUS les objectifs : le bonus DEFEND
    etait paye exactement quand la zone avait ete PERDUE, et refuse quand elle avait ete tenue.
    Le solde du joueur 1 doit donc rendre la meme valeur que ce soit son tour ou celui du 2.
    """
    kept_own_turn = _settle([INTENT_DEFEND], [1.0], [1], player=1, current_player=1)
    kept_enemy_turn = _settle([INTENT_DEFEND], [1.0], [1], player=1, current_player=2)
    assert kept_own_turn == pytest.approx(DEFEND_HELD)
    assert kept_enemy_turn == pytest.approx(kept_own_turn), (
        "le solde a change de valeur selon le joueur dont c'est le tour"
    )

    lost_own_turn = _settle([INTENT_DEFEND], [1.0], [2], player=1, current_player=1)
    lost_enemy_turn = _settle([INTENT_DEFEND], [1.0], [2], player=1, current_player=2)
    assert lost_own_turn == pytest.approx(0.0)
    assert lost_enemy_turn == pytest.approx(0.0), (
        "zone perdue payee comme conservee : le point de vue est inverse"
    )

    # Symetrique cote INVADE : une prise par l'ADVERSAIRE ne doit jamais payer l'agent.
    taken_by_enemy = _settle([INTENT_INVADE], [0.0], [2], player=1, current_player=2)
    assert taken_by_enemy == pytest.approx(0.0)


def test_zone_shaping_enters_the_reward_breakdown() -> None:
    """
    Le shaping n'est pas produit par `calculate_reward`, donc il n'apparait pas dans
    `last_reward_breakdown`. S'ajoutant quand meme au reward, il gonflait le retour de l'episode
    sans entrer dans aucune categorie : les cinq `reward/*_total` ne sommaient plus le retour, et
    `reward/objective_share` — la metrique que ce shaping doit precisement eclairer — ignorait un
    flux d'objectif reellement percu.
    """
    engine = _engine()
    journal = _play_declaring_defend(engine)

    paid = sum(entry["reward"] for entry in journal)
    assert paid > 0.0, "aucun shaping verse : le test ne mesurerait rien"

    breakdown = engine.episode_tactical_data["reward_breakdown"]
    # `calculate_reward` est neutralise a 0.0 : tout ce qui est ventile ici vient du shaping.
    assert breakdown["objective"] == pytest.approx(paid)
    assert breakdown["objective_positive"] == pytest.approx(paid)


def test_pending_shaping_does_not_leak_across_episodes() -> None:
    """
    Jumeau de `test_declarations_do_not_leak_across_episodes`, pour le solde DEJA CALCULE mais
    pas encore verse. Il n'est poppe que par une action non-zone-intent, et plusieurs chemins
    n'y arrivent jamais (fin de partie pendant les free steps, sortie anticipee turn-limit,
    auto-advance) : sans remise a zero au reset, il atterrirait sur la premiere action de
    l'episode suivant.
    """
    engine = _engine()
    _play_declaring_defend(engine, max_steps=60)

    engine.game_state["_pending_zone_shaping"] = 42.0
    engine.reset()

    assert engine.game_state["_pending_zone_shaping"] == 0.0
