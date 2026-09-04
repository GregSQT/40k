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

import ast
import functools
import json
import os
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]

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
    from ai.train import build_agent_model_path

    model_path = build_agent_model_path(models_root, agent)
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


def _run_main(monkeypatch, argv: list, *, neutralise_closure: bool = True) -> Any:
    """Joue `main()` sur `argv`. Rend son code de sortie.

    Les gardes d'arguments LEVENT (elles sont hors du `try` de `main`), tandis qu'un echec
    survenant apres le prologue est attrape et rendu comme code non nul.

    `neutralise_closure` remplace la cloture et la lecture d'artefacts par des doubles. Sans
    cela, un test qui va jusqu'au bout du dispatch joue une VRAIE cloture sur `ai/models/` : gate
    de 300 episodes contre l'archive du champion, ligne ajoutee a `curriculum.log`,
    `promote_stage_model` qui ecrit `model_<agent>_<etape>.zip` et `copy_tensorboard_run` qui
    `rmtree` sa cible. CLAUDE.md interdit d'ecrire dans `ai/models/**/*.zip`, et rien n'y
    redirige la racine des modeles comme `tests/conftest.py` le fait pour `config/users.db`.
    C'est le controle de cycle de vie qui arretait ces tests avant, par accident : depuis que
    `--close-stage` en est exempte, l'arret ne tenait plus qu'a la presence fortuite d'un zip
    d'etape deja promu.
    """
    import sys

    import ai.train as train_module

    if neutralise_closure:
        monkeypatch.setattr(train_module, "_close_curriculum_stage", lambda *a, **k: 0)
        monkeypatch.setattr(train_module, "_run_info_from_disk", lambda *a, **k: {})
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


def test_close_stage_combined_with_another_read_only_mode_names_the_right_culprit(
    monkeypatch,
) -> None:
    """Le refus doit designer `--close-stage`, pas un entrainement qui n'a pas lieu.

    Le message generique de `--etape` annonce « joue un ENTRAINEMENT complet », ce qui est faux
    des que `--close-stage` est present : les deux drapeaux sont alors deux modes de LECTURE
    demandes en meme temps, et l'utilisateur enverrait retirer le mauvais.
    """
    with pytest.raises(ValueError, match="--close-stage ne fait que mesurer"):
        _run_main(monkeypatch, [
            "--close-stage", "--agent", "ArmageddonAgent_x1", "--training-config", "x1_long",
            "--etape", "P1", "--test-only",
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

    # La cloture est remplacee par `_capture` : elle ne doit RIEN ecrire dans `ai/models/`.
    monkeypatch.setattr(train_module, "_close_curriculum_stage", _capture)
    monkeypatch.setattr(train_module, "_run_info_from_disk", lambda *a, **k: {})

    exit_code = _run_main(monkeypatch, [
        "--close-stage", "--agent", "ArmageddonAgent_x1", "--training-config", "x1_long",
        "--etape", "P1",
    ], neutralise_closure=False)

    assert exit_code == 0
    assert seen["rewards_config"] == "ArmageddonAgent_x1", (
        "--rewards-config non defaute : la cloture passera controlled_agent=None au gate"
    )
    assert seen["board"] == "board/44x60x1", (
        f"W40K_BOARD_PATH={seen['board']!r} : le gate se jouerait sur un autre plateau que "
        "celui de la resolution de l'agent"
    )
    assert seen["stage_is_p1"] is True


def test_close_stage_is_not_asked_for_a_model_lifecycle_intention(monkeypatch) -> None:
    """`check_model_lifecycle` ne doit pas s'appliquer a une cloture.

    Elle exige `--new` ou `--append` des qu'un modele canonique existe — ce qui est toujours le
    cas quand on clot une etape, par construction. Or `--close-stage` exige `--etape`, et
    `--etape` combine a `--new` ou `--append` est rejete plus haut comme exclusif : la condition
    est insatisfiable, donc la cloture etait purement impossible.

    Le test porte sur l'APPEL et non sur la levee : la garde ne leve que si un modele existe
    reellement au chemin canonique, ce qui depend de l'arborescence ambiante. Verifier qu'elle
    n'est pas appelee du tout est ce qui reste vrai sur un depot fraichement clone comme sur le
    poste de l'utilisateur.
    """
    import ai.train as train_module

    appels: list = []
    monkeypatch.setattr(
        train_module, "check_model_lifecycle",
        lambda *a, **k: appels.append(a),
    )

    exit_code = _run_main(monkeypatch, [
        "--close-stage", "--agent", "ArmageddonAgent_x1", "--training-config", "x1_long",
        "--etape", "P1",
    ])

    assert exit_code == 0
    assert appels == [], (
        "check_model_lifecycle appele sur une cloture : elle reclamerait --new ou --append, que "
        "--etape interdit deja"
    )


def test_close_stage_does_not_prepare_the_stage_init(monkeypatch) -> None:
    """`_prepare_curriculum_stage` ne doit PAS tourner : il pose `--new` ou `--resume-from`.

    Sur une cloture, cela ecarterait ou remplacerait le modele canonique que l'on vient
    precisement mesurer et promouvoir. La cloture elle-meme est neutralisee par `_run_main` : ce
    test observe le dispatch, il ne doit toucher a aucun artefact.
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
    # La cloture neutralisee rend 0 : le dispatch est bien alle jusqu'au bout SANS passer par la
    # preparation d'etape.
    assert exit_code == 0


# ── ANCRE episodes_trained APRÈS CRASH+RESUME ───────────────────────────────────────────────────
#
# Scénario : étape P1 `init: from:P0`, run planté en cours d'étape, relancé avec
# --resume-from <checkpoint>. Le canonique porte l'état DU CHECKPOINT (C épisodes), pas celui de
# l'archive source (S épisodes, S < C). Les deux chemins de clôture doivent s'accorder sur le
# même episodes_trained = C - S.
#
# Chemin --close-stage  : _run_info_from_disk → load_run_state(source)  → offset = S.
# Chemin run nominal    : stage_origin(canonical, stage).episodes        → offset = S.
# La MÊME ancre doit être utilisée ; c'est ce que ce test verrouille.


def _write_sb3_zip(path: str, num_timesteps: int) -> None:
    """Crée un zip minimal lisible par stage_origin (zipfile + clé 'data')."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("data", json.dumps({"num_timesteps": num_timesteps, "ent_coef": 0.01}))


def test_episodes_trained_anchor_identical_for_both_closure_paths_after_crash_resume(
    tmp_path,
) -> None:
    """Crash+resume : run nominal et --close-stage utilisent la même ancre (archive source P0).

    Rouge avant le fix : episode_offset = checkpoint_episodes → run nominal donnait C - C = 0.
    Vert après le fix  : stage_episode_origin = source_episodes → les deux chemins donnent C - S.
    """
    from ai.curriculum import stage_origin
    from ai.run_state import save_run_state
    from ai.train import _run_info_from_disk, build_agent_model_path

    models_root = str(tmp_path / "models")

    source_episodes = 50_000
    checkpoint_episodes = 70_000

    # Archive source P0 : un vrai zip (stage_origin le lit) avec son run_state.
    canonical = build_agent_model_path(models_root, "ArmageddonAgent_x1")
    from ai.curriculum import stage_model_path
    source_path = stage_model_path(canonical, "P0")
    _write_sb3_zip(source_path, num_timesteps=10_000_000)
    save_run_state(source_path, source_episodes)

    # Canonique = checkpoint de mi-étape (état après crash+resume, pas l'archive source).
    os.makedirs(os.path.dirname(canonical), exist_ok=True)
    with open(canonical, "wb") as fh:
        fh.write(b"zip")
    save_run_state(canonical, checkpoint_episodes)
    with open(f"{canonical}.tb_run.json", "w", encoding="utf-8") as fh:
        json.dump({"run_dir": "./tensorboard/x1/run_1"}, fh)

    stage = _CURRICULUM["stages"]["P1"]

    # Chemin --close-stage.
    run_info = _run_info_from_disk(_args(), _Config(models_root), _CURRICULUM)
    close_stage_trained = run_info["episodes_trained"]

    # Ancre du chemin run nominal (la valeur qui sera passée en stage_episode_origin).
    nominal_origin = stage_origin(canonical, stage).episodes
    nominal_trained = checkpoint_episodes - nominal_origin

    assert close_stage_trained == nominal_trained, (
        f"Les deux chemins de clôture divergent après crash+resume : "
        f"--close-stage={close_stage_trained}, run nominal={nominal_trained}. "
        f"L'ancre doit être l'archive source ({source_episodes} épisodes), "
        f"pas le checkpoint ({checkpoint_episodes} épisodes)."
    )


# ── Verrou AST : stage_episode_origin utilisé dans episodes_trained ─────────────────────────────
#
# `train_with_scenario_rotation` lance un vrai training (trop lourd à tester bout-en-bout).
# L'invariant structurel est verrouillé dans l'AST : la formule de `episodes_trained` passe
# par `_ep_origin`, qui lui-même dérive de `stage_episode_origin` quand il est fourni.
# Une mutation naïve (`_ep_origin = episode_offset`) serait détectée ici.


@functools.cache
def _train_with_scenario_rotation_ast() -> ast.FunctionDef:
    tree = ast.parse((PROJECT_ROOT / "ai" / "train.py").read_text(encoding="utf-8"))
    definitions = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "train_with_scenario_rotation"
    ]
    assert definitions, "`train_with_scenario_rotation` introuvable dans ai/train.py"
    return definitions[-1]  # implémentation (pas les @overload)


def test_stage_episode_origin_is_used_as_episodes_trained_anchor() -> None:
    """La formule de episodes_trained passe par _ep_origin = stage_episode_origin or episode_offset.

    Rouge sans le fix : _ep_origin = episode_offset (checkpoint, pas archive source).
    Vert avec le fix  : _ep_origin utilise stage_episode_origin quand fourni.
    """
    func = _train_with_scenario_rotation_ast()
    src = ast.unparse(func)

    # La ligne _ep_origin doit mentionner stage_episode_origin.
    assert "stage_episode_origin" in src, (
        "stage_episode_origin absent du corps de train_with_scenario_rotation"
    )
    assert "_ep_origin" in src, (
        "_ep_origin absent : la formule de episodes_trained n'utilise pas stage_episode_origin"
    )
    # L'assignation FINALE de episodes_trained (celle qui alimente run_info) doit passer par
    # _ep_origin. L'assignation d'initialisation `episodes_trained = 0` (ligne ~3521, compteur de
    # frozen-model-update dans la boucle) n'est pas concernée — on isole en cherchant l'assignation
    # dont la RHS référence `metrics_tracker`.
    episodes_trained_final_assigns = [
        node
        for node in ast.walk(func)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(t, ast.Name) and t.id == "episodes_trained"
            for t in node.targets
        )
        and any(
            isinstance(n, ast.Name) and n.id == "_ep_origin"
            for n in ast.walk(node.value)
        )
    ]
    assert episodes_trained_final_assigns, (
        "aucune assignation de `episodes_trained` passant par `_ep_origin` trouvée dans "
        "train_with_scenario_rotation — la formule a été mutée"
    )
    for assign in episodes_trained_final_assigns:
        names_in_rhs = {n.id for n in ast.walk(assign.value) if isinstance(n, ast.Name)}
        assert "episode_offset" not in names_in_rhs, (
            f"episodes_trained utilise episode_offset directement (bypass de stage_episode_origin) : "
            f"{ast.unparse(assign)}"
        )
