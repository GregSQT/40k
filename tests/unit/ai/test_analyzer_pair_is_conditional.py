"""_pair_is_conditional : cas croisé leader/menés.

Avant le fix, seul le cas direct (weapon appartenant au LEADER lui-même) était reconnu comme
CONDITIONAL. Le cas croisé — Bigboss accorde SUSTAINED_HITS à « Choppa (Boyz) » via
`grant_weapon_rule_melee`, alors que Bigboss n'est PAS l'unité de l'arme — tombait en INVALID.

Fix : vérifier si l'unité de l'arme figure dans `squadmates_by_type` du leader accordant.
"""
from __future__ import annotations

from ai.analyzer import _pair_is_conditional


def _grantable(granting_units: set[str], rule: str = "SUSTAINED_HITS") -> dict:
    return {rule: granting_units}


def test_cas_direct_bigboss_propre_arme():
    """La règle est accordée par le porteur lui-même (Bigboss) à son propre Choppa."""
    grantable = _grantable({"Bigboss"})
    assert _pair_is_conditional("Sustained_hits", "Choppa (Bigboss)", grantable)


def test_cas_croise_bigboss_accorde_aux_boyz():
    """Bigboss accorde SUSTAINED_HITS à « Choppa (Boyz) » via grant_weapon_rule_melee."""
    grantable = _grantable({"Bigboss"})
    squadmates = {"Bigboss": {"Boyz", "Nobz"}}
    assert _pair_is_conditional(
        "Sustained_hits", "Choppa (Boyz)", grantable, squadmates
    ), "Choppa (Boyz) doit être CONDITIONAL quand Bigboss mène Boyz"


def test_cas_croise_inconnu_reste_invalid():
    """Sans squadmates, le cas croisé reste INVALID."""
    grantable = _grantable({"Bigboss"})
    assert not _pair_is_conditional("Sustained_hits", "Choppa (Boyz)", grantable)


def test_chapelain_accorde_lethal_hits_a_vanguard():
    """ChaplainJumpPack accorde LETHAL_HITS aux armes de VanguardVeteranSquadJumpPack."""
    grantable = {"LETHAL_HITS": {"ChaplainJumpPack"}}
    squadmates = {"ChaplainJumpPack": {"VanguardVeteranSquadJumpPack", "AssaultIntercessorJumpPack"}}
    assert _pair_is_conditional(
        "Lethal_hits",
        "Bolt Pistol (VanguardVeteranSquadJumpPack)",
        grantable,
        squadmates,
    )


def test_cas_inverse_croise_vanguard_accorde_au_chaplain():
    """VanguardVeteranSquadJumpPack accorde LETHAL_HITS via grant_weapon_rule_melee_after_charge :
    le ChaplainJumpPack qui le mène bénéficie aussi de la règle sur son propre Crozius Arcanum."""
    grantable = {"LETHAL_HITS": {"VanguardVeteranSquadJumpPack"}}
    squadmates = {"ChaplainJumpPack": {"VanguardVeteranSquadJumpPack"}}
    assert _pair_is_conditional(
        "Lethal_hits",
        "Crozius Arcanum (ChaplainJumpPack)",
        grantable,
        squadmates,
    ), "Crozius (ChaplainJumpPack) doit être CONDITIONAL quand il mène VanguardVeteranSquadJumpPack qui accorde"


def test_regle_inconnue_retourne_false():
    """Règle absente de grantable → False."""
    grantable = _grantable({"Bigboss"})
    squadmates = {"Bigboss": {"Boyz"}}
    assert not _pair_is_conditional(
        "Devastating_wounds", "Choppa (Boyz)", grantable, squadmates
    )
