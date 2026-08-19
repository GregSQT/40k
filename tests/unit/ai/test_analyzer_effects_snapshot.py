"""Les effets de règle sont DÉCLARÉS une fois, avec leur contribution — plus dérivés par ligne.

Une capacité comme Waaagh! (24) ou Oath of Moment (08.04) est vraie pour une ARMÉE pendant un
tour. Trois défauts venaient de l'avoir traitée comme une propriété d'attaque :

1. Elle était recopiée en token sur chaque ligne de mêlée. Poser ce token entre le verbe et la
   cible a cassé QUATRE grammaires de lecteurs, dont deux rattrapées par un code-review — chacune
   échouant en silence (la ligne n'est pas rejetée, elle est ignorée).
2. Oath était re-dérivé une SECONDE fois, indépendamment, sur les lignes de charge.
3. Le nom seul obligeait l'analyzer à RÉ-ENCODER la règle (« waaagh ⇒ +1 »). Deux définitions
   d'une même règle : celle du moteur (`WAAAGH_MELEE_BONUS`) et celle du lecteur, la seconde
   divergeant en silence le jour où la première bouge.

Et le volet **+1 Force** du Waaagh n'était représenté NULLE PART : un seuil de blessure amélioré
restait inexplicable pour tout contrôle futur.
"""
from __future__ import annotations

from ai.analyzer_core import _parse_effects_snapshot
from ai.analyzer_state import AnalyzerState
from tests.unit.ai._fabriques import analyzer_config


def test_les_deux_moities_du_waaagh_sont_declarees() -> None:
    """+1 Attaques ET +1 Force. La seconde n'existait dans aucune ligne du journal."""
    out = _parse_effects_snapshot(
        "P1 none | P2 waaagh=on waaagh_melee_str=+1 waaagh_melee_atk=+1"
    )
    assert out[1] == {}
    assert out[2]["waaagh_melee_atk"] == "+1"
    assert out[2]["waaagh_melee_str"] == "+1", "le +1 Force reste invisible"


def test_oath_est_porte_par_la_meme_ligne() -> None:
    """Une seule grammaire pour toutes les capacités : la suivante n'ouvrira aucun chantier."""
    out = _parse_effects_snapshot("P1 oath_target=104 oath_wound=+1 | P2 none")
    assert out[1] == {"oath_target": "104", "oath_wound": "+1"}
    assert out[2] == {}


def test_un_joueur_sans_effet_est_dit_explicitement() -> None:
    """`none` distingue « aucun effet » d'une ligne tronquée, et REMPLACE l'état précédent."""
    assert _parse_effects_snapshot("P1 none | P2 none") == {1: {}, 2: {}}


# ── Le plafond d'attaques LIT le bonus, il ne le redevine pas ──────────────────────────────

def _cap(state: AnalyzerState, player: int, line: str) -> int:
    from ai.analyzer_perfig import parse_shooter_models_segment
    from ai.analyzer_phases.fight_handler import _cc_cap_for_line
    cfg = analyzer_config(
        unit_attack_limits={"WarTrakk": {"cc_nb_by_weapon": {"Choppa": 5}}},
    )
    # Cible de 1 figurine et arme sans [CLEAVE] : aucun dé additionnel possible, le plafond
    # rendu est celui du seul NB (+ Waaagh). L'erreur de journal (2e membre) est ignorée ici —
    # elle a ses propres tests dans test_step_log_weapon_rule_tokens.py.
    cap, _ = _cc_cap_for_line(
        state, cfg, line, player, "WarTrakk", "Choppa", 5, 1, parse_shooter_models_segment(line),
        1,
    )
    return cap


def test_le_bonus_vient_de_la_ligne_deffets_pas_du_token() -> None:
    """VERROU : le token peut disparaître de la ligne d'attaque, le plafond reste juste.

    C'est tout l'objet du lot — la donnée n'est plus recopiée sur chaque attaque, donc la
    grammaire des lignes d'attaque n'a plus à bouger quand une capacité s'ajoute.
    """
    st = AnalyzerState(stats={})
    st.model_types = {"105#0": "WarTrakk"}
    line_sans_token = "FOUGHT Unit 1(2,3) with [Choppa] [SHOOTER_MODELS: 105#0]"

    st.active_effects = {}
    assert _cap(st, 2, line_sans_token) == 5

    st.active_effects = {2: {"waaagh": "on", "waaagh_melee_atk": "+1"}}
    assert _cap(st, 2, line_sans_token) == 6, "le bonus journalisé n'est pas lu"


def test_le_bonus_est_attribue_au_BON_joueur() -> None:
    """Le Waaagh d'un joueur ne relève pas le plafond de l'autre — le token par ligne, lui, ne
    portait aucune notion de camp."""
    st = AnalyzerState(stats={})
    st.model_types = {"105#0": "WarTrakk"}
    st.active_effects = {2: {"waaagh_melee_atk": "+1"}}
    line = "FOUGHT Unit 1(2,3) with [Choppa] [SHOOTER_MODELS: 105#0]"
    assert _cap(st, 2, line) == 6
    assert _cap(st, 1, line) == 5


def test_forme_du_bonus_libre_cote_producteur() -> None:
    """`+1` et `1` sont acceptés : le lecteur n'impose pas sa notation au producteur."""
    st = AnalyzerState(stats={})
    st.model_types = {"105#0": "WarTrakk"}
    line = "FOUGHT Unit 1(2,3) with [Choppa] [SHOOTER_MODELS: 105#0]"
    st.active_effects = {2: {"waaagh_melee_atk": "1"}}
    assert _cap(st, 2, line) == 6
