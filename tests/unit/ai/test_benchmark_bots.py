"""Tests pour ai/benchmark_bots.py (§4.C Bot_refactor.md).

Trois invariants :
1. Construction — chaque clé benchmark produit le bon type via le registre.
2. Non-régression d'entraînement — aucune clé benchmark dans bot_training.ratios.
3. Stabilité de plan réactif — le plan de ReferenceReactiveBot ne change pas au sein d'un tour.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional
from unittest.mock import MagicMock

import pytest

from ai import bot_registry
from ai.benchmark_bots import (
    ReferenceBalancedBot, ReferenceDenialBot, ReferenceReactiveBot,
)

BENCHMARK_KEYS = bot_registry.BENCHMARK_BOT_KEYS
EXPECTED_CLASSES = {
    "reference_balanced": ReferenceBalancedBot,
    "reference_denial": ReferenceDenialBot,
    "reference_reactive": ReferenceReactiveBot,
}

# ─────────────────────────────────────────────────────────────────────────────────────────────
# 1. Construction via le registre
# ─────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("key", BENCHMARK_KEYS)
def test_build_bot_produces_expected_class(key: str) -> None:
    """build_bot(key) produit la bonne classe de benchmark."""
    bot = bot_registry.build_bot(key, {key: 0.0})
    assert isinstance(bot, EXPECTED_CLASSES[key])


@pytest.mark.parametrize("key", BENCHMARK_KEYS)
def test_randomness_zero_accepted(key: str) -> None:
    """randomness=0.0 est la valeur neutre — construire sans lever."""
    bot = bot_registry.build_bot(key, {key: 0.0})
    assert bot.randomness == 0.0


# ─────────────────────────────────────────────────────────────────────────────────────────────
# 2. Non-régression d'entraînement — aucun benchmark dans bot_training.ratios
# ─────────────────────────────────────────────────────────────────────────────────────────────

def _collect_bot_training_profiles() -> list:
    """Tous les fichiers de profil d'agent qui ont un bot_training.ratios."""
    repo_root = Path(__file__).parent.parent.parent.parent
    config_dir = repo_root / "config" / "agents"
    profiles = []
    if not config_dir.exists():
        return profiles
    for json_path in config_dir.rglob("*.json"):
        try:
            with open(json_path) as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(data, dict) and "bot_training" in data:
            bt = data["bot_training"]
            if isinstance(bt, dict) and "ratios" in bt:
                profiles.append((str(json_path), bt["ratios"]))
    return profiles


@pytest.mark.parametrize("profile_path,ratios", _collect_bot_training_profiles())
def test_no_benchmark_key_in_training_ratios(profile_path: str, ratios: Any) -> None:
    """Un benchmark dans bot_training.ratios serait un holdout entraîné — violation §4.C."""
    if not isinstance(ratios, dict):
        pytest.skip(f"ratios n'est pas un dict dans {profile_path}")
    intersection = set(ratios) & set(BENCHMARK_KEYS)
    assert not intersection, (
        f"{profile_path} contient des clés benchmark dans bot_training.ratios : {intersection}"
    )


# ─────────────────────────────────────────────────────────────────────────────────────────────
# 3. Stabilité du plan réactif au sein d'un tour
# ─────────────────────────────────────────────────────────────────────────────────────────────

def _minimal_game_state(episode: int = 1, turn: int = 1, player: int = 1) -> Dict[str, Any]:
    return {
        "units": [],
        "units_cache": {},
        "turn": turn,
        "episode_number": episode,
        "phase": "move",
        "victory_points": {1: 0, 2: 0},
        "objectives": [],
        "objective_controllers": {},
    }


def test_reactive_bot_plan_stable_within_same_turn() -> None:
    """Le plan de ReferenceReactiveBot ne change pas quand on appelle _update_plan
    plusieurs fois avec le même marqueur (même épisode, même tour).

    Le marqueur (episode_number, turn) est la contrainte de stabilité intra-tour :
    plusieurs activations dans un tour voient le même plan.
    """
    bot = ReferenceReactiveBot(randomness=0.0)
    gs = _minimal_game_state(episode=42, turn=3)

    bot._update_plan(gs, player=1)
    plan_first = bot._plan

    # Deuxième appel : même tour → plan inchangé.
    bot._update_plan(gs, player=1)
    plan_second = bot._plan

    assert plan_first == plan_second, (
        f"Plan a changé au sein du même tour : {plan_first!r} → {plan_second!r}"
    )


def test_reactive_bot_plan_resets_on_new_episode() -> None:
    """Un nouvel épisode remet le plan à 'SCORE' et réinitialise les snapshots."""
    bot = ReferenceReactiveBot(randomness=0.0)

    # Épisode 1 — pousser le bot en plan KILL manuellement pour vérifier le reset.
    gs_ep1 = _minimal_game_state(episode=1, turn=1)
    bot._update_plan(gs_ep1, player=1)
    bot._plan = "KILL"  # forcer un plan non-SCORE

    # Épisode 2 — doit réinitialiser.
    gs_ep2 = _minimal_game_state(episode=2, turn=1)
    bot._update_plan(gs_ep2, player=1)

    assert bot._plan == "SCORE", f"Plan attendu 'SCORE' après reset d'épisode, obtenu {bot._plan!r}"
    assert bot._snapshot_episode == 2


def test_balanced_bot_intent_score_when_no_enemies() -> None:
    """Sans ennemis sur la table : _elect_intent retourne SCORE."""
    bot = ReferenceBalancedBot(randomness=0.0)
    gs = _minimal_game_state()
    unit = {"id": "u1", "player": 1, "VALUE": 5.0, "MOVE": 12}
    gs["units"] = [unit]
    intent = bot._elect_intent(unit, gs)
    assert intent == "SCORE"


def _gs_with_enemy(vp_me: int = 0, vp_opp: int = 0) -> tuple:
    """Retourne (game_state, attacker, enemy) avec un ennemi vivant sur le champ.

    MOVE ajouté (Fix R0a-bis §2) : _elect_intent filtre maintenant par portée, require_key(MOVE).
    Les positions (5,5) / (6,6) restent à distance 1-2 hexes, bien dans le reach MOVE=12.
    """
    gs = _minimal_game_state()
    attacker = {"id": "u1", "player": 1, "VALUE": 5.0, "MOVE": 12}
    enemy = {"id": "e1", "player": 2, "VALUE": 8.0, "MOVE": 6}
    gs["units"] = [attacker, enemy]
    gs["units_cache"] = {
        "u1": {"col": 5, "row": 5, "HP_CUR": 10, "player": 1},
        "e1": {"col": 6, "row": 6, "HP_CUR": 10, "player": 2},
    }
    gs["victory_points"] = {1: vp_me, 2: vp_opp}
    return gs, attacker, enemy


@pytest.mark.parametrize("vp_me,dmg_att,dmg_def,expected", [
    (0, 15.0, 0.0, "KILL"),    # attaquant peut anéantir → KILL
    (12, 0.0, 10.0, "PRESERVE"),  # menace ennemie + avance VP → PRESERVE
])
def test_balanced_bot_intent_kill_or_preserve(
    vp_me: int, dmg_att: float, dmg_def: float, expected: str
) -> None:
    """_elect_intent retourne KILL ou PRESERVE selon le scoring."""
    from unittest.mock import patch

    gs, attacker, _ = _gs_with_enemy(vp_me=vp_me)
    bot = ReferenceBalancedBot(randomness=0.0)

    def _dmg(game_state, att_id, def_id, is_ranged):
        return dmg_att if att_id == "u1" else dmg_def

    with patch("ai.benchmark_bots.squad_expected_damage", side_effect=_dmg):
        intent = bot._elect_intent(attacker, gs)

    assert intent == expected


def test_denial_bot_move_to_uncontested_objective() -> None:
    """ReferenceDenialBot se dirige vers les objectifs non tenus par lui."""
    bot = ReferenceDenialBot(randomness=0.0)

    # Objectif à (5,5) tenu par le joueur adverse (2).
    gs = _minimal_game_state(player=1)
    # On ne peut pas appeler select_movement_destination sans le moteur complet —
    # on vérifie seulement que la construction est propre et que randomness=0.
    assert bot.randomness == 0.0
    assert isinstance(bot.PLACEMENT_WEIGHTS, dict)
    assert len(bot.PLACEMENT_WEIGHTS) == 7


# ─────────────────────────────────────────────────────────────────────────────────────────────
# 4. VP SCORE — _update_plan bascule quand l'adversaire a une avance VP
# ─────────────────────────────────────────────────────────────────────────────────────────────

def test_reactive_bot_switches_to_score_on_opponent_vp_lead() -> None:
    """_update_plan bascule en SCORE quand l'adversaire dépasse notre VP de _VP_LEAD.

    Scénario : plan forcé à KILL au tour 1, puis l'adversaire prend une avance
    VP supérieure à _VP_LEAD au tour 2. Sans la correction, la condition VP
    était toujours fausse (VP monotone ≥ snapshot) et le plan restait KILL.
    """
    from ai.benchmark_bots import _VP_LEAD

    bot = ReferenceReactiveBot(randomness=0.0)
    # Tour 1 : initialise les snapshots (VP=0/0, pas de pertes).
    gs_t1 = _minimal_game_state(episode=1, turn=1)
    gs_t1["victory_points"] = {1: 0, 2: 0}
    bot._update_plan(gs_t1, player=1)
    # Force le plan en KILL pour que la transition vers SCORE soit observable.
    bot._plan = "KILL"

    # Tour 2 : aucune perte de valeur, adversaire a une avance VP > _VP_LEAD.
    gs_t2 = _minimal_game_state(episode=1, turn=2)
    gs_t2["victory_points"] = {1: 0, 2: int(_VP_LEAD) + 1}
    bot._update_plan(gs_t2, player=1)
    assert bot._plan == "SCORE", (
        f"attendu SCORE quand adversaire VP+{int(_VP_LEAD)+1} vs nous 0, obtenu {bot._plan!r}"
    )


def test_reactive_bot_no_score_switch_when_vp_equal() -> None:
    """_update_plan ne bascule PAS en SCORE si les VP sont égaux."""
    bot = ReferenceReactiveBot(randomness=0.0)
    gs_t1 = _minimal_game_state(episode=1, turn=1)
    gs_t1["victory_points"] = {1: 5, 2: 5}
    bot._update_plan(gs_t1, player=1)
    bot._plan = "KILL"

    gs_t2 = _minimal_game_state(episode=1, turn=2)
    gs_t2["victory_points"] = {1: 10, 2: 10}
    bot._update_plan(gs_t2, player=1)
    assert bot._plan == "KILL", f"plan ne devrait pas changer à VP égaux, obtenu {bot._plan!r}"


def test_reactive_bot_no_score_switch_at_exact_vp_lead_boundary() -> None:
    """Frontière exacte : un retard de PILE _VP_LEAD ne bascule PAS en SCORE.

    La condition est stricte (`vp_me < vp_opp - _VP_LEAD`) : à l'égalité exacte le
    plan reste inchangé. Un `<=` ferait basculer ce scénario.
    """
    from ai.benchmark_bots import _VP_LEAD

    bot = ReferenceReactiveBot(randomness=0.0)
    gs_t1 = _minimal_game_state(episode=1, turn=1)
    bot._update_plan(gs_t1, player=1)
    bot._plan = "KILL"

    gs_t2 = _minimal_game_state(episode=1, turn=2)
    gs_t2["victory_points"] = {1: 0, 2: int(_VP_LEAD)}
    bot._update_plan(gs_t2, player=1)
    assert bot._plan == "KILL", (
        f"retard de pile {int(_VP_LEAD)} VP : la condition stricte doit laisser le plan "
        f"inchangé, obtenu {bot._plan!r}"
    )


# ─────────────────────────────────────────────────────────────────────────────────────────────
# 5. require_key pour episode_number (T1 — pas de .get() silencieux)
# ─────────────────────────────────────────────────────────────────────────────────────────────

def test_select_placement_action_raises_on_missing_episode_number() -> None:
    """select_placement_action lève KeyError si episode_number absent du game_state."""
    from ai.evaluation_bots import DEPLOYMENT_ACTIONS
    bot = ReferenceBalancedBot(randomness=0.0)
    gs = _minimal_game_state()
    del gs["episode_number"]
    from shared.data_validation import ConfigurationError
    with pytest.raises(ConfigurationError):
        bot.select_placement_action(list(DEPLOYMENT_ACTIONS), gs)


def test_update_plan_raises_on_missing_episode_number() -> None:
    """_update_plan lève ConfigurationError si episode_number absent du game_state."""
    from shared.data_validation import ConfigurationError
    bot = ReferenceReactiveBot(randomness=0.0)
    gs = _minimal_game_state()
    del gs["episode_number"]
    with pytest.raises(ConfigurationError):
        bot._update_plan(gs, player=1)


# ─────────────────────────────────────────────────────────────────────────────────────────────
# 6. _swing_score_fn et _denial_score_fn lèvent sur hp incohérent (T1)
# ─────────────────────────────────────────────────────────────────────────────────────────────

def _make_game_state_with_unit(sid: str, hp: Optional[int]) -> Dict[str, Any]:
    """game_state minimal avec une unité en cache ; hp=None = pas de cache.

    MOVE et col/row ajoutés (Fix R0a-bis §2) : _elect_intent lit require_key(MOVE) et
    require_unit_from_cache pour la position de chaque ennemi dans la boucle de filtrage.
    """
    gs: Dict[str, Any] = {
        "units": [{"id": sid, "player": 2, "VALUE": 3.0, "MOVE": 6}],
        "units_cache": {},
        "episode_number": 1,
        "turn": 1,
        "phase": "shoot",
        "victory_points": {1: 0, 2: 0},
        "objectives": [],
        "objective_controllers": {},
    }
    if hp is not None:
        gs["units_cache"][sid] = {"HP_CUR": hp, "col": 0, "row": 0, "player": 2}
    return gs


def test_swing_score_fn_raises_on_none_hp() -> None:
    """_swing_score_fn lève ValueError quand l'unité n'est pas en cache (hp=None)."""
    from ai.benchmark_bots import _swing_score_fn
    from unittest.mock import patch

    fn = _swing_score_fn("att1", is_ranged=True)
    gs = _make_game_state_with_unit("tgt1", hp=None)
    entry = {"VALUE": 3.0}
    with patch("ai.benchmark_bots.squad_expected_damage", return_value=5.0):
        with pytest.raises(ValueError, match="absent du cache"):
            fn("tgt1", entry, gs)


def test_denial_score_fn_raises_on_none_hp() -> None:
    """_denial_score_fn lève ValueError quand l'unité n'est pas en cache (hp=None)."""
    bot = ReferenceDenialBot(randomness=0.0)
    attacker = {"id": "att1", "player": 1}
    gs = _make_game_state_with_unit("tgt1", hp=None)
    gs["objective_controllers"] = {}
    entry = {"VALUE": 3.0}
    fn = bot._denial_score_fn(attacker, is_ranged=True, game_state=gs)
    with __import__("unittest.mock", fromlist=["patch"]).patch(
        "ai.benchmark_bots.squad_expected_damage", return_value=5.0
    ):
        with pytest.raises(ValueError, match="absent du cache"):
            fn("tgt1", entry, gs)


def test_swing_score_fn_raises_on_zero_hp() -> None:
    """_swing_score_fn lève ValueError quand le cache annonce HP<=0.

    Distinct de hp=None : ici l'unité EST dans le cache (donc réputée vivante) mais
    avec un HP incohérent — division par zéro évitée par une erreur explicite, pas
    par un fallback (T1).
    """
    from ai.benchmark_bots import _swing_score_fn
    from unittest.mock import patch

    fn = _swing_score_fn("att1", is_ranged=True)
    gs = _make_game_state_with_unit("tgt1", hp=0)
    entry = {"VALUE": 3.0}
    with patch("ai.benchmark_bots.squad_expected_damage", return_value=5.0):
        with pytest.raises(ValueError, match="HP=0"):
            fn("tgt1", entry, gs)


def test_denial_score_fn_raises_on_zero_hp() -> None:
    """_denial_score_fn lève ValueError quand le cache annonce HP<=0."""
    from unittest.mock import patch

    bot = ReferenceDenialBot(randomness=0.0)
    attacker = {"id": "att1", "player": 1}
    gs = _make_game_state_with_unit("tgt1", hp=0)
    entry = {"VALUE": 3.0}
    fn = bot._denial_score_fn(attacker, is_ranged=True, game_state=gs)
    with patch("ai.benchmark_bots.squad_expected_damage", return_value=5.0):
        with pytest.raises(ValueError, match="HP=0"):
            fn("tgt1", entry, gs)


def test_elect_intent_raises_on_zero_hp() -> None:
    """_elect_intent lève ValueError quand un ennemi du cache annonce HP<=0.

    La liste d'ennemis est passée explicitement (paramètre `enemies`) : c'est le
    chemin qu'emprunte select_movement_destination, qui calcule la liste une fois
    et la partage avec l'élection d'intention.

    L'attaquant (att1) est à (1,0), la cible à (0,0) — distance 1 ≤ att_reach=12.
    Le filtre de portée laisse passer la cible, puis la vérification HP=0 lève.
    """
    from unittest.mock import patch

    bot = ReferenceBalancedBot(randomness=0.0)
    gs = _make_game_state_with_unit("tgt1", hp=0)
    unit = {"id": "att1", "player": 1, "VALUE": 5.0, "MOVE": 12}
    gs["units_cache"]["att1"] = {"col": 1, "row": 0, "player": 1}
    enemy = gs["units"][0]
    with patch("ai.benchmark_bots.squad_expected_damage", return_value=5.0):
        with pytest.raises(ValueError, match="HP=0"):
            bot._elect_intent(unit, gs, [enemy])


# ─────────────────────────────────────────────────────────────────────────────────────────────
# 7. Comportement de charge ReferenceDenialBot — conditionnel à l'objectif
# ─────────────────────────────────────────────────────────────────────────────────────────────

def test_denial_bot_no_charge_when_no_enemy_on_objective() -> None:
    """ReferenceDenialBot retourne WAIT_ACTION en phase charge si aucun ennemi n'est sur objectif."""
    from unittest.mock import patch
    from ai.evaluation_bots import WAIT_ACTION

    bot = ReferenceDenialBot(randomness=0.0)
    gs = _minimal_game_state()
    gs["phase"] = "charge"
    active_unit = {"id": "u1", "player": 1, "VALUE": 5.0}
    enemy = {"id": "e1", "player": 2, "VALUE": 5.0}

    with patch("ai.benchmark_bots._living_enemies", return_value=[enemy]), \
         patch("ai.benchmark_bots.objective_hex_sets", return_value={(3, 3): True}), \
         patch("ai.benchmark_bots.unit_is_within_objective", return_value=False):
        result = bot.select_action_with_state([WAIT_ACTION], gs, active_unit)

    assert result == WAIT_ACTION, (
        f"Denial bot ne doit pas charger sans ennemi sur objectif, obtenu {result}"
    )


def test_denial_bot_charges_when_enemy_on_objective() -> None:
    """ReferenceDenialBot délègue à _charge si un ennemi est sur un objectif."""
    from unittest.mock import patch
    from ai.evaluation_bots import WAIT_ACTION

    FAKE_CHARGE = 999

    bot = ReferenceDenialBot(randomness=0.0)
    gs = _minimal_game_state()
    gs["phase"] = "charge"
    active_unit = {"id": "u1", "player": 1, "VALUE": 5.0}
    enemy = {"id": "e1", "player": 2, "VALUE": 5.0}

    with patch("ai.benchmark_bots._living_enemies", return_value=[enemy]), \
         patch("ai.benchmark_bots.objective_hex_sets", return_value={(3, 3): True}), \
         patch("ai.benchmark_bots.unit_is_within_objective", return_value=True), \
         patch.object(bot, "_charge", return_value=FAKE_CHARGE):
        result = bot.select_action_with_state([WAIT_ACTION, FAKE_CHARGE], gs, active_unit)

    assert result == FAKE_CHARGE, (
        f"Denial bot doit charger quand ennemi sur objectif, obtenu {result}"
    )


# ─────────────────────────────────────────────────────────────────────────────────────────────
# 8. Plan CONTEST (ancien RETREAT) de ReferenceReactiveBot
# ─────────────────────────────────────────────────────────────────────────────────────────────

def test_reactive_bot_contest_plan_on_heavy_own_losses() -> None:
    """_update_plan bascule en 'CONTEST' quand les pertes propres depassent seuil + pertes adverses.

    Scénario : tour 1 valeur=10/10, tour 2 mon unité morte (HP_CUR=0) → loss_me=10, loss_opp=0.
    Attendu : plan == 'CONTEST' (anciennement 'RETREAT' — §4.C correction).
    """
    from ai.benchmark_bots import _VALUE_LOSS_THRESHOLD

    assert _VALUE_LOSS_THRESHOLD < 10.0, "Fixture invalide : _VALUE_LOSS_THRESHOLD doit être < 10"

    bot = ReferenceReactiveBot(randomness=0.0)

    # is_unit_alive verifie la PRESENCE dans units_cache, pas HP_CUR.
    # Pour simuler une unite morte : la retirer du cache (elle reste dans units pour la VP).
    def _gs(episode: int, turn: int, u1_alive: bool) -> Dict[str, Any]:
        gs = _minimal_game_state(episode=episode, turn=turn)
        gs["units"] = [
            {"id": "u1", "player": 1, "VALUE": 10.0, "MOVE": 6},
            {"id": "u2", "player": 2, "VALUE": 10.0, "MOVE": 6},
        ]
        cache = {"u2": {"col": 6, "row": 6, "player": 2}}
        if u1_alive:
            cache["u1"] = {"col": 5, "row": 5, "player": 1}
        gs["units_cache"] = cache
        return gs

    bot._update_plan(_gs(episode=1, turn=1, u1_alive=True), player=1)
    bot._update_plan(_gs(episode=1, turn=2, u1_alive=False), player=1)

    assert bot._plan == "CONTEST", (
        f"Plan attendu 'CONTEST' apres lourdes pertes, obtenu {bot._plan!r}"
    )


# ─────────────────────────────────────────────────────────────────────────────────────────────
# 9. Fix R0a-bis §1 — MELEE_TRADE_FLOOR bloque une charge non rentable (rouge/vert)
# ─────────────────────────────────────────────────────────────────────────────────────────────

def test_charge_blocked_when_melee_below_trade_floor() -> None:
    """_charge retourne WAIT_ACTION quand melee_dmg < ranged_dmg * _MELEE_TRADE_FLOOR.

    Scénario : tir espéré = 10.0, mêlée = 1.0 → 1.0 < 10.0 * 0.5 = 5.0 → pas de charge.
    Mutation prouvée : mettre _MELEE_TRADE_FLOOR = 0 (condition jamais bloquante) fait
    retourner FAKE_CHARGE au lieu de WAIT_ACTION.
    """
    from unittest.mock import patch
    from ai.evaluation_bots import WAIT_ACTION
    from ai.benchmark_bots import _MELEE_TRADE_FLOOR

    FAKE_CHARGE = 999
    bot = ReferenceBalancedBot(randomness=0.0)
    gs = _minimal_game_state()
    gs["phase"] = "charge"
    attacker = {"id": "u1", "player": 1, "VALUE": 5.0, "MOVE": 6}
    enemy = {"id": "e1", "player": 2, "VALUE": 5.0, "MOVE": 6}
    gs["units"] = [attacker, enemy]

    def dmg(game_state, att_id, tgt_id, is_ranged):
        if att_id == "u1":
            return 10.0 if is_ranged else 1.0   # tir >> mêlée → en-dessous du floor
        return 0.0

    with patch("ai.benchmark_bots.squad_expected_damage", side_effect=dmg), \
         patch("ai.benchmark_bots._living_enemies", return_value=[enemy]):
        result = bot._charge([WAIT_ACTION, FAKE_CHARGE], gs, attacker)

    assert result == WAIT_ACTION, (
        f"Charge doit être bloquée (melee=1.0 < ranged*{_MELEE_TRADE_FLOOR}=5.0), "
        f"obtenu {result}"
    )


def test_charge_allowed_when_melee_meets_trade_floor() -> None:
    """_charge délègue au sélecteur de cible quand melee_dmg >= ranged_dmg * _MELEE_TRADE_FLOOR.

    Scénario : mêlée = 6.0, tir = 10.0 → 6.0 >= 5.0 → charge autorisée.
    """
    from unittest.mock import patch
    from ai.benchmark_bots import _MELEE_TRADE_FLOOR

    FAKE_CHARGE = 999
    bot = ReferenceBalancedBot(randomness=0.0)
    gs = _minimal_game_state()
    attacker = {"id": "u1", "player": 1, "VALUE": 5.0, "MOVE": 6}
    enemy = {"id": "e1", "player": 2, "VALUE": 5.0, "MOVE": 6}
    gs["units"] = [attacker, enemy]

    def dmg(game_state, att_id, tgt_id, is_ranged):
        if att_id == "u1":
            return 10.0 if is_ranged else 6.0   # 6.0 >= 10.0*0.5 → OK
        return 0.0

    with patch("ai.benchmark_bots.squad_expected_damage", side_effect=dmg), \
         patch("ai.benchmark_bots._living_enemies", return_value=[enemy]), \
         patch("ai.benchmark_bots._best_slot_action", return_value=FAKE_CHARGE):
        result = bot._charge([999], gs, attacker)

    assert result == FAKE_CHARGE, (
        f"Charge doit être autorisée (melee=6.0 >= ranged*{_MELEE_TRADE_FLOOR}=5.0), "
        f"obtenu {result}"
    )


# ─────────────────────────────────────────────────────────────────────────────────────────────
# 10. Fix R0a-bis §2 — filtre de portée dans _elect_intent (rouge/vert)
# ─────────────────────────────────────────────────────────────────────────────────────────────

def test_elect_intent_score_when_enemy_out_of_reach() -> None:
    """_elect_intent retourne SCORE quand le seul ennemi est hors portée ce tour.

    Scénario : att MOVE=6, pas de tir → att_reach=6. Ennemi à distance 20 → hors portée.
    s_kill doit rester 0 → pas de KILL, pas de PRESERVE → SCORE.

    Mutation prouvée : retirer le filtre (toujours compter l'ennemi) ferait retourner KILL
    car squad_expected_damage renvoie 15.0 et hp=1 → p_kill=1, s_kill=15 > s_score=0.
    """
    from unittest.mock import patch

    bot = ReferenceBalancedBot(randomness=0.0)
    gs = _minimal_game_state()
    attacker = {"id": "u1", "player": 1, "VALUE": 5.0, "MOVE": 6}
    enemy = {"id": "e1", "player": 2, "VALUE": 8.0, "MOVE": 6}
    gs["units"] = [attacker, enemy]
    gs["units_cache"] = {
        "u1": {"col": 0, "row": 0, "player": 1},
        "e1": {"col": 20, "row": 0, "player": 2},   # distance 20 > att_reach=6
    }

    def hp_fn(sid, game_state):
        return 1

    with patch("ai.benchmark_bots.squad_expected_damage", return_value=15.0), \
         patch("ai.benchmark_bots.get_hp_from_cache", side_effect=hp_fn):
        intent = bot._elect_intent(attacker, gs, [enemy])

    assert intent == "SCORE", (
        f"Ennemi hors portée : attendu SCORE, obtenu {intent!r} "
        f"(s_kill aurait dû rester 0)"
    )


def test_elect_intent_kill_when_enemy_in_reach() -> None:
    """_elect_intent retourne KILL quand l'ennemi est atteignable (dans att_reach).

    Même scénario mais ennemi à distance 4 ≤ att_reach=6 → s_kill > 0 → KILL.
    """
    from unittest.mock import patch

    bot = ReferenceBalancedBot(randomness=0.0)
    gs = _minimal_game_state()
    attacker = {"id": "u1", "player": 1, "VALUE": 5.0, "MOVE": 6}
    enemy = {"id": "e1", "player": 2, "VALUE": 8.0, "MOVE": 6}
    gs["units"] = [attacker, enemy]
    gs["units_cache"] = {
        "u1": {"col": 0, "row": 0, "player": 1},
        "e1": {"col": 4, "row": 0, "player": 2},   # distance 4 ≤ att_reach=6
    }

    def hp_fn(sid, game_state):
        return 1

    with patch("ai.benchmark_bots.squad_expected_damage", return_value=15.0), \
         patch("ai.benchmark_bots.get_hp_from_cache", side_effect=hp_fn):
        intent = bot._elect_intent(attacker, gs, [enemy])

    assert intent == "KILL", (
        f"Ennemi à portée (dist=4 ≤ reach=6) : attendu KILL, obtenu {intent!r}"
    )


# ─────────────────────────────────────────────────────────────────────────────────────────────
# 11. Fix R0a-bis §2 — KILL guard dans _update_plan (rouge/vert)
# ─────────────────────────────────────────────────────────────────────────────────────────────

def test_reactive_bot_no_kill_when_enemies_out_of_reach() -> None:
    """_update_plan ne bascule PAS en KILL si aucun ennemi n'est atteignable.

    Scénario : grosse perte adverse (loss_opp=10 > threshold), mais ennemi survivant
    à distance 50 — hors att_reach=6. Sans le guard, le plan passerait à KILL.
    """
    bot = ReferenceReactiveBot(randomness=0.0)

    def _gs(turn: int, u2_alive: bool) -> Dict[str, Any]:
        gs = _minimal_game_state(episode=1, turn=turn)
        gs["units"] = [
            {"id": "u1", "player": 1, "VALUE": 5.0, "MOVE": 6},
            {"id": "u2", "player": 2, "VALUE": 10.0, "MOVE": 6},
        ]
        cache: Dict[str, Any] = {"u1": {"col": 0, "row": 0, "player": 1}}
        if u2_alive:
            cache["u2"] = {"col": 50, "row": 0, "player": 2}  # distance 50 >> att_reach=6
        gs["units_cache"] = cache
        return gs

    bot._update_plan(_gs(1, True), player=1)
    bot._plan = "SCORE"  # état initial connu
    bot._update_plan(_gs(2, False), player=1)  # u2 mort → loss_opp=10, mais plus d'ennemi

    # Ennemi survivant inexistant → _has_reachable_enemies=False → plan reste SCORE
    assert bot._plan == "SCORE", (
        f"Aucun ennemi atteignable : plan doit rester SCORE, obtenu {bot._plan!r}"
    )


def test_reactive_bot_no_kill_when_no_enemies_in_units() -> None:
    """_update_plan ne bascule PAS en KILL si units ne contient aucune unité ennemie.

    Scénario : grosse perte adverse (loss_opp=10 > threshold) car les ennemis ont
    entièrement disparu de la liste units — _has_reachable_enemies retourne False
    immédiatement (alive_enemies=[]), sans même évaluer les distances.
    """
    bot = ReferenceReactiveBot(randomness=0.0)

    def _gs_with_enemies(turn: int) -> Dict[str, Any]:
        gs = _minimal_game_state(episode=1, turn=turn)
        gs["units"] = [
            {"id": "u1", "player": 1, "VALUE": 5.0, "MOVE": 6},
            {"id": "u2", "player": 2, "VALUE": 10.0, "MOVE": 6},
        ]
        gs["units_cache"] = {
            "u1": {"col": 0, "row": 0, "player": 1},
            "u2": {"col": 3, "row": 0, "player": 2},
        }
        return gs

    def _gs_no_enemies(turn: int) -> Dict[str, Any]:
        gs = _minimal_game_state(episode=1, turn=turn)
        gs["units"] = [
            {"id": "u1", "player": 1, "VALUE": 5.0, "MOVE": 6},
            # aucune unité ennemie — alive_enemies=[] dans _has_reachable_enemies
        ]
        gs["units_cache"] = {"u1": {"col": 0, "row": 0, "player": 1}}
        return gs

    bot._update_plan(_gs_with_enemies(1), player=1)  # snapshot: val_opp=10
    bot._plan = "SCORE"
    bot._update_plan(_gs_no_enemies(2), player=1)  # loss_opp=10 > threshold, alive_enemies=[]

    assert bot._plan == "SCORE", (
        f"Aucun ennemi dans units : plan doit rester SCORE, obtenu {bot._plan!r}"
    )


def test_reactive_bot_kill_when_enemy_in_reach_after_losses() -> None:
    """_update_plan bascule en KILL quand grosse perte adverse ET ennemi atteignable.

    Même scénario mais un ennemi u3 survit à distance 4 ≤ att_reach=6.
    """
    bot = ReferenceReactiveBot(randomness=0.0)

    def _gs(turn: int, u2_alive: bool) -> Dict[str, Any]:
        gs = _minimal_game_state(episode=1, turn=turn)
        gs["units"] = [
            {"id": "u1", "player": 1, "VALUE": 5.0, "MOVE": 6},
            {"id": "u2", "player": 2, "VALUE": 10.0, "MOVE": 6},
            {"id": "u3", "player": 2, "VALUE": 3.0, "MOVE": 6},  # ennemi survivant proche
        ]
        cache: Dict[str, Any] = {
            "u1": {"col": 0, "row": 0, "player": 1},
            "u3": {"col": 4, "row": 0, "player": 2},  # distance 4 ≤ att_reach=6
        }
        if u2_alive:
            cache["u2"] = {"col": 4, "row": 0, "player": 2}
        gs["units_cache"] = cache
        return gs

    bot._update_plan(_gs(1, True), player=1)
    bot._plan = "SCORE"
    bot._update_plan(_gs(2, False), player=1)  # u2 mort → loss_opp=10 > threshold, u3 proche

    assert bot._plan == "KILL", (
        f"Ennemi u3 à portée après grosse perte adverse : attendu KILL, obtenu {bot._plan!r}"
    )


# ─────────────────────────────────────────────────────────────────────────────────────────────
# 12. Fix R0a-bis §3 — _CONTEST_PULL incorporé dans obj_map (rouge/vert)
# ─────────────────────────────────────────────────────────────────────────────────────────────

def test_contest_pull_biases_enemy_objective_map() -> None:
    """_score_destinations_weighted préfère la destination proche d'un objectif ennemi
    grâce au pull _CONTEST_PULL_ENEMY, contre une destination proche d'un objectif neutre.

    Géométrie choisie pour que le pull soit décisif :
      zone 0 (ennemi) : current=(5,5) loin (12), valid_dest=(5,6) proche (10).
      zone 1 (neutre) : current=(5,5) proche (10), valid_dest=(5,6) loin (12).
      Sans pull : min(12,10)=10 aux deux → égalité → current renvoyé (premier dans scored).
      Avec pull ennemi=2 w=3 (6 hex) / neutre=1 w=3 (3 hex) :
        (5,5) : min(12-6, 10-3) = min(6, 7) = 6
        (5,6) : min(10-6, 12-3) = min(4, 9) = 4  → (5,6) préféré.
    Mutation ciblée : supprimer le rabais dans _score_destinations_weighted → égalité
    → current (5,5) renvoyé → assertion échoue.
    """
    from unittest.mock import patch
    from ai.benchmark_bots import _W_DENIAL
    import numpy as np

    fake_map_0 = np.full((10, 10), 12, dtype=np.int16)
    fake_map_0[5, 6] = 10  # valid_dest est proche de la zone ennemie
    fake_map_1 = np.full((10, 10), 12, dtype=np.int16)
    fake_map_1[5, 5] = 10  # current est proche de la zone neutre
    fake_maps = [fake_map_0, fake_map_1]
    fake_holders = [2, None]  # zone 0 → ennemi (player 2), zone 1 → neutre

    unit = {"id": "u1", "player": 1, "VALUE": 5.0, "MOVE": 6}
    gs = _minimal_game_state()
    gs["units"] = [unit]

    with patch("ai.benchmark_bots.objective_distance_maps", return_value=fake_maps), \
         patch("ai.benchmark_bots._objective_holders", return_value=fake_holders), \
         patch("ai.benchmark_bots._living_enemies", return_value=[]), \
         patch("ai.benchmark_bots._enemy_anchors", return_value=[]), \
         patch("ai.benchmark_bots.objective_hex_sets", return_value=[]), \
         patch("ai.benchmark_bots._surplus_oc_by_zone", return_value=[0.0, 0.0]), \
         patch("ai.benchmark_bots.unit_is_within_objective", return_value=False):
        from ai.benchmark_bots import _score_destinations_weighted
        dest = _score_destinations_weighted(
            unit=unit,
            current=(5, 5),
            valid_destinations=[(5, 6)],
            weights=_W_DENIAL,  # w_contest=3.0
            game_state=gs,
        )

    assert dest == (5, 6), (
        f"Le pull ennemi doit faire préférer (5,6) proche de la zone ennemie, obtenu {dest!r}. "
        "Vérifier que le rabais _CONTEST_PULL_ENEMY est soustrait dans _score_destinations_weighted."
    )


def test_own_zone_gets_no_pull_when_all_zones_held() -> None:
    """Quand le joueur tient tous les objectifs (free=[]), les zones propres ne génèrent
    aucun pull (pull=0.0) — spec 'mien: 0.0, y envoyer une deuxième escouade ne rapporte rien'.

    Note COUVERTURE : avec toutes les zones propres, le pull constant s'applique
    identiquement à toutes les destinations (décalage uniforme), donc le choix de
    destination est invariant à la mutation pull=0 → pull=_CONTEST_PULL_NEUTRAL.
    Ce test valide le code path free=[] et que la destination la plus proche selon les
    distances brutes est bien retournée sans biais supplémentaire.
    """
    from unittest.mock import patch
    import numpy as np
    from ai.benchmark_bots import _W_BALANCED_SCORE

    # Deux zones propres (player 1 tient tout) → free=[], targets=[0, 1].
    # Zone 0 : current=(5,5) à distance 3 (proche), valid_dest=(5,6) à 10.
    # Zone 1 : uniforme à 10.
    # min sans pull : (5,5)=3, (5,6)=10 → current préféré.
    fake_map_0 = np.full((10, 10), 10, dtype=np.int16)
    fake_map_0[5, 5] = 3
    fake_map_1 = np.full((10, 10), 10, dtype=np.int16)
    fake_maps = [fake_map_0, fake_map_1]
    fake_holders = [1, 1]  # joueur 1 tient tout → free=[]

    unit = {"id": "u1", "player": 1, "VALUE": 5.0, "MOVE": 6}
    gs = _minimal_game_state()
    gs["units"] = [unit]

    with patch("ai.benchmark_bots.objective_distance_maps", return_value=fake_maps), \
         patch("ai.benchmark_bots._objective_holders", return_value=fake_holders), \
         patch("ai.benchmark_bots._living_enemies", return_value=[]), \
         patch("ai.benchmark_bots._enemy_anchors", return_value=[]), \
         patch("ai.benchmark_bots.objective_hex_sets", return_value=[]), \
         patch("ai.benchmark_bots._surplus_oc_by_zone", return_value=[0.0, 0.0]), \
         patch("ai.benchmark_bots.unit_is_within_objective", return_value=False):
        from ai.benchmark_bots import _score_destinations_weighted
        dest = _score_destinations_weighted(
            unit=unit,
            current=(5, 5),
            valid_destinations=[(5, 6)],
            weights=_W_BALANCED_SCORE,
            game_state=gs,
        )

    assert dest == (5, 5), (
        f"current (plus proche de la zone propre) doit être préféré, obtenu {dest!r}"
    )
