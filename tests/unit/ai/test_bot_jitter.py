"""Tests du jitter d'episode (Bot_refactor.md §4.B / etape B).

Verrous :
- jitter=0 (facteur 1.0 partout) => poids nominaux exacts.
- Bornes respectees : chaque facteur dans [1-j, 1+j].
- Meme seed => memes facteurs.
- Seeds differentes => facteurs differents.
- Idempotence : apply_episode_jitter avec meme marqueur n'ecrase pas.
- Config source non mutee.
- Poids zero reste zero, negatif garde son signe.
- Identite de style non touchee par le jitter (seuls les coefficients bougent).
"""
from __future__ import annotations

import hashlib
from typing import Any, Tuple

import pytest

import ai.bot_doctrines as doctrines
from ai.bot_doctrines import (
    AttritionBot,
    DecapitationBot,
    RacerBot,
    ScorerBot,
    _apply_jitter_weights,
    get_jitter_config,
)


# ─── helpers ──────────────────────────────────────────────────────────────────

def _sha256_uniform(seed_str: str, suffix: str) -> float:
    h = hashlib.sha256(f"{seed_str}:{suffix}".encode("utf-8")).hexdigest()
    return int(h[:8], 16) / float(0xFFFFFFFF)


def _compute_movement_factors(global_seed: int, env_rank: int, episode_index: int,
                               bot_key: str, j_move: float) -> Tuple[float, ...]:
    """Reproduit le calcul de env_wrappers — utile pour tester la coherence seed."""
    base_seed = f"{global_seed}:{env_rank}:{episode_index}:jitter:{bot_key}"
    return tuple(
        1.0 + j_move * (2.0 * _sha256_uniform(base_seed, str(i)) - 1.0)
        for i in range(6)
    )


def _compute_behavior_factor(global_seed: int, env_rank: int, episode_index: int,
                              bot_key: str, j_beh: float) -> float:
    base_seed = f"{global_seed}:{env_rank}:{episode_index}:jitter:{bot_key}"
    return 1.0 + j_beh * (2.0 * _sha256_uniform(base_seed, "beh") - 1.0)


def _unit(sid: str = "u1", player: int = 1) -> dict:
    return {"id": sid, "player": player}


def _gs() -> dict:
    return {
        "turn": 1, "episode_number": 1,
        "config": {"game_rules": {"max_turns": 5}},
        "victory_points": {1: 0.0, 2: 0.0},
        "units": [], "units_cache": {}, "objectives": None,
    }


def _patch_basics(monkeypatch: pytest.MonkeyPatch, key: str,
                  weights: Tuple[float, ...] = (1.0, -0.5, 0.0, 0.8, 1.5, 2.0)) -> None:
    monkeypatch.setattr(doctrines, "load_style_profile", lambda k: {
        "late_game": 0.0, "preservation": 0.0,
        "persistence": 0.0, "focus_shared": False,
    })
    monkeypatch.setattr(doctrines, "load_doctrine_weights", lambda k: weights)
    monkeypatch.setattr(doctrines, "_state_overrides_cfg", lambda: {})
    monkeypatch.setattr(doctrines, "_late_game_transform_cfg",
                        lambda: {"push_gain": 0.5, "protect_gain": 0.5})
    monkeypatch.setattr(doctrines, "is_unit_at_or_below_half_strength",
                        lambda sid, gs: False)
    monkeypatch.setattr(doctrines, "is_unit_alive", lambda sid, gs: True)


# ─── _apply_jitter_weights : invariants fondamentaux ─────────────────────────

class TestApplyJitterWeights:
    def test_all_ones_is_identity(self) -> None:
        """Facteurs 1.0 partout => vecteur inchange."""
        weights = (1.3, -0.35, 0.0, 0.9, 2.5, 1.0)
        factors = (1.0, 1.0, 1.0, 1.0, 1.0, 1.0)
        assert _apply_jitter_weights(weights, factors) == weights

    def test_zero_weight_stays_zero(self) -> None:
        """w=0 reste 0 quel que soit le facteur."""
        weights = (1.0, 0.0, 0.5, -0.3, 0.0, 2.0)
        factors = (1.1, 1.2, 0.9, 1.05, 1.3, 0.8)
        result = _apply_jitter_weights(weights, factors)
        assert result[1] == 0.0
        assert result[4] == 0.0

    def test_negative_weight_keeps_sign(self) -> None:
        """Poids negatif garde son signe (facteur positif => resultat negatif)."""
        weights = (1.0, -0.35, 0.0, 0.8, 1.5, 1.0)
        factors = (1.1, 1.08, 1.0, 0.92, 1.05, 0.95)
        result = _apply_jitter_weights(weights, factors)
        assert result[1] < 0.0, "w_enemy negatif doit rester negatif"

    def test_factor_amplifies_correctly(self) -> None:
        """Verification numerique : 0.5 * 1.2 = 0.6."""
        weights = (0.5, 1.0, 0.0, 0.0, 0.0, 0.0)
        factors = (1.2, 1.0, 1.0, 1.0, 1.0, 1.0)
        result = _apply_jitter_weights(weights, factors)
        assert abs(result[0] - 0.6) < 1e-9


# ─── apply_episode_jitter : idempotence ───────────────────────────────────────

class TestApplyEpisodeJitter:
    def test_idempotent_same_marker(self) -> None:
        """Appel avec le meme marqueur ne modifie pas les facteurs deja stockes."""
        bot = RacerBot()
        factors1 = (1.05, 0.97, 1.03, 1.01, 0.98, 1.07)
        factors2 = (0.90, 1.10, 0.95, 1.15, 1.02, 0.88)  # differents
        marker = ("seed1", 0, 42)

        bot.apply_episode_jitter(factors1, 1.03, marker)
        bot.apply_episode_jitter(factors2, 0.95, marker)  # meme marqueur => ignore

        assert bot._jitter_movement == factors1, "Idempotence : premier appel gagne"
        assert bot._jitter_behavior == 1.03

    def test_new_marker_overwrites(self) -> None:
        """Marqueur different => mise a jour."""
        bot = RacerBot()
        factors1 = (1.05, 0.97, 1.03, 1.01, 0.98, 1.07)
        factors2 = (0.90, 1.10, 0.95, 1.15, 1.02, 0.88)

        bot.apply_episode_jitter(factors1, 1.03, ("seed1", 0, 0))
        bot.apply_episode_jitter(factors2, 0.95, ("seed1", 0, 1))  # episode suivant

        assert bot._jitter_movement == factors2, "Nouveau marqueur doit etre accepte"
        assert bot._jitter_behavior == 0.95

    def test_default_factors_are_identity(self) -> None:
        """Instance fraiche : facteurs neutres (1.0 partout)."""
        bot = RacerBot()
        assert all(f == 1.0 for f in bot._jitter_movement)
        assert bot._jitter_behavior == 1.0
        assert bot._jitter_episode_marker is None


# ─── movement_weights avec jitter ─────────────────────────────────────────────

class TestMovementWeightsJitter:
    def test_unit_factors_reproduce_weights(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Jitter de 1.0 partout => movement_weights == load_doctrine_weights."""
        base_weights = (1.3, 0.2, 0.0, 0.0, 4.0, 3.0)
        _patch_basics(monkeypatch, "racer", base_weights)
        bot = RacerBot()
        # Facteurs par defaut = 1.0 => identite
        result = bot.movement_weights(_unit(), _gs())
        assert result == base_weights

    def test_nonunit_factors_change_weights(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Facteurs differents de 1.0 modifient les poids nominaux."""
        base_weights = (1.3, 0.2, 0.0, 0.0, 4.0, 3.0)
        _patch_basics(monkeypatch, "racer", base_weights)
        bot = RacerBot()
        factors = (1.1, 0.9, 1.0, 1.0, 1.0, 1.05)
        bot.apply_episode_jitter(factors, 1.0, ("seed", 0, 0))
        result = bot.movement_weights(_unit(), _gs())
        assert result != base_weights, "Facteurs non-unitaires doivent modifier les poids"
        assert abs(result[0] - 1.3 * 1.1) < 1e-9
        assert abs(result[1] - 0.2 * 0.9) < 1e-9
        assert result[2] == 0.0, "Zero reste zero meme avec facteur non-unitaire"

    def test_zero_weight_stays_zero_in_movement(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Poids zero dans le vecteur de mouvement reste zero apres jitter."""
        base_weights = (1.0, -0.5, 0.0, 0.8, 1.5, 2.0)
        _patch_basics(monkeypatch, "attrition", base_weights)
        bot = AttritionBot()
        factors = (1.08, 1.05, 1.15, 0.93, 1.02, 0.97)
        bot.apply_episode_jitter(factors, 1.0, ("seed", 0, 0))
        result = bot.movement_weights(_unit(), _gs())
        assert result[2] == 0.0

    def test_negative_weight_keeps_sign_in_movement(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Poids negatif reste negatif apres jitter."""
        base_weights = (1.0, -0.5, 0.0, 0.8, 1.5, 2.0)
        _patch_basics(monkeypatch, "attrition", base_weights)
        bot = AttritionBot()
        factors = (1.0, 1.08, 1.0, 1.0, 1.0, 1.0)
        bot.apply_episode_jitter(factors, 1.0, ("seed", 0, 0))
        result = bot.movement_weights(_unit(), _gs())
        assert result[1] < 0.0, "Poids negatif doit rester negatif"


# ─── Bornes [1-j, 1+j] ────────────────────────────────────────────────────────

class TestJitterBounds:
    """Les facteurs SHA256 doivent etre dans [1-j, 1+j] pour j_move et j_beh."""

    @pytest.mark.parametrize("global_seed,env_rank,episode_index", [
        (42, 0, 0), (42, 1, 0), (42, 0, 1), (1337, 3, 100),
    ])
    def test_movement_factors_in_bounds(
        self, global_seed: int, env_rank: int, episode_index: int
    ) -> None:
        j = 0.10
        factors = _compute_movement_factors(global_seed, env_rank, episode_index, "racer", j)
        for i, f in enumerate(factors):
            assert 1.0 - j <= f <= 1.0 + j + 1e-9, (
                f"Facteur {i} hors bornes : {f} (j={j})"
            )

    @pytest.mark.parametrize("global_seed,env_rank,episode_index", [
        (42, 0, 0), (999, 2, 50),
    ])
    def test_behavior_factor_in_bounds(
        self, global_seed: int, env_rank: int, episode_index: int
    ) -> None:
        j = 0.05
        f = _compute_behavior_factor(global_seed, env_rank, episode_index, "attrition", j)
        assert 1.0 - j <= f <= 1.0 + j + 1e-9


# ─── Determinisme SHA256 : meme seed => memes facteurs ────────────────────────

class TestJitterDeterminism:
    def test_same_seed_same_factors(self) -> None:
        """Seed identique produit des facteurs identiques (reproductibilite)."""
        f1 = _compute_movement_factors(42, 0, 7, "endgame", 0.10)
        f2 = _compute_movement_factors(42, 0, 7, "endgame", 0.10)
        assert f1 == f2

    def test_different_episode_different_factors(self) -> None:
        """Episodes differents produisent des facteurs differents."""
        f1 = _compute_movement_factors(42, 0, 7, "racer", 0.10)
        f2 = _compute_movement_factors(42, 0, 8, "racer", 0.10)
        assert f1 != f2, "Episodes differents doivent avoir des facteurs differents"

    def test_different_rank_different_factors(self) -> None:
        """Rangs differents produisent des facteurs differents (parallelisme)."""
        f1 = _compute_movement_factors(42, 0, 7, "racer", 0.10)
        f2 = _compute_movement_factors(42, 1, 7, "racer", 0.10)
        assert f1 != f2

    def test_different_style_different_factors(self) -> None:
        """Cles de style differentes => facteurs differents (styles isoles)."""
        f1 = _compute_movement_factors(42, 0, 7, "racer", 0.10)
        f2 = _compute_movement_factors(42, 0, 7, "attrition", 0.10)
        assert f1 != f2


# ─── Config source non mutee ──────────────────────────────────────────────────

def test_jitter_config_not_mutated() -> None:
    """get_jitter_config() retourne un dict independant a chaque appel."""
    cfg1 = get_jitter_config()
    cfg1["movement_weight_jitter"] = 9999.0  # on mute la copie
    cfg2 = get_jitter_config()
    assert cfg2["movement_weight_jitter"] != 9999.0, (
        "La config source ne doit pas etre mutee par le consommateur"
    )


# ─── Identite de style preservee ──────────────────────────────────────────────

def test_style_identity_preserved(monkeypatch: pytest.MonkeyPatch) -> None:
    """Le jitter ne change pas quel bot est utilise — seuls les coefficients varient."""
    base_weights = (1.3, 0.2, 0.0, 0.0, 4.0, 3.0)
    _patch_basics(monkeypatch, "racer", base_weights)
    bot = RacerBot()

    # Sans jitter : les poids de base
    result_no_jitter = bot.movement_weights(_unit(), _gs())
    assert result_no_jitter == base_weights

    # Avec jitter : toujours des poids RACER (meme vecteur source * facteurs)
    factors = (1.05, 0.95, 1.0, 1.02, 0.98, 1.03)
    bot.apply_episode_jitter(factors, 1.0, ("seed", 0, 42))
    result_jittered = bot.movement_weights(_unit(), _gs())

    # Chaque composant doit etre le produit w_base * facteur
    for i, (w, f) in enumerate(zip(base_weights, factors)):
        assert abs(result_jittered[i] - w * f) < 1e-9, (
            f"Composant {i}: attendu {w*f}, obtenu {result_jittered[i]}"
        )


# ─── Verrou T4 : mutation : facteur non-neutre detectee ───────────────────────

def test_mutation_jitter_verrou(monkeypatch: pytest.MonkeyPatch) -> None:
    """Preuve rouge/vert : un facteur ≠ 1.0 modifie le resultat.

    1. Baseline  : factors=(1,1,1,1,1,1) => poids nominaux [vert]
    2. Mutant    : factors=(1.15,...) => poids differents [rouge si baseline]
    3. Retabli   : factors=(1,1,1,1,1,1) => poids nominaux [vert]
    """
    base_weights = (0.7, 0.2, 0.8, 0.6, 1.5, 1.0)
    _patch_basics(monkeypatch, "attrition", base_weights)
    bot = AttritionBot()

    # Baseline
    result_base = bot.movement_weights(_unit(), _gs())
    assert result_base == base_weights, "Baseline : poids nominaux attendus"

    # Mutant
    mutant_factors = (1.15, 0.92, 1.07, 0.98, 1.03, 1.10)
    bot.apply_episode_jitter(mutant_factors, 1.0, ("seed", 0, 0))
    result_mutant = bot.movement_weights(_unit(), _gs())
    assert result_mutant != base_weights, "Mutant (facteurs ≠ 1) doit changer les poids"

    # Retabli
    neutral_factors = (1.0, 1.0, 1.0, 1.0, 1.0, 1.0)
    bot.apply_episode_jitter(neutral_factors, 1.0, ("seed", 0, 1))  # marqueur different
    result_restored = bot.movement_weights(_unit(), _gs())
    assert result_restored == base_weights, "Retabli : facteurs neutres => poids nominaux"
