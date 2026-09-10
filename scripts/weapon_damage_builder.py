#!/usr/bin/env python3
"""
weapon_damage_builder.py - Pre-compute expected damage for all weapon × target profile combinations.

Generates config/weapon_damage_table.json used by engine/weapon_damage_cache.py
to eliminate all runtime weapon probability calculations.

Usage:
    python scripts/weapon_damage_builder.py

Output:
    config/weapon_damage_table.json

Architecture:
    - Parses EVERY armory present under frontend/src/roster via engine/weapons/parser.py
    - Extracts unique offensive profiles: (ATK, STR, expected_NB, expected_DMG, AP, TORRENT)
    - Enumerates all realistic defensive profiles: (T, ARMOR_SAVE, INVUL_SAVE)
    - Computes expected_damage_per_activation for each (offensive, defensive) pair
    - Runtime: TTK = HP_CUR / expected_damage, kill_prob = min(1.0, expected_damage / HP_CUR)

TROIS DEFAUTS CORRIGES LE 2026-09-10, mesures ensemble : 57 des 231 armes des armureries
n avaient AUCUNE entree dans la table, et `lookup_best_weapon` rendait 0 degat pour chacune.

1. LA LISTE DE FACTIONS ETAIT ECRITE EN DUR (`spaceMarine, tyranid, aeldari, adeptusCustodes,
   chaos`) alors que six armureries existent. Les 18 armes orkes absentes venaient de la :
   `shoota`, `slugga`, `rokkit_launcha`... donc TOUTE escouade orke passait pour incapable de
   tirer. Les armureries sont desormais DECOUVERTES sur le disque, pour qu en ajouter une
   suffise a la faire entrer dans la table.
2. LA CLE OFFENSIVE IGNORAIT [TORRENT] 24.37. La probabilite de toucher etait (7 - ATK) / 6,
   or les armes a touche automatique portent ATK 7 dans les armureries : (7 - 7) / 6 = 0, donc
   degat nul contre TOUTE cible, donc AUCUNE entree ecrite et profil absent de la table. Douze
   armes y tombaient (`flamer`, `heavy_flamer_vehicle`, `d_scythe`, `balefire_pike`...). La
   cle porte maintenant le drapeau TORRENT, sans quoi `heavy_flamer` (ATK 7, sans TORRENT) et
   `heavy_flamer_vehicle` (ATK 7, TORRENT) — profils numeriques IDENTIQUES — se partageraient
   une seule valeur, qui serait fausse pour l un des deux.
3. LA TABLE ETAIT PERIMEE : 27 armes ajoutees aux armureries depuis la derniere generation
   (2026-03-31) n y figuraient pas, dont `ballistus_lascannon`, `screamer_killer_talons` et
   `redemptor_fist`. Le seul remede est de la regenerer ; le verrou est desormais
   `tests/unit/engine/test_weapon_damage_table_completeness.py`, qui balaie chaque armurerie.

TOUT profil enumere est DECLARE dans `offensive_profiles`, meme celui dont l esperance de
degats est nulle partout. Sans cette liste, un profil sans entree serait indistinguable d un
profil oublie, et c est exactement le trou que ce chantier ferme : la table doit pouvoir dire
« je connais cette arme, et sa valeur est zero ».
"""

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from shared.json_atomic import json_draft  # noqa: E402  (dépend du sys.path ci-dessus)

# IMPORTS ORDINAIRES, et c est la QUATRIEME correction du 2026-09-10. Ce module chargeait
# `engine.combat_utils`, `engine.weapons.*` par chemin de fichier, via un `_load_module` maison,
# pour eviter `engine/__init__.py` (qui tire torch). Ce contournement est mort le jour ou
# `engine/combat_utils.py` a pris `from engine.game_utils import require_unit_by_id` : l import
# re-entre dans `engine/__init__`, qui charge `w40k_core`, qui reimporte `combat_utils` a demi
# initialise — ImportError des la premiere ligne du script. Le constructeur etait donc INEXECUTABLE,
# et c est ce qui rendait la table perimee : 27 armes ajoutees aux armureries depuis la derniere
# generation (2026-03-31) n y figuraient pas. Payer l import de torch une fois dans un script
# ponctuel coute quelques secondes ; un contournement qui pourrit la donnee en silence coute
# plus cher.
from engine.weapons.parser import get_armory_parser  # noqa: E402
# `weapon_off_key` : SOURCE UNIQUE de la cle offensive, partagee avec le moteur. Le constructeur
# la recopiait ; la copie aurait diverge de la table au premier champ ajoute — ce qui vient
# justement d arriver avec [TORRENT].
from engine.weapon_damage_cache import weapon_off_key  # noqa: E402

ROSTER_DIR = PROJECT_ROOT / "frontend" / "src" / "roster"

#: Plages defensives ENUMEREES, dimensionnees sur les valeurs REELLEMENT portees par les 179
#: datasheets des rosters (mesure du 2026-09-10), pas sur un maximum theorique. Le verrou est
#: `test_weapon_damage_table_completeness.py`, qui relit les datasheets et rougit des qu une
#: valeur en sort.
#:
#: T           : datasheets 2 a 10, plus le seul bonus de T applicable en cours de partie —
#:               `toughness_bonus_while_waaagh` (+1, BannerNob, 19.02/19.04) — soit 2 a 11.
#: ARMOR_SAVE  : datasheets 2 a 7 (7 = aucune). Aucun effet du depot ne la modifie ; l AP est
#:               applique dans la formule, pas dans la cle.
#: INVUL_SAVE  : valeur EFFECTIVE (`effective_invul_save`), donc la declaration amelioree par le
#:               Waaagh! (5+) et par `invul_save_override` (4+ Librarian, 5+ BannerNob).
#:               Datasheets 4 a 7, meilleur override 4 : la plage effective est 4 a 7.
T_RANGE = range(2, 12)
ARMOR_SAVE_RANGE = range(2, 8)
INVUL_SAVE_RANGE = range(4, 8)


def discover_factions() -> List[str]:
    """Factions dont une armurerie est CHARGEABLE, decouvertes sur le disque.

    Une liste ecrite en dur a coute 18 armes orkes — donc le tir de toute escouade orke — parce
    qu ajouter `frontend/src/roster/ork/armory.ts` ne suffisait pas a la mettre a jour. Leve si
    aucune armurerie n est trouvee : une table vide n est pas un resultat.
    """
    factions = sorted(p.parent.name for p in ROSTER_DIR.glob("*/armory.ts"))
    if not factions:
        raise FileNotFoundError(
            f"Aucune armurerie trouvee sous {ROSTER_DIR} (attendu <faction>/armory.ts)."
        )
    return factions


def _compute_expected_damage(
    atk: int, strength: int, exp_nb: float, exp_dmg: float, ap: int, torrent: int,
    toughness: int, armor_save: int, invul_save: int,
) -> float:
    """
    W40K expected damage formula (hit x wound x fail save x DMG, sans regle d'arme).

    [TORRENT] 24.37 (« does not make a Hit roll ») est la SEULE regle d arme portee par la cle :
    elle ne modifie pas une probabilite, elle SUPPRIME le jet, et l ignorer donnait 0 degat a
    toute arme a touche automatique — celles-ci portant ATK 7 dans les armureries, la formule
    (7 - 7) / 6 les rendait incapables de blesser quoi que ce soit.

    Returns expected_damage_per_activation (float). Zero if weapon cannot damage.
    """
    p_hit = 1.0 if torrent else max(0.0, min(1.0, (7 - atk) / 6.0))

    if strength >= toughness * 2:
        p_wound = 5.0 / 6.0
    elif strength > toughness:
        p_wound = 4.0 / 6.0
    elif strength == toughness:
        p_wound = 3.0 / 6.0
    elif strength * 2 <= toughness:
        p_wound = 1.0 / 6.0
    else:
        p_wound = 2.0 / 6.0

    save_target = min(armor_save - ap, invul_save)
    p_fail_save = max(0.0, min(1.0, (save_target - 1) / 6.0))

    return exp_nb * p_hit * p_wound * p_fail_save * exp_dmg


def _extract_offensive_profiles(parser: Any, factions: List[str]) -> Dict[Tuple, str]:
    """Extract all unique offensive profiles from every chargeable armory.

    Returns mapping: (ATK, STR, exp_NB, exp_DMG, AP, TORRENT) -> first weapon name (for logging).

    AUCUNE ARME N EST SAUTEE. Une caracteristique manquante ou une armurerie introuvable levent :
    les deux etaient auparavant un `print(WARNING); continue`, c est-a-dire un profil silencieusement
    absent de la table — et un profil absent vaut zero degat chez tous les bots. C est precisement
    le defaut que ce chantier ferme, il n a pas a survivre sous forme d avertissement.
    """
    profiles: Dict[Tuple, str] = {}

    for faction in factions:
        armory = parser.get_armory(faction)

        for weapon_code, weapon in armory.items():
            missing = [
                field for field in ("ATK", "STR", "NB", "DMG", "AP")
                if weapon.get(field) is None
            ]
            if missing:
                raise ValueError(
                    f"Arme {faction}/{weapon_code} : caracteristiques manquantes {missing}. "
                    "Une arme incomplete ne peut pas entrer dans la table, et l ignorer la "
                    "ferait valoir zero degat pour tous les bots."
                )

            off_key = weapon_off_key(weapon)
            if off_key not in profiles:
                display = weapon.get("display_name", weapon_code)
                profiles[off_key] = f"{faction}/{display}"

    return profiles


def build_weapon_damage_table() -> Dict[str, Any]:
    """Build the complete weapon damage table."""
    parser = get_armory_parser()

    factions = discover_factions()
    print(f"Extracting offensive profiles from {len(factions)} armories: {', '.join(factions)}")
    offensive_profiles = _extract_offensive_profiles(parser, factions)
    print(f"  Found {len(offensive_profiles)} unique offensive profiles")

    defensive_count = len(T_RANGE) * len(ARMOR_SAVE_RANGE) * len(INVUL_SAVE_RANGE)
    print(f"  Defensive profiles: T={T_RANGE.start}-{T_RANGE.stop - 1}, "
          f"ARMOR={ARMOR_SAVE_RANGE.start}-{ARMOR_SAVE_RANGE.stop - 1}, "
          f"INVUL={INVUL_SAVE_RANGE.start}-{INVUL_SAVE_RANGE.stop - 1} "
          f"= {defensive_count} profiles")

    total = len(offensive_profiles) * defensive_count
    print(f"  Computing {total} expected_damage values...")

    entries = []
    declared = []
    dead_profiles = []
    for off_key in sorted(offensive_profiles.keys()):
        atk, strength, exp_nb, exp_dmg, ap, torrent = off_key
        off_list = [atk, strength, exp_nb, exp_dmg, ap, torrent]
        declared.append(off_list)
        before = len(entries)

        for t in T_RANGE:
            for armor in ARMOR_SAVE_RANGE:
                for invul in INVUL_SAVE_RANGE:
                    dmg = _compute_expected_damage(
                        atk, strength, exp_nb, exp_dmg, ap, torrent,
                        t, armor, invul,
                    )
                    if dmg > 0.0:
                        entries.append([off_list, [t, armor, invul], round(dmg, 6)])

        if len(entries) == before:
            dead_profiles.append((off_key, offensive_profiles[off_key]))

    nonzero = len(entries)
    print(f"  Non-zero entries: {nonzero} / {total} ({100 * nonzero / total:.1f}%)")
    # Un profil sans AUCUNE entree reste DECLARE : c est ce qui permet a la table de distinguer
    # « arme connue, esperance nulle partout » de « arme oubliee ». Il est signale, parce qu il
    # revele presque toujours une donnee d armurerie fautive (ATK 7 sans [TORRENT], p. ex.).
    for off_key, display in dead_profiles:
        print(f"  NOTE: profil sans aucun degat possible, declare a vide : {display} {off_key}")

    table = {
        "version": 2,
        "description": "Pre-computed expected_damage for weapon×target profile combinations",
        "usage": "TTK = HP_CUR / expected_damage, kill_prob = min(1.0, expected_damage / HP_CUR)",
        "offensive_key_format": "[ATK, STR, expected_NB, expected_DMG, AP, TORRENT]",
        "defensive_key_format": "[T, ARMOR_SAVE, INVUL_SAVE]",
        "defensive_ranges": {
            "T": [T_RANGE.start, T_RANGE.stop - 1],
            "ARMOR_SAVE": [ARMOR_SAVE_RANGE.start, ARMOR_SAVE_RANGE.stop - 1],
            "INVUL_SAVE": [INVUL_SAVE_RANGE.start, INVUL_SAVE_RANGE.stop - 1],
        },
        "factions": factions,
        "offensive_profiles": declared,
        "offensive_profile_count": len(offensive_profiles),
        "defensive_profile_count": defensive_count,
        "nonzero_entry_count": nonzero,
        "entries": entries,
    }
    return table


def main():
    print("=== Weapon Damage Table Builder ===\n")
    table = build_weapon_damage_table()

    output_path = PROJECT_ROOT / "config" / "weapon_damage_table.json"
    # forme COMPACTE conservée : cette table est lue par le moteur et sa taille est le sujet
    # (elle est affichée juste en dessous). L'indentation du dépôt la ferait tripler pour rien —
    # seule l'atomicité vient du module.
    with json_draft(output_path) as f:
        json.dump(table, f, separators=(",", ":"))

    size_kb = os.path.getsize(output_path) / 1024
    print(f"\n  Written: {output_path}")
    print(f"  Size: {size_kb:.1f} KB")
    print("  Done!")


if __name__ == "__main__":
    main()
