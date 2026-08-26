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
        self.calls = 0

    def get_squad_action_mask_and_eligible_units(self, game_state):
        _ = game_state
        self.calls += 1
        empty_mask = np.zeros(4, dtype=bool)
        if not self.advanced:
            return empty_mask, []
        return empty_mask, [{"id": "u1"}]


class _RecordingObsBuilder:
    def __init__(self) -> None:
        self.squad_builds = 0
        self._obs_scratch: Optional[Dict[str, np.ndarray]] = None
        self._full_obs_scratch: Optional[Dict[str, np.ndarray]] = None

    def build_squad_observation(self, game_state, squad_id):
        _ = (game_state, squad_id)
        self.squad_builds += 1
        self._empty_squad_observation()
        return self._obs_scratch

    def build_squad_grid(self, game_state, squad_id, out=None):
        _ = (game_state, squad_id)
        if out is not None:
            out.fill(0)
            return out
        return np.zeros((1, 1, 1), dtype=np.float32)

    def _empty_squad_observation(self):
        if self._obs_scratch is None:
            self._obs_scratch = {"x": np.zeros(2, dtype=np.float32)}
        else:
            for arr in self._obs_scratch.values():
                arr.fill(0)
        return self._obs_scratch

    def _ensure_full_obs_scratch(self):
        assert self._obs_scratch is not None
        if self._full_obs_scratch is None:
            self._full_obs_scratch = dict(self._obs_scratch)
            self._full_obs_scratch["grid"] = np.zeros((1, 1, 1), dtype=np.float32)
        return self._full_obs_scratch


class _EngineStub:
    """Porte les VRAIES `_step_observation` / `_build_observation`, avec leurs dependances."""

    _step_observation = W40KEngine._step_observation
    _build_observation = W40KEngine._build_observation
    _build_observation_and_mask = W40KEngine._build_observation_and_mask
    # `_build_observation_and_mask` verifie desormais le masque qu'on lui transmet (no-op hors
    # `W40K_MASK_VERIFY=2`) : le vrai moteur le fait, la doublure doit donc le porter aussi.
    _verify_supplied_mask = W40KEngine._verify_supplied_mask
    # La transition « pool vide » passe par le helper de drainage : l'attribut doit exister pour
    # que l'appel aboutisse. Que ce chemin ne soit pas court-circuite est verrouille ailleurs, par
    # le balayage de source de tests/unit/engine/test_step_log_state_and_advance_drain.py.
    _advance_phase_and_drain = W40KEngine._advance_phase_and_drain

    def __init__(self, defer: bool) -> None:
        self.defer_observation = defer
        self.game_state: Dict[str, Any] = {"phase": "move", "turn": 1, "current_player": 1}
        self.state_manager = _RecordingStateManager()
        self.action_decoder = _PoolDecoder()
        self.obs_builder = _RecordingObsBuilder()
        # Aucun StepLogger : le drainage de `_advance_phase_and_drain` est alors un no-op strict,
        # ce que ce fichier veut — il mesure les mutations d'etat, pas le journal.
        self.step_logger = None
        # Les TROIS instantanes du meme point de passage, dans une seule trace ORDONNEE : la
        # doublure les nomme au lieu de les ecrire (leur contenu est verrouille par
        # test_step_log_state_and_advance_drain.py et test_step_log_effects_snapshot.py). Une
        # liste dit strictement plus que trois compteurs — elle porte aussi leur ordre.
        self.snapshot_calls: List[str] = []
        self.advance_actions: List[Dict[str, Any]] = []

    def _log_objective_control_snapshot_if_changed(self) -> None:
        self.snapshot_calls.append("objective")

    def _log_state_snapshot_if_turn_changed(self) -> None:
        self.snapshot_calls.append("state")

    def _log_effects_snapshot_if_changed(self) -> None:
        self.snapshot_calls.append("effects")

    def _process_squad_action(self, action: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        self.advance_actions.append(action)
        self.action_decoder.advanced = True
        return True, {"phase_complete": True}


def _mutations(engine: "_EngineStub") -> Dict[str, Any]:
    """Empreinte des EFFETS DE BORD — tout sauf le tenseur."""
    return {
        "boundary": engine.state_manager.boundary_calls,
        "snapshots": engine.snapshot_calls,
        "advances": engine.advance_actions,
    }


def test_deferral_replays_the_exact_same_mutations() -> None:
    """Le report ne doit RIEN retirer au pas de simulation, seulement a l'encodage.

    Verrou du defaut signale en revue : `advance_phase` sur pool vide est declenche DEPUIS
    `_build_observation`. Le sauter laissait le moteur rendre la main sur un etat non avance.
    """
    engine_full = _EngineStub(defer=False)
    engine_deferred = _EngineStub(defer=True)

    # `_step_observation` rend `(observation, masque_utilise)` : le masque de l'etat de sortie
    # remonte jusqu'a l'appelant de `step_with_mask` au lieu d'y etre reconstruit.
    obs_full, mask_full = engine_full._step_observation()
    obs_deferred, mask_deferred = engine_deferred._step_observation()

    assert _mutations(engine_full) == _mutations(engine_deferred)
    # ... et la mutation en question a bien eu lieu (sinon le test compare deux inactions).
    assert len(engine_full.advance_actions) == 1
    assert engine_full.advance_actions[0]["action"] == "advance_phase"
    assert engine_full.state_manager.boundary_calls == 1

    # Seul l'encodage differe.
    assert obs_full is not None and engine_full.obs_builder.squad_builds == 1
    assert obs_deferred is None and engine_deferred.obs_builder.squad_builds == 0
    # Le masque rendu ne depend PAS du report : seul l'encodage l'est. Sans cette assertion, un
    # report qui cesserait de rendre le masque passerait inapercu et l'appelant le reconstruirait
    # en silence — la deduplication disparaitrait sans qu'aucun test ne bouge.
    assert mask_full is not None and mask_deferred is not None
    assert np.array_equal(mask_full[0], mask_deferred[0])
    assert [u["id"] for u in mask_full[1]] == [u["id"] for u in mask_deferred[1]]


def test_boundary_checkpoint_runs_exactly_once_per_observation() -> None:
    """Regle 14.02 : un seul point de passage. Ni zero (VP perdus), ni deux (automate duplique)."""
    for defer in (False, True):
        engine = _EngineStub(defer=defer)
        for _ in range(3):
            engine._step_observation()
        assert engine.state_manager.boundary_calls == 3, f"defer={defer}"
        # Les trois instantanes du point de passage, dans l'ordre, une fois par observation.
        assert engine.snapshot_calls == ["objective", "state", "effects"] * 3, f"defer={defer}"


def test_precomputed_mask_is_consumed_instead_of_rebuilt() -> None:
    """`mask_and_eligible` doit REELLEMENT eviter la construction, pas seulement etre accepte.

    Un parametre ignore laisserait tout vert en supprimant zero appel : le gain annonce serait
    nul et rien ne le dirait. Ce test compare donc les deux modes sur le meme etat.
    """
    engine = _EngineStub(defer=False)
    engine.action_decoder.advanced = True  # pool non vide : on reste sur le chemin nominal
    mask = np.zeros(4, dtype=bool)
    mask[0] = True

    engine._build_observation(mask_and_eligible=(mask, [{"id": "u1"}]))
    assert engine.action_decoder.calls == 0, "le masque fourni n'a pas ete consomme"

    engine._build_observation()
    assert engine.action_decoder.calls == 1, "sans valeur fournie, le masque doit etre construit"


def test_every_observation_return_path_honours_the_tensor_flag() -> None:
    """Invariant de CONCEPTION : les deux fabriques locales sont les seuls producteurs de tenseur.

    Le drapeau `tensor` n'est teste qu'a l'interieur de `_zero_obs` / `_build_for_squad`. Cette
    economie n'est sure que si TOUT `return` du corps passe par l'une des deux : un futur
    `return self.obs_builder...` en direct rendrait un tenseur malgre le report, sans bruit.

    Le balayage porte sur `_build_observation_and_mask`, l'implementation (`_build_observation`
    n'en est plus que la facade). Chaque `return` y rend le couple `(observation, masque)` : c'est
    donc le PREMIER element qui doit venir d'une fabrique.
    """
    tree = ast.parse(textwrap.dedent(inspect.getsource(W40KEngine._build_observation_and_mask)))
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
        assert isinstance(value, ast.Tuple) and len(value.elts) == 2, (
            f"return qui n'est pas un couple (observation, masque) : "
            f"{ast.dump(value) if value else 'None'}"
        )
        observation = value.elts[0]
        assert (
            isinstance(observation, ast.Call)
            and isinstance(observation.func, ast.Name)
            and observation.func.id in factories
        ), f"observation rendue hors fabrique : {ast.dump(observation)}"
