"""04.03 IDENTICAL ATTACKS — la cle de groupe doit porter les REGLES, pas seulement le profil.

Encadre 04.03 : « Identical attacks are those that have the same BS/WS, S, AP and D
characteristics, **and which are affected by the same applicable abilities and rules**. »

La cle de lot d'allocation ne portait que la premiere moitie. Sur le roster Ork reel, Shoota
(RAPID_FIRE:1), Kombi Shoota (aucune regle) et Kustom Shoota (RAPID_FIRE:2) ont le meme
ATK/AP/DMG : elles tombaient dans un lot unique, qui ne peut porter qu'UNE valeur de
`[RAPID FIRE:X]` dans le log — 898 faux « marker value mismatch » cote analyzer sur un run de
600 episodes, et un nom d'arme composite « A / B / C » melangeant des attaques non identiques.

Ce que ce fichier verrouille :
  1. la signature de regles (`weapon_rule_signature`), y compris le parametre ;
  2. la separation effective des lots par la cle de groupe ;
  3. la NON-separation quand les regles sont identiques (sinon on aurait remplace une
     sur-fusion par une sur-separation, tout aussi fausse au regard de 04.03).
"""

from __future__ import annotations

from typing import Any, Dict, FrozenSet, List, Set, Tuple

import pytest

from engine.phase_handlers.attack_sequence import build_weapon_attack_profile
from engine.phase_handlers.shared_utils import RULE_LABEL_RAPID_FIRE
from engine.utils.weapon_helpers import weapon_rule_signature


def _weapon(name: str, rules: List[str]) -> Dict[str, Any]:
    return {"display_name": name, "ATK": 5, "STR": 4, "AP": 0, "DMG": 1, "NB": 2,
            "RNG": 18, "WEAPON_RULES": list(rules), "code": name}


# ─────────────────────────────────────────────────────────────────────────────
# 1. La signature elle-meme
# ─────────────────────────────────────────────────────────────────────────────

def test_signature_normalises_case_and_spacing() -> None:
    assert weapon_rule_signature(_weapon("w", ["rapid_fire: 2", " Heavy "])) == frozenset(
        {"RAPID_FIRE:2", "HEAVY"}
    )


def test_signature_keeps_the_parameter() -> None:
    """RAPID_FIRE:1 et RAPID_FIRE:2 ne sont pas la meme regle appliquee."""
    assert weapon_rule_signature(_weapon("a", ["RAPID_FIRE:1"])) != weapon_rule_signature(
        _weapon("b", ["RAPID_FIRE:2"])
    )


def test_signature_refuses_a_non_string_entry() -> None:
    """Aucun repli masquant : meme doctrine que `weapon_has_rule`."""
    with pytest.raises(TypeError):
        weapon_rule_signature({"display_name": "w", "WEAPON_RULES": [{"rule": "HEAVY"}]})


# ─────────────────────────────────────────────────────────────────────────────
# 2. La cle de groupe — reproduite a l'IDENTIQUE du site de production
# ─────────────────────────────────────────────────────────────────────────────

def _gkey(
    weapon: Dict[str, Any],
    *,
    rapid_fire_applied: int,
    target_sid: str,
    cleave_applied: int = 0,
) -> Tuple:
    """Miroir exact de `_build_manual_allocation` (shared_utils) pour un profil brut commun.

    Les trois Shootas partagent ATK/AP/DMG et visent la meme cible : `bs`, `ap`, `dmg_raw`,
    `dmg_bonus`, `display_wth`, `display_save_th` et `target_sid` sont donc identiques par
    construction. Ce qui reste pour les departager, c'est exactement ce que 04.03 exige.

    Les deux X APPLIQUES ([RAPID FIRE] 24.30, [CLEAVE] 24.06) sont les seules valeurs de la cle
    qui dependent de la FIGURINE et non de l'arme declaree — d'ou leur presence ici a cote de la
    signature. `cleave_applied` a un defaut : les armes de TIR de ce fichier ne le portent
    jamais, et l'ecrire a chaque appel noierait ce qu'ils discriminent vraiment.

    X == 0 ⇒ label ABSENT du dict, comme chez le producteur : `additive_rules_applied` ne
    retient une regle que si elle a AJOUTE des des.
    """
    _additive = {
        label: x
        for label, x in (("RAPID FIRE", rapid_fire_applied), ("CLEAVE", cleave_applied))
        if x > 0
    }
    return (
        5, 0, 1, 0, 4, 5, weapon_rule_signature(weapon),
        tuple(sorted(_additive.items())), target_sid,
    )


SHOOTA = _weapon("Shoota", ["RAPID_FIRE:1"])
KOMBI_SHOOTA = _weapon("Kombi Shoota", [])
KUSTOM_SHOOTA = _weapon("Kustom Shoota", ["RAPID_FIRE:2"])


def test_three_shootas_no_longer_share_a_batch() -> None:
    """Le cas mesure : trois armes, trois regles differentes -> trois lots."""
    keys: Set[Tuple] = {
        _gkey(SHOOTA, rapid_fire_applied=1, target_sid="101"),
        _gkey(KOMBI_SHOOTA, rapid_fire_applied=0, target_sid="101"),
        _gkey(KUSTOM_SHOOTA, rapid_fire_applied=2, target_sid="101"),
    }
    assert len(keys) == 3, keys


def test_same_weapon_splits_when_rapid_fire_does_not_apply_to_every_shooter() -> None:
    """24.30 : « APPLICABLE » — a demi-portee ou non, ce ne sont pas les memes attaques.

    Deux figurines de la MEME escouade avec la MEME arme : la signature declaree est identique,
    seule la valeur appliquee les separe. Sans elle, le groupe garderait la valeur de la
    premiere figurine et le token `[RAPID FIRE:X]` du log resterait ambigu.
    """
    in_half = _gkey(SHOOTA, rapid_fire_applied=1, target_sid="101")
    out_of_half = _gkey(SHOOTA, rapid_fire_applied=0, target_sid="101")
    assert in_half != out_of_half


def test_identical_rules_still_group_together() -> None:
    """Contre-epreuve : 04.03 FUSIONNE les attaques identiques — ne pas sur-separer.

    Deux profils distincts par le NOM seulement (Kustom Shoota a2 / a4 du roster reel) doivent
    rester dans le meme lot. Sans ce test, mettre RNG/NB ou le nom dans la cle passerait au vert
    alors que ce serait une violation symetrique de la regle.
    """
    a2 = _weapon("Kustom Shoota", ["RAPID_FIRE:2"])
    a4 = _weapon("Kustom Shoota", ["RAPID_FIRE:2"])
    a4["RNG"] = 24  # RNG et NB ne sont PAS des caracteristiques d'identite (04.03)
    a4["NB"] = 4
    assert _gkey(a2, rapid_fire_applied=2, target_sid="101") == _gkey(
        a4, rapid_fire_applied=2, target_sid="101"
    )


def test_different_targets_never_share_a_batch() -> None:
    """04.03 etape 1 « Select Enemy Unit » : un lot ne concerne qu'une seule unite cible."""
    assert _gkey(SHOOTA, rapid_fire_applied=1, target_sid="101") != _gkey(
        SHOOTA, rapid_fire_applied=1, target_sid="102"
    )


def test_same_weapon_splits_when_cleave_does_not_apply_to_every_fighter() -> None:
    """JUMEAU EXACT du cas [RAPID FIRE] ci-dessus, cote MELEE — 24.06.

    « if you only selected one target for ALL of that weapon's attacks » : deux figurines de la
    MEME escouade avec la MEME arme [CLEAVE] n'y ont pas droit pareil si l'une repartit ses
    attaques sur deux cibles. La signature declaree est identique, seule la valeur appliquee les
    separe — et 04.03 exige de les separer (« affected by the same APPLICABLE abilities »).

    Sans ce test, [CLEAVE] pouvait rester hors de la cle sans que rien ne le signale : c'est
    exactement l'etat du moteur jusqu'au 2026-08-10, ou le X applique de [RAPID FIRE] y etait et
    celui de [CLEAVE] non.
    """
    choppa = _weapon("Big Choppa", ["CLEAVE:1"])
    mono_cible = _gkey(choppa, rapid_fire_applied=0, cleave_applied=1, target_sid="101")
    attaques_reparties = _gkey(choppa, rapid_fire_applied=0, cleave_applied=0, target_sid="101")
    assert mono_cible != attaques_reparties


# ─────────────────────────────────────────────────────────────────────────────
# 3. Parite avec le site de production : la cle du test ne doit pas deriver
# ─────────────────────────────────────────────────────────────────────────────

def _run_real_grouping(rolled: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Fait tourner le VRAI `_build_manual_allocation` et rend ses `weapon_groups`.

    Le roller de phase est injectable (parametre `roll_intent_fn`) : on lui fait rendre des
    resultats fabriques, sans blessure a allouer (`pending_wounds` vide). Aucun lot n'est donc
    cree et l'allocation se termine immediatement — mais la boucle de GROUPEMENT, elle, est
    celle de la production, pas un miroir.
    """
    from engine.phase_handlers.shared_utils import SHOOT_CTX, _build_manual_allocation

    weapon = _weapon("Stub", [])
    models_cache = {
        f"1#{i}": {"squad_id": "1", "player": 1, "col": 10, "row": 10, "SHOOT_LEFT": 1,
                   "RNG_WEAPONS": [weapon], "HP_CUR": 2, "HP_MAX": 2, "VALUE": 10,
                   "points_per_hp": 5.0}
        for i in range(len(rolled))
    }
    _units = [
        {"id": "1", "player": 1, "col": 10, "row": 10, "unitType": "Stubber", "UNIT_RULES": []},
        {"id": "101", "player": 2, "col": 20, "row": 10, "unitType": "StubTarget", "UNIT_RULES": []},
        {"id": "102", "player": 2, "col": 30, "row": 10, "unitType": "StubTarget", "UNIT_RULES": []},
    ]
    game_state: Dict[str, Any] = {
        "units": _units,
        "unit_by_id": {u["id"]: u for u in _units},
        "action_logs": [],
        "action_log_seq": 0,
        "turn": 1,
        "models_cache": models_cache,
        "squad_models": {"1": list(models_cache), "101": ["101#0"], "102": ["102#0"]},
        "units_cache": {
            "1": {"col": 10, "row": 10, "player": 1, "VALUE": 100, "HP_CUR": 2, "HP_MAX": 2},
            "101": {"col": 20, "row": 10, "player": 2, "VALUE": 100, "HP_CUR": 2, "HP_MAX": 2},
            "102": {"col": 30, "row": 10, "player": 2, "VALUE": 100, "HP_CUR": 2, "HP_MAX": 2},
        },
        "config": {"game_rules": {"bonus_malus_cap": 0}},
        "squad_cache": {"1": {"model_count_at_start": len(models_cache)}, "101": {"model_count_at_start": 1}, "102": {"model_count_at_start": 1}},
        SHOOT_CTX.intents_key: {
            "1": [{"model_id": f"1#{i}", "weapon_index": 0, "target_unit_id": r["target_sid"],
                   "target_squad_size_at_declaration": 1}
                  for i, r in enumerate(rolled)]
        },
    }
    queue = list(rolled)

    def _fake_roller(gs, intent, targets_meta):
        r = queue.pop(0)
        r = {**r, "attacker": models_cache[str(intent["model_id"])],
             "attacker_mid": str(intent["model_id"])}
        targets_meta.setdefault(
            r["target_sid"], {"value": 100.0, "model_count_at_start": 1, "player": 2, "col": 20, "row": 10, "hp_before": 1}
        )
        return r

    _build_manual_allocation(game_state, "1", SHOOT_CTX, _fake_roller)
    # L'allocation se termine et purge sa cle : on observe ce qui SORT — un action_log de tir
    # par groupe, c'est-a-dire exactement ce que step.log et le replay recevront.
    return [e for e in game_state["action_logs"] if e.get("type") == "shoot"]


def _rolled(weapon: Dict[str, Any], *, rapid_fire_applied: int, target_sid: str) -> Dict[str, Any]:
    """Resultat de roller au profil BRUT commun : seules les regles varient."""
    return {
        "target_sid": target_sid, "weapon_name": weapon["display_name"],
        "bs": 5, "ap": 0, "dmg_raw": 1, "dmg_bonus": 0,
        # Seuils ENTIERS, comme les rends le vrai roller (`wound_threshold` /
        # `display_save_threshold_with_waaagh`) : l emission les relit pour rejouer l arbitrage
        # de [LETHAL HITS], un stub qui rendrait « 4+ » ne serait plus fidele au producteur.
        "display_wth": 4, "display_save_th": 5,
        "weapon_rules": weapon_rule_signature(weapon),
        # Arme + profil de regles gardes par REFERENCE : c est l emission qui en tire le token
        # `[RAPID FIRE:X]`, celui-la meme que le regroupement rendait ambigu avant 04.03.
        "weapon": weapon,
        "attack_profile": build_weapon_attack_profile(weapon, None),
        # Regles additives ayant joue -> leur X declare. Aucune de ces trois armes ne porte
        # [BLAST] ; [RAPID FIRE] n'y entre que quand la cible est a demi-portee, ce que le
        # parametre du helper modelise. C'est de LA que la cle de groupe et le step.log lisent
        # le X applique — il n'y a pas de second champ qui le porterait.
        "additive_rules_applied": (
            {RULE_LABEL_RAPID_FIRE: rapid_fire_applied} if rapid_fire_applied else {}
        ),
        # 10.06 : aucun MONSTER/VEHICLE dans ce scenario.
        "point_blank_malus": False,
        "indirect_fire_fail_below": False,
        # 10.05 / 10.06 : verdicts du portier, publies par le roller au meme titre que
        # `point_blank_malus`. Le groupe les lit en `require_key`, donc un intent muet leve.
        "assault_applied": False, "close_quarters_applied": False,
        "precision": False, "precision_range": None, "heavy_applied": False,
        # Oath (08.04) : le groupement copie ces deux clés de l'intent — un roller stub qui ne
        # les rend pas n'est plus fidèle au producteur.
        "oath_hit_reroll": False, "oath_wound_bonus": 0,
        # Waaagh! (08.04) : jumeau des deux clés ci-dessus, exigées par le groupement.
        "waaagh_melee_bonus": False, "waaagh_target_invul": False,
        "shot_records": [], "pending_wounds": [],
        "counts": {"attacks": 1, "hits": 0, "wounds": 0},
    }


def test_production_grouping_separates_the_three_shootas() -> None:
    """Le VRAI moteur, pas le miroir : trois armes de regles differentes -> trois groupes.

    C'est ce test qui echoue sur l'ancienne cle (un seul groupe, nomme
    « Shoota / Kombi Shoota / Kustom Shoota », portant une seule valeur de RAPID FIRE).
    """
    groups = _run_real_grouping([
        _rolled(SHOOTA, rapid_fire_applied=1, target_sid="101"),
        _rolled(KOMBI_SHOOTA, rapid_fire_applied=0, target_sid="101"),
        _rolled(KUSTOM_SHOOTA, rapid_fire_applied=2, target_sid="101"),
    ])
    assert len(groups) == 3, [g["weaponName"] for g in groups]
    assert sorted(g["weaponName"] for g in groups) == [
        "Kombi Shoota", "Kustom Shoota", "Shoota"
    ]
    # Chaque ligne porte SA valeur de RAPID FIRE : c'est ce que le controle analyzer exige.
    assert sorted(int(g["rapidFireApplied"]) for g in groups) == [0, 1, 2]


def test_production_grouping_still_merges_truly_identical_attacks() -> None:
    """Contre-epreuve sur le vrai moteur : 04.03 FUSIONNE les attaques identiques."""
    groups = _run_real_grouping([
        _rolled(SHOOTA, rapid_fire_applied=1, target_sid="101"),
        _rolled(SHOOTA, rapid_fire_applied=1, target_sid="101"),
    ])
    assert len(groups) == 1, [g["weaponName"] for g in groups]
    assert groups[0]["weaponName"] == "Shoota"


def test_both_rollers_publish_the_signature() -> None:
    """Tir ET melee : le jumeau manquant est le motif d'echec n°1 de ce depot."""
    import inspect

    from engine.phase_handlers import fight_handlers, shared_utils

    import re

    APPEL = "weapon_rule_signature(weapon)"
    for fn in (shared_utils._manual_roll_intent, fight_handlers._manual_roll_fight_intent):
        src = inspect.getsource(fn)
        # La cle peut etre publiee par l'appel direct OU par une variable locale liee a cet
        # appel (le roller de tir relit la signature plus haut, pour 10.05/10.06). Les deux
        # formes sont acceptees ; ce qui ne l'est pas, c'est qu'une SECONDE derivation des
        # regles de l'arme s'installe a cote de `weapon_rule_signature` — le jumeau manquant
        # est le motif d'echec n°1 de ce depot.
        publie = re.search(r'"weapon_rules":\s*([\w.]+\(weapon\)|[A-Za-z_]\w*)', src)
        assert publie, fn.__name__
        valeur = publie.group(1)
        if valeur != APPEL:
            assert re.search(rf'\b{re.escape(valeur)}\s*=\s*{re.escape(APPEL)}', src), (
                fn.__name__, valeur
            )


def test_signature_type_is_hashable() -> None:
    """La cle de groupe est un tuple utilise en cle de dict : un set nu leverait a l'insertion."""
    sig: FrozenSet[str] = weapon_rule_signature(SHOOTA)
    assert isinstance(sig, frozenset)
    index: Dict[Tuple, int] = {_gkey(SHOOTA, rapid_fire_applied=1, target_sid="101"): 0}
    assert len(index) == 1
