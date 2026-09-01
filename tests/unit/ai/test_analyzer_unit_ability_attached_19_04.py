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


def test_porteurs_natifs_morts_perd_la_capacite():
    """VERROU mort-porteur : model_types garde les morts, living_mids ne garde que les vivants.

    Scénario : tous les Intercessors sont morts, seul l'Ancient (5#6) est vivant et tire.
    model_types contient encore 5#0 et 5#4 (Intercessor) → sans filtre, _types inclurait
    Intercessor → bonus accordé alors que le moteur l'a retiré (native_alive=False).
    Avec living_mids={5#6}, seul le type Ancient entre dans _types → 0.
    """
    assert unit_ability_attack_cap(
        ("5#6",), MODEL_TYPES, "5", "Intercessor", "Bolt Rifle",
        LIMITS, "atk_bonus_by_weapon", 1,
        living_mids={"5#6"},
    ) == 0


def test_porteurs_natifs_vivants_avec_living_mids():
    """living_mids fourni, natives vivants → bonus accordé comme sans filtre."""
    assert unit_ability_attack_cap(
        ("5#0", "5#4", "5#6"), MODEL_TYPES, "5", "Intercessor", "Bolt Rifle",
        LIMITS, "atk_bonus_by_weapon", 3,
        living_mids={"5#0", "5#4", "5#6"},
    ) == 6


def test_living_mids_none_repli_historique():
    """Sans living_mids, le repli historique (model_types non filtré) s'applique.

    Régression : les appels anciens (logs sans [MODELS:]) continuent à rendre le bonus
    via squad_unit_type, sans que la signature change ait cassé quoi que ce soit.
    """
    assert _cap(("5#0", "5#4", "5#6")) == 6


def test_porteurs_types_morts_mid_vivant_non_type_perd_la_capacite():
    """VERROU : porteurs typés tous morts, seul un mid sans entrée model_types survit → 0.

    Scénario : Intercessors (5#0, 5#4) ont été loggués via [MODEL_TYPES:] puis sont morts.
    L'Ancient (5#6) survit mais n'a jamais tiré → absent de model_types. Sans garde,
    _types={} → fallback squad_unit_type="Intercessor" → bonus accordé à tort (porteurs
    native_alive=False côté moteur). Avec garde : model_types a des entrées pour le préfixe
    "5#" mais aucune n'est vivante → return 0.
    """
    model_types_sans_ancient = {
        "5#0": "Intercessor",
        "5#4": "IntercessorSergeant",
    }
    assert unit_ability_attack_cap(
        ("5#6",), model_types_sans_ancient, "5", "Intercessor", "Bolt Rifle",
        LIMITS, "atk_bonus_by_weapon", 1,
        living_mids={"5#6"},
    ) == 0, "porteurs natifs morts, mid vivant non typé : aucun bonus"


def test_living_mids_vide_perd_la_capacite():
    """VERROU : living_mids={} (aucun socle vivant dans ce segment) → 0, pas de fallback.

    Scénario dégénéré : [MODELS:] présent mais vide ou parsé comme dict vide →
    set({}) = set() → living_mids fourni et vide. Sans garde : _types={} → fallback →
    bonus accordé alors qu'aucun socle n'est vivant.
    """
    assert unit_ability_attack_cap(
        ("5#0",), MODEL_TYPES, "5", "Intercessor", "Bolt Rifle",
        LIMITS, "atk_bonus_by_weapon", 1,
        living_mids=set(),
    ) == 0, "living_mids vide : aucun bonus"


def test_mids_vivants_non_types_repli_squad_unit_type():
    """living_mids fourni mais aucun mid dans model_types → fallback squad_unit_type.

    Scénario : log sans [MODEL_TYPES:] ou modèles non encore typés. Les mids sont dans
    living_mids (le segment [MODELS:] les voit vivants) mais absents de model_types.
    Sans fallback : _types = {} → return 0 → faux positif shoot_over_rng_nb sur une
    escouade vivante. Avec fallback squad_unit_type : Intercessor → Hail of Bolts → bonus.
    """
    assert unit_ability_attack_cap(
        ("5#0", "5#4"), {}, "5", "Intercessor", "Bolt Rifle",
        LIMITS, "atk_bonus_by_weapon", 2,
        living_mids={"5#0", "5#4"},
    ) == 4, "fallback squad_unit_type obligatoire quand model_types ne type pas les vivants"
