"""Lot 2 — l'analyzer consomme ce que le journal dit désormais, et cesse de deviner.

Quatre défauts fermés ensemble, tous mesurés sur le run de 600 épisodes du 2026-08-08 :

1. AUCUN POINT DE RECALAGE. L'état était reconstruit par accumulation ; 546 lignes portent une
   sauvegarde ratée sans segment `Dmg:`, donc des morts jamais vues, donc 76 « action sur une
   unité morte » mesurées contre des fantômes. L'instantané `T{tour} STATE:` recale — et l'écart
   est COMPTÉ avant d'être corrigé (2.8), sans quoi la prochaine dérive repasserait inaperçue.
2. 1.6 NE REGARDAIT PAS LA PHASE DE COMBAT (`phase in ('MOVE','SHOOT','CHARGE')`), c'est-à-dire
   exactement là où le défaut vit : 24 unités combattent deux fois dans la même phase, sur 15
   épisodes, pendant que « Double-activation : 0 » s'affichait en vert.
3. LE PLAFOND D'ATTAQUES ÉTAIT CALCULÉ SUR LE TYPE D'ESCOUADE. 20 fausses « Attacks over CC_NB »,
   dont 5 attaques d'un Ancient rattaché (arme NB=5) plafonnées au NB=3 de l'Intercessor porteur.
4. LE BFS CONFONDAIT TRANSIT ET PLACEMENT : une case d'arrivée occupée devenait injoignable à
   n'importe quel budget, et 8 charges sur 8 remontaient « au-delà du budget » là où le fait est
   « chevauchement » — leur chemin valait exactement la distance à vol d'oiseau.
"""
from __future__ import annotations

from typing import Any, Dict

import pytest

import ai.analyzer as an
from ai.analyzer_core import _apply_state_snapshot
from ai.analyzer_state import AnalyzerState


def _state() -> AnalyzerState:
    stats: Dict[str, Any] = {"state_resync": {"dead_missed": 0, "alive_missed": 0, "pos_mismatch": 0}}
    st = AnalyzerState(stats=stats)
    st.unit_hp = {"1": 2, "101": 2}
    st.unit_models_alive = {"1": 2, "101": 1}
    st.positions_by_model = {"1": {"1#0": (5, 48), "1#1": (7, 47)}, "101": {"101#5": (4, 49)}}
    return st


# ── 1. Recalage sur l'instantané d'état ─────────────────────────────────────────────────────

def test_mort_non_vue_est_comptee_puis_corrigee() -> None:
    """Le fantôme : l'analyzer croit l'unité vivante, le moteur ne la voit plus.

    C'est la forme exacte des 76 « action sur une unité morte » : la blessure qui a tué 101 a été
    écartée faute d'allocataire, donc écrite sans `Dmg:`, donc jamais soustraite.
    """
    st = _state()
    _apply_state_snapshot(st, "1[1#0@(5,48,z0):2 1#1@(7,47,z0):1]")

    assert st.stats["state_resync"]["dead_missed"] == 1
    assert st.unit_hp["101"] == 0
    assert st.unit_models_alive["101"] == 0
    assert "101" not in st.positions_by_model
    assert "101" in st.dead_units_current_episode


def test_deplacement_non_journalise_est_compte_puis_corrige() -> None:
    """C'est ainsi que le pile-in muet se manifestait : la figurine n'est pas là où on la croit."""
    st = _state()
    _apply_state_snapshot(st, "1[1#0@(9,44,z0):2 1#1@(7,47,z0):1] 101[101#5@(4,49,z0):2]")

    assert st.stats["state_resync"]["pos_mismatch"] == 1
    assert st.positions_by_model["1"]["1#0"] == (9, 44)
    assert st.heights_by_model["1"]["1#0"] == 0.0


def test_unite_tuee_a_tort_est_comptee_puis_ressuscitee() -> None:
    st = _state()
    st.unit_hp["101"] = 0
    _apply_state_snapshot(st, "1[1#0@(5,48,z0):2 1#1@(7,47,z0):1] 101[101#5@(4,49,z0):2]")

    assert st.stats["state_resync"]["alive_missed"] == 1
    assert st.unit_hp["101"] == 2
    assert "101" not in st.dead_units_current_episode


def test_unite_jamais_deployee_nest_pas_un_fantome() -> None:
    """Une escouade en réserves (20.01) n'a pas d'entrée côté moteur : l'absence est normale.

    La compter ferait sonner 2.8 sur toute partie à réserves — un compteur qui crie sans raison
    finit ignoré, et c'est la panne dont il est censé protéger.
    """
    st = _state()
    st.unit_hp["7"] = 2               # déclarée à l'entête, jamais posée
    st.unit_models_alive["7"] = 3
    # Sentinelle hors table (20.01) : c'est ainsi que l'entête déclare une escouade en réserves.
    st.positions_by_model["7"] = {"7#0": (-1, -1), "7#1": (-1, -1)}
    _apply_state_snapshot(st, "1[1#0@(5,48,z0):2 1#1@(7,47,z0):1] 101[101#5@(4,49,z0):2]")

    assert st.stats["state_resync"]["dead_missed"] == 0
    # Et surtout : elle reste VIVANTE. La tuer ici la ferait « ressusciter » à son ingress move,
    # et tous les contrôles la concernant seraient faussés entre les deux.
    assert st.unit_hp["7"] == 2
    assert "7" not in st.dead_units_current_episode


# ── 2. Le BFS distingue le TRANSIT du PLACEMENT ─────────────────────────────────────────────

def test_case_darrivee_occupee_reste_joignable() -> None:
    """Le chevauchement est une faute, mais ce n'est PAS un dépassement de budget.

    Confondre les deux faisait rendre « au-delà du budget » sur des charges dont le chemin valait
    exactement la distance à vol d'oiseau. Le chevauchement est mesuré par le contrôle de
    collision (2.2), avec son propre nom.
    """
    walls: set = set()
    occupied = {(4, 49)}
    assert an._bfs_shortest_path_length(5, 48, 4, 49, 4, walls, occupied, set()) == 1
    # …mais une case occupée reste infranchissable EN TRANSIT.
    blocked = {(5, 49), (4, 48), (4, 49), (5, 47), (6, 48), (6, 47), (4, 50)}
    assert an._bfs_shortest_path_length(5, 48, 3, 50, 3, walls, blocked, set()) is None


# ── 3. Plafond d'attaques par FIGURINE ──────────────────────────────────────────────────────

def _cap(state: AnalyzerState, config, action_desc: str, n_models: int = 6) -> int:
    from ai.analyzer_phases.fight_handler import _cc_cap_for_line, _shooter_models
    return _cc_cap_for_line(
        state, config, action_desc, "105", "Intercessor", "Close Combat Weapon", 3, n_models,
        _shooter_models(action_desc),
    )


class _Cfg:
    def __init__(self, limits):
        self.unit_attack_limits = limits
        self.cc_nb_by_weapon_global = {}


def test_plafond_suit_la_datasheet_de_la_figurine_qui_frappe() -> None:
    """L'Ancient rattaché porte une arme NB=5 ; l'Intercessor porteur, NB=3."""
    st = AnalyzerState(stats={})
    st.model_types = {"105#6": "Ancient", "105#0": "Intercessor"}
    cfg = _Cfg({
        "Intercessor": {"cc_nb_by_weapon": {"Close Combat Weapon": 3}},
        "Ancient": {"cc_nb_by_weapon": {"Close Combat Weapon": 5}},
    })
    assert _cap(st, cfg, "[SHOOTER_MODELS: 105#6]") == 5
    assert _cap(st, cfg, "[SHOOTER_MODELS: 105#0]") == 3
    assert _cap(st, cfg, "[SHOOTER_MODELS: 105#0 105#6]") == 8


def test_waaagh_ajoute_une_attaque_par_figurine() -> None:
    """24 (ORKS) : « add 1 to the Strength and Attacks characteristics of melee weapons ».

    Le moteur l'appliquait sans le dire — un WarTrakk (Choppa NB=5) portait 6 attaques et
    l'analyzer plafonnait à 5.
    """
    st = AnalyzerState(stats={})
    st.model_types = {"105#0": "WarTrakk"}
    cfg = _Cfg({"WarTrakk": {"cc_nb_by_weapon": {"Close Combat Weapon": 5}}})
    assert _cap(st, cfg, "[SHOOTER_MODELS: 105#0]") == 5
    assert _cap(st, cfg, "FOUGHT [WAAAGH!] ... [SHOOTER_MODELS: 105#0]") == 6


def test_repli_explicite_sur_le_type_descouade_sans_MODEL_TYPES() -> None:
    """Journal antérieur au format : même mesure qu'avant, sur la donnée qu'il porte.

    Ce n'est pas un défaut masqué — c'est l'absence d'une donnée neuve, et le repli est écrit.
    """
    st = AnalyzerState(stats={})   # model_types vide
    cfg = _Cfg({"Intercessor": {"cc_nb_by_weapon": {"Close Combat Weapon": 3}}})
    assert _cap(st, cfg, "[SHOOTER_MODELS: 105#6]", n_models=6) == 18
