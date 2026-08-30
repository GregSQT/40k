"""Primitive B — effets accordés conditionnellement aux armes (chantier 06, passe 2).

Huit capacités, trois mécaniques :
  A. Accordent une règle d'arme (SUSTAINED HITS, LETHAL HITS, BLAST) en passant par UNIT_RULES
  B. Accordent un bonus d'attaques conditionnel (vs keyword, vs cible désignée, scaling)
  C. Effets une-fois-par-partie ou dépendant de l'état de jeu (Waaagh!, Finest Hour)

CE QUE CES TESTS VERROUILLENT :

- Chaque capacité n'agit QUE dans la bonne phase (mêlée vs tir), sur la bonne arme (weapon_code)
  et sous la bonne condition (charge, Waaagh! actif, once_per_battle) — les quatre pièges
  symétriques de ce dépôt.
- Le comptage d'attaques est vérifié par le nombre de records produits, pas par une assertion
  interne : le moteur produit exactement autant de records qu'il consomme de dés d'attaque.
- Les conditions négatives (règle absente, mauvaise arme, Waaagh! inactif, flag déjà posé)
  sont vérifiées explicitement pour éviter les vrais verts vacants.
"""

import random

import pytest

from engine.game_state import initial_faction_ability_state
from tests.unit.engine._roll_helpers import roll_fight_intent, roll_shoot_intent
from tests.unit.engine._state_builders import units_cache_entry as _uc

# ---------------------------------------------------------------------------
# Règles d'unité des 8 capacités — même forme exacte que les datasheets
# ---------------------------------------------------------------------------
_BREAKIN_HEADS = {"ruleId": "grant_weapon_rule_melee", "displayName": "Breakin' Heads"}

_VANGUARD_ASSAULT = {
    "ruleId": "grant_weapon_rule_melee_after_charge",
    "displayName": "Vanguard Assault",
}

_OVERLAPPING_DET = {
    "ruleId": "grant_weapon_rule_vs_designated_target",
    "displayName": "Overlapping Detonations",
    "rule_args": {"weapon_code": "heavy_bolter"},
}

_DAKKABLITZ = {
    "ruleId": "weapon_attacks_bonus_vs_keyword",
    "displayName": "Dakkablitz",
    "rule_args": {
        "weapon_code": "blitzcannon",
        "attacks_bonus": 6,
        "excluded_keywords": ["MONSTER", "VEHICLE"],
    },
}

_HAIL_OF_BOLTS = {
    "ruleId": "weapon_attacks_bonus_vs_designated_target",
    "displayName": "Hail of Bolts",
    "rule_args": {"weapon_code": "bolt_rifle", "attacks_bonus": 2},
}

_WAAAGH_ENERGY = {
    "ruleId": "weapon_profile_scaling_by_model_count",
    "displayName": "Waaagh! Energy",
    "rule_args": {
        "weapon_code": "eadbanger",
        "per_count": 5,
        "str_bonus": 1,
        "dmg_bonus": 1,
        "hazardous_threshold": 10,
    },
}

_DA_BIGGEST = {
    "ruleId": "melee_attacks_bonus_while_waaagh",
    "displayName": "Da Biggest and da Best",
    "rule_args": {"attacks_bonus": 4},
}

_FINEST_HOUR = {
    "ruleId": "once_per_battle_melee_buff",
    "displayName": "Finest Hour",
    "rule_args": {"attacks_bonus": 3},
}


# ---------------------------------------------------------------------------
# Helpers dés
# ---------------------------------------------------------------------------

def _fixed(monkeypatch, value: int):
    monkeypatch.setattr(random, "randint", lambda a, b: value)


def _seq(monkeypatch, rolls: list):
    seq = list(rolls)

    def fake(a, b):
        assert seq, "sequence RNG epuisee : le moteur a tire plus de des que prevu"
        return seq.pop(0)

    monkeypatch.setattr(random, "randint", fake)
    return seq


# ---------------------------------------------------------------------------
# Builders d'état de jeu
# ---------------------------------------------------------------------------

def _fight_state(
    unit_rules,
    *,
    ws=4,
    strength=4,
    toughness=4,
    save=5,
    model_unit_rules=None,
    units_charged=None,
    waaagh_player=None,
):
    """Attaquant '1' au contact d'une cible '2'.

    model_unit_rules : règles portées par le MODÈLE seul (attacker["UNIT_RULES"]),
    distinctes de celles de l'unité fusionnée (unit_by_id["1"]["UNIT_RULES"]).
    waaagh_player : si non None, active le Waaagh! pour ce joueur (orks, faction ORKS).
    """
    weapon = {
        "ATK": ws, "STR": strength, "AP": 0, "DMG": 1, "NB": 1,
        "WEAPON_RULES": [], "code": "test_choppa", "display_name": "Choppa",
    }
    attacker: dict = {
        "id": "A1", "squad_id": "1", "player": 1, "T": 4, "CC_WEAPONS": [weapon],
    }
    if model_unit_rules is not None:
        attacker["UNIT_RULES"] = model_unit_rules

    target_model = {
        "id": "T1", "squad_id": "2", "player": 2, "T": toughness,
        "HP_CUR": 4, "HP_MAX": 4,
        "ARMOR_SAVE": save, "INVUL_SAVE": 7, "role": None, "unitType": "Grunt",
        "col": 9, "row": 9, "level": 0, "BASE_SHAPE": "round", "BASE_SIZE": 1,
    }
    unit_entry: dict = {"id": "1", "player": 1, "UNIT_RULES": unit_rules}
    gs: dict = {
        **initial_faction_ability_state(),
        "models_cache": {"A1": attacker, "T1": target_model},
        "squad_models": {"1": ["A1"], "2": ["T1"]},
        "squad_cache": {"1": {"model_count_at_start": 1}, "2": {"model_count_at_start": 1}},
        "units_cache": {
            "1": {"col": 0, "row": 0, "VALUE": 10.0, "player": 1, "orientation": 0},
            "2": {"col": 9, "row": 9, "VALUE": 10.0, "player": 2, "orientation": 0, "HP_CUR": 4},
        },
        "unit_by_id": {
            "1": unit_entry,
            "2": {"id": "2", "player": 2, "UNIT_RULES": []},
        },
        "objectives": [{"id": "o1", "hexes": [[5, 5]]}],
        "suppressed_squads": {},
        "units_charged": set(units_charged) if units_charged else set(),
    }
    if waaagh_player is not None:
        gs["waaagh_active"] = {waaagh_player: True}
        gs["waaagh_called"] = {waaagh_player: True}
        # army_faction : le moteur lit les clés par str(player), pas par int.
        gs["config"] = {
            "army_faction": {str(waaagh_player): "ORKS"},
            "uses_codex_detachment": {str(waaagh_player): False},
        }
        unit_entry["FACTION_KEYWORDS"] = [{"keywordId": "ORKS"}]
        unit_entry["player"] = waaagh_player
        attacker["player"] = waaagh_player
        gs["units"] = list(gs["unit_by_id"].values())

    intent = {
        "model_id": "A1",
        "target_unit_id": "2",
        "weapon_index": 0,
        "n_attacks_resolved": 1,
        "target_squad_size_at_declaration": 1,
    }
    return gs, intent


def _shoot_state(
    unit_rules,
    *,
    bs=4,
    strength=4,
    weapon_code="test_gun",
    target_keywords=None,
    target_squad_size=1,
    n_models_in_shooter_squad=1,
    n_attacks_resolved=1,
):
    """Tireur '1' avec une arme de code weapon_code. target_keywords : liste de keywordId pour la cible."""
    from engine.phase_handlers import shooting_handlers

    weapon = {
        "ATK": bs, "STR": strength, "AP": 0, "DMG": 1, "NB": 1, "RNG": 24,
        "WEAPON_RULES": [], "code": weapon_code, "display_name": "Gun",
    }
    attacker = {"id": "A1", "squad_id": "1", "T": 4, "player": 0, "RNG_WEAPONS": [weapon]}
    target_model = {
        "id": "T1", "T": 4, "HP_CUR": 4, "HP_MAX": 4,
        "ARMOR_SAVE": 5, "INVUL_SAVE": 7, "role": None, "unitType": "Grunt", "player": 1,
    }
    shooter_mids = ["A1"] + [f"A{i}" for i in range(2, n_models_in_shooter_squad + 1)]
    extra_models = {
        f"A{i}": {"id": f"A{i}", "squad_id": "1", "T": 4, "player": 0, "RNG_WEAPONS": [weapon]}
        for i in range(2, n_models_in_shooter_squad + 1)
    }
    target_unit_entry: dict = {"id": "2", "UNIT_RULES": [], "UNIT_KEYWORDS": []}
    if target_keywords:
        target_unit_entry["UNIT_KEYWORDS"] = [{"keywordId": kw} for kw in target_keywords]

    gs = {
        **initial_faction_ability_state(),
        "models_cache": {"A1": attacker, "T1": target_model, **extra_models},
        "squad_models": {"1": shooter_mids, "2": ["T1"]},
        "squad_cache": {
            "1": {"model_count": n_models_in_shooter_squad, "model_count_at_start": n_models_in_shooter_squad},
            "2": {"model_count_at_start": target_squad_size},
        },
        "units_cache": {"1": _uc(0, 0, player=0), "2": {**_uc(0, 1), "HP_CUR": 1}},
        "unit_by_id": {
            "1": {"id": "1", "UNIT_RULES": unit_rules},
            "2": target_unit_entry,
        },
        "objectives": [],
        "units_moved": set(),
        "units_advanced": set(),
        "suppressed_squads": {},
    }
    intent = {
        "model_id": "A1",
        "target_unit_id": "2",
        "weapon_index": 0,
        "n_attacks_resolved": n_attacks_resolved,
        "target_squad_size_at_declaration": target_squad_size,
    }
    return gs, intent, shooting_handlers


def _neutralise_shoot(monkeypatch, shooting_handlers):
    """LoS et distance neutralisés."""
    monkeypatch.setattr(shooting_handlers, "compute_unit_los", lambda gs, s, t: {"cover": False})
    monkeypatch.setattr(shooting_handlers, "_get_unit_by_id", lambda gs, sid: {"id": sid})
    monkeypatch.setattr(
        shooting_handlers, "_ranged_distance_metric", lambda *args, **kwargs: "euclidean"
    )


# ===========================================================================
# grant_weapon_rule_melee — Breakin' Heads (SUSTAINED HITS 1)
# ===========================================================================


def test_breakin_heads_genere_un_hit_supplementaire_sur_un_critique(monkeypatch):
    """Un 6 non modifié déclenche SUSTAINED HITS 1 : 1 attaque devient 2 records."""
    _seq(monkeypatch, [6, 5, 2, 5, 2])  # crit hit, wound (main), save ; sustained auto-wound, save
    gs, intent = _fight_state([_BREAKIN_HEADS])

    result = roll_fight_intent(gs, intent)

    records = result["shot_records"]
    assert len(records) == 2, "crit + sustained = 2 records"
    sustained_records = [r for r in records if r.get("sustainedHit")]
    assert len(sustained_records) == 1, "exactement 1 sustained hit record"


def test_sans_breakin_heads_un_critique_ne_genere_pas_de_hit_supplementaire(monkeypatch):
    """CONTRE-ÉPREUVE : sans la capacité, un 6 reste un seul hit."""
    _seq(monkeypatch, [6, 5, 2])
    gs, intent = _fight_state([])

    result = roll_fight_intent(gs, intent)

    assert len(result["shot_records"]) == 1


def test_breakin_heads_ne_joue_pas_au_tir(monkeypatch):
    """« this unit's melee weapons » : la règle ne s'étend pas au roller de tir."""
    gs, intent, sh = _shoot_state([_BREAKIN_HEADS])
    _neutralise_shoot(monkeypatch, sh)
    _seq(monkeypatch, [6, 5, 2])  # crit hit (tir) : si SUSTAINED se déclenchait, 2 records

    result = roll_shoot_intent(gs, intent)

    assert len(result["shot_records"]) == 1, "SUSTAINED HITS inactif au tir"


# ===========================================================================
# grant_weapon_rule_melee_after_charge — Vanguard Assault (LETHAL HITS après charge)
# ===========================================================================


def test_vanguard_assault_letal_apres_charge_sur_crit(monkeypatch):
    """Unité chargée + crit hit → lethalHit=True (auto-wound, sans jet de blessure)."""
    # S=4 vs T=8 : blessure naturelle sur 6+, lethal auto-wound est toujours meilleur
    _seq(monkeypatch, [6, 2])  # crit hit → auto-wound lethal ; save=2 → FAIL
    gs, intent = _fight_state([_VANGUARD_ASSAULT], strength=4, toughness=8, units_charged={"1"})

    result = roll_fight_intent(gs, intent)

    recs = result["shot_records"]
    assert recs[0].get("lethalHit"), "lethalHit doit être True quand la capacité active"


def test_vanguard_assault_inactif_sans_charge(monkeypatch):
    """CONTRE-ÉPREUVE : même crit, sans l'unité dans units_charged → pas de lethalHit."""
    _seq(monkeypatch, [6, 6, 2])  # crit hit, wound roll 6 (crit wound), save
    gs, intent = _fight_state([_VANGUARD_ASSAULT], strength=4, toughness=8, units_charged=set())

    result = roll_fight_intent(gs, intent)

    assert not result["shot_records"][0].get("lethalHit")


def test_vanguard_assault_inactif_si_unites_charged_absent(monkeypatch):
    """Sans la clé units_charged dans game_state : pas de lethalHit (init lazy)."""
    _seq(monkeypatch, [6, 6, 2])
    gs, intent = _fight_state([_VANGUARD_ASSAULT], strength=4, toughness=8)
    gs.pop("units_charged", None)

    result = roll_fight_intent(gs, intent)

    assert not result["shot_records"][0].get("lethalHit")


# ===========================================================================
# grant_weapon_rule_vs_designated_target — Overlapping Detonations (BLAST)
# ===========================================================================


def test_overlapping_detonations_ajoute_des_via_blast_vs_non_mv(monkeypatch):
    """Cible de 6 figurines non-MONSTER/VEHICLE → +1 dé (6//5 = 1)."""
    gs, intent, sh = _shoot_state(
        [_OVERLAPPING_DET],
        weapon_code="heavy_bolter",
        target_squad_size=6,
    )
    _neutralise_shoot(monkeypatch, sh)
    _fixed(monkeypatch, 4)  # tout réussit

    result = roll_shoot_intent(gs, intent)

    assert len(result["shot_records"]) == 2, "1 attack_resolved + 1 BLAST extra"


def test_overlapping_detonations_nul_vs_target_trop_petite(monkeypatch):
    """Cible de 4 figurines → 4//5 = 0 dés supplémentaires."""
    gs, intent, sh = _shoot_state(
        [_OVERLAPPING_DET],
        weapon_code="heavy_bolter",
        target_squad_size=4,
    )
    _neutralise_shoot(monkeypatch, sh)
    _fixed(monkeypatch, 4)

    result = roll_shoot_intent(gs, intent)

    assert len(result["shot_records"]) == 1


def test_overlapping_detonations_nul_vs_monster(monkeypatch):
    """MONSTER → exclu par la règle (non-MONSTER/VEHICLE requis)."""
    gs, intent, sh = _shoot_state(
        [_OVERLAPPING_DET],
        weapon_code="heavy_bolter",
        target_squad_size=6,
        target_keywords=["MONSTER"],
    )
    _neutralise_shoot(monkeypatch, sh)
    _fixed(monkeypatch, 4)

    result = roll_shoot_intent(gs, intent)

    assert len(result["shot_records"]) == 1


def test_overlapping_detonations_nul_si_mauvaise_arme(monkeypatch):
    """DISCRIMINATION arme : la règle porte weapon_code 'heavy_bolter', pas 'test_gun'."""
    gs, intent, sh = _shoot_state(
        [_OVERLAPPING_DET],
        weapon_code="test_gun",
        target_squad_size=10,
    )
    _neutralise_shoot(monkeypatch, sh)
    _fixed(monkeypatch, 4)

    result = roll_shoot_intent(gs, intent)

    assert len(result["shot_records"]) == 1


# ===========================================================================
# weapon_attacks_bonus_vs_keyword — Dakkablitz (+6 A hors MONSTER/VEHICLE)
# ===========================================================================


def test_dakkablitz_ajoute_six_attaques_vs_infanterie(monkeypatch):
    """Blitzcannon vs cible non-MONSTER/VEHICLE : n_attacks_resolved=1 → 7 records."""
    gs, intent, sh = _shoot_state(
        [_DAKKABLITZ],
        weapon_code="blitzcannon",
    )
    _neutralise_shoot(monkeypatch, sh)
    _fixed(monkeypatch, 4)

    result = roll_shoot_intent(gs, intent)

    assert len(result["shot_records"]) == 7, "1 + 6 bonus"


def test_dakkablitz_nul_vs_monster(monkeypatch):
    """MONSTER est dans excluded_keywords → pas de bonus."""
    gs, intent, sh = _shoot_state(
        [_DAKKABLITZ],
        weapon_code="blitzcannon",
        target_keywords=["MONSTER"],
    )
    _neutralise_shoot(monkeypatch, sh)
    _fixed(monkeypatch, 4)

    result = roll_shoot_intent(gs, intent)

    assert len(result["shot_records"]) == 1


def test_dakkablitz_nul_si_mauvaise_arme(monkeypatch):
    """DISCRIMINATION : la règle porte weapon_code 'blitzcannon', autre arme → pas de bonus."""
    gs, intent, sh = _shoot_state(
        [_DAKKABLITZ],
        weapon_code="test_gun",
    )
    _neutralise_shoot(monkeypatch, sh)
    _fixed(monkeypatch, 4)

    result = roll_shoot_intent(gs, intent)

    assert len(result["shot_records"]) == 1


# ===========================================================================
# weapon_attacks_bonus_vs_designated_target — Hail of Bolts (+2 A)
# ===========================================================================


def test_hail_of_bolts_ajoute_deux_attaques_vs_cible_designee(monkeypatch):
    """Bolt rifle tiré sur la cible désignée : +2 A → 3 records au total."""
    gs, intent, sh = _shoot_state([_HAIL_OF_BOLTS], weapon_code="bolt_rifle")
    _neutralise_shoot(monkeypatch, sh)
    _fixed(monkeypatch, 4)

    result = roll_shoot_intent(gs, intent)

    assert len(result["shot_records"]) == 3, "1 + 2 bonus"


def test_hail_of_bolts_sans_regle(monkeypatch):
    """CONTRE-ÉPREUVE : sans la règle, 1 seul record."""
    gs, intent, sh = _shoot_state([], weapon_code="bolt_rifle")
    _neutralise_shoot(monkeypatch, sh)
    _fixed(monkeypatch, 4)

    result = roll_shoot_intent(gs, intent)

    assert len(result["shot_records"]) == 1


def test_hail_of_bolts_nul_si_mauvaise_arme(monkeypatch):
    """DISCRIMINATION arme : weapon_code 'test_gun' ne correspond pas à 'bolt_rifle'."""
    gs, intent, sh = _shoot_state([_HAIL_OF_BOLTS], weapon_code="test_gun")
    _neutralise_shoot(monkeypatch, sh)
    _fixed(monkeypatch, 4)

    result = roll_shoot_intent(gs, intent)

    assert len(result["shot_records"]) == 1


# ===========================================================================
# weapon_profile_scaling_by_model_count — Waaagh! Energy (+1S +1D par tranche de 5)
# ===========================================================================


def test_waaagh_energy_abaisse_le_seuil_de_blessure_avec_5_modeles(monkeypatch):
    """Escouade de 5 : +1S (S4 vs T4 = 4+ au lieu de 5+). Un dé de 4 blesse."""
    # STR=3 (base), T=4 → wound target = 5+ sans bonus. Avec 5 modèles → STR=4 → wound = 4+.
    gs, intent, sh = _shoot_state(
        [_WAAAGH_ENERGY],
        weapon_code="eadbanger",
        strength=3,
        n_models_in_shooter_squad=5,
    )
    _neutralise_shoot(monkeypatch, sh)
    _seq(monkeypatch, [4, 4, 2])  # hit=4, wound=4 sur 4+, save=2 vs 5+ → FAIL

    result = roll_shoot_intent(gs, intent)

    rec = result["shot_records"][0]
    assert rec["woundTarget"] == 4, "+1S ramène le seuil de blessure à 4+"
    assert rec["strengthResult"] in ("WOUND", "SUCCESS")


def test_waaagh_energy_inactif_sans_modeles_suffisants(monkeypatch):
    """Escouade de 4 : 4//5 = 0 → pas de bonus. S3 vs T4 → wound target = 5+, 4 échoue."""
    gs, intent, sh = _shoot_state(
        [_WAAAGH_ENERGY],
        weapon_code="eadbanger",
        strength=3,
        n_models_in_shooter_squad=4,
    )
    _neutralise_shoot(monkeypatch, sh)
    _seq(monkeypatch, [4, 4])  # hit=4, wound=4 → rate sur 5+ (pas de save roll)

    result = roll_shoot_intent(gs, intent)

    rec = result["shot_records"][0]
    assert rec["woundTarget"] == 5, "sans bonus, S3 vs T4 = 5+"
    assert rec["strengthResult"] == "FAILED"


def test_waaagh_energy_bonus_double_avec_10_modeles(monkeypatch):
    """Escouade de 10 : +2S (S5 vs T4 = 3+)."""
    gs, intent, sh = _shoot_state(
        [_WAAAGH_ENERGY],
        weapon_code="eadbanger",
        strength=3,
        n_models_in_shooter_squad=10,
    )
    _neutralise_shoot(monkeypatch, sh)
    _seq(monkeypatch, [4, 3, 2])

    result = roll_shoot_intent(gs, intent)

    rec = result["shot_records"][0]
    assert rec["woundTarget"] == 3, "+2S (2×1) → S5 vs T4 → 3+"


def test_waaagh_energy_nul_si_mauvaise_arme(monkeypatch):
    """DISCRIMINATION arme : weapon_code 'test_gun' ne touche pas 'eadbanger'."""
    gs, intent, sh = _shoot_state(
        [_WAAAGH_ENERGY],
        weapon_code="test_gun",
        strength=3,
        n_models_in_shooter_squad=5,
    )
    _neutralise_shoot(monkeypatch, sh)
    _seq(monkeypatch, [4, 4])  # S3 vs T4 = 5+, wound=4 rate, pas de save

    result = roll_shoot_intent(gs, intent)

    rec = result["shot_records"][0]
    assert rec["woundTarget"] == 5, "STR=3 vs T=4 = 5+ (pas de bonus car mauvaise arme)"
    assert rec["strengthResult"] == "FAILED"


# ===========================================================================
# melee_attacks_bonus_while_waaagh — Da Biggest and da Best (+4 A)
# ===========================================================================


def test_da_biggest_ajoute_quatre_attaques_tant_que_waaagh_actif(monkeypatch):
    """Waaagh! actif + règle sur le MODÈLE → n_attacks = 1 + 1 (Waaagh) + 4 (Da Biggest) = 6."""
    _fixed(monkeypatch, 4)
    gs, intent = _fight_state(
        unit_rules=[],  # unité fusionnée : vide (la règle est sur le modèle seul)
        model_unit_rules=[_DA_BIGGEST],
        waaagh_player=1,
    )
    result = roll_fight_intent(gs, intent)

    assert len(result["shot_records"]) == 6, "1 base + 1 Waaagh + 4 Da Biggest"


def test_da_biggest_inactif_sans_waaagh(monkeypatch):
    """Waaagh! inactif → _waaagh_bonus = 0 → Da Biggest ne joue pas."""
    _fixed(monkeypatch, 4)
    gs, intent = _fight_state(unit_rules=[], model_unit_rules=[_DA_BIGGEST])

    result = roll_fight_intent(gs, intent)

    assert len(result["shot_records"]) == 1


def test_da_biggest_seulement_sur_le_modele_porteur_pas_sur_lequipe(monkeypatch):
    """La règle sur le MODÈLE ne doit pas s'appliquer aux autres membres de l'équipe.

    Un modèle sans UNIT_RULES=Da Biggest dans un squad Waaagh!-actif ne gagne que +1A
    (Waaagh! baseline), pas les +4A de Da Biggest.
    """
    _fixed(monkeypatch, 4)
    # Modèle sans la règle Da Biggest
    gs, intent = _fight_state(
        unit_rules=[],
        model_unit_rules=[],  # ce modèle n'a PAS Da Biggest
        waaagh_player=1,
    )
    result = roll_fight_intent(gs, intent)

    assert len(result["shot_records"]) == 2, "1 base + 1 Waaagh seulement"


# ===========================================================================
# once_per_battle_melee_buff — Finest Hour (+3 A + DEVASTATING WOUNDS, 1×/partie)
# ===========================================================================


def test_finest_hour_ajoute_trois_attaques_premiere_activation(monkeypatch):
    """Première activation dans la partie : n_attacks = 1 + 3 = 4 records."""
    _fixed(monkeypatch, 4)
    # Finest Hour est sur le MODÈLE (this model's melee weapons)
    gs, intent = _fight_state(unit_rules=[], model_unit_rules=[_FINEST_HOUR])

    result = roll_fight_intent(gs, intent)

    assert len(result["shot_records"]) == 4, "1 base + 3 Finest Hour"


def test_finest_hour_inactif_deuxieme_activation(monkeypatch):
    """ONCE PER BATTLE : flag finest_hour_used posé → deuxième activation = pas de bonus."""
    _fixed(monkeypatch, 4)
    gs, intent = _fight_state(unit_rules=[], model_unit_rules=[_FINEST_HOUR])
    # Simuler que le squad "1" a déjà utilisé Finest Hour
    gs["finest_hour_used"] = {"1"}

    result = roll_fight_intent(gs, intent)

    assert len(result["shot_records"]) == 1, "flag déjà posé → pas de +3A"


def test_finest_hour_accorde_devastating_wounds_premiere_activation(monkeypatch):
    """Première activation : blessure critique → devastating=True (pas sauvegardable)."""
    # Finest Hour : +3A → 4 attaques totales. Séquence calculée précisément :
    # Attaque 1 : hit=4 (HIT), wound=6 (crit → devastating, pas de jet de sauvegarde)
    # Attaques 2-4 : hit=4 (HIT), wound=4 (WOUND, non-crit), save=2 (FAIL vs 5+)
    _seq(monkeypatch, [4, 6, 4, 4, 2, 4, 4, 2, 4, 4, 2])
    gs, intent = _fight_state(
        unit_rules=[], model_unit_rules=[_FINEST_HOUR],
        toughness=4, save=5,  # S=4 vs T=4 : wound 4+, 6 → crit wound
    )

    result = roll_fight_intent(gs, intent)

    first_hit_record = [r for r in result["shot_records"] if r.get("hitResult") == "HIT"][0]
    assert first_hit_record.get("devastating"), "blessure critique + Finest Hour → devastating"


def test_finest_hour_pose_le_flag_apres_premiere_activation(monkeypatch):
    """Le flag finest_hour_used est posé dans game_state après la première activation."""
    _fixed(monkeypatch, 4)
    gs, intent = _fight_state(unit_rules=[], model_unit_rules=[_FINEST_HOUR])
    assert "finest_hour_used" not in gs or "1" not in gs.get("finest_hour_used", set())

    roll_fight_intent(gs, intent)

    assert "1" in gs.get("finest_hour_used", set()), "le flag doit être posé après activation"


def test_finest_hour_devastating_wounds_sur_deuxieme_arme(monkeypatch):
    """Finest Hour actif sur intent 1 → DEVASTATING WOUNDS appliqué sur intent 2 (2e CC weapon, même phase)."""
    # Intent 1 (weapon 0, 4 attaques) : 4 × [hit=4, wound=4, save=4] = 12 dés
    # Intent 2 (weapon 1, 1 attaque) : [hit=4, wound=6, save=4] = 3 dés SANS fix (crit sans DEVASTATING)
    #   ou [hit=4, wound=6] = 2 dés AVEC fix (DEVASTATING WOUNDS actif → pas de save)
    _seq(monkeypatch, [4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 6, 4])
    gs, intent = _fight_state(unit_rules=[], model_unit_rules=[_FINEST_HOUR])
    weapon2 = {
        "ATK": 1, "STR": 4, "AP": 0, "DMG": 1, "NB": 1,
        "WEAPON_RULES": [], "code": "test_blade", "display_name": "Blade",
    }
    gs["models_cache"]["A1"]["CC_WEAPONS"].append(weapon2)

    roll_fight_intent(gs, {**intent, "weapon_index": 0, "n_attacks_resolved": 1})
    assert "1" in gs.get("finest_hour_used", set()), "flag posé après intent 1"

    result2 = roll_fight_intent(gs, {**intent, "weapon_index": 1, "n_attacks_resolved": 1})

    assert len(result2["shot_records"]) == 1, "pas de +3A sur la 2e arme"
    hit_records = [r for r in result2["shot_records"] if r.get("hitResult") == "HIT"]
    assert hit_records, "l'attaque doit toucher (roll 4 vs ws 4)"
    assert hit_records[0].get("devastating"), "Finest Hour toujours actif → devastating sur blessure critique (2e arme)"


def test_finest_hour_devastating_wounds_sur_deuxieme_arme(monkeypatch):
    """Finest Hour actif sur intent 1 → DEVASTATING WOUNDS appliqué sur intent 2 (2e CC weapon, même phase)."""
    # Intent 1 (weapon 0, 4 attaques) : 4 × [hit=4, wound=4, save=4] = 12 dés
    # Intent 2 (weapon 1, 1 attaque) : [hit=4, wound=6, save=4] = 3 dés SANS fix (crit sans DEVASTATING)
    #   ou [hit=4, wound=6] = 2 dés AVEC fix (DEVASTATING WOUNDS actif → pas de save)
    _seq(monkeypatch, [4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 6, 4])
    gs, intent = _fight_state(unit_rules=[], model_unit_rules=[_FINEST_HOUR])
    weapon2 = {
        "ATK": 1, "STR": 4, "AP": 0, "DMG": 1, "NB": 1,
        "WEAPON_RULES": [], "code": "test_blade", "display_name": "Blade",
    }
    gs["models_cache"]["A1"]["CC_WEAPONS"].append(weapon2)

    roll_fight_intent(gs, {**intent, "weapon_index": 0, "n_attacks_resolved": 1})
    assert "1" in gs.get("finest_hour_used", set()), "flag posé après intent 1"

    result2 = roll_fight_intent(gs, {**intent, "weapon_index": 1, "n_attacks_resolved": 1})

    assert len(result2["shot_records"]) == 1, "pas de +3A sur la 2e arme"
    hit_records = [r for r in result2["shot_records"] if r.get("hitResult") == "HIT"]
    assert hit_records, "l'attaque doit toucher (roll 4 vs ws 4)"
    assert hit_records[0].get("devastating"), "Finest Hour toujours actif → devastating sur blessure critique (2e arme)"
