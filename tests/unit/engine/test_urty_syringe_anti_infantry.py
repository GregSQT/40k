"""'urty Syringe — [ANTI-INFANTRY 4+] conforme à la datasheet.

L'armurerie déclarait `ANTI_INFANTRY:2`. Le paramètre est le SEUIL du jet de blessure non
modifié à partir duquel la blessure est critique (config/weapon_rules.json) : avec 2, tout jet
de 2 ou plus devenait critique contre de l'INFANTERIE, soit presque toutes les blessures.

Source : Documentation/40k_rules/Armageddon/Datasheets - Orks.pdf, page 4, PAINBOY, ligne
MELEE WEAPONS — « 'Urty syringe [ANTI-INFANTRY 4+, EXTRA ATTACKS, PRECISION] ».

Ce seuil ne décide pas que du critique : c'est lui qui commande la fréquence de Hold Still and
Say Aargh, dont chaque déclenchement inflige D6 blessures mortelles.
"""
from __future__ import annotations

from engine.phase_handlers.attack_sequence import build_weapon_attack_profile
from engine.weapons import get_armory_parser

_ANTI_INFANTRY_DATASHEET = 4


def _urty_syringe() -> dict:
    armory = get_armory_parser().get_armory("ork")
    assert armory, "armurerie ork vide : le test ne prouverait rien"
    weapon = armory.get("urty_syringe")
    assert weapon is not None, "urty_syringe absente de l'armurerie ork"
    return weapon


def test_armurerie_declare_le_seuil_de_la_datasheet() -> None:
    rules = _urty_syringe()["WEAPON_RULES"]
    assert f"ANTI_INFANTRY:{_ANTI_INFANTRY_DATASHEET}" in rules, (
        f"seuil ANTI-INFANTRY non conforme à la datasheet (4+), got {rules}"
    )


def test_seuil_de_blessure_critique_contre_infanterie() -> None:
    """Le contrôle qui compte est celui du profil réellement résolu : c'est `crit_wound_on`
    qui décide, pas la chaîne déclarée."""
    profile = build_weapon_attack_profile(
        _urty_syringe(),
        {"id": "TGT", "unit_keywords": ["INFANTRY"]},
        attacker_unit={"id": "PAIN", "UNIT_RULES": []},
        game_state={},
        is_melee=True,
        finest_hour_active=False,
    )
    assert profile.crit_wound_on == _ANTI_INFANTRY_DATASHEET, (
        f"crit_wound_on={profile.crit_wound_on}, attendu {_ANTI_INFANTRY_DATASHEET} (datasheet)"
    )
    assert profile.anti_threshold == _ANTI_INFANTRY_DATASHEET


def test_pas_de_critique_anticipe_hors_infanterie() -> None:
    """[ANTI-X] ne joue que contre le mot-clé nommé : contre un VÉHICULE, seul le 6 non
    modifié est critique (05.02)."""
    profile = build_weapon_attack_profile(
        _urty_syringe(),
        {"id": "TGT", "unit_keywords": ["VEHICLE"]},
        attacker_unit={"id": "PAIN", "UNIT_RULES": []},
        game_state={},
        is_melee=True,
        finest_hour_active=False,
    )
    assert profile.crit_wound_on == 6
    assert profile.anti_threshold is None
