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
from ai.analyzer_config import AnalyzerConfig
from ai.analyzer_state import AnalyzerState
from tests.unit.ai._fabriques import analyzer_config


def _state() -> AnalyzerState:
    stats: Dict[str, Any] = {"state_resync": {"dead_missed": 0, "alive_missed": 0, "pos_mismatch": 0}}
    st = AnalyzerState(stats=stats)
    st.unit_hp = {"1": 2, "101": 2}
    st.unit_models_alive = {"1": 2, "101": 1}
    st.positions_by_model = {"1": {"1#0": (5, 48), "1#1": (7, 47)}, "101": {"101#5": (4, 49)}}
    return st


class _Registry:
    """Registry VIDE, et c'est exact ici : ces fixtures ne renseignent pas ``model_types``, donc
    le recalage des PV par figurine lit les PV de l'instantané et ne consulte aucune datasheet.
    Un registry peuplé n'ajouterait rien et masquerait cette dépendance."""

    units: Dict[str, Any] = {}


def _config() -> AnalyzerConfig:
    return analyzer_config(unit_registry=_Registry())


# ── 1. Recalage sur l'instantané d'état ─────────────────────────────────────────────────────

def test_mort_non_vue_est_comptee_puis_corrigee() -> None:
    """Le fantôme : l'analyzer croit l'unité vivante, le moteur ne la voit plus.

    C'est la forme exacte des 76 « action sur une unité morte » : la blessure qui a tué 101 a été
    écartée faute d'allocataire, donc écrite sans `Dmg:`, donc jamais soustraite.
    """
    st = _state()
    _apply_state_snapshot(st, _config(), "1[1#0@(5,48,z0):2 1#1@(7,47,z0):1]")

    assert st.stats["state_resync"]["dead_missed"] == 1
    assert st.unit_hp["101"] == 0
    assert st.unit_models_alive["101"] == 0
    assert "101" not in st.positions_by_model
    assert "101" in st.dead_units_current_episode


def test_fantome_enregistre_unit_deaths_quand_phase_connue() -> None:
    """La mort fantôme doit figurer dans unit_deaths pour que les vérifications de timing tiennent.

    Sans cette entrée, les handlers (charge, shoot, fight) qui itèrent unit_deaths ne voient pas
    l'unité comme morte : un tir sur une cible tuée par Hazardous dans la même phase passe vert à
    tort. On vérifie les deux cas : phase connue → entrée ajoutée ; phase inconnue → rien.
    """
    st = _state()
    st.episode_turn = 2
    st.last_phase = "SHOOT"
    st.line_number = 150
    _apply_state_snapshot(st, _config(), "1[1#0@(5,48,z0):2 1#1@(7,47,z0):1]")

    assert len(st.unit_deaths) == 1
    assert st.unit_deaths[0] == (2, "SHOOT", "101", 150)


def test_fantome_nentree_pas_unit_deaths_sans_phase() -> None:
    """Sans phase de jeu active, ghost detection ne produit pas d'entrée inventée."""
    st = _state()
    # last_phase reste None (défaut)
    _apply_state_snapshot(st, _config(), "1[1#0@(5,48,z0):2 1#1@(7,47,z0):1]")

    assert st.unit_deaths == []


def test_deplacement_non_journalise_est_compte_puis_corrige() -> None:
    """C'est ainsi que le pile-in muet se manifestait : la figurine n'est pas là où on la croit."""
    st = _state()
    _apply_state_snapshot(st, _config(), "1[1#0@(9,44,z0):2 1#1@(7,47,z0):1] 101[101#5@(4,49,z0):2]")

    assert st.stats["state_resync"]["pos_mismatch"] == 1
    assert st.positions_by_model["1"]["1#0"] == (9, 44)
    assert st.heights_by_model["1"]["1#0"] == 0.0


def test_unite_tuee_a_tort_est_comptee_puis_ressuscitee() -> None:
    st = _state()
    st.unit_hp["101"] = 0
    _apply_state_snapshot(st, _config(), "1[1#0@(5,48,z0):2 1#1@(7,47,z0):1] 101[101#5@(4,49,z0):2]")

    assert st.stats["state_resync"]["alive_missed"] == 1
    assert st.unit_hp["101"] == 2
    assert "101" not in st.dead_units_current_episode


@pytest.mark.parametrize("positions,label", [
    (None, "jamais déployée — aucun [MODELS:] reçu, positions_by_model vide"),
    ({"7#0": (-1, -1), "7#1": (-1, -1)}, "sentinelle hors table (20.01) — entrée présente mais hors battlefield"),
])
def test_unite_hors_table_nest_pas_un_fantome(positions, label) -> None:
    """Une unité hors table n'est pas un fantôme, quelle que soit la raison de son absence.

    Deux cas légitimes : (1) aucun [MODELS:] reçu → positions_by_model vaut None ;
    (2) toutes les positions portent la sentinelle (-1,-1) → entrée présente mais hors battlefield.
    Dans les deux cas le compteur ne doit pas sonner et l'unité doit rester vivante.
    """
    st = _state()
    st.unit_hp["7"] = 2               # déclarée à l'entête, jamais posée
    st.unit_models_alive["7"] = 3
    if positions is not None:
        st.positions_by_model["7"] = positions
    _apply_state_snapshot(st, _config(), "1[1#0@(5,48,z0):2 1#1@(7,47,z0):1] 101[101#5@(4,49,z0):2]")

    assert st.stats["state_resync"]["dead_missed"] == 0
    assert st.unit_hp["7"] == 2
    assert "7" not in st.dead_units_current_episode


# ── 2. Le BFS distingue le TRANSIT du PLACEMENT ─────────────────────────────────────────────

def test_case_darrivee_occupee_reste_joignable() -> None:
    """Le chevauchement est une faute, mais ce n'est PAS un dépassement de budget.

    Confondre les deux faisait rendre « au-delà du budget » sur des charges dont le chemin valait
    exactement la distance à vol d'oiseau. Le chevauchement est mesuré par le contrôle de
    collision (2.2), avec son propre nom.
    """
    # Le BFS borne son champ au plateau du run (03.01) : hors `parse_step_log`, aucune entête
    # `Board:` ne l'a posé et le getter LÈVE plutôt que de retomber sur le config courant. On le
    # pose donc ici, comme les autres tests qui appellent le BFS à la main — sans quoi ce test ne
    # passait que derrière un voisin qui l'avait laissé au module (mesuré rouge en `-n 16`).
    # 60×60 contient largement les hexes ci-dessous : le bord ne participe à aucun verdict ici.
    an.set_analyzer_board_dims(60, 60)
    walls: set = set()
    occupied = {(4, 49)}
    assert an._bfs_shortest_path_length(5, 48, 4, 49, 4, walls, occupied, set()) == 1
    # …mais une case occupée reste infranchissable EN TRANSIT.
    blocked = {(5, 49), (4, 48), (4, 49), (5, 47), (6, 48), (6, 47), (4, 50)}
    assert an._bfs_shortest_path_length(5, 48, 3, 50, 3, walls, blocked, set()) is None


# ── 3. Plafond d'attaques par FIGURINE ──────────────────────────────────────────────────────

def _cap(state: AnalyzerState, config: AnalyzerConfig, action_desc: str, n_models: int = 6) -> int:
    from ai.analyzer_perfig import parse_shooter_models_segment
    from ai.analyzer_phases.fight_handler import _cc_cap_for_line
    # Cible de 1 figurine et arme sans [CLEAVE] : le plafond rendu est celui du seul NB
    # par figurine, ce que ces verrous mesurent. Cf. test_analyzer_effects_snapshot.py.
    cap, _ = _cc_cap_for_line(
        state, config, action_desc, 1, "Intercessor", "Close Combat Weapon", 3, n_models,
        parse_shooter_models_segment(action_desc), 1,
    )
    return cap


def test_plafond_suit_la_datasheet_de_la_figurine_qui_frappe() -> None:
    """L'Ancient rattaché porte une arme NB=5 ; l'Intercessor porteur, NB=3."""
    st = AnalyzerState(stats={})
    st.model_types = {"105#6": "Ancient", "105#0": "Intercessor"}
    cfg = analyzer_config(unit_attack_limits={
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
    cfg = analyzer_config(unit_attack_limits={"WarTrakk": {"cc_nb_by_weapon": {"Close Combat Weapon": 5}}})
    assert _cap(st, cfg, "[SHOOTER_MODELS: 105#0]") == 5
    # Le bonus vient desormais de la ligne `EFFECTS`, plus d'un token recopie sur chaque attaque :
    # c'est une propriete d'ARMEE, et le token ne portait aucune notion de camp.
    st.active_effects = {1: {"waaagh_melee_atk": "+1"}}
    assert _cap(st, cfg, "[SHOOTER_MODELS: 105#0]") == 6


def test_repli_explicite_sur_le_type_descouade_sans_MODEL_TYPES() -> None:
    """Journal antérieur au format : même mesure qu'avant, sur la donnée qu'il porte.

    Ce n'est pas un défaut masqué — c'est l'absence d'une donnée neuve, et le repli est écrit.
    """
    st = AnalyzerState(stats={})   # model_types vide
    cfg = analyzer_config(unit_attack_limits={"Intercessor": {"cc_nb_by_weapon": {"Close Combat Weapon": 3}}})
    assert _cap(st, cfg, "[SHOOTER_MODELS: 105#6]", n_models=6) == 18
