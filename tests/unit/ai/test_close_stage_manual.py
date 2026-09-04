"""Verrou — `--close-stage` clot une etape dont le run a ete interrompu.

Un run tue au clavier ou mort en vol ne revient jamais de `train_with_scenario_rotation` :
`_close_curriculum_stage` n'est donc pas atteint, et l'etape reste sans gate, sans ligne de
`curriculum.log` et sans `model_<agent>_<etape>.zip`. L'etape SUIVANTE nomme celle-ci dans son
`init` (`from:P1`) et refuse alors de demarrer, sur un `FileNotFoundError` de
`_apply_stage_init`. Aucun point d'entree n'exposait la cloture : `promote_stage_model` n'avait
qu'un seul appelant, la cloture elle-meme.

DEUX choses sont verrouillees ici, et la seconde est celle qui a failli passer :
1. la reconstruction de `run_info` depuis les artefacts du disque ;
2. la PLACE de la branche dans `main()`. Un `return` pose dans le bloc de validation de
   `--etape` sautait le prologue partage — `W40K_BOARD_PATH` (gate joue sur le plateau par
   defaut de config.json, donc une autre resolution que celle de l'agent), le defaut de
   `--rewards-config` (`controlled_agent=None`, mort dans `_strip_phase_suffix`), les overrides
   `--param` et la validation de `--training-config`. La branche vit desormais avec les autres
   modes qui n'entrainent pas, apres le prologue.
"""

from __future__ import annotations

import json
import os
from types import SimpleNamespace
from typing import Any

import pytest


class _Config:
    """Loader double : ne sert qu'a designer la racine des modeles."""

    def __init__(self, models_root: str) -> None:
        self._models_root = models_root

    def get_models_root(self) -> str:
        return self._models_root


#: Curriculum minimal : P1 reprend P0, P0 part de zero. Le test construit son scenario, il ne
#: lit pas `config/agents/**` — dont le contenu change au gre des runs.
_CURRICULUM: dict = {
    "order": ["P0", "P1"],
    "stages": {
        "P0": {"role": "learner", "init": "new", "warmup_episodes": 0,
               "ratio_start": 0.0, "ratio_end": 0.0, "pool": []},
        "P1": {"role": "learner", "init": "from:P0", "warmup_episodes": 0,
               "ratio_start": 0.0, "ratio_end": 0.5,
               "pool": [{"kind": "champion", "members": ["P0"], "weight": 0.5}]},
    },
}


def _args(agent: str = "ArmageddonAgent_x1", etape: str = "P1") -> Any:
    return SimpleNamespace(agent=agent, etape=etape)


def _canonical_path(models_root: str, agent: str) -> str:
    from ai.train import build_agent_model_path

    return build_agent_model_path(models_root, agent)


def _write_model(path: str, episodes: Any = None) -> None:
    from ai.run_state import get_run_state_path

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(b"zip")
    if episodes is not None:
        with open(get_run_state_path(path), "w", encoding="utf-8") as handle:
            json.dump({"episodes_trained": episodes}, handle)


def _write_run_artifacts(
    models_root: str, agent: str = "ArmageddonAgent_x1", *,
    episodes: Any = 50165, run_dir: str = "./tensorboard/x1/run_1",
    source_episodes: Any = 0, with_run_state: bool = True, with_tb_meta: bool = True,
    with_model: bool = True, with_source: bool = True,
) -> str:
    """Pose sur disque ce qu'un run interrompu laisse derriere lui."""
    from ai.curriculum import stage_model_path

    model_path = _canonical_path(models_root, agent)
    if with_model:
        _write_model(model_path, episodes if with_run_state else None)
    if with_tb_meta:
        os.makedirs(os.path.dirname(model_path), exist_ok=True)
        with open(f"{model_path}.tb_run.json", "w", encoding="utf-8") as handle:
            json.dump({"run_dir": run_dir}, handle)
    if with_source:
        _write_model(stage_model_path(model_path, "P0"), source_episodes)
    return model_path


def test_run_info_is_rebuilt_from_the_artifacts_on_disk(tmp_path) -> None:
    """Les cles que la cloture EXIGE sont lues, pas devinees."""
    from ai.train import _run_info_from_disk

    models_root = str(tmp_path / "models")
    _write_run_artifacts(models_root, episodes=57_240,
                         run_dir="./tensorboard/x1_long/run_20260903-181906")

    run_info = _run_info_from_disk(_args(), _Config(models_root), _CURRICULUM)

    assert run_info["episode_count_total"] == 57_240
    assert run_info["tensorboard_run_dir"] == "./tensorboard/x1_long/run_20260903-181906"


def test_episodes_trained_counts_the_stage_not_the_lifetime(tmp_path) -> None:
    """`episodes_trained` est le compte de l'ETAPE, offset du modele repris deduit.

    Le chemin nominal journalise `episode_count - episode_offset`. Publier le compte de vie
    ferait entrer dans `curriculum.log` un chiffre incomparable d'une etape a l'autre.
    """
    from ai.train import _run_info_from_disk

    models_root = str(tmp_path / "models")
    _write_run_artifacts(models_root, episodes=70_000, source_episodes=50_000)

    run_info = _run_info_from_disk(_args(), _Config(models_root), _CURRICULUM)

    assert run_info["episodes_trained"] == 20_000
    assert run_info["episode_count_total"] == 70_000


def test_a_cold_started_stage_has_no_offset(tmp_path) -> None:
    """Une etape `init: "new"` n'a pas de modele source : son offset vaut zero."""
    from ai.train import _run_info_from_disk

    models_root = str(tmp_path / "models")
    _write_run_artifacts(models_root, episodes=30_000, with_source=False)

    run_info = _run_info_from_disk(_args(etape="P0"), _Config(models_root), _CURRICULUM)

    assert run_info["episodes_trained"] == 30_000


def test_a_missing_source_model_is_refused(tmp_path) -> None:
    """Sans le modele source, l'offset est inconnu : erreur explicite, pas un total publie."""
    from ai.train import _run_info_from_disk

    models_root = str(tmp_path / "models")
    _write_run_artifacts(models_root, with_source=False)

    with pytest.raises(FileNotFoundError, match="from:P0"):
        _run_info_from_disk(_args(), _Config(models_root), _CURRICULUM)


def test_last_bot_eval_is_absent_rather_than_invented(tmp_path) -> None:
    """Aucun score bot n'est fabrique pour un run qui n'en a pas rendu.

    `_close_curriculum_stage` lit cette cle avec `.get` et n'ecrit alors rien dans le journal.
    La remplir depuis TensorBoard daterait le journal d'une mesure prise a un autre moment que le
    modele promu.
    """
    from ai.train import _run_info_from_disk

    models_root = str(tmp_path / "models")
    _write_run_artifacts(models_root)

    run_info = _run_info_from_disk(_args(), _Config(models_root), _CURRICULUM)

    assert "last_bot_eval" not in run_info


def test_an_already_promoted_stage_is_refused(tmp_path) -> None:
    """Re-clore ecraserait le modele promu par ce qui se trouve AUJOURD'HUI au chemin canonique.

    Le scenario vise : un `--etape` errone, ou une cloture lancee apres avoir relance autre chose
    sur le meme agent. `promote_stage_model` copie sans demander et `copy_tensorboard_run` fait un
    `rmtree` de sa cible ; les pools des etapes suivantes seraient empoisonnes sans trace.
    """
    from ai.curriculum import stage_model_path
    from ai.train import _run_info_from_disk

    models_root = str(tmp_path / "models")
    canonical = _write_run_artifacts(models_root)
    _write_model(stage_model_path(canonical, "P1"), 40_000)

    with pytest.raises(FileExistsError, match="DEJA promue"):
        _run_info_from_disk(_args(), _Config(models_root), _CURRICULUM)


def test_a_missing_canonical_model_is_refused(tmp_path) -> None:
    """Sans modele canonique, il n'y a rien a clore : erreur explicite, pas une promotion vide."""
    from ai.train import _run_info_from_disk

    models_root = str(tmp_path / "models")
    _write_run_artifacts(models_root, with_model=False)

    with pytest.raises(FileNotFoundError, match="modele canonique absent"):
        _run_info_from_disk(_args(), _Config(models_root), _CURRICULUM)


def test_a_missing_run_state_is_refused(tmp_path) -> None:
    """Le compte d'episodes ne se devine pas : il date le modele promu et pilote le journal."""
    from ai.train import _run_info_from_disk

    models_root = str(tmp_path / "models")
    _write_run_artifacts(models_root, with_run_state=False)

    with pytest.raises(FileNotFoundError, match="run_state"):
        _run_info_from_disk(_args(), _Config(models_root), _CURRICULUM)


def test_a_missing_tensorboard_sidecar_is_refused(tmp_path) -> None:
    """Le repertoire TensorBoard ne se devine pas non plus : `copy_tensorboard_run` en depend.

    Le `match` vise le sidecar et non un `FileNotFoundError` nu : la garde du modele canonique
    leve le MEME type, donc un test sans ancrage passerait au vert sans jamais atteindre la
    lecture du sidecar.
    """
    from ai.train import _run_info_from_disk

    models_root = str(tmp_path / "models")
    _write_run_artifacts(models_root, with_tb_meta=False)

    with pytest.raises(FileNotFoundError, match="TensorBoard run metadata not found"):
        _run_info_from_disk(_args(), _Config(models_root), _CURRICULUM)


# ── PLACE DE LA BRANCHE DANS main() ────────────────────────────────────────────────────────
#
# In-process et non par sous-processus : `ai.train` est deja importe par les tests ci-dessus, et
# les gardes visees se declenchent dans `main()` avant tout effet de bord. Un sous-processus
# repaierait un demarrage d'interpreteur et la chaine torch/stable_baselines3 par cas.


def _run_main(monkeypatch, argv: list) -> Any:
    """Joue `main()` sur `argv`. Rend son code de sortie.

    Les gardes d'arguments LEVENT (elles sont hors du `try` de `main`), tandis qu'un echec
    survenant apres le prologue est attrape et rendu comme code non nul.
    """
    import sys

    import ai.train as train_module

    monkeypatch.setattr(sys, "argv", ["ai/train.py"] + argv)
    return train_module.main()


def test_close_stage_without_etape_is_refused(monkeypatch) -> None:
    """Sans `--etape`, ni champion a affronter ni nom sous lequel promouvoir."""
    with pytest.raises(ValueError, match="--close-stage exige --etape"):
        _run_main(monkeypatch, [
            "--close-stage", "--agent", "ArmageddonAgent_x1", "--training-config", "x1_long",
        ])


def test_close_stage_refuses_resume_from(monkeypatch) -> None:
    """`--resume-from` installerait un autre checkpoint au chemin canonique que la cloture mesure.

    Le prologue partage appelle `_promote_checkpoint_for_resume` : sans ce refus, la cloture
    promouvrait un modele que l'utilisateur n'a jamais entraine sous cette etape.
    """
    with pytest.raises(ValueError, match="--close-stage et --resume-from sont exclusifs"):
        _run_main(monkeypatch, [
            "--close-stage", "--agent", "ArmageddonAgent_x1", "--training-config", "x1_long",
            "--etape", "P1", "--resume-from", "/inexistant/checkpoint.zip",
        ])


def test_close_stage_refuses_an_exploiter_stage(monkeypatch) -> None:
    """Le budget d'un exploiteur n'existe que dans le run : aucun artefact du disque ne le porte.

    Sans ce refus, `_close_exploiter_stage` journaliserait `budget: None` comme si la sonde avait
    tourne.
    """
    with pytest.raises(ValueError, match="etape EXPLOITEUR"):
        _run_main(monkeypatch, [
            "--close-stage", "--agent", "ArmageddonAgent_x1", "--training-config", "x1_long",
            "--etape", "E1",
        ])


def test_close_stage_runs_after_the_shared_prologue(monkeypatch) -> None:
    """La cloture recoit un `--rewards-config` defaute et un `W40K_BOARD_PATH` pose.

    C'est le verrou des deux defauts qu'un `return` place trop tot produisait, tous deux
    SILENCIEUX :
    - `args.rewards_config` reste None, donc `_score_stage_against_pool` passe
      `controlled_agent=None` a `evaluate_against_checkpoints`, qui meurt dans
      `_strip_phase_suffix(None)` sur `'NoneType' object has no attribute 'endswith'` ;
    - `W40K_BOARD_PATH` n'est pas pose, donc le gate se joue sur le plateau par defaut de
      `config.json` (`board/44x60x5`) au lieu de celui de la resolution de l'agent — et ce sont
      ces scores-la qui decident de la promotion et entrent dans `curriculum.log`.
    """
    import ai.train as train_module

    seen: dict = {}

    def _capture(args_, config_, curriculum_, stage_, run_info_) -> int:
        seen["rewards_config"] = args_.rewards_config
        seen["board"] = os.environ.get("W40K_BOARD_PATH")
        seen["stage_is_p1"] = stage_ is curriculum_["stages"]["P1"]
        return 0

    monkeypatch.setattr(train_module, "_close_curriculum_stage", _capture)
    monkeypatch.setattr(train_module, "_run_info_from_disk", lambda *a, **k: {})

    exit_code = _run_main(monkeypatch, [
        "--close-stage", "--agent", "ArmageddonAgent_x1", "--training-config", "x1_long",
        "--etape", "P1",
    ])

    assert exit_code == 0
    assert seen["rewards_config"] == "ArmageddonAgent_x1", (
        "--rewards-config non defaute : la cloture passera controlled_agent=None au gate"
    )
    assert seen["board"] == "board/44x60x1", (
        f"W40K_BOARD_PATH={seen['board']!r} : le gate se jouerait sur un autre plateau que "
        "celui de la resolution de l'agent"
    )
    assert seen["stage_is_p1"] is True


def test_close_stage_does_not_prepare_the_stage_init(monkeypatch) -> None:
    """`_prepare_curriculum_stage` ne doit PAS tourner : il pose `--new` ou `--resume-from`.

    Sur une cloture, cela ecarterait ou remplacerait le modele canonique que l'on vient
    precisement mesurer et promouvoir. Le test laisse la cloture echouer plus loin (aucun modele
    sur disque dans l'environnement de test) et verifie seulement que la preparation n'a pas eu
    lieu.
    """
    import ai.train as train_module

    called: list = []

    def _forbidden(*args_: Any, **kwargs_: Any) -> Any:
        called.append(True)
        raise AssertionError("_prepare_curriculum_stage appele sur une cloture")

    monkeypatch.setattr(train_module, "_prepare_curriculum_stage", _forbidden)
    exit_code = _run_main(monkeypatch, [
        "--close-stage", "--agent", "ArmageddonAgent_x1", "--training-config", "x1_long",
        "--etape", "P1",
    ])

    assert called == []
    # La cloture est bien ALLEE jusqu'au bout du prologue puis a echoue sur l'absence de modele
    # canonique dans l'arborescence de test — pas sur la preparation d'etape.
    assert exit_code != 0
