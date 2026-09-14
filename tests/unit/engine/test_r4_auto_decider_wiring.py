"""R4 / T1 — le BRANCHEMENT du prédicat programmatique, pas seulement le prédicat.

Contexte (V11 §0.19.3). `test_programmatic_owner_predicate.py` verrouille
`is_programmatic_owner` lui-même. Mais **la rupture R4 n'était pas un prédicat faux** : le
prédicat était correct avant T1, c'est son **câblage** sur les décideurs d'allocation qui
manquait, si bien qu'en gym le moteur attendait une réponse humaine qui ne venait jamais.

Un test de prédicat ne rougit PAS si l'on débranche `SHOOT_CTX.auto_decider`. Ce fichier ferme
ce trou : il vérifie la **chaîne**, de bout en bout.

Chaîne couverte (lue dans le code, pas supposée) :

    SHOOT_CTX.auto_decider = _target_defender_is_ai -> is_programmatic_defender -> is_programmatic_owner
    FIGHT_CTX.auto_decider = _fight_auto_defender   -> _is_ai_controlled_fight_unit -> is_programmatic_owner
    consommation : _manual_allocation_step (shared_utils) `if ctx.auto_decider(...)`

Depuis le fight PvE par siège (2026-09-12), le flux fight ne décide plus lui-même « défenseur
humain ou machine » : ses quatre anciens sites `defender_human` sont fondus dans
`_fight_v11_allocate_declared` -> `build_manual_fight_allocation` -> `FIGHT_CTX`, et c'est le
moteur d'allocation qui interroge `auto_decider`. Le prédicat n'a donc plus qu'UN appelant.

⚠️ **Miroir PvP obligatoire (§8.1)** : chaque cas gym a son jumeau PvP-humain. Un test qui ne
couvrirait que la branche gym laisserait passer une casse du PvP — c'est la moitié du contrat.
"""

from __future__ import annotations

import dataclasses
from typing import Any, Dict

import pytest

from engine.phase_handlers import fight_handlers
from engine.phase_handlers import shared_utils as su
from engine.phase_handlers.fight_handlers import (
    FIGHT_CTX,
    _fight_auto_defender,
    _is_ai_controlled_fight_unit,
)
from engine.phase_handlers.shared_utils import SHOOT_CTX
from shared.data_validation import ConfigurationError


def _gs(gym: bool, owner_type: str) -> Dict[str, Any]:
    """État minimal : une cible '10' appartenant au joueur 1, dont le type est paramétré."""
    return {
        "gym_training_mode": gym,
        "player_types": {"1": owner_type, "2": "ai"},
        "units_cache": {"10": {"player": 1}},
        "unit_by_id": {"10": {"id": "10", "player": 1}},
    }


# ── Le décideur du TIR est bien branché (SHOOT_CTX) ────────────────────────────

def test_shoot_auto_decider_is_wired_to_the_predicate():
    """`SHOOT_CTX.auto_decider` existe et délègue au prédicat unique.

    Rougit si quelqu'un met `auto_decider=None` ou le rebranche sur `player_types` en direct.
    """
    assert SHOOT_CTX.auto_decider is not None, "SHOOT_CTX.auto_decider débranché"
    assert SHOOT_CTX.auto_decider(_gs(gym=True, owner_type="human"), "10") is True


def test_shoot_auto_decider_pvp_human_stays_manual():
    """MIROIR PvP : hors gym, un défenseur humain n'est PAS auto — l'allocation reste manuelle."""
    assert SHOOT_CTX.auto_decider is not None, "SHOOT_CTX.auto_decider débranché"
    assert SHOOT_CTX.auto_decider(_gs(gym=False, owner_type="human"), "10") is False


def test_shoot_auto_decider_pve_ai_defender_is_auto():
    """Hors gym, un défenseur `ai` reste auto (comportement PvE historique, non régressé)."""
    assert SHOOT_CTX.auto_decider is not None, "SHOOT_CTX.auto_decider débranché"
    assert SHOOT_CTX.auto_decider(_gs(gym=False, owner_type="ai"), "10") is True


# ── Le décideur du COMBAT est bien branché (FIGHT_CTX) ─────────────────────────

def test_fight_auto_decider_is_wired_to_the_predicate():
    assert FIGHT_CTX.auto_decider is not None, "FIGHT_CTX.auto_decider débranché"
    assert FIGHT_CTX.auto_decider(_gs(gym=True, owner_type="human"), "10") is True


def test_fight_auto_decider_pvp_human_stays_manual():
    """MIROIR PvP : le chemin FIGHT_CTX ne doit pas auto-résoudre contre un humain."""
    assert FIGHT_CTX.auto_decider is not None, "FIGHT_CTX.auto_decider débranché"
    assert FIGHT_CTX.auto_decider(_gs(gym=False, owner_type="human"), "10") is False


def test_fight_auto_defender_missing_target_raises():
    """Aucun repli silencieux : cible introuvable = bug explicite."""
    gs = _gs(gym=True, owner_type="human")
    gs["unit_by_id"] = {}
    with pytest.raises(ConfigurationError, match="Unit '404'"):
        _fight_auto_defender(gs, "404")


# ── Le prédicat que FIGHT_CTX.auto_decider consulte ────────────────────────────
# `_fight_auto_defender` rend `_is_ai_controlled_fight_unit(game_state, target)` : verrouiller ce
# prédicat verrouille la décision de tout le flux fight (un seul appelant, cf. le verrou structurel).

def test_defender_human_is_false_in_gym():
    """En gym, `defender_human` vaut False partout → aucune attente d'un humain absent.

    C'est LA rupture R4 : avec un `defender_human` resté True, le moteur rendait la main à un
    joueur qui n'existe pas et l'épisode se bloquait.
    """
    unit = {"player": 1}
    assert _is_ai_controlled_fight_unit(_gs(gym=True, owner_type="human"), unit) is True


def test_defender_human_is_true_for_a_human_in_pvp():
    """MIROIR PvP : hors gym, le joueur humain garde son allocation manuelle."""
    unit = {"player": 1}
    assert _is_ai_controlled_fight_unit(_gs(gym=False, owner_type="human"), unit) is False


def test_fight_unit_predicate_requires_player():
    """`player` manquant sur l'unité = bug explicite, pas un défaut (type ET message, §8.1)."""
    with pytest.raises(ConfigurationError, match="player"):
        _is_ai_controlled_fight_unit(_gs(gym=True, owner_type="human"), {})


def test_the_fight_flow_has_a_single_defender_decision_site():
    """⚠️ Verrou STRUCTUREL — sans lui, ce fichier retomberait dans le travers qu'il corrige.

    Les tests ci-dessus vérifient `_is_ai_controlled_fight_unit` et `FIGHT_CTX.auto_decider`, PAS
    que le flux fight ne décide nulle part ailleurs. Conclure « le prédicat est bon donc le
    branchement l'est » est exactement le raisonnement qui a laissé passer R4. Ce test lit la
    source et exige que la décision « défenseur humain / machine » n'ait qu'UN site : le prédicat
    est appelé une seule fois, depuis `_fight_auto_defender`, et `FIGHT_CTX` le porte. Un site
    local réintroduit (`defender_human = ...`, ou un appel direct au prédicat dans un handler)
    contournerait le moteur d'allocation : il fait rougir ici au lieu de passer inaperçu.
    """
    import ast
    from pathlib import Path

    src = Path(fight_handlers.__file__).read_text(encoding="utf-8")
    assert "defender_human" not in src, (
        "un site `defender_human` local est revenu dans fight_handlers : la décision doit passer "
        "par FIGHT_CTX.auto_decider, pas par un test ad hoc dans le flux"
    )

    callers: list[str] = []
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for sub in ast.walk(node):
            if (
                isinstance(sub, ast.Call)
                and isinstance(sub.func, ast.Name)
                and sub.func.id == "_is_ai_controlled_fight_unit"
            ):
                callers.append(node.name)
    assert callers == ["_fight_auto_defender"], (
        f"appelants de `_is_ai_controlled_fight_unit` : {callers} — attendu le seul "
        "`_fight_auto_defender` (un appelant en plus = décision hors FIGHT_CTX, R4 rompu)"
    )
    assert FIGHT_CTX.auto_decider is _fight_auto_defender, "FIGHT_CTX.auto_decider rebranché"


# ── La CONSOMMATION : _manual_allocation_step suit-il vraiment le décideur ? ────

def _alloc_ctx_state(auto: bool, monkeypatch, n_groups: int = 2) -> Dict[str, Any]:
    """État d'allocation minimal. `n_groups=2` déclenche la décision d'ORDRE des groupes."""
    groups = [{"group_id": f"g{i}", "model_ids": ["m1"]} for i in range(1, n_groups + 1)]
    monkeypatch.setattr(su, "_build_alloc_groups", lambda gs, sid: groups)
    monkeypatch.setattr(su, "_group_alive", lambda gs, g: True)
    monkeypatch.setattr(su, "_auto_declared_order", lambda gs, gl: [g["group_id"] for g in gl])
    monkeypatch.setattr(
        su, "_declare_order_payload",
        lambda gs, batch, live, ctx: {"waiting_for_player": True},
    )
    monkeypatch.setattr(su, "_finalize_manual_allocation", lambda gs, ctx: {"done": True})
    gs = _gs(gym=auto, owner_type="human")
    gs["models_cache"] = {}
    gs[SHOOT_CTX.alloc_key] = {
        "current_batch_index": 0,
        "batches": [{
            "target_sid": "10",
            # Batch sans groupe d'armes (ce test ne porte que sur l'ordre des groupes) :
            # même convention que le batch hazard, qui pose explicitement None.
            "weapon_group_idx": None,
            "alloc_groups": None,
            "declared_order": None,
            "current_group_index": 0,
            "pool": [],
            "pool_index": 0,
            "pending_mortal_wounds": None,
        }],
    }
    return gs


def test_allocation_step_auto_resolves_in_gym(monkeypatch):
    """En gym, l'ordre des groupes est tranché par le moteur : PAS de `waiting_for_player`.

    Verrouille la consommation réelle de `ctx.auto_decider` dans `_manual_allocation_step`.
    """
    gs = _alloc_ctx_state(auto=True, monkeypatch=monkeypatch)
    result = su._manual_allocation_step(gs, SHOOT_CTX)
    assert not (isinstance(result, dict) and result.get("waiting_for_player")), (
        "le moteur a rendu la main à un joueur alors qu'on est en gym — R4 débranché"
    )
    assert gs[SHOOT_CTX.alloc_key]["batches"][0]["declared_order"] == ["g1", "g2"]


def test_allocation_step_waits_for_human_in_pvp(monkeypatch):
    """MIROIR PvP : hors gym contre un humain, le moteur DOIT rendre la main.

    Sans ce test, brancher `auto_decider` en dur sur True passerait inaperçu et supprimerait
    l'allocation manuelle du PvP.
    """
    gs = _alloc_ctx_state(auto=False, monkeypatch=monkeypatch)
    result = su._manual_allocation_step(gs, SHOOT_CTX)
    assert isinstance(result, dict) and result.get("waiting_for_player") is True, (
        "le moteur n'a pas rendu la main à l'humain — le miroir PvP est cassé"
    )


# ── SECOND point de consommation : le choix de la FIGURINE (~L6446) ────────────
# `_manual_allocation_step` interroge `auto_decider` une DEUXIÈME fois pour décider qui,
# dans le groupe courant, encaisse la blessure : `_select_allocation_model` (auto) contre
# `_manual_waiting_payload` (on rend la main). Le premier test ne couvre pas ce site.

def _model_choice_state(auto: bool, monkeypatch) -> Dict[str, Any]:
    """Un SEUL groupe (ordre implicite) → la 1ʳᵉ décision est court-circuitée, on atteint la 2ᵉ."""
    group = {"group_id": "g1", "model_ids": ["m1"]}
    monkeypatch.setattr(su, "_build_alloc_groups", lambda gs, sid: [group])
    monkeypatch.setattr(su, "_group_alive", lambda gs, g: True)
    monkeypatch.setattr(su, "_current_live_group", lambda gs, batch: group)
    monkeypatch.setattr(su, "_select_allocation_model", lambda gs, sid, alive: "m1")
    monkeypatch.setattr(
        su, "_manual_waiting_payload",
        lambda gs, batch, alive, ctx: {"waiting_for_player": True},
    )
    monkeypatch.setattr(su, "_finalize_manual_allocation", lambda gs, ctx: {"done": True})
    gs = _gs(gym=auto, owner_type="human")
    gs["models_cache"] = {"m1": {"HP_CUR": 2, "HP_MAX": 2}}
    gs[SHOOT_CTX.alloc_key] = {
        "current_batch_index": 0,
        "batches": [{
            "target_sid": "10",
            # Batch sans groupe d'armes (ce test ne porte que sur l'ordre des groupes) :
            # même convention que le batch hazard, qui pose explicitement None.
            "weapon_group_idx": None,
            "alloc_groups": None,
            "declared_order": None,
            "current_group_index": 0,
            "current_model_id": None,
            "pool": ["w1"],
            "pool_index": 0,
            "pending_mortal_wounds": None,
        }],
    }
    return gs


def test_model_choice_is_automatic_in_gym(monkeypatch):
    """En gym, le moteur choisit la figurine touchée sans rendre la main."""
    resolved: list = []
    ctx = dataclasses.replace(SHOOT_CTX, resolve_wound_fn=lambda gs, alloc, batch, c: (
        resolved.append(batch["current_model_id"]),
        batch.__setitem__("pool_index", batch["pool_index"] + 1),
    ))
    gs = _model_choice_state(auto=True, monkeypatch=monkeypatch)
    gs[ctx.alloc_key] = gs.pop(SHOOT_CTX.alloc_key)
    result = su._manual_allocation_step(gs, ctx)
    assert not (isinstance(result, dict) and result.get("waiting_for_player")), (
        "le moteur attend un humain pour choisir la figurine — R4 débranché au 2ᵉ site"
    )
    assert resolved == ["m1"]


def test_model_choice_waits_for_human_in_pvp(monkeypatch):
    """MIROIR PvP : hors gym, le choix de la figurine revient au joueur."""
    ctx = dataclasses.replace(SHOOT_CTX, resolve_wound_fn=lambda gs, alloc, batch, c: None)
    gs = _model_choice_state(auto=False, monkeypatch=monkeypatch)
    gs[ctx.alloc_key] = gs.pop(SHOOT_CTX.alloc_key)
    result = su._manual_allocation_step(gs, ctx)
    assert isinstance(result, dict) and result.get("waiting_for_player") is True, (
        "le choix de figurine n'est plus rendu à l'humain — miroir PvP cassé"
    )
