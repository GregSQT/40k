"""Les estimations de dégâts lisent la cible EFFECTIVE, pas sa datasheet.

Le défaut corrigé le 2026-09-10 était une ASYMÉTRIE dans une seule fonction : `expected_damage`
appliquait déjà le Waaagh! de l'ATTAQUANT (+1 S, +1 A) mais lisait `target_unit["T"]` et
`target_unit["INVUL_SAVE"]` bruts — donc le profil du soldat de base tel qu'il sort du roster.
Elle mentait sur deux règles que la résolution, elle, applique :

  * 19.02 — la blessure se résout contre la plus haute T des figurines bodyguard
    (`_target_highest_bodyguard_toughness`), bonus `toughness_bonus_while_waaagh` compris ;
  * 05.04 / 19.04 — la sauvegarde se compare à l'invulnérable EFFECTIVE
    (`effective_invul_save`), qui inclut le 5+ du Waaagh! (08.04) et les `invul_save_override`
    conférés à toute l'unité par une règle (Waaagh! Banner du BannerNob → 5+).

Mesure d'origine sur {5 Boyz + BannerNob attaché}, bolt rifle d'Intercessor : 0,37037 dégât
espéré annoncé contre 0,29630 réellement résolu — 25,0 % de surestimation, DÈS LE TOUR 1,
puisque le BannerNob confère sa 5+ en permanence.

Le second verrou porte sur la FORME du cache des bots. `squad_expected_damage` lisait une
valeur figée au reset : sa clé défensive était tamponnée à l'initialisation des unités
(`_wdc_def_key`), si bien qu'aucun effet s'activant EN COURS DE PARTIE ne pouvait l'atteindre.
`test_le_waaagh_change_les_degats_esperes_des_bots` est le test que l'ancienne forme ne peut
pas passer : il appelle le Waaagh! ENTRE deux lectures.

Datasheets (`Documentation/40k_rules/Armageddon/Datasheets - Orks.pdf`) :
  Boyz      T5, Sv5+, aucune invulnérable ; BannerNob T5, Sv4+, InSv5+, `invul_save_override` 5
  et `toughness_bonus_while_waaagh` +1, tous deux conférés à l'unité attachée par 19.04.
  Intercessor : bolt rifle ATK3+, S4, AP-1, NB2, DMG1.
"""
from __future__ import annotations

from typing import Any, Dict, List

import pytest

from engine.game_state import call_waaagh
from engine.utils.expected_damage import expected_damage
from engine.weapon_damage_cache import squad_expected_damage
from tests.unit.engine._config_helpers import (
    attached_scenario,
    load_engine_from_scenario,
)

#: 5 Boyz — l'escouade bodyguard. Cinq figurines alignées, aucune contrainte géométrique :
#: seules les caractéristiques comptent ici.
_BOYZ: Dict[str, Any] = {
    "id": 101, "unit_type": "Boyz", "player": 2, "col": 12, "row": 10,
    "models": [{"col": 12 + i, "row": 10} for i in range(5)],
}
#: Le BannerNob attaché — la source des deux règles de 19.04 testées ici.
_NOB: Dict[str, Any] = {
    "id": 102, "unit_type": "BannerNob", "player": 2, "attached_squad": 101,
    "col": 17, "row": 10,
}
#: L'attaquant : un Intercessor et son bolt rifle.
_ENEMY: Dict[str, Any] = {"id": 1, "unit_type": "Intercessor", "player": 1, "col": 3, "row": 3}

#: Arme SYNTHÉTIQUE de Force 5. Elle existe parce qu'aucune arme du couple ne discrimine T5 de
#: T6 : S4 blesse à 5+ contre les deux. S5 blesse à 4+ contre T5 et à 5+ contre T6 — c'est la
#: seule façon de rendre le +1 T du Waaagh! OBSERVABLE sur l'espérance de dégâts.
_S5_WEAPON: Dict[str, Any] = {
    "ATK": 3, "STR": 5, "AP": 0, "NB": 1, "DMG": 1,
    "WEAPON_RULES": [], "code": "test_s5", "display_name": "Test S5",
}


def _engine(units: List[Dict[str, Any]]):
    """Moteur sur un scénario ORKS vs ADEPTUS ASTARTES, épisode réinitialisé.

    La faction d'armée du joueur 2 est déclarée ORKS : 08.04 l'exige pour que `call_waaagh`
    soit recevable, et `unit_has_waaagh_ability` la relit à chaque effet.
    """
    scenario = attached_scenario(units)
    scenario["army_faction"] = {"1": "ADEPTUS ASTARTES", "2": "ORKS"}
    engine = load_engine_from_scenario(scenario)
    engine.reset()
    return engine


def test_expected_damage_voit_l_invulnerable_conferee_par_19_04() -> None:
    """LE verrou du défaut d'origine, sans aucun Waaagh! : la 5+ du BannerNob compte.

    Bolt rifle ATK3+, S4, AP-1, NB2, DMG1 contre les Boyz (T5, Sv5+) menés par le BannerNob.
      - sauvegarde d'armure modifiée : 5 - (-1) = 6+ ;
      - invulnérable EFFECTIVE : 5+ (`invul_save_override` du Waaagh! Banner, 19.04) ;
      - 05.04 retient la meilleure des deux → seuil 5+, et non 6+.
    Lire `INVUL_SAVE` brut (7 = aucune) donnerait 0,37037 : 25,0 % de trop.
    """
    engine = _engine([_BOYZ, _NOB, _ENEMY])
    gs = engine.game_state
    cible = gs["unit_by_id"]["101"]
    attaquant = gs["unit_by_id"]["1"]
    bolt_rifle = attaquant["RNG_WEAPONS"][0]

    # La datasheet de l'escouade dit bien « aucune invulnérable » : c'est cette valeur-là que
    # la fonction lisait, et c'est ce qui rend le test discriminant.
    assert int(cible["INVUL_SAVE"]) == 7

    assert expected_damage(bolt_rifle, cible, attaquant, gs, is_melee=False) == pytest.approx(
        8.0 / 27.0
    )


def test_expected_damage_voit_la_toughness_19_02_augmentee_par_le_waaagh() -> None:
    """Le +1 T conféré à l'unité attachée (19.02 + `toughness_bonus_while_waaagh`) est lu.

    Arme S5 contre les Boyz : T5 → blessure à 4+ ; T6 → blessure à 5+. La chute d'espérance
    (2/9 → 4/27) ne peut venir que de la T, l'invulnérable étant déjà 5+ dans les deux cas.
    """
    engine = _engine([_BOYZ, _NOB, _ENEMY])
    gs = engine.game_state
    cible = gs["unit_by_id"]["101"]
    attaquant = gs["unit_by_id"]["1"]

    avant = expected_damage(_S5_WEAPON, cible, attaquant, gs, is_melee=False)
    call_waaagh(gs, 2)
    apres = expected_damage(_S5_WEAPON, cible, attaquant, gs, is_melee=False)

    assert avant == pytest.approx(2.0 / 9.0)
    assert apres == pytest.approx(4.0 / 27.0)


def test_les_bots_voient_l_invulnerable_conferee_par_19_04() -> None:
    """Même verrou, côté table pré-calculée : `squad_expected_damage` est le lecteur des bots.

    Sa clé défensive était tamponnée à l'initialisation des unités — mesurée à (5, 5, 7) là où
    la résolution joue (5, 5, 5). Toutes les décisions de tous les bots portaient donc cette
    surestimation de 25,0 %.
    """
    engine = _engine([_BOYZ, _NOB, _ENEMY])
    gs = engine.game_state

    assert squad_expected_damage(gs, "1", "101", True) == pytest.approx(0.296296, abs=1e-6)


def test_le_waaagh_change_les_degats_esperes_des_bots() -> None:
    """LE verrou de la FORME du cache : un effet activé EN COURS DE PARTIE doit être vu.

    Boyz SEULS, sans BannerNob : leur invulnérable est bien « aucune » au tour 1, et le Waaagh!
    (08.04) leur confère une 5+ quand il est appelé. Le seuil passe de 6+ (armure 5+ modifiée
    par AP-1) à 5+, donc l'espérance de 0,37037 à 0,296296.

    Aucune valeur pré-calculée au reset ne peut passer ce test : c'est exactement ce que
    l'ancienne forme du cache faisait, et elle rendait deux fois 0,37037.
    """
    engine = _engine([_BOYZ, _ENEMY])
    gs = engine.game_state

    avant = squad_expected_damage(gs, "1", "101", True)
    call_waaagh(gs, 2)
    apres = squad_expected_damage(gs, "1", "101", True)

    assert avant == pytest.approx(0.37037, abs=1e-6)
    assert apres == pytest.approx(0.296296, abs=1e-6)


def test_une_cible_sans_figurine_vivante_leve() -> None:
    """T1 : estimer les dégâts contre une escouade morte est un désynchronisme, pas un zéro.

    Le cache est bâti au reset et gardait ses entrées pour une escouade détruite depuis : il
    rendait des dégâts contre un mort. Le profil défensif étant désormais relu dans l'état,
    l'absence de figurine vivante lève — ce que tous les appelants du dépôt évitent déjà en
    n'interrogeant que des ennemis vivants.
    """
    engine = _engine([_BOYZ, _ENEMY])
    gs = engine.game_state
    for model_id in list(gs["squad_models"]["101"]):
        gs["models_cache"].pop(model_id, None)

    with pytest.raises(ValueError, match="sans figurine vivante"):
        squad_expected_damage(gs, "1", "101", True)


# ─────────────────────────────────────────────────────────────────────────────
# Jumeaux : les DEUX heuristiques de choix d'arme du moteur
#
# `_ranged_profile_expected_damage` (choix du profil d'un combi au tir) et
# `squad_declare_fight` (choix de l'arme de mêlée d'une figurine) notaient déjà leurs armes
# contre l'invulnérable EFFECTIVE, mais contre la T de la FIGURINE ÉCHANTILLON — donc sans
# 19.02 ni `toughness_bonus_while_waaagh`. Mesuré le 2026-09-10 sur {5 Boyz + BannerNob},
# Waaagh! actif : T5 lue par les deux heuristiques, T6 résolue par le moteur.
# ─────────────────────────────────────────────────────────────────────────────


def test_le_score_de_profil_de_tir_note_contre_la_toughness_19_02() -> None:
    """Le choix du profil de combi note l'arme contre la T que la résolution appliquera.

    Arme S5, AP0, NB1, DMG1, ATK3+ contre {5 Boyz + BannerNob}, Waaagh! actif :
      - T6 (19.02 + `toughness_bonus_while_waaagh`) → blessure à 5+ → 4/27 ;
      - T5 (figurine échantillon) → blessure à 4+ → 2/9, soit 50 % de trop.
    La sauvegarde vaut 5+ dans les deux cas (armure 5+, AP0, invulnérable effective 5+), donc
    l'écart ne peut venir que de la T.
    """
    from engine.phase_handlers.shared_utils import _ranged_profile_expected_damage

    engine = _engine([_BOYZ, _NOB, _ENEMY])
    gs = engine.game_state
    call_waaagh(gs, 2)

    score = _ranged_profile_expected_damage(
        gs, _S5_WEAPON, "101", gs["unit_by_id"]["1"]
    )

    assert score == pytest.approx(4.0 / 27.0)


#: Deux armes de mêlée dont le classement S'INVERSE entre T5 et T6, seul moyen d'observer la T
#: retenue par `squad_declare_fight` sur son RÉSULTAT (l'arme déclarée) :
#:   T5 → S5 blesse à 4+ et S6 à 3+ : 7 × 6/36 = 0,7778 contre 5 × 8/36 = 0,7407, la S5 gagne ;
#:   T6 → S5 blesse à 5+ et S6 à 4+ : 7 × 4/36 = 0,5185 contre 5 × 6/36 = 0,5556, la S6 gagne.
_CC_S5: Dict[str, Any] = {
    "ATK": 3, "STR": 5, "AP": 0, "NB": 7, "DMG": 1,
    "WEAPON_RULES": [], "code": "cc_s5", "display_name": "Choppa S5",
}
_CC_S6: Dict[str, Any] = {
    "ATK": 3, "STR": 6, "AP": 0, "NB": 5, "DMG": 1,
    "WEAPON_RULES": [], "code": "cc_s6", "display_name": "Choppa S6",
}


def test_le_choix_d_arme_de_melee_note_contre_la_toughness_19_02(monkeypatch) -> None:
    """JUMEAU MÊLÉE : `squad_declare_fight` déclare l'arme qui gagne contre la VRAIE T.

    La cible porte `toughness_bonus_while_waaagh` (+1 T à toute l'unité, 19.04) et son Waaagh!
    est actif : ses figurines sont T5, la blessure se résout contre T6. L'arme déclarée doit
    donc être la S6 (index 1) ; noter contre la T de la figurine échantillon déclarerait la S5
    (index 0), et le moteur résoudrait ensuite avec l'arme perdante.
    """
    from engine.phase_handlers import shared_utils
    from tests._state_invariants import turn_state_invariants

    monkeypatch.setattr(shared_utils, "get_fighting_models", lambda gs, sid, tid=None: ["A1"])
    attaquant = {
        "id": "A1", "squad_id": "1", "player": 1, "ATTACK_LEFT": 0,
        "CC_WEAPONS": [_CC_S5, _CC_S6],
    }
    cible = {
        "id": "T1", "squad_id": "2", "player": 2, "T": 5, "ARMOR_SAVE": 3,
        "INVUL_SAVE": 7, "HP_MAX": 3, "role": None,
    }
    unite_cible = {
        "id": "2", "player": 2,
        "UNIT_KEYWORDS": [{"keywordId": "INFANTRY"}],
        "FACTION_KEYWORDS": [{"keywordId": "ORKS"}],
        "UNIT_RULES": [{
            "ruleId": "toughness_bonus_while_waaagh",
            "displayName": "Waaagh! Banner (T+1)",
            "rule_args": {"toughness_bonus": 1},
        }],
    }
    gs: Dict[str, Any] = {
        **turn_state_invariants(),
        "models_cache": {"A1": attaquant, "T1": cible},
        "squad_models": {"1": ["A1"], "2": ["T1"]},
        "pending_squad_fight_intents": {"1": []},
        "pending_squad_shoot_intents": {},
        "unit_by_id": {
            "1": {"id": "1", "player": 1, "UNIT_KEYWORDS": [], "FACTION_KEYWORDS": [],
                  "UNIT_RULES": []},
            "2": unite_cible,
        },
        "config": {
            "game_rules": {"bonus_malus_cap": 0},
            "army_faction": {"1": "ADEPTUS ASTARTES", "2": "ORKS"},
            "uses_codex_detachment": {"1": True, "2": True},
        },
        "waaagh_active": {1: False, 2: True},
        # `army_faction` valide la faction DÉCLARÉE contre les unités présentes : la liste est
        # donc exigée, et l'unité cible doit y porter le mot-clé ORKS.
        "units": [
            {"id": "1", "player": 1, "FACTION_KEYWORDS": [{"keywordId": "ADEPTUS ASTARTES"}]},
            unite_cible,
        ],
    }

    intents = shared_utils.squad_declare_fight(gs, "1", "2")

    assert [i["weapon_index"] for i in intents] == [1]
    assert attaquant["selectedCcWeaponIndex"] == 1
