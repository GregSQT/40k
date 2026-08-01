"""Contrat entre `ai/train.py` (qui EMET la ligne n_steps) et `scripts/ab_train_common.py` (qui la LIT).

Le banc A/B ne deduit pas le regime de `n_steps`, il le lit dans la sortie de `train.py` via
`_N_STEPS_RE`. Les deux fichiers sont donc couples par un format de texte, et rien ne le
signalait : changer le libelle cote `train.py` faisait silencieusement echouer le `search()`,
et `_expected_n_steps` concluait « pas de division » — donc comparait `requested` (un TOTAL) a
la valeur PAR ENV lue dans le zip, et refusait un run parfaitement correct.

Ce test fait produire la vraie ligne par la vraie fonction et la donne au vrai parseur. Il
casse a la seconde ou l'un des deux bouge sans l'autre.

Il verrouille aussi le trou signale par la revue : l'ancienne ligne annoncait le total DEMANDE,
ce qui masquait la troncature de `//` et le clamp `max(1, ...)`. A `n_envs=48`, `n_steps` 32 et
40 donnaient tous deux 1 pas par env — le banc validait les deux cotes et comparait deux fois
la meme configuration.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


def _box(n: int):
    import gymnasium as gym
    import numpy as np

    return gym.spaces.Box(low=-1, high=1, shape=(n,), dtype=np.float32)


def test_the_line_train_emits_is_the_line_the_bench_parses(capsys) -> None:
    """La vraie ligne, produite par la vraie fonction, lue par le vrai parseur. ROUGE si l'un bouge."""
    from ab_train_common import _N_STEPS_RE

    from ai.train import apply_rollout_n_steps

    params: Dict[str, Any] = {"n_steps": 8192}
    apply_rollout_n_steps(params, 48, _box(64))
    line = capsys.readouterr().out

    match = _N_STEPS_RE.search(line)
    assert match is not None, (
        f"_N_STEPS_RE ne reconnait plus la ligne emise par apply_rollout_n_steps : {line!r}. "
        "Le banc conclurait 'pas de division' et refuserait un run correct."
    )
    per_env, total, asked = (int(match.group(i)) for i in (1, 2, 3))
    assert (per_env, total, asked) == (170, 8160, 8192)
    assert per_env == params["n_steps"], "la ligne doit annoncer ce que PPO recoit"


def test_expected_n_steps_reads_that_line(capsys) -> None:
    """Bout en bout : la ligne emise donne bien la valeur par env attendue dans le zip."""
    from ab_train_common import _expected_n_steps

    from ai.train import apply_rollout_n_steps

    apply_rollout_n_steps({"n_steps": 8192}, 48, _box(64))
    assert _expected_n_steps(capsys.readouterr().out, 8192) == 170


def test_expected_n_steps_refuses_a_request_clamped_to_the_floor(capsys) -> None:
    """`max(1, 32 // 48)` = 1 : toute demande < n_envs donne le MEME rollout. ROUGE avant le fix."""
    from ab_train_common import _expected_n_steps

    from ai.train import apply_rollout_n_steps

    apply_rollout_n_steps({"n_steps": 32}, 48, _box(64))
    out = capsys.readouterr().out
    with pytest.raises(SystemExit, match="meme configuration"):
        _expected_n_steps(out, 32)


def test_expected_n_steps_still_catches_an_overridden_param(capsys) -> None:
    """Le garde-fou d'origine reste : ce que train.py a recu doit etre ce qui a ete demande."""
    from ab_train_common import _expected_n_steps

    from ai.train import apply_rollout_n_steps

    apply_rollout_n_steps({"n_steps": 8192}, 48, _box(64))
    out = capsys.readouterr().out
    with pytest.raises(SystemExit, match="ecrase --param"):
        _expected_n_steps(out, 4096)


def test_expected_n_steps_passes_through_when_no_division_happens(capsys) -> None:
    """n_envs=1 : aucune ligne emise, PPO recoit la valeur demandee telle quelle."""
    from ab_train_common import _expected_n_steps

    from ai.train import apply_rollout_n_steps

    apply_rollout_n_steps({"n_steps": 2048}, 1, _box(64))
    assert capsys.readouterr().out.strip() == "", "n_envs=1 ne doit rien annoncer"
    assert _expected_n_steps("", 2048) == 2048
