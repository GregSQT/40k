"""Report d'observation dans `W40KEngine.step` — contrat de `_step_observation`.

Optimisation d'entrainement : un step gym du wrapper enchaine plusieurs steps moteur mais PPO
ne lit que la derniere observation, donc seule celle-la est encodee.

Le piege que ces tests verrouillent : `_build_observation` n'est PAS un pur constructeur de
tenseur. Elle mute l'etat — checkpoint de controle d'objectif (regle 14.02), journal VP, et
surtout `advance_phase` quand le pool d'activation est vide. Une premiere version du report
court-circuitait l'appel : le moteur rendait alors la main sur un etat NON avance, `terminated`
etait calcule dessus et le wrapper compensait par un WAIT force — steps et journal decales,
sans qu'aucune observation soit visiblement fausse.

Le report traverse donc la fonction avec `tensor=False`. Ce que ces tests exigent :
1. la sequence de mutations est rigoureusement la meme dans les deux modes ;
2. aucun point de sortie ne peut oublier le drapeau (invariant de conception, verifie par AST).
"""

import ast
import inspect
import textwrap
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from engine.w40k_core import W40KEngine


class _RecordingStateManager:
    def __init__(self) -> None:
        self.boundary_calls = 0

    def refresh_objective_control_on_boundary(self, game_state: Dict[str, Any]) -> bool:
        _ = game_state
        self.boundary_calls += 1
        return True


class _PoolDecoder:
    """Decoder qui rend un pool VIDE puis, apres `advance_phase`, un pool non vide.

    C'est la branche interessante : celle ou `_build_observation` MUTE l'etat.
    """

    def __init__(self) -> None:
        self.advanced = False

    def get_squad_action_mask_and_eligible_units(self, game_state):
        _ = game_state
        empty_mask = np.zeros(4, dtype=bool)
        if not self.advanced:
            return empty_mask, []
        return empty_mask, [{"id": "u1"}]


class _RecordingObsBuilder:
    def __init__(self) -> None:
        self.squad_builds = 0

    def build_squad_observation(self, game_state, squad_id):
        _ = (game_state, squad_id)
        self.squad_builds += 1
        return {"x": np.zeros(2, dtype=np.float32)}

    def build_squad_grid(self, game_state, squad_id):
        _ = (game_state, squad_id)
        return np.zeros((1, 1, 1), dtype=np.float32)

    def _empty_squad_observation(self):
        return {"x": np.zeros(2, dtype=np.float32)}


class _EngineStub:
    """Porte les VRAIES `_step_observation` / `_build_observation`, avec leurs dependances."""

    _step_observation = W40KEngine._step_observation
    _build_observation = W40KEngine._build_observation

    def __init__(self, defer: bool) -> None:
        self.defer_observation = defer
        self.game_state: Dict[str, Any] = {"phase": "move", "turn": 1, "current_player": 1}
        self.state_manager = _RecordingStateManager()
        self.action_decoder = _PoolDecoder()
        self.obs_builder = _RecordingObsBuilder()
        self.snapshot_logs = 0
        self.advance_actions: List[Dict[str, Any]] = []

    def _log_objective_control_snapshot_if_changed(self) -> None:
        self.snapshot_logs += 1

    def _process_squad_action(self, action: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        self.advance_actions.append(action)
        self.action_decoder.advanced = True
        return True, {"phase_complete": True}


def _mutations(engine: "_EngineStub") -> Dict[str, Any]:
    """Empreinte des EFFETS DE BORD — tout sauf le tenseur."""
    return {
        "boundary": engine.state_manager.boundary_calls,
        "snapshots": engine.snapshot_logs,
        "advances": engine.advance_actions,
    }


def test_deferral_replays_the_exact_same_mutations() -> None:
    """Le report ne doit RIEN retirer au pas de simulation, seulement a l'encodage.

    Verrou du defaut signale en revue : `advance_phase` sur pool vide est declenche DEPUIS
    `_build_observation`. Le sauter laissait le moteur rendre la main sur un etat non avance.
    """
    engine_full = _EngineStub(defer=False)
    engine_deferred = _EngineStub(defer=True)

    obs_full = engine_full._step_observation()
    obs_deferred = engine_deferred._step_observation()

    assert _mutations(engine_full) == _mutations(engine_deferred)
    # ... et la mutation en question a bien eu lieu (sinon le test compare deux inactions).
    assert len(engine_full.advance_actions) == 1
    assert engine_full.advance_actions[0]["action"] == "advance_phase"
    assert engine_full.state_manager.boundary_calls == 1

    # Seul l'encodage differe.
    assert obs_full is not None and engine_full.obs_builder.squad_builds == 1
    assert obs_deferred is None and engine_deferred.obs_builder.squad_builds == 0


def test_boundary_checkpoint_runs_exactly_once_per_observation() -> None:
    """Regle 14.02 : un seul point de passage. Ni zero (VP perdus), ni deux (automate duplique)."""
    for defer in (False, True):
        engine = _EngineStub(defer=defer)
        for _ in range(3):
            engine._step_observation()
        assert engine.state_manager.boundary_calls == 3, f"defer={defer}"
        assert engine.snapshot_logs == 3, f"defer={defer}"


def test_every_observation_return_path_honours_the_tensor_flag() -> None:
    """Invariant de CONCEPTION : les deux fabriques locales sont les seuls producteurs de tenseur.

    Le drapeau `tensor` n'est teste qu'a l'interieur de `_zero_obs` / `_build_for_squad`. Cette
    economie n'est sure que si TOUT `return` du corps passe par l'une des deux : un futur
    `return self.obs_builder...` en direct rendrait un tenseur malgre le report, sans bruit.
    """
    tree = ast.parse(textwrap.dedent(inspect.getsource(W40KEngine._build_observation)))
    fn = tree.body[0]
    assert isinstance(fn, ast.FunctionDef)
    factories = {"_zero_obs", "_build_for_squad"}
    nested = {n.name for n in fn.body if isinstance(n, ast.FunctionDef)}
    assert nested == factories, f"fabriques locales inattendues : {nested}"

    body_returns: List[Optional[ast.expr]] = [
        sub.value
        for node in fn.body
        if not isinstance(node, ast.FunctionDef)
        for sub in ast.walk(node)
        if isinstance(sub, ast.Return)
    ]
    assert body_returns, "aucun return detecte : le balayage AST est casse"
    for value in body_returns:
        assert (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Name)
            and value.func.id in factories
        ), f"return hors fabrique : {ast.dump(value) if value else 'None'}"
