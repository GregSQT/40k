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

Les 4 sites `defender_human` du flux fight (calcul local `not _is_ai_controlled_fight_unit(...)`
par site) ont disparu avec le chantier « fight PvE par siège » (2026-09-12) : l'allocation des
pertes en mêlée passe désormais par le SEUL `FIGHT_CTX.auto_decider`. Le verrou structurel porte
donc sur cette unicité : aucun autre appel du prédicat, aucune lecture directe de `player_types`.

⚠️ **Miroir PvP obligatoire (§8.1)** : chaque cas gym a son jumeau PvP-humain. Un test qui ne
couvrirait que la branche gym laisserait passer une casse du PvP — c'est la moitié du contrat.
"""

from __future__ import annotations

import ast
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


# ── Le prédicat unique du flux fight ───────────────────────────────────────────
# `_fight_auto_defender` (FIGHT_CTX) calcule `_is_ai_controlled_fight_unit(game_state, target)`.
# Verrouiller ce prédicat verrouille le seul site qui décide qui alloue les pertes en mêlée.

def test_fight_unit_is_ai_controlled_in_gym():
    """En gym, le défenseur est AUTO partout → aucune attente d'un humain absent.

    C'est LA rupture R4 : avec un défenseur resté « humain », le moteur rendait la main à un
    joueur qui n'existe pas et l'épisode se bloquait.
    """
    unit = {"player": 1}
    assert _is_ai_controlled_fight_unit(_gs(gym=True, owner_type="human"), unit) is True


def test_fight_unit_is_not_ai_controlled_for_a_human_in_pvp():
    """MIROIR PvP : hors gym, le joueur humain garde son allocation manuelle."""
    unit = {"player": 1}
    assert _is_ai_controlled_fight_unit(_gs(gym=False, owner_type="human"), unit) is False


def test_fight_unit_predicate_requires_player():
    """`player` manquant sur l'unité = bug explicite, pas un défaut (type ET message, §8.1)."""
    with pytest.raises(ConfigurationError, match="player"):
        _is_ai_controlled_fight_unit(_gs(gym=True, owner_type="human"), {})


def _fight_handlers_module() -> ast.Module:
    from pathlib import Path

    return ast.parse(Path(fight_handlers.__file__).read_text(encoding="utf-8"))


def _enclosing_function_names(tree: ast.Module, wanted: str) -> list[str]:
    """Nom de la fonction qui contient chaque appel `wanted(...)` ; '<module>' hors fonction."""
    sites: list[str] = []

    def _walk(node: ast.AST, scope: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                _walk(child, child.name)
                continue
            if (
                isinstance(child, ast.Call)
                and isinstance(child.func, ast.Name)
                and child.func.id == wanted
            ):
                sites.append(scope)
            _walk(child, scope)

    _walk(tree, "<module>")
    return sites


def test_fight_owner_decision_has_a_single_site_wired_to_the_predicate():
    """⚠️ Verrou STRUCTUREL — sans lui, ce fichier retomberait dans le travers qu'il corrige.

    Les tests ci-dessus vérifient `_is_ai_controlled_fight_unit`, PAS que le flux fight l'appelle.
    Conclure « le helper est bon donc le branchement l'est » est exactement le raisonnement qui a
    laissé passer R4. Ce test lit la SOURCE (AST, pas grep : un appel en commentaire ou en
    docstring ne compte pas) et exige que le prédicat soit appelé EXACTEMENT UNE fois, depuis
    `_fight_auto_defender` — un 2ᵉ site local (retour des `defender_human` par site) ou un site
    qui lirait `player_types` en direct au lieu du prédicat fait rougir au lieu de passer inaperçu.
    """
    tree = _fight_handlers_module()
    sites = _enclosing_function_names(tree, "_is_ai_controlled_fight_unit")
    assert sites == ["_fight_auto_defender"], (
        f"appels de `_is_ai_controlled_fight_unit` : {sites} — le flux fight doit décider du "
        "défenseur par le SEUL `_fight_auto_defender` (FIGHT_CTX.auto_decider)"
    )
    direct_reads = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and node.value == "player_types"
    ]
    assert direct_reads == [], (
        f"lecture directe de `player_types` dans fight_handlers (lignes {direct_reads}) — "
        "le type de propriétaire ne se lit que par `is_programmatic_owner`"
    )


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
