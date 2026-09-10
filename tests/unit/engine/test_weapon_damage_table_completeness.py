"""La table de dégâts pré-calculée couvre TOUTES les armes de TOUTES les armureries.

Défaut d'origine, mesuré le 2026-09-10 : **57 des 231 armes des six armureries** n'avaient
aucune entrée dans `config/weapon_damage_table.json`, et `lookup_best_weapon` rendait
silencieusement 0 dégât pour chacune. Conséquence directe sur 5 Boyz contre 5 Intercessors :
`squad_expected_damage` rendait **0,0 au tir** — tous les bots tenaient toute escouade orke pour
incapable de tirer, et choisissaient leurs cibles et leurs charges sur cette invention.

Quatre causes distinctes y menaient, et ce fichier les verrouille une par une :

1. La liste de factions du constructeur était écrite en dur et ignorait `ork` (18 armes).
   → `test_toute_arme_de_toute_armurerie_a_un_profil_offensif`.
2. La clé offensive ignorait [TORRENT] 24.37, alors que les armes à touche automatique portent
   ATK 7 : (7 - 7) / 6 = 0 chance de toucher, donc aucune entrée écrite (12 armes).
   → `test_une_arme_torrent_peut_infliger_des_degats` et
     `test_torrent_separe_deux_armes_de_profil_numerique_identique`.
3. La table était périmée de cinq mois (27 armes ajoutées depuis).
   → même verrou que la cause 1 : le balayage rougit dès qu'une arme manque.
4. Le constructeur lui-même était inexécutable (contournement d'import mort).
   → hors de portée d'un test unitaire ; c'est la cause 3 qui le révèle.

Et le trou lui-même, celui qui transformait une donnée manquante en zéro dégât :
`test_un_profil_absent_de_la_table_leve_au_lieu_de_valoir_zero`.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest

from ai.unit_registry import UnitRegistry
from engine.game_state import WAAAGH_INVUL_SAVE
from engine.weapon_damage_cache import (
    _TABLE_PATH,
    load_weapon_damage_table,
    lookup_best_weapon,
    weapon_off_key,
)
from engine.weapons.parser import get_armory_parser
from engine.utils.weapon_helpers import weapon_has_rule

#: Racine des rosters : les armureries sont DÉCOUVERTES, exactement comme le constructeur les
#: découvre. Écrire la liste ici rejouerait la cause n° 1 dans le test censé la verrouiller.
_ROSTER_DIR = Path(__file__).resolve().parents[3] / "frontend" / "src" / "roster"


def _factions() -> List[str]:
    factions = sorted(p.parent.name for p in _ROSTER_DIR.glob("*/armory.ts"))
    assert factions, f"aucune armurerie sous {_ROSTER_DIR}"
    return factions


def _all_weapons() -> List[Tuple[str, str, Dict[str, Any]]]:
    """(faction, code, arme) pour toutes les armes de toutes les armureries chargeables."""
    parser = get_armory_parser()
    out: List[Tuple[str, str, Dict[str, Any]]] = []
    for faction in _factions():
        for code, weapon in parser.get_armory(faction).items():
            out.append((faction, code, weapon))
    return out


def test_toute_arme_de_toute_armurerie_a_un_profil_offensif() -> None:
    """LE verrou. Chaque `weapon_off_key` atteignable est une clé de la table.

    Une clé absente n'est pas « zéro dégât » : c'est une arme dont le moteur ne sait rien dire,
    et le lecteur des bots la traitait comme inoffensive. Le message d'échec nomme les armes,
    parce que la correction consiste à relancer `scripts/weapon_damage_builder.py`.
    """
    table = load_weapon_damage_table()

    absentes = [
        f"{faction}/{code} {weapon_off_key(weapon)}"
        for faction, code, weapon in _all_weapons()
        if weapon_off_key(weapon) not in table
    ]

    assert absentes == [], (
        f"{len(absentes)} armes sans profil offensif dans {_TABLE_PATH.name}. "
        f"Run: python3 scripts/weapon_damage_builder.py\n  " + "\n  ".join(absentes)
    )


def test_une_arme_torrent_peut_infliger_des_degats() -> None:
    """[TORRENT] 24.37 touche automatiquement : sa sous-table ne peut pas être vide.

    Les armes à touche automatique portent ATK 7 dans les armureries. Tant que la clé ignorait
    la règle, le constructeur leur appliquait (7 - ATK) / 6 = 0 et n'écrivait aucune entrée :
    profil déclaré mais vide, donc 0 dégât garanti pour `flamer`, `d_scythe`, `balefire_pike`...
    Une sous-table VIDE est un résultat légitime pour une arme qui ne peut blesser personne ;
    elle ne l'est jamais pour une arme qui touche à tous les coups.
    """
    table = load_weapon_damage_table()
    torrent = [
        (f"{faction}/{code}", weapon_off_key(weapon))
        for faction, code, weapon in _all_weapons()
        if weapon_has_rule(weapon, "TORRENT")
    ]
    assert torrent, "aucune arme [TORRENT] dans les armureries : le test ne prouve plus rien"

    vides = [name for name, key in torrent if not table[key]]

    assert vides == [], f"armes [TORRENT] incapables de blesser quoi que ce soit : {vides}"


def test_torrent_separe_deux_armes_de_profil_numerique_identique() -> None:
    """La règle fait partie de l'identité du profil, pas seulement du calcul.

    `heavy_flamer` (ATK 7, sans [TORRENT]) et `heavy_flamer_vehicle` (ATK 7, [TORRENT]) portent
    des caractéristiques numériques IDENTIQUES. Sans le sixième champ, ils partageraient une
    seule ligne de table, qui serait fausse pour l'un des deux — et l'ordre d'énumération des
    armureries déciderait lequel.
    """
    armory = get_armory_parser().get_armory("spaceMarine")
    sans_torrent = weapon_off_key(armory["heavy_flamer"])
    avec_torrent = weapon_off_key(armory["heavy_flamer_vehicle"])

    assert sans_torrent[:5] == avec_torrent[:5], "les deux profils ne sont plus numériquement égaux"
    assert sans_torrent != avec_torrent


def test_un_profil_absent_de_la_table_leve_au_lieu_de_valoir_zero() -> None:
    """T1 : un trou de DONNÉE lève ; il ne se déguise pas en « cette arme ne fait rien ».

    C'est ce silence qui a laissé 57 armes hors de la table sans qu'aucun bot ne s'en plaigne.
    L'absence d'une entrée DÉFENSIVE, elle, reste un zéro légitime (test suivant).
    """
    cache = {("M1", 1): (None,)}

    with pytest.raises(KeyError, match="profil offensif absent"):
        lookup_best_weapon(cache, "M1", (4, 3, 7), True)


def test_une_entree_defensive_absente_reste_un_zero() -> None:
    """L'autre moitié, et elle ne doit PAS lever : la table n'écrit pas les valeurs nulles.

    Une arme dont le profil est connu mais qui ne peut pas blesser CETTE cible-là vaut zéro, et
    c'est un résultat. Confondre les deux cas ferait lever sur une partie parfaitement normale.
    """
    cache = {("M1", 1): ({(4, 3, 7): 1.5},)}

    assert lookup_best_weapon(cache, "M1", (4, 3, 7), True) == (0, 1.5)
    assert lookup_best_weapon(cache, "M1", (10, 2, 4), True) == (-1, 0.0)


def _datasheet_defensive_values() -> Tuple[List[int], List[int], List[int]]:
    """(T, ARMOR_SAVE, INVUL_SAVE) EFFECTIFS possibles sur les 179 datasheets des rosters.

    Les unités `endlessDuty` aliasent les caractéristiques d'une autre datasheet (`static T =
    IntercessorSergeant.T`) et le registre les rend telles quelles, sous forme de chaîne : elles
    sont résolues ici, sans quoi le balayage porterait sur un sous-ensemble en se croyant complet.

    Les MODIFICATEURS applicables en cours de partie sont inclus, parce que c'est la valeur
    effective que `effective_defensive_profile` remet à la table :
      * `toughness_bonus_while_waaagh` (19.02/19.04) augmente la T ;
      * `invul_save_override` (19.04) et le Waaagh! (08.04) améliorent l'invulnérable.

    Ces deux règles sont CONFÉRÉES À TOUTE L'UNITÉ ATTACHÉE par 19.04 : le +1 T du BannerNob
    profite aux figurines qu'il rejoint, pas à lui seul. Le bonus et l'override sont donc
    appliqués à CHAQUE datasheet, et non à leur seul porteur — les borner sur le porteur laissait
    passer une plage trop étroite d'un cran, ce qui est exactement le silence que ce test existe
    pour empêcher.
    """
    registry = UnitRegistry()
    data = {name: registry.get_unit_data(name) for name in registry.units}

    def _value(unit: Dict[str, Any], field: str) -> int:
        raw = unit[field]
        if isinstance(raw, str):
            source, _, aliased = raw.partition(".")
            return int(data[source][aliased])
        return int(raw)

    bonus_max = 0
    override_min = WAAAGH_INVUL_SAVE
    for unit in data.values():
        for rule in unit["UNIT_RULES"]:
            args = rule.get("rule_args", {})
            if rule["ruleId"] == "toughness_bonus_while_waaagh":
                bonus_max = max(bonus_max, int(args["toughness_bonus"]))
            elif rule["ruleId"] == "invul_save_override":
                override_min = min(override_min, int(args["value"]))

    toughness: List[int] = []
    armor: List[int] = []
    invul: List[int] = []
    for unit in data.values():
        base_t = _value(unit, "T")
        toughness += [base_t, base_t + bonus_max]
        armor.append(_value(unit, "ARMOR_SAVE"))
        base_inv = _value(unit, "INVUL_SAVE")
        invul += [base_inv, min(base_inv, override_min)]
    return toughness, armor, invul


def test_les_plages_defensives_couvrent_les_datasheets() -> None:
    """Les plages énumérées sont DIMENSIONNÉES sur les datasheets, donc elles doivent les couvrir.

    Elles ont été resserrées le 2026-09-10 sur la mesure (T 2-11, Sv 2-7, InSv 4-7) plutôt que
    laissées à un maximum théorique. Le prix de ce choix est ce test : une datasheet portant une
    valeur hors plage rendrait 0 dégât en silence, exactement comme une arme absente. Ajouter une
    telle datasheet doit donc rougir ici, pas passer inaperçu en partie.
    """
    with open(_TABLE_PATH, "r", encoding="utf-8") as handle:
        ranges = json.load(handle)["defensive_ranges"]
    toughness, armor, invul = _datasheet_defensive_values()

    for label, values in (("T", toughness), ("ARMOR_SAVE", armor), ("INVUL_SAVE", invul)):
        low, high = ranges[label]
        hors = sorted({v for v in values if not low <= v <= high})
        assert hors == [], (
            f"{label} : valeurs {hors} hors de la plage énumérée [{low}, {high}]. "
            "Élargir la plage dans scripts/weapon_damage_builder.py puis régénérer la table."
        )
