"""Tests — les DEUX distances de charge (11.04) : journal, compteurs, courbes.

Ce que ces distances servent : le step.log du 2026-08-11 (494 charges) avait montre que 41 %
des declarations de l'agent visaient une cible a 9" ou plus, quand un 2D6 n'atteint 9 que
27,8 % du temps — mediane des ratees a 9", des reussies a 5". Il avait fallu re-deriver ces
chiffres a la main depuis les coordonnees loggees. Depuis l'alignement sur 11.02, la
DECLARATION (l'activation, 11.02.1) et le CHOIX DE CIBLE (11.04) sont deux instants distincts
et reels : la mesure est desormais prise a l'instant ou la regle la regarde.

TROIS choses se verrouillent ici, et elles echouent de trois façons differentes :

1. COUVERTURE. Les lignes de charge naissent a SEPT endroits (5 dans `charge_handlers` pour le
   chemin PvP/PvE, 2 dans `w40k_core` pour le chemin gym). Le chemin gym est celui qui produit
   le step.log d'entrainement : une couverture partielle rendrait la mesure muette la ou elle
   sert. Les tests d'episode ci-dessous passent par les sites GYM.

2. INSTANT DE LA MESURE. `commit_move` deplace les figurines : une distance relevee au site de
   succes vaudrait « au contact » sur TOUTES les charges reussies, et la moyenne des reussies
   s'effondrerait vers l'ER sans que rien ne leve. C'est le sujet de
   `test_the_target_distance_is_measured_before_the_charge_move`.

3. DENOMINATEUR. Une activation close sur WAIT (11.02.3 « if you still want to ») n'est pas une
   tentative de charge. La compter diluerait la part de declarations lointaines — d'autant plus
   que l'agent renonce souvent.

Meme harnais que `test_episode_charge_counters` (scenario melee de `scripts/smoke_t5_bare`, le
seul montage du depot ou une charge soit reellement declarable) et meme doctrine : ce qui doit
etre vrai est CONSTRUIT, jamais espere d'une graine.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
import pytest

from smoke_t5_bare import MELEE_SCENARIO

from ai.metrics_tracker import W40KMetricsTracker  # noqa: E402
from ai.step_logger import _charge_distance_segment  # noqa: E402
from ai.unit_registry import UnitRegistry  # noqa: E402
from engine.phase_handlers.shared_utils import SQUAD_ACTION_WAIT  # noqa: E402
from engine.w40k_core import CHARGE_DISTANCE_MEASURES, W40KEngine  # noqa: E402

_SEEDS = (1, 2, 3, 4, 5, 6, 7, 8)

#: Types de journal qui portent une issue de charge, donc les deux distances.
_CHARGE_TYPES = ("charge", "charge_fail")


@pytest.fixture(scope="module")
def melee_scenario_file():
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "melee.json"
        path.write_text(json.dumps(MELEE_SCENARIO))
        yield str(path)


def _play(
    scenario_file: str, seed: int, charge_policy: str = "declare",
) -> Tuple[W40KEngine, Dict[str, Any]]:
    """Joue un episode complet ; rend (moteur, tactical_data).

    `charge_policy` :
      - `declare` : en phase de charge, la premiere action legale qui n'est pas `wait`. C'est le
        sujet du fichier — tirer au sort la seule action mesuree reviendrait a esperer d'une
        graine ce que le test pretend observer.
      - `wait`    : en phase de charge, TOUJOURS `wait`. Sert le verrou du denominateur : une
        activation close sur un renoncement ne doit produire aucune tentative.
    """
    engine = W40KEngine(
        rewards_config="ArmageddonAgent", training_config_name="x1_debug",
        controlled_agent="ArmageddonAgent", scenario_file=scenario_file,
        unit_registry=UnitRegistry(), quiet=True, gym_training_mode=True,
    )
    engine.reset(seed=seed)
    rng = np.random.default_rng(seed)
    info: Dict[str, Any] = {}
    for _ in range(4000):
        legal = np.flatnonzero(engine.get_action_mask())
        if not legal.size:
            action = SQUAD_ACTION_WAIT
        elif engine.game_state["phase"] == "charge":
            if charge_policy == "wait":
                action = SQUAD_ACTION_WAIT
            else:
                declared = [int(a) for a in legal if int(a) != SQUAD_ACTION_WAIT]
                action = declared[0] if declared else SQUAD_ACTION_WAIT
        else:
            action = int(rng.choice(legal))
        _obs, _reward, terminated, truncated, info = engine.step(action)
        if terminated or truncated:
            break
    assert "tactical_data" in info, "l'episode ne s'est pas termine : pas de tactical_data"
    return engine, info["tactical_data"]


_EPISODES: Dict[Tuple[int, str], Tuple[W40KEngine, Dict[str, Any]]] = {}


def _cached_play(
    scenario_file: str, seed: int, charge_policy: str = "declare",
) -> Tuple[W40KEngine, Dict[str, Any]]:
    """`_play` memoise sur (graine, politique). Episodes STRICTEMENT deterministes, partages en
    LECTURE SEULE : aucun test ne mute le moteur ni le `tactical_data` rendus."""
    key = (seed, charge_policy)
    if key not in _EPISODES:
        _EPISODES[key] = _play(scenario_file, seed, charge_policy)
    return _EPISODES[key]


def _charge_lines(engine: W40KEngine) -> List[Dict[str, Any]]:
    return [lg for lg in engine.game_state["action_logs"] if lg.get("type") in _CHARGE_TYPES]


def _episode_with_charges(scenario_file) -> Tuple[W40KEngine, Dict[str, Any]]:
    """Un episode ou au moins une charge a ete tentee. Sinon le fichier verifie le vide."""
    for seed in _SEEDS:
        engine, tactical = _cached_play(scenario_file, seed)
        if _charge_lines(engine):
            return engine, tactical
    raise AssertionError(
        f"aucune graine {list(_SEEDS)} n'a produit de charge : le montage ne cree plus la "
        "situation qu'il pretend observer — a corriger, ce test ne doit pas verifier le vide"
    )


def _episode_with_successful_charges(scenario_file) -> Tuple[W40KEngine, Dict[str, Any]]:
    for seed in _SEEDS:
        engine, tactical = _cached_play(scenario_file, seed)
        if any(lg.get("type") == "charge" for lg in _charge_lines(engine)):
            return engine, tactical
    raise AssertionError(
        f"aucune graine {list(_SEEDS)} n'a produit de charge REUSSIE : montage a corriger"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 1. Couverture — chaque ligne de charge porte les deux distances
# ─────────────────────────────────────────────────────────────────────────────

def test_every_charge_line_carries_the_declaration_distance(melee_scenario_file) -> None:
    """`charge_nearest_enemy_inches` est present sur TOUTE ligne de charge, succes ou echec.

    C'est la mesure prise a la declaration (11.02.1), donc elle existe des que l'escouade s'est
    activee — independamment de ce qui a suivi. Une ligne sans elle signale un site de
    journalisation oublie : c'est exactement le motif jumeau qui a fait passer le compte de
    sites de cinq (ceux de `charge_handlers`) a sept.
    """
    engine, _tactical = _episode_with_charges(melee_scenario_file)
    lines = _charge_lines(engine)
    for line in lines:
        assert "charge_nearest_enemy_inches" in line, (
            f"ligne {line.get('type')} de l'unite {line.get('unitId')} sans distance de "
            "declaration : un site de journalisation de charge n'a pas ete couvert"
        )
        assert line["charge_nearest_enemy_inches"] > 0, (
            "distance nulle a l'ennemi le plus proche : la mesure a ete prise apres le "
            "deplacement de charge, pas a la declaration"
        )


def test_a_successful_charge_carries_the_target_distance(melee_scenario_file) -> None:
    """Une charge REUSSIE porte aussi la distance a la cible choisie (11.04)."""
    engine, _tactical = _episode_with_successful_charges(melee_scenario_file)
    for line in _charge_lines(engine):
        if line.get("type") != "charge":
            continue
        assert line["charge_target_distance_inches"] is not None
        assert line["charge_target_distance_inches"] > 0


def test_the_target_distance_is_measured_before_the_charge_move(melee_scenario_file) -> None:
    """VERROU DE L'INSTANT : au moins une charge reussie part de plus loin que l'ER.

    Apres un `commit_move` de charge, l'escouade est ENGAGEE avec sa cible, donc a 2" ou moins
    (03.04). Si la mesure etait prise au site de succes plutot qu'au choix de la cible, TOUTES
    les distances de charge reussie tiendraient sous cette borne et la moyenne des reussies
    s'effondrerait — sans qu'aucun `require_key` ne leve, puisque le champ serait bien la.

    Le seuil compare est l'ENGAGEMENT RANGE lu dans la config, pas un 2 ecrit en dur : c'est la
    borne que le moteur applique reellement.
    """
    engine, _tactical = _episode_with_successful_charges(melee_scenario_file)
    from engine.phase_handlers.shared_utils import get_engagement_zone

    ez_inches = get_engagement_zone(engine.game_state) / int(
        engine.game_state["inches_to_subhex"]
    )
    distances = [
        lg["charge_target_distance_inches"]
        for lg in _charge_lines(engine)
        if lg.get("type") == "charge"
    ]
    assert distances, "montage casse : aucune charge reussie"
    assert max(distances) > ez_inches, (
        f"toutes les charges reussies partent d'au plus {ez_inches}\" (l'engagement range) : "
        "la distance est mesuree APRES le mouvement de charge, pas au choix de la cible"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 2. Compteurs d'episode
# ─────────────────────────────────────────────────────────────────────────────

def test_the_distance_counters_match_the_journal(melee_scenario_file) -> None:
    """Sommes et effectifs des distances = ce que porte le journal, camp par camp.

    Ces compteurs se derivent des lignes de charge, dans la MEME passe et sur le meme couple de
    types que `charge_attempts` / `charge_successes` : ce test verifie que la derivation lit
    bien ce que les sept sites d'emission ont ecrit, et qu'elle ne croise pas les deux camps.
    """
    engine, tactical = _episode_with_charges(melee_scenario_file)
    controlled = int(engine.config["controlled_player"])
    opponent = 2 if controlled == 1 else 1
    charge_distance = tactical["charge_distance"]

    for label, player in (("agent", controlled), ("opponent", opponent)):
        journal = [lg for lg in _charge_lines(engine) if int(lg["player"]) == player]
        measured = charge_distance[label]
        nearest = [
            lg["charge_nearest_enemy_inches"] for lg in journal
            if lg["charge_nearest_enemy_inches"] is not None
        ]
        target = [
            lg["charge_target_distance_inches"] for lg in journal
            if lg["charge_target_distance_inches"] is not None
        ]
        ok = [
            lg["charge_target_distance_inches"] for lg in journal
            if lg["type"] == "charge" and lg["charge_target_distance_inches"] is not None
        ]
        assert measured["nearest_n"] == len(nearest)
        assert measured["nearest_sum"] == pytest.approx(sum(nearest))
        assert measured["target_n"] == len(target)
        assert measured["target_sum"] == pytest.approx(sum(target))
        assert measured["success_n"] == len(ok)
        assert measured["success_sum"] == pytest.approx(sum(ok))
        assert measured["long"] == sum(1 for d in target if d >= 9)


def test_waiting_in_the_charge_phase_is_not_a_declaration_distance(melee_scenario_file) -> None:
    """VERROU DU DENOMINATEUR : un episode ou l'agent renonce toujours ne mesure aucune DISTANCE
    DE DECLARATION.

    11.02.3 laisse renoncer apres le jet, et un renoncement n'emet aucune ligne de charge : le
    denominateur de la part de declarations a >= 9\" ne bouge donc pas avec le nombre de
    renoncements. C'est ce que ce test protege, et c'est `target_n` qui le porte.

    CE QUI A CHANGE LE 2026-08-12 : il faut distinguer DEUX attentes. Celle ou le jet atteignait
    une cible et ou l'agent a renonce (11.02.3) n'emet toujours rien. Celle ou le jet n'atteint
    AUCUNE cible n'est pas un renoncement — l'escouade a declare et subit une charge ratee
    (`roll_too_short`) : elle emet desormais sa ligne, la ou elle sortait en `wait` invisible.
    Cette ligne porte la distance a l'ennemi le plus proche mais AUCUNE distance de cible
    (`charge_target_distance_inches` reste None, il n'y a pas de cible), donc `target_n` — et avec
    lui la part des >= 9\" — reste intact. C'est exactement la propriete a verrouiller ici.
    """
    engine, tactical = _cached_play(melee_scenario_file, _SEEDS[0], charge_policy="wait")
    mine = [
        lg for lg in _charge_lines(engine)
        if int(lg["player"]) == int(engine.config["controlled_player"])
    ]
    assert not [lg for lg in mine if lg["type"] == "charge"], (
        "montage casse : l'agent a charge alors qu'il attend toujours"
    )
    for lg in mine:
        assert lg["charge_failed_reason"] == "roll_too_short", lg
        assert lg["charge_target_distance_inches"] is None, lg
    measured = tactical["charge_distance"]["agent"]
    assert tactical["charge_attempts"] == len(mine)
    assert tactical["charge_successes"] == 0
    # Le denominateur de la part des >= 9" : aucune distance de CIBLE, quel que soit le nombre
    # d'attentes — c'est le sujet du test et la seule grandeur qu'un renoncement pourrait fausser.
    assert measured["target_n"] == 0
    assert measured["success_n"] == 0
    assert measured["long"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# 3. Courbes
# ─────────────────────────────────────────────────────────────────────────────

class _RecordingWriter:
    def __init__(self) -> None:
        self.scalars: List[Tuple[str, float, int]] = []

    def add_scalar(self, tag: str, value: Any, step: int) -> None:
        self.scalars.append((tag, float(value), int(step)))

    def add_custom_scalars(self, layout: Dict[str, Any], /) -> None:
        pass

    def flush(self) -> None:
        pass

    def close(self) -> None:
        pass


def _recording_tracker(tmp_path: Any) -> Tuple[W40KMetricsTracker, _RecordingWriter]:
    tracker = W40KMetricsTracker(
        "ArmageddonAgent", log_dir=str(tmp_path), show_banner=False,
        perf_window=1, perf_window_fast=1,
    )
    tracker.writer = _RecordingWriter()
    tracker.episode_count = 1
    return tracker, tracker.writer


def _with_charge_distance(tactical: Dict[str, Any], **agent_measures: float) -> Dict[str, Any]:
    """`tactical` dont le bloc `charge_distance['agent']` est remplace par ces mesures.

    Copie, jamais mutation : les episodes de `_cached_play` sont partages entre tests.
    """
    return {
        **tactical,
        "charge_distance": {
            "agent": {
                **{_m: 0.0 for _m in CHARGE_DISTANCE_MEASURES}, **agent_measures,
            },
            "opponent": dict(tactical["charge_distance"]["opponent"]),
        },
    }


def test_the_curves_carry_the_measured_means(melee_scenario_file, tmp_path) -> None:
    """Les courbes publient le rapport somme/effectif, en pouces.

    Construit, pas espere : 4 mesures de proximite pour 12" au total et 3 de cible pour 21",
    soit 3,0" et 7,0" — deux valeurs distinctes, donc un croisement des deux courbes se verrait.
    """
    _engine, tactical = _episode_with_charges(melee_scenario_file)
    tactical = _with_charge_distance(
        tactical,
        nearest_sum=12.0, nearest_n=4.0,
        target_sum=21.0, target_n=3.0,
        success_sum=10.0, success_n=2.0,
    )
    tracker, recording = _recording_tracker(tmp_path)
    tracker.log_tactical_metrics(tactical)

    by_key = {key: value for key, value, _step in recording.scalars}
    assert by_key["05_charge/a_nearest_enemy_inches_agent"] == pytest.approx(3.0)
    assert by_key["05_charge/b_target_inches_agent"] == pytest.approx(7.0)
    assert by_key["05_charge/c_target_inches_success_agent"] == pytest.approx(5.0)


def test_the_ge9_share_is_taken_over_the_targeted_charges(
    melee_scenario_file, tmp_path
) -> None:
    """Le denominateur de la part a >= 9\" est le nombre de charges AVEC cible.

    Une charge declaree qui n'atteint aucune cible (11.02.3) n'a pas de distance : elle ne peut
    jamais entrer au numerateur. La compter au denominateur ferait baisser la part a mesure que
    ces cas se multiplient — la courbe descendrait en decrivant l'inverse de ce qui se passe.

    Construit : 4 charges seulement ont vise une cible, 2 a >= 9\". La bonne reponse est 2/4 ;
    rapportee aux 10 tentatives, elle vaudrait 2/10 — deux valeurs qu'aucun arrondi ne confond.
    """
    _engine, tactical = _episode_with_charges(melee_scenario_file)
    tactical = {
        **_with_charge_distance(tactical, long=2.0, target_n=4.0, target_sum=24.0),
        "charge_attempts": 10,
    }
    tracker, recording = _recording_tracker(tmp_path)
    tracker.log_tactical_metrics(tactical)

    by_key = {key: value for key, value, _step in recording.scalars}
    assert by_key["05_charge/e_declarations_ge9_share_agent"] == pytest.approx(2 / 4)


def test_no_distance_curve_when_nothing_was_charged(melee_scenario_file, tmp_path) -> None:
    """Aucune charge : pas de courbe de distance — et surtout pas une courbe a 0.

    Un 0.0 se lirait « il charge au contact », soit l'inverse exact de « il n'a pas charge ».
    Le volume, lui, reste lisible sur `02_combat/m_charge_attempts`, qui compte les MEMES
    lignes de journal — raison pour laquelle ces courbes-ci n'en publient pas un second.
    """
    _engine, tactical = _episode_with_charges(melee_scenario_file)
    tactical = _with_charge_distance(tactical)
    tracker, recording = _recording_tracker(tmp_path)
    tracker.log_tactical_metrics(tactical)

    emitted = {key for key, _value, _step in recording.scalars}
    assert "05_charge/a_nearest_enemy_inches_agent" not in emitted
    assert "05_charge/b_target_inches_agent" not in emitted
    assert "05_charge/e_declarations_ge9_share_agent" not in emitted
    # Le tag existe bien par ailleurs : l'absence ci-dessus n'est pas celle d'un nom jamais ecrit.
    assert "02_combat/m_charge_attempts" in emitted


# ─────────────────────────────────────────────────────────────────────────────
# 4. Ligne de step.log
# ─────────────────────────────────────────────────────────────────────────────

def test_the_step_log_segment_shows_both_distances() -> None:
    """Le segment porte les deux distances, en pouces, dans l'ordre cible puis plus proche."""
    segment = _charge_distance_segment({
        "charge_target_distance_inches": 5.0,
        "charge_nearest_enemy_inches": 3.0,
    })
    assert segment == ' [Dist: 5.0" | Nearest: 3.0"]'


def test_the_analyzer_still_parses_a_charge_line_carrying_the_distances() -> None:
    """VERROU JUMEAU log/analyzer : le segment ajoute ne casse aucun des parseurs de step.log.

    Le formateur du StepLogger REECRIT integralement la ligne de charge, et trois parseurs la
    relisent (`analyzer_phases/charge_handler`, `hidden_action_finder`, `replay_converter`).
    Ils ancrent tous sur `... CHARGED ... Unit N(c,r) from (c,r) to (c,r)`, donc un segment pose
    APRES `[Roll: N]` les laisse intacts — mais rien d'autre que ce test ne le verifie, et un
    segment glisse plus haut dans la ligne les casserait tous les trois en silence (l'analyzer
    ne signale pas une ligne qu'il ne reconnait pas : elle disparait de ses comptes).
    """
    import re

    from ai.step_logger import StepLogger

    logger = StepLogger(enabled=False)
    line = logger._format_replay_style_message(  # noqa: SLF001 — formateur, pas d'API publique
        "3", "charge",
        {
            "unit_with_coords": "3(12,7)", "target_id": "9",
            "start_pos": (12, 7), "end_pos": (14, 8), "target_coords": (15, 8),
            "charge_roll": 8,
            "charge_target_distance_inches": 5.0,
            "charge_nearest_enemy_inches": 3.0,
        },
    )
    assert 'Dist: 5.0"' in line
    assert re.search(
        r'Unit (\d+)\s*\((\d+),\s*(\d+)\)\s+CHARGED(?:\s+(?:\([^)]+\)|\[[^\]]+\]))*\s+'
        r'Unit (\d+)(?:\s*\((\d+),\s*(\d+)\))?\s+from \((\d+),\s*(\d+)\)\s+to \((\d+),\s*(\d+)\)',
        line,
    ), f"la ligne n'est plus reconnue par le parseur de charge de l'analyzer : {line!r}"


def test_the_step_log_segment_omits_a_missing_distance() -> None:
    """Charge declaree sans cible atteignable : pas de `Dist`, jamais un `Dist: 0.0`.

    Un zero se lirait « il a charge une cible au contact », alors qu'aucune cible n'a ete
    choisie. L'absence est l'information.
    """
    segment = _charge_distance_segment({
        "charge_target_distance_inches": None,
        "charge_nearest_enemy_inches": 7.0,
    })
    assert segment == ' [Nearest: 7.0"]'
    assert _charge_distance_segment({}) == ""
