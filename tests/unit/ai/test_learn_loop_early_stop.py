#!/usr/bin/env python3
"""Un callback qui rend `False` termine le RUN, pas seulement la tranche de `learn()`.

`train_with_scenario_rotation` budgète en épisodes en enchaînant des `learn()` courts. SB3
n'expose le refus d'un callback que comme SORTIE de `learn()` : la boucle ne le voyait pas et
rappelait `learn()` jusqu'à la cible d'épisodes. Quatre callbacks rendent `False` sur ce chemin
(budget d'épisodes, early-stop bot, budget exploiteur confirmé ou censuré, seuil de pool
confirmé) et tous les quatre demandent l'arrêt du run.

Pire cas mesurable : une fois l'exploiteur censuré, `_on_step` rend `False` dès le premier pas de
chaque tranche — chaque itération n'avançait que de `n_envs` pas en repayant `_setup_learn`.

Deux verrous : le comportement du porteur de drapeau (`StopAwareCallbackList`), et le fait que la
boucle de production le consulte. La boucle elle-même demande un run complet (config, env,
modèle) pour être jouée : son contrat est lu dans l'AST, comme celui de la fermeture du pool des
sondes dans `test_probe_eval_pool_lifetime.py`.
"""

import ast
import functools
import sys
from pathlib import Path
from unittest.mock import MagicMock

from stable_baselines3.common.callbacks import BaseCallback

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from ai.training_callbacks import StopAwareCallbackList  # noqa: E402


class _RefusingCallback(BaseCallback):
    """Rend `False` au n-ième appel — `n_calls` est incrémenté par `BaseCallback.on_step`."""

    def __init__(self, refuse_at_call: int):
        super().__init__()
        self.refuse_at_call = refuse_at_call

    def _on_step(self) -> bool:
        return self.n_calls != self.refuse_at_call


class _CountingCallback(BaseCallback):
    """Accepte toujours, et compte ses appels."""

    def _on_step(self) -> bool:
        return True


def _wired(*callbacks: BaseCallback) -> StopAwareCallbackList:
    model = MagicMock()
    model.num_timesteps = 0
    callback_list = StopAwareCallbackList(list(callbacks))
    callback_list.init_callback(model)
    return callback_list


# ── Le drapeau ──────────────────────────────────────────────────────────────────────────────


def test_no_stop_requested_while_every_callback_agrees():
    """Sans refus, le drapeau reste baissé : une tranche consommée n'arrête pas le run."""
    callback_list = _wired(_CountingCallback(), _CountingCallback())

    assert all(callback_list.on_step() for _ in range(5))
    assert callback_list.stop_requested is False


def test_a_refusal_raises_the_flag_and_propagates():
    """Le refus est rendu à SB3 (il coupe la tranche) ET mémorisé (il coupe le run)."""
    callback_list = _wired(_RefusingCallback(refuse_at_call=1))

    assert callback_list.on_step() is False
    assert callback_list.stop_requested is True


def test_every_callback_is_still_polled_on_a_refusal():
    """Le refus ne court-circuite pas les autres callbacks : `CallbackList` les appelle tous.

    Les métriques et l'affichage sont dans cette liste ; les court-circuiter ferait diverger
    le compte d'épisodes du pas où l'arrêt est décidé.
    """
    counter = _CountingCallback()
    callback_list = _wired(_RefusingCallback(refuse_at_call=1), counter)

    callback_list.on_step()

    assert counter.n_calls == 1


def test_the_flag_survives_the_learn_chunk_boundary():
    """SB3 appaire `on_training_start`/`on_training_end` autour de CHAQUE `learn()`.

    Le drapeau est justement lu APRÈS cette frontière : s'il y était remis à zéro, la boucle
    verrait toujours « pas d'arrêt demandé ».
    """
    callback_list = _wired(_RefusingCallback(refuse_at_call=1))

    callback_list.on_step()
    callback_list.on_training_end()
    callback_list.on_training_start({}, {})

    assert callback_list.stop_requested is True


# ── La boucle de production ─────────────────────────────────────────────────────────────────


def _while_calls_learn(node: ast.While) -> bool:
    return any(
        isinstance(call.func, ast.Attribute) and call.func.attr == "learn"
        for stmt in node.body
        for call in ast.walk(stmt)
        if isinstance(call, ast.Call)
    )


@functools.cache
def _rotation_learn_loop() -> ast.While:
    tree = ast.parse((PROJECT_ROOT / "ai" / "train.py").read_text(encoding="utf-8"))
    # `train_with_scenario_rotation` est précédée de trois `@overload` : l'implémentation est la
    # DERNIÈRE définition du nom.
    definitions = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "train_with_scenario_rotation"
    ]
    assert definitions, "`train_with_scenario_rotation` introuvable dans ai/train.py"
    loops = [
        node
        for node in ast.walk(definitions[-1])
        if isinstance(node, ast.While) and _while_calls_learn(node)
    ]
    assert len(loops) == 1, (
        f"attendu UNE boucle `while` appelant `learn()` dans `train_with_scenario_rotation`, "
        f"trouvé {len(loops)}"
    )
    return loops[0]


def test_the_learn_loop_breaks_on_the_stop_flag():
    """La boucle sort quand un callback a demandé l'arrêt, après l'appel à `learn()`.

    Sans ce `break`, un seuil confirmé à 50 000 épisodes sur un run de 200 000 ne stoppait rien.
    """
    loop = _rotation_learn_loop()

    learn_positions = [
        index
        for index, stmt in enumerate(loop.body)
        for call in ast.walk(stmt)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and call.func.attr == "learn"
    ]
    guards = [
        (index, stmt)
        for index, stmt in enumerate(loop.body)
        if isinstance(stmt, ast.If)
        and any(
            isinstance(node, ast.Attribute) and node.attr == "stop_requested"
            for node in ast.walk(stmt.test)
        )
        and any(isinstance(node, ast.Break) for node in ast.walk(stmt))
    ]

    assert guards, (
        "aucun `if <callbacks>.stop_requested: ... break` dans le corps de la boucle — un "
        "callback qui rend False n'interrompt alors que la tranche courante de `learn()`"
    )
    assert min(index for index, _ in guards) > max(learn_positions), (
        "le drapeau doit être consulté APRÈS `model.learn()` : lu avant, il ne peut pas voir "
        "le refus rendu pendant la tranche qui vient de tourner"
    )


def test_the_early_stop_is_only_announced_when_the_target_is_missed():
    """Le message d'arrêt anticipé est gardé par une comparaison à la cible d'épisodes.

    `EpisodeTerminationCallback` rend `False` au budget ATTEINT (`disable_early_stopping=False`) :
    le drapeau se lève donc à la fin de CHAQUE run nominal. Annoncé sans garde, tout run réussi se
    terminerait sur « 🛑 Arret anticipe demande par un callback a 10000 episodes (cible 10000) ».
    """
    guard = next(
        stmt
        for stmt in _rotation_learn_loop().body
        if isinstance(stmt, ast.If)
        and any(
            isinstance(node, ast.Attribute) and node.attr == "stop_requested"
            for node in ast.walk(stmt.test)
        )
    )
    announcements = [
        node
        for node in ast.walk(guard)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "chunk_log"
    ]
    assert announcements, "l'arrêt anticipé doit être annoncé dans le journal du run"

    guarded_by_the_target = [
        node
        for node in ast.walk(guard)
        if isinstance(node, ast.If)
        and any(
            isinstance(name, ast.Name) and name.id == "target_episode_count"
            for name in ast.walk(node.test)
        )
        and any(announcement in ast.walk(node) for announcement in announcements)
    ]
    assert guarded_by_the_target, (
        "le message d'arrêt anticipé n'est pas gardé par une comparaison à "
        "`target_episode_count` — il s'afficherait aussi à la fin de tout run nominal"
    )


def test_the_learn_loop_uses_a_stop_aware_callback_list():
    """Le drapeau lu par la boucle est bien celui passé à `learn()` comme `callback=`."""
    loop = _rotation_learn_loop()

    learn_call = next(
        call
        for stmt in loop.body
        for call in ast.walk(stmt)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and call.func.attr == "learn"
    )
    callback_argument = next(
        keyword.value for keyword in learn_call.keywords if keyword.arg == "callback"
    )
    assert isinstance(callback_argument, ast.Name)

    guard_names = {
        node.value.id
        for stmt in loop.body
        if isinstance(stmt, ast.If)
        for node in ast.walk(stmt.test)
        if isinstance(node, ast.Attribute)
        and node.attr == "stop_requested"
        and isinstance(node.value, ast.Name)
    }
    assert callback_argument.id in guard_names, (
        f"la boucle lit `stop_requested` sur {sorted(guard_names)} alors que `learn()` reçoit "
        f"`{callback_argument.id}`"
    )
