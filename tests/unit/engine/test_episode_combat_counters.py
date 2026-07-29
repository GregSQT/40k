"""Tests — les quatre compteurs de combat d'``episode_tactical_data``.

``shots_fired``, ``hits``, ``damage_dealt``, ``damage_received`` ont ete DECLARES puis jamais
incrementes pendant neuf mois : le commit ``fe1df7d8`` « metrics OK » (2025-10-25) a deplace
``episode_tactical_data`` du callback vers le moteur en reimplementant les autres compteurs,
mais pas ceux-la, tout en supprimant leur calcul cote callback dans le meme diff. Rien ne l'a
attrape, parce que leurs consommateurs (``ai/metrics_tracker.log_tactical_metrics``) sont
gardes par ``> 0`` : une courbe absente ne se distingue pas d'un agent qui ne se bat jamais.

DEUX FAMILLES DE TESTS, ET C'EST DELIBERE.

1. Les tests de VOLUME (« les compteurs bougent ») MONTENT la situation qu'ils observent :
   figurines posees au contact pour la melee, hors de portee de charge pour le tir, des pinees
   sur 6 et armes DEVASTATING_WOUNDS pour qu'une blessure passe a coup sur (24.10 : pas de
   sauvegarde contre une blessure critique). Une premiere version de ce fichier jouait des
   episodes aleatoires en ESPERANT du combat ; quatre tests sont tombes le jour ou des
   correctifs de regles (vol 21.03, redemarrage de l'activation de melee) ont change la partie
   produite par la meme graine. Mesure apres coup : sur 40 graines, 2 ne produisent AUCUN degat
   du camp controle. Le pari etait donc perdant a 5 %, et il l'a ete.

2. Les tests de COHERENCE CROISEE jouent au contraire de VRAIS episodes, sans rien presupposer,
   et n'assertent que des EGALITES — vraies meme a zero. C'est de la qu'ils tirent leur valeur :
   ils relient le journal a l'etat reel du plateau. Ils tournent sur des graines pacifiques
   CHOISIES pour ca (28 et 39), pour que l'egalite a zero soit couverte explicitement.
"""

from __future__ import annotations

import random
from typing import Any, Callable, Dict, List, Tuple
from unittest.mock import patch

import numpy as np
import pytest

from engine.observation_builder import ObservationBuilder
from engine.phase_handlers.shared_utils import SQUAD_ACTION_WAIT
from engine.reward_calculator import RewardCalculator
from engine.w40k_core import W40KEngine


# ─────────────────────────────────────────────────────────────────────────────
# Harnais — vrai W40KEngine depuis une config en memoire, figurines posees au hex
# (idiome de tests/unit/engine/test_close_quarters_monster_vehicle_mono.py)
# ─────────────────────────────────────────────────────────────────────────────

#: « Devastating wounds » : une blessure critique (6 non modifie) ne souffre AUCUNE
#: sauvegarde (24.10). Avec le de pine sur 6, chaque attaque touche, blesse de facon
#: critique, et inflige donc ses degats — sans dependre du seuil de sauvegarde.
DEVASTATING = ["DEVASTATING_WOUNDS"]


def _weapon(rng: int, name: str, rules: List[str]) -> Dict[str, Any]:
    return {"ATK": 2, "STR": 4, "AP": 0, "DMG": 1, "NB": 2, "RNG": rng,
            "WEAPON_RULES": list(rules), "display_name": name}


def _unit(uid: int, player: int, col: int, row: int,
          rules: List[str], move: int = 6) -> Dict[str, Any]:
    return {
        "id": uid, "player": player, "col": col, "row": row,
        "unitType": "TestUnit", "DISPLAY_NAME": f"Unit {uid}",
        "HP_CUR": 6, "HP_MAX": 6, "MOVE": move, "T": 4,
        "ARMOR_SAVE": 3, "INVUL_SAVE": 0,
        "RNG_WEAPONS": [_weapon(24, "Test Bolter", rules)],
        "CC_WEAPONS": [_weapon(1, "Test Blade", rules)],
        "UNIT_RULES": [], "UNIT_KEYWORDS": [], "LD": 7, "OC": 1, "VALUE": 100,
        "ICON": "test", "ICON_SCALE": 1.0, "ILLUSTRATION_RATIO": 1.0,
        "BASE_SHAPE": "round", "BASE_SIZE": 1, "MODEL_HEIGHT": 2.5,
    }


def _config(units: List[Dict[str, Any]], controlled_player: int,
            charge_max_distance: int = 12) -> Dict[str, Any]:
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
        "charge": {"charge_max_distance": charge_max_distance},
        "pve_mode": False,
        "controlled_player": controlled_player,
        "observation_params": obs_params,
        "training_config": {"observation_params": obs_params},
        "units": units,
    }


@pytest.fixture(autouse=True)
def _stub_rewards(monkeypatch: pytest.MonkeyPatch) -> None:
    """Les recompenses exigent une config d'agent ; elles ne pesent pas sur les compteurs."""
    monkeypatch.setattr(RewardCalculator, "calculate_reward", lambda self, *a, **kw: 0.0)
    monkeypatch.setattr(
        W40KEngine, "_build_observation",
        lambda self: np.zeros(ObservationBuilder.SQUAD_OBS_SIZE_TARGET),
    )


def _build(config: Dict[str, Any]) -> W40KEngine:
    with patch("engine.w40k_core.load_weapon_damage_table", return_value={}), \
         patch.object(W40KEngine, "_build_reward_configs_for_current_units", return_value={}):
        engine = W40KEngine(config=config, gym_training_mode=True, quiet=True)
    engine.reset()
    return engine


def _run_to_end(engine: W40KEngine, pick: Callable[[Any], int]) -> Dict[str, Any]:
    """Joue jusqu'a la fin de l'episode ; rend le ``tactical_data`` emis a la terminaison."""
    info: Dict[str, Any] = {}
    for _ in range(4000):
        mask = engine.get_action_mask()
        legal = np.flatnonzero(mask)
        action = int(pick(legal)) if legal.size else SQUAD_ACTION_WAIT
        _obs, _reward, terminated, truncated, info = engine.step(action)
        if terminated or truncated:
            break
    assert "tactical_data" in info, "l'episode ne s'est pas termine : pas de tactical_data"
    return info["tactical_data"]


# ─────────────────────────────────────────────────────────────────────────────
# Montages DETERMINISTES : la situation est construite, pas esperee
# ─────────────────────────────────────────────────────────────────────────────

#: Politiques d'action deterministes (aucune graine). Le montage decide de la situation
#: tactique ; la politique decide seulement quelle action legale est jouee. On en essaie
#: plusieurs et on garde la premiere qui produit la situation EXIGEE — si aucune n'y arrive,
#: le test echoue en le disant, au lieu de verifier le vide.
_POLICIES: Dict[str, Callable[[Any], int]] = {
    "first": lambda legal: legal[0],
    "middle": lambda legal: legal[len(legal) // 2],
    "last": lambda legal: legal[-1],
}


def _pinned_die(monkeypatch: pytest.MonkeyPatch, value: int = 6) -> None:
    """Epingle ``random.randint`` — le moteur n'a pas de ``roll_d6``, il appelle randint(1, 6).

    Idiome de tests/unit/engine/test_blast_cleave.py et test_rapid_fire_shoot.py.
    """
    monkeypatch.setattr(random, "randint", lambda a, b: value)


def _attack_logs(engine: W40KEngine) -> List[Dict[str, Any]]:
    return [lg for lg in engine.game_state["action_logs"]
            if lg.get("type") in ("shoot", "combat")]


def _attacks_of(engine: W40KEngine, log_type: str, player: int) -> int:
    return sum(len(lg["shootDetails"]) for lg in _attack_logs(engine)
               if lg["type"] == log_type and int(lg["player"]) == player)


def _damage_of(engine: W40KEngine, log_type: str, player: int) -> int:
    return sum(int(lg["damage"]) for lg in _attack_logs(engine)
               if lg["type"] == log_type and int(lg["player"]) == player)


def _melee_units(controlled_player: int) -> List[Dict[str, Any]]:
    """Les deux camps DEJA au contact : la melee n'attend ni deplacement ni charge."""
    _ = controlled_player
    return [_unit(1, 1, 7, 6, DEVASTATING), _unit(2, 1, 7, 7, DEVASTATING),
            _unit(3, 2, 8, 6, DEVASTATING), _unit(4, 2, 8, 7, DEVASTATING)]


def _ranged_units() -> List[Dict[str, Any]]:
    """Camps a 10 hexes, MOVE 1 : hors d'atteinte pour toute la partie, mais a portee 24."""
    return [_unit(1, 1, 2, 6, DEVASTATING, move=1), _unit(2, 1, 2, 7, DEVASTATING, move=1),
            _unit(3, 2, 12, 6, DEVASTATING, move=1), _unit(4, 2, 12, 7, DEVASTATING, move=1)]


def _play_until(
    monkeypatch: pytest.MonkeyPatch,
    units: List[Dict[str, Any]],
    controlled_player: int,
    require: Callable[[W40KEngine, Dict[str, Any]], bool],
    what: str,
    charge_max_distance: int = 12,
) -> Tuple[W40KEngine, Dict[str, Any]]:
    """Joue l'episode avec chaque politique jusqu'a obtenir ``require``, sinon echoue en le disant.

    Borne stricte : le nombre de politiques. Aucune graine, aucun tirage — si un futur
    correctif de regles fait qu'aucune politique ne produit plus la situation, le test le dit
    au lieu de devenir silencieusement vacant.
    """
    _pinned_die(monkeypatch)
    tried: List[str] = []
    for name, pick in _POLICIES.items():
        engine = _build(_config(units, controlled_player, charge_max_distance))
        tactical = _run_to_end(engine, pick)
        if require(engine, tactical):
            return engine, tactical
        tried.append(name)
    raise AssertionError(
        f"aucune politique deterministe {tried} n'a produit {what} : le montage ne cree plus "
        f"la situation qu'il pretend observer — a corriger, ce test ne doit pas verifier le vide"
    )


def _melee_episode(monkeypatch: pytest.MonkeyPatch,
                   controlled_player: int = 1) -> Tuple[W40KEngine, Dict[str, Any]]:
    """Episode de melee PURE du cote controle : des degats au corps a corps, aucun tir.

    La purete est exigee, pas esperee : c'est elle qui permet d'affirmer que ``shots_fired``
    reste a zero PARCE QUE la melee en est exclue, et non parce que rien ne s'est passe.
    """
    return _play_until(
        monkeypatch, _melee_units(controlled_player), controlled_player,
        require=lambda eng, _td: (_damage_of(eng, "combat", controlled_player) > 0
                                  and _attacks_of(eng, "shoot", controlled_player) == 0),
        what="une melee pure avec des degats",
    )


def _ranged_episode(monkeypatch: pytest.MonkeyPatch,
                    controlled_player: int = 1) -> Tuple[W40KEngine, Dict[str, Any]]:
    """Episode de TIR PUR du cote controle : des degats a distance, aucune melee.

    Purete exigee pour la meme raison : sans elle, ``damage_dealt`` melangerait les deux
    phases et le test ne dirait plus lequel des deux chemins l'alimente.
    """
    return _play_until(
        monkeypatch, _ranged_units(), controlled_player,
        require=lambda eng, _td: (_damage_of(eng, "shoot", controlled_player) > 0
                                  and _attacks_of(eng, "combat", controlled_player) == 0),
        what="un tir pur avec des degats",
        charge_max_distance=1,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Volume — les quatre compteurs bougent (situation construite)
# ─────────────────────────────────────────────────────────────────────────────

def test_the_four_counters_are_non_zero_on_a_built_firefight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Le branchement existe : sur un echange de tirs monte de toutes pieces, aucun des quatre
    ne reste a zero.

    C'est l'assertion qui manquait pendant neuf mois — les quatre valaient 0 et la suite etait
    verte.
    """
    _engine, tactical = _ranged_episode(monkeypatch)

    assert tactical["shots_fired"] > 0, "aucun tir compte"
    assert tactical["hits"] > 0, "aucune touche comptee"
    assert tactical["damage_dealt"] > 0, "aucun degat inflige compte"
    assert tactical["damage_received"] > 0, "aucun degat recu compte"


def test_shooting_feeds_shots_hits_and_damage(monkeypatch: pytest.MonkeyPatch) -> None:
    """Chaque attaque de tir est comptee une fois, et les touches sont les jets reussis."""
    engine, tactical = _ranged_episode(monkeypatch)

    expected_shots = _attacks_of(engine, "shoot", player=1)
    expected_hits = sum(
        1 for lg in _attack_logs(engine)
        if lg["type"] == "shoot" and int(lg["player"]) == 1
        for shot in lg["shootDetails"] if shot["hitResult"] == "HIT"
    )
    assert expected_shots > 0, "montage casse : l'episode de tir n'a produit aucune attaque"

    assert tactical["shots_fired"] == expected_shots
    assert tactical["hits"] == expected_hits
    assert tactical["damage_dealt"] == _damage_of(engine, "shoot", player=1)


def test_melee_feeds_damage_but_never_shots(monkeypatch: pytest.MonkeyPatch) -> None:
    """La melee alimente l'attrition, jamais les tirs — choix de definition, verrouille ici.

    ``accuracy = hits / shots_fired`` est une precision au TIR (CT). Y verser les attaques de
    melee (CC) la rendrait ininterpretable. L'exclusion est donc exigee par un test, sur un
    episode ou la melee est la SEULE source de degats : si quelqu'un elargit ``shots_fired``
    a la melee, ce test rougit et l'oblige a decider sciemment.
    """
    engine, tactical = _melee_episode(monkeypatch)

    melee_attacks = _attacks_of(engine, "combat", player=1)
    melee_damage = _damage_of(engine, "combat", player=1)
    assert melee_attacks > 0, "montage casse : l'episode de melee n'a produit aucune attaque"
    assert melee_damage > 0, "montage casse : l'episode de melee n'a inflige aucun degat"

    assert _attacks_of(engine, "shoot", player=1) == 0, "ce montage doit etre melee pure"
    assert tactical["shots_fired"] == 0
    assert tactical["hits"] == 0
    # ... mais l'attrition, elle, compte bien la melee.
    assert tactical["damage_dealt"] == melee_damage


# ─────────────────────────────────────────────────────────────────────────────
# Coherence croisee — vrais episodes joues, EGALITES seulement (vraies meme a zero)
# ─────────────────────────────────────────────────────────────────────────────

def _random_episode(seed: int, controlled_player: int) -> Tuple[W40KEngine, Dict[str, Any]]:
    """Episode joue en actions legales tirees au sort — on ne presuppose RIEN de son contenu."""
    engine = _build(_config(
        [_unit(1, 1, 5, 6, []), _unit(2, 1, 5, 7, []),
         _unit(3, 2, 9, 6, []), _unit(4, 2, 9, 7, [])],
        controlled_player,
    ))
    rng = np.random.default_rng(seed)
    return engine, _run_to_end(engine, lambda legal: rng.choice(legal))


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


# 28 et 39 sont des graines PACIFIQUES : le camp controle n'y inflige aucun degat. Elles sont
# incluses expres — l'egalite doit tenir a zero aussi, et c'est ce qui rend ces tests immunises
# aux correctifs de regles qui changent la partie produite par une graine.
_EPISODE_SEEDS = [7, 11, 23, 28, 39]


@pytest.mark.parametrize("seed", _EPISODE_SEEDS)
def test_damage_dealt_matches_the_hp_the_opponent_actually_lost(seed: int) -> None:
    """Coherence croisee : ce que j'inflige = ce que l'adversaire perd, PV pour PV.

    C'est ce controle qui separe un compteur juste d'un compteur qui compte n'importe quoi :
    il relie le journal a l'etat reel du plateau, et non le journal a lui-meme. Il n'exige
    aucun combat — a zero partout, l'egalite tient et le controle reste valide.
    """
    engine, tactical = _random_episode(seed, controlled_player=1)
    hp_lost = _hp_lost_by_player(engine)

    assert tactical["damage_dealt"] == hp_lost[2]
    assert tactical["damage_received"] == hp_lost[1]


@pytest.mark.parametrize("controlled_player", [1, 2])
def test_counters_follow_the_controlled_seat(controlled_player: int) -> None:
    """Le siege compte : ``damage_received`` est celui de l'agent controle, pas d'un camp fixe.

    Sans ce controle, un compteur code en dur sur le joueur 1 passerait tout le reste.
    """
    engine, tactical = _random_episode(seed=5, controlled_player=controlled_player)
    hp_lost = _hp_lost_by_player(engine)
    opponent = 2 if controlled_player == 1 else 1

    assert tactical["damage_dealt"] == hp_lost[opponent]
    assert tactical["damage_received"] == hp_lost[controlled_player]


@pytest.mark.parametrize("seed", _EPISODE_SEEDS)
def test_hits_never_exceed_shots(seed: int) -> None:
    """Une touche est un tir reussi : ``hits <= shots_fired``, sinon accuracy depasse 1.

    Inegalite pure, sans ``> 0`` : elle doit tenir sur n'importe quel episode, y compris ceux
    ou personne ne tire. La preuve que les compteurs BOUGENT est ailleurs, sur montage construit.
    """
    _engine, tactical = _random_episode(seed, controlled_player=1)
    assert tactical["hits"] <= tactical["shots_fired"]


# ─────────────────────────────────────────────────────────────────────────────
# Les courbes qui en dependent sortent vraiment
# ─────────────────────────────────────────────────────────────────────────────

class _RecordingWriter:
    """Doublure typee du writer TensorBoard (contrat ``MetricsWriter``)."""

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


def test_the_four_tensorboard_curves_are_emitted(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Les gardes ``> 0`` de ``log_tactical_metrics`` ne rendent plus ces courbes muettes.

    Les brutes rebranchees ne suffisent pas : ce sont les derivees (accuracy,
    damage_efficiency) que l'on lit pour juger si l'agent apprend a se battre.
    """
    from ai.metrics_tracker import W40KMetricsTracker

    _engine, tactical = _ranged_episode(monkeypatch)

    # Vrai tracker (tous ses accumulateurs initialises), writer remplace pour lire les sorties.
    tracker = W40KMetricsTracker("ArmageddonAgent", log_dir=str(tmp_path), show_banner=False)
    recording = _RecordingWriter()
    tracker.writer = recording
    tracker.episode_count = 1
    tracker.log_tactical_metrics(tactical)

    emitted = {key for key, _value, _step in recording.scalars}
    assert "game_tactical/shooting_accuracy" in emitted
    assert "game_detailed/damage_dealt" in emitted
    assert "game_detailed/damage_received" in emitted
    assert "game_tactical/damage_efficiency" in emitted

    by_key = {key: value for key, value, _step in recording.scalars}
    assert by_key["game_tactical/shooting_accuracy"] == pytest.approx(
        tactical["hits"] / tactical["shots_fired"]
    )
    assert by_key["game_tactical/damage_efficiency"] == pytest.approx(
        tactical["damage_dealt"] / tactical["damage_received"]
    )
