"""Contrat du mémo d'engagement partagé entre les 5 intentions de charge (L10).

`charge_build_valid_plan` est appelée CINQ fois de suite par `arm_charge_placement_decision`,
une par intention. Depuis le 2026-09-08, le verdict « cette cellule engage-t-elle une cible ? »
est mémoïsé et PARTAGÉ entre ces cinq appels, parce que `intent` ne pilote que la clé de tri des
candidats : ni l'énumération, ni le test d'engagement n'en dépendent.

CE QUE CE FICHIER VERROUILLE — le risque métier, et lui seul. Si le mémo changeait ne serait-ce
qu'une cellule retenue, il changerait le plan de charge, donc le comportement de l'agent, donc la
comparabilité des modèles entraînés. Le test compare donc, sur de VRAIS états de charge produits
par le moteur, les cinq plans calculés AVEC mémo aux cinq plans calculés SANS aucune mémoïsation.
Toute divergence, même d'une seule figurine, échoue.

Pourquoi cette forme plutôt qu'une copie verbatim de l'implémentation d'origine : le changement
n'est pas un algorithme de remplacement mais une mémoïsation. La référence pertinente est donc
« le même corps privé de tout mémo », obtenu en substituant à la tranche un dictionnaire qui ne
retient rien (``_NeverStores``).

PIÈGE ÉVITÉ, mesuré : une première version comparait « mémo partagé entre intentions » à « mémo
vidé entre intentions ». Les deux branches mémoïsant, une clé de mémo mutilée en
``(figurine, colonne)`` — qui rend un verdict d'une AUTRE cellule — passait au vert. Seule la
comparaison à l'absence totale de mémo attrape ce défaut.

VERT VACANT — deux gardes : on exige d'avoir réellement comparé plusieurs états, et que le mémo
se soit réellement rempli. Sans elles, un moteur qui n'appellerait plus la fonction, ou un mémo
qui resterait vide, rendrait ce fichier vert sans rien prouver.
"""

from __future__ import annotations

import os
import random
from typing import Any, Dict, List, Optional, Tuple

import engine.phase_handlers.shared_utils as su

SCENARIO = "config/board/44x60x5/scenario/scenario_pvp_test.json"
PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
STEPS = 400
INTENTS = (0, 1, 2, 3, 4)
MAX_COMPARISONS = 12

Plan = Optional[List[Tuple[str, int, int, int]]]


def _build_env():
    """Vrai moteur, même construction que `test_geodesic_move_reach_contract.py`."""
    from ai.training_utils import setup_imports
    from ai.unit_registry import UnitRegistry
    from services.api_server import get_agents_from_scenario

    W40KEngine, _ = setup_imports()
    ur = UnitRegistry()
    sf = os.path.join(PROJECT_ROOT, SCENARIO)
    if not os.path.exists(sf):
        raise FileNotFoundError(sf)
    env = W40KEngine(
        rewards_config="default",
        training_config_name="x1",
        controlled_agent=sorted(get_agents_from_scenario(sf, ur))[0],
        scenario_file=sf,
        unit_registry=ur,
        quiet=True,
        gym_training_mode=True,
        training_n_envs=1,
    )
    env.reset(seed=42)
    return env


class _NeverStores(dict):
    """Mémo qui accepte les écritures et n'en garde AUCUNE.

    Substitué à la vraie tranche, il rend le comportement d'AVANT la mémoïsation : chaque
    verdict est recalculé. C'est la seule référence qui attrape un mémo faux — comparer
    « partagé » à « re-vidé entre intentions » ne le ferait pas, les deux branches mémoïsant.
    """

    def __setitem__(self, key: Any, value: Any) -> None:  # noqa: D105
        return


def _reset_caches(game_state: Dict[str, Any]) -> None:
    """Repart d'un état sans plan mémoïsé ni mémo d'engagement."""
    game_state.pop("_charge_engage_memo", None)
    game_state["_charge_plan_cache"] = {}


def _plans_with_memo(live, game_state, squad_id, target_ids, roll) -> List[Plan]:
    """Les 5 plans tels que le moteur les produit : un mémo partagé par les cinq intentions."""
    _reset_caches(game_state)
    return [live(game_state, squad_id, target_ids, roll, intent=i) for i in INTENTS]


def _plans_without_memo(
    live, monkeypatched_su, game_state, squad_id, target_ids, roll
) -> List[Plan]:
    """Les 5 plans SANS mémoïsation du tout — le comportement d'origine."""
    _reset_caches(game_state)
    original = monkeypatched_su.charge_engage_memo
    monkeypatched_su.charge_engage_memo = lambda _gs, _key: _NeverStores()
    try:
        return [live(game_state, squad_id, target_ids, roll, intent=i) for i in INTENTS]
    finally:
        monkeypatched_su.charge_engage_memo = original


def test_sharing_the_memo_across_intents_changes_no_plan():
    """Sur de vrais états de charge, partager le mémo entre intentions ne change aucun plan."""
    live = su.charge_build_valid_plan
    comparisons: List[Tuple[str, int]] = []
    memo_sizes: List[int] = []
    plans_seen = 0
    guard = {"busy": False}

    def shadowed(game_state, squad_id, target_squad_ids, charge_roll, intent=0):
        nonlocal plans_seen
        produced = live(game_state, squad_id, target_squad_ids, charge_roll, intent=intent)
        # `guard` : les appels de comparaison ci-dessous repassent par ce shadow. Sans lui, la
        # récursion serait infinie.
        #
        # On ne compare que les états où un plan EXISTE. La majorité des appels du moteur sont
        # des sondes d'éligibilité qui rendent `None` (mesuré : 81 sur 98 appels) ; les comparer
        # remplirait le quota avec des états où il n'y a rien à partager, et le test passerait
        # au vert sans avoir exercé le mémo une seule fois.
        if guard["busy"] or not produced or len(comparisons) >= MAX_COMPARISONS:
            return produced
        guard["busy"] = True
        # Sauvegardes prises AVANT le `try` : les lier à l'intérieur les rendrait non définies
        # dans le `finally` si la première ligne levait, et la restauration échouerait sur une
        # NameError masquant l'erreur d'origine.
        saved_cache = game_state.get("_charge_plan_cache")  # get allowed : restauré ensuite
        saved_memo = game_state.get("_charge_engage_memo")  # get allowed : restauré ensuite
        try:
            memoised = _plans_with_memo(
                live, game_state, squad_id, target_squad_ids, charge_roll
            )
            memo_slot = game_state.get("_charge_engage_memo")  # get allowed : mesure du remplissage
            memo_sizes.append(len(memo_slot[1]) if memo_slot else 0)
            reference = _plans_without_memo(
                live, su, game_state, squad_id, target_squad_ids, charge_roll
            )
            assert memoised == reference, (
                f"le mémo change un plan pour squad={squad_id} "
                f"cibles={list(target_squad_ids)} jet={charge_roll} :\n"
                f"  avec mémo : {memoised}\n"
                f"  sans mémo : {reference}"
            )
            plans_seen += sum(1 for p in memoised if p)
            comparisons.append((str(squad_id), int(charge_roll)))
        finally:
            # L'état doit ressortir EXACTEMENT comme il est entré : ces caches sont dérivés,
            # mais les laisser modifiés ferait diverger la partie que le test est en train de
            # dérouler, et le test mesurerait alors autre chose que le moteur réel.
            if saved_cache is None:
                game_state.pop("_charge_plan_cache", None)
            else:
                game_state["_charge_plan_cache"] = saved_cache
            if saved_memo is None:
                game_state.pop("_charge_engage_memo", None)
            else:
                game_state["_charge_engage_memo"] = saved_memo
            guard["busy"] = False
        return produced

    su.charge_build_valid_plan = shadowed
    try:
        env = _build_env()
        rng = random.Random(42)
        for _ in range(STEPS):
            mask = env.get_action_mask()
            valid = [i for i in range(len(mask)) if mask[i]]
            if not valid:
                break
            _obs, _r, terminated, truncated, _info = env.step(rng.choice(valid))
            if terminated or truncated:
                env.reset(seed=42)
    finally:
        su.charge_build_valid_plan = live

    assert len(comparisons) >= 3, (
        f"seulement {len(comparisons)} états de charge comparés — le test n'a rien exercé"
    )
    assert plans_seen > 0, "aucun plan non vide produit — les comparaisons sont dégénérées"
    assert max(memo_sizes) >= 50, (
        f"mémo au plus rempli à {max(memo_sizes) if memo_sizes else 0} entrées — "
        f"le partage n'a rien à partager, le test ne prouve rien"
    )
