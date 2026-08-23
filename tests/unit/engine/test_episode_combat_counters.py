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

from ai.metrics_tracker import W40KMetricsTracker
from engine.observation_builder import ObservationBuilder
from engine.phase_handlers.shared_utils import SQUAD_ACTION_WAIT
from engine.reward_calculator import RewardCalculator
from engine.w40k_core import W40KEngine
from tests._state_invariants import charge_log_line
from tests.unit.engine._config_helpers import build_engine_config


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
            "WEAPON_RULES": list(rules), "display_name": name, "code": name}


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
            "pile_in_target_range": 5, "consolidation_trigger_range": 3,
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
    """Les recompenses exigent une config d'agent ; elles ne pesent pas sur les compteurs.

    build_squad_grid exige que la carte de cellules du BFS ait ete construite via
    get_squad_action_mask_and_eligible_units. Dans ce harnais, l'observation n'est pas
    l'objet du test et la grille peut etre nulle — le step s'appuie sur
    _build_observation_and_mask directement (pas sur _build_observation), donc ce patch
    cible build_squad_grid plutot que _build_observation.
    """
    from engine.spatial_grid import GRID_CHANNELS, GRID_SIZE
    monkeypatch.setattr(RewardCalculator, "calculate_reward", lambda self, *a, **kw: 0.0)
    monkeypatch.setattr(
        ObservationBuilder, "build_squad_grid",
        lambda self, *_a, **_k: np.zeros((GRID_CHANNELS, GRID_SIZE, GRID_SIZE), dtype=np.float32),
    )


def _build(config: Dict[str, Any]) -> W40KEngine:
    with patch("engine.w40k_core.load_weapon_damage_table", return_value={}), \
         patch.object(W40KEngine, "_build_reward_configs_for_current_units", return_value={}):
        engine = W40KEngine(config=build_engine_config(config), gym_training_mode=True, quiet=True)
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


def _model_kills_of(engine: W40KEngine, log_type: str, player: int) -> List[Dict[str, Any]]:
    """Les attaques du camp `player` qui ont DETRUIT une figurine (une entree = une figurine)."""
    return [shot for lg in _attack_logs(engine)
            if lg["type"] == log_type and int(lg["player"]) == player
            for shot in lg["shootDetails"] if shot.get("targetDied")]


def _has_kill_after_the_first_attack(engine: W40KEngine, log_type: str, player: int) -> bool:
    """Au moins une figurine achevee par une attaque qui n'est pas la PREMIERE de son groupe.

    C'est la situation que l'ancienne formule de ``melee_kills`` (``shootDetails[0]``
    uniquement) ne voyait pas. Sans elle, les tests de kills ne distingueraient pas le
    compteur corrige de celui qu'il remplace.
    """
    return any(shot.get("targetDied") for lg in _attack_logs(engine)
               if lg["type"] == log_type and int(lg["player"]) == player
               for shot in lg["shootDetails"][1:])


def _enemy_models_destroyed(engine: W40KEngine, controlled_player: int) -> int:
    """Figurines adverses reellement retirees du plateau, lues sur l'etat, pas sur le journal.

    ``destroy_model`` retire la figurine morte de ``squad_models`` ET de ``models_cache`` :
    les morts ne sont plus enumerables, seuls les vivants le sont. On compte donc a l'envers,
    depuis les unites du scenario. Les montages de ce fichier sont MONO-FIGURINE (aucune cle
    ``models``) — verifie ici, sinon ce compte d'unites ne serait pas un compte de figurines.
    """
    gs = engine.game_state
    alive_ids = {str(uid) for uid in gs["units_cache"]}
    for mids in gs["squad_models"].values():
        assert len(mids) <= 1, "helper valable seulement sur un montage mono-figurine"
    return sum(1 for u in gs["units"]
               if int(u["player"]) != controlled_player and str(u["id"]) not in alive_ids)


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


def _melee_kill_episode(monkeypatch: pytest.MonkeyPatch,
                        controlled_player: int = 1) -> Tuple[W40KEngine, Dict[str, Any]]:
    """Melee pure AVEC des figurines tuees, dont au moins une hors de la premiere attaque.

    La derniere condition est ce qui donne sa valeur au test : c'est exactement le kill que
    l'ancienne formule (``shootDetails[0]``) ne comptait pas.
    """
    return _play_until(
        monkeypatch, _melee_units(controlled_player), controlled_player,
        require=lambda eng, _td: (_attacks_of(eng, "shoot", controlled_player) == 0
                                  and bool(_model_kills_of(eng, "combat", controlled_player))
                                  and _has_kill_after_the_first_attack(
                                      eng, "combat", controlled_player)),
        what="une melee pure tuant une figurine ailleurs qu'a la premiere attaque",
    )


def _ranged_episode(monkeypatch: pytest.MonkeyPatch,
                    controlled_player: int = 1) -> Tuple[W40KEngine, Dict[str, Any]]:
    """Episode de TIR PUR du cote controle : des degats a distance, aucune melee.

    Purete exigee pour la meme raison : sans elle, ``damage_dealt`` melangerait les deux
    phases et le test ne dirait plus lequel des deux chemins l'alimente.
    """
    return _play_until(
        monkeypatch, _ranged_units(), controlled_player,
        require=lambda eng, td: (_damage_of(eng, "shoot", controlled_player) > 0
                                 and _attacks_of(eng, "combat", controlled_player) == 0
                                 and td.get("damage_received", 0) > 0),
        what="un tir pur avec des degats des deux camps",
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
# Kills et VALUE detruite — par FIGURINE, dans les deux phases
# ─────────────────────────────────────────────────────────────────────────────

def test_melee_kills_count_every_model_not_just_the_first_attack(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``melee_kills`` compte chaque figurine tuee, quelle que soit l'attaque qui l'acheve.

    Jusqu'au 2026-07-30 le moteur ne lisait que ``shootDetails[0]["targetDied"]`` : il ne
    mesurait que « la premiere attaque du groupe a-t-elle tue ? », soit une probabilite quasi
    constante, independante de la competence de l'agent — d'ou une courbe l_melee_kills plate
    et bruitee pendant que k_shoot_kills progressait. Le montage EXIGE un kill hors premiere
    attaque : avec l'ancienne formule, ce test est rouge.
    """
    engine, tactical = _melee_kill_episode(monkeypatch)
    kills = _model_kills_of(engine, "combat", player=1)

    assert tactical["melee_kills"] == len(kills)
    # Le compte de l'ancienne formule, recalcule ici : il DOIT etre plus bas, sinon le montage
    # ne separe pas les deux implementations et le test ne verrouille rien.
    old_formula = sum(1 for lg in _attack_logs(engine)
                      if lg["type"] == "combat" and int(lg["player"]) == 1
                      and lg["shootDetails"] and lg["shootDetails"][0].get("targetDied"))
    assert old_formula < tactical["melee_kills"]


def test_shoot_kills_count_every_model_not_just_the_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``shoot_kills`` compte des FIGURINES, pas des groupes (arme, cible).

    L'entete du log porte ``target_died = kills > 0`` pour tout le groupe : un groupe qui tue
    trois figurines n'en aurait compte qu'une. Les deux phases suivent desormais la meme
    convention, seule facon de comparer k_ et l_ entre elles.
    """
    engine, tactical = _ranged_episode(monkeypatch)
    kills = _model_kills_of(engine, "shoot", player=1)

    assert tactical["shoot_kills"] == len(kills)
    assert tactical["melee_kills"] == 0, "ce montage doit etre tir pur"


@pytest.mark.parametrize("controlled_player", [1, 2])
def test_melee_kills_match_the_models_actually_removed(
    monkeypatch: pytest.MonkeyPatch, controlled_player: int
) -> None:
    """Coherence croisee : les kills comptes = les figurines reellement retirees du plateau.

    Le montage est une melee PURE du cote controle : aucune autre source de perte adverse,
    donc l'egalite journal/plateau doit tenir exactement, et sur les deux sieges.
    """
    engine, tactical = _melee_kill_episode(monkeypatch, controlled_player)

    assert tactical["melee_kills"] == _enemy_models_destroyed(engine, controlled_player)


def test_value_killed_sums_the_value_of_each_model_destroyed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``melee_value_killed`` somme la VALUE PAR FIGURINE des cibles detruites.

    C'est ce qui separe 20 gretchins a 4 points d'un monstre a 120 : le compte de tetes seul
    ne le dit pas. La VALUE lue doit etre celle de la figurine (100 ici), jamais celle de
    l'escouade — l'erreur classique de ce depot.
    """
    engine, tactical = _melee_kill_episode(monkeypatch)
    kills = _model_kills_of(engine, "combat", player=1)

    assert tactical["melee_value_killed"] == pytest.approx(
        sum(float(shot["targetValue"]) for shot in kills)
    )
    assert tactical["melee_value_killed"] == pytest.approx(100.0 * len(kills))
    assert tactical["shoot_value_killed"] == 0.0


def test_the_kill_and_value_curves_are_emitted(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Les quatre courbes sortent avec les valeurs de l'episode (02_combat/g_ h_ i_ j_)."""
    _engine, tactical = _melee_kill_episode(monkeypatch)

    tracker, recording = _recording_tracker(tmp_path)
    tracker.log_tactical_metrics(tactical)

    by_key = {key: value for key, value, _step in recording.scalars}
    assert by_key["02_combat/h_melee_model_kills"] == pytest.approx(tactical["melee_kills"])
    assert by_key["02_combat/g_shoot_model_kills"] == pytest.approx(tactical["shoot_kills"])
    assert by_key["02_combat/j_melee_value_killed"] == pytest.approx(tactical["melee_value_killed"])
    assert by_key["02_combat/i_shoot_value_killed"] == pytest.approx(tactical["shoot_value_killed"])


# ─────────────────────────────────────────────────────────────────────────────
# Charges — VENTILATION PAR SIEGE
#
# Les compteurs de charge sont verifies bout en bout dans test_episode_charge_counters, sur le
# seul scenario du depot ou une charge est reellement declarable. Ce qu'IL ne peut pas couvrir,
# c'est le siege 2 : son moteur se construit depuis un `scenario_file`, et cette branche fixe
# `controlled_player` a 1 en dur (w40k_core ~L297). Ce harnais-ci, lui, le prend en parametre.
# Les tentatives sont donc INJECTEES dans le journal : ce qu'on verifie ici n'est pas que le
# moteur produise des charges, mais que chaque ligne parte du bon cote — le defaut exact que le
# chemin callback avait deja produit (charges du BOT sous le drapeau de l'agent).
# ─────────────────────────────────────────────────────────────────────────────

#: Tentatives injectees : trois du joueur 1 (deux abouties), une du joueur 2 (ratee). Le
#: desequilibre est voulu — des chiffres identiques des deux cotes rendraient une inversion
#: des camps invisible.
_INJECTED_CHARGES = (("charge", 1), ("charge", 1), ("charge_fail", 1), ("charge_fail", 2))


def _inject_charges(engine: W40KEngine) -> None:
    """Ajoute ``_INJECTED_CHARGES`` au journal de l'episode en cours.

    Injecte juste apres le reset : ``action_logs`` n'est remis a zero QUE par ``reset()`` et
    n'est jamais purge en cours d'episode, donc ces lignes seront encore la a la terminaison,
    au moment ou le moteur fait sa passe de comptage.
    """
    for log_type, player in _INJECTED_CHARGES:
        # Le CONTRAT de la ligne vient du socle partage : les champs que la production lit sans
        # repli (les deux distances 11.04, `charge_failed_reason`) y sont poses une seule fois,
        # pour les deux fichiers qui injectent des charges. Cette injection-ci les avait perdus
        # au chantier 11.04, qui n'avait mis a jour que l'autre copie.
        engine.game_state["action_logs"].append(charge_log_line(
            player, log_type, roll=7, unitId="1", reward=0.0,
        ))


@pytest.mark.parametrize("controlled_player", [1, 2])
def test_charge_counters_ventilate_by_seat(
    monkeypatch: pytest.MonkeyPatch, controlled_player: int,
) -> None:
    """Chaque tentative est comptee du cote de SON joueur, sur les deux sieges.

    Les memes lignes injectees doivent basculer d'un jeu de compteurs a l'autre quand le siege
    change : c'est ce qui distingue une ventilation reelle d'un compteur qui verserait tout du
    meme cote et passerait quand meme au siege 1.
    """
    _pinned_die(monkeypatch)
    opponent = 2 if controlled_player == 1 else 1
    engine = _build(_config(_melee_units(controlled_player), controlled_player))
    _inject_charges(engine)
    tactical = _run_to_end(engine, _POLICIES["first"])

    def _count(player: int, types: Tuple[str, ...]) -> int:
        return sum(1 for lg in engine.game_state["action_logs"]
                   if lg.get("type") in types and int(lg["player"]) == player)

    assert tactical["charge_attempts"] == _count(controlled_player, ("charge", "charge_fail"))
    assert tactical["charge_successes"] == _count(controlled_player, ("charge",))
    assert tactical["charge_attempts_opponent"] == _count(opponent, ("charge", "charge_fail"))
    assert tactical["charge_successes_opponent"] == _count(opponent, ("charge",))
    # Les deux cotes portent des tentatives : sans ca les egalites tiendraient a zero.
    assert tactical["charge_attempts"] > 0
    assert tactical["charge_attempts_opponent"] > 0
    # Et les totaux injectes se retrouvent bien, repartis selon le siege.
    assert (tactical["charge_successes"] + tactical["charge_successes_opponent"]) == 2
    assert (tactical["charge_attempts"] + tactical["charge_attempts_opponent"]) == 4


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


def _recording_tracker(tmp_path: Any) -> Tuple[W40KMetricsTracker, _RecordingWriter]:
    """Vrai tracker (tous ses accumulateurs initialises), writer remplace pour lire les sorties.

    Les deux fenetres de lissage sont ramenees a 1 : ces tests lisent les courbes d'UN episode,
    la ou les fenetres de production (500/100) exigeraient d'en rejouer des centaines avant
    qu'un point sorte (``_emit_windowed`` n'emet qu'a fenetre PLEINE). Egales, elles suppriment
    aussi le doublon reactif ``_<fast>ep``, donc chaque tag n'apparait qu'une fois.
    """
    tracker = W40KMetricsTracker(
        "ArmageddonAgent", log_dir=str(tmp_path), show_banner=False,
        perf_window=1, perf_window_fast=1,
    )
    recording = _RecordingWriter()
    tracker.writer = recording
    tracker.episode_count = 1
    return tracker, recording


def test_the_four_tensorboard_curves_are_emitted(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Les gardes ``> 0`` de ``log_tactical_metrics`` ne rendent plus ces courbes muettes.

    Les brutes rebranchees ne suffisent pas : ce sont les derivees (accuracy,
    damage_efficiency) que l'on lit pour juger si l'agent apprend a se battre.
    """
    _engine, tactical = _ranged_episode(monkeypatch)

    tracker, recording = _recording_tracker(tmp_path)
    tracker.log_tactical_metrics(tactical)

    emitted = {key for key, _value, _step in recording.scalars}
    assert "04_shoot/b_accuracy" in emitted
    assert "game_detailed/damage_dealt" in emitted
    assert "game_detailed/damage_received" in emitted
    assert "02_combat/q_damage_efficiency" in emitted

    by_key = {key: value for key, value, _step in recording.scalars}
    assert by_key["04_shoot/b_accuracy"] == pytest.approx(
        tactical["hits"] / tactical["shots_fired"]
    )
    assert by_key["02_combat/q_damage_efficiency"] == pytest.approx(
        tactical["damage_dealt"] / tactical["damage_received"]
    )

# ─────────────────────────────────────────────────────────────────────────────
# Effectifs de depart et ratios 02_combat/ — denominateurs, pas compteurs bruts
# ─────────────────────────────────────────────────────────────────────────────

def _asymmetric_units() -> List[Dict[str, Any]]:
    """Montage ou les QUATRE effectifs sont DISTINCTS : 1 escouade alliee de 3 figurines
    a 40 points contre 2 escouades ennemies mono-figurine a 100.

    C'est la seule facon de verrouiller les ratios : sur un montage symetrique
    mono-figurine, figurines et unites valent le meme nombre des deux cotes, et une
    confusion allie/ennemi ou figurine/unite passerait tous les controles. Les deux camps
    sont DEJA au contact — la melee n'attend ni deplacement ni charge.
    """
    ally = _unit(1, 1, 7, 6, DEVASTATING)
    # models[0] DOIT etre a l'ancre de l'unite (invariant multi-figurine de build_units_cache).
    ally["models"] = [
        {"col": 7, "row": 6, "VALUE": 40}, {"col": 7, "row": 5, "VALUE": 40},
        {"col": 7, "row": 7, "VALUE": 40},
    ]
    ally["VALUE"] = 120
    return [ally, _unit(3, 2, 8, 6, DEVASTATING), _unit(4, 2, 8, 7, DEVASTATING)]


def _asymmetric_config() -> Dict[str, Any]:
    config = _config(_asymmetric_units(), controlled_player=1)
    # Exigees des qu'une escouade a plusieurs figurines (coherence 03.03).
    config["game_rules"]["unit_model_cohesion_range"] = 2
    config["game_rules"]["unit_global_cohesion_range"] = 9
    config["game_rules"]["squad_min_neighbors"] = 1
    config["game_rules"]["cohesion_distance_mode"] = "euclidean"
    return config


def _asymmetric_episode(monkeypatch: pytest.MonkeyPatch) -> Tuple[W40KEngine, Dict[str, Any]]:
    """Episode ou les DEUX camps perdent des figurines, l'escouade alliee restant ENTAMEE
    mais vivante.

    Sans pertes, tous les ratios valent 0 et un mauvais denominateur passerait inapercu
    (0/2 = 0/3). Sans escouade SURVIVANTE entamee, l'attrition en VALUE comptee a l'escouade
    (valeur entiere tant qu'une figurine tient) donnerait le meme resultat que le compte par
    figurine — c'est exactement le defaut que ce montage doit voir.

    Meme idiome que ``_play_until`` : on essaie les politiques deterministes et on garde la
    premiere qui produit la situation EXIGEE, au lieu de l'esperer d'une graine.
    """
    _pinned_die(monkeypatch)
    for _name, policy in _POLICIES.items():
        engine = _build(_asymmetric_config())
        tactical = _run_to_end(engine, policy)
        survivors = tactical["initial_ally_models"] - tactical["models_lost"]
        if tactical["models_lost"] > 0 and tactical["models_killed"] > 0 and survivors > 0:
            return engine, tactical
    raise AssertionError("aucune politique n'a produit de pertes des DEUX cotes")


def test_initial_model_counts_are_per_side_and_survive_the_deaths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Les effectifs de depart en FIGURINES sont releves par camp, et par camp seulement.

    Ils ne sont plus derivables en fin d'episode (``models_cache`` perd les mortes), d'ou la
    photo posee par ``build_units_cache`` au reset : c'est elle que ce controle verrouille,
    contre le compte d'unites.
    """
    engine, tactical = _asymmetric_episode(monkeypatch)

    assert tactical["initial_ally_models"] == 3
    assert tactical["initial_enemy_models"] == 2
    assert tactical["total_ally_units"] == 1
    assert tactical["total_enemy_units"] == 2

    # Les pertes sont bien la difference avec les figurines VIVANTES, lues sur le plateau.
    models_cache = engine.game_state["models_cache"]
    alive_ally = sum(1 for m in models_cache.values() if int(m["player"]) == 1)
    alive_enemy = sum(1 for m in models_cache.values() if int(m["player"]) == 2)
    assert tactical["models_lost"] == 3 - alive_ally
    assert tactical["models_killed"] == 2 - alive_enemy
    assert tactical["total_ally_value"] == pytest.approx(120.0)
    assert tactical["total_enemy_value"] == pytest.approx(200.0)

    # L'escouade alliee est ENTAMEE, pas detruite : sa VALUE perdue doit valoir les figurines
    # tombees (40 chacune), et non 0 comme le donnait le compte a l'escouade.
    assert tactical["models_lost"] > 0 and alive_ally > 0
    assert tactical["ally_value_lost"] == pytest.approx(40.0 * tactical["models_lost"])


def test_the_zero_combat_ratios_use_their_own_denominators(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Chaque ratio 02_combat/ divise par SON effectif de depart, pas par celui d'a cote."""
    _engine, tactical = _asymmetric_episode(monkeypatch)

    tracker, recording = _recording_tracker(tmp_path)
    tracker.log_tactical_metrics(tactical)

    by_key = {key: value for key, value, _step in recording.scalars}
    assert by_key["02_combat/c_models_killed_ratio"] == pytest.approx(tactical["models_killed"] / 2)
    assert by_key["02_combat/d_models_lost_ratio"] == pytest.approx(tactical["models_lost"] / 3)
    assert by_key["02_combat/e_value_killed_ratio"] == pytest.approx(
        tactical["enemy_value_destroyed"] / 200.0
    )
    assert by_key["02_combat/f_value_lost_ratio"] == pytest.approx(
        tactical["ally_value_lost"] / 120.0
    )
    assert by_key["02_combat/k_units_killed_ratio"] == pytest.approx(tactical["units_killed"] / 2)
    assert by_key["02_combat/l_units_lost_ratio"] == pytest.approx(tactical["units_lost"] / 1)

    # Les ratios ne sont pas tous nuls : sans ca, 0/2 et 0/3 seraient indistinguables et
    # ce controle vaudrait pour n'importe quel denominateur.
    assert by_key["02_combat/d_models_lost_ratio"] > 0
    assert by_key["02_combat/c_models_killed_ratio"] > 0
