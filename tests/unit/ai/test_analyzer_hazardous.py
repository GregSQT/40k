"""Tests TROU 1 : ligne `hazardous` (24.15) — lecteur de l'analyzer.

Comportements verrouillés :
- `hazardous_mortal_wounds[player]` est incrémenté du nombre de BM journalisées.
- `hazardous_no_hazardous_weapon[player]` est incrémenté si aucun type de l'escouade
  ne porte une arme HAZARDOUS dans la cache armurerie, ET que la ligne est en phase SHOOTING.
- `hazardous_no_hazardous_weapon_fight[player]` est incrémenté si la même erreur arrive
  en phase FIGHT.
- La présence d'une arme HAZARDOUS dans la cache supprime l'erreur.
- Sans ligne HAZARDOUS, les compteurs restent à 0.
"""
from __future__ import annotations

import pytest

from tests.unit.ai._fabriques import entete_step_log
from tests.unit.ai._fabriques import analyzer_config as fab_config

_OBJECTIVES = ";".join(f"(30,{r})" for r in range(30, 33))


class _Registry:
    """Registry minimal : HP_MAX/MOVE/MODEL_HEIGHT suffisent pour l'entête d'unité."""
    units = {
        "HazUnit": {
            "HP_MAX": 3,
            "MOVE": 6,
            "MODEL_HEIGHT": 1.0,
            "UNIT_RULES": [],
        },
    }

# Unité 1 (P1) déployée en (20,20) avec HP_MAX=3.
# Type "HazUnit" : inconnu de la config réelle → weapons_cache["HazUnit"] sera None.
_UNITS = (
    "[10:00:00] Unit 1 (HazUnit) P1: Starting position (20,20), HP_MAX=3 base=round/1\n"
    "[10:00:00] Unit 101 (HazUnit) P2: Starting position (21,21), HP_MAX=3 base=round/1\n"
)

# Grammaire : `Unit N(c,r) SUFFERS X Mortal Wounds [HAZARDOUS]` — §1.2 de analyzer_couverture.md.
# La ligne est émise dans la phase SHOOTING (après résolution des attaques de tir) ou FIGHT.
_HAZARDOUS_3_MW = (
    "[10:00:02] E1 T1 P1 SHOOTING : Unit 1(20,20) SUFFERS 3 Mortal Wounds [HAZARDOUS] "
    "[R:+0.0] [SUCCESS]\n"
)
_HAZARDOUS_FIGHT = (
    "[10:00:02] E1 T1 P1 FIGHT : Unit 1(20,20) SUFFERS 2 Mortal Wounds [HAZARDOUS] "
    "[R:+0.0] [SUCCESS]\n"
)

_END = (
    "[10:00:08] T1 OBJECTIVE CONTROL: VP1=0 VP2=0 CP1=0 CP2=0 ZONES=rect b NW:Ctrl=none\n"
    "[10:00:09] EPISODE END: Winner=2, Method=objectives, Actions=0, Steps=0, "
    "Total=0, Duration=1.000s\n"
)

# 09.07 Desperate Escape : grammaire identique à HAZARDOUS avec tag [DESPERATE ESCAPE].
# Unité 1 (HP_MAX=3) reçoit 3 BM en MOVE → elle meurt.
# Une 2e DESPERATE ESCAPE en SHOOT sur la même unité morte lève damage_missing_unit_hp.
# La branche DE utilise _dmg_actor_id (correct) et non action_unit_id (stale après header 101).
# Phase MOVE ≠ SHOOT exclut le garde "excess wound lost" (05) basé sur kill_context.
_DESPERATE_ESCAPE_3_MW = (
    "[10:00:02] E1 T1 P1 MOVE : Unit 1(20,20) SUFFERS 3 Mortal Wounds [DESPERATE ESCAPE] "
    "[R:+0.0] [SUCCESS]\n"
)
_DESPERATE_ESCAPE_SHOOT_1_MW = (
    "[10:00:03] E1 T1 P1 SHOOT : Unit 1(20,20) SUFFERS 1 Mortal Wounds [DESPERATE ESCAPE] "
    "[R:+0.0] [SUCCESS]\n"
)
# Branche HAZARDOUS sur unité déjà morte : phase SHOOTING ≠ phase MOVE du kill_context
# → damage_missing_unit_hp doit être incrémenté (pas "excess wound lost").
_HAZARDOUS_SHOOT_1_MW = (
    "[10:00:03] E1 T1 P1 SHOOTING : Unit 1(20,20) SUFFERS 1 Mortal Wounds [HAZARDOUS] "
    "[R:+0.0] [SUCCESS]\n"
)


def _parse(tmp_path, monkeypatch, body: str = "", weapons_cache=None):
    """Parse step.log en injectant une cache armurerie contrôlée.

    `parse_step_log` charge sa config via `from ai.analyzer_config import load_analyzer_config`
    (import local dans la fonction) : le monkeypatch cible le SYMBOLE dans le MODULE SOURCE,
    ce que la liaison locale re-lit à chaque appel.
    """
    import ai.analyzer as an
    import ai.analyzer_config as ac_mod

    cfg = fab_config(
        unit_registry=_Registry(),
        unit_weapons_cache=weapons_cache if weapons_cache is not None else {},
    )
    monkeypatch.setattr(ac_mod, "load_analyzer_config", lambda: cfg)

    log = tmp_path / "step.log"
    log.write_text(entete_step_log(
        body,
        inches_to_subhex=1,
        board="cols=40 rows=40",
        objectives=_OBJECTIVES,
        units=_UNITS,
    ))
    return an.parse_step_log(str(log))


def test_hazardous_mortal_wounds_counter(tmp_path, monkeypatch):
    """VERROU : supprimer la branche HAZARDOUS de l'analyzer rend ce test ROUGE."""
    stats = _parse(tmp_path, monkeypatch, _HAZARDOUS_3_MW)
    assert stats["hazardous_mortal_wounds"][1] == 3, (
        "la ligne HAZARDOUS doit incrémenter hazardous_mortal_wounds du joueur 1 de 3"
    )
    assert stats["hazardous_mortal_wounds"][2] == 0


def test_hazardous_no_weapon_flagged_when_cache_empty(tmp_path, monkeypatch):
    """Sans arme HAZARDOUS dans la cache, `hazardous_no_hazardous_weapon` est incrémenté.

    Cache vide → `weapons_cache.get("HazUnit")` = None → aucun profil connu → erreur.
    Ce comportement verrouille que le manque de donnée est signalé, pas ignoré.
    """
    stats = _parse(tmp_path, monkeypatch, _HAZARDOUS_3_MW, weapons_cache={})
    assert stats["hazardous_no_hazardous_weapon"][1] == 1, (
        "avec une cache vide, aucun type ne porte d'arme HAZARDOUS : l'erreur doit être signalée"
    )


def test_hazardous_no_error_when_weapon_in_cache(tmp_path, monkeypatch):
    """Avec arme HAZARDOUS dans la cache, `hazardous_no_hazardous_weapon` reste à 0."""
    cache = {
        "HazUnit": [{"name": "Plasma Gun", "rules": ["HAZARDOUS"], "is_melee": False}],
    }
    stats = _parse(tmp_path, monkeypatch, _HAZARDOUS_3_MW, weapons_cache=cache)
    assert stats["hazardous_no_hazardous_weapon"][1] == 0, (
        "HazUnit porte un Plasma Gun HAZARDOUS : l'erreur ne doit pas être signalée"
    )


def test_no_hazardous_no_counter(tmp_path, monkeypatch):
    """Sans ligne HAZARDOUS, les trois compteurs restent à 0."""
    stats = _parse(tmp_path, monkeypatch)
    assert stats["hazardous_mortal_wounds"] == {1: 0, 2: 0}
    assert stats["hazardous_no_hazardous_weapon"] == {1: 0, 2: 0}
    assert stats["hazardous_no_hazardous_weapon_fight"] == {1: 0, 2: 0}


def test_hazardous_fight_phase_goes_to_fight_counter(tmp_path, monkeypatch):
    """VERROU finding 1 : HAZARDOUS déclenché en FIGHT phase → compteur fight, pas shoot.

    Supprimer la branche `phase == 'fight'` dans analyzer_core rend ce test ROUGE.
    """
    stats = _parse(tmp_path, monkeypatch, _HAZARDOUS_FIGHT, weapons_cache={})
    assert stats["hazardous_no_hazardous_weapon_fight"][1] == 1, (
        "erreur HAZARDOUS en FIGHT doit incrémenter hazardous_no_hazardous_weapon_fight"
    )
    assert stats["hazardous_no_hazardous_weapon"][1] == 0, (
        "erreur HAZARDOUS en FIGHT ne doit PAS incrémenter hazardous_no_hazardous_weapon (shoot)"
    )


# PROJ.1.2 faux positifs — Desperate Escape 09.07 produit [DESPERATE ESCAPE], pas [HAZARDOUS].
# L'analyzer ne doit pas comptabiliser ces lignes comme des erreurs HAZARDOUS.
_DESPERATE_ESCAPE_MW = (
    "[10:00:02] E1 T1 P1 MOVE : Unit 1(20,20) SUFFERS 2 Mortal Wounds [DESPERATE ESCAPE] "
    "[R:+0.0] [SUCCESS]\n"
)
# Coup fatal : 3 BM sur une unité à HP_MAX=3 → doit tuer l'unité et alimenter current_episode_deaths.
_DESPERATE_ESCAPE_FATAL = (
    "[10:00:02] E1 T1 P1 MOVE : Unit 1(20,20) SUFFERS 3 Mortal Wounds [DESPERATE ESCAPE] "
    "[R:+0.0] [SUCCESS]\n"
)


def test_desperate_escape_decremente_hp_et_enregistre_la_mort(tmp_path, monkeypatch):
    """VERROU : [DESPERATE ESCAPE] fatal doit appeler _apply_damage_and_handle_death.

    Avant le fix, la branche manquante laissait la ligne tomber dans action_type='other' :
    unit_hp restait à 3, current_episode_deaths restait vide → HP drift et kill tracking perdu.
    """
    stats = _parse(tmp_path, monkeypatch, _DESPERATE_ESCAPE_FATAL, weapons_cache={})
    deaths = stats["current_episode_deaths"]
    assert any(d[1] == "1" for d in deaths), (
        "L'unité 1 tuée par [DESPERATE ESCAPE] doit apparaître dans current_episode_deaths"
    )
    assert stats["hazardous_mortal_wounds"][1] == 0, (
        "[DESPERATE ESCAPE] ne doit pas incrémenter hazardous_mortal_wounds (24.15 uniquement)"
    )


def test_desperate_escape_ne_compte_pas_en_hazardous_mw(tmp_path, monkeypatch):
    """VERROU : [DESPERATE ESCAPE] (09.07) ne doit PAS incrémenter hazardous_mortal_wounds.

    Avant le fix, roll_hazard_for_unit émettait [HAZARDOUS] même pour les Desperate Escape,
    générant 337 faux positifs PROJ.1.2 ('unité sans arme HAZARDOUS').
    """
    stats = _parse(tmp_path, monkeypatch, _DESPERATE_ESCAPE_MW, weapons_cache={})
    assert stats["hazardous_mortal_wounds"][1] == 0, (
        "[DESPERATE ESCAPE] ne doit pas incrémenter hazardous_mortal_wounds (24.15 uniquement)"
    )


def test_desperate_escape_ne_declenche_pas_erreur_armurerie(tmp_path, monkeypatch):
    """VERROU : [DESPERATE ESCAPE] ne doit pas déclencher hazardous_no_hazardous_weapon.

    Peu importe si l'unité a ou non une arme HAZARDOUS dans la cache — le Desperate Escape
    est la règle 09.07, sans rapport avec 24.15.
    """
    stats = _parse(tmp_path, monkeypatch, _DESPERATE_ESCAPE_MW, weapons_cache={})
    assert stats["hazardous_no_hazardous_weapon"][1] == 0, (
        "[DESPERATE ESCAPE] ne doit pas signaler d'erreur HAZARDOUS (arme absente de l'armurerie)"
    )
    assert stats["hazardous_no_hazardous_weapon_fight"][1] == 0


def test_desperate_escape_reduit_les_pv_et_unit_morte_trackee(tmp_path, monkeypatch):
    """VERROU finding 2 : [DESPERATE ESCAPE] doit appliquer les BM à l'unité (réduire ses PV).

    Sans le fix : la branche DESPERATE ESCAPE n'existe pas dans analyzer_core ; les deux lignes
    tombent dans action_type='other' ; unit_hp["1"] reste à 3 → damage_missing_unit_hp == 0.
    Avec le fix : 1re DE en MOVE tue l'unité (HP=3→0). 2e DE en SHOOT : _de_unit_id="1"
    (via _dmg_actor_id), unit_hp["1"] absent, kill_context MOVE ≠ SHOOT → pas excess-wound
    → damage_missing_unit_hp[1] == 1.
    """
    body = _DESPERATE_ESCAPE_3_MW + _DESPERATE_ESCAPE_SHOOT_1_MW
    stats = _parse(tmp_path, monkeypatch, body)
    assert stats["damage_missing_unit_hp"][1] == 1, (
        "[DESPERATE ESCAPE] 3 BM sur une unité HP=3 doit la détruire ; "
        "une 2e DE en SHOOT sur cette unité morte doit lever damage_missing_unit_hp"
    )


def test_desperate_escape_non_fatal_decrement_hp(tmp_path, monkeypatch):
    """VERROU finding 3 : [DESPERATE ESCAPE] non-fatal doit décrémenter les PV de l'unité.

    Sans le fix : la branche DE est absente, unit_hp["1"] reste à 3 après les 2 BM en MOVE.
    La 2e DE en SHOOT enlève 1 BM : HP 3→2, l'unité survit, current_episode_deaths reste vide.
    Avec le fix : 1re DE en MOVE réduit HP 3→1. 2e DE en SHOOT réduit HP 1→0, l'unité meurt.
    damage_missing_unit_hp reste à 0 (l'unité était vivante au moment du SHOOT).
    """
    body = _DESPERATE_ESCAPE_MW + _DESPERATE_ESCAPE_SHOOT_1_MW
    stats = _parse(tmp_path, monkeypatch, body, weapons_cache={})
    deaths = stats["current_episode_deaths"]
    assert any(d[1] == "1" for d in deaths), (
        "2 BM DE en MOVE + 1 BM DE en SHOOT sur HP_MAX=3 : l'unité doit mourir en SHOOT"
    )
    assert stats["damage_missing_unit_hp"][1] == 0, (
        "l'unité était vivante en SHOOT (HP=1 après MOVE) : damage_missing_unit_hp ne doit pas "
        "être levé"
    )


def test_hazardous_damage_applique_a_la_bonne_unite(tmp_path, monkeypatch):
    """VERROU : la BM HAZARDOUS cible l'unité de la ligne SUFFERS, pas le dernier header.

    _UNITS déclare Unit 1 (P1) puis Unit 101 (P2). Après les headers, action_unit_id = "101".
    Sans le fix : _apply_damage_and_handle_death reçoit action_unit_id = "101" comme target_id
    → Unit 101 perd 3 PV et meurt, Unit 1 reste intacte, la mort est silencieusement attribuée
    au mauvais camp.
    Avec le fix : _dmg_actor_id = "1" (préfixe Unit 1( de la ligne SUFFERS) est utilisé
    → Unit 1 meurt, Unit 101 reste intacte.
    """
    stats = _parse(tmp_path, monkeypatch, _HAZARDOUS_3_MW)
    deaths = stats["current_episode_deaths"]
    assert any(d[1] == "1" for d in deaths), (
        "Unit 1 doit être tuée par 3 BM HAZARDOUS (HP_MAX=3) — pas Unit 101"
    )
    assert not any(d[1] == "101" for d in deaths), (
        "Unit 101 ne doit pas être tuée : les dégâts HAZARDOUS de Unit 1 ne doivent pas "
        "lui être attribués via action_unit_id"
    )


def test_hazardous_sur_unite_morte_incremente_damage_missing_unit_hp(tmp_path, monkeypatch):
    """VERROU : branche HAZARDOUS sur unité déjà morte → damage_missing_unit_hp.

    Scénario : Unit 1 (HP_MAX=3) tuée par 3 BM [DESPERATE ESCAPE] en MOVE.
    Une 2e ligne HAZARDOUS (1 BM) en SHOOTING touche Unit 1 déjà morte.
    Phase SHOOTING ≠ phase MOVE du kill_context → pas "excess wound lost" →
    _apply_damage_and_handle_death doit incrémenter damage_missing_unit_hp[1].
    Sans fix (branche HAZARDOUS absente) : la ligne tombe dans action_type='other',
    _apply_damage_and_handle_death n'est pas appelé → damage_missing_unit_hp reste à 0.
    """
    body = _DESPERATE_ESCAPE_3_MW + _HAZARDOUS_SHOOT_1_MW
    stats = _parse(tmp_path, monkeypatch, body)
    assert stats["damage_missing_unit_hp"][1] == 1, (
        "HAZARDOUS 1 BM sur Unit 1 déjà morte (tuée en MOVE) doit lever damage_missing_unit_hp"
    )


# VERROU : action_unit_id stale dans la branche HAZARDOUS.
# Scénario : Unit 2 est le dernier header vu (action_unit_id = "2", type "NoHazUnit" sans arme
# HAZARDOUS), mais la ligne HAZARDOUS est émise pour Unit 1 (type "HazUnit" avec arme HAZARDOUS).
# Sans fix : le lookup armurerie porte sur "2" (NoHazUnit) → erreur signalée à tort.
# Avec fix : le lookup porte sur "1" (HazUnit, arme HAZARDOUS présente) → aucune erreur.
class _RegistryTwo:
    units = {
        "HazUnit":   {"HP_MAX": 3, "MOVE": 6, "MODEL_HEIGHT": 1.0, "UNIT_RULES": []},
        "NoHazUnit": {"HP_MAX": 3, "MOVE": 6, "MODEL_HEIGHT": 1.0, "UNIT_RULES": []},
    }

_UNITS_TWO = (
    "[10:00:00] Unit 1 (HazUnit) P1: Starting position (20,20), HP_MAX=3 base=round/1\n"
    "[10:00:00] Unit 2 (NoHazUnit) P1: Starting position (22,22), HP_MAX=3 base=round/1\n"
)
# HAZARDOUS sur Unit 1 (HazUnit), mais Unit 2 (NoHazUnit) est le dernier header vu.
_HAZARDOUS_UNIT1_AFTER_UNIT2_HEADER = (
    "[10:00:02] E1 T1 P1 SHOOTING : Unit 1(20,20) SUFFERS 1 Mortal Wounds [HAZARDOUS] "
    "[R:+0.0] [SUCCESS]\n"
)


def _parse_two(tmp_path, monkeypatch, body: str, weapons_cache=None):
    import ai.analyzer as an
    import ai.analyzer_config as ac_mod

    cfg = fab_config(
        unit_registry=_RegistryTwo(),
        unit_weapons_cache=weapons_cache if weapons_cache is not None else {},
    )
    monkeypatch.setattr(ac_mod, "load_analyzer_config", lambda: cfg)

    log = tmp_path / "step.log"
    log.write_text(entete_step_log(
        body,
        inches_to_subhex=1,
        board="cols=40 rows=40",
        objectives=_OBJECTIVES,
        units=_UNITS_TWO,
    ))
    return an.parse_step_log(str(log))


def test_hazardous_utilise_unite_de_la_ligne_pas_le_header_stale(tmp_path, monkeypatch):
    """VERROU : la branche HAZARDOUS doit lire l'ID depuis la ligne (_dmg_actor_id), pas
    le dernier header (action_unit_id).

    Unit 2 (NoHazUnit, sans arme HAZARDOUS) est le dernier header vu → action_unit_id="2".
    La ligne HAZARDOUS est émise pour Unit 1 (HazUnit, arme HAZARDOUS présente).
    Sans fix : lookup sur "2" → NoHazUnit → erreur hazardous_no_hazardous_weapon signalée.
    Avec fix : lookup sur "1" → HazUnit → arme présente → aucune erreur.
    """
    cache = {
        "HazUnit":   [{"name": "Plasma Gun", "rules": ["HAZARDOUS"], "is_melee": False}],
        "NoHazUnit": [],
    }
    stats = _parse_two(tmp_path, monkeypatch, _HAZARDOUS_UNIT1_AFTER_UNIT2_HEADER, weapons_cache=cache)
    assert stats["hazardous_no_hazardous_weapon"][1] == 0, (
        "Unit 1 (HazUnit) porte une arme HAZARDOUS : pas d'erreur attendue. "
        "Si action_unit_id stale (Unit 2 / NoHazUnit) est utilisé → faux positif."
    )


# VERROU : faux positif quand la MW HAZARDOUS tue le seul modèle porteur de l'arme HAZARDOUS.
#
# Scenario réel (VanguardVeteranSquadJumpPack + plasma model à 1 PV) :
#   - Unit 1 de type "SquadType" (sans arme HAZARDOUS dans la cache)
#   - Contient un sous-modèle "1#0" de type "PlasmaModel" (HP_MAX=1, arme HAZARDOUS)
#   - et un sous-modèle "1#1" de type "SquadType" (HP_MAX=3)
#   - "1#0" est le front (listé en premier dans [MODELS:]) : HP=1
#   - HAZARDOUS SUFFERS 1 MW → tue "1#0" (HP 1→0) → retiré de unit_model_hp
#   - Bug : le contrôle d'armurerie lit unit_model_hp APRÈS la mort → ne voit que SquadType →
#     faux positif "sans arme HAZARDOUS en armurerie".
#   - Fix : contrôle AVANT l'application des dégâts → PlasmaModel encore présent → aucune erreur.
class _RegistryMixed:
    units = {
        "SquadType":  {"HP_MAX": 3, "MOVE": 6, "MODEL_HEIGHT": 1.0, "UNIT_RULES": []},
        "PlasmaModel": {"HP_MAX": 1, "MOVE": 6, "MODEL_HEIGHT": 1.0, "UNIT_RULES": []},
    }

# PlasmaModel ("1#0") en tête de [MODELS:] → c'est le front (HP=1, non-CHARACTER en premier).
# SquadType ("1#1") en deuxième.
_UNITS_MIXED = (
    "[10:00:00] Unit 1 (SquadType) P1: Starting position (20,20), HP_MAX=3 "
    "[MODELS: 1#0@(20,20) 1#1@(20,21)] [MODEL_TYPES: 1#0=PlasmaModel 1#1=SquadType] "
    "base=round/1\n"
    "[10:00:00] Unit 101 (SquadType) P2: Starting position (21,21), HP_MAX=3 base=round/1\n"
)
_HAZARDOUS_1_MW_MIXED = (
    "[10:00:02] E1 T1 P1 SHOOTING : Unit 1(20,20) SUFFERS 1 Mortal Wounds [HAZARDOUS] "
    "[R:+0.0] [SUCCESS]\n"
)


def _parse_mixed(tmp_path, monkeypatch, body: str, weapons_cache=None):
    import ai.analyzer as an
    import ai.analyzer_config as ac_mod

    cfg = fab_config(
        unit_registry=_RegistryMixed(),
        unit_weapons_cache=weapons_cache if weapons_cache is not None else {},
    )
    monkeypatch.setattr(ac_mod, "load_analyzer_config", lambda: cfg)

    log = tmp_path / "step.log"
    log.write_text(entete_step_log(
        body,
        inches_to_subhex=1,
        board="cols=40 rows=40",
        objectives=_OBJECTIVES,
        units=_UNITS_MIXED,
    ))
    return an.parse_step_log(str(log))


def test_hazardous_pas_de_faux_positif_quand_plasma_model_meurt_sous_la_mw(tmp_path, monkeypatch):
    """VERROU : la MW HAZARDOUS qui tue le seul modèle HAZARDOUS ne doit pas lever de faux positif.

    Sans fix (contrôle APRÈS dégâts) : PlasmaModel ("1#0", HP=1) est retiré de unit_model_hp
    avant le contrôle → _all_unit_types = {"SquadType"} seulement → hazardous_no_hazardous_weapon
    incrémenté alors que l'arme était bien là (faux positif).
    Avec fix (contrôle AVANT dégâts) : PlasmaModel est encore présent → _all_unit_types contient
    "PlasmaModel" → arme HAZARDOUS trouvée → aucune erreur.
    """
    cache = {
        "SquadType":  [],
        "PlasmaModel": [{"name": "Plasma Pistol (Supercharge)", "rules": ["HAZARDOUS"], "is_melee": False}],
    }
    stats = _parse_mixed(tmp_path, monkeypatch, _HAZARDOUS_1_MW_MIXED, weapons_cache=cache)
    assert stats["hazardous_no_hazardous_weapon"][1] == 0, (
        "PlasmaModel (1#0, HP=1) porte une arme HAZARDOUS : la MW qui le tue ne doit pas "
        "déclencher hazardous_no_hazardous_weapon — le contrôle doit avoir lieu AVANT les dégâts."
    )


