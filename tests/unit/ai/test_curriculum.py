"""Verrous du curriculum par etapes (ai/curriculum.py + config/agents/*/curriculum.json).

Quatre invariants portent tout le reste, et chacun echoue SILENCIEUSEMENT sans test :

1. La somme des ratios d'une etape vaut 1.0. Un poids mal recopie deplace de l'adversite vers
   les bots sans qu'aucune courbe ne bouge.
2. La repartition par environnement suit les poids. C'est elle qui realise la composition du
   pool ; si elle derive, le pool annonce n'est pas celui qui est joue.
3. Une etape inconnue est refusee nommement. Sinon une faute de frappe lance des heures
   d'entrainement sur une adversite vide.
4. La rampe tient son palier de warmup puis interpole lineairement. Un warmup mal interprete
   ne se voit que des semaines plus tard, dans un win-rate.
"""

import os
import sys
from collections import Counter

import pytest

from shared.data_validation import ConfigurationError

from ai.curriculum import (
    RATIO_SUM_TOLERANCE,
    assign_pool_members_to_envs,
    copy_tensorboard_run,
    evaluate_stage_gate,
    load_curriculum,
    pool_monotonicity_diagnostic,
    promote_stage_model,
    ramped_ratio,
    require_stage,
    stage_champion_label,
    stage_init_source,
    stage_model_path,
    stage_order,
    stage_pool_members,
    validate_curriculum,
)

#: Le curriculum LIVRE, epingle etape par etape : (warmup, ratio_end, champion, poids par membre).
#: Table ecrite depuis la specification, PAS relue du JSON — c'est tout l'interet : elle
#: constate ce que le fichier dit, elle ne le repete pas.
EXPECTED_STAGES = {
    "P00": (0,     0.00, None, {}),
    "P0":  (0,     0.00, None, {}),
    "P1":  (10000, 0.50, "P0", {"P0": 0.50}),
    "P2":  (10000, 0.60, "P1", {"P1": 0.40, "P0": 0.20}),
    "P3":  (10000, 0.70, "P2", {"P2": 0.40, "P0": 0.15, "P1": 0.15}),
    "E1":  (0,     1.00, "P3", {"P3": 1.00}),
    "P4":  (10000, 0.75, "P3", {"P3": 0.30, "P0": 0.20 / 3, "P1": 0.20 / 3, "P2": 0.20 / 3,
                                "E1": 0.25}),
    "P5":  (10000, 0.80, "P4", {"P4": 0.35, "P0": 0.075, "P1": 0.075, "P2": 0.075, "P3": 0.075,
                                "E1": 0.15}),
    "E2":  (0,     1.00, "P5", {"P5": 1.00}),
    "P6":  (10000, 0.80, "P5", {"P5": 0.30, "P0": 0.05, "P1": 0.05, "P2": 0.05, "P3": 0.05,
                                "P4": 0.05, "E1": 0.125, "E2": 0.125}),
    "P7":  (10000, 0.85, "P6", {"P6": 0.30, "P0": 0.35 / 6, "P1": 0.35 / 6, "P2": 0.35 / 6,
                                "P3": 0.35 / 6, "P4": 0.35 / 6, "P5": 0.35 / 6,
                                "E1": 0.10, "E2": 0.10}),
    "P8":  (10000, 0.85, "P7", {"P7": 0.25, "P0": 0.40 / 7, "P1": 0.40 / 7, "P2": 0.40 / 7,
                                "P3": 0.40 / 7, "P4": 0.40 / 7, "P5": 0.40 / 7, "P6": 0.40 / 7,
                                "E1": 0.10, "E2": 0.10}),
    "E3":  (0,     1.00, "P8", {"P8": 1.00}),
    "P9":  (10000, 0.85, "P8", {"P8": 0.25, "P0": 0.35 / 8, "P1": 0.35 / 8, "P2": 0.35 / 8,
                                "P3": 0.35 / 8, "P4": 0.35 / 8, "P5": 0.35 / 8, "P6": 0.35 / 8,
                                "P7": 0.35 / 8, "E1": 0.25 / 3, "E2": 0.25 / 3, "E3": 0.25 / 3}),
    "P10": (10000, 0.85, "P9", {"P9": 0.25, "P0": 0.40 / 9, "P1": 0.40 / 9, "P2": 0.40 / 9,
                                "P3": 0.40 / 9, "P4": 0.40 / 9, "P5": 0.40 / 9, "P6": 0.40 / 9,
                                "P7": 0.40 / 9, "P8": 0.40 / 9,
                                "E1": 0.20 / 3, "E2": 0.20 / 3, "E3": 0.20 / 3}),
}

#: n_envs du profil x1/x5 d'ArmageddonAgent. Le plus gros pool (P10, treize membres) doit y
#: tenir : c'est la contrainte qui borne la taille des pools du curriculum.
ARMAGEDDON_N_ENVS = 48


@pytest.fixture(scope="module")
def curriculum():
    return load_curriculum("ArmageddonAgent_x1")


def _minimal_curriculum() -> dict:
    """Le plus petit curriculum VALIDE : deux etapes, un pool d'un membre."""
    return {
        "order": ["P0", "P1"],
        "opponent": {"snapshot_device": "cpu", "deterministic": False},
        "gate": {
            "min_score_vs_champion": 0.55,
            "target_score_vs_champion": 0.60,
            "eval_episodes": 300,
        },
        "stages": {
            "P0": {
                "role": "learner", "init": "new", "warmup_episodes": 0,
                "ratio_start": 0.0, "ratio_end": 0.0, "pool": [],
            },
            "P1": {
                "role": "learner", "init": "new", "warmup_episodes": 10,
                "ratio_start": 0.0, "ratio_end": 0.4,
                "pool": [{"kind": "champion", "members": ["P0"], "weight": 0.4}],
            },
        },
    }


# ── 1. SOMME DES RATIOS = 1.0 ──────────────────────────────────────────────────────────────

def test_shipped_curriculum_declares_fifteen_stages(curriculum) -> None:
    order = stage_order(curriculum)
    assert order == [
        "P00", "P0", "P1", "P2", "P3", "E1", "P4", "P5", "E2", "P6", "P7", "P8", "E3", "P9", "P10"
    ]
    assert len(order) == 15
    assert sorted(order) == sorted(EXPECTED_STAGES)


@pytest.mark.parametrize("stage_name", sorted(EXPECTED_STAGES))
def test_each_stage_ratios_sum_to_one(curriculum, stage_name: str) -> None:
    """Bots (1 - ratio_end) + pool (somme des poids) = 1.0, sans exception."""
    stage = require_stage(curriculum, stage_name)
    pool_weight = sum(member["weight"] for member in stage_pool_members(stage))
    total = (1.0 - float(stage["ratio_end"])) + pool_weight
    assert abs(total - 1.0) <= RATIO_SUM_TOLERANCE, (
        f"{stage_name}: bots {1.0 - float(stage['ratio_end'])} + pool {pool_weight} = {total}"
    )


@pytest.mark.parametrize("stage_name", sorted(EXPECTED_STAGES))
def test_shipped_stage_matches_the_specification(curriculum, stage_name: str) -> None:
    """Warmup, ratio_end, champion et poids PAR MEMBRE, epingles depuis la specification."""
    expected_warmup, expected_ratio_end, expected_champion, expected_weights = (
        EXPECTED_STAGES[stage_name]
    )
    stage = require_stage(curriculum, stage_name)
    assert int(stage["warmup_episodes"]) == expected_warmup
    assert float(stage["ratio_end"]) == pytest.approx(expected_ratio_end)
    assert stage_champion_label(stage) == expected_champion
    weights = {member["label"]: member["weight"] for member in stage_pool_members(stage)}
    assert weights.keys() == expected_weights.keys()
    for label, expected in expected_weights.items():
        assert weights[label] == pytest.approx(expected), f"{stage_name} / {label}"


def test_learners_all_start_the_ramp_at_zero(curriculum) -> None:
    for name in stage_order(curriculum):
        stage = require_stage(curriculum, name)
        if stage["role"] == "learner":
            assert float(stage["ratio_start"]) == 0.0, name


def test_exploiters_resume_the_champion_they_only_ever_play(curriculum) -> None:
    """Un exploiteur reprend les poids de sa cible ET ne joue que contre elle (ratio 1.0)."""
    exploiters = [
        name for name in stage_order(curriculum)
        if require_stage(curriculum, name)["role"] == "exploiter"
    ]
    assert exploiters == ["E1", "E2", "E3"]
    for name in exploiters:
        stage = require_stage(curriculum, name)
        target = stage_init_source(stage)
        assert target is not None
        assert stage_champion_label(stage) == target
        assert [m["label"] for m in stage_pool_members(stage)] == [target]
        assert float(stage["ratio_start"]) == 1.0
        assert float(stage["ratio_end"]) == 1.0


def test_seed_stage_is_new(curriculum) -> None:
    """P00 est la seule etape learner qui demarre from scratch (pas de warm start)."""
    stage = require_stage(curriculum, "P00")
    assert stage_init_source(stage) is None


def test_learners_form_a_single_chain(curriculum) -> None:
    """Chaque learner reprend le learner qui le PRECEDE dans `order` — une lignee chainee.

    P00 mis a part (`test_seed_stage_is_new`), un learner ne repart jamais de zero ni d'une etape
    quelconque : il reprend son predecesseur immediat, les exploiteurs etant sautes puisqu'ils ne
    sont jamais promus champions. La forme de la lignee ne se voit NULLE PART ailleurs — ni dans
    `EXPECTED_STAGES`, qui epingle warmup, ratio_end, champion et poids mais pas `init`, ni dans
    `validate_curriculum`, qui interdit seulement de nommer une etape posterieure. Une etoile
    (tous depuis P00) et une chaine tournent toutes deux sans erreur : sans ce verrou, passer de
    l'une a l'autre ne se remarque nulle part, alors que le choix change ce que le curriculum
    MESURE — deux champions chaines ne sont pas deux runs independants, cf. la docstring de
    `pool_monotonicity_diagnostic`.

    La chaine est DERIVEE de `order` et non recopiee ici : inserer une etape ne doit pas obliger
    a rediter ce test. Verrou precedent : « tous les learners depuis P00 », design abandonne le
    2026-09-04 au profit du chainage, et qui laissait ce test rouge sur main.
    """
    learners = [
        name for name in stage_order(curriculum)
        if require_stage(curriculum, name)["role"] == "learner"
    ]
    assert learners[0] == "P00", learners
    for previous, name in zip(learners, learners[1:]):
        assert stage_init_source(require_stage(curriculum, name)) == previous, name


def test_a_stage_whose_weights_do_not_reach_ratio_end_is_refused() -> None:
    broken = _minimal_curriculum()
    broken["stages"]["P1"]["pool"][0]["weight"] = 0.3  # ratio_end vaut 0.4
    with pytest.raises(ValueError, match="somme des ratios"):
        validate_curriculum(broken)


def test_a_pool_member_from_a_later_stage_is_refused() -> None:
    broken = _minimal_curriculum()
    broken["stages"]["P0"]["ratio_end"] = 0.4
    broken["stages"]["P0"]["pool"] = [
        {"kind": "champion", "members": ["P1"], "weight": 0.4}
    ]
    with pytest.raises(ValueError, match="ANTERIEURE"):
        validate_curriculum(broken)


def test_an_init_from_a_later_stage_is_refused() -> None:
    broken = _minimal_curriculum()
    broken["stages"]["P0"]["init"] = "from:P1"
    with pytest.raises(ValueError, match="ANTERIEURE"):
        validate_curriculum(broken)


def test_a_pool_without_champion_is_refused() -> None:
    broken = _minimal_curriculum()
    broken["stages"]["P1"]["pool"][0]["kind"] = "ancients"
    with pytest.raises(ValueError, match="sans membre 'champion'"):
        validate_curriculum(broken)


def test_decreasing_ramp_is_refused() -> None:
    broken = _minimal_curriculum()
    broken["stages"]["P1"]["ratio_start"] = 0.6
    broken["stages"]["P1"]["ratio_end"] = 0.1
    # Défense si l'ordre des contrôles change : sans cet ajustement, weight=0.4 (défaut)
    # donnerait bots=0.9+pool=0.4=1.3 et ferait matcher "somme des ratios" avant
    # "decroissante" si le contrôle de somme remontait au-dessus du contrôle de rampe.
    broken["stages"]["P1"]["pool"][0]["weight"] = 0.1
    with pytest.raises(ValueError, match="decroissante"):
        validate_curriculum(broken)


def test_ramp_end_below_warmup_is_refused() -> None:
    broken = _minimal_curriculum()
    broken["stages"]["P1"]["ramp_end_episodes"] = 5  # warmup_episodes=10
    with pytest.raises(ValueError, match="ramp_end_episodes"):
        validate_curriculum(broken)


def test_ramp_end_exceeding_override_total_is_refused() -> None:
    broken = _minimal_curriculum()
    broken["stages"]["P1"]["ramp_end_episodes"] = 200
    broken["stages"]["P1"]["training_config_overrides"] = {"total_episodes": 100}
    with pytest.raises(ValueError, match="ramp_end_episodes"):
        validate_curriculum(broken)


def test_ramp_end_below_override_total_is_accepted() -> None:
    ok = _minimal_curriculum()
    ok["stages"]["P1"]["ramp_end_episodes"] = 50
    ok["stages"]["P1"]["training_config_overrides"] = {"total_episodes": 100}
    validate_curriculum(ok)  # ne leve pas


def test_ramp_end_without_override_total_is_refused() -> None:
    """ramp_end_episodes sans training_config_overrides.total_episodes = validation impossible."""
    broken = _minimal_curriculum()
    broken["stages"]["P1"]["ramp_end_episodes"] = 50
    # Pas de training_config_overrides du tout
    with pytest.raises(ValueError, match="total_episodes"):
        validate_curriculum(broken)


def _minimal_curriculum_with_exploiter() -> dict:
    """Curriculum minimal valide avec une etape exploiteur (E1 joue 100% contre P0)."""
    return {
        "order": ["P0", "E1"],
        "opponent": {"snapshot_device": "cpu", "deterministic": False},
        "gate": {
            "min_score_vs_champion": 0.55,
            "target_score_vs_champion": 0.60,
            "eval_episodes": 300,
        },
        "exploiter_config": {
            "probe_every_episodes": 1000,
            "probe_cheap_n": 100,
            "probe_confirm_n": 500,
            "win_rate_target": 0.70,
        },
        "stages": {
            "P0": {
                "role": "learner", "init": "new", "warmup_episodes": 0,
                "ratio_start": 0.0, "ratio_end": 0.0, "pool": [],
            },
            "E1": {
                "role": "exploiter", "init": "from:P0", "warmup_episodes": 0,
                "ratio_start": 1.0, "ratio_end": 1.0,
                "budget_cap": 50000,
                "pool": [{"kind": "champion", "members": ["P0"], "weight": 1.0}],
            },
        },
    }


def test_exploiter_with_correct_protocol_is_accepted() -> None:
    validate_curriculum(_minimal_curriculum_with_exploiter())  # ne leve pas


def test_exploiter_with_wrong_ratio_start_is_refused() -> None:
    broken = _minimal_curriculum_with_exploiter()
    broken["stages"]["E1"]["ratio_start"] = 0.5
    with pytest.raises(ValueError, match="protocole"):
        validate_curriculum(broken)


def test_exploiter_with_nonzero_warmup_is_refused() -> None:
    broken = _minimal_curriculum_with_exploiter()
    broken["stages"]["E1"]["warmup_episodes"] = 500
    with pytest.raises(ValueError, match="protocole"):
        validate_curriculum(broken)


def test_exploiter_with_non_unit_weight_pool_is_refused() -> None:
    """Un membre unique dont le weight n'est pas 1.0 viole le protocole gele."""
    broken = _minimal_curriculum_with_exploiter()
    broken["stages"]["E1"]["pool"] = [{"kind": "champion", "members": ["P0"], "weight": 0.7}]
    with pytest.raises(ValueError, match="un seul membre de pool"):
        validate_curriculum(broken)


def test_early_stop_with_missing_key_is_refused() -> None:
    broken = _minimal_curriculum()
    broken["early_stop"] = {"win_rate_threshold": 0.60, "min_steps": 1000}  # manque consecutive_evals
    with pytest.raises(ConfigurationError, match="consecutive_evals"):
        validate_curriculum(broken)


def test_early_stop_with_wrong_key_name_is_refused() -> None:
    """Cle erronee (ex. 'win_rate_thresh') doit etre refusee."""
    broken = _minimal_curriculum()
    broken["early_stop"] = {"win_rate_thresh": 0.60, "min_steps": 1000, "consecutive_evals": 2}
    with pytest.raises(ConfigurationError, match="win_rate_threshold"):
        validate_curriculum(broken)


def test_early_stop_with_valid_block_is_accepted() -> None:
    ok = _minimal_curriculum()
    ok["early_stop"] = {"win_rate_threshold": 0.60, "min_steps": 50000, "consecutive_evals": 2}
    validate_curriculum(ok)  # ne leve pas


def test_stage_early_stop_override_with_wrong_key_is_refused() -> None:
    broken = _minimal_curriculum()
    broken["stages"]["P1"]["early_stop"] = {
        "win_rate_thresh": 0.70,  # typo
        "min_steps": 1000,
        "consecutive_evals": 2,
    }
    with pytest.raises(ConfigurationError, match="win_rate_threshold"):
        validate_curriculum(broken)


# ── 2. REPARTITION PAR ENVIRONNEMENT ───────────────────────────────────────────────────────

@pytest.mark.parametrize("stage_name", sorted(EXPECTED_STAGES))
def test_every_pool_member_gets_environments_in_proportion(curriculum, stage_name: str) -> None:
    """Chaque membre recoit sa part des 48 environnements, a un environnement pres.

    C'est ici que la composition du pool se REALISE : la rampe ne connait que la frontiere
    bots/pool, et chaque environnement ne charge qu'un adversaire. Une repartition fausse
    donnerait un pool different de celui que le JSON annonce, sans aucun symptome.
    """
    members = stage_pool_members(require_stage(curriculum, stage_name))
    if not members:
        pytest.skip(f"{stage_name} n'a pas de pool")
    assignment = assign_pool_members_to_envs(members, ARMAGEDDON_N_ENVS)
    assert len(assignment) == ARMAGEDDON_N_ENVS
    counts = Counter(member["label"] for member in assignment)
    total_weight = sum(member["weight"] for member in members)
    for member in members:
        expected = ARMAGEDDON_N_ENVS * member["weight"] / total_weight
        assert counts[member["label"]] >= 1, f"{stage_name} / {member['label']} jamais joue"
        assert abs(counts[member["label"]] - expected) < 1.0, (
            f"{stage_name} / {member['label']}: {counts[member['label']]} env pour {expected:.2f} attendus"
        )


def test_assignment_is_stable_for_a_given_pool_and_env_count() -> None:
    members = [
        {"label": "A", "weight": 0.5},
        {"label": "B", "weight": 0.3},
        {"label": "C", "weight": 0.2},
    ]
    first = [m["label"] for m in assign_pool_members_to_envs(members, 10)]
    second = [m["label"] for m in assign_pool_members_to_envs(members, 10)]
    assert first == second
    assert Counter(first) == {"A": 5, "B": 3, "C": 2}


def test_fewer_environments_than_pool_members_is_refused() -> None:
    """Un membre sans environnement serait absent du run sans que rien ne le dise."""
    members = [{"label": label, "weight": 0.25} for label in "ABCD"]
    with pytest.raises(ValueError, match="membres de pool"):
        assign_pool_members_to_envs(members, 3)


def test_a_weight_too_small_for_the_env_count_is_refused() -> None:
    members = [
        {"label": "A", "weight": 0.999},
        {"label": "B", "weight": 0.001},
    ]
    with pytest.raises(ValueError, match="sans aucun environnement"):
        assign_pool_members_to_envs(members, 4)


# ── 3. ETAPE INCONNUE ──────────────────────────────────────────────────────────────────────

def test_unknown_stage_is_refused_and_lists_the_known_ones(curriculum) -> None:
    with pytest.raises(ValueError) as excinfo:
        require_stage(curriculum, "P11")
    message = str(excinfo.value)
    assert "P11" in message
    # Le refus doit permettre de corriger la commande sans ouvrir le JSON.
    for name in ("P0", "E1", "P10"):
        assert name in message


# ── 4. RAMPE ───────────────────────────────────────────────────────────────────────────────

def test_ramp_holds_ratio_start_through_the_whole_warmup() -> None:
    for episode in range(0, 21):
        assert ramped_ratio(episode, 20, 100, 0.0, 0.8) == 0.0


def test_ramp_interpolates_linearly_after_the_warmup() -> None:
    # Warmup 20 sur 100 : 80 episodes de rampe, donc +0.01 de part par episode pour aller a 0.8.
    assert ramped_ratio(40, 20, 100, 0.0, 0.8) == pytest.approx(0.2)
    assert ramped_ratio(60, 20, 100, 0.0, 0.8) == pytest.approx(0.4)
    assert ramped_ratio(80, 20, 100, 0.0, 0.8) == pytest.approx(0.6)
    assert ramped_ratio(100, 20, 100, 0.0, 0.8) == pytest.approx(0.8)


def test_ramp_is_clamped_past_the_budget() -> None:
    assert ramped_ratio(500, 20, 100, 0.0, 0.8) == pytest.approx(0.8)


def test_ramp_with_no_room_left_is_flat_at_ratio_end() -> None:
    """Warmup egal au budget : il ne reste aucun episode a interpoler."""
    assert ramped_ratio(101, 100, 100, 0.0, 0.8) == pytest.approx(0.8)


def test_ramp_end_episodes_plateaus_before_total() -> None:
    """ramp_end_episodes atteint ratio_end avant total_episodes : la rampe est plus rapide."""
    # Sans ramp_end : a episode 60 sur total=100, warmup=20 → progress 50% → ratio=0.4
    assert ramped_ratio(60, 20, 100, 0.0, 0.8) == pytest.approx(0.4)
    # Avec ramp_end=60 : la rampe se termine a 60, donc ratio_end est deja atteint
    assert ramped_ratio(60, 20, 100, 0.0, 0.8, ramp_end_episodes=60) == pytest.approx(0.8)
    # Bien au-dela de ramp_end : ratio reste plat a ratio_end
    assert ramped_ratio(100, 20, 100, 0.0, 0.8, ramp_end_episodes=60) == pytest.approx(0.8)


def test_ramp_end_episodes_interpolates_up_to_ramp_end() -> None:
    """Avant ramp_end, la rampe interpole normalement (comme si total=ramp_end)."""
    # warmup=20, ramp_end=60 → 40 episodes de rampe pour 0.8 → +0.02/ep
    assert ramped_ratio(40, 20, 100, 0.0, 0.8, ramp_end_episodes=60) == pytest.approx(0.4)


def test_ramp_end_none_is_identical_to_original_behavior() -> None:
    """ramp_end_episodes=None est strictement equivalent a l'absence du parametre."""
    for episode in (0, 20, 40, 60, 80, 100, 500):
        assert ramped_ratio(episode, 20, 100, 0.0, 0.8, ramp_end_episodes=None) == pytest.approx(
            ramped_ratio(episode, 20, 100, 0.0, 0.8)
        ), f"episode {episode}"


def test_env_wrapper_ramp_end_episodes_is_passed_to_curriculum_ramp() -> None:
    """BotControlledEnv convertit ramp_end_episodes en budget par env et le passe a ramped_ratio."""
    from tests.unit.ai.test_env_wrappers import _DummyBot, _DummyEngine
    from ai.env_wrappers import BotControlledEnv

    wrapper = BotControlledEnv(
        _DummyEngine(),
        bot=_DummyBot(),
        self_play_opponent_enabled=True,
        self_play_ratio_start=0.0,
        self_play_ratio_end=0.8,
        self_play_total_episodes=100,
        self_play_warmup_episodes=20,
        self_play_ramp_end_episodes=60,
        self_play_n_envs=1,
        self_play_snapshot_path="snapshot.zip",
        self_play_snapshot_frozen=True,
        self_play_snapshot_device="cpu",
        self_play_snapshot_label="test-snapshot",
    )
    for episode in (0, 20, 40, 60, 100):
        wrapper._episode_index = episode
        assert wrapper._compute_pool_ratio_for_episode() == pytest.approx(
            ramped_ratio(episode, 20, 100, 0.0, 0.8, ramp_end_episodes=60)
        ), f"episode {episode}"


def test_env_wrapper_ramp_is_the_curriculum_ramp() -> None:
    """`BotControlledEnv` ne recalcule pas la rampe : un warmup interprete des deux facons ne
    se verrait dans aucune courbe."""
    from tests.unit.ai.test_env_wrappers import _DummyBot, _DummyEngine
    from ai.env_wrappers import BotControlledEnv

    wrapper = BotControlledEnv(
        _DummyEngine(),
        bot=_DummyBot(),
        self_play_opponent_enabled=True,
        self_play_ratio_start=0.0,
        self_play_ratio_end=0.8,
        self_play_total_episodes=100,
        self_play_warmup_episodes=20,
        self_play_n_envs=1,
        self_play_snapshot_path="snapshot.zip",
        self_play_snapshot_frozen=True,
        self_play_snapshot_device="cpu",
        self_play_snapshot_label="test-snapshot",
    )
    for episode in (0, 20, 21, 60, 100, 500):
        wrapper._episode_index = episode
        assert wrapper._compute_pool_ratio_for_episode() == pytest.approx(
            ramped_ratio(episode, 20, 100, 0.0, 0.8)
        ), f"episode {episode}"


# ── GATE ───────────────────────────────────────────────────────────────────────────────────

def test_gate_refuses_below_the_hard_floor() -> None:
    accepted, reason = evaluate_stage_gate("P4", "P3", {"P3": 0.54}, 0.55, 0.60)
    assert accepted is False
    assert "REFUSEE" in reason


def test_gate_accepts_between_floor_and_target_and_says_so() -> None:
    accepted, reason = evaluate_stage_gate("P4", "P3", {"P3": 0.57}, 0.55, 0.60)
    assert accepted is True
    assert "sous la cible" in reason


def test_gate_accepts_at_the_target() -> None:
    accepted, reason = evaluate_stage_gate("P4", "P3", {"P3": 0.62}, 0.55, 0.60)
    assert accepted is True
    assert "au-dessus de la cible" in reason


def test_gate_does_not_apply_to_the_first_stage() -> None:
    accepted, reason = evaluate_stage_gate("P0", None, {}, 0.55, 0.60)
    assert accepted is True
    assert "sans objet" in reason


def test_gate_refuses_to_pass_when_the_champion_was_never_measured() -> None:
    """Un champion non mesure ne peut pas etre 'accepte par defaut' : le gate leve."""
    with pytest.raises(KeyError, match="P3"):
        evaluate_stage_gate("P4", "P3", {"P0": 0.9}, 0.55, 0.60)


def test_only_the_most_recent_champion_gates(curriculum) -> None:
    """Un score ecrase contre un ANCIEN n'empeche pas l'etape : seul le champion compte."""
    stage = require_stage(curriculum, "P4")
    assert stage_champion_label(stage) == "P3"
    accepted, _ = evaluate_stage_gate(
        "P4", "P3", {"P3": 0.70, "P0": 0.10, "P1": 0.10, "P2": 0.10, "E1": 0.10}, 0.55, 0.60
    )
    assert accepted is True


# ── MONOTONIE : DIAGNOSTIC, PAS GATE ───────────────────────────────────────────────────────

def test_monotonicity_reports_inversions_without_refusing_anything() -> None:
    lines = pool_monotonicity_diagnostic(
        {"P0": 0.90, "P1": 0.95, "P2": 0.60}, ["P0", "P1", "P2"]
    )
    text = "\n".join(lines)
    assert "1 inversion(s)" in text
    assert "P0=0.900 < P1=0.950" in text
    # Le diagnostic ne rend qu'un texte : rien dans cette fonction ne peut refuser une etape.
    assert all(isinstance(line, str) for line in lines)


def test_monotonicity_reports_a_clean_pool() -> None:
    lines = pool_monotonicity_diagnostic({"P0": 0.95, "P1": 0.80, "P2": 0.60}, ["P0", "P1", "P2"])
    assert "aucune inversion." in lines[-1]


# ── PROMOTION PAR COPIE ────────────────────────────────────────────────────────────────────

def test_promotion_copies_the_model_and_its_companions(tmp_path) -> None:
    """COPIE : le modele canonique doit rester en place, et ses compagnons suivre.

    Un zip promu sans son `_vec_normalize.pkl` est injouable comme adversaire fige (V11 §0.35).
    """
    from ai.model_artifacts import model_companion_paths

    canonical = tmp_path / "model_TestAgent.zip"
    canonical.write_bytes(b"poids")
    for companion in model_companion_paths(str(canonical)):
        with open(companion, "wb") as handle:
            handle.write(b"compagnon")

    written = promote_stage_model(str(canonical), "P4")
    target = stage_model_path(str(canonical), "P4")

    assert canonical.exists(), "le modele canonique doit rester en place (copie, pas renommage)"
    assert target.endswith("model_TestAgent_P4.zip")
    assert set(written) == {target, *model_companion_paths(target)}
    for path in written:
        assert open(path, "rb").read() in (b"poids", b"compagnon")


def test_promotion_without_a_model_is_refused(tmp_path) -> None:
    with pytest.raises(FileNotFoundError, match="modele canonique est absent"):
        promote_stage_model(str(tmp_path / "model_TestAgent.zip"), "P4")


def test_stage_model_path_suffixes_the_canonical_path() -> None:
    assert stage_model_path("/m/ArmageddonAgent/model_ArmageddonAgent.zip", "E1") == (
        "/m/ArmageddonAgent/model_ArmageddonAgent_E1.zip"
    )


# ── JOURNAL ────────────────────────────────────────────────────────────────────────────────

def test_curriculum_log_appends_instead_of_overwriting(tmp_path) -> None:
    """Quatorze runs etales sur des jours : un mode 'w' perdrait l'historique."""
    import json

    from ai.curriculum import append_curriculum_log

    log_path = tmp_path / "curriculum.log"
    append_curriculum_log({"etape": "P0"}, str(log_path))
    append_curriculum_log({"etape": "P1"}, str(log_path))
    entries = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert [entry["etape"] for entry in entries] == ["P0", "P1"]


# ── written_by : quel PROGRAMME a ecrit la ligne ───────────────────────────────────────────
#
# Defaut d'origine (2026-08-26) : `scripts/replay_p1_cloture.py`, script one-shot jamais commite,
# a journalise un refus de l'etape P1 mesure sur 30 episodes au lieu des 300 de `curriculum.json`.
# Relue plus tard, la ligne etait indistinguable d'une mesure du pipeline.

def test_written_by_names_the_entry_point(tmp_path, monkeypatch) -> None:
    """Chaque entree porte le point d'entree du processus, relatif a la racine du depot."""
    import json

    from ai.curriculum import append_curriculum_log, _project_root

    faux_script = os.path.join(_project_root(), "scripts", "un_script_jetable.py")
    monkeypatch.setattr(sys, "argv", [faux_script])

    log_path = tmp_path / "curriculum.log"
    append_curriculum_log({"etape": "P1"}, str(log_path))

    entry = json.loads(log_path.read_text(encoding="utf-8").strip())
    assert entry["written_by"] == os.path.join("scripts", "un_script_jetable.py")
    assert entry["etape"] == "P1"  # l'estampille n'ecrase pas le contenu


def test_written_by_keeps_an_out_of_tree_entry_point_absolute(tmp_path, monkeypatch) -> None:
    """Un point d'entree hors depot reste absolu : il n'y a rien a raccourcir."""
    import json

    from ai.curriculum import append_curriculum_log

    monkeypatch.setattr(sys, "argv", ["/usr/lib/python3/dist-packages/pytest"])

    log_path = tmp_path / "curriculum.log"
    append_curriculum_log({"etape": "P0"}, str(log_path))

    entry = json.loads(log_path.read_text(encoding="utf-8").strip())
    assert entry["written_by"] == "/usr/lib/python3/dist-packages/pytest"


def test_written_by_supplied_by_caller_raises(tmp_path) -> None:
    """Declarer soi-meme la cle LEVE : une entree ne peut pas se dire ecrite par un autre.

    Sans cette garde, le champ serait declaratif — le script jetable qui a cause le defaut
    d'origine aurait pu s'annoncer `ai/train.py` et le journal l'aurait cru.
    """
    from ai.curriculum import append_curriculum_log

    log_path = tmp_path / "curriculum.log"
    with pytest.raises(ValueError, match="estampille par le journal"):
        append_curriculum_log({"etape": "P1", "written_by": "ai/train.py"}, str(log_path))

    assert not log_path.exists()  # rien n'a ete ecrit avant de lever


# ── COPIE TENSORBOARD ──────────────────────────────────────────────────────────────────────

def test_copy_tensorboard_run_copies_source_to_named_target(tmp_path) -> None:
    run_dir = tmp_path / "run_0"
    run_dir.mkdir()
    (run_dir / "events.out").write_bytes(b"tb")
    target = copy_tensorboard_run(str(run_dir), "P4")
    assert os.path.isdir(target)
    assert (tmp_path / "tensorboard_P4" / "events.out").read_bytes() == b"tb"
    assert run_dir.exists(), "le run source ne doit pas etre supprime"


def test_copy_tensorboard_run_replaces_existing_target(tmp_path) -> None:
    run_dir = tmp_path / "run_0"
    run_dir.mkdir()
    (run_dir / "events.out").write_bytes(b"new")
    target_dir = tmp_path / "tensorboard_P4"
    target_dir.mkdir()
    (target_dir / "stale.out").write_bytes(b"old")
    copy_tensorboard_run(str(run_dir), "P4")
    assert not (target_dir / "stale.out").exists()
    assert (target_dir / "events.out").read_bytes() == b"new"


def test_copy_tensorboard_run_preserves_source_on_copy_failure(tmp_path, monkeypatch) -> None:
    """Si copytree echoue, le target precedent doit rester intact."""
    run_dir = tmp_path / "run_0"
    run_dir.mkdir()
    (run_dir / "events.out").write_bytes(b"new")
    target_dir = tmp_path / "tensorboard_P4"
    target_dir.mkdir()
    (target_dir / "events.out").write_bytes(b"preserved")

    def failing_copytree(src: str, dst: str, **kwargs: object) -> None:
        raise OSError("disk full (simulated)")

    import ai.curriculum as _curriculum_mod
    monkeypatch.setattr(_curriculum_mod.shutil, "copytree", failing_copytree)

    with pytest.raises(OSError, match="disk full"):
        copy_tensorboard_run(str(run_dir), "P4")

    assert target_dir.exists(), "le target existant doit survivre a l'echec de copytree"
    assert (target_dir / "events.out").read_bytes() == b"preserved"


def test_copy_tensorboard_run_raises_when_source_is_missing(tmp_path) -> None:
    with pytest.raises(FileNotFoundError, match="absent"):
        copy_tensorboard_run(str(tmp_path / "nonexistent"), "P4")
