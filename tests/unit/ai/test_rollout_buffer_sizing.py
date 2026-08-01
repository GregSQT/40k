"""`n_steps` est un TOTAL par update : tout chemin vectorise DOIT le diviser par `n_envs`.

Bug d'origine, mesure a l'appui. Trois fonctions de `ai/train.py` construisent un
`SubprocVecEnv` de `n_envs` environnements — `create_model`, `create_multi_agent_model`,
`train_with_scenario_rotation` — mais une seule divisait `n_steps`. Un run mono-scenario
(`--scenario X --new`), qui passe par `create_model`, allouait donc un buffer de
`8192 x 48 = 393 216` transitions au lieu de 8160, soit **44 Go** rien que pour les
observations (30 044 flottants par obs, config x1).

MESURE sur le run fautif (PID 7720) : `VmSize` 139,7 Go, RSS croissant de 2,4 Go/min a mesure
que les pages du buffer etaient touchees, les six plus gros mappings anonymes dans les rapports
exacts des cles d'observation (grid 9216 : enemies_wpn_bin 7200 : enemies_wpn_cont 5200 =
1 : 0,78 : 0,56), 113 920 transitions remplies sur 393 216. La VM WSL mourait avant la fin.

C'est le motif JUMEAU du depot a l'etat pur : correction appliquee a un chemin sur trois,
sur du code qui n'echoue pas — il consomme.

Verrous :
- CONTRAT : aucun site de `ai/train.py` ne construit ou ne recharge un modele sans passer par
  les fabriques uniques (celui qui attraperait la reintroduction sur un 4e chemin) ;
- COMPORTEMENT : les fabriques divisent, journalisent le total REELLEMENT obtenu (pas celui
  demande — `//` tronque), et refusent un buffer plus gros que la memoire disponible.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, Dict, List

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
TRAIN_PY = PROJECT_ROOT / "ai" / "train.py"


def _enclosing_function(tree: ast.AST, lineno: int) -> str:
    owners = [
        node.name for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.lineno <= lineno <= (node.end_lineno or node.lineno)
    ]
    return owners[-1] if owners else "<module>"


def _train_tree() -> ast.AST:
    return ast.parse(TRAIN_PY.read_text(encoding="utf-8"))


def test_every_subprocvecenv_path_converts_n_steps() -> None:
    """Chaque fonction qui construit un SubprocVecEnv appelle apply_rollout_n_steps."""
    tree = _train_tree()
    builders, converters = set(), set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        if node.func.id == "SubprocVecEnv":
            builders.add(_enclosing_function(tree, node.lineno))
        elif node.func.id == "apply_rollout_n_steps":
            converters.add(_enclosing_function(tree, node.lineno))
    assert builders, "aucun SubprocVecEnv trouve : le test regarderait le vide"
    missing = builders - converters
    assert not missing, (
        f"ces fonctions construisent un SubprocVecEnv sans convertir n_steps : {sorted(missing)}. "
        "n_steps est un TOTAL par update ; sans division le buffer vaut n_steps x n_envs "
        "transitions (8192 x 48 = 44 Go d'observations, mesure)."
    )


def test_every_n_steps_assignment_rebuilds_the_buffer() -> None:
    """`model.n_steps = ...` sans reconstruction laisse le buffer du checkpoint."""
    tree = _train_tree()
    offenders: List[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Attribute) or target.attr != "n_steps":
            continue
        if not isinstance(target.value, ast.Name) or target.value.id != "model":
            continue
        parent_fn = _enclosing_function(tree, node.lineno)
        rebuilt = any(
            isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
            and n.func.id == "recreate_rollout_buffer"
            and abs(n.lineno - node.lineno) <= 3
            for n in ast.walk(tree)
        )
        if not rebuilt:
            offenders.append(f"{parent_fn}:{node.lineno}")
    assert not offenders, (
        f"`model.n_steps` ecrit sans recreate_rollout_buffer : {offenders}. "
        "MaskablePPO.load dimensionne le buffer sur le checkpoint ; l'ecriture seule ne le "
        "redimensionne pas."
    )


def _space(kind: str):
    import gymnasium as gym
    import numpy as np

    if kind == "dict":
        return gym.spaces.Dict({
            "a": gym.spaces.Box(low=-1, high=1, shape=(100,), dtype=np.float32),
            "b": gym.spaces.Box(low=-1, high=1, shape=(4, 25), dtype=np.float32),
        })
    return gym.spaces.Box(low=-1, high=1, shape=(200,), dtype=np.float32)


@pytest.mark.parametrize("kind,expected_floats", [("dict", 200), ("box", 200)])
def test_observation_floats_counts_every_key(kind: str, expected_floats: int) -> None:
    """VERT VACANT : un espace Dict dont on ne compterait qu'une cle sous-estimerait le buffer."""
    from ai.train import _observation_floats

    assert _observation_floats(_space(kind)) == expected_floats


def test_apply_rollout_n_steps_divides_and_reports_the_real_total(capsys) -> None:
    """Divise, et journalise le total OBTENU, pas celui demande. ROUGE avant le fix."""
    from ai.train import apply_rollout_n_steps

    params: Dict[str, Any] = {"n_steps": 8192}
    effective = apply_rollout_n_steps(params, 48, _space("box"))
    assert effective == 170, "8192 // 48 = 170 pas par env"
    assert params["n_steps"] == 170, "model_params doit porter la valeur PAR ENV"
    out = capsys.readouterr().out
    # 170 * 48 = 8160, pas 8192 : `//` tronque. Annoncer 8192 a deja fait valider a
    # scripts/ab_train_common.py deux configurations que le clamp rendait identiques.
    assert "8160 total" in out, f"le total journalise doit etre celui obtenu : {out!r}"


def test_apply_rollout_n_steps_is_a_noop_on_single_env() -> None:
    """n_envs=1 : le total EST le nombre de pas par env, aucune division."""
    from ai.train import apply_rollout_n_steps

    params: Dict[str, Any] = {"n_steps": 2048}
    assert apply_rollout_n_steps(params, 1, _space("box")) == 2048
    assert params["n_steps"] == 2048


def test_apply_rollout_n_steps_refuses_an_oversized_buffer() -> None:
    """Le buffer fautif (44 Go) doit lever AU LANCEMENT, pas apres 10 min de remplissage."""
    import gymnasium as gym
    import numpy as np

    from ai.train import apply_rollout_n_steps

    # 30 044 flottants par obs = la vraie obs x1, et n_envs=1 pour empecher la division de
    # sauver la mise : 393 216 transitions, soit 44 Go. Aucune machine de test n'a ca.
    huge = gym.spaces.Box(low=-1, high=1, shape=(30044,), dtype=np.float32)
    with pytest.raises(MemoryError, match="rollout buffer"):
        apply_rollout_n_steps({"n_steps": 393216}, 1, huge)


@pytest.mark.parametrize("bad", [0, -1, None, 1.5, True, "8192"])
def test_apply_rollout_n_steps_rejects_bad_totals(bad: Any) -> None:
    """Pas de valeur par defaut silencieuse : le `.get("n_steps", 10240)` d'origine en etait une."""
    from ai.train import apply_rollout_n_steps

    with pytest.raises((ValueError, TypeError)):
        apply_rollout_n_steps({"n_steps": bad}, 48, _space("box"))


def test_apply_rollout_n_steps_requires_the_key() -> None:
    from ai.train import apply_rollout_n_steps

    with pytest.raises(KeyError):
        apply_rollout_n_steps({}, 48, _space("box"))


# --- `batch_size` doit diviser le rollout REEL, pas celui demande en config -------------------

def test_every_profile_batch_size_divides_its_real_rollout() -> None:
    """Le rollout reel est `(n_steps // n_envs) * n_envs`, PAS `n_steps`.

    `apply_rollout_n_steps` ajuste `n_steps` au passage vectorise ; `batch_size` ne l'est pas et
    reste recopie tel quel. A `n_envs=48` le rollout tombe a 8160 et `batch_size: 1024` laisse un
    mini-lot tronque de 992 a chaque epoque — SB3 le signale, mais un avertissement au demarrage
    d'un run de plusieurs heures ne se lit pas.

    Le controle porte sur l'INVARIANT (`rollout % batch_size == 0`), jamais sur une valeur en
    dur : 1020 ne vaut que pour `n_envs=48`, et `n_envs=8` (rollout 8192) veut 1024. Figer un
    nombre ici creerait le defaut inverse sur la moitie des profils.
    """
    import json
    import os

    config_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
        "config/agents/ArmageddonAgent/ArmageddonAgent_training_config.json",
    )
    with open(config_path, encoding="utf-8-sig") as f:
        profiles = {k: v for k, v in json.load(f).items() if isinstance(v, dict)}

    assert profiles, "aucun profil lu : le controle ne regarderait rien"
    for name, profile in profiles.items():
        n_envs = profile["n_envs"]
        n_steps = profile["model_params"]["n_steps"]
        batch_size = profile["model_params"]["batch_size"]
        rollout = (n_steps // n_envs) * n_envs if n_envs > 1 else n_steps
        assert rollout % batch_size == 0, (
            f"profil '{name}' : n_envs={n_envs}, n_steps={n_steps} -> rollout reel {rollout}, "
            f"que batch_size={batch_size} ne divise pas (reste {rollout % batch_size}). "
            f"Plus grande valeur valide <= {batch_size} : "
            f"{max(d for d in range(1, batch_size + 1) if rollout % d == 0)}."
        )
