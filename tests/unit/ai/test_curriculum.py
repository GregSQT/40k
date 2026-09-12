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
    _validate_early_stop_against_gate,
    validate_early_stop_block,
    assign_pool_members_to_envs,
    copy_tensorboard_run,
    POOL_VERDICT_CONTINUE,
    POOL_VERDICT_DESTROY,
    POOL_VERDICT_PROMOTE,
    evaluate_pool_decision,
    evaluate_stage_gate,
    exploiter_stage_names,
    load_curriculum,
    required_training_config,
    load_parity_check,
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
#:
#: `1 - ratio_end` est la PART DE BOTS : 30 % en P1, 20 % en P2, 15 % de P3 a P10 (2026-09-06,
#: cf. `_doc_part_bots` du JSON). Elle suit la TAILLE du pool et non la force de l'agent — a
#: 15 %, P1 jouerait 85 % de ses parties contre son unique membre de pool, soit le regime d'un
#: exploiteur alors qu'il est promu champion.
#:
#: `warmup` vaut 0 PARTOUT : plus aucune etape ne rampe son adversite. La table portait encore
#: 10000 sur neuf etapes et etait ROUGE sur chacune — la suppression des rampes de P2 a P10 ne
#: l'avait pas mise a jour, celle de P1 l'acheve.
#:
#: P2 REPONDERE le 2026-09-06 (commit 4a4180b4) : champion P1 0.55 -> 0.50, ancien P0 0.25 -> 0.30,
#: a part de bots constante (ratio_end 0.80). Le pool de P2 n'a que deux membres et P1 est le
#: predecesseur DIRECT du learner (init from:P1), donc les parties contre P1 opposent deux
#: politiques quasi identiques : c'est P0, plus lointain dans la lignee chainee, qui porte seul
#: la diversite de style a cette etape. Deplacer 5 points vers lui achete cette diversite sans
#: toucher aux bots. La table etait restee sur les anciens poids et rendait
#: test_shipped_stage_matches_the_specification[P2] ROUGE.
EXPECTED_STAGES = {
    "P0":  (0, 0.00, None, {}),
    "P1":  (0, 0.70, "P0", {"P0": 0.70}),
    "P2":  (0, 0.80, "P1", {"P1": 0.50, "P0": 0.30}),
    "P3":  (0, 0.85, "P2", {"P2": 0.50, "P0": 0.175, "P1": 0.175}),
    "E1":  (0, 1.00, "P3", {"P3": 1.00}),
    "P4":  (0, 0.85, "P3", {"P3": 0.35, "P0": 0.25 / 3, "P1": 0.25 / 3, "P2": 0.25 / 3,
                            "E1": 0.25}),
    "P5":  (0, 0.85, "P4", {"P4": 0.40, "P0": 0.075, "P1": 0.075, "P2": 0.075, "P3": 0.075,
                            "E1": 0.15}),
    "E2":  (0, 1.00, "P5", {"P5": 1.00}),
    "P6":  (0, 0.85, "P5", {"P5": 0.35, "P0": 0.05, "P1": 0.05, "P2": 0.05, "P3": 0.05,
                            "P4": 0.05, "E1": 0.125, "E2": 0.125}),
    "P7":  (0, 0.85, "P6", {"P6": 0.30, "P0": 0.35 / 6, "P1": 0.35 / 6, "P2": 0.35 / 6,
                            "P3": 0.35 / 6, "P4": 0.35 / 6, "P5": 0.35 / 6,
                            "E1": 0.10, "E2": 0.10}),
    "P8":  (0, 0.85, "P7", {"P7": 0.25, "P0": 0.40 / 7, "P1": 0.40 / 7, "P2": 0.40 / 7,
                            "P3": 0.40 / 7, "P4": 0.40 / 7, "P5": 0.40 / 7, "P6": 0.40 / 7,
                            "E1": 0.10, "E2": 0.10}),
    "E3":  (0, 1.00, "P8", {"P8": 1.00}),
    "P9":  (0, 0.85, "P8", {"P8": 0.25, "P0": 0.35 / 8, "P1": 0.35 / 8, "P2": 0.35 / 8,
                            "P3": 0.35 / 8, "P4": 0.35 / 8, "P5": 0.35 / 8, "P6": 0.35 / 8,
                            "P7": 0.35 / 8, "E1": 0.25 / 3, "E2": 0.25 / 3, "E3": 0.25 / 3}),
    "P10": (0, 0.85, "P9", {"P9": 0.25, "P0": 0.40 / 9, "P1": 0.40 / 9, "P2": 0.40 / 9,
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
            "min_score_vs_others": 0.50,
            "eval_episodes": 300,
            "eval_repeats": 3,
        },
        "parity_check": {"min_score": 0.40, "max_score": 0.60},
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

def test_shipped_curriculum_declares_fourteen_stages(curriculum) -> None:
    """P00 SUPPRIMEE le 2026-09-07 : la graine n'existait que pour eviter de repayer un warmup a
    chaque learner, ce que le chainage de la lignee a rendu sans objet — un seul depart a froid
    suffit, et c'est P0."""
    order = stage_order(curriculum)
    assert order == [
        "P0", "P1", "P2", "P3", "E1", "P4", "P5", "E2", "P6", "P7", "P8", "E3", "P9", "P10"
    ]
    assert len(order) == 14
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


def test_the_curriculum_names_one_profile_per_nature_of_stage(curriculum) -> None:
    """Le curriculum ne porte que des NOMS de profils ; les VALEURS vivent dans les profils.

    C'est le partage de responsabilite decide le 2026-09-07 : le curriculum est le seul a savoir
    quelle etape reprend des poids, le fichier de profils est le seul a savoir ce que vaut un
    hyperparametre. Un premier jet avait mis les valeurs ici, sous le nom `lineage_regime` ; il
    les dispersait alors sur deux fichiers, avec une regle de precedence a connaitre pour
    repondre a « quel learning_rate utilise P5 ».
    """
    block = curriculum["training_configs"]
    assert block["cold_start"] == "x1_long"
    assert block["lineage"] == "x1_lineage"
    for role in ("cold_start", "lineage"):
        assert isinstance(block[role], str) and block[role]


def test_every_stage_that_resumes_weights_requires_the_lineage_profile(curriculum) -> None:
    """Le critere est l'init, et lui seul : `new` prend le froid, tout le reste prend la lignee.

    VERT VACANT evite : les deux natures sont representees et comparees a des noms DIFFERENTS,
    donc un `required_training_config` qui rendrait une constante echouerait.
    """
    par_nature = {
        name: required_training_config(curriculum, require_stage(curriculum, name))
        for name in stage_order(curriculum)
    }
    froid = {n for n, p in par_nature.items() if p == "x1_long"}
    lignee = {n for n, p in par_nature.items() if p == "x1_lineage"}
    assert froid == {"P0"}, froid
    assert lignee == set(stage_order(curriculum)) - {"P0"}
    assert len(lignee) == 13, sorted(lignee)


def test_no_warm_started_stage_declares_hyperparameters_of_its_own(curriculum) -> None:
    """Une etape reprise a chaud ne declare que sa DUREE : le regime de lignee porte le reste.

    Verrou de la decision du 2026-09-07. Une seule etape qui reposerait un `model_params` ou un
    `agent_seat_p2_ratio` ferait coexister deux sources pour la meme valeur, et ce serait la
    perdante — les overrides d'etape sont appliques AVANT le regime — qui aurait l'air de decider
    en relisant le JSON. C'est ce que faisaient `vf_coef` et `max_grad_norm` sur P2 et P3.
    """
    for name in stage_order(curriculum):
        stage = require_stage(curriculum, name)
        if stage_init_source(stage) is None:
            continue  # depart a froid : les rampes du profil lui reviennent legitimement
        overrides = stage.get("training_config_overrides", {})
        assert set(overrides) <= {"total_episodes"}, (
            f"{name} declare {sorted(set(overrides) - {'total_episodes'})} alors qu'elle reprend "
            f"des poids ({stage['init']}) : ces cles appartiennent au bloc de lignee."
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


def test_learners_have_no_adversity_ramp(curriculum) -> None:
    """Aucune etape ne rampe son adversite : `ratio_start == ratio_end`, sans exception.

    REMPLACE `test_learners_all_start_the_ramp_at_zero`, qui exigeait `ratio_start == 0.0` et
    etait rouge sur neuf etapes : les rampes de P2 a P10 avaient ete supprimees sans que le
    verrou suive, et celle de P1 l'a ete le 2026-09-06. Un learner reprend les poids du champion
    qui le precede et ce champion est dans son pool : il fait jeu egal par construction des
    l'episode 0, donc la rampe ne faisait que substituer des parties de bots — gagnees a ~92 % —
    aux parties de pool, sans signal correctif.

    La cle `ramp_end_episodes` disparait avec les rampes : la laisser derriere ferait croire a
    une interpolation que plus personne ne joue.
    """
    for name in stage_order(curriculum):
        stage = require_stage(curriculum, name)
        assert float(stage["ratio_start"]) == pytest.approx(float(stage["ratio_end"])), name
        assert int(stage["warmup_episodes"]) == 0, name
        assert "ramp_end_episodes" not in stage, name


def test_exploiters_play_their_target_but_start_from_the_seed(curriculum) -> None:
    """Un exploiteur ne joue QUE sa cible (ratio 1.0) mais part de P0, pas de cette cible.

    Decision du 2026-09-07. Partir de la cible faisait de l'exploiteur une COPIE du champion a
    laquelle on demandait de trouver sa propre faiblesse : il commencait a la parite par
    construction et ne pouvait s'en ecarter qu'en desapprenant. Partir du depart a froid en fait
    une politique reellement differente, entrainee contre la cible — ce que le pool des etapes
    suivantes doit contenir. `validate_exploiter_protocol` ne contraint pas `init` : ce verrou
    est le seul endroit ou le choix est ecrit.
    """
    exploiters = exploiter_stage_names(curriculum)
    # Liste LITTÉRALE, et volontairement : les verrous de protocole exploiteur dérivent la leur
    # pour couvrir d'office une étape ajoutée plus tard, mais celui-ci fige la FORME décidée le
    # 2026-09-07. La dériver ici laisserait une lignée que personne n'a décidée passer en silence.
    assert exploiters == ["E1", "E2", "E3"]
    for name in exploiters:
        stage = require_stage(curriculum, name)
        target = stage_champion_label(stage)
        assert target is not None
        assert target != stage_init_source(stage)
        assert stage_init_source(stage) == "P0"
        assert [m["label"] for m in stage_pool_members(stage)] == [target]
        assert float(stage["ratio_start"]) == 1.0
        assert float(stage["ratio_end"]) == 1.0


def test_seed_stage_is_new(curriculum) -> None:
    """P0 est la seule etape du curriculum qui demarre from scratch (pas de warm start)."""
    from_scratch = [
        name for name in stage_order(curriculum)
        if stage_init_source(require_stage(curriculum, name)) is None
    ]
    assert from_scratch == ["P0"]


def test_learners_form_a_single_chain(curriculum) -> None:
    """Chaque learner reprend le learner qui le PRECEDE dans `order` — une lignee chainee.

    P0 mis a part (`test_seed_stage_is_new`), un learner ne repart jamais de zero ni d'une etape
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
    assert learners[0] == "P0", learners
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
            "min_score_vs_others": 0.50,
            "eval_episodes": 300,
            "eval_repeats": 3,
        },
        "parity_check": {"min_score": 0.40, "max_score": 0.60},
        "training_configs": {"cold_start": "x1_long", "lineage": "x1_lineage"},
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


def _early_stop_block(**overrides) -> dict:
    """Bloc `early_stop` valide, aux valeurs du curriculum livre."""
    block = {
        "probe_window": 3,
        "promote_score_vs_champion": 0.55,
        "promote_score_vs_others": 0.50,
        "promote_min_episodes": 50000,
        "destroy_score_vs_champion": 0.40,
        "destroy_min_episodes": 20000,
        "full_pool_probe_every": 3,
    }
    block.update(overrides)
    return block


def test_early_stop_with_missing_key_is_refused() -> None:
    broken = _minimal_curriculum()
    broken["early_stop"] = _early_stop_block()
    del broken["early_stop"]["destroy_min_episodes"]
    with pytest.raises(ConfigurationError, match="destroy_min_episodes"):
        validate_curriculum(broken)


def test_early_stop_with_wrong_key_name_is_refused() -> None:
    """Cle erronee (ex. l'ancien 'win_rate_threshold') doit etre refusee."""
    broken = _minimal_curriculum()
    broken["early_stop"] = _early_stop_block()
    broken["early_stop"]["win_rate_threshold"] = broken["early_stop"].pop(
        "promote_score_vs_champion"
    )
    with pytest.raises(ConfigurationError, match="promote_score_vs_champion"):
        validate_curriculum(broken)


def test_early_stop_with_valid_block_is_accepted() -> None:
    ok = _minimal_curriculum()
    ok["early_stop"] = _early_stop_block()
    validate_curriculum(ok)  # ne leve pas


# ── LE SEUIL D'ARRET ANTICIPE NE PEUT PAS ETRE SOUS LE PLANCHER DU GATE ────────────────────


@pytest.mark.parametrize(
    "promote_key, gate_key, promote_value",
    [
        ("promote_score_vs_champion", "min_score_vs_champion", 0.50),
        ("promote_score_vs_others", "min_score_vs_others", 0.45),
    ],
)
def test_a_promotion_threshold_below_the_gate_floor_is_refused(
    promote_key: str, gate_key: str, promote_value: float
) -> None:
    """Chaque bloc etait valide SEUL : leurs seuils ne se rencontraient jamais.

    Avec `promote_score_vs_champion` a 0.50 sous un `gate.min_score_vs_champion` de 0.55, une
    etape atteignant 0.51 s'arrete en annoncant que « le budget restant serait paye pour rien »,
    puis le gate la refuse a 0.55 : le budget non depense est perdu AVEC l'etape. C'est exactement
    ce que la docstring de `_pool_score_shortfalls` affirme impossible en mutualisant le CALCUL —
    mais mutualiser le calcul ne croisait pas les VALEURS.
    """
    broken = _minimal_curriculum()
    broken["early_stop"] = _early_stop_block(**{promote_key: promote_value})

    with pytest.raises(ValueError, match=f"{promote_key}.*SOUS gate.{gate_key}"):
        validate_curriculum(broken)


def test_a_promotion_threshold_equal_to_the_gate_floor_is_accepted() -> None:
    """L'egalite est le reglage LIVRE (0.55/0.55, 0.50/0.50) : la refuser casserait la prod.

    Les deux decisions comparent avec `>=`, donc une moyenne qui promeut atteint le plancher. Elle
    ne le franchit pas avec marge et les deux mesures sont des echantillons distincts — le gate
    peut donc encore refuser par variance, mais c'est une decision de conception a prendre, pas
    un invariant a supposer dans un validateur.
    """
    ok = _minimal_curriculum()
    ok["early_stop"] = _early_stop_block(
        promote_score_vs_champion=ok["gate"]["min_score_vs_champion"],
        promote_score_vs_others=ok["gate"]["min_score_vs_others"],
    )
    validate_curriculum(ok)  # ne leve pas


def test_a_per_stage_early_stop_is_crossed_with_the_gate_too() -> None:
    """Le gate est UNIQUE (racine) : un `early_stop` pose sur une etape le rencontrera aussi.

    Ne croiser que le bloc racine laisserait l'incoherence rentrer par la porte des etapes.
    """
    broken = _minimal_curriculum()
    broken["stages"]["P1"]["early_stop"] = _early_stop_block(
        promote_score_vs_champion=0.50
    )
    with pytest.raises(ValueError, match=r"stages\[P1\].early_stop.promote_score_vs_champion"):
        validate_curriculum(broken)


def test_the_shipped_curriculum_holds_the_promote_over_gate_invariant(curriculum) -> None:
    """Verrou sur le fichier LIVRE, pas seulement sur des fixtures."""
    gate = curriculum["gate"]
    early = curriculum["early_stop"]
    assert early["promote_score_vs_champion"] >= gate["min_score_vs_champion"]
    assert early["promote_score_vs_others"] >= gate["min_score_vs_others"]


def test_early_stop_window_of_one_is_refused() -> None:
    """Une fenetre d'un seul point n'est pas une moyenne, c'est la sonde brute."""
    broken = _minimal_curriculum()
    broken["early_stop"] = _early_stop_block(probe_window=1)
    with pytest.raises(ValueError, match="probe_window"):
        validate_curriculum(broken)


def test_early_stop_destroy_threshold_above_promote_is_refused() -> None:
    """Seuils croises : une meme moyenne declencherait promotion ET destruction."""
    broken = _minimal_curriculum()
    broken["early_stop"] = _early_stop_block(destroy_score_vs_champion=0.60)
    with pytest.raises(ValueError, match="destroy_score_vs_champion"):
        validate_curriculum(broken)


def test_stage_early_stop_override_with_wrong_key_is_refused() -> None:
    broken = _minimal_curriculum()
    broken["stages"]["P1"]["early_stop"] = _early_stop_block()
    del broken["stages"]["P1"]["early_stop"]["probe_window"]
    with pytest.raises(ConfigurationError, match="probe_window"):
        validate_curriculum(broken)


# ── SURCHARGE PROFIL D'ENTRAINEMENT : VALIDATION APRES MERGE ──────────────────────────────


def test_merged_early_stop_inverted_destroy_promote_is_refused() -> None:
    """Un override training_config peut inverser destroy > promote apres merge.

    `validate_curriculum` valide le bloc curriculum AVANT la surcharge ; validate_early_stop_block
    doit etre appelé APRES le merge pour attraper que destroy_score >= promote_score.
    """
    merged = _early_stop_block(promote_score_vs_champion=0.38, destroy_score_vs_champion=0.40)
    with pytest.raises(ValueError, match="destroy_score_vs_champion"):
        validate_early_stop_block(merged, "test surcharge inversee")


@pytest.mark.parametrize(
    "promote_key, promote_value, gate_key",
    [
        ("promote_score_vs_champion", 0.50, "min_score_vs_champion"),
        ("promote_score_vs_others", 0.45, "min_score_vs_others"),
    ],
)
def test_merged_early_stop_below_gate_is_refused(
    promote_key: str, promote_value: float, gate_key: str
) -> None:
    """Un override training_config peut faire descendre promote sous le plancher du gate.

    `validate_curriculum` valide AVANT la surcharge ; `_validate_early_stop_against_gate`
    doit etre appelé APRES le merge pour attraper cette violation.
    """
    merged = _early_stop_block(**{promote_key: promote_value})
    gate = _minimal_curriculum()["gate"]
    with pytest.raises(ValueError, match=f"{promote_key}.*SOUS gate.{gate_key}"):
        _validate_early_stop_against_gate(merged, gate, "profil 'x1_lineage' surcharge / etape P1")


def test_merged_early_stop_equal_to_gate_floor_is_accepted() -> None:
    """Egalite tolérée : la condition est >=, pas >."""
    merged = _early_stop_block(promote_score_vs_champion=0.55, promote_score_vs_others=0.50)
    gate = _minimal_curriculum()["gate"]
    _validate_early_stop_against_gate(merged, gate, "test")  # ne leve pas


# ── REGIME DE LIGNEE : VALIDATION ──────────────────────────────────────────────────────────

def test_a_stage_that_resumes_weights_may_not_declare_model_params() -> None:
    """La cle appartient au bloc de lignee ; la declarer sur l'etape cree une seconde source."""
    broken = _minimal_curriculum_with_exploiter()
    broken["stages"]["E1"]["role"] = "learner"  # sinon c'est le refus exploiteur qui tombe
    broken["stages"]["E1"]["training_config_overrides"] = {
        "total_episodes": 1000, "model_params": {"ent_coef": 0.05},
    }
    with pytest.raises(ValueError, match="training_configs"):
        validate_curriculum(broken)


def test_a_stage_that_resumes_weights_may_not_declare_the_seat_ratio() -> None:
    broken = _minimal_curriculum_with_exploiter()
    broken["stages"]["E1"]["role"] = "learner"
    broken["stages"]["E1"]["training_config_overrides"] = {"agent_seat_p2_ratio": 0.9}
    with pytest.raises(ValueError, match="training_configs"):
        validate_curriculum(broken)


def test_a_cold_started_stage_may_still_declare_its_own_model_params() -> None:
    """Le depart a froid n'est pas gouverne par la lignee : il garde le droit de se regler."""
    ok = _minimal_curriculum()
    ok["stages"]["P1"]["training_config_overrides"] = {
        "total_episodes": 1000, "model_params": {"ent_coef": 0.05},
    }
    validate_curriculum(ok)  # ne leve pas


def test_a_resumed_stage_without_a_training_configs_block_is_refused() -> None:
    """Sans contrainte, une etape reprise pourrait tourner sous le profil de demarrage a froid."""
    broken = _minimal_curriculum_with_exploiter()
    del broken["training_configs"]
    with pytest.raises(ConfigurationError, match="training_configs"):
        validate_curriculum(broken)


def test_a_cold_only_curriculum_needs_no_training_configs_block() -> None:
    """Aucune etape ne reprend de poids : il n'y a pas deux regimes a distinguer."""
    ok = _minimal_curriculum()
    for stage in ok["stages"].values():
        stage["init"] = "new"
    assert "training_configs" not in ok, "le scenario perdrait son objet si le bloc etait la"
    validate_curriculum(ok)  # ne leve pas


def test_an_incomplete_training_configs_block_is_refused() -> None:
    """Le bloc est COMPLET ou il ne contraint rien : une nature sans profil accepte tout."""
    broken = _minimal_curriculum_with_exploiter()
    del broken["training_configs"]["lineage"]
    with pytest.raises(ConfigurationError, match="lineage"):
        validate_curriculum(broken)


def test_the_same_profile_for_both_natures_is_refused() -> None:
    """Un profil unique ferait disparaitre en silence la distinction froid / chaud."""
    broken = _minimal_curriculum_with_exploiter()
    broken["training_configs"]["lineage"] = broken["training_configs"]["cold_start"]
    with pytest.raises(ValueError, match="MEME profil"):
        validate_curriculum(broken)


def test_an_unknown_role_in_training_configs_is_refused() -> None:
    """Une cle inventee y serait ignoree en silence, donc sans effet et sans alerte."""
    broken = _minimal_curriculum_with_exploiter()
    broken["training_configs"]["exploiter"] = "x1_debug"
    with pytest.raises(ValueError, match="exploiter"):
        validate_curriculum(broken)


def test_a_non_string_profile_name_is_refused() -> None:
    broken = _minimal_curriculum_with_exploiter()
    broken["training_configs"]["lineage"] = 4080
    with pytest.raises(TypeError, match="lineage"):
        validate_curriculum(broken)


def test_a_parity_window_that_misses_parity_is_refused() -> None:
    """Une fenetre qui n'encadre pas 0.5 refuserait TOUT run : elle est fausse, pas stricte."""
    broken = _minimal_curriculum()
    broken["parity_check"] = {"min_score": 0.55, "max_score": 0.65}
    with pytest.raises(ValueError, match="ENCADRER"):
        validate_curriculum(broken)


def test_the_shipped_parity_window_brackets_parity(curriculum) -> None:
    assert load_parity_check(curriculum) == (0.40, 0.60)


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

def test_gate_refuses_below_the_champion_floor() -> None:
    accepted, reason = evaluate_stage_gate("P4", "P3", {"P3": 0.54}, 0.55, 0.50)
    assert accepted is False
    assert "REFUSEE" in reason


def test_gate_accepts_when_both_floors_are_held() -> None:
    accepted, reason = evaluate_stage_gate(
        "P4", "P3", {"P3": 0.57, "P0": 0.62, "E1": 0.51}, 0.55, 0.50
    )
    assert accepted is True
    assert "planchers tenus" in reason


def test_gate_refuses_a_regression_against_a_non_champion_member() -> None:
    """DEUXIEME PLANCHER, pose le 2026-09-07 : le champion seul ne suffit plus.

    Avant, une etape pouvait etre promue en battant son predecesseur immediat tout en ayant
    regresse contre tout le reste du pool — l'ancien gate ne regardait que le champion, et rien
    dans le journal ne refusait cette etape. La regression contre un ancien est exactement ce
    qu'une lignee chainee doit detecter : c'est la seule facon de voir qu'elle derive.
    """
    accepted, reason = evaluate_stage_gate(
        "P4", "P3", {"P3": 0.70, "P0": 0.10, "P1": 0.10, "P2": 0.10, "E1": 0.10}, 0.55, 0.50
    )
    assert accepted is False
    assert "P0=0.100 < 0.50" in reason


def test_gate_does_not_apply_to_the_first_stage() -> None:
    accepted, reason = evaluate_stage_gate("P0", None, {}, 0.55, 0.50)
    assert accepted is True
    assert "sans objet" in reason


def test_gate_refuses_to_pass_when_the_champion_was_never_measured() -> None:
    """Un champion non mesure ne peut pas etre 'accepte par defaut' : le gate leve."""
    with pytest.raises(KeyError, match="P3"):
        evaluate_stage_gate("P4", "P3", {"P0": 0.9}, 0.55, 0.50)


# ── DECISIONS EN COURS DE RUN, SUR LA MOYENNE DES SONDES ───────────────────────────────────

_ES = {
    "probe_window": 3,
    "promote_score_vs_champion": 0.55,
    "promote_score_vs_others": 0.50,
    "promote_min_episodes": 50000,
    "destroy_score_vs_champion": 0.40,
    "destroy_min_episodes": 20000,
    "full_pool_probe_every": 3,
}


def test_decision_waits_for_the_promotion_floor_of_episodes() -> None:
    """Meme au-dessus des deux seuils, rien ne se decide avant `promote_min_episodes`."""
    decision = evaluate_pool_decision("P2", "P1", {"P1": 0.90, "P0": 0.90}, 49_999, _ES)
    assert decision.verdict == POOL_VERDICT_CONTINUE
    assert "50000" in decision.reason


def test_decision_promotes_when_both_floors_are_held_after_the_episode_gate() -> None:
    decision = evaluate_pool_decision("P2", "P1", {"P1": 0.56, "P0": 0.51}, 50_000, _ES)
    assert decision.verdict == POOL_VERDICT_PROMOTE


def test_decision_does_not_promote_on_the_champion_alone() -> None:
    """0.56 contre le champion mais 0.49 contre un ancien : le second plancher retient."""
    decision = evaluate_pool_decision("P2", "P1", {"P1": 0.56, "P0": 0.49}, 60_000, _ES)
    assert decision.verdict == POOL_VERDICT_CONTINUE
    assert "P0=0.490 < 0.50" in decision.reason


def test_decision_stops_for_destruction_below_the_floor() -> None:
    """Une etape part a 0.50 contre son champion par identite : 0.39 est une destruction."""
    decision = evaluate_pool_decision("P2", "P1", {"P1": 0.39, "P0": 0.95}, 20_000, _ES)
    assert decision.verdict == POOL_VERDICT_DESTROY
    assert "0.390" in decision.reason


def test_destruction_does_not_fire_before_its_own_episode_gate() -> None:
    """Avant `destroy_min_episodes` il n'y a pas encore deux sondes : rien a moyenner."""
    decision = evaluate_pool_decision("P2", "P1", {"P1": 0.20, "P0": 0.20}, 19_999, _ES)
    assert decision.verdict == POOL_VERDICT_CONTINUE


def test_destruction_wins_over_promotion_when_both_gates_are_open() -> None:
    """Les seuils ne peuvent pas se croiser (verrou de validation), l'ORDRE le garantit quand meme."""
    decision = evaluate_pool_decision("P2", "P1", {"P1": 0.30, "P0": 0.99}, 60_000, _ES)
    assert decision.verdict == POOL_VERDICT_DESTROY


def test_decision_is_a_noop_without_a_pool() -> None:
    decision = evaluate_pool_decision("P0", None, {}, 1_000_000, _ES)
    assert decision.verdict == POOL_VERDICT_CONTINUE


def test_decision_refuses_to_read_a_champion_that_was_never_probed() -> None:
    with pytest.raises(KeyError, match="P1"):
        evaluate_pool_decision("P2", "P1", {"P0": 0.9}, 60_000, _ES)


def test_promotion_and_gate_read_the_same_thresholds(curriculum) -> None:
    """Une etape ne doit pas pouvoir s'arreter sur un critere plus faible que celui qui la jugera.

    Les deux jeux de seuils vivent dans deux blocs du JSON (`early_stop` et `gate`) parce qu'ils
    repondent a deux questions distinctes — quand s'arreter, et si l'etape est promue — mais ils
    doivent porter les MEMES valeurs : un early-stop plus laxiste ferait s'arreter des runs que le
    gate refuserait ensuite, apres avoir jete le budget restant.
    """
    gate = curriculum["gate"]
    early_stop = curriculum["early_stop"]
    assert float(early_stop["promote_score_vs_champion"]) == pytest.approx(
        float(gate["min_score_vs_champion"])
    )
    assert float(early_stop["promote_score_vs_others"]) == pytest.approx(
        float(gate["min_score_vs_others"])
    )


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


def test_promotion_refuses_a_canonical_model_without_its_contract(tmp_path) -> None:
    """Un modele d'etape sans contrat n'est pas reprenable : l'etape suivante le refuserait.

    `--resume-from` installe le contrat DU modele promu ; le copier « s'il existe » aurait
    produit un `model_<agent>_<etape>.zip` muet, decouvert seulement a l'etape suivante.
    """
    from ai.training_contract import contract_path
    from ai.vec_normalize_utils import get_vec_normalize_path

    canonical = tmp_path / "model_TestAgent.zip"
    canonical.write_bytes(b"poids")
    with open(get_vec_normalize_path(str(canonical)), "wb") as handle:
        handle.write(b"stats")

    with pytest.raises(FileNotFoundError, match="aucun contrat"):
        promote_stage_model(str(canonical), "P4")

    # Refus AVANT toute copie : une etape a moitie promue passerait pour « deja promue » a la
    # relance de `--close-stage`.
    target = stage_model_path(str(canonical), "P4")
    assert not os.path.exists(target)
    assert not os.path.exists(get_vec_normalize_path(target))
    assert not os.path.exists(contract_path(target))


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
