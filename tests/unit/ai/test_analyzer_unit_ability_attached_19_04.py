"""19.04 — une capacité d'UNITÉ vaut pour TOUTE figurine de l'unité attachée.

PDF `19 Attached units.pdf` §19.04 : « abilities/rules that affect a unit (or models in it)
apply to every model in an attached unit » ; seules les capacités visant un socle nommé
(enhancement, wargear) restent locales.

Hail of Bolts (`weapon_attacks_bonus_vs_designated_target`) est une capacité de l'escouade
Intercessor. Un Ancient ou un Captain rattaché tire donc son Bolt Rifle avec le bonus, alors
que sa PROPRE datasheet ne porte pas la règle.

Le moteur applique déjà cette lecture (`shared_utils.py` lit les arguments sur `attacker_unit`).
Résoudre le bonus par datasheet individuelle refusait aux personnages rattachés un bonus que le
moteur leur accorde : 2447 faux `shoot_over_rng_nb` sur le run du 2026-09-02.

Escouade du run témoin (unité 5) :
  5#0..5#2 = Intercessor · 5#3 = IntercessorGrenadeLauncher · 5#4 = IntercessorSergeant
  5#5 = CaptainRelicShield (rattaché) · 5#6 = Ancient (rattaché)
"""
from __future__ import annotations

from ai.analyzer_perfig import unit_ability_attack_cap

#: Datasheets du socle, telles que `[MODEL_TYPES:]` les nomme.
MODEL_TYPES = {
    "5#0": "Intercessor",
    "5#4": "IntercessorSergeant",
    "5#6": "Ancient",
}

#: Seules les datasheets Intercessor portent Hail of Bolts ; l'Ancient rattaché ne l'a pas.
LIMITS = {
    "Intercessor": {"atk_bonus_by_weapon": {"Bolt Rifle": 2}},
    "IntercessorSergeant": {"atk_bonus_by_weapon": {"Bolt Rifle": 2}},
    "Ancient": {"atk_bonus_by_weapon": {}},
}


def _cap(shooters):
    return unit_ability_attack_cap(
        shooters, MODEL_TYPES, "5", "Intercessor", "Bolt Rifle",
        LIMITS, "atk_bonus_by_weapon", len(shooters),
    )


def test_le_personnage_rattache_recoit_le_bonus_d_unite():
    """VERROU 19.04 : 3 tireurs dont l'Ancient → 3 × 2, pas 2 × 2.

    C'est le cas exact du run : l'Ancient (5#6) tire avec les Intercessors et le moteur lui
    accorde +2 A. Résoudre par datasheet individuelle rendait 4 au lieu de 6.
    """
    assert _cap(("5#0", "5#4", "5#6")) == 6, (
        "19.04 : la capacité d'escouade doit valoir pour l'Ancient rattaché"
    )


def test_le_bonus_vaut_par_socle_tireur():
    """Le bonus modifie la caractéristique d'Attaques : il compte par socle qui tire."""
    assert _cap(("5#0",)) == 2
    assert _cap(("5#0", "5#4")) == 4


def test_aucune_capacite_dans_l_unite_donne_zero():
    """Contre-épreuve : sans porteur de la règle, aucun bonus n'est inventé."""
    limits_sans_regle = {"Ancient": {"atk_bonus_by_weapon": {}}}
    assert unit_ability_attack_cap(
        ("5#6",), {"5#6": "Ancient"}, "5", "Ancient", "Bolt Rifle",
        limits_sans_regle, "atk_bonus_by_weapon", 1,
    ) == 0
