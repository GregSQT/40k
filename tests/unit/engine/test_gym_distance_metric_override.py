"""Métrique de distance imposée par la PHASE de training (`gym_distance_metric`).

POURQUOI CE RÉGLAGE. `distance_metric["move_gym"]`/`["charge_gym"]` valent `hex` alors que le
PvP résout en `euclidean` dès x5. Mesuré sur 162 états de move réels (scénario d'entraînement,
x5) : les deux pools diffèrent dans 100 % des états, de 11,4 % du pool en médiane, et le pool
euclidien est un sous-ensemble STRICT du pool hex dans 162/162 — l'agent n'est aveugle à aucune
destination légale, mais il apprend une frontière de portée hexagonale là où elle est circulaire,
et 72 % de l'écart tombe sur l'anneau extérieur du disque (l'anneau des entrées en charge).

Aligner coûte ×3,55 sur la construction du pool, et ce coût est STRUCTUREL : au sol le pool
euclidien est un champ géodésique qui encode le contournement d'obstacle. Testé — il n'est
radialement clos dans le pool hex que pour 21 % des états au sol (100 % en FLY, où 21.03 le fait
dégénérer en disque), donc aucun filtre du pool hex ne le reconstitue.

D'où le réglage PAR PHASE : curriculum en `hex`, phase finale en `euclidean` par `--append`.

Ce fichier verrouille les quatre propriétés qui rendent le réglage sûr :
  1. absent → comportement inchangé (opt-in strict) ;
  2. présent → il PREND, sur move ET sur charge (11.04 : la charge est un move) ;
  3. la RÉSOLUTION prime toujours : à x1 la géométrie reste hex quoi qu'impose la phase ;
  4. valeur invalide → erreur explicite à la CONSTRUCTION du moteur, pas au premier pool.
"""

from __future__ import annotations

from typing import Any, Dict

import pytest

from engine.combat_utils import GYM_DISTANCE_METRIC_KEY, gym_distance_metric_override
from engine.phase_handlers.charge_handlers import _charge_distance_metric
from engine.phase_handlers.movement_handlers import _move_distance_metric
from tests.unit.engine._config_helpers import build_engine_config


def _gs(*, ish: int, gym: bool, override: Any = None) -> Dict[str, Any]:
    """`game_state` minimal pour les SÉLECTEURS : ils ne lisent que ces trois clés."""
    gs: Dict[str, Any] = {"inches_to_subhex": ish, "gym_training_mode": gym}
    if override is not None:
        gs[GYM_DISTANCE_METRIC_KEY] = override
    return gs


def test_absent_override_leaves_both_selectors_untouched():
    """Opt-in STRICT : sans la clé, les sélecteurs rendent ce qu'ils rendaient avant."""
    from config_loader import get_config_loader

    metrics = get_config_loader().get_game_config()["distance_metric"]
    gs = _gs(ish=5, gym=True)
    assert _move_distance_metric(gs) == metrics["move_gym"]
    assert _charge_distance_metric(gs) == metrics["charge_gym"]
    # Prémisse : ce test ne vaut que si la config N'EST PAS déjà à la valeur qu'on veut imposer
    # plus bas — sinon il resterait vert avec un override qui ne fait rien.
    assert metrics["move_gym"] == "hex", (
        "prémisse : ce fichier suppose le défaut hex ; si la config passe en euclidean, "
        "les tests d'override ci-dessous doivent imposer 'hex' pour rester discriminants"
    )


@pytest.mark.parametrize("metric", ["euclidean", "hex"])
def test_override_drives_move_and_charge_together(metric: str):
    """La phase impose, les DEUX sélecteurs suivent — jamais l'un sans l'autre (11.04)."""
    gs = _gs(ish=5, gym=True, override=metric)
    assert _move_distance_metric(gs) == metric
    assert _charge_distance_metric(gs) == metric


def test_resolution_still_wins_at_x1():
    """À x1 la géométrie EST hex (`geometry_is_hex`) : aucune phase ne peut la contredire.

    Sans ce verrou, une phase `euclidean` mal recopiée dans un curriculum x1 mesurerait de
    l'euclidien sur des socles réduits à un point de grille — le défaut que `geometry_is_hex`
    existe pour rendre impossible.
    """
    gs = _gs(ish=1, gym=True, override="euclidean")
    assert _move_distance_metric(gs) == "hex"
    assert _charge_distance_metric(gs) == "hex"


def test_override_is_ignored_outside_gym():
    """PvP/replay lisent `move`/`charge` : un réglage d'ENTRAÎNEMENT n'a rien à y faire."""
    from config_loader import get_config_loader

    metrics = get_config_loader().get_game_config()["distance_metric"]
    gs = _gs(ish=5, gym=False, override="hex")
    assert _move_distance_metric(gs) == metrics["move"]
    assert _charge_distance_metric(gs) == metrics["charge"]
    assert metrics["move"] != "hex", (
        "prémisse : la config PvP doit différer de l'override, sinon le test ne discrimine rien"
    )


def test_invalid_value_raises_instead_of_falling_back():
    """Valeur invalide → erreur explicite. Un repli silencieux ferait tourner 47 h de training
    dans une métrique que personne n'a demandée (CLAUDE.md : jamais de défaut anti-erreur)."""
    with pytest.raises(ValueError, match=GYM_DISTANCE_METRIC_KEY):
        gym_distance_metric_override({GYM_DISTANCE_METRIC_KEY: "manhattan"})
    with pytest.raises(ValueError):
        _move_distance_metric(_gs(ish=5, gym=True, override="manhattan"))


def _engine_x5_with_phase_metric(metric: Any):
    """Moteur GYM à x5 dont la PHASE de training impose `metric` (None = phase muette).

    Passe par le vrai chemin de construction (`W40KEngine` → `game_state`), pas par un dict
    fabriqué : c'est le câblage training config → état qu'on veut vérifier, et un sélecteur
    correct branché sur rien ne corrige rien.
    """
    from unittest.mock import patch

    from engine.w40k_core import W40KEngine, load_weapon_damage_table  # noqa: F401
    from test_squad_obs_model_engagement import _config

    cfg = _config([(30, 60)], [(60, 60)], base_size=6)
    cfg["board"]["default"]["inches_to_subhex"] = 5
    cfg["game_rules"]["engagement_zone"] = 2
    cfg["controlled_player"] = 1  # exigé explicitement en mode training (aucun défaut implicite)
    if metric is not None:
        cfg["training_config"][GYM_DISTANCE_METRIC_KEY] = metric
    with patch("engine.w40k_core.load_weapon_damage_table", return_value={}), \
         patch.object(W40KEngine, "_build_reward_configs_for_current_units", return_value={}):
        eng = W40KEngine(config=build_engine_config(cfg), gym_training_mode=True)
    eng.reset()
    return eng


def _move_pool(eng) -> set:
    from engine.phase_handlers.movement_handlers import movement_build_valid_destinations_pool
    from engine.phase_handlers.shared_utils import build_enemy_adjacent_hexes

    gs = eng.game_state
    build_enemy_adjacent_hexes(gs, 1)
    return {(int(p[0]), int(p[1])) for p in movement_build_valid_destinations_pool(gs, "1")}


def test_the_override_actually_reaches_the_move_pool():
    """VERROU DE BOUT EN BOUT : la phase change le POOL, pas seulement le sélecteur.

    C'est le motif d'échec récurrent de ce dépôt — du code corrigé et testé que le chemin de
    production n'appelle jamais. Ici : `game_state` construit par le moteur, pool construit par
    la fonction du masque, et les deux métriques doivent produire des ensembles DIFFÉRENTS.
    """
    from engine.phase_handlers.movement_handlers import _move_distance_metric

    eng_hex = _engine_x5_with_phase_metric("hex")
    eng_euc = _engine_x5_with_phase_metric("euclidean")
    assert eng_hex.game_state[GYM_DISTANCE_METRIC_KEY] == "hex", "câblage config → game_state"
    assert _move_distance_metric(eng_euc.game_state) == "euclidean"

    pool_hex = _move_pool(eng_hex)
    pool_euc = _move_pool(eng_euc)
    assert pool_hex and pool_euc, "VERT VACANT : un pool vide ne compare rien"
    assert pool_euc < pool_hex, (
        f"le pool euclidien doit être un sous-ensemble STRICT du pool hex "
        f"(hex={len(pool_hex)}, euclid={len(pool_euc)})"
    )


def test_a_mute_phase_changes_nothing_end_to_end():
    """Contre-épreuve : sans la clé, le pool est celui d'aujourd'hui (`move_gym` = hex)."""
    assert _move_pool(_engine_x5_with_phase_metric(None)) == _move_pool(
        _engine_x5_with_phase_metric("hex")
    )


def test_a_mute_or_absent_phase_yields_no_override():
    """Les trois entrées légitimes du résolveur : pas de config, phase muette, phase explicite."""
    assert gym_distance_metric_override(None) is None, "pas de training config → pas d'override"
    assert gym_distance_metric_override({}) is None, "phase muette → pas d'override"
    assert gym_distance_metric_override({GYM_DISTANCE_METRIC_KEY: "euclidean"}) == "euclidean"


def test_engine_validates_the_phase_at_construction_time():
    """Le run doit MOURIR au lancement, pas au premier pool de move d'un worker vectorisé.

    Un `n_envs=48` qui lève dans un subprocess au bout de plusieurs minutes donne une trace
    illisible et un run à moitié démarré ; la validation à la construction est le seul endroit
    où l'erreur est encore rattachable à la phase qu'on vient de nommer.

    Ce test CONSTRUIT donc un moteur — il ne se contente pas d'appeler le résolveur. Dans sa
    première version il ne testait que le helper : remplacer l'appel validé de `w40k_core` par un
    `.get()` brut le laissait vert, c'est-à-dire qu'il ne verrouillait rien du comportement qu'il
    décrit (trouvé en review, 2026-08-04).
    """
    with pytest.raises(ValueError, match=GYM_DISTANCE_METRIC_KEY):
        _engine_x5_with_phase_metric("manhattan")

    # Contre-épreuve : une valeur VALIDE doit construire, et atteindre le game_state. Sans elle,
    # un moteur qui lèverait sur tout (ou qui ne construirait jamais) passerait le test ci-dessus.
    eng = _engine_x5_with_phase_metric("euclidean")
    assert eng.game_state[GYM_DISTANCE_METRIC_KEY] == "euclidean"
