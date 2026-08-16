"""Tests de `late_game_state` et de la transformation de poids late_game (Bot_refactor.md §4.A.1).

Verrous :
- D4 : gain=0 → identite exacte du vecteur de poids.
- Bascule endgame au tour 3 sur une bataille de 5 tours (comportement INCHANGE par rapport
  a l'ancien PUSH_LAST_TURNS=3).
- protect_lead renforce l'evitement d'`endgame` (|w_enemy| effectif ≥ base, signe conserve).
"""
from __future__ import annotations

from typing import Any, Dict

import pytest

import ai.bot_doctrines as doctrines
from ai.bot_doctrines import (
    EndgameBot,
    _apply_late_game_transform,
    late_game_state,
    load_doctrine_weights,
    load_style_profile,
)
from shared.data_validation import ConfigurationError


# ─── helpers ──────────────────────────────────────────────────────────────────

def _gs(*, turn: int, limit: int, vp1: float = 0.0, vp2: float = 0.0) -> Dict[str, Any]:
    """Game state minimal : tour, limite, VP."""
    return {
        "turn": turn,
        "config": {"game_rules": {"max_turns": limit}},
        "victory_points": {1: vp1, 2: vp2},
    }


# ─── late_game_state ──────────────────────────────────────────────────────────

class TestLateGameState:
    def test_normal_early_balanced(self) -> None:
        """Tour 1/5, scores equivalents → normal."""
        assert late_game_state(_gs(turn=1, limit=5), 1) == "normal"

    def test_desperate_push_last_3_turns_serre(self) -> None:
        """Tour 3/5, vp_diff < 15 → desperate_push."""
        assert late_game_state(_gs(turn=3, limit=5, vp1=5.0, vp2=5.0), 1) == "desperate_push"

    def test_desperate_push_turn_4(self) -> None:
        """Tour 4/5, ecart serre → desperate_push."""
        assert late_game_state(_gs(turn=4, limit=5), 1) == "desperate_push"

    def test_desperate_push_last_turn(self) -> None:
        """Tour 5/5, ecart serre → desperate_push."""
        assert late_game_state(_gs(turn=5, limit=5), 1) == "desperate_push"

    def test_not_desperate_turn_2(self) -> None:
        """Tour 2/5, ecart serre → normal (pas encore la fenetre des 3 derniers tours)."""
        assert late_game_state(_gs(turn=2, limit=5), 1) == "normal"

    def test_protect_lead_dominant(self) -> None:
        """Avance de 15+ → protect_lead, independamment du tour."""
        assert late_game_state(_gs(turn=1, limit=5, vp1=20.0, vp2=0.0), 1) == "protect_lead"

    def test_protect_lead_beats_desperate_push(self) -> None:
        """Avance >= 15 meme en fin de partie → protect_lead prime sur desperate_push."""
        assert late_game_state(_gs(turn=4, limit=5, vp1=30.0, vp2=10.0), 1) == "protect_lead"

    def test_desperate_push_exact_margin_boundary(self) -> None:
        """vp_diff = 14.9 (< 15) en tour 3/5 → desperate_push."""
        assert late_game_state(_gs(turn=3, limit=5, vp1=14.9, vp2=0.0), 1) == "desperate_push"

    def test_protect_lead_exact_margin(self) -> None:
        """vp_diff = 15.0 (>= 15) → protect_lead."""
        assert late_game_state(_gs(turn=3, limit=5, vp1=15.0, vp2=0.0), 1) == "protect_lead"

    def test_opponent_perspective(self) -> None:
        """Joueur 2 : avance de joueur 2 = protect_lead pour player=2."""
        gs = _gs(turn=1, limit=5, vp1=0.0, vp2=20.0)
        assert late_game_state(gs, 2) == "protect_lead"
        assert late_game_state(gs, 1) == "normal"

    def test_unlimited_turns_no_desperate_push(self) -> None:
        """Bataille illimitee (Endless Duty) : pas de desperate_push quand aucun limit."""
        gs: Dict[str, Any] = {
            "turn": 10, "unlimited_turns": True,
            "config": {"game_rules": {"max_turns": 5}},
            "victory_points": {1: 0.0, 2: 0.0},
        }
        assert late_game_state(gs, 1) == "normal"

    @pytest.mark.parametrize("player", [1, 2])
    def test_missing_active_player_key_raises(self, player: int) -> None:
        """Clé du joueur actif absente de victory_points → ConfigurationError sur la bonne clé."""
        gs = _gs(turn=1, limit=5)
        gs["victory_points"] = {3 - player: 0.0}
        with pytest.raises(ConfigurationError, match=rf"Required key '{player}'"):
            late_game_state(gs, player)

    @pytest.mark.parametrize("player", [1, 2])
    def test_missing_opponent_key_raises(self, player: int) -> None:
        """Clé du joueur adverse absente de victory_points → ConfigurationError sur la bonne clé."""
        opponent = 3 - player
        gs = _gs(turn=1, limit=5)
        gs["victory_points"] = {player: 0.0}
        with pytest.raises(ConfigurationError, match=rf"Required key '{opponent}'"):
            late_game_state(gs, player)


# ─── Bascule EndgameBot — toujours au tour 3 sur 5 tours ───────────────────────

class TestEndgameBotBascule:
    """Verrou de non-regression : la bascule d'endgame doit survenir au meme tour qu'avant
    (PUSH_LAST_TURNS=3 sur 5 tours => tour 3). Maintenant implementee via late_game_state.
    """

    @pytest.fixture(autouse=True)
    def _patch_weights(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Retourne des poids fixes pour ne pas charger la config reelle."""
        fake_weights = (1.0, -0.35, 0.6, 0.9, 1.0, 1.0)
        fake_profile = {
            "late_game": 1.0, "preservation": 0.0,
            "persistence": 0.0, "focus_shared": False,
        }
        monkeypatch.setattr(doctrines, "load_doctrine_weights", lambda key: fake_weights)
        monkeypatch.setattr(doctrines, "load_style_profile", lambda key: fake_profile)
        monkeypatch.setattr(doctrines, "_state_overrides_cfg", lambda: {
            "endgame": {"desperate_push": "endgame_push"},
        })
        monkeypatch.setattr(doctrines, "_late_game_transform_cfg", lambda: {
            "push_gain": 0.5, "protect_gain": 0.5,
        })

    def _mode(self, turn: int) -> str:
        """Mode de late_game_state du point de vue du joueur 1."""
        return late_game_state(
            _gs(turn=turn, limit=5, vp1=0.0, vp2=0.0), player=1
        )

    def test_bascule_at_turn_3(self) -> None:
        """Tour 3 : desperate_push (bascule exacte comme l'ancien PUSH_LAST_TURNS=3)."""
        assert self._mode(3) == "desperate_push"

    def test_normal_at_turn_2(self) -> None:
        """Tour 2 : pas encore en push."""
        assert self._mode(2) == "normal"

    def test_push_continues_turn_4(self) -> None:
        """Tour 4 : toujours en push."""
        assert self._mode(4) == "desperate_push"

    def test_push_continues_turn_5(self) -> None:
        """Tour 5 : toujours en push."""
        assert self._mode(5) == "desperate_push"

    def test_endgame_target_score_switches_at_bascule(self) -> None:
        """target_score passe de _score_efficiency a _score_contester au tour 3."""
        bot = EndgameBot()
        attacker = {"id": "1", "player": 1}
        gs_early = _gs(turn=2, limit=5)
        gs_push = _gs(turn=3, limit=5)
        # En early : efficacite (ne renvoie pas None sur une cible ordinaire)
        score_early = bot.target_score(attacker, True, gs_early)
        # En push : contester (peut renvoyer None si damage nul)
        score_push = bot.target_score(attacker, True, gs_push)
        # Les deux closures doivent venir de fonctions distinctes (efficiency vs contester).
        # `is not` passe toujours (deux objets differents) meme si les deux retournent
        # _score_efficiency — on verifie le qualname de la closure retournee.
        assert score_early.__qualname__ != score_push.__qualname__


# ─── Transformation de poids — protect_lead renforce l'evitement d'endgame ──────

class TestLateGameWeightTransform:
    """Verifie que la transformation de poids respecte les regles de signe (corrige 2026-08-15).

    protect_lead sur endgame (w_enemy=-0.35) DOIT renforcer l'evitement : |w_enemy_effectif| >= base.
    """

    def _transform(self, state: str, base: tuple, g: float, k: float = 0.5) -> tuple:
        return _apply_late_game_transform(base, state, g, k)

    # ---- w_enemy signe ----

    def test_protect_lead_negative_w_enemy_becomes_more_negative(self) -> None:
        """w_enemy=-0.35 avec protect_lead : |effectif| >= 0.35 (renforcement de l'evitement)."""
        base = (0.9, -0.35, 0.6, 0.9, 1.0, 1.0)
        result = self._transform("protect_lead", base, g=0.5, k=0.5)
        w_enn_eff = result[1]
        assert w_enn_eff < -0.35, (
            f"protect_lead doit renforcer l'evitement (plus negatif), got {w_enn_eff}"
        )
        assert abs(w_enn_eff) >= 0.35

    def test_protect_lead_positive_w_enemy_decreases(self) -> None:
        """w_enemy positif avec protect_lead : attenuee (bot se rapproche moins)."""
        base = (1.0, 0.2, 0.0, 0.9, 1.0, 1.0)
        result = self._transform("protect_lead", base, g=0.5, k=0.5)
        w_enn_eff = result[1]
        assert 0.0 <= w_enn_eff < 0.2, f"w_enemy positif attenuee, got {w_enn_eff}"

    def test_protect_lead_zero_w_enemy_stays_zero(self) -> None:
        """w_enemy=0 reste 0 sous protect_lead."""
        base = (1.0, 0.0, 0.0, 0.9, 1.0, 1.0)
        result = self._transform("protect_lead", base, g=0.5, k=0.5)
        assert result[1] == 0.0

    # ---- desperate_push ----

    def test_desperate_push_raises_w_objective(self) -> None:
        base = (1.0, 0.2, 0.3, 0.5, 1.0, 1.0)
        result = self._transform("desperate_push", base, g=0.5, k=0.5)
        assert result[0] > base[0], "w_objective doit augmenter en desperate_push"

    def test_desperate_push_lowers_w_risk(self) -> None:
        base = (1.0, 0.2, 0.3, 0.5, 1.0, 1.0)
        result = self._transform("desperate_push", base, g=0.5, k=0.5)
        assert result[3] < base[3], "w_risk doit diminuer en desperate_push"

    def test_desperate_push_raises_w_contest(self) -> None:
        base = (1.0, 0.2, 0.3, 0.5, 1.0, 1.0)
        result = self._transform("desperate_push", base, g=0.5, k=0.5)
        assert result[4] > base[4], "w_contest doit augmenter en desperate_push"

    def test_desperate_push_w_enemy_unchanged(self) -> None:
        base = (1.0, 0.2, 0.3, 0.5, 1.0, 1.0)
        result = self._transform("desperate_push", base, g=0.5, k=0.5)
        assert result[1] == base[1], "w_enemy non touche en desperate_push"

    # ---- gain=0 => identite (verrou D4) ----

    def test_gain_zero_is_identity_protect_lead(self) -> None:
        base = (0.9, -0.35, 0.6, 0.9, 1.0, 1.0)
        result = self._transform("protect_lead", base, g=0.0, k=0.5)
        assert result == base, "gain=0 doit rendre le vecteur identique (D4)"

    def test_gain_zero_is_identity_desperate_push(self) -> None:
        base = (1.5, 0.2, 0.3, 0.2, 4.0, 3.0)
        result = self._transform("desperate_push", base, g=0.0, k=0.5)
        assert result == base, "gain=0 doit rendre le vecteur identique (D4)"

    def test_normal_is_identity(self) -> None:
        base = (1.3, 0.2, 0.0, 0.0, 4.0, 3.0)
        result = self._transform("normal", base, g=1.0, k=0.5)
        assert result == base, "etat normal doit laisser le vecteur inchange"
