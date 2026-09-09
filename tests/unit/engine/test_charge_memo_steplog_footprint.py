"""Verrou d'EMPREINTE `step.log` : le mémo d'engagement de charge ne change pas la trace.

`Documentation/Roadmap/infra.md` pose le verrou d'empreinte `step.log` comme la condition de
tout chantier d'optimisation du pool de déplacement et de la charge. Le mémo inter-intentions
(`charge_engage_memo`, `shared_utils.py`) est le premier changement livré sous cette condition ;
ce fichier la remplit.

CE QU'IL AJOUTE À `test_charge_intent_memo_contract.py` — l'autre verrou compare les PLANS rendus
par `charge_build_valid_plan`. Celui-ci compare la TRACE COMPLÈTE d'une partie : non seulement les
charges committées, mais tout ce qui en découle ensuite (déplacements, tirs, objectifs, fin de
partie). Un plan identique qui produirait malgré tout une trace différente — parce que le mémo
aurait touché un état partagé, par exemple — n'est visible qu'ici.

POURQUOI PAS `--test-only --step` : le modèle entraîné est incompatible avec l'espace
d'observation courant (`global_bin` 83 contre 95, `global_cont` 13 contre 23, `grid` 9 canaux
contre 12 — l'écart se creuse à chaque lot d'observation), donc `ai/train.py --test-only`
s'arrête avant d'écrire quoi que ce soit. Le verrou n'a de toute façon pas besoin d'une policy entraînée : il porte sur le MOTEUR.
Une politique aléatoire MASQUÉE et ensemencée suffit, et ne dépend d'aucun artefact qui dérive.

DÉTERMINISME — vérifié avant d'écrire ce fichier : deux runs identiques de 150 pas produisent
le même nombre de lignes, et les seules qui diffèrent portent `Duration=<n>s`, du temps de mur.
C'est la seule chose que `_normalise` retire, avec l'horodatage de début de ligne. Sans cette
mesure préalable, le verrou aurait été rouge en permanence et donc inutile.

LA GRAINE EST UN PARAMÈTRE DE MESURE, PAS UNE CONSTANTE DU VERROU. Une politique aléatoire
masquée n'a aucune raison de rejouer la même partie après un changement de moteur : la graine 42
d'origine (402 lignes, 2 charges committées) ne produisait plus AUCUNE charge après l'ouverture
de la verticalité au move (13.06), qui ajoute un point de décision et décale donc tout le tirage.
La graine 0 qui l'a remplacée le 2026-09-09 (mesurée alors à 323 lignes et 3 charges) est tombée
à ZÉRO charge le jour même, après les livraisons suivantes — le tirage se redécale à chaque
changement du moteur, et ce fichier ne dit rien d'autre en le constatant une deuxième fois.

Re-mesuré le 2026-09-09 sur SEIZE graines, à 150 pas, par ce fichier même (`_trace`, donc le
harnais du verrou et non une réimplémentation) : 0 → 0 charge committée, 2 → 0, 5 → 0, 7 → 0,
9 → 0, 11 → 0, 12 → 0, 15 → 0, 3 → 1, 4 → 1, 6 → 1, 8 → 1, 13 → 1, 1 → 2, 14 → 2, **10 → 5**.
La 10 est retenue pour sa marge, et ses 5 charges portent toutes un segment `[MODELS:]`. Zéro
charge committée sur une graine ne dit rien du moteur — c'est le résultat d'un jet de dés ; ce
qui compte est qu'il EXISTE des graines qui en produisent, et il y en a NEUF sur seize. Choisir
la graine est le geste que prévoit ce commentaire ; retirer l'assertion « aucune charge dans la
trace », non.
"""

from __future__ import annotations

import os
import re
import sys
from typing import Any, List

import numpy as np
import pytest

import engine.phase_handlers.shared_utils as su
from ai.step_logger import StepLogger
from engine.w40k_core import W40KEngine

PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
STEPS = 150
SEED = 10  # graine de mesure — voir « LA GRAINE EST UN PARAMÈTRE DE MESURE » en tête de fichier
BUFFER_SIZE = 200

_TIMESTAMP = re.compile(r"^\[\d\d:\d\d:\d\d\]\s*")
_DURATION = re.compile(r"Duration=[\d.]+s")


class _NeverStores(dict):
    """Mémo qui accepte les écritures et n'en garde aucune — le comportement d'avant."""

    def __setitem__(self, key: Any, value: Any) -> None:  # noqa: D105
        return


def _normalise(line: str) -> str:
    """Retire les deux seuls champs non déterministes : l'horodatage et la durée de mur."""
    return _DURATION.sub("Duration=<t>", _TIMESTAMP.sub("", line.rstrip("\n")))


def _trace(path: str, *, with_memo: bool) -> List[str]:
    """Déroule STEPS pas ensemencés et rend la trace normalisée."""
    sys.path.insert(0, os.path.join(PROJECT_ROOT, "scripts"))
    from bench_env_step import _build_env, _run_steps, _seed_randomness

    original = su.charge_engage_memo
    if not with_memo:
        su.charge_engage_memo = lambda _gs, _key: _NeverStores()
    try:
        _seed_randomness(SEED)
        env = _build_env()
        # `_build_env` empile Monitor(BotControlledEnv(ActionMasker(W40KEngine))) et `.unwrapped`
        # n'est typé que par l'interface Gym, qui ne connaît pas `step_logger`. Le contrôle n'est
        # pas là que pour le typage : si un wrapper cessait d'en être un, l'enregistreur serait
        # posé à côté du moteur, la trace resterait vide et les bornes anti-vert-vacant plus bas
        # ne diraient plus laquelle des deux causes a échoué.
        moteur = env.unwrapped
        assert isinstance(moteur, W40KEngine), (
            f"`.unwrapped` ne rend plus le moteur mais {type(moteur).__name__} : la pile de "
            "wrappers de `_build_env` a changé, l'enregistreur ne serait branché sur rien"
        )
        moteur.step_logger = StepLogger(path, enabled=True, buffer_size=BUFFER_SIZE)
        env.reset()
        _run_steps(env, STEPS, np.random.default_rng(SEED))
        env.close()
    finally:
        su.charge_engage_memo = original

    with open(path, encoding="utf-8", errors="ignore") as handle:
        return [_normalise(line) for line in handle]


@pytest.mark.integration
def test_the_charge_memo_leaves_the_step_log_footprint_identical(tmp_path):
    """Trace identique avec et sans mémoïsation, sur la même séquence ensemencée."""
    with_memo = _trace(str(tmp_path / "with_memo.log"), with_memo=True)
    without_memo = _trace(str(tmp_path / "without_memo.log"), with_memo=False)

    # VERT VACANT — une trace vide, ou sans charge, ou sans positions par figurine, rendrait
    # ce verrou vert sans rien garder. Les trois bornes viennent d'une mesure : 338 lignes,
    # 5 charges committées et 244 segments `[MODELS:]` sur 150 pas ensemencés à SEED=10.
    assert len(with_memo) > 100, f"trace trop courte ({len(with_memo)} lignes) — rien n'est gardé"
    charges = [ln for ln in with_memo if "CHARGED" in ln]
    assert charges, "aucune charge dans la trace — le verrou ne couvre pas ce qu'il vise"
    per_model = [ln for ln in with_memo if "[MODELS:" in ln]
    assert len(per_model) > 50, (
        f"seulement {len(per_model)} lignes portent [MODELS:] — sans les positions par "
        f"figurine, la trace ne verrait pas un plan de charge modifié"
    )
    assert any("[MODELS:" in ln for ln in charges), (
        "les lignes de charge ne portent pas [MODELS:] — c'est précisément le segment par "
        "lequel un placement par figurine modifié deviendrait visible"
    )

    if with_memo != without_memo:
        diffs = [
            (i, a, b)
            for i, (a, b) in enumerate(zip(with_memo, without_memo))
            if a != b
        ]
        detail = "\n".join(f"  L{i}\n    avec : {a}\n    sans : {b}" for i, a, b in diffs[:3])
        raise AssertionError(
            f"le mémo change l'empreinte step.log : {len(diffs)} ligne(s) divergentes, "
            f"{len(with_memo)} contre {len(without_memo)} lignes\n{detail}"
        )
