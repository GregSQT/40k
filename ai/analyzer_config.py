"""
analyzer_config.py - Static configuration loaded once at analyzer startup.

load_analyzer_config() reads all unit/weapon/rule data from disk and returns
an AnalyzerConfig that handlers can use as a read-only context.
"""

import os
import sys
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from shared.data_validation import require_key
from engine.utils.weapon_helpers import weapon_rule_parameter, weapon_rule_parameter_or
from engine.game_state import FACTION_ABILITY_KEYWORD_BY_RULE_ID, unit_faction_keywords

# Échelle subhex/pouce du run en cours d'analyse, lue dans l'entête `Board:` du step.log.
#
# Elle vit ICI, et pas dans `ai/analyzer.py`, parce que ce dernier est exécuté comme `__main__`
# par la CLI : les handlers qui font `from ai.analyzer import ...` en chargent alors une SECONDE
# copie, avec ses propres globales. Une valeur posée par la CLI n'y serait jamais visible. Ce
# module, lui, n'est importé que par son chemin de paquet — il n'existe donc qu'en un exemplaire.
_run_inches_to_subhex: Optional[int] = None

# Valeurs de règle du run ANALYSÉ, lues dans l'entête `Run rules:` du step.log. Même raison que
# l'échelle : `config/game_config.json` s'édite entre deux runs, et le relire au moment de
# l'analyse rend des verdicts faux en silence. Même emplacement, pour la même raison (module
# chargé en un seul exemplaire).
_run_rules: Optional[Dict[str, str]] = None

# Dimensions du plateau du run ANALYSÉ, lues dans la même entête `Board:` que l'échelle. Même
# emplacement et même raison : le BFS de mouvement doit refuser un pas HORS PLATEAU (03.01,
# « it cannot be moved off the battlefield »), et le seul plateau qui fasse foi est celui du
# journal relu, pas celui du `config/board/*.json` du jour.
_run_board_dims: Optional[Tuple[int, int]] = None


def reset_run_state() -> None:
    """Ramène l'état du run analysé à « non posé », c'est-à-dire à l'état d'import du module.

    Une passe de production n'en a pas besoin — `parse_step_log` repose les trois valeurs depuis
    l'entête de chaque journal. C'est l'ARBRE DE TEST qui l'appelle, entre deux tests d'un même
    worker : les valeurs posées à la main par l'un restaient visibles pour le suivant, et le
    voisin qui avait oublié de les poser passait en vert sur l'échelle ou le plateau d'autrui.

    La fonction vit ICI, avec les globales et leurs setters, plutôt qu'en trois affectations
    recopiées dans un `conftest` : une quatrième valeur de run ajoutée au-dessus doit être remise
    à zéro au même endroit qu'elle est déclarée, sans quoi elle échappera à la remise à zéro sans
    que rien ne le dise.
    """
    global _run_inches_to_subhex, _run_rules, _run_board_dims
    _run_inches_to_subhex = None
    _run_rules = None
    _run_board_dims = None


def set_run_rules(rules: Dict[str, str]) -> None:
    """Fixe les règles du run pour toute la passe d'analyse."""
    global _run_rules
    if not isinstance(rules, dict) or not rules:
        raise ValueError(f"run_rules invalide: {rules!r}")
    for k, v in rules.items():
        if not isinstance(v, str):
            raise TypeError(
                f"run_rules[{k!r}] doit être str, reçu {type(v).__name__}: {v!r}"
            )
    _run_rules = dict(rules)


def get_run_rule(key: str) -> str:
    """Valeur d'une règle du run. Lève si l'entête n'a pas été lue ou ne porte pas la clé :
    prendre celle du config courant produirait un verdict faux sans le dire."""
    if _run_rules is None:
        raise RuntimeError(
            "Règles du run non fixées : set_run_rules() doit être appelé depuis l'entête "
            "`Run rules:` du step.log avant tout contrôle de règle."
        )
    if key not in _run_rules:
        raise KeyError(
            f"Règle {key!r} absente de l'entête `Run rules:` du step.log "
            f"(présentes : {sorted(_run_rules)})"
        )
    return _run_rules[key]


def get_run_rule_optional(key: str) -> Optional[str]:
    """Valeur d'une règle du run, ou ``None`` si la clé est absente.

    Réservé aux clés introduites après les premiers journaux de production : un log ANCIEN
    n'a pas la clé, et l'absence est un comportement valide (pas une erreur).
    Lève quand même si ``set_run_rules()`` n'a pas encore été appelé.
    """
    if _run_rules is None:
        raise RuntimeError(
            "Règles du run non fixées : set_run_rules() doit être appelé depuis l'entête "
            "`Run rules:` du step.log avant tout contrôle de règle."
        )
    return _run_rules.get(key)


def set_run_inches_to_subhex(inches_to_subhex: int) -> None:
    """Fixe l'échelle du run pour toute la passe d'analyse."""
    global _run_inches_to_subhex
    if not isinstance(inches_to_subhex, int) or isinstance(inches_to_subhex, bool) or inches_to_subhex <= 0:
        raise ValueError(f"inches_to_subhex invalide: {inches_to_subhex!r}")
    _run_inches_to_subhex = inches_to_subhex


def get_run_inches_to_subhex() -> int:
    """Échelle du run. Lève si elle n'a pas été posée : analyser à l'échelle du config courant
    produirait des distances fausses (faux positifs d'engagement, contrôles de portée neutralisés)."""
    if _run_inches_to_subhex is None:
        raise RuntimeError(
            "Échelle du run non fixée : set_run_inches_to_subhex() doit être appelé depuis "
            "l'entête `Board:` du step.log avant tout contrôle géométrique."
        )
    return _run_inches_to_subhex


def set_run_board_dims(cols: int, rows: int) -> None:
    """Fixe les dimensions du plateau du run pour toute la passe d'analyse."""
    global _run_board_dims
    for name, value in (("cols", cols), ("rows", rows)):
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ValueError(f"Board {name} invalide: {value!r}")
    _run_board_dims = (cols, rows)


def get_run_board_dims() -> Tuple[int, int]:
    """`(cols, rows)` du plateau du run. Lève si l'entête n'a pas été lue : un BFS qui ignore le
    bord accepte un chemin sortant du plateau (03.01), et prendre les dimensions du config
    courant relirait un vieux journal sur un autre plateau."""
    if _run_board_dims is None:
        raise RuntimeError(
            "Dimensions du plateau non fixées : set_run_board_dims() doit être appelé depuis "
            "l'entête `Board:` du step.log avant tout contrôle de chemin."
        )
    return _run_board_dims


def _numeric(value: Any) -> Optional[int]:
    """Valeur entière d'une caractéristique du registre, ou ``None`` si elle est SYMBOLIQUE.

    Le registre porte parfois une référence non résolue (``'LieutenantPowerFistPlasmaPistol.T'``)
    à la place d'un entier. ``None`` dit « pas de valeur exploitable », il ne remplace aucune
    valeur : les appelants sautent l'entrée au chargement et lèvent au moment où la donnée sert
    vraiment, pour une unité réellement jouée.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        s = value.strip()
        s_no_sign = s.lstrip("-")
        if s_no_sign and s_no_sign.isdigit() and s.count("-") <= 1:
            return int(s)
    return None


def _int_by_weapon(weapons: Any, field_name: str) -> Dict[str, int]:
    """Carte ``display_name -> <field_name>`` des armes dont la caractéristique est numérique."""
    out: Dict[str, int] = {}
    for weapon in weapons:
        if not isinstance(weapon, dict):
            continue
        value = _numeric(require_key(weapon, field_name))
        if value is not None:
            out[require_key(weapon, "display_name")] = value
    return out


@dataclass
class AnalyzerConfig:
    unit_registry: Any
    config_loader: Any
    unit_weapons_cache: Dict[str, List]
    unit_attack_limits: Dict[str, Dict]
    unit_combi_by_weapon: Dict[str, Dict]
    unit_rules_by_type: Dict[str, Set[str]]
    unit_move_after_shooting_distance_by_type: Dict[str, int]
    unit_is_fly_by_type: Dict[str, bool]
    unit_is_monster_or_vehicle_by_type: Dict[str, bool]
    # Socles du registre CONVERTIS à la résolution du run (`_scale_socle`), MÉMOÏSÉS à la
    # demande : c'est une fonction pure de (unit_type, échelle), résolue une fois au lieu de
    # deux fois par ligne de tir et une fois par ennemi vivant sur chaque WAIT. Rempli
    # paresseusement — certaines entrées du registre portent un BASE_SIZE symbolique qui ne se
    # résout que pour les unités réellement jouées ; le pré-calculer pour tout le registre
    # ferait lever au chargement sur des unités absentes du log.
    unit_socle_by_type: Dict[str, Any]
    unit_choice_effect_to_source_rules: Dict[str, Dict[str, Set[str]]]
    display_rule_name_to_ids: Dict[str, Set[str]]
    #: `effet technique -> noms d'affichage de DATASHEET` qui le confèrent, en MAJUSCULES.
    #: C'est la forme sous laquelle le journal les écrit (`step_logger._ability_token`), donc
    #: la seule qui permette de reconnaître un token de step.log comme celui d'un effet.
    effect_display_tokens: Dict[str, Set[str]]
    rule_to_units: Dict[str, Set[str]]
    weapon_rule_to_weapons: Dict[str, Set[str]]
    resolve_rule_id: Callable  # closure over all_unit_rules_config
    inches_to_subhex: int
    # Cartes GLOBALES arme→NB/portée, agrégées sur TOUS les model-types du registre.
    # Une escouade V11 est hétérogène (ex. "Boyz" contient Warboss/PainBoy/Nob...) ; l'arme
    # loguée peut appartenir à un model-type du squad et non à l'entrée unit_type. La
    # résolution per-unit-type échoue alors → on retombe sur ces cartes globales. En cas de
    # même nom d'arme avec NB différents entre model-types, on retient le MAX (plafond).
    rng_nb_by_weapon_global: Dict[str, int]
    cc_nb_by_weapon_global: Dict[str, int]
    rapid_fire_by_weapon_global: Dict[str, int]
    #: X déclaré de [BLAST] 24.05 (tir) et [CLEAVE] 24.06 (mêlée) — les deux règles qui ajoutent
    #: X dés par tranche de 5 figurines de la CIBLE. Mêmes cartes, même agrégation que ci-dessus :
    #: l'arme se résout par FIGURINE, et le porteur d'une arme CLEAVE est presque toujours un
    #: personnage rattaché (règle 19) dont le type diffère de celui de l'escouade.
    blast_by_weapon_global: Dict[str, int]
    cleave_by_weapon_global: Dict[str, int]
    sustained_hits_by_weapon_global: Dict[str, int]
    weapon_range_global: Dict[str, int]
    weapon_is_close_quarters_global: Dict[str, bool]
    # Cartes GLOBALES arme→STR/ATK (mêlée uniquement pour cc_str/cc_atk), agrégées sur tous les
    # model-types du registre. Même motif que rng_nb_by_weapon_global / cc_nb_by_weapon_global :
    # un leader rattaché porte une arme dont le type diffère de celui de l'escouade ; la résolution
    # per-unit-type échoue et on tombe ici. MAX en cas d'homonymie inter-datasheets.
    rng_str_by_weapon_global: Dict[str, int]
    cc_str_by_weapon_global: Dict[str, int]
    cc_atk_by_weapon_global: Dict[str, int]
    #: ENDURANCE par datasheet. Par FIGURINE et non par escouade : 19.02 impose la plus haute E
    #: des figurines bodyguard, jamais celle du leader rattaché.
    unit_toughness_by_type: Dict[str, int]
    #: Nombre de tours maximum déclaré dans game_config (07.02 / P2). 0 = non disponible.
    max_turns: int
    #: Cap sur le total des modificateurs de jet (0 = pas de cap, comportement 10e).
    bonus_malus_cap: int


def load_analyzer_config() -> AnalyzerConfig:
    """Load all static unit/weapon/rule config from disk. Called once per parse run.

    L'échelle vient de `get_run_inches_to_subhex()`, donc de l'entête `Board:` du step.log
    analysé — JAMAIS de `board_config`, qui décrit le prochain run et pas celui qu'on relit.
    Elle met à l'échelle les portées d'armes et la distance de move-after-shooting ci-dessous.
    La prendre en paramètre ouvrait un second canal : un appelant pouvait poser une échelle et
    en passer une autre, sans que rien ne le détecte.
    """
    from ai.unit_registry import UnitRegistry
    from config_loader import get_config_loader
    from ai.analyzer import max_dice_value

    inches_to_subhex = get_run_inches_to_subhex()
    unit_registry = UnitRegistry()
    config_loader = get_config_loader()
    all_unit_rules_config = config_loader.load_unit_rules_config()

    def resolve_effect_rule_id_to_technical(
        rule_id: str, visited: Optional[Set[str]] = None
    ) -> str:
        if not isinstance(rule_id, str) or not rule_id.strip():
            raise ValueError(f"Invalid rule id for analyzer resolution: {rule_id!r}")
        normalized_rule_id = rule_id.strip()
        if normalized_rule_id not in all_unit_rules_config:
            raise KeyError(
                f"Unknown rule id '{normalized_rule_id}' while resolving unit rules in analyzer"
            )
        if visited is None:
            visited = set()
        if normalized_rule_id in visited:
            raise ValueError(
                f"Rule alias cycle detected in config/unit_rules.json for '{normalized_rule_id}'"
            )
        visited.add(normalized_rule_id)
        rule_config = all_unit_rules_config[normalized_rule_id]
        alias = rule_config.get("alias")
        if alias is None:
            return normalized_rule_id
        if not isinstance(alias, str) or not alias.strip():
            raise ValueError(
                f"Rule '{normalized_rule_id}' has invalid alias in config/unit_rules.json: {alias!r}"
            )
        return resolve_effect_rule_id_to_technical(alias.strip(), visited)

    unit_weapons_cache: Dict[str, List] = {}
    unit_attack_limits: Dict[str, Dict] = {}
    unit_combi_by_weapon: Dict[str, Dict] = {}
    unit_rules_by_type: Dict[str, Set[str]] = {}
    unit_move_after_shooting_distance_by_type: Dict[str, int] = {}
    unit_is_fly_by_type: Dict[str, bool] = {}
    unit_is_monster_or_vehicle_by_type: Dict[str, bool] = {}
    unit_socle_by_type: Dict[str, Any] = {}
    unit_choice_effect_to_source_rules: Dict[str, Dict[str, Set[str]]] = {}
    # Mots-clés de FACTION par type d'unité, sous la forme NORMALISÉE du moteur : c'est eux qui
    # portent les capacités de faction, absentes des `UNIT_RULES` (cf. plus bas).
    unit_faction_keywords_by_type: Dict[str, frozenset] = {}
    unit_toughness_by_type: Dict[str, int] = {}
    display_rule_name_to_ids: Dict[str, Set[str]] = {}
    effect_display_tokens: Dict[str, Set[str]] = {}

    for display_rule_id, rule_cfg in all_unit_rules_config.items():
        rule_name_raw = rule_cfg.get("name")
        if not isinstance(rule_name_raw, str) or not rule_name_raw.strip():
            continue
        normalized_rule_name = rule_name_raw.strip().upper()
        if normalized_rule_name not in display_rule_name_to_ids:
            display_rule_name_to_ids[normalized_rule_name] = set()
        display_rule_name_to_ids[normalized_rule_name].add(display_rule_id)

    for unit_type, unit_data in unit_registry.units.items():
        rng_weapons = require_key(unit_data, "RNG_WEAPONS")
        cc_weapons = require_key(unit_data, "CC_WEAPONS")
        unit_keywords = require_key(unit_data, "UNIT_KEYWORDS")
        keyword_ids_lower = {
            str(require_key(keyword_entry, "keywordId")).strip().lower()
            for keyword_entry in unit_keywords
        }
        unit_is_fly_by_type[unit_type] = "fly" in keyword_ids_lower
        unit_faction_keywords_by_type[unit_type] = unit_faction_keywords(unit_data)
        # 10.06 / 17.03 : les MONSTER/VEHICLE tirent engagés avec TOUTES leurs armes et peuvent
        # être pris pour cible alors qu'ils sont engagés. Sans ce drapeau, chaque tir d'un
        # LandSpeeder au contact remontait « tir invalide » + « cible engagée ».
        unit_is_monster_or_vehicle_by_type[unit_type] = bool(
            keyword_ids_lower & {"monster", "vehicle"}
        )
        rng_nb_by_weapon: Dict[str, int] = {}
        rapid_fire_by_weapon: Dict[str, int] = {}
        blast_by_weapon: Dict[str, int] = {}
        cleave_by_weapon: Dict[str, int] = {}
        sustained_hits_by_weapon: Dict[str, int] = {}
        combi_by_weapon: Dict[str, str] = {}
        for weapon in rng_weapons:
            if isinstance(weapon, dict):
                weapon_name = require_key(weapon, "display_name")
                rng_nb_by_weapon[weapon_name] = max_dice_value(
                    require_key(weapon, "NB"),
                    "analyzer_rng_nb",
                )
                # Paramètre des règles d'armes paramétrées : helper MOTEUR
                # (`weapon_rule_parameter`), qui est déjà le miroir mutualisé de l'extraction
                # RAPID_FIRE de ce fichier. Le redoubler ici ferait diverger deux contrats —
                # la copie locale acceptait encore la forme objet que le moteur rejette depuis
                # le 2026-07-29. `None` = l'arme ne déclare pas la règle → 0, neutre.
                rapid_fire_by_weapon[weapon_name] = weapon_rule_parameter(weapon, "RAPID_FIRE") or 0
                # [BLAST] 24.05 : paramètre OPTIONNEL par les règles — la forme nue `[BLAST]`
                # vaut « 1 dé par tranche de 5 », la forme `[BLAST 2]` vaut 2. D'où le helper
                # moteur `weapon_rule_parameter_or` et non `weapon_rule_parameter`, qui lèverait
                # sur la forme nue (celle de 4 des 5 armes BLAST du dépôt). Le défaut 1 est une
                # valeur MÉTIER du PDF, pas un repli anti-erreur.
                blast_by_weapon[weapon_name] = weapon_rule_parameter_or(weapon, "BLAST", 1) or 0
                sustained_hits_by_weapon[weapon_name] = weapon_rule_parameter(weapon, "SUSTAINED_HITS") or 0
                combi_key = weapon.get("COMBI_WEAPON")
                if combi_key is not None:
                    combi_by_weapon[weapon_name] = combi_key
        cc_nb_by_weapon: Dict[str, int] = {}
        for weapon in cc_weapons:
            if isinstance(weapon, dict):
                weapon_name = require_key(weapon, "display_name")
                cc_nb_by_weapon[weapon_name] = max_dice_value(
                    require_key(weapon, "NB"),
                    "analyzer_cc_nb",
                )
                # [CLEAVE] 24.06 : JUMEAU mêlée de [BLAST], même helper, même défaut métier.
                cleave_by_weapon[weapon_name] = weapon_rule_parameter_or(weapon, "CLEAVE", 1) or 0
        # FORCE par arme (05.02) : lue au MÊME endroit et sous la même clé de nom que le NB, pour
        # que la résolution par-figurine (`resolve_weapon_value`) marche à l'identique.
        #
        # ENTRÉES SYMBOLIQUES IGNORÉES ICI. Le registre porte, pour certaines datasheets, une
        # référence non résolue (`'LieutenantPowerFistPlasmaPistol.T'`) au lieu d'un entier —
        # même phénomène que le `BASE_SIZE` symbolique de `unit_socle_by_type`, et même
        # traitement : les pré-calculer pour TOUT le registre ferait lever au chargement sur des
        # unités absentes du log. L'absence se rattrape là où la donnée sert : le contrôle du
        # seuil de blessure lève pour une unité RÉELLEMENT jouée dont la F ou l'E manque.
        rng_str_by_weapon = _int_by_weapon(rng_weapons, "STR")
        cc_str_by_weapon = _int_by_weapon(cc_weapons, "STR")
        # CARACTERISTIQUE DE TOUCHE de mêlée (WS), lue au MÊME endroit et sous la même clé de nom
        # que la Force juste au-dessus, et pour la même raison : le contrôle du seuil de touche
        # (`analyzer_hit.check_melee_hit_threshold`) doit la résoudre PAR FIGURINE — cinq armes
        # s'appellent « Close Combat Weapon » et leur WS diffère selon la datasheet.
        cc_atk_by_weapon = _int_by_weapon(cc_weapons, "ATK")
        _t_raw = require_key(unit_data, "T")
        if _numeric(_t_raw) is not None:
            unit_toughness_by_type[unit_type] = int(_t_raw)
        unit_attack_limits[unit_type] = {
            "rng_nb_by_weapon": rng_nb_by_weapon,
            "cc_nb_by_weapon": cc_nb_by_weapon,
            "rapid_fire_by_weapon": rapid_fire_by_weapon,
            "blast_by_weapon": blast_by_weapon,
            "cleave_by_weapon": cleave_by_weapon,
            "sustained_hits_by_weapon": sustained_hits_by_weapon,
            "rng_str_by_weapon": rng_str_by_weapon,
            "cc_str_by_weapon": cc_str_by_weapon,
            "cc_atk_by_weapon": cc_atk_by_weapon,
        }
        weapons_info: List[Dict] = []
        for weapon in rng_weapons:
            if isinstance(weapon, dict):
                weapon_rules = require_key(weapon, "WEAPON_RULES")
                weapons_info.append(
                    {
                        "name": require_key(weapon, "display_name"),
                        "range": require_key(weapon, "RNG") * inches_to_subhex,
                        "rules": weapon_rules,
                        "is_close_quarters": "CLOSE_QUARTERS" in weapon_rules,
                        "is_melee": False,
                    }
                )
        # Armes de MÊLÉE dans le même registre. Sans elles, aucune règle propre à la mêlée
        # n'existait pour le rapport : le tableau d'usage §1.8 était intégralement construit sur
        # ce cache, donc il ne listait que des armes de tir et déclarait implicitement que les
        # 54 profils de mêlée des rosters n'ont aucune règle. Mesuré : 32 paires (règle, arme)
        # invisibles, dont les 2 armes [CLEAVE] dont le moteur écrit désormais le token.
        #
        # `is_melee` n'est PAS décoratif : trois noms d'affichage existent des DEUX côtés
        # (`Castellan Axe`, `Guardian Spear`, `Sentinel Blade` — profils Custodes tir + mêlée).
        # Sans le drapeau, la résolution par nom rendrait pour ces trois-là le profil de l'autre
        # phase : règles fausses dans le tableau d'usage, et surtout portée absente pour un
        # contrôle de portée de tir. Chaque lecture filtre donc selon la phase de la ligne.
        #
        # `range` vaut 0 : une arme de mêlée n'a pas de portée, ce n'est pas une valeur
        # manquante qu'on masquerait. Les lecteurs de portée écartent d'abord `is_melee`.
        for weapon in cc_weapons:
            if isinstance(weapon, dict):
                weapon_rules = require_key(weapon, "WEAPON_RULES")
                weapons_info.append(
                    {
                        "name": require_key(weapon, "display_name"),
                        "range": 0,
                        "rules": weapon_rules,
                        "is_close_quarters": "CLOSE_QUARTERS" in weapon_rules,
                        "is_melee": True,
                    }
                )
        unit_weapons_cache[unit_type] = weapons_info
        unit_combi_by_weapon[unit_type] = combi_by_weapon
        unit_rules = require_key(unit_data, "UNIT_RULES")
        expanded_rule_ids: Set[str] = set()
        choice_effect_to_source_rules_for_unit: Dict[str, Set[str]] = {}
        for rule in unit_rules:
            direct_rule_id = require_key(rule, "ruleId")
            direct_rule_technical = resolve_effect_rule_id_to_technical(direct_rule_id)
            expanded_rule_ids.add(direct_rule_technical)
            if "grants_rule_ids" in rule:
                granted_rule_ids = rule["grants_rule_ids"]
            else:
                granted_rule_ids = []
            if not isinstance(granted_rule_ids, list):
                raise TypeError(
                    f"UNIT_RULES entry for '{direct_rule_id}' has invalid grants_rule_ids type: "
                    f"{type(granted_rule_ids).__name__}"
                )
            for granted_rule_id in granted_rule_ids:
                granted_rule_technical = resolve_effect_rule_id_to_technical(
                    str(granted_rule_id)
                )
                expanded_rule_ids.add(granted_rule_technical)
                if granted_rule_technical not in choice_effect_to_source_rules_for_unit:
                    choice_effect_to_source_rules_for_unit[granted_rule_technical] = set()
                choice_effect_to_source_rules_for_unit[granted_rule_technical].add(
                    direct_rule_id
                )
            rule_effect_ids = {
                direct_rule_technical,
                *[
                    resolve_effect_rule_id_to_technical(str(rid))
                    for rid in granted_rule_ids
                ],
            }
            # TOKEN que le journal écrit pour cet effet : le `displayName` de la DATASHEET, mis
            # en majuscules par `step_logger._ability_token`. C'est le seul lien entre un effet
            # technique et le texte de step.log — `display_rule_name_to_ids` ci-dessus part du
            # `name` du REGISTRE (« Charge roll bonus »), que le journal n'écrit jamais.
            _display_name = rule.get("displayName")
            if isinstance(_display_name, str) and _display_name.strip():
                for _effect_id in rule_effect_ids:
                    effect_display_tokens.setdefault(_effect_id, set()).add(
                        _display_name.strip().upper()
                    )
            if "move_after_shooting" in rule_effect_ids:
                rule_args = rule.get("rule_args")
                if not isinstance(rule_args, dict):
                    raise ValueError(
                        f"Unit '{unit_type}' rule '{direct_rule_id}' must define rule_args for move_after_shooting"
                    )
                if "distance" in rule_args:
                    move_after_shooting_distance = rule_args["distance"]
                    if not isinstance(move_after_shooting_distance, int):
                        raise TypeError(
                            f"Unit '{unit_type}' rule '{direct_rule_id}' rule_args.distance must be int, "
                            f"got {type(move_after_shooting_distance).__name__}"
                        )
                    if move_after_shooting_distance <= 0:
                        raise ValueError(
                            f"Unit '{unit_type}' rule '{direct_rule_id}' rule_args.distance must be > 0, "
                            f"got {move_after_shooting_distance}"
                        )
                elif "distance_dice" in rule_args:
                    dice_spec = rule_args["distance_dice"]
                    move_after_shooting_distance = max_dice_value(
                        dice_spec, "analyzer_move_after_shooting_dice"
                    )
                else:
                    raise ValueError(
                        f"Unit '{unit_type}' rule '{direct_rule_id}' missing rule_args.distance (int) "
                        f"or rule_args.distance_dice (str) for move_after_shooting"
                    )
                scaled_distance = move_after_shooting_distance * inches_to_subhex
                existing_distance = unit_move_after_shooting_distance_by_type.get(unit_type)
                if existing_distance is not None and existing_distance != scaled_distance:
                    raise ValueError(
                        f"Unit '{unit_type}' has conflicting move_after_shooting distances: "
                        f"{existing_distance} vs {scaled_distance}"
                    )
                unit_move_after_shooting_distance_by_type[unit_type] = scaled_distance
        unit_rules_by_type[unit_type] = expanded_rule_ids
        unit_choice_effect_to_source_rules[unit_type] = choice_effect_to_source_rules_for_unit

    rule_to_units: Dict[str, Set[str]] = {}
    for ut, rules in unit_rules_by_type.items():
        for rid in rules:
            rule_to_units.setdefault(rid, set()).add(ut)

    # Capacités de FACTION (08.04 : Waaagh!, Oath of Moment). Elles ne sont dans aucun
    # `UNIT_RULES` — c'est le mot-clé de faction qui les porte, exactement comme le moteur les
    # attribue (`unit_has_waaagh_ability`). Sans ce complément, `rule_to_units` ne les connaît
    # pas et §1.7 compte chaque usage relevé comme `invalid` : la ligne passe au rouge sur toute
    # partie orke où une escouade charge après avoir avancé — un coup légal.
    for _rule_id, _faction_keyword in FACTION_ABILITY_KEYWORD_BY_RULE_ID.items():
        _carriers = {
            ut for ut, kws in unit_faction_keywords_by_type.items() if _faction_keyword in kws
        }
        if _carriers:
            rule_to_units.setdefault(_rule_id, set()).update(_carriers)

    weapon_rule_to_weapons: Dict[str, Set[str]] = {}
    for unit_type, weapons_list in unit_weapons_cache.items():
        for winfo in weapons_list:
            wname = require_key(winfo, "name")
            rules_list = require_key(winfo, "rules")
            weapon_key = f"{wname} ({unit_type})"
            for r in rules_list:
                rule_base = str(r).split(":")[0] if ":" in str(r) else str(r)
                weapon_rule_to_weapons.setdefault(rule_base, set()).add(weapon_key)

    # Cartes globales arme→NB/portée/STR/ATK (agrégation MAX sur tous les model-types).
    rng_nb_by_weapon_global: Dict[str, int] = {}
    cc_nb_by_weapon_global: Dict[str, int] = {}
    rapid_fire_by_weapon_global: Dict[str, int] = {}
    blast_by_weapon_global: Dict[str, int] = {}
    cleave_by_weapon_global: Dict[str, int] = {}
    sustained_hits_by_weapon_global: Dict[str, int] = {}
    weapon_range_global: Dict[str, int] = {}
    weapon_is_close_quarters_global: Dict[str, bool] = {}
    rng_str_by_weapon_global: Dict[str, int] = {}
    cc_str_by_weapon_global: Dict[str, int] = {}
    cc_atk_by_weapon_global: Dict[str, int] = {}
    for _ut, _limits in unit_attack_limits.items():
        for _wname, _nb in _limits["rng_nb_by_weapon"].items():
            rng_nb_by_weapon_global[_wname] = max(rng_nb_by_weapon_global.get(_wname, 0), _nb)  # get allowed : max cumulatif, 0 = neutre
        for _wname, _rf in _limits["rapid_fire_by_weapon"].items():
            rapid_fire_by_weapon_global[_wname] = max(rapid_fire_by_weapon_global.get(_wname, 0), _rf)  # get allowed : max cumulatif, 0 = neutre
        for _wname, _bl in _limits["blast_by_weapon"].items():
            blast_by_weapon_global[_wname] = max(blast_by_weapon_global.get(_wname, 0), _bl)  # get allowed : max cumulatif, 0 = neutre
        for _wname, _cl in _limits["cleave_by_weapon"].items():
            cleave_by_weapon_global[_wname] = max(cleave_by_weapon_global.get(_wname, 0), _cl)  # get allowed : max cumulatif, 0 = neutre
        for _wname, _sh in _limits["sustained_hits_by_weapon"].items():
            sustained_hits_by_weapon_global[_wname] = max(sustained_hits_by_weapon_global.get(_wname, 0), _sh)  # get allowed : max cumulatif, 0 = neutre
        for _wname, _nb in _limits["cc_nb_by_weapon"].items():
            cc_nb_by_weapon_global[_wname] = max(cc_nb_by_weapon_global.get(_wname, 0), _nb)  # get allowed : max cumulatif, 0 = neutre
        for _wname, _s in _limits["rng_str_by_weapon"].items():
            rng_str_by_weapon_global[_wname] = max(rng_str_by_weapon_global.get(_wname, 0), _s)  # get allowed : max cumulatif, 0 = neutre
        for _wname, _s in _limits["cc_str_by_weapon"].items():
            cc_str_by_weapon_global[_wname] = max(cc_str_by_weapon_global.get(_wname, 0), _s)  # get allowed : max cumulatif, 0 = neutre
        for _wname, _a in _limits["cc_atk_by_weapon"].items():
            cc_atk_by_weapon_global[_wname] = max(cc_atk_by_weapon_global.get(_wname, 0), _a)  # get allowed : max cumulatif, 0 = neutre
    for _ut, _winfos in unit_weapons_cache.items():
        for _winfo in _winfos:
            # Cartes de TIR : les entrées de mêlée en sont exclues, et pas seulement parce que
            # leur portée vaut 0. Trois noms existent des deux côtés : y laisser entrer le profil
            # de mêlée ferait porter à ces armes un `is_close_quarters` qui n'est pas celui de
            # leur profil de tir — un `or` cumulatif ne se rattrape pas.
            if require_key(_winfo, "is_melee"):
                continue
            _wname = _winfo["name"]
            weapon_range_global[_wname] = max(weapon_range_global.get(_wname, 0), _winfo["range"])  # get allowed : max cumulatif, 0 = neutre
            weapon_is_close_quarters_global[_wname] = weapon_is_close_quarters_global.get(_wname, False) or _winfo["is_close_quarters"]

    return AnalyzerConfig(
        unit_registry=unit_registry,
        config_loader=config_loader,
        unit_weapons_cache=unit_weapons_cache,
        unit_attack_limits=unit_attack_limits,
        unit_combi_by_weapon=unit_combi_by_weapon,
        unit_rules_by_type=unit_rules_by_type,
        unit_move_after_shooting_distance_by_type=unit_move_after_shooting_distance_by_type,
        unit_is_fly_by_type=unit_is_fly_by_type,
        unit_is_monster_or_vehicle_by_type=unit_is_monster_or_vehicle_by_type,
        unit_socle_by_type=unit_socle_by_type,
        unit_choice_effect_to_source_rules=unit_choice_effect_to_source_rules,
        display_rule_name_to_ids=display_rule_name_to_ids,
        effect_display_tokens=effect_display_tokens,
        rule_to_units=rule_to_units,
        weapon_rule_to_weapons=weapon_rule_to_weapons,
        resolve_rule_id=resolve_effect_rule_id_to_technical,
        inches_to_subhex=inches_to_subhex,
        rng_nb_by_weapon_global=rng_nb_by_weapon_global,
        cc_nb_by_weapon_global=cc_nb_by_weapon_global,
        rapid_fire_by_weapon_global=rapid_fire_by_weapon_global,
        blast_by_weapon_global=blast_by_weapon_global,
        cleave_by_weapon_global=cleave_by_weapon_global,
        sustained_hits_by_weapon_global=sustained_hits_by_weapon_global,
        rng_str_by_weapon_global=rng_str_by_weapon_global,
        cc_str_by_weapon_global=cc_str_by_weapon_global,
        cc_atk_by_weapon_global=cc_atk_by_weapon_global,
        unit_toughness_by_type=unit_toughness_by_type,
        weapon_range_global=weapon_range_global,
        weapon_is_close_quarters_global=weapon_is_close_quarters_global,
        max_turns=config_loader.get_max_turns(),
        bonus_malus_cap=config_loader.get_bonus_malus_cap(),
    )
