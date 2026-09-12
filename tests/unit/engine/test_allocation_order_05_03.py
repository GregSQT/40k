"""05.03 « Allocation Order » — validation de l ordre des groupes declare par le defenseur.

Le PDF 05 Attack sequence (05.03, etape 2) impose TROIS contraintes a l ordre declare :
  1. un groupe non-CHARACTER contenant une figurine blessee est en premier ;
  2. aucun groupe CHARACTER n est plus tot qu un groupe non-CHARACTER ;
  3. un groupe CHARACTER blesse est plus tot qu un groupe CHARACTER sain.

Deux consommateurs dans `shared_utils` :
  - `apply_manual_shoot_declare_order` (defenseur humain) : une boucle de validation par
    contrainte, chacune levant sa propre ValueError ;
  - `_auto_declared_order` (defenseur programmatique) : produit directement un ordre conforme.

Chaque ordre invalide de la section 05.03 viole EXACTEMENT UNE contrainte : retirer une boucle
de validation rougit le test correspondant et lui seul. La precondition « permutation des
groupes vivants » (groupe mort exclu, aucun doublon) a sa propre section.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from engine.phase_handlers import shared_utils as su
from engine.phase_handlers.shared_utils import SHOOT_CTX

# Identifiants des groupes (creation : non-CHARACTER d abord, puis CHARACTER, cf.
# `_build_alloc_groups`).
NH = 0  # non-CHARACTER sain
NW = 1  # non-CHARACTER blesse
CW = 2  # CHARACTER blesse
CH = 3  # CHARACTER sain


def _model(hp_cur: int, hp_max: int) -> Dict[str, Any]:
    return {"HP_CUR": hp_cur, "HP_MAX": hp_max}


def _groups() -> List[Dict[str, Any]]:
    return [
        {"group_id": NH, "is_character": False, "model_ids": ["nh_a", "nh_b"]},
        {"group_id": NW, "is_character": False, "model_ids": ["nw_a", "nw_b"]},
        {"group_id": CW, "is_character": True, "model_ids": ["cw"]},
        {"group_id": CH, "is_character": True, "model_ids": ["ch"]},
    ]


def _gs() -> Dict[str, Any]:
    """Une allocation tir en attente de declaration d ordre : un lot, quatre groupes vivants."""
    return {
        "models_cache": {
            "nh_a": _model(2, 2), "nh_b": _model(2, 2),
            "nw_a": _model(2, 2), "nw_b": _model(1, 2),
            "cw": _model(3, 5),
            "ch": _model(5, 5),
        },
        SHOOT_CTX.alloc_key: {
            "current_batch_index": 0,
            "batches": [{"alloc_groups": _groups(), "declared_order": None, "current_group_index": None}],
        },
    }


def _declare(gs: Dict[str, Any], order: List[int]) -> Dict[str, Any]:
    return su.apply_manual_shoot_declare_order(gs, order, SHOOT_CTX)


# ── Defenseur humain : apply_manual_shoot_declare_order ───────────────────────


def test_ordre_conforme_accepte_et_enregistre(monkeypatch):
    """[NW, NH, CW, CH] respecte les trois contraintes : ordre enregistre, allocation relancee."""
    gs = _gs()
    stepped: List[Any] = []
    monkeypatch.setattr(su, "_manual_allocation_step", lambda g, ctx: stepped.append((g, ctx)) or {"ok": True})

    result = _declare(gs, [NW, NH, CW, CH])

    batch = gs[SHOOT_CTX.alloc_key]["batches"][0]
    assert batch["declared_order"] == [NW, NH, CW, CH]
    assert batch["current_group_index"] == 0
    assert stepped == [(gs, SHOOT_CTX)]
    assert result == {"ok": True}


def test_character_avant_non_character_refuse():
    """Contrainte 2 seule violee : un CHARACTER (blesse) place avant un non-CHARACTER (sain)."""
    gs = _gs()
    with pytest.raises(ValueError, match="non-CHARACTER ne peut pas etre place apres un CHARACTER"):
        _declare(gs, [NW, CW, NH, CH])
    assert gs[SHOOT_CTX.alloc_key]["batches"][0]["declared_order"] is None


def test_non_character_sain_avant_non_character_blesse_refuse():
    """Contrainte 1 seule violee : le groupe non-CHARACTER blesse n est pas en premier."""
    gs = _gs()
    with pytest.raises(ValueError, match="non-CHARACTER blesse doit preceder les groupes sains"):
        _declare(gs, [NH, NW, CW, CH])
    assert gs[SHOOT_CTX.alloc_key]["batches"][0]["declared_order"] is None


def test_character_sain_avant_character_blesse_refuse():
    """Contrainte 3 seule violee : deux CHARACTER, le sain declare avant le blesse."""
    gs = _gs()
    with pytest.raises(ValueError, match="CHARACTER blesse doit preceder un CHARACTER sain"):
        _declare(gs, [NW, NH, CH, CW])
    assert gs[SHOOT_CTX.alloc_key]["batches"][0]["declared_order"] is None


def test_double_declaration_refuse(monkeypatch):
    """Garde de re-declaration : un ordre deja enregistre pour le lot ne peut pas etre redeclare,
    et l ordre initial reste intact (l allocation n est pas relancee une seconde fois)."""
    gs = _gs()
    stepped: List[Any] = []
    monkeypatch.setattr(su, "_manual_allocation_step", lambda g, ctx: stepped.append((g, ctx)) or {"ok": True})
    _declare(gs, [NW, NH, CW, CH])

    with pytest.raises(ValueError, match="deja declare"):
        _declare(gs, [NW, NH, CW, CH])

    batch = gs[SHOOT_CTX.alloc_key]["batches"][0]
    assert batch["declared_order"] == [NW, NH, CW, CH]
    assert batch["current_group_index"] == 0
    assert stepped == [(gs, SHOOT_CTX)]


# ── Precondition : permutation des groupes vivants ────────────────────────────


def test_groupe_mort_exclu_de_la_permutation(monkeypatch):
    """Un groupe dont toutes les figurines sont mortes ne fait plus partie des groupes vivants :
    le declarer est refuse, l ordre sans lui est accepte."""
    gs = _gs()
    del gs["models_cache"]["ch"]
    monkeypatch.setattr(su, "_manual_allocation_step", lambda g, ctx: {"ok": True})

    with pytest.raises(ValueError, match="n est pas une permutation"):
        _declare(gs, [NW, NH, CW, CH])
    assert gs[SHOOT_CTX.alloc_key]["batches"][0]["declared_order"] is None

    _declare(gs, [NW, NH, CW])
    assert gs[SHOOT_CTX.alloc_key]["batches"][0]["declared_order"] == [NW, NH, CW]


def test_identifiant_duplique_refuse():
    """Un ID repete (et un autre absent) n est pas une permutation des groupes vivants."""
    gs = _gs()
    with pytest.raises(ValueError, match="n est pas une permutation"):
        _declare(gs, [NW, NW, CW, CH])
    assert gs[SHOOT_CTX.alloc_key]["batches"][0]["declared_order"] is None


# ── Defenseur programmatique : _auto_declared_order ───────────────────────────


def test_ordre_auto_conforme_05_03():
    """L ordre automatique est [non-CHAR blesse, non-CHAR sain, CHAR blesse, CHAR sain]."""
    gs = _gs()
    # Groupes fournis dans le pire ordre : le resultat ne doit rien devoir a l ordre d entree.
    live_groups = list(reversed(_groups()))

    assert su._auto_declared_order(gs, live_groups) == [NW, NH, CW, CH]


def test_ordre_auto_passe_la_validation_humaine(monkeypatch):
    """Miroir IA/PvP : l ordre que rend l auto-decideur est un ordre qu un humain aurait le
    droit de declarer (meme contrat 05.03 des deux cotes)."""
    gs = _gs()
    monkeypatch.setattr(su, "_manual_allocation_step", lambda g, ctx: {"ok": True})

    auto_order = su._auto_declared_order(gs, _groups())
    _declare(gs, auto_order)

    assert gs[SHOOT_CTX.alloc_key]["batches"][0]["declared_order"] == auto_order
