"""Observation — seuil de commandement (01.06) et déclenchement du test de Battle-shock (08.03).

Les deux champs sont les moitiés d'un même fait de règle, et c'est pourquoi ils vivent dans le
même fichier de test : `leadership` dit CONTRE QUOI l'unité testera, `battle_shock_test_due` dit
SI elle testera. L'un sans l'autre ne décide de rien — un seuil de 8+ sur une escouade qui ne
testera jamais ne vaut pas plus qu'un test imminent dont on ignore le seuil.

Ce que ce fichier NE refait PAS : le moteur est déjà verrouillé par
`test_command_points_and_battle_shock.py` (meilleur Ld 01.06, extinction 19.04 à la mort du
character, parité de l'appendice 25). Ici, tout porte sur l'OBSERVATION — que les deux champs
LISENT ces oracles et suivent l'état, au lieu d'en porter une copie qui se périmerait.

PREUVE DU ROUGE (2026-09-09), mutations posées dans `_encode_unit_entity` puis retirées :
- `leadership` câblé sur `require_key(unit, "LD")` — le Ld du bodyguard, c'est-à-dire le défaut
  historique du moteur — au lieu de `unit_effective_leadership` : les deux tests de seuil tombent
  (6.0 au lieu de 5.0, puis une valeur qui ne bouge plus à la mort du Chaplain) ;
- `battle_shock_test_due` câblé sur `restant / départ <= 0,5` au lieu du prédicat du moteur : seul
  le cas MONO-FIGURINE tombe (Warboss à 3 PV sur 6 annoncé comme n'ayant pas à tester). Les cas de
  parité, eux, restent VERTS — les deux formulations sont équivalentes sur un effectif en
  figurines, et c'est la mutation qui l'a établi, pas une lecture du texte de la règle.

Les états sont CONSTRUITS — effectifs, positions, figurines détruites une par une : aucun test ici
ne dépend d'une graine ni d'un ordre d'exécution.
"""
from __future__ import annotations

from typing import Any, Dict, List

import pytest

from engine.observation_entities import unit_bin_index, unit_cont_index
from engine.phase_handlers.shared_utils import destroy_model, update_model_hp

# Source UNIQUE du chargement réel (repli 19.04, factions déclarées, scénario temporaire) : un
# second harnais écrit ici serait libre de diverger du premier sur le format de scénario, et c'est
# précisément ce chargement-là — celui qui lit les datasheets — que ces champs doivent traverser.
from tests.unit.engine.test_command_points_and_battle_shock import _load

CONT_LEADERSHIP = unit_cont_index("leadership")
BIN_TEST_DUE = unit_bin_index("battle_shock_test_due")

#: Datasheets RÉELLES des rosters joués : Vanguard Ld 6+, Chaplain Ld 5+ attaché (roster SM
#: `training` et `holdout`), Boyz Ld 7+. Des stats inventées ne prouveraient rien du câblage —
#: c'est la lecture de la datasheet de la figurine attachée qui est en jeu.
_VANGUARD = "VanguardVeteranSquadJumpPack"
_CHAPLAIN = "ChaplainJumpPack"
_BOYZ = "Boyz"


def _squad(uid: int, player: int, unit_type: str, count: int, col: int, row: int,
           *, leader: str | None = None) -> Dict[str, Any]:
    """Escouade de `count` figurines alignées, avec un `leader` d'une AUTRE datasheet en dernier.

    Le personnage est déclaré comme une figurine `models[]` portant son propre `unit_type` — la
    forme exacte des rosters d'entraînement (`config/agents/.../rosters/500pts/`), donc le chemin
    qui recopie le `LD` de SA datasheet dans `models_cache`.
    """
    models: List[Dict[str, Any]] = [
        {"col": col + i, "row": row} for i in range(count - (1 if leader else 0))
    ]
    if leader:
        models.append({"col": col + count - 1, "row": row, "unit_type": leader})
    return {"id": uid, "unit_type": unit_type, "player": player,
            "col": col, "row": row, "models": models}


def _cont(eng, squad_id: str):
    """Ligne CONTINUE de l'escouade `squad_id`, observée depuis elle-même.

    Slot allié 0 = l'escouade ACTIVE : contrat de `get_ally_slot_mapping`, pas une convention de
    tri (« LIGNE 0 = l'escouade ACTIVE […] l'encodeur lit ce slot comme "moi" »).
    """
    return eng.obs_builder.build_squad_observation(eng.game_state, squad_id)["allies_cont"][0]


def _bin(eng, squad_id: str):
    """Ligne de DRAPEAUX de l'escouade `squad_id`, observée depuis elle-même."""
    return eng.obs_builder.build_squad_observation(eng.game_state, squad_id)["allies_bin"][0]


def _kill(eng, squad_id: str, n: int) -> None:
    """Détruit `n` figurines de base de l'escouade, en partant de la dernière posée."""
    gs = eng.game_state
    for mid in list(reversed(gs["squad_models"][squad_id]))[:n]:
        destroy_model(gs, mid, reason="combat")


# ─────────────────────────────────────────────────────────────────────────────
# 01.06 — le seuil OBSERVÉ est celui contre lequel l'unité teste
# ─────────────────────────────────────────────────────────────────────────────

def test_le_champ_leadership_porte_le_seuil_en_vigueur_de_lescouade():
    """Chaplain (Ld 5+) attaché à des Vanguard (Ld 6+) : l'escouade est observée à 5."""
    eng = _load([
        _squad(1, 1, _VANGUARD, 5, 3, 3, leader=_CHAPLAIN),
        _squad(101, 2, _BOYZ, 5, 12, 10),
    ])
    assert _cont(eng, "1")[CONT_LEADERSHIP] == pytest.approx(5.0)


def test_le_champ_leadership_est_celui_de_lescouade_sans_personnage():
    """Contre-épreuve : les mêmes Vanguard sans Chaplain sont observés à 6."""
    eng = _load([
        _squad(1, 1, _VANGUARD, 5, 3, 3),
        _squad(101, 2, _BOYZ, 5, 12, 10),
    ])
    assert _cont(eng, "1")[CONT_LEADERSHIP] == pytest.approx(6.0)


def test_le_champ_leadership_remonte_quand_le_personnage_attache_meurt():
    """19.04 : la source morte, son Ld disparaît de l'observation avec elle (5 -> 6).

    C'est le seul cas où la valeur BOUGE en cours de partie, et il est rare — mesuré le
    2026-09-09, aucune des 66 escouades suivies sur 6 épisodes gym n'a vu son Ld effectif changer,
    l'allocation 19.02 faisant tomber le character en dernier. Rare ne veut pas dire inatteignable :
    une observation qui garderait 5 après sa mort annoncerait un test plus facile qu'il ne l'est.
    """
    eng = _load([
        _squad(1, 1, _VANGUARD, 5, 3, 3, leader=_CHAPLAIN),
        _squad(101, 2, _BOYZ, 5, 12, 10),
    ])
    gs = eng.game_state
    chaplain = next(
        mid for mid in gs["squad_models"]["1"]
        if gs["models_cache"][mid]["unitType"] == _CHAPLAIN
    )
    assert _cont(eng, "1")[CONT_LEADERSHIP] == pytest.approx(5.0)

    destroy_model(gs, chaplain, reason="combat")
    assert _cont(eng, "1")[CONT_LEADERSHIP] == pytest.approx(6.0)


# ─────────────────────────────────────────────────────────────────────────────
# 08.03 / appendice 25 — le bit dit si l'unité TESTERA
# ─────────────────────────────────────────────────────────────────────────────

def test_le_bit_de_test_08_03_est_eteint_sur_une_escouade_intacte():
    """Une escouade à effectif plein et non choquée ne testera pas."""
    eng = _load([
        _squad(1, 1, _VANGUARD, 5, 3, 3),
        _squad(101, 2, _BOYZ, 6, 12, 10),
    ])
    assert _bin(eng, "101")[BIN_TEST_DUE] == pytest.approx(0.0)


def test_le_bit_de_test_08_03_respecte_la_parite_de_lappendice_25():
    """Force de départ IMPAIRE : 5 réduits à 3 ne testent pas (3 × 2 > 5), à 2 ils testent.

    ⚠️ Ce cas ne DISCRIMINE pas un seuil naïf : sur des entiers, `restant / départ <= 0,5` est
    équivalent à l'union des deux prédicats de l'appendice 25, la clause de parité ne pouvant
    jouer que là où `2 × restant == départ` est impossible. Mesuré par mutation le 2026-09-09 —
    le seuil naïf laisse ce test VERT. Il reste comme verrou de non-régression du comportement ;
    ce qui sépare réellement les deux formulations est le cas mono-figurine ci-dessous.
    """
    eng = _load([
        _squad(1, 1, _VANGUARD, 5, 3, 3),
        _squad(101, 2, _BOYZ, 5, 12, 10),
    ])
    _kill(eng, "101", 2)  # 5 -> 3 : au-dessus du demi-effectif d'une force impaire
    assert _bin(eng, "101")[BIN_TEST_DUE] == pytest.approx(0.0)

    _kill(eng, "101", 1)  # 3 -> 2 : sous le demi-effectif
    assert _bin(eng, "101")[BIN_TEST_DUE] == pytest.approx(1.0)


def test_le_bit_de_test_08_03_sallume_au_demi_effectif_exact_dune_force_paire():
    """Force de départ PAIRE : 6 réduits à 3, c'est le demi-effectif exact — l'unité testera."""
    eng = _load([
        _squad(1, 1, _VANGUARD, 5, 3, 3),
        _squad(101, 2, _BOYZ, 6, 12, 10),
    ])
    _kill(eng, "101", 3)
    assert _bin(eng, "101")[BIN_TEST_DUE] == pytest.approx(1.0)


def test_le_bit_de_test_08_03_mesure_les_PV_dune_unite_mono_figurine():
    """Appendice 25 : à force de départ 1, la mesure est en POINTS DE VIE, pas en figurines.

    C'est le cas qui sépare le prédicat du moteur de tout seuil bâti sur l'effectif : un Warboss
    à 3 PV sur 6 est à demi-effectif et testera, alors qu'il reste 1 figurine sur 1 — `alive_models`
    et `model_count_ratio` valent exactement ce qu'ils valaient intacts.
    """
    eng = _load([
        _squad(1, 1, _VANGUARD, 5, 3, 3),
        {"id": 101, "unit_type": "Warboss", "player": 2, "col": 12, "row": 10},
    ])
    gs = eng.game_state
    warboss = gs["squad_models"]["101"][0]
    assert int(gs["models_cache"][warboss]["HP_MAX"]) == 6

    update_model_hp(gs, warboss, 4)  # 4/6 : au-dessus du demi-effectif
    assert _bin(eng, "101")[BIN_TEST_DUE] == pytest.approx(0.0)

    update_model_hp(gs, warboss, 3)  # 3/6 : demi-effectif EXACT, mesuré en PV
    assert _bin(eng, "101")[BIN_TEST_DUE] == pytest.approx(1.0)


def test_le_bit_de_test_08_03_reste_arme_tant_que_lunite_est_choquee():
    """Clause de sortie de 08.03 : une unité choquée RETESTE, même au-dessus du demi-effectif.

    Sans le premier terme du prédicat, le bit s'éteindrait sur une unité choquée à effectif plein
    (soignée, ou choquée par un autre effet) et l'agent ne verrait pas venir le jet qui peut la
    libérer. `battle_shocked` est l'état qu'écrit `roll_battle_shock` ; il est posé ici tel quel.
    """
    eng = _load([
        _squad(1, 1, _VANGUARD, 5, 3, 3),
        _squad(101, 2, _BOYZ, 6, 12, 10),
    ])
    gs = eng.game_state
    assert _bin(eng, "101")[BIN_TEST_DUE] == pytest.approx(0.0)

    next(u for u in gs["units"] if str(u["id"]) == "101")["battle_shocked"] = True
    assert _bin(eng, "101")[BIN_TEST_DUE] == pytest.approx(1.0)
