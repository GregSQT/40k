#!/usr/bin/env python3
"""VERROU : les tags par defaut de `--decaying-tags` existent reellement dans un run.

`compute_schedule_diagnostic` ne leve pas sur un tag absent : `points_by_tag.get(tag, [])` rend
une liste vide et le diagnostic sort `{"status": "MISSING"}`. Un defaut qui nomme un tag mort ne
casse donc rien — il rend le diagnostic de rythme MUET, seed apres seed, sans un message.

C'est exactement ce qui est arrive le 2026-09-11 : le tracker a cesse de recopier
`train/learning_rate` sous le nom `training_diagnostic/learning_rate`, et le defaut du script
pointait encore sur la recopie.
"""

import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

from ai.metrics_tracker import W40KMetricsTracker

_AGENT_KEY = "ArmageddonAgent_x1"

#: Dump d'update PPO complet, tel que `training_callbacks` le passe au tracker.
_UPDATE_STATS: Dict[str, float] = {
    "train/learning_rate": 3e-4,
    "train/policy_gradient_loss": -0.2,
    "train/value_loss": 0.3,
    "train/entropy_loss": 0.05,
    "train/ent_coef": 0.01,
    "train/clip_fraction": 0.2,
    "train/approx_kl": 0.01,
    "train/approx_kl_max": 0.034,
    "train/explained_variance": 0.42,
    "train/n_updates": 10,
    "train/gradient_norm": 0.8,
    "train/grad_clip_fraction": 0.15,
    "diag/grad_share_policy_mb0": 0.235,
}


class _RecordingWriter:
    def __init__(self) -> None:
        self.scalars: List[Tuple[str, float, int]] = []

    def add_scalar(self, tag: str, scalar_value: float, global_step: int, /) -> None:
        self.scalars.append((tag, float(scalar_value), int(global_step)))

    def add_custom_scalars(self, layout: Dict[str, Any], /) -> None:
        return None

    def flush(self) -> None:
        return None

    def close(self) -> None:
        return None


def _default_decaying_tags() -> List[str]:
    """Relit le defaut de `--decaying-tags` par le parser lui-meme, sans le recopier ici."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
    try:
        import aggregate_seed_results
    finally:
        sys.path.pop(0)

    argv = sys.argv
    sys.argv = ["aggregate_seed_results.py", "--runs-root", ".", "--seeds", "1"]
    try:
        args = aggregate_seed_results.parse_args()
    finally:
        sys.argv = argv
    return list(args.decaying_tags)


def _tags_ecrits_par_le_tracker(tmp_path: Path) -> set[str]:
    t = W40KMetricsTracker(
        _AGENT_KEY,
        log_dir=str(tmp_path),
        show_banner=False,
        perf_window=1,
        perf_window_fast=1,
    )
    t.writer.close()
    writer = _RecordingWriter()
    t.writer = writer
    t.log_training_metrics(dict(_UPDATE_STATS))
    return {tag for tag, _v, _s in writer.scalars}


def test_chaque_tag_decroissant_par_defaut_a_un_ecrivain(tmp_path: Path) -> None:
    """Chaque defaut est ecrit soit par le tracker, soit par le logger de SB3.

    Les deux ecrivains publient dans le MEME dossier de run (`attach_run_logger`), donc
    `EventAccumulator` les lit tous les deux. `train/*` et `diag/*` sont le namespace de SB3 ;
    tout le reste doit sortir du tracker, ce que ce test constate en le faisant ecrire.
    """
    defauts = _default_decaying_tags()
    assert defauts, "defaut vide : le verrou ne regarderait rien"

    ecrits = _tags_ecrits_par_le_tracker(tmp_path)
    assert ecrits, "le tracker n'a rien ecrit sur un dump d'update complet"

    orphelins = [
        tag for tag in defauts
        if tag not in ecrits and not tag.startswith(("train/", "diag/", "time/", "rollout/"))
    ]
    assert orphelins == [], (
        f"tags par defaut sans ecrivain : {orphelins} — `compute_schedule_diagnostic` rendra "
        "silencieusement MISSING pour chaque seed"
    )
