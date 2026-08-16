"""Tests de `_best_slot_action_persistent` (Bot_refactor.md §4.A.3).

Verrous (§2.5, D6) :
- Bascule effective a DEUX candidats : precedente legerement sous la meilleure
  => conservee a p fort, lachee a p=0.
- Echelle par critere : ratio pour les trois positifs, 10.0 pour contester.
- Bascule forcee vers un kill letal si la precedente ne l'est pas.
- Rupture sur cible morte / hors masque / nouveau tour.
- DecapitationBot concentre (deux escouades, une seule cible via focus_shared).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import pytest

import ai.bot_doctrines as doctrines
from ai.bot_doctrines import (
    DecapitationBot,
    _best_slot_action_persistent,
    _score_contester,
    _score_efficiency,
)
from engine import macro_intents as mi


# ─── helpers ──────────────────────────────────────────────────────────────────

def _make_gs(units: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "turn": 1,
        "episode_number": 1,
        "config": {"game_rules": {"max_turns": 5}},
        "victory_points": {1: 0.0, 2: 0.0},
        "units": units,
        "units_cache": {str(u["id"]): {"col": 0, "row": 0, "player": u.get("player", 2)}
                        for u in units},
        "objectives": None,
        "current_player": 1,
        "active_unit_id": "att",
    }


def _active(sid: str = "att", player: int = 1) -> Dict[str, Any]:
    return {"id": sid, "player": player}


def _target_entry(sid: str, player: int = 2) -> Dict[str, Any]:
    return {"id": sid, "player": player, "VALUE": 100.0}


# ─── Stub de _target_slot_entries ─────────────────────────────────────────────

def _make_stub_entries(pairs: List[Tuple[int, str]]):
    """Retourne une fonction stub qui produit les (action, sid, entry) demandes."""
    entries = [(a, sid, {"id": sid, "VALUE": 100.0}) for a, sid in pairs]

    def _stub(valid_actions, slots, slot_base, game_state, active_unit):
        return [(a, sid, e) for a, sid, e in entries if a in valid_actions]

    return _stub


# ─── Test: conservation a DEUX candidats (verrou cle de §2.5) ─────────────────

class TestTwoCandidatePersistence:
    """Verrou D6 : p fort conserve, p=0 lache — le test que la forme 'x etalement' ratait."""

    def _run(
        self,
        monkeypatch: pytest.MonkeyPatch,
        *,
        persistence_p: float,
        use_contester: bool = False,
        prev_sid: Optional[str] = "B",
    ) -> Tuple[Optional[int], Optional[str]]:
        """Score A=20, Score B=18 (precedente). Retourne (action, sid)."""
        scores = {"A": 20.0, "B": 18.0}
        entries_stub = _make_stub_entries([(mi.SHOOT_SLOT_BASE + 0, "A"),
                                           (mi.SHOOT_SLOT_BASE + 1, "B")])
        monkeypatch.setattr(doctrines, "_target_slot_entries", entries_stub)
        valid = [mi.SHOOT_SLOT_BASE + 0, mi.SHOOT_SLOT_BASE + 1]

        def _score_fn(sid, entry, gs) -> Optional[float]:
            return scores[sid]

        targets: Dict[str, Any] = {}
        if prev_sid:
            targets["att"] = (prev_sid, (1, 1))  # turn_marker = (episode, turn) = (1,1)

        gs = _make_gs([])
        return _best_slot_action_persistent(
            valid, mi.SHOOT_SLOTS, mi.SHOOT_SLOT_BASE, gs, _active(),
            _score_fn, persistence_p, use_contester, targets,
        )

    def test_strong_p_keeps_previous_ratio(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """p=0.95, echelle ratio : gap=2 <= 0.95*18=17.1 => conserve B."""
        _, sid = self._run(monkeypatch, persistence_p=0.95)
        assert sid == "B", "p fort doit conserver la cible precedente"

    def test_zero_p_switches_to_best(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """p=0 : threshold=0, gap=2 > 0 => bascule toujours vers A."""
        _, sid = self._run(monkeypatch, persistence_p=0.0)
        assert sid == "A", "p=0 doit toujours choisir la meilleure"

    def test_strong_p_keeps_previous_contester(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """p=0.95, echelle contester (10.0) : gap=2 <= 0.95*10=9.5 => conserve B."""
        _, sid = self._run(monkeypatch, persistence_p=0.95, use_contester=True)
        assert sid == "B"

    def test_weak_p_contester_switches(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """p=0.10, echelle contester : gap=2 > 0.10*10=1.0 => bascule vers A."""
        _, sid = self._run(monkeypatch, persistence_p=0.10, use_contester=True)
        assert sid == "A"

    def test_no_previous_picks_best(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Sans precedente, choisit toujours le meilleur."""
        _, sid = self._run(monkeypatch, persistence_p=0.95, prev_sid=None)
        assert sid == "A"


# ─── Test: echelle ratio (criteres positifs) ──────────────────────────────────

def test_ratio_scale_uses_prev_score(monkeypatch: pytest.MonkeyPatch) -> None:
    """Echelle = abs(prev_score). Avec prev_score=10, p=0.5 : gap doit depasser 5 pour basculer.

    A=14 (gap=4 <= 5) => garde B. A=16 (gap=6 > 5) => bascule vers A.
    """
    targets_dict: Dict[str, Any] = {"att": ("B", (1, 1))}

    def _run_with_a_score(a_score: float, monkeypatch: pytest.MonkeyPatch) -> Optional[str]:
        scores = {"A": a_score, "B": 10.0}
        stub = _make_stub_entries([(mi.SHOOT_SLOT_BASE + 0, "A"),
                                    (mi.SHOOT_SLOT_BASE + 1, "B")])
        monkeypatch.setattr(doctrines, "_target_slot_entries", stub)
        valid = [mi.SHOOT_SLOT_BASE + 0, mi.SHOOT_SLOT_BASE + 1]
        t_copy = dict(targets_dict)
        _, sid = _best_slot_action_persistent(
            valid, mi.SHOOT_SLOTS, mi.SHOOT_SLOT_BASE, _make_gs([]), _active(),
            lambda sid, e, gs: scores[sid], 0.5, False, t_copy,
        )
        return sid

    assert _run_with_a_score(14.0, monkeypatch) == "B", "gap=4 <= threshold=5 => garde B"
    assert _run_with_a_score(16.0, monkeypatch) == "A", "gap=6 > threshold=5 => bascule A"


# ─── Test: bascule forcee vers kill letal ─────────────────────────────────────

def test_lethal_kills_force_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    """Si la precedente n'est pas letale (score~10) et qu'une cible letale (score~1010) est disponible,
    gap >> p*scale => bascule forcee vers le kill.
    """
    targets_dict: Dict[str, Any] = {"att": ("B", (1, 1))}
    # B non letale (score 10), A letale (score 1010)
    scores = {"A": 1010.0, "B": 10.0}
    stub = _make_stub_entries([(mi.SHOOT_SLOT_BASE + 0, "A"),
                                (mi.SHOOT_SLOT_BASE + 1, "B")])
    monkeypatch.setattr(doctrines, "_target_slot_entries", stub)
    valid = [mi.SHOOT_SLOT_BASE + 0, mi.SHOOT_SLOT_BASE + 1]
    _, sid = _best_slot_action_persistent(
        valid, mi.SHOOT_SLOTS, mi.SHOOT_SLOT_BASE, _make_gs([]), _active(),
        lambda sid, e, gs: scores[sid], 0.95, False, targets_dict,
    )
    assert sid == "A", "Kill letal doit forcer la bascule meme avec p fort"


def test_both_lethal_keep_previous(monkeypatch: pytest.MonkeyPatch) -> None:
    """Les deux cibles sont letales : gap nul => garde la precedente."""
    targets_dict: Dict[str, Any] = {"att": ("B", (1, 1))}
    scores = {"A": 1012.0, "B": 1010.0}
    stub = _make_stub_entries([(mi.SHOOT_SLOT_BASE + 0, "A"),
                                (mi.SHOOT_SLOT_BASE + 1, "B")])
    monkeypatch.setattr(doctrines, "_target_slot_entries", stub)
    valid = [mi.SHOOT_SLOT_BASE + 0, mi.SHOOT_SLOT_BASE + 1]
    _, sid = _best_slot_action_persistent(
        valid, mi.SHOOT_SLOTS, mi.SHOOT_SLOT_BASE, _make_gs([]), _active(),
        lambda sid, e, gs: scores[sid], 0.95, False, targets_dict,
    )
    assert sid == "B", "Les deux letales : p fort conserve la precedente"


# ─── Test: ruptures de memoire ────────────────────────────────────────────────

class TestPersistenceRupture:
    def _setup_two_targets(self, monkeypatch: pytest.MonkeyPatch) -> None:
        scores = {"A": 20.0, "B": 18.0}
        stub = _make_stub_entries([(mi.SHOOT_SLOT_BASE + 0, "A"),
                                    (mi.SHOOT_SLOT_BASE + 1, "B")])
        monkeypatch.setattr(doctrines, "_target_slot_entries", stub)

        def _score(sid, e, gs) -> float:
            return scores[sid]
        self._score_fn = _score  # type: ignore[attr-defined]
        self._valid = [mi.SHOOT_SLOT_BASE + 0, mi.SHOOT_SLOT_BASE + 1]

    def _run(self, targets_dict: Dict, gs: Dict) -> Optional[str]:
        _, sid = _best_slot_action_persistent(
            self._valid, mi.SHOOT_SLOTS, mi.SHOOT_SLOT_BASE, gs, _active(),
            self._score_fn, 0.95, False, targets_dict,
        )
        return sid

    def test_new_turn_rupture(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Nouveau tour (marqueur change) => rupture => choisit le meilleur."""
        self._setup_two_targets(monkeypatch)
        # Memoire enregistree au tour 0, maintenant au tour 1
        targets = {"att": ("B", (1, 0))}  # marker (episode=1, turn=0) != (1, 1)
        gs = _make_gs([])  # gs.turn=1, gs.episode_number=1
        sid = self._run(targets, gs)
        assert sid == "A", "Rupture de tour => choisit le meilleur"

    def test_prev_absent_from_mask_rupture(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Precedente absent du masque (cible morte) => rupture => meilleur."""
        # stub ne retourne que A (B mort)
        stub = _make_stub_entries([(mi.SHOOT_SLOT_BASE + 0, "A")])
        monkeypatch.setattr(doctrines, "_target_slot_entries", stub)
        self._valid = [mi.SHOOT_SLOT_BASE + 0]
        self._score_fn = lambda sid, e, gs: 20.0  # type: ignore[attr-defined]
        targets = {"att": ("B", (1, 1))}  # B mort, absent du masque
        gs = _make_gs([])
        sid = self._run(targets, gs)
        assert sid == "A"

    def test_empty_mask_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Masque vide => (None, None)."""
        monkeypatch.setattr(doctrines, "_target_slot_entries", lambda *a: [])
        targets: Dict = {}
        gs = _make_gs([])
        action, sid = _best_slot_action_persistent(
            [], mi.SHOOT_SLOTS, mi.SHOOT_SLOT_BASE, gs, _active(),
            lambda sid, e, gs: 0.0, 0.95, False, targets,
        )
        assert action is None and sid is None

    def test_all_none_scores_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Toutes les cibles ecartees (score None) => (None, None)."""
        stub = _make_stub_entries([(mi.SHOOT_SLOT_BASE + 0, "A"),
                                    (mi.SHOOT_SLOT_BASE + 1, "B")])
        monkeypatch.setattr(doctrines, "_target_slot_entries", stub)
        valid = [mi.SHOOT_SLOT_BASE + 0, mi.SHOOT_SLOT_BASE + 1]
        action, sid = _best_slot_action_persistent(
            valid, mi.SHOOT_SLOTS, mi.SHOOT_SLOT_BASE, _make_gs([]), _active(),
            lambda sid, e, gs: None, 0.95, False, {},
        )
        assert action is None and sid is None


# ─── Test: DecapitationBot reste concentre (focus_shared) ────────────────────

class TestDecapitationConcentration:
    """Deux escouades attaquantes, une seule cible elue par le focus. Elles doivent tirer
    sur la MEME cible (verrou 'focus_shared: true' du profil decapitation).
    """

    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(doctrines, "load_style_profile", lambda key: {
            "late_game": 0.0, "preservation": 0.0,
            "persistence": 0.0, "focus_shared": True,
        })
        monkeypatch.setattr(doctrines, "load_doctrine_weights",
                            lambda key: (1.0, 0.6, 1.0, 0.2, 1.5, 2.0))
        monkeypatch.setattr(doctrines, "_state_overrides_cfg", lambda: {})
        monkeypatch.setattr(doctrines, "_late_game_transform_cfg",
                            lambda: {"push_gain": 0.5, "protect_gain": 0.5})
        monkeypatch.setattr(doctrines, "is_unit_alive",
                            lambda sid, gs: True)
        monkeypatch.setattr(doctrines, "_living_enemies_on_table",
                            lambda unit, gs: [
                                {"id": "E1", "player": 2},
                                {"id": "E2", "player": 2},
                            ])
        monkeypatch.setattr(doctrines, "require_unit_from_cache",
                            lambda sid, gs, ctx: {"col": 5, "row": 5})
        monkeypatch.setattr(doctrines, "entry_is_on_battlefield",
                            lambda e: True)
        # E1 a damage=10, E2 a damage=5 => E1 est elue
        monkeypatch.setattr(doctrines, "_damage_on",
                            lambda gs, att, tgt, r: 10.0 if str(tgt) == "E1" else 5.0)
        monkeypatch.setattr(doctrines, "get_hp_from_cache",
                            lambda sid, gs: 20.0)

        # slot mapping : slot 0 → E1, slot 1 → E2
        from ai.evaluation_bots import _target_slot_entries as real_tse
        def _stub_tse(valid_actions, slots, slot_base, game_state, active_unit):
            entries = []
            if slot_base + 0 in valid_actions:
                entries.append((slot_base + 0, "E1", {"id": "E1", "VALUE": 100.0}))
            if slot_base + 1 in valid_actions:
                entries.append((slot_base + 1, "E2", {"id": "E2", "VALUE": 50.0}))
            return entries

        monkeypatch.setattr(doctrines, "_target_slot_entries", _stub_tse)

    def _gs(self) -> Dict[str, Any]:
        return {
            "turn": 1,
            "episode_number": 42,
            "phase": "shoot",
            "config": {"game_rules": {"max_turns": 5}},
            "victory_points": {1: 0.0, 2: 0.0},
            "units": [
                {"id": "att1", "player": 1}, {"id": "att2", "player": 1},
                {"id": "E1", "player": 2}, {"id": "E2", "player": 2},
            ],
            "units_cache": {
                "att1": {"col": 0, "row": 0, "player": 1},
                "att2": {"col": 0, "row": 1, "player": 1},
                "E1": {"col": 5, "row": 5, "player": 2},
                "E2": {"col": 3, "row": 3, "player": 2},
            },
            "objectives": None,
            "current_player": 1,
            "active_unit_id": "att1",
        }

    def test_both_squads_target_same_focus(self) -> None:
        """Deux escouades DecapitationBot ciblent la meme unite (E1 = focus elu)."""
        bot = DecapitationBot()
        gs = self._gs()
        valid_all = [mi.SHOOT_SLOT_BASE + 0, mi.SHOOT_SLOT_BASE + 1]

        att1 = {"id": "att1", "player": 1}
        att2 = {"id": "att2", "player": 1}

        result1 = bot.select_action_with_state(valid_all, gs, att1)
        result2 = bot.select_action_with_state(valid_all, gs, att2)

        # Les deux doivent choisir le slot de E1 (slot 0)
        assert result1 == mi.SHOOT_SLOT_BASE + 0, f"att1 devrait cibler E1, got slot {result1 - mi.SHOOT_SLOT_BASE}"
        assert result2 == mi.SHOOT_SLOT_BASE + 0, f"att2 devrait cibler E1 (meme focus), got slot {result2 - mi.SHOOT_SLOT_BASE}"


# ─── Verrou T4 : mutation de persistence_p ───────────────────────────────────

def test_mutation_persistence_verrou(monkeypatch: pytest.MonkeyPatch) -> None:
    """Preuve rouge/vert : mettre persistence_p=0 annule la conservation.

    Cas : score A=20 (best), score B=18 (precedente).
    p=0.95 => conserve B. p=0 => choisit A.
    """
    scores = {"A": 20.0, "B": 18.0}
    stub = _make_stub_entries([(mi.SHOOT_SLOT_BASE + 0, "A"),
                                (mi.SHOOT_SLOT_BASE + 1, "B")])
    monkeypatch.setattr(doctrines, "_target_slot_entries", stub)
    valid = [mi.SHOOT_SLOT_BASE + 0, mi.SHOOT_SLOT_BASE + 1]
    gs = _make_gs([])
    targets = {"att": ("B", (1, 1))}

    def _score(sid, e, g) -> float:
        return scores[sid]

    # Baseline p=0.95 => conserve B
    t1 = dict(targets)
    _, sid = _best_slot_action_persistent(
        valid, mi.SHOOT_SLOTS, mi.SHOOT_SLOT_BASE, gs, _active(),
        _score, 0.95, False, t1,
    )
    assert sid == "B", "Baseline : p=0.95 conserve B"

    # Mutant p=0 => bascule vers A
    t2 = dict(targets)
    _, sid = _best_slot_action_persistent(
        valid, mi.SHOOT_SLOTS, mi.SHOOT_SLOT_BASE, gs, _active(),
        _score, 0.0, False, t2,
    )
    assert sid == "A", "Mutant : p=0 bascule vers A"
