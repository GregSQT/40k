"""Tests — les quatre compteurs de combat d'``episode_tactical_data``.

``shots_fired``, ``hits``, ``damage_dealt``, ``damage_received`` ont ete DECLARES puis jamais
incrementes pendant neuf mois : le commit ``fe1df7d8`` « metrics OK » (2025-10-25) a deplace
``episode_tactical_data`` du callback vers le moteur en reimplementant les autres compteurs,
mais pas ceux-la, tout en supprimant leur calcul cote callback dans le meme diff. Rien ne l'a
attrape, parce que leurs consommateurs (``ai/metrics_tracker.log_tactical_metrics``) sont
gardes par ``> 0`` : une courbe absente ne se distingue pas d'un agent qui ne se bat jamais.

Ces tests jouent une VRAIE partie, sur un moteur reel, et verifient la coherence croisee des
compteurs entre eux et avec l'etat du plateau. Un test sur un dictionnaire fabrique ne dirait
rien : c'est le branchement qui a lache, pas l'arithmetique.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple
from unittest.mock import patch

import numpy as np
import pytest

from engine.observation_builder import ObservationBuilder
from engine.phase_handlers.shared_utils import SQUAD_ACTION_WAIT
from engine.reward_calculator import RewardCalculator
from engine.w40k_core import W40KEngine


# ─────────────────────────────────────────────────────────────────────────────
# Harnais — moteur reel, deux escouades qui se voient et s'atteignent
# ─────────────────────────────────────────────────────────────────────────────

def _ranged_weapon() -> Dict[str, Any]:
    return {"ATK": 2, "STR": 4, "AP": 0, "DMG": 1, "NB": 2, "RNG": 24,
            "WEAPON_RULES": [], "display_name": "Test Bolter"}


def _melee_weapon() -> Dict[str, Any]:
    return {"ATK": 3, "STR": 4, "AP": 0, "DMG": 1, "NB": 1, "RNG": 1,
            "WEAPON_RULES": [], "display_name": "Test Blade"}


def _unit(uid: int, player: int, col: int, row: int) -> Dict[str, Any]:
    return {
        "id": uid, "player": player, "col": col, "row": row,
        "unitType": "TestUnit", "DISPLAY_NAME": f"Unit {uid}",
        # ARMOR_SAVE 6+ : les sauvegardes echouent souvent, donc des degats tombent
        # de facon fiable en quelques tours, sans dependre d'un jet chanceux.
        "HP_CUR": 6, "HP_MAX": 6, "MOVE": 6, "T": 4,
        "ARMOR_SAVE": 6, "INVUL_SAVE": 0,
        "RNG_WEAPONS": [_ranged_weapon()],
        "CC_WEAPONS": [_melee_weapon()],
        "UNIT_RULES": [], "UNIT_KEYWORDS": [], "LD": 7, "OC": 1, "VALUE": 100,
        "ICON": "test", "ICON_SCALE": 1.0, "ILLUSTRATION_RATIO": 1.0,
        "BASE_SHAPE": "round", "BASE_SIZE": 1, "MODEL_HEIGHT": 2.5,
    }


def _config(controlled_player: int) -> Dict[str, Any]:
    obs_params = {"obs_size": ObservationBuilder.SQUAD_OBS_SIZE_TARGET}
    return {
        "board": {"default": {
            "cols": 15, "rows": 13, "hex_radius": 1.0, "margin": 0.0, "wall_hexes": [],
            "objectives": [{"id": "obj1", "name": "Alpha", "hexes": [[7, 6]]}],
            "inches_to_subhex": 1,
        }},
        "game_rules": {
            "engagement_zone": 1, "engagement_zone_vertical": 5, "max_base_size_hex": 35,
            "max_turns": 5, "max_actions_per_model_per_turn": 7, "step_limit_margin": 1.5,
        },
        "move": {
            "can_move_through_enemy_engagement_zone": True,
            "can_move_through_enemy_model": False,
            "can_move_through_friendly_model": True,
        },
        "charge": {"charge_max_distance": 12},
        "pve_mode": False,
        "controlled_player": controlled_player,
        "observation_params": obs_params,
        "training_config": {"observation_params": obs_params},
        "units": [_unit(1, 1, 5, 6), _unit(2, 1, 5, 7),
                  _unit(3, 2, 9, 6), _unit(4, 2, 9, 7)],
    }


@pytest.fixture(autouse=True)
def _stub_rewards(monkeypatch: pytest.MonkeyPatch) -> None:
    """Les recompenses demandent une config d'agent ; elles ne pesent pas sur les compteurs."""
    monkeypatch.setattr(RewardCalculator, "calculate_reward", lambda self, *a, **kw: 0.0)
    monkeypatch.setattr(
        W40KEngine, "_build_observation",
        lambda self: np.zeros(ObservationBuilder.SQUAD_OBS_SIZE_TARGET),
    )


def _play_episode(controlled_player: int, seed: int) -> Tuple[W40KEngine, Dict[str, Any]]:
    """Joue un episode complet en actions legales tirees au hasard ; rend le moteur et info."""
    with patch("engine.w40k_core.load_weapon_damage_table", return_value={}), \
         patch.object(W40KEngine, "_build_reward_configs_for_current_units", return_value={}):
        engine = W40KEngine(config=_config(controlled_player),
                            gym_training_mode=True, quiet=True)
    engine.reset()
    rng = np.random.default_rng(seed)
    last_info: Dict[str, Any] = {}
    for _ in range(4000):
        mask = engine.get_action_mask()
        legal = np.flatnonzero(mask)
        action = int(rng.choice(legal)) if legal.size else SQUAD_ACTION_WAIT
        _obs, _reward, terminated, truncated, last_info = engine.step(action)
        if terminated or truncated:
            break
    assert "tactical_data" in last_info, "l'episode ne s'est pas termine : pas de tactical_data"
    return engine, last_info["tactical_data"]


def _hp_lost_by_player(engine: W40KEngine) -> Dict[int, int]:
    """PV reellement perdus par camp, lus sur le plateau (unite morte = tous ses PV)."""
    cache = engine.game_state["units_cache"]
    alive = {str(uid): entry for uid, entry in cache.items()}
    lost = {1: 0, 2: 0}
    for unit in engine.game_state["units"]:
        player = int(unit["player"])
        entry = alive.get(str(unit["id"]))
        if entry is None:
            lost[player] += int(unit["HP_MAX"])
        else:
            lost[player] += int(unit["HP_MAX"]) - int(entry["HP_CUR"])
    return lost


def _attack_logs(engine: W40KEngine) -> List[Dict[str, Any]]:
    return [lg for lg in engine.game_state["action_logs"]
            if lg.get("type") in ("shoot", "combat")]


# ─────────────────────────────────────────────────────────────────────────────
# Les quatre compteurs bougent, et sont coherents entre eux
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("seed", [7, 11, 23])
def test_the_four_counters_are_non_zero_on_a_real_game(seed: int) -> None:
    """Le branchement existe : sur une vraie partie, aucun des quatre ne reste a zero.

    C'est exactement l'assertion qui manquait. Pendant neuf mois les quatre valaient 0 et
    la suite etait verte.
    """
    _engine, tactical = _play_episode(controlled_player=1, seed=seed)

    assert tactical["shots_fired"] > 0, "aucun tir compte"
    assert tactical["hits"] > 0, "aucune touche comptee"
    assert tactical["damage_dealt"] > 0, "aucun degat inflige compte"
    assert tactical["damage_received"] > 0, "aucun degat recu compte"


@pytest.mark.parametrize("seed", [7, 11, 23])
def test_hits_never_exceed_shots(seed: int) -> None:
    """Une touche est un tir reussi : hits <= shots_fired, sinon accuracy depasse 1."""
    _engine, tactical = _play_episode(controlled_player=1, seed=seed)
    assert 0 < tactical["hits"] <= tactical["shots_fired"]


@pytest.mark.parametrize("seed", [7, 11, 23])
def test_damage_dealt_matches_the_hp_the_opponent_actually_lost(seed: int) -> None:
    """Coherence croisee : ce que j'inflige = ce que l'adversaire perd, PV pour PV.

    C'est ce controle qui separe un compteur juste d'un compteur qui compte n'importe quoi :
    il relie le journal a l'etat reel du plateau, et non le journal a lui-meme.
    """
    engine, tactical = _play_episode(controlled_player=1, seed=seed)
    hp_lost = _hp_lost_by_player(engine)

    assert tactical["damage_dealt"] == hp_lost[2]
    assert tactical["damage_received"] == hp_lost[1]


@pytest.mark.parametrize("controlled_player", [1, 2])
def test_counters_follow_the_controlled_seat(controlled_player: int) -> None:
    """Le siege compte : damage_received est celui de l'agent controle, pas d'un camp fixe.

    Sans cette verification, un compteur code en dur sur le joueur 1 passerait les tests
    ci-dessus des que l'agent joue en premiere position.
    """
    engine, tactical = _play_episode(controlled_player=controlled_player, seed=5)
    hp_lost = _hp_lost_by_player(engine)
    opponent = 2 if controlled_player == 1 else 1

    assert tactical["damage_dealt"] == hp_lost[opponent]
    assert tactical["damage_received"] == hp_lost[controlled_player]


# ─────────────────────────────────────────────────────────────────────────────
# Pas de double comptage, pas de chemin oublie
# ─────────────────────────────────────────────────────────────────────────────

def test_shots_counted_once_and_ranged_only() -> None:
    """Une attaque compte une fois, et shots_fired est le TIR seul — choix explicite.

    accuracy = hits / shots_fired est une precision au tir (BS). Y verser les attaques de
    melee (WS) rendrait la courbe ininterpretable. L'exclusion est donc verrouillee ici, pas
    laissee au hasard : si quelqu'un elargit shots_fired a la melee, ce test rougit et
    l'oblige a decider sciemment.
    """
    engine, tactical = _play_episode(controlled_player=1, seed=7)
    logs = _attack_logs(engine)

    expected_shots = sum(
        len(lg["shootDetails"]) for lg in logs
        if lg["type"] == "shoot" and int(lg["player"]) == 1
    )
    expected_hits = sum(
        1 for lg in logs if lg["type"] == "shoot" and int(lg["player"]) == 1
        for shot in lg["shootDetails"] if shot["hitResult"] == "HIT"
    )
    assert tactical["shots_fired"] == expected_shots
    assert tactical["hits"] == expected_hits

    # La melee a bien eu lieu et n'a pas alimente shots_fired.
    melee_details = sum(
        len(lg["shootDetails"]) for lg in logs
        if lg["type"] == "combat" and int(lg["player"]) == 1
    )
    assert melee_details > 0, "l'episode n'a produit aucune melee : le controle serait vide"
    assert tactical["shots_fired"] == expected_shots


def test_damage_covers_both_shooting_and_melee() -> None:
    """A l'inverse des tirs, l'attrition compte les DEUX phases : c'est le total encaisse.

    Un compteur limite au tir sous-estimerait l'agent de melee — un chemin oublie donne une
    metrique fausse, ce qui est pire qu'une metrique absente.
    """
    engine, tactical = _play_episode(controlled_player=1, seed=7)
    logs = _attack_logs(engine)

    shoot_damage = sum(int(lg["damage"]) for lg in logs
                       if lg["type"] == "shoot" and int(lg["player"]) == 1)
    melee_damage = sum(int(lg["damage"]) for lg in logs
                       if lg["type"] == "combat" and int(lg["player"]) == 1)

    assert melee_damage > 0, "l'episode n'a produit aucun degat de melee : le controle serait vide"
    assert tactical["damage_dealt"] == shoot_damage + melee_damage


# ─────────────────────────────────────────────────────────────────────────────
# Les courbes qui en dependent sortent vraiment
# ─────────────────────────────────────────────────────────────────────────────

class _RecordingWriter:
    """Doublure typee du writer TensorBoard (contrat MetricsWriter)."""

    def __init__(self) -> None:
        self.scalars: List[Tuple[str, float, int]] = []

    def add_scalar(self, key: str, value: float, step: int, /) -> None:
        self.scalars.append((key, value, step))

    def add_custom_scalars(self, layout: Dict[str, Any], /) -> None:
        pass

    def flush(self) -> None:
        pass

    def close(self) -> None:
        pass


def test_the_four_tensorboard_curves_are_emitted_from_a_real_episode(tmp_path) -> None:
    """Les gardes `> 0` de log_tactical_metrics ne rendent plus ces courbes muettes.

    Les brutes rebranchees ne suffisent pas : ce sont les derivees (accuracy,
    damage_efficiency) que l'on lit pour juger si l'agent apprend a se battre.
    """
    from ai.metrics_tracker import W40KMetricsTracker

    _engine, tactical = _play_episode(controlled_player=1, seed=7)

    # Vrai tracker (tous ses accumulateurs initialises), writer remplace pour lire les sorties.
    tracker = W40KMetricsTracker("ArmageddonAgent", log_dir=str(tmp_path), show_banner=False)
    recording = _RecordingWriter()
    tracker.writer = recording
    tracker.episode_count = 1
    tracker.log_tactical_metrics(tactical)

    emitted = {key for key, _value, _step in tracker.writer.scalars}
    assert "game_tactical/shooting_accuracy" in emitted
    assert "game_detailed/damage_dealt" in emitted
    assert "game_detailed/damage_received" in emitted
    assert "game_tactical/damage_efficiency" in emitted

    by_key = {key: value for key, value, _step in tracker.writer.scalars}
    assert by_key["game_tactical/shooting_accuracy"] == pytest.approx(
        tactical["hits"] / tactical["shots_fired"]
    )
    assert by_key["game_tactical/damage_efficiency"] == pytest.approx(
        tactical["damage_dealt"] / tactical["damage_received"]
    )
