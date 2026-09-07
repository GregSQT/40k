"""Composition de _close_curriculum_stage (ai/train.py).

Les briques individuelles (evaluate_stage_gate, pool_monotonicity_diagnostic,
promote_stage_model, append_curriculum_log) sont testees dans test_curriculum.py.
Ce fichier verrouille leur ENCHAINEMENT et les deux codes de sortie.

_score_stage_against_pool est mocke : il charge de vrais modeles zip.
copy_tensorboard_run est mocke : I/O tensorboard irrelevant ici.
Tout le reste s'execute reellement.
"""

import json
import os
from types import SimpleNamespace

import pytest

import ai.train as train_mod
import ai.curriculum as curriculum_mod


# ── Fixtures ────────────────────────────────────────────────────────────────────────────────


def _make_args(etape: str = "P4") -> SimpleNamespace:
    return SimpleNamespace(
        etape=etape,
        training_config="x1",
        rewards_config="x1",
        agent="TestAgent",
    )


def _make_config(models_root: str) -> SimpleNamespace:
    return SimpleNamespace(
        get_models_root=lambda: models_root,
        load_agent_training_config=lambda _agent, _phase: {
            "callback_params": {
                "bot_eval_use_subprocess": False,
                "bot_eval_task_timeout_seconds": 60,
                "bot_eval_n_workers": 1,
                "bot_eval_n_workers_gate": 1,
            }
        },
    )


def _make_curriculum() -> dict:
    return {
        "order": ["P3", "P4"],
        "training_configs": {"cold_start": "x1_long", "lineage": "x1_lineage"},
        "parity_check": {"min_score": 0.40, "max_score": 0.60},
        "gate": {
            "min_score_vs_champion": 0.55,
            "min_score_vs_others": 0.50,
            "eval_repeats": 3,
            "eval_episodes": 10,
        },
        "stages": {
            "P3": {"role": "learner", "pool": [], "init": None, "ratio_start": 0.0, "ratio_end": 0.0, "warmup_episodes": 0},
            "P4": {
                "role": "learner",
                "pool": [{"kind": "champion", "members": ["P3"], "weight": 1.0}],
                "init": "P3",
                "ratio_start": 0.20,
                "ratio_end": 0.50,
                "warmup_episodes": 100,
            },
        },
    }


def _make_run_info(tmp_path) -> dict:
    tb_dir = tmp_path / "tb_run"
    tb_dir.mkdir()
    return {
        "last_bot_eval": {"random": 0.80},
        "episodes_trained": 50000,
        "episode_count_total": 50000,
        "tensorboard_run_dir": str(tb_dir),
    }


def _make_canonical_model(tmp_path) -> str:
    """Cree un zip minimal sous le nom retourne par le mock de build_agent_model_path."""
    model = tmp_path / "model_Stub.zip"
    model.write_bytes(b"fake-weights")
    return str(model)


def _make_context(tmp_path):
    canonical = _make_canonical_model(tmp_path)
    args = _make_args()
    config = _make_config(str(tmp_path))
    curriculum = _make_curriculum()
    stage = curriculum["stages"]["P4"]
    run_info = _make_run_info(tmp_path)
    return canonical, args, config, curriculum, stage, run_info


# ── Tests ───────────────────────────────────────────────────────────────────────────────────


def _patch_common(monkeypatch, tmp_path, canonical: str, score: float):
    """Mocks communs aux deux tests : score + chemin canonique + journal. TB est mockee par chaque test."""
    monkeypatch.setattr(train_mod, "build_agent_model_path", lambda _root, _key: canonical)
    monkeypatch.setattr(train_mod, "_score_stage_against_pool", lambda *_a, **_kw: {"P3": score})
    log_path = tmp_path / "curriculum.log"
    monkeypatch.setattr(
        train_mod, "append_curriculum_log",
        lambda entry, path=None: curriculum_mod.append_curriculum_log(entry, str(log_path)),
    )
    return log_path


def test_gate_refus_renvoie_exit_1_et_nescrit_aucun_zip(tmp_path, monkeypatch):
    """Score sous le plancher → exit 1, aucun _P4.zip cree, copy_tensorboard_run non appele, journal ecrit quand meme."""
    canonical, args, config, curriculum, stage, run_info = _make_context(tmp_path)
    log_path = _patch_common(monkeypatch, tmp_path, canonical, score=0.40)

    tb_copied = []
    monkeypatch.setattr(
        train_mod, "copy_tensorboard_run",
        lambda run_dir, etape: tb_copied.append((run_dir, etape)) or "/fake/tb",
    )

    exit_code = train_mod._close_curriculum_stage(args, config, curriculum, stage, run_info)

    assert exit_code == 1

    promoted = tmp_path / "model_Stub_P4.zip"
    assert not promoted.exists(), "aucun zip promeu attendu sur refus"

    assert not tb_copied, "copy_tensorboard_run ne doit pas etre appele sur refus"

    entries = [json.loads(line) for line in log_path.read_text().splitlines()]
    assert entries, "le journal doit etre ecrit meme sur refus"
    assert entries[-1]["gate_accepted"] is False
    assert entries[-1]["etape"] == "P4"
    assert entries[-1]["scores_vs_pool"] == {"P3": 0.40}


def test_gate_accepte_renvoie_exit_0_et_ecrit_zip_et_journal(tmp_path, monkeypatch):
    """Score au-dessus de la cible → exit 0, _P4.zip cree, TB copie, journal marque accepted."""
    canonical, args, config, curriculum, stage, run_info = _make_context(tmp_path)
    log_path = _patch_common(monkeypatch, tmp_path, canonical, score=0.65)

    tb_copied = []
    monkeypatch.setattr(
        train_mod,
        "copy_tensorboard_run",
        lambda run_dir, etape: tb_copied.append((run_dir, etape)) or "/fake/tb",
    )

    exit_code = train_mod._close_curriculum_stage(args, config, curriculum, stage, run_info)

    assert exit_code == 0

    promoted = tmp_path / "model_Stub_P4.zip"
    assert promoted.exists(), "_P4.zip doit etre cree sur acceptation"
    assert promoted.read_bytes() == b"fake-weights"

    assert tb_copied, "copy_tensorboard_run doit etre appele sur acceptation"
    assert tb_copied[0][1] == "P4"

    entries = [json.loads(line) for line in log_path.read_text().splitlines()]
    assert entries[-1]["gate_accepted"] is True
    assert entries[-1]["scores_vs_pool"] == {"P3": 0.65}
    assert entries[-1]["scores_vs_bots"] == {"random": 0.80}


def test_gate_accepte_episode_count_total_absent_lève(tmp_path, monkeypatch):
    """episode_count_total absent de run_info → ConfigurationError, pas de skip silencieux.

    Rouge sans le require_key : save_run_state sautée silencieusement.
    Vert avec le require_key : lève avant toute écriture.
    """
    from shared.data_validation import ConfigurationError

    canonical, args, config, curriculum, stage, run_info = _make_context(tmp_path)
    del run_info["episode_count_total"]

    _patch_common(monkeypatch, tmp_path, canonical, score=0.65)

    with pytest.raises(ConfigurationError, match="episode_count_total"):
        train_mod._close_curriculum_stage(args, config, curriculum, stage, run_info)


def test_gate_accepte_run_state_reflète_episodes_entraînes(tmp_path, monkeypatch):
    """Gate acceptée : run_state de l'étape promue porte episode_count_total du run_info.

    Rouge avant le fix : canonical run_state absent → promote_stage_model le saute → FileNotFoundError.
    Vert après le fix : _close_curriculum_stage écrit le canonical run_state avant promotion.
    """
    from ai.run_state import load_run_state

    canonical, args, config, curriculum, stage, run_info = _make_context(tmp_path)
    run_info["episode_count_total"] = 5000

    log_path = _patch_common(monkeypatch, tmp_path, canonical, score=0.65)
    monkeypatch.setattr(train_mod, "copy_tensorboard_run", lambda *_a: "/fake/tb")

    exit_code = train_mod._close_curriculum_stage(args, config, curriculum, stage, run_info)
    assert exit_code == 0

    promoted = tmp_path / "model_Stub_P4.zip"
    assert load_run_state(str(promoted)) == 5000


def test_gate_accepte_run_state_canonique_existant_nest_pas_ecrase(tmp_path, monkeypatch):
    """Un run_state canonique DEJA ecrit fait autorite : la cloture ne l'ecrase pas.

    C'est le cas `save_best_robust` (profils x1_long/x5_long, ceux des etapes de curriculum) : le
    zip canonique est l'INSTANTANE ROBUSTE pris plus tot dans le run, et
    `BotEvaluationCallback._copy_model_artifacts` lui a deja ecrit un run_state coherent avec SES
    poids. Y poser le compte de FIN de run daterait le modele d'episodes qu'il n'a pas joues, et
    `promote_stage_model` propagerait l'ecart a l'etape suivante, qui repartirait sur un
    `episode_offset` gonfle.
    """
    from ai.run_state import load_run_state, save_run_state

    canonical, args, config, curriculum, stage, run_info = _make_context(tmp_path)
    # Le run a tourne 50 000 episodes, mais l'instantane robuste retenu date de l'episode 30 000.
    run_info["episode_count_total"] = 50000
    save_run_state(canonical, 30000)

    _patch_common(monkeypatch, tmp_path, canonical, score=0.65)
    monkeypatch.setattr(train_mod, "copy_tensorboard_run", lambda *_a: "/fake/tb")

    exit_code = train_mod._close_curriculum_stage(args, config, curriculum, stage, run_info)
    assert exit_code == 0

    assert load_run_state(canonical) == 30000, (
        "le run_state canonique, deja coherent avec les poids de l'instantane, a ete ecrase"
    )
    promoted = tmp_path / "model_Stub_P4.zip"
    assert load_run_state(str(promoted)) == 30000, (
        "l'etape promue doit porter le compte de l'instantane promu, pas celui de fin de run"
    )


# ── UN VERDICT `destroy` EST SOUVERAIN : LE GATE NE LE REJUGE PAS ───────────────────────────


def test_un_verdict_destroy_refuse_letape_meme_si_le_gate_laurait_acceptee(tmp_path, monkeypatch):
    """LE cas du finding : sous `save_best_robust`, le gate ne mesure pas le modele juge.

    L'early-stop a arrete le run parce que la moyenne glissante des sondes est tombee sous le
    plancher de destruction. Mais le zip canonique est alors l'INSTANTANE ROBUSTE pris plus tot
    dans le run — d'autres poids que ceux sur lesquels le verdict a ete rendu. Ici il mesure 0.65,
    tres au-dessus du plancher de 0.55 : sans court-circuit, le gate acceptait, `promote_stage_model`
    ecrivait `model_Stub_P4.zip`, le processus sortait a 0, et `curriculum.log` portait
    `pool_stop_verdict: "destroy"` A COTE de `gate_accepted: true`. P4 devenait alors le champion
    de P5.
    """
    canonical, args, config, curriculum, stage, run_info = _make_context(tmp_path)
    run_info["pool_stop_verdict"] = curriculum_mod.POOL_VERDICT_DESTROY
    run_info["pool_stop_reason"] = "P4 : moyenne 0.350 contre P3, sous 0.40. Run ARRETE."
    log_path = _patch_common(monkeypatch, tmp_path, canonical, score=0.65)

    tb_copied = []
    monkeypatch.setattr(
        train_mod, "copy_tensorboard_run",
        lambda run_dir, etape: tb_copied.append((run_dir, etape)) or "/fake/tb",
    )

    exit_code = train_mod._close_curriculum_stage(args, config, curriculum, stage, run_info)

    assert exit_code == 1, "un run detruit ne peut pas sortir en succes"
    assert not (tmp_path / "model_Stub_P4.zip").exists(), "aucune promotion apres destruction"
    assert not tb_copied, "aucun run TensorBoard promu apres destruction"

    entry = [json.loads(line) for line in log_path.read_text().splitlines()][-1]
    assert entry["gate_accepted"] is False
    assert entry["pool_stop_verdict"] == curriculum_mod.POOL_VERDICT_DESTROY
    assert "0.350" in entry["pool_stop_reason"], "le journal doit porter la raison de l'arret"


def test_un_verdict_destroy_ne_paie_pas_la_mesure_du_gate(tmp_path, monkeypatch):
    """La mesure est SAUTEE, pas seulement ignoree.

    `_score_stage_against_pool` coute `eval_repeats` x `eval_episodes` episodes PAR MEMBRE du
    pool — des heures sur un pool de fin de curriculum. Les payer pour un chiffre qui ne peut plus
    rien changer, et qui decrirait un modele que personne n'a decide de promouvoir, est du
    gaspillage pur.
    """
    canonical, args, config, curriculum, stage, run_info = _make_context(tmp_path)
    run_info["pool_stop_verdict"] = curriculum_mod.POOL_VERDICT_DESTROY
    run_info["pool_stop_reason"] = "detruite"
    _patch_common(monkeypatch, tmp_path, canonical, score=0.65)

    appels = []
    monkeypatch.setattr(
        train_mod, "_score_stage_against_pool",
        lambda *a, **kw: appels.append(1) or {"P3": 0.65},
    )
    monkeypatch.setattr(train_mod, "copy_tensorboard_run", lambda *_a: "/fake/tb")

    assert train_mod._close_curriculum_stage(args, config, curriculum, stage, run_info) == 1
    assert appels == [], "le gate ne doit rien mesurer apres un verdict de destruction"


def test_un_verdict_promote_laisse_le_gate_mesurer_et_promouvoir(tmp_path, monkeypatch):
    """Contre-epreuve : SEUL `destroy` court-circuite.

    Une promotion anticipee dit que l'etape a fini son travail — c'est precisement le cas ou le
    gate doit mesurer et, s'il est franchi, promouvoir. Court-circuiter tout verdict d'arret
    rendrait tout arret anticipe inutile.
    """
    canonical, args, config, curriculum, stage, run_info = _make_context(tmp_path)
    run_info["pool_stop_verdict"] = curriculum_mod.POOL_VERDICT_PROMOTE
    run_info["pool_stop_reason"] = "seuils de promotion franchis"
    log_path = _patch_common(monkeypatch, tmp_path, canonical, score=0.65)
    monkeypatch.setattr(train_mod, "copy_tensorboard_run", lambda *_a: "/fake/tb")

    assert train_mod._close_curriculum_stage(args, config, curriculum, stage, run_info) == 0
    assert (tmp_path / "model_Stub_P4.zip").exists(), "une promotion anticipee reste promouvable"

    entry = [json.loads(line) for line in log_path.read_text().splitlines()][-1]
    assert entry["gate_accepted"] is True
    assert entry["scores_vs_pool"] == {"P3": 0.65}


# ── `--close-stage` NE DOIT PAS ROUVRIR LA PROMOTION D'UNE ETAPE DETRUITE ───────────────────


def _prepare_disk_artifacts(tmp_path, monkeypatch, canonical: str, curriculum: dict):
    """Les artefacts que `_run_info_from_disk` relit a cote du modele canonique.

    `init: from:P3` et non le `"P3"` nu de la fixture generale : c'est la forme que
    `stage_init_source` accepte, et l'archive source porte l'offset d'episodes de l'etape.
    """
    from ai.run_state import save_run_state

    curriculum["stages"]["P4"]["init"] = "from:P3"
    source = curriculum_mod.stage_model_path(canonical, "P3")
    with open(source, "wb") as handle:
        handle.write(b"fake-source")
    save_run_state(source, 20_000)
    save_run_state(canonical, 50_000)
    train_mod._write_tensorboard_run_meta(canonical, str(tmp_path / "tb_run"))
    monkeypatch.setattr(train_mod, "build_agent_model_path", lambda _root, _key: canonical)


def test_close_stage_relit_le_verdict_destroy_dans_son_sidecar(tmp_path, monkeypatch):
    """LE finding : le court-circuit de destruction survit a la commande de reprise.

    Un run detruit atteint bien `_close_curriculum_stage` : le gate est court-circuite et AUCUN
    `model_<agent>_P4.zip` n'est ecrit. Le garde « etape deja promue » de `_run_info_from_disk` ne
    voit donc rien, et `--close-stage` repartait sur un `run_info` reconstruit ou le verdict
    n'existait pas : la mesure reprenait sur l'instantane robuste, et l'etape que le run venait de
    detruire pouvait etre promue.
    """
    canonical, args, config, curriculum, stage, _ = _make_context(tmp_path)
    _prepare_disk_artifacts(tmp_path, monkeypatch, canonical, curriculum)
    train_mod.save_pool_stop_verdict(
        canonical, curriculum_mod.POOL_VERDICT_DESTROY,
        "P4 : moyenne 0.350 contre P3, sous 0.40. Run ARRETE.",
    )

    run_info = train_mod._run_info_from_disk(args, config, curriculum)

    assert run_info["pool_stop_verdict"] == curriculum_mod.POOL_VERDICT_DESTROY
    assert "0.350" in run_info["pool_stop_reason"]

    # Et le court-circuit s'applique : gate non mesure, exit 1, aucune promotion.
    _patch_common(monkeypatch, tmp_path, canonical, score=0.65)
    appels = []
    monkeypatch.setattr(
        train_mod, "_score_stage_against_pool",
        lambda *a, **kw: appels.append(1) or {"P3": 0.65},
    )
    monkeypatch.setattr(train_mod, "copy_tensorboard_run", lambda *_a: "/fake/tb")

    assert train_mod._close_curriculum_stage(args, config, curriculum, stage, run_info) == 1
    assert appels == []
    assert not (tmp_path / "model_Stub_P4.zip").exists()


def test_close_stage_dun_run_jamais_clos_na_pas_de_verdict(tmp_path, monkeypatch):
    """Contre-epreuve : un run tue au clavier n'a ecrit AUCUN sidecar de verdict.

    C'est le cas nominal de `--close-stage`. Le verdict doit y rester None, sinon la commande
    refuserait la cloture qu'elle existe pour rendre possible.
    """
    canonical, args, config, curriculum, _stage, _ = _make_context(tmp_path)
    _prepare_disk_artifacts(tmp_path, monkeypatch, canonical, curriculum)

    run_info = train_mod._run_info_from_disk(args, config, curriculum)

    assert run_info["pool_stop_verdict"] is None
    assert run_info["pool_stop_reason"] is None
    assert run_info["episodes_trained"] == 30_000, "50 000 cumules moins les 20 000 de P3"


def test_le_verdict_est_ecarte_au_demarrage_du_run_suivant(tmp_path, monkeypatch):
    """Le sidecar suit le cycle de vie du RUN, et pas l'historique de l'etape.

    C'est ce qui interdit a une TENTATIVE precedente de decider. Rejouer P4 apres l'avoir
    detruite, puis tuer ce run au clavier, ne doit pas faire refuser la nouvelle tentative avec le
    verdict de l'ancienne — ce que ferait une relecture de `curriculum.log`, qui est en append,
    conserve toutes les tentatives et ne porte AUCUNE cle d'agent.

    `--new` comme `--resume-from` ecartent les artefacts canoniques par le meme
    `canonical_set_aside_pairs` : il suffit donc que le sidecar y figure.
    """
    canonical, _args, _config, _curriculum, _stage, _ = _make_context(tmp_path)
    train_mod.save_pool_stop_verdict(canonical, curriculum_mod.POOL_VERDICT_DESTROY, "detruite")
    sidecar = train_mod.pool_stop_path(canonical)
    assert os.path.exists(sidecar)

    assert sidecar in [origin for origin, _ in train_mod.canonical_set_aside_pairs(
        canonical, "pre_resume_20260907-120000"
    )], "le verdict doit etre ecarte au demarrage, comme le seuil de score robuste"

    train_mod.archive_canonical_artifacts_for_new_run(canonical, log_fn=lambda _m: None)

    assert not os.path.exists(sidecar)
    assert train_mod.load_pool_stop_verdict(canonical) == (None, None)


def test_le_verdict_est_propre_a_chaque_agent(tmp_path, monkeypatch):
    """Deux agents jouant la meme etape ne partagent pas leur verdict.

    Le sidecar est derive du modele CANONIQUE, donc de l'agent. `curriculum.log` ne portant pas de
    cle d'agent, une relecture par etape aurait confondu les deux.
    """
    autre = str(tmp_path / "model_AutreAgent.zip")
    canonical, _args, _config, _curriculum, _stage, _ = _make_context(tmp_path)
    train_mod.save_pool_stop_verdict(canonical, curriculum_mod.POOL_VERDICT_DESTROY, "detruite")

    assert train_mod.load_pool_stop_verdict(autre) == (None, None)


def test_close_stage_refuse_un_pool_a_deux_champions(tmp_path, monkeypatch):
    """`validate_curriculum` n'exige qu'AU MOINS un champion ; la cloture doit refuser le reste.

    Un run d'entrainement s'arrete deja sur ce pool (`stage_champion_label`). La cloture, elle,
    prenait le premier venu et appliquait `min_score_vs_champion` a un etalon arbitraire, l'autre
    champion tombant sous le plancher plus laxiste des `others`.
    """
    canonical, args, config, curriculum, stage, run_info = _make_context(tmp_path)
    stage["pool"] = [{"kind": "champion", "members": ["P2", "P3"], "weight": 1.0}]
    _patch_common(monkeypatch, tmp_path, canonical, score=0.65)
    monkeypatch.setattr(train_mod, "copy_tensorboard_run", lambda *_a: "/fake/tb")

    with pytest.raises(ValueError, match="qu'UN champion"):
        train_mod._close_curriculum_stage(args, config, curriculum, stage, run_info)
