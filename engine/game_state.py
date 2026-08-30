#!/usr/bin/env python3
"""
game_state.py - Game state initialization and management
"""

from typing import Dict, FrozenSet, Iterable, Iterator, List, Any, Optional, Tuple, Set
import copy
import json
import math
import os
from pathlib import Path
import re
from shared.data_validation import ConfigurationError, require_key
from engine.constants import DRAW_WINNER
from engine.episode_schedule import ramp_progress
from engine.combat_utils import normalize_coordinates, get_unit_coordinates, resolve_dice_value
from engine.phase_handlers.shared_utils import (
    is_unit_alive, _derive_model_role, compute_unit_rules_in_effect, strip_role_rules,
)
from engine.hex_utils import (
    expand_wall_group_to_hex_list, is_in_bounds, is_phantom_bottom_hex,
    polygon_to_hex_list, require_base_size,
)

# Plafond des réserves stratégiques (20.01) : « the combined points value of all of your
# strategic reserves units cannot exceed 50% of your points limit for your battle size ».
STRATEGIC_RESERVES_POINTS_RATIO = 0.5

# `scale` du scénario = taille de bataille en points ("500pts"). C'est la SEULE source du
# plafond 20.01 ; un format inconnu lève plutôt que de désactiver le contrôle en silence.
_BATTLE_SIZE_RE = re.compile(r"^(\d+)pts$")


def battle_points_limit(scale: Any, context: str) -> int:
    """Limite de points de la bataille (20.01) lue depuis le `scale` du scénario ("500pts" → 500)."""
    match = _BATTLE_SIZE_RE.match(str(scale).strip())
    if match is None:
        raise ValueError(
            f"{context}: 'scale' {scale!r} n'exprime pas une taille de bataille en points "
            f"(format attendu '<N>pts') — impossible de vérifier le plafond de réserves 20.01"
        )
    limit = int(match.group(1))
    if limit <= 0:
        raise ValueError(f"{context}: 'scale' {scale!r} donne une limite de points nulle ou négative")
    return limit


def _require_codex_detachment_when_astartes(
    army_faction_by_player: Any,
    uses_codex_detachment: Any,
    scenario_file: str,
    *,
    roster_sourced: bool,
) -> None:
    """AU CHARGEMENT : une armée ADEPTUS ASTARTES exige `uses_codex_detachment`.

    POURQUOI ICI, ET PAS AU SEUL POINT DE LECTURE. Les deux données n'ont pas la même source :
    `army_faction` vient du ROSTER quand le scénario en tire un (`training_random` en change à
    chaque épisode), tandis qu'`uses_codex_detachment` ne vient QUE du scénario. Les 16 fichiers
    de roster de `config/agents/**` déclarent leur `army_faction` sans porter la clause — un
    scénario à rosters qui l'oublierait ne serait donc trahi qu'au premier appel, et depuis le
    2026-08-06 ce premier appel est la construction de l'OBSERVATION (bits
    `*_oath_wound_bonus_active`) : le run entier partirait avant de casser.

    Ce n'est pas un doublon du `require_key` d'`uses_codex_detachment` : celui-là protège le
    POINT DE LECTURE (fixtures et états construits en mémoire compris), celui-ci protège le
    CHARGEMENT, avec le nom du fichier fautif — la seule information qui permette de corriger.
    Aucune valeur par défaut n'est posée ni ici ni là : elle changerait les jets.
    """
    if not isinstance(army_faction_by_player, dict):
        return
    if not any(
        _normalize_keyword(faction) == OATH_FACTION_KEYWORD
        for faction in army_faction_by_player.values()
    ):
        return
    if uses_codex_detachment is not None:
        return
    origine = "le roster tiré par ce scénario" if roster_sourced else "ce scénario"
    raise KeyError(
        f"{scenario_file}: {origine} déclare une armée ADEPTUS ASTARTES "
        f"({army_faction_by_player!r}) mais 'uses_codex_detachment' est absent du SCÉNARIO. "
        f"Le +1 au jet de blessure d'Oath of Moment en dépend (« If you are using a Codex: "
        f"Space Marines Detachment »), et l'observation le lit à chaque construction. Déclarer "
        f"le champ dans le scénario, par joueur — aucune valeur par défaut n'est admise, elle "
        f"changerait les jets."
    )


def _default_reserves_parameters() -> Dict[str, Any]:
    """Les trois paramètres de 20.03/20.04, à leur valeur GÉNÉRIQUE, posés sur chaque unité.

    Les trois clauses concernées sont explicitement surchargeables par des capacités (« unless
    otherwise stated » pour le round d'arrivée, « anywhere on the battlefield » pour la bande de
    bord, « more than 9\" away » pour la distance aux ennemis). Les porter sur l'unité est ce qui
    permet à une règle — y compris une règle d'une AUTRE unité, comme Logan Grimnar qui fait
    arriver une unité au 1er round — de les modifier sans toucher au moteur.

    Importés depuis `movement_handlers`, propriétaire des règles 20.03/20.04 : les défauts n'ont
    ainsi qu'une seule définition.
    """
    from engine.phase_handlers.movement_handlers import (
        INGRESS_ENEMY_CLEARANCE_INCHES,
        INGRESS_FIRST_BATTLE_ROUND,
        INGRESS_SETUP_DISTANCE_INCHES,
        RESERVES_ARRIVAL_ROUND_FIELD,
        RESERVES_EDGE_DISTANCE_FIELD,
        RESERVES_ENEMY_CLEARANCE_FIELD,
    )

    return {
        RESERVES_ARRIVAL_ROUND_FIELD: INGRESS_FIRST_BATTLE_ROUND,
        RESERVES_EDGE_DISTANCE_FIELD: INGRESS_SETUP_DISTANCE_INCHES,
        RESERVES_ENEMY_CLEARANCE_FIELD: INGRESS_ENEMY_CLEARANCE_INCHES,
    }


def validate_strategic_reserves_cap(
    units: List[Dict[str, Any]], points_limit: int, context: str
) -> None:
    """Plafond 20.01 : ≤ 50 % de la limite de points par joueur, en RÉSERVES.

    Contrôle DUR au chargement : dépassement -> erreur nommant les unités et le total. Tronquer
    la liste (retirer des unités des réserves jusqu'à repasser sous le plafond) déciderait à la
    place du joueur et masquerait une liste illégale.
    """
    cap = int(points_limit * STRATEGIC_RESERVES_POINTS_RATIO)
    by_player: Dict[int, List[Dict[str, Any]]] = {}
    for unit in units:
        if not unit.get("in_strategic_reserves"):  # get allowed (champ optionnel = pas en réserve)
            continue
        by_player.setdefault(int(require_key(unit, "player")), []).append(unit)
    for player, reserve_units in sorted(by_player.items()):
        total = sum(int(require_key(u, "VALUE")) for u in reserve_units)
        if total > cap:
            detail = ", ".join(
                f"{u.get('unitType', u.get('unit_type'))}(id={u.get('id')}, {require_key(u, 'VALUE')}pts)"
                for u in reserve_units
            )
            raise ValueError(
                f"{context}: joueur {player} place {total} points en réserves stratégiques pour un "
                f"plafond de {cap} points (50 % de {points_limit}, règle 20.01). Unités en "
                f"réserves : {detail}"
            )


# PERF: In-memory caches to avoid repeated disk I/O during scenario rotation.
_scenario_json_cache: Dict[str, Any] = {}
_roster_json_cache: Dict[str, Any] = {}  # item 1.9 — clé = chemin absolu du roster
_walls_json_cache: Dict[str, List[List[int]]] = {}
_walls_json_mtime_ns: Dict[str, int] = {}
# board_config.json des plateaux SOURCE (résolution native déclarée par board_ref), lus à
# chaque chargement de terrain. Clé (chemin, mtime_ns) : édition à chaud prise en compte.
_board_config_cache: Dict[Tuple[str, int], Dict[str, Any]] = {}

def _scale_socle(
    base_shape: Any, base_size: Any, inches_to_subhex: int, context: str
) -> Tuple[Any, Any]:
    """Convertit le socle d'une datasheet (`BASE_SHAPE`, `BASE_SIZE` en unités ×10) vers le board.

    FRONTIÈRE DE VALIDATION de l'invariant du socle : `BASE_SHAPE` est l'étiquette qui
    DÉTERMINE le type de `BASE_SIZE` (`round`/`square` → scalaire, `oval` → paire). C'est ici
    que la datasheet entre dans le moteur, donc ici que le couple est vérifié — une fois —
    par `hex_utils.require_base_size`, qui nomme l'unité (`context`) et les deux valeurs
    incohérentes. Tout le reste du moteur (Socle, empreintes, masques) consomme la donnée
    déjà validée : il n'y a pas à re-garder chaque site géométrique.

    Au-dessus de `inches_to_subhex == 1`, seule la taille change et son TYPE est porteur de
    sens : un socle `oval` porte une PAIRE `[a, b]` que `hex_utils._socle_edge_primitives`
    indexe et que `precompute_footprint_offsets` développe en empreinte ; `round` et `square`
    portent un scalaire.

    À `inches_to_subhex == 1`, une figurine tient dans UNE case — c'est la définition même de
    cette résolution (`_compute_deploy_footprint` ne rend qu'un hex, `is_micro_board` est faux).
    La forme du socle n'a alors plus de sens géométrique : le socle est **normalisé en `round`
    de taille 1**.

    Ne PAS normaliser la forme casse le moteur de deux façons opposées, l'une ou l'autre selon
    le type laissé :
      - taille scalaire `1` avec `BASE_SHAPE = "oval"` → `_socle_edge_primitives` indexe
        `size[0]` sur un int : `TypeError` dès qu'une distance bord-à-bord est calculée ;
      - taille `[1, 1]` avec `BASE_SHAPE = "oval"` → l'unité bascule sur le chemin MULTI-HEX du
        pool de mouvement (`is_single_hex = base_size == 1` est faux), lequel évalue l'engagement
        ennemi depuis les socles alors que `validate_move_plan` le lit dans le set dilaté
        `enemy_adjacent_hexes_player_N`. Les deux définitions ne coïncident pas et le masque
        propose des destinations que l'exécution refuse (« incohérence masque/exécution »).
    """
    validated = require_base_size(base_shape, base_size, context)
    if int(inches_to_subhex) <= 1:
        return "round", 1
    if isinstance(validated, list):
        return base_shape, [max(1, round(s * inches_to_subhex / 10)) for s in validated]
    return base_shape, max(1, round(validated * inches_to_subhex / 10))


# Keywords granting the "hideable" property (Benefit of Cover / Hidden rules 13.08-13.09).
_HIDEABLE_KEYWORDS = ("infantry", "beast", "swarm")


# Mots-clés autorisant une figurine à finir un move sur une surface hors rez-de-chaussée
# (règle 13.06). Étend _HIDEABLE_KEYWORDS (infantry/beast/swarm) avec fly/monster : même
# convention de lecture (keywordId, lower/strip) que compute_hideable, donc aligné sur la donnée.
_FLOOR_CAPABLE_KEYWORDS = _HIDEABLE_KEYWORDS + ("fly", "monster")


def unit_can_occupy_upper_floor(unit_keywords: Any) -> bool:
    """True si l'unité peut être posée/finir un move sur un étage (niveau >= 1), règle 13.06.

    Condition mot-clé : INFANTRY / BEASTS / SWARM / FLY / MONSTER. Les autres unités ne
    peuvent PAS finir en hauteur (elles restent au rez-de-chaussée). Le rez-de-chaussée
    (niveau 0) est autorisé pour toute unité : ne pas appeler ce gate pour le niveau 0.
    """
    if not isinstance(unit_keywords, list):
        raise TypeError(f"UNIT_KEYWORDS must be a list, got {type(unit_keywords).__name__}")
    for kw in unit_keywords:
        if not isinstance(kw, dict):
            raise TypeError(f"UNIT_KEYWORDS entries must be dicts, got {kw!r}")
        if str(require_key(kw, "keywordId")).strip().lower() in _FLOOR_CAPABLE_KEYWORDS:
            return True
    return False


def _validate_level(level: Any, unit_id: Any) -> int:
    """Validate a vertical level (étages). 0 = ground (default business case), >= 0 int.

    No silent coercion: a non-int or negative level is an explicit config error.
    """
    if isinstance(level, bool) or not isinstance(level, int) or level < 0:
        raise ValueError(f"Unit {unit_id!r}: 'level' must be an int >= 0 (0 = ground), got {level!r}")
    return level


def compute_hideable(unit_keywords: Any) -> bool:
    """True if the unit has an INFANTRY/BEASTS/SWARM keyword (eligible for cover/hidden)."""
    if not isinstance(unit_keywords, list):
        raise TypeError(f"UNIT_KEYWORDS must be a list, got {type(unit_keywords).__name__}")
    for kw in unit_keywords:
        if not isinstance(kw, dict):
            raise TypeError(f"UNIT_KEYWORDS entries must be dicts, got {kw!r}")
        if str(require_key(kw, "keywordId")).strip().lower() in _HIDEABLE_KEYWORDS:
            return True
    return False


class GameStateManager:
    """Manages game state."""
    
    def __init__(self, config: Dict[str, Any], unit_registry=None):
        self.config = config
        self.unit_registry = unit_registry
        self.training_config: Optional[Dict[str, Any]] = None
    
    # ============================================================================
    # UNIT MANAGEMENT
    # ============================================================================
    
    def initialize_units(self, game_state: Dict[str, Any]):
        """Initialize units with UPPERCASE field validation."""
        # tour_de_jeu.md COMPLIANCE: Direct access - units must be provided
        if "units" not in self.config:
            raise KeyError("Config missing required 'units' field")
        unit_configs = self.config["units"]
        
        for unit_config in unit_configs:
            unit = self.create_unit(unit_config)
            self.validate_uppercase_fields(unit)
            game_state["units"].append(unit)
    
    def _get_inches_to_subhex(self) -> int:
        """Get the board scale factor (inches to sub-hex conversion).

        Returns 1 for legacy boards (1 hex = 1 inch),
        or the configured value (e.g. 10) for ×10 micro-grids.
        """
        board = require_key(self.config, "board")
        if "default" in board:
            default = require_key(board, "default")
        else:
            default = board
        return int(require_key(default, "inches_to_subhex"))

    def create_unit(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Create unit with tour_de_jeu.md compliant fields."""
        rng_weapons = copy.deepcopy(require_key(config, "RNG_WEAPONS"))
        cc_weapons = copy.deepcopy(require_key(config, "CC_WEAPONS"))

        # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Initialize selected weapon indices
        selected_rng_weapon_index = 0 if rng_weapons else None
        selected_cc_weapon_index = 0 if cc_weapons else None
        
        # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Extract SHOOT_LEFT and ATTACK_LEFT from selected weapons
        shoot_left = 0
        if rng_weapons and selected_rng_weapon_index is not None:
            selected_weapon = rng_weapons[selected_rng_weapon_index]
            shoot_left = resolve_dice_value(
                require_key(selected_weapon, "NB"),
                "game_state_init_shoot_left",
            )
        
        attack_left = 0
        if cc_weapons and selected_cc_weapon_index is not None:
            selected_weapon = cc_weapons[selected_cc_weapon_index]
            attack_left = resolve_dice_value(
                require_key(selected_weapon, "NB"),
                "game_state_init_attack_left",
            )
        
        unit_rules = copy.deepcopy(config["UNIT_RULES"]) if "UNIT_RULES" in config else []
        unit_keywords = copy.deepcopy(require_key(config, "UNIT_KEYWORDS"))
        # Mots-clés de FACTION (chantier 03) : « If your Army Faction is ORKS / ADEPTUS
        # ASTARTES ». MÊME traitement que `_UNIT_RULES_OWN` ci-dessous, et pour la même raison :
        # l'autorité est `_build_enhanced_unit`, qui les EXIGE de la datasheet (`require_key`) —
        # une unité de roster ne peut donc pas perdre sa faction en silence. Ici, une unité
        # construite par un autre chemin (API build army, fixture) et qui n'en déclare aucune
        # n'appartient à aucune faction connue : c'est l'identité du cas simple, pas un repli
        # anti-erreur, et c'est déjà la convention de `attack_sequence.unit_keywords_upper`.
        faction_keywords = (
            copy.deepcopy(config["FACTION_KEYWORDS"]) if "FACTION_KEYWORDS" in config else []
        )
        # Provenance 19.04 : `_build_enhanced_unit` (autorité) l'a déjà calculée — on la
        # transporte telle quelle. Une unité construite par un autre chemin (API build army,
        # fixture) n'a par construction aucun character replié : ses règles en vigueur SONT
        # ses règles propres. Ce n'est pas un repli anti-erreur mais l'identité du cas simple.
        unit_rules_own = (
            copy.deepcopy(config["_UNIT_RULES_OWN"]) if "_UNIT_RULES_OWN" in config
            else copy.deepcopy(unit_rules)
        )
        attached_rule_groups = (
            copy.deepcopy(config["_ATTACHED_RULE_GROUPS"]) if "_ATTACHED_RULE_GROUPS" in config
            else {}
        )

        # Scaling (MOVE, RNG, BASE_SIZE) : autorité unique = _build_enhanced_unit, qui produit
        # TOUTES les units (loader + change_roster + reload). create_unit ne voit que du déjà-scalé.

        if "orientation" in config:
            orientation_init = int(require_key(config, "orientation"))
        else:
            orientation_init = 0

        # PR4 4c: pass-through "models" field (multi-fig squad declaration).
        # Already validated/normalized upstream by load_units_from_scenario.
        models_passthrough = config.get("models")
        _add_col, _add_row = normalize_coordinates(config["col"], config["row"])

        result = {
            # Identity
            "id": config["id"],
            "player": config["player"],
            "unitType": config["unitType"],  # NO DEFAULTS - must be provided
            "DISPLAY_NAME": config["DISPLAY_NAME"],

            # Position
            "col": _add_col,
            "row": _add_row,
            # Niveau vertical (étages, format B). 0 = rez-de-chaussée (cas métier par défaut :
            # unité au sol), >=1 = étage d'une ruine. Ancre unité = niveau de models[0].
            "level": _validate_level(config.get("level", 0), config["id"]),  # get allowed (champ optionnel : scénarios sans étages)
            
            # UPPERCASE STATS (tour_de_jeu.md requirement) - NO DEFAULTS
            "HP_CUR": config["HP_CUR"],
            "HP_MAX": config["HP_MAX"],
            "MOVE": config["MOVE"],
            "T": config["T"],
            "ARMOR_SAVE": config["ARMOR_SAVE"],
            "INVUL_SAVE": config["INVUL_SAVE"],
            
            # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Multiple weapons system
            "RNG_WEAPONS": rng_weapons,
            "CC_WEAPONS": cc_weapons,
            "selectedRngWeaponIndex": selected_rng_weapon_index,
            "selectedCcWeaponIndex": selected_cc_weapon_index,
            
            # Required stats - NO DEFAULTS
            "LD": config["LD"],
            "OC": config["OC"],
            "VALUE": config["VALUE"],
            "ICON": config["ICON"],
            "ICON_SCALE": config["ICON_SCALE"],
            "ILLUSTRATION_RATIO": require_key(config, "ILLUSTRATION_RATIO"),
            # Second (et dernier) point d'entrée d'un socle dans le moteur : `create_unit`
            # reçoit du DÉJÀ-SCALÉ (cf. commentaire ci-dessus), donc pas de `_scale_socle`
            # ici — mais l'invariant (BASE_SHAPE ↔ type de BASE_SIZE) est verifié comme à
            # l'autre frontière, sinon une unité construite par l'API ou une fixture
            # entrerait sans garde.
            "BASE_SHAPE": require_key(config, "BASE_SHAPE"),
            "BASE_SIZE": require_base_size(
                require_key(config, "BASE_SHAPE"),
                require_key(config, "BASE_SIZE"),
                f"create_unit {config['unitType']} (id {config['id']})",
            ),
            # Hauteur modèle (pouces) : clairance sous les étages (§13.06 maison). Fournie par
            # _build_enhanced_unit (autorité) / build army API → recopiée ici (builder central).
            "MODEL_HEIGHT": float(require_key(config, "MODEL_HEIGHT")),
            "orientation": orientation_init,
            "UNIT_RULES": unit_rules,
            # Sources immuables dont UNIT_RULES est l'union en vigueur (19.04).
            "_UNIT_RULES_OWN": unit_rules_own,
            "_ATTACHED_RULE_GROUPS": attached_rule_groups,
            "UNIT_KEYWORDS": unit_keywords,
            "FACTION_KEYWORDS": faction_keywords,
            # Tour de mise en place (règle 24.16 « not set up this turn » + feature
            # d'observation déploiement/réserve). 0 = posée avant la bataille (positions du
            # scénario / mode fixed) ; None = pas encore sur le board (déploiement actif, la
            # valeur est écrite au commit) ; N > 0 = arrivée de réserve au tour N.
            "deployed_on_turn": None if int(config["col"]) < 0 else 0,
            # Réserves stratégiques (20.01/20.02) — cf. `_build_enhanced_unit` pour la
            # sémantique. DEUX sources, dans cet ordre :
            #   - `in_strategic_reserves` : l'unité vient de `_build_enhanced_unit`, qui a déjà
            #     résolu la déclaration de roster. C'est le cas de TOUTES les unités du moteur,
            #     `initialize_units` reconstruisant chaque unité enrichie par ce constructeur.
            #     L'omettre annulait purement et simplement toute réserve déclarée par un roster :
            #     l'unité repassait à False et se retrouvait soit redéployée normalement, soit
            #     bloquée hors table sans arrivée possible ni destruction de fin de 3e round.
            #   - `strategic_reserves` : déclaration BRUTE (roster/scénario), pour une unité
            #     construite sans passer par l'enrichissement (API build army, fixture).
            "in_strategic_reserves": bool(
                config.get(  # get allowed (2 sources, cf. ci-dessus)
                    "in_strategic_reserves", config.get("strategic_reserves", False)
                )
            ),
            "reserves_repositioned": bool(config.get("reserves_repositioned", False)),  # get allowed
            **{
                # Paramètres 20.03/20.04 : ceux de l'unité enrichie si elle en porte (une
                # capacité a pu les modifier avant un rechargement), sinon la règle générique.
                _k: config.get(_k, _v)  # get allowed (idem)
                for _k, _v in _default_reserves_parameters().items()
            },
            # Attached units (rule 19.01): bodyguard unit-name keywords this leader/support may attach to.
            # Empty list for non-leader units (valid business case: the LEADER rule is absent from their config).
            "CAN_LEAD": copy.deepcopy(config["CAN_LEAD"] if "CAN_LEAD" in config else []),

            # tour_de_jeu.md action tracking fields
            "SHOOT_LEFT": shoot_left,
            "ATTACK_LEFT": attack_left,

            # Terrain visibility (rules 13.08-13.09): hideable derived from keywords, hidden is runtime state
            "hideable": compute_hideable(unit_keywords),
            "hidden": False,
            "hidden_models": [],

            # Battle-shock state (règle 01.07) — reset au début de la command phase du joueur
            "battle_shocked": False,
        }
        if models_passthrough is not None:
            result["models"] = copy.deepcopy(models_passthrough)
        return result

    def validate_uppercase_fields(self, unit: Dict[str, Any]):
        """Validate unit uses UPPERCASE field naming convention."""
        # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Validate weapons instead of individual weapon fields
        required_uppercase = {
            "HP_CUR", "HP_MAX", "MOVE", "T", "ARMOR_SAVE", "INVUL_SAVE",
            "RNG_WEAPONS", "CC_WEAPONS",
            "LD", "OC", "VALUE", "ICON", "ICON_SCALE", "ILLUSTRATION_RATIO", "UNIT_RULES", "UNIT_KEYWORDS",
            "FACTION_KEYWORDS",
            "SHOOT_LEFT", "ATTACK_LEFT"
        }
        
        for field in required_uppercase:
            if field not in unit:
                raise ValueError(f"Unit {unit['id']} missing required UPPERCASE field: {field}")

    def load_units_from_scenario(self, scenario_file, unit_registry, deployment_type_override=None):
            """Load units from scenario file - NO FALLBACKS ALLOWED.

            ``deployment_type_override`` (optionnel) : force le mode de déploiement de CE chargement,
            en remplaçant le ``deployment_type`` du JSON (et en neutralisant les surcharges par joueur
            ``deployment_type_P1``/``deployment_type_P2``). Sert au scheduler par-épisode fixed↔active
            (`w40k_core._configure_deployment_mode_for_episode`) : le MÊME fichier est rechargé tantôt
            "fixed" (positions du JSON), tantôt "active" (déploiement, positions ignorées). Exige un
            scénario objet (dict) fournissant des zones de déploiement pour le mode "active".
            """
            if not scenario_file:
                raise ValueError("scenario_file is required - no fallbacks allowed")
            if not unit_registry:
                raise ValueError("unit_registry is required - no fallbacks allowed")
            
            import random
            
            if not os.path.exists(scenario_file):
                raise FileNotFoundError(f"Scenario file not found: {scenario_file}")
            
            abs_path = os.path.abspath(scenario_file)
            if abs_path in _scenario_json_cache:
                scenario_data = copy.deepcopy(_scenario_json_cache[abs_path])
            else:
                try:
                    with open(scenario_file, 'r') as f:
                        scenario_data = json.load(f)
                except Exception as e:
                    raise ValueError(f"Failed to parse scenario file {scenario_file}: {e}")
                _scenario_json_cache[abs_path] = copy.deepcopy(scenario_data)

            # Override par-épisode du mode de déploiement (scheduler fixed↔active). Appliqué sur la
            # copie locale (jamais sur le cache) AVANT toute résolution de deployment_type.
            if deployment_type_override is not None:
                valid_override = ("fixed", "active", "random")
                if deployment_type_override not in valid_override:
                    raise ValueError(
                        f"deployment_type_override invalide: {deployment_type_override!r} "
                        f"(attendu {valid_override})"
                    )
                if not isinstance(scenario_data, dict):
                    raise ValueError(
                        f"deployment_type_override requiert un scénario objet (dict) avec zones de "
                        f"déploiement, pas une simple liste d'unités: {scenario_file}"
                    )
                scenario_data["deployment_type"] = deployment_type_override
                scenario_data.pop("deployment_type_P1", None)
                scenario_data.pop("deployment_type_P2", None)

            scenario_roster_info: Optional[Dict[str, Any]] = None
            if isinstance(scenario_data, list):
                basic_units = scenario_data
            elif isinstance(scenario_data, dict) and "units" in scenario_data:
                basic_units = scenario_data["units"]
            elif (
                isinstance(scenario_data, dict)
                and "agent_roster_ref" in scenario_data
                and "opponent_roster_ref" in scenario_data
            ):
                basic_units, scenario_roster_info = self._load_units_from_roster_refs(
                    scenario_data=scenario_data,
                    scenario_file=scenario_file
                )
            else:
                raise ValueError(
                    f"Invalid scenario format in {scenario_file}: must have 'units' array or "
                    f"'agent_roster_ref'+'opponent_roster_ref'"
                )
            
            if not basic_units:
                raise ValueError(f"Scenario file {scenario_file} contains no units")

            deployment_zone = None
            deployment_type = "fixed"
            deployment_type_by_player: Dict[int, str] = {1: "fixed", 2: "fixed"}
            resolved_scenario_walls = None
            resolved_scenario_dense_walls = None
            resolved_scenario_objectives = None
            resolved_terrain_areas = None
            resolved_deployment_zones = None
            if isinstance(scenario_data, dict):
                # board_ref (V11 T4) : autorise la résolution walls/terrain hors dossier 'scenario/'
                # (banque par-agent). None = comportement PvP legacy (parent 'scenario/' requis).
                board_ref = scenario_data.get("board_ref")
                has_wall_hexes = "wall_hexes" in scenario_data
                has_wall_ref = "wall_ref" in scenario_data
                if has_wall_hexes and has_wall_ref:
                    raise ValueError(
                        f"Scenario file {scenario_file} cannot define both 'wall_hexes' and 'wall_ref'"
                    )
                if has_wall_hexes:
                    resolved_scenario_walls = require_key(scenario_data, "wall_hexes")
                    # Murs écrits DANS le scénario : même conversion que les murs partagés, sinon
                    # ils resteraient les seuls en coordonnées natives sur un plateau réduit.
                    # Conditionné à une résolution d'origine DÉCLARÉE (`board_ref` ou dossier
                    # `config/board/<board>/scenario/`) : sans elle, aucune échelle source.
                    if self._has_declared_source_board(scenario_file, board_ref):
                        inline_ratio = self._board_ref_downscale_ratio(scenario_file, board_ref)
                        if inline_ratio != 1:
                            resolved_scenario_walls = self._downscale_terrain_data(
                                {"walls": [{"hexes": resolved_scenario_walls}]}, inline_ratio
                            )["walls"][0]["hexes"]
                elif has_wall_ref:
                    resolved_scenario_walls = self._load_shared_walls_from_ref(
                        require_key(scenario_data, "wall_ref"),
                        scenario_file,
                        board_ref=board_ref,
                    )
                    resolved_scenario_dense_walls = self._load_shared_walls_from_ref(
                        require_key(scenario_data, "wall_ref"),
                        scenario_file,
                        only_type="dense",
                        board_ref=board_ref,
                    )
                if "terrain_ref" in scenario_data:
                    terrain_walls = self._load_terrain_walls_from_ref(
                        scenario_data["terrain_ref"], scenario_file, board_ref=board_ref
                    )
                    terrain_dense_walls = self._load_terrain_walls_from_ref(
                        scenario_data["terrain_ref"], scenario_file, only_type="dense",
                        board_ref=board_ref,
                    )
                    if terrain_walls:
                        resolved_scenario_walls = list(resolved_scenario_walls or []) + terrain_walls
                    if terrain_dense_walls:
                        resolved_scenario_dense_walls = (
                            list(resolved_scenario_dense_walls or []) + terrain_dense_walls
                        )
                    resolved_terrain_areas = self._load_terrain_areas_from_ref(
                        scenario_data["terrain_ref"], scenario_file, board_ref=board_ref
                    )
                    resolved_deployment_zones = self._load_deployment_zones_from_ref(
                        scenario_data["terrain_ref"], scenario_file, board_ref=board_ref
                    )

                # Objectifs : source UNIQUE = terrains "objective": true (14.01/14.02).
                # L'ancien système (objectives_ref / objectives inline / objective_hexes)
                # est supprimé — toute clé legacy est une erreur explicite, pas un fallback.
                for legacy_key in ("objectives", "objectives_ref", "objective_hexes"):
                    if legacy_key in scenario_data:
                        raise ValueError(
                            f"Scenario file {scenario_file} uses removed objective key "
                            f"'{legacy_key}'. Objectives are now sourced exclusively from terrain "
                            f"areas flagged \"objective\": true (see terrain_ref)."
                        )

                has_deployment_zone = "deployment_zone" in scenario_data
                has_deployment_type = "deployment_type" in scenario_data
                has_deployment_type_p1 = "deployment_type_P1" in scenario_data
                has_deployment_type_p2 = "deployment_type_P2" in scenario_data
                has_any_deployment_type = (
                    has_deployment_type
                    or has_deployment_type_p1
                    or has_deployment_type_p2
                )
                if has_deployment_zone or has_any_deployment_type:
                    if not has_deployment_zone and resolved_deployment_zones is None:
                        raise KeyError(
                            f"Scenario file {scenario_file} requires 'deployment_zone' (or a 'deployment_zones' "
                            f"section in its terrain_ref) when deployment type is configured"
                        )
                    if has_deployment_zone:
                        deployment_zone = require_key(scenario_data, "deployment_zone")
                    if has_deployment_type:
                        deployment_type = require_key(scenario_data, "deployment_type")
                    else:
                        deployment_type = "fixed"
                    deployment_type_by_player = self._resolve_deployment_type_by_player(scenario_data)
                valid_deployment_types = ("random", "fixed", "active")
                for player_id, player_deployment_type in deployment_type_by_player.items():
                    if player_deployment_type not in valid_deployment_types:
                        raise ValueError(
                            f"Invalid deployment type for player {player_id}: '{player_deployment_type}' "
                            f"in {scenario_file} (expected one of {valid_deployment_types})"
                        )
            
            # Objectifs runtime {id, hexes} dérivés des terrains "objective": true.
            # Aucun terrain objectif → liste vide (zéro objectif), pas de fallback.
            resolved_scenario_objectives = [
                {"id": area["id"], "name": area.get("name", area["id"]), "hexes": area["hexes"]}
                for area in (resolved_terrain_areas or [])
                if area.get("objective")
            ]

            wall_hex_set = set()
            if resolved_scenario_walls is not None:
                wall_hex_set = {(int(col), int(row)) for col, row in resolved_scenario_walls}
            
            board_config = require_key(self.config, "board")
            board_spec = board_config["default"] if "default" in board_config else board_config
            board_cols = require_key(board_spec, "cols")
            board_rows = require_key(board_spec, "rows")
            if board_cols <= 0 or board_rows <= 0:
                raise ValueError(f"Invalid board dimensions: cols={board_cols}, rows={board_rows}")

            def _is_valid_deploy_hex(col: int, row: int) -> bool:
                return is_in_bounds(col, row, board_cols, board_rows) and not is_phantom_bottom_hex(
                    col, row, board_rows
                )

            deploy_pools = {}
            if resolved_deployment_zones is not None:
                # Source unique : section 'deployment_zones' du terrain (polygones par joueur).
                # id "1" → joueur 1, id "2" → joueur 2.
                zones_by_player: Dict[int, set] = {}
                for zi, zone in enumerate(resolved_deployment_zones):
                    hint = f"terrain deployment_zones[{zi}]"
                    zid = require_key(zone, "id")
                    try:
                        player_id = int(zid)
                    except (TypeError, ValueError):
                        raise ValueError(f"{hint}: 'id' must be a player number (1 or 2), got {zid!r}")
                    if player_id not in (1, 2):
                        raise ValueError(f"{hint}: 'id' must be 1 or 2, got {player_id}")
                    if player_id in zones_by_player:
                        raise ValueError(f"{hint}: duplicate deployment zone for player {player_id}")
                    if zone.get("shape") != "polygon":
                        raise ValueError(f"{hint}: deployment zone must have shape 'polygon'")
                    vertices = require_key(zone, "vertices")
                    if not isinstance(vertices, list) or len(vertices) < 3:
                        raise ValueError(f"{hint}: 'vertices' must be a list of >= 3 [col,row] points")
                    poly = [[int(v[0]), int(v[1])] for v in vertices]
                    zones_by_player[player_id] = {
                        (int(c), int(r))
                        for c, r in polygon_to_hex_list(poly, board_cols, board_rows)
                        if _is_valid_deploy_hex(c, r)
                    }
                if set(zones_by_player.keys()) != {1, 2}:
                    raise KeyError(
                        f"Terrain deployment_zones must define exactly players 1 and 2, "
                        f"got {sorted(zones_by_player.keys())}"
                    )
                deploy_pools = {1: zones_by_player[1], 2: zones_by_player[2]}
            elif deployment_zone:
                # Voie legacy : nom de zone validé par l'existence du fichier ci-dessous
                # (config/deployment/<board>/<zone>.json) — pas de whitelist figée.
                project_root = os.path.dirname(os.path.dirname(__file__))
                board_size_dir = f"{board_cols}x{board_rows}"
                deployment_path = os.path.join(
                    project_root, "config", "deployment", board_size_dir, f"{deployment_zone}.json"
                )
                if not os.path.exists(deployment_path):
                    raise FileNotFoundError(f"Deployment file not found: {deployment_path}")
                try:
                    with open(deployment_path, "r") as f:
                        deployment_data = json.load(f)
                except Exception as e:
                    raise ValueError(f"Failed to parse deployment file {deployment_path}: {e}")
                if "p1" not in deployment_data or "p2" not in deployment_data:
                    raise KeyError(f"Deployment file {deployment_path} missing required p1/p2 zones")
                
                def _build_deploy_pool(zone: Dict[str, Any]) -> set[tuple[int, int]]:
                    # Format géométrique : liste de shapes rect/triangle (zones diagonales).
                    if "shapes" in zone:
                        from engine.hex_utils import (
                            _objective_rect_hexes,
                            _objective_triangle_hexes,
                        )
                        shapes = zone["shapes"]
                        if not isinstance(shapes, list) or not shapes:
                            raise ValueError("deploy zone 'shapes' must be a non-empty list")
                        pool: set[tuple[int, int]] = set()
                        for si, shp in enumerate(shapes):
                            kind = require_key(shp, "shape")
                            if kind == "rect":
                                hexes = _objective_rect_hexes(
                                    top_left=require_key(shp, "top_left"),
                                    bottom_right=require_key(shp, "bottom_right"),
                                    cols=board_cols,
                                    rows=board_rows,
                                )
                            elif kind == "triangle":
                                hexes = _objective_triangle_hexes(
                                    vertices=require_key(shp, "vertices"),
                                    cols=board_cols,
                                    rows=board_rows,
                                )
                            else:
                                raise ValueError(
                                    f"deploy zone shape[{si}] unsupported '{kind}' (rect or triangle)"
                                )
                            for c, r in hexes:
                                if _is_valid_deploy_hex(c, r):
                                    pool.add((int(c), int(r)))
                        return pool
                    # Format historique : bbox rectangulaire.
                    col_min = require_key(zone, "col_min")
                    col_max = require_key(zone, "col_max")
                    row_min = require_key(zone, "row_min")
                    row_max = require_key(zone, "row_max")
                    if col_min > col_max or row_min > row_max:
                        raise ValueError(
                            f"Invalid deploy bounds: col=({col_min},{col_max}) row=({row_min},{row_max})"
                        )
                    pool = {
                        (col, row)
                        for col in range(col_min, col_max + 1)
                        for row in range(row_min, row_max + 1)
                        if _is_valid_deploy_hex(col, row)
                    }
                    return pool
                
                deploy_pools = {
                    1: _build_deploy_pool(deployment_data["p1"]),
                    2: _build_deploy_pool(deployment_data["p2"]),
                }
            if deploy_pools and any(
                deployment_type_by_player[player_id] in ("random", "active")
                for player_id in (1, 2)
            ):
                # `wall_hexes` EXIGÉ quand un joueur pose réellement des figurines depuis la zone :
                # sans murs déclarés, le tirage random/actif poserait dans le décor.
                if not wall_hex_set:
                    raise KeyError(
                        f"Scenario file {scenario_file} missing required 'wall_hexes' for random/active deployment"
                    )
            # Soustraction INCONDITIONNELLE : un hex de mur n'est une case de déploiement légale
            # dans AUCUN mode. Elle était réservée à random/active tant que les zones ne servaient
            # qu'à la phase de déploiement. Depuis que le reset les publie hors phase
            # (`game_state["deployment_pools"]`), deux lecteurs les consomment en mode `fixed` :
            # `squad_grid_anchor`, dont l'ancre est le BARYCENTRE du pool, et la clause 20.04 sur
            # la zone adverse. Mesuré sur le scénario d'entraînement avant ce correctif : 0 mur
            # dans les zones en `active`, 149 et 151 en `fixed` — la même unité sur le même
            # plateau recevait donc un centrage de grille différent selon le tirage fixed↔active.
            # `wall_hex_set` vide (scénario sans décor) → soustraction neutre, pas de repli masqué.
            if deploy_pools:
                deploy_pools = {
                    1: deploy_pools[1] - wall_hex_set,
                    2: deploy_pools[2] - wall_hex_set,
                }
            used_hexes = set()
            _ish = int(require_key(board_spec, "inches_to_subhex"))
            is_micro_board = _ish > 1

            def _compute_deploy_footprint(
                col: int, row: int, base_shape: str, base_size, orientation: int = 0
            ) -> set:
                if not is_micro_board or base_size == 1:
                    return {(col, row)}
                from engine.hex_utils import compute_occupied_hexes
                return compute_occupied_hexes(col, row, base_shape, base_size, orientation)

            def _is_footprint_deployable(
                footprint: set, pool_set: set, wall_set: set, used: set
            ) -> bool:
                for c, r in footprint:
                    if not _is_valid_deploy_hex(c, r):
                        return False
                    if pool_set and (c, r) not in pool_set:
                        return False
                    if (c, r) in wall_set:
                        return False
                    if (c, r) in used:
                        return False
                return True

            basic_units = self._fold_attached_characters(basic_units, unit_registry)

            # Les coordonnées de roster sont écrites dans la résolution déclarée par `board_ref`,
            # comme le terrain du même scénario. Sans board_ref il n'y a pas d'échelle source
            # déclarée : le scénario vit dans le dossier de son propre plateau, rien à convertir.
            roster_downscale_ratio = 1
            model_cohesion_hex = 0
            global_cohesion_hex = 0
            floor_hexes_by_level: Dict[int, set] = {}
            _scenario_board_ref = (
                scenario_data.get("board_ref") if isinstance(scenario_data, dict) else None
            )
            if self._has_declared_source_board(scenario_file, _scenario_board_ref):
                roster_downscale_ratio = self._board_ref_downscale_ratio(
                    scenario_file, _scenario_board_ref
                )
            if roster_downscale_ratio != 1:
                if is_micro_board:
                    # Le placement converti raisonne PAR CASE (une figurine = une case). Sur un
                    # plateau à empreintes multi-hex, réserver la seule case centrale laisserait
                    # deux socles se chevaucher sans que rien ne le signale. Configuration
                    # inatteignable aujourd'hui (les données sont en x5, la seule cible plus
                    # grossière est x1, où une figurine tient dans une case) : on refuse
                    # explicitement plutôt que de livrer un placement par empreinte non testé.
                    raise ValueError(
                        f"Scenario '{scenario_file}': conversion des positions de roster x"
                        f"{roster_downscale_ratio} vers un plateau à empreintes multi-hex "
                        f"(inches_to_subhex={_ish}) non supportée"
                    )
                # Cases couvertes par un plancher, par niveau : contrainte de placement des
                # figurines déclarées à l'étage (`floor_height_at` lève si la case n'y est pas).
                for _area in resolved_terrain_areas or []:
                    for _floor in _area.get("floors", []):  # get allowed (aire sans étage)
                        _level = int(require_key(_floor, "level"))
                        floor_hexes_by_level.setdefault(_level, set()).update(
                            (int(h[0]), int(h[1])) for h in require_key(_floor, "hexes")
                        )
                from config_loader import get_config_loader
                _game_rules = require_key(get_config_loader().get_game_config(), "game_rules")
                # Portée de cohérence (03.03) en POUCES dans game_config → en hex du plateau actif.
                # C'est le déplacement maximal toléré pour dégager une figurine : au-delà, elle
                # sortirait de sa propre escouade.
                model_cohesion_hex = int(require_key(_game_rules, "unit_model_cohesion_range")) * _ish
                # 2e puce (03.03) : écart max fig-à-fig, vérifié en sortie de conversion.
                global_cohesion_hex = int(require_key(_game_rules, "unit_global_cohesion_range")) * _ish

            enhanced_units = []
            for unit_data in basic_units:
                if "unit_type" not in unit_data:
                    raise KeyError(f"Unit missing required 'unit_type' field: {unit_data}")
                
                unit_type = unit_data["unit_type"]
                unit_player = require_key(unit_data, "player")
                if int(unit_player) not in deployment_type_by_player:
                    raise ValueError(f"Invalid unit player for deployment: {unit_player}")

                try:
                    full_unit_data = unit_registry.get_unit_data(unit_type)
                except Exception as e:
                    raise ValueError(f"Failed to get unit data for '{unit_type}': {e}")

                # Socle du placement de déploiement : MÊME autorité que l'unité construite
                # ensuite (`_build_enhanced_unit`). L'ancien bloc dupliquait la formule de
                # scaling sous `if is_micro_board` ; à `inches_to_subhex == 1`
                # `_compute_deploy_footprint` ne rend de toute façon qu'un hex, donc la
                # normalisation `round`/1 de `_scale_socle` y est équivalente.
                base_shape, base_size = _scale_socle(
                    require_key(full_unit_data, "BASE_SHAPE"),
                    require_key(full_unit_data, "BASE_SIZE"),
                    _ish,
                    f"datasheet {unit_type} (déploiement)",
                )
                player_deployment_type = deployment_type_by_player[int(unit_player)]
                # 20.01 — « Instead of setting up these units on the battlefield during
                # deployment, place them to one side ». Une unité en réserves n'entre dans AUCUN
                # des trois modes de placement : ni tirage aléatoire, ni position fixe du roster,
                # ni pool de déploiement actif. Sentinelle (-1,-1) = hors table, exactement comme
                # une unité en attente de déploiement actif (source unique `deployed_on_turn`).
                in_reserves = bool(unit_data.get("strategic_reserves", False))  # get allowed
                if in_reserves:
                    _reserve_keywords = {
                        str(require_key(kw, "keywordId")).strip().lower()
                        for kw in require_key(full_unit_data, "UNIT_KEYWORDS")
                    }
                    if "fortification" in _reserve_keywords:
                        raise ValueError(
                            f"Unit {unit_data.get('id')} ({unit_type}) : une FORTIFICATION ne peut "
                            f"pas être placée en réserves stratégiques (règle 20.01)"
                        )
                pool_set = set()
                # deploy_pools est peuplé soit par les deployment_zones du terrain (voie moderne,
                # sans nom 'deployment_zone'), soit par la voie legacy config/deployment/<board>/.
                # Le pool suffit — ne pas exiger en plus le NOM legacy 'deployment_zone'.
                if int(unit_player) in deploy_pools:
                    pool_set = deploy_pools[int(unit_player)]

                if in_reserves:
                    chosen_col, chosen_row = -1, -1
                elif player_deployment_type == "random":
                    if not pool_set:
                        raise ValueError(f"No deployment pool for player {unit_player}")
                    candidates = [
                        (c, r) for c, r in pool_set
                        if _is_footprint_deployable(
                            _compute_deploy_footprint(c, r, base_shape, base_size),
                            pool_set, wall_hex_set, used_hexes,
                        )
                    ]
                    if not candidates:
                        raise ValueError(
                            f"No available deployment hexes for player {unit_player} "
                            f"(unit {unit_data.get('id')} base_size={base_size})"
                        )
                    chosen_col, chosen_row = random.choice(candidates)
                    fp = _compute_deploy_footprint(chosen_col, chosen_row, base_shape, base_size)
                    used_hexes.update(fp)
                elif player_deployment_type == "active":
                    chosen_col, chosen_row = -1, -1
                else:
                    required_fields = ["id", "player", "col", "row"]
                    for field in required_fields:
                        if field not in unit_data:
                            raise KeyError(f"Unit missing required field '{field}': {unit_data}")
                    if roster_downscale_ratio != 1:
                        unit_data = self._downscale_fixed_unit(
                            unit_data, roster_downscale_ratio, _is_valid_deploy_hex,
                            wall_hex_set, used_hexes, model_cohesion_hex, global_cohesion_hex,
                            floor_hexes_by_level,
                        )
                    chosen_col, chosen_row = normalize_coordinates(unit_data["col"], unit_data["row"])
                    fp = _compute_deploy_footprint(chosen_col, chosen_row, base_shape, base_size)
                    # Placement FIXE : ne confiner à la zone que pour la voie legacy nommée
                    # (config/deployment/<board>/<zone>). Neutralité PvP stricte : les scénarios
                    # à zones-terrain + placement fixe posent les unités librement (comportement
                    # d'avant le peuplement du pool depuis le terrain) — pas de durcissement.
                    if deployment_zone and pool_set:
                        for c, r in fp:
                            if (c, r) not in pool_set:
                                raise ValueError(
                                    f"Unit {unit_data.get('id')} footprint cell ({c},{r}) outside "
                                    f"deployment zone '{deployment_zone}' for player {unit_player}"
                                )
                    for c, r in fp:
                        if not _is_valid_deploy_hex(c, r):
                            raise ValueError(
                                f"Unit {unit_data.get('id')} footprint cell ({c},{r}) on invalid hex"
                            )
                        if wall_hex_set and (c, r) in wall_hex_set:
                            raise ValueError(
                                f"Unit {unit_data.get('id')} footprint cell ({c},{r}) on wall hex"
                            )
                        if (c, r) in used_hexes:
                            raise ValueError(
                                f"Unit {unit_data.get('id')} footprint overlap at ({c},{r})"
                            )
                    used_hexes.update(fp)

                enhanced_unit = self._build_enhanced_unit(
                    unit_data, full_unit_data, unit_type, unit_player,
                    player_deployment_type, chosen_col, chosen_row, unit_registry,
                )
                enhanced_units.append(enhanced_unit)

            # 20.01 — plafond des réserves, vérifié AU CHARGEMENT (contrôle dur). N'a de sens
            # qu'avec une taille de bataille déclarée (`scale`) : les scénarios PvP historiques
            # (liste d'unités nue, sans `scale`) n'en portent pas, et aucun d'eux ne déclare de
            # réserves — si l'un le faisait, l'absence de `scale` lèverait ici plutôt que de
            # désactiver le plafond en silence.
            _declared_reserves = any(u["in_strategic_reserves"] for u in enhanced_units)
            _scale_raw = scenario_data.get("scale") if isinstance(scenario_data, dict) else None
            if _declared_reserves:
                if _scale_raw is None:
                    raise ValueError(
                        f"Scenario {scenario_file} déclare des réserves stratégiques sans 'scale' : "
                        f"la limite de points de la bataille est inconnue, le plafond 20.01 "
                        f"(50 %) ne peut pas être vérifié"
                    )
                validate_strategic_reserves_cap(
                    enhanced_units,
                    battle_points_limit(_scale_raw, f"Scenario {scenario_file}"),
                    f"Scenario {scenario_file}",
                )

            # Extract optional terrain data from scenario
            # If present in scenario, use it; otherwise return None for board config selection
            scenario_walls = resolved_scenario_walls
            scenario_dense_walls = resolved_scenario_dense_walls
            scenario_objectives = resolved_scenario_objectives
            scenario_primary_objective = None
            scenario_wall_ref = (
                scenario_data.get("wall_ref") if isinstance(scenario_data, dict) else None
            )

            if isinstance(scenario_data, dict):
                if "primary_objectives" in scenario_data:
                    scenario_primary_objective = scenario_data["primary_objectives"]
                elif "primary_objective" in scenario_data:
                    scenario_primary_objective = scenario_data["primary_objective"]

            scenario_primary_objectives = (
                scenario_primary_objective
                if isinstance(scenario_primary_objective, list)
                else None
            )
            scenario_primary_objective_single = (
                scenario_primary_objective
                if scenario_primary_objective is not None and not isinstance(scenario_primary_objective, list)
                else None
            )

            deployment_pools_serializable = None
            if deploy_pools:
                deployment_pools_serializable = {
                    player: sorted(list(pool))
                    for player, pool in deploy_pools.items()
                }

            scenario_uses_codex_detachment = (
                scenario_data.get("uses_codex_detachment")  # get allowed
                if isinstance(scenario_data, dict) else None
            )
            scenario_army_faction = (
                {
                    str(require_key(scenario_roster_info, "agent_player")):
                        require_key(scenario_roster_info, "agent_army_faction"),
                    str(require_key(scenario_roster_info, "opponent_player")):
                        require_key(scenario_roster_info, "opponent_army_faction"),
                }
                if scenario_roster_info is not None
                else (
                    scenario_data.get("army_faction")  # get allowed
                    if isinstance(scenario_data, dict) else None
                )
            )
            _require_codex_detachment_when_astartes(
                scenario_army_faction, scenario_uses_codex_detachment, str(scenario_file),
                roster_sourced=scenario_roster_info is not None,
            )

            # Return dict with units and optional terrain
            return {
                "units": enhanced_units,
                "wall_hexes": scenario_walls,
                "dense_wall_hexes": scenario_dense_walls,
                "terrain_areas": resolved_terrain_areas or [],
                "wall_ref": scenario_wall_ref,
                "objectives": scenario_objectives,
                "primary_objectives": scenario_primary_objectives,
                "primary_objective": scenario_primary_objective_single,
                "deployment_zone": deployment_zone,
                "deployment_type": deployment_type,
                "deployment_type_by_player": deployment_type_by_player,
                "deployment_pools": deployment_pools_serializable,
                "roster_info": scenario_roster_info,
                # Taille de bataille en points (20.01) — None quand le scénario ne la déclare
                # pas (`scale` absent : scénarios PvP historiques). Le plafond de réserves est
                # alors invérifiable, donc la mise en réserve n'est pas proposée : l'absence
                # ferme la règle, elle ne l'ouvre pas sans contrôle.
                "points_limit": (
                    battle_points_limit(_scale_raw, f"Scenario {scenario_file}")
                    if _scale_raw is not None else None
                ),
                # Oath of Moment (chantier 03) : « If you are using a Codex: Space Marines
                # Detachment ». Donnée d'ARMÉE déclarée par le scénario — le moteur n'a pas de
                # système de détachement et ne peut pas la déduire. `.get` : elle n'a de sens
                # que pour une armée ADEPTUS ASTARTES, et c'est le consommateur du +1 Wound qui
                # lève si elle manque alors qu'elle est nécessaire (aucun défaut ici, aucun
                # blocage des scénarios qui n'en ont pas besoin).
                "uses_codex_detachment": scenario_uses_codex_detachment,
                # Faction d'Armée DÉCLARÉE par joueur (« If your Army Faction is … »). Jumeau
                # exact de la clé ci-dessus : donnée d'armée que le moteur ne peut pas déduire
                # de ce qui est sur la table, transmise telle quelle. C'est `army_faction` qui
                # lève si elle manque au moment où une capacité de faction la demande.
                #
                # DEUX sources, et la priorité n'est pas un confort : un scénario à rosters tire
                # ses listes au sort à chaque épisode (`training_random`), donc seule la liste
                # chargée sait quelle est sa faction. Une déclaration de scénario décrirait
                # l'armée d'un autre épisode.
                "army_faction": scenario_army_faction,
            }

    def _fold_attached_characters(self, basic_units: List[Dict[str, Any]], unit_registry: Any) -> List[Dict[str, Any]]:
        """Fusionne les characters ``attached_squad`` comme figurines de leur squad.

        Règle 19 : un character déclaré séparément avec ``"attached_squad": <id>``
        n'est qu'une écriture plus lisible. On l'injecte dans le tableau ``models``
        du squad cible (override ``unit_type``) puis on le retire des unités : en jeu
        l'unité attachée n'existe pas à part (déploiement/valeur/PV/ciblage comme avant).
        Mutation en place de ``basic_units`` (déjà un deepcopy du scénario), renvoie la
        liste filtrée. Source unique réutilisée par le chargement et ``change_roster``.
        """
        units_by_id_raw = {str(u["id"]): u for u in basic_units if "id" in u}
        folded_ids: Set[str] = set()
        # Unicité 19.01/24.22/24.34 : au plus un leader ET un support par bodyguard.
        attached_roles_by_target: Dict[str, Set[str]] = {}
        for u in basic_units:
            if "attached_squad" not in u:
                continue
            target_id = str(u["attached_squad"])
            if target_id == str(u.get("id")):
                raise ValueError(f"Unit {u.get('id')}: 'attached_squad' cannot reference itself")
            if target_id not in units_by_id_raw:
                raise ValueError(
                    f"Unit {u.get('id')}: 'attached_squad' references unknown unit '{target_id}'"
                )
            target = units_by_id_raw[target_id]
            if str(require_key(target, "player")) != str(require_key(u, "player")):
                raise ValueError(
                    f"Unit {u.get('id')}: 'attached_squad' target '{target_id}' "
                    f"belongs to a different player"
                )
            # Légalité d'attachement 19.01/24.22/24.34 : le character doit être un
            # leader/support et la cible un bodyguard ÉLIGIBLE — un de ses keywords de
            # nom d'unité ∈ CAN_LEAD du character (comparaison insensible à la casse,
            # les entrées CAN_LEAD listent des noms d'unité comme "terminator squad").
            char_data = unit_registry.get_unit_data(u["unit_type"])
            char_role = _derive_model_role(require_key(char_data, "UNIT_RULES"))
            if char_role not in ("leader", "support"):
                raise ValueError(
                    f"Unit {u.get('id')} ({u['unit_type']}): 'attached_squad' set but the "
                    f"unit has no LEADER/SUPPORT role (derived role: {char_role})"
                )
            can_lead = {str(name).lower() for name in char_data["CAN_LEAD"]} if "CAN_LEAD" in char_data else set()
            target_data = unit_registry.get_unit_data(target["unit_type"])
            target_keywords = {
                str(kw["keywordId"]).lower()
                for kw in require_key(target_data, "UNIT_KEYWORDS")
                if isinstance(kw, dict) and "keywordId" in kw
            }
            if not (can_lead & target_keywords):
                raise ValueError(
                    f"Unit {u.get('id')} ({u['unit_type']}): illegal attachment (19.01) — "
                    f"target '{target_id}' ({target['unit_type']}) is not an eligible bodyguard. "
                    f"CAN_LEAD={sorted(can_lead)} vs target keywords={sorted(target_keywords)}"
                )
            existing_roles = attached_roles_by_target.setdefault(target_id, set())
            if char_role in existing_roles:
                raise ValueError(
                    f"Unit {u.get('id')} ({u['unit_type']}): bodyguard '{target_id}' already has "
                    f"a {char_role} attached (19.01: at most one leader and one support per bodyguard)"
                )
            existing_roles.add(char_role)
            # Figurine du character injectée dans le squad (override unit_type).
            # `attached_from` = id de l'unité character d'origine : c'est la SOURCE au sens
            # 19.04 (« until the last model in that leader/support unit is destroyed »). Sans
            # ce marqueur, rien ne distingue la figurine du leader d'une figurine native du
            # bodyguard, et l'extinction des règles ne peut pas être calculée.
            char_model: Dict[str, Any] = {
                "unit_type": u["unit_type"], "attached_from": str(u["id"]),
            }
            if "col" in u:
                char_model["col"] = u["col"]
            if "row" in u:
                char_model["row"] = u["row"]
            # Le squad doit exposer "models" ; sinon le créer depuis son ancre.
            if "models" not in target:
                base_model: Dict[str, Any] = {}
                if "col" in target:
                    base_model["col"] = target["col"]
                if "row" in target:
                    base_model["row"] = target["row"]
                target["models"] = [base_model]
            target["models"].append(char_model)
            folded_ids.add(str(u["id"]))
        if folded_ids:
            basic_units = [u for u in basic_units if str(u.get("id")) not in folded_ids]
        return basic_units

    def _build_enhanced_unit(
        self,
        unit_data: Dict[str, Any],
        full_unit_data: Dict[str, Any],
        unit_type: str,
        unit_player: Any,
        player_deployment_type: str,
        chosen_col: int,
        chosen_row: int,
        unit_registry: Any,
    ) -> Dict[str, Any]:
        """Construit une unité moteur enrichie depuis sa déclaration brute.

        Indépendant de la géométrie du board (murs/pools) : la position est fournie
        (``chosen_col``/``chosen_row``, sentinelle ``-1,-1`` en déploiement actif).
        Normalise le champ optionnel ``models`` (squad multi-figurines, override
        ``unit_type`` par figurine, sommes HP/VALUE). Source unique réutilisée par
        ``load_units_from_scenario`` ET par le changement de roster (``change_roster``).
        """
        required_fields = ["id", "player"]
        for field in required_fields:
            if field not in unit_data:
                raise KeyError(f"Unit missing required field '{field}': {unit_data}")

        # 20.01 — une unité en réserves est HORS TABLE au même titre qu'une unité en attente de
        # déploiement actif : figurines à la sentinelle (-1,-1) et `deployed_on_turn` nul, quel
        # que soit le mode de déploiement du joueur. Les positions déclarées par un roster
        # positionné (mode 'fixed') sont donc ignorées pour elle — et surtout PAS appliquées,
        # sinon l'ancre (-1,-1) et models[0] divergeraient (invariant `build_units_cache`).
        in_strategic_reserves = bool(unit_data.get("strategic_reserves", False))  # get allowed
        off_board = player_deployment_type == "active" or in_strategic_reserves

        # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Extract RNG_WEAPONS and CC_WEAPONS
        rng_weapons = copy.deepcopy(require_key(full_unit_data, "RNG_WEAPONS"))
        cc_weapons = copy.deepcopy(require_key(full_unit_data, "CC_WEAPONS"))

        # Autorité UNIQUE de scaling (subhexes) : MOVE + portées d'armes, comme BASE_SIZE plus bas.
        # Toutes les units passent par ici (loader, change_roster, reload) → scaling garanti une fois.
        scale = self._get_inches_to_subhex()
        if scale != 1:
            for w in rng_weapons:
                w["RNG"] = int(require_key(w, "RNG")) * scale
            for w in cc_weapons:
                if "RNG" in w:
                    w["RNG"] = int(w["RNG"]) * scale

        # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Initialize selected weapon indices
        selected_rng_weapon_index = 0 if rng_weapons else None
        selected_cc_weapon_index = 0 if cc_weapons else None

        # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Extract SHOOT_LEFT and ATTACK_LEFT from selected weapons
        shoot_left = 0
        if rng_weapons and selected_rng_weapon_index is not None:
            selected_weapon = rng_weapons[selected_rng_weapon_index]
            if isinstance(selected_weapon, dict):
                shoot_left = resolve_dice_value(
                    require_key(selected_weapon, "NB"),
                    "scenario_init_shoot_left",
                )
            else:
                raise TypeError(f"Unit {unit_type}: RNG_WEAPONS[{selected_rng_weapon_index}] is {type(selected_weapon).__name__}, expected dict. Value: {selected_weapon}")

        attack_left = 0
        if cc_weapons and selected_cc_weapon_index is not None:
            selected_weapon = cc_weapons[selected_cc_weapon_index]
            if isinstance(selected_weapon, dict):
                attack_left = resolve_dice_value(
                    require_key(selected_weapon, "NB"),
                    "scenario_init_attack_left",
                )
            else:
                raise TypeError(f"Unit {unit_type}: CC_WEAPONS[{selected_cc_weapon_index}] is {type(selected_weapon).__name__}, expected dict. Value: {selected_weapon}")

        if "orientation" in unit_data:
            orientation_u = int(require_key(unit_data, "orientation"))
        elif "orientation" in full_unit_data:
            orientation_u = int(require_key(full_unit_data, "orientation"))
        else:
            orientation_u = 0

        # Socle de l'unité : converti ET validé une seule fois (l'appel était fait deux fois,
        # une par champ). `context` nomme l'unité pour qu'une datasheet incohérente
        # (ex. `oval` avec un BASE_SIZE scalaire) soit identifiable au chargement.
        _u_base_shape, _u_base_size = _scale_socle(
            require_key(full_unit_data, "BASE_SHAPE"),
            require_key(full_unit_data, "BASE_SIZE"),
            scale,
            f"datasheet {unit_type} (unité {unit_data['id']})",
        )

        _norm_col, _norm_row = normalize_coordinates(chosen_col, chosen_row)
        enhanced_unit = {
            "id": str(unit_data["id"]),
            "player": unit_player,
            "unitType": unit_type,
            "DISPLAY_NAME": require_key(full_unit_data, "DISPLAY_NAME"),
            "col": _norm_col,
            "row": _norm_row,
            # Niveau vertical (étages, format B). 0 = rez-de-chaussée (défaut métier).
            "level": _validate_level(unit_data.get("level", full_unit_data.get("level", 0)), str(unit_data["id"])),  # get allowed (champ optionnel : scénarios sans étages). Source = déclaration scénario (unit_data), comme orientation.
            "HP_CUR": full_unit_data["HP_MAX"],
            "HP_MAX": full_unit_data["HP_MAX"],
            "MOVE": full_unit_data["MOVE"] * scale,
            "T": full_unit_data["T"],
            "ARMOR_SAVE": full_unit_data["ARMOR_SAVE"],
            "INVUL_SAVE": full_unit_data["INVUL_SAVE"],
            # MULTIPLE_WEAPONS_IMPLEMENTATION.md: Multiple weapons system
            "RNG_WEAPONS": rng_weapons,
            "CC_WEAPONS": cc_weapons,
            "selectedRngWeaponIndex": selected_rng_weapon_index,
            "selectedCcWeaponIndex": selected_cc_weapon_index,
            "LD": full_unit_data["LD"],
            "OC": full_unit_data["OC"],
            "VALUE": full_unit_data["VALUE"],
            "ICON": full_unit_data["ICON"],
            "ICON_SCALE": full_unit_data["ICON_SCALE"],
            "ILLUSTRATION_RATIO": require_key(full_unit_data, "ILLUSTRATION_RATIO"),
            # Socle : forme ET taille passent par `_scale_socle` (autorité unique, cf. sa
            # docstring). À `inches_to_subhex == 1` il est normalisé en `round`/1 — une figurine
            # tient dans une case et la forme n'a plus de sens géométrique.
            "BASE_SHAPE": _u_base_shape,
            # Hauteur du modèle (pouces) : clairance sous les étages (§13.06 maison) — comparée telle
            # quelle à ``height_inches`` des floors (même unité), sans scaling subhex.
            "MODEL_HEIGHT": float(require_key(full_unit_data, "MODEL_HEIGHT")),
            "BASE_SIZE": _u_base_size,
            "orientation": orientation_u,
            "UNIT_RULES": copy.deepcopy(require_key(full_unit_data, "UNIT_RULES")),
            # Provenance des règles (19.04) — sources IMMUABLES dont `UNIT_RULES` est dérivé :
            #   `_UNIT_RULES_OWN`       = bloc « bodyguard unit » (datasheet de l'escouade +
            #                             règles propres de ses figurines natives) ;
            #   `_ATTACHED_RULE_GROUPS` = {id de l'unité leader/support repliée -> ses règles}.
            # `UNIT_RULES` = union des sources dont il reste ≥1 figurine vivante, recalculée à
            # chaque mort par `recompute_unit_rules_in_effect`. Renseignées pour de bon dans le
            # bloc `models` ci-dessous ; ces valeurs valent pour une unité sans `models`.
            "_UNIT_RULES_OWN": copy.deepcopy(require_key(full_unit_data, "UNIT_RULES")),
            "_ATTACHED_RULE_GROUPS": {},
            "UNIT_KEYWORDS": copy.deepcopy(require_key(full_unit_data, "UNIT_KEYWORDS")),
            # Mots-clés de FACTION (chantier 03) : « If your Army Faction is ORKS / ADEPTUS
            # ASTARTES ». Union 19.03 appliquée plus bas, exactement comme UNIT_KEYWORDS.
            "FACTION_KEYWORDS": copy.deepcopy(require_key(full_unit_data, "FACTION_KEYWORDS")),
            # Cf. create_unit : 0 = posée avant la bataille, None = hors table (déploiement actif
            # en attente, ou réserves stratégiques 20.01).
            "deployed_on_turn": None if off_board else 0,
            # 20.01 — statut de RÉSERVE. `deployed_on_turn` reste la source unique du « où » (hors
            # table / posée à quel tour) ; ce drapeau porte le « pourquoi », que la position ne
            # peut pas exprimer : une unité hors table en phase de déploiement attend d'être
            # posée, une unité en réserves attend un ingress move (20.04). Ce n'est donc PAS un
            # second modèle de hors-table.
            "in_strategic_reserves": in_strategic_reserves,
            # 20.02 — unité RETIRÉE du board puis replacée en réserves pendant la bataille
            # (Da Jump). Exemptée de la destruction de fin de 3e round (20.04).
            "reserves_repositioned": False,
            **_default_reserves_parameters(),
            # Attached units (rule 19.01): empty list for non-leader units (valid business case).
            "CAN_LEAD": copy.deepcopy(full_unit_data["CAN_LEAD"] if "CAN_LEAD" in full_unit_data else []),
            "SHOOT_LEFT": shoot_left,
            "ATTACK_LEFT": attack_left,

            # Terrain visibility (rules 13.08-13.09): hideable derived from keywords, hidden is runtime state
            "hideable": compute_hideable(require_key(full_unit_data, "UNIT_KEYWORDS")),
            "hidden": False,
            "hidden_models": [],

            # Battle-shock state (règle 01.07) — reset au début de la command phase du joueur
            "battle_shocked": False,
        }

        # PR4 4c : pass-through champ optionnel "models" (multi-fig squad)
        # Format option B (cf. squad_audit.md §8) : liste de {col, row[, unit_type]}
        # Si absent → backward compat (auto-build 1 fig in _build_models_for_unit)
        # Si unit_type présent dans un spec → stats overrides pour ce modèle spécifique
        if "models" in unit_data:
            raw_models = unit_data["models"]
            if not isinstance(raw_models, list) or not raw_models:
                raise ValueError(
                    f"Unit {unit_data.get('id')}: 'models' must be a non-empty list"
                )
            normalized_models: List[Dict[str, Any]] = []
            total_hp_cur = 0
            total_value = 0
            for idx, spec in enumerate(raw_models):
                if not isinstance(spec, dict):
                    raise TypeError(
                        f"Unit {unit_data.get('id')}: models[{idx}] must be dict, got {type(spec).__name__}"
                    )
                # Hors table (mode active, ou réserves 20.01) : l'escouade n'est
                # pas encore posée. On conserve la composition (nombre de
                # figurines + unit_type par figurine) mais on ne place pas les
                # figurines : ancre et toutes les figurines à la sentinelle
                # (-1,-1) pour respecter l'invariant ancre==models[0]
                # (build_units_cache). Les positions réelles sont générées à la
                # mise en place (formation compacte) — déploiement ou ingress
                # move (20.04) — puis ajustées via squad/fig move.
                if off_board:
                    m_norm_col, m_norm_row = -1, -1
                else:
                    m_col = int(require_key(spec, "col"))
                    m_row = int(require_key(spec, "row"))
                    m_norm_col, m_norm_row = normalize_coordinates(m_col, m_row)
                # Niveau vertical par-figurine (§2.5, escouade répartie sur plusieurs étages).
                # 'level' optionnel = sol (0). Sans recopie ici, build_units_cache retombe sur le
                # niveau ancre de l'unité et perd le level déclaré par modèle dans le scénario.
                m_level = _validate_level(spec.get("level", 0), unit_data["id"])  # get allowed (champ optionnel : level absent = sol)
                m_spec: Dict[str, Any] = {"col": m_norm_col, "row": m_norm_row, "level": m_level}
                # Provenance 19.04 posée par le fold : conservée jusqu'à models_cache.
                if "attached_from" in spec:
                    m_spec["attached_from"] = str(spec["attached_from"])
                model_unit_type = spec.get("unit_type")
                if model_unit_type is not None:
                    # Load stats for this specific model's unit_type
                    try:
                        m_data = unit_registry.get_unit_data(model_unit_type)
                    except Exception as e:
                        raise ValueError(
                            f"Unit {unit_data.get('id')} models[{idx}]: "
                            f"unknown unit_type '{model_unit_type}': {e}"
                        )
                    m_rng = copy.deepcopy(require_key(m_data, "RNG_WEAPONS"))
                    m_cc = copy.deepcopy(require_key(m_data, "CC_WEAPONS"))
                    _ish_local = self._get_inches_to_subhex()
                    if _ish_local != 1:
                        for w in m_rng:
                            if "RNG" in w:
                                w["RNG"] = int(w["RNG"]) * _ish_local
                        for w in m_cc:
                            if "RNG" in w:
                                w["RNG"] = int(w["RNG"]) * _ish_local
                    # BASE_SIZE : même transformation subhex que l'unité parente
                    # (cf. enhanced_unit ci-dessus) pour un affichage cohérent.
                    _m_base_shape, _m_base_size = _scale_socle(
                        require_key(m_data, "BASE_SHAPE"),
                        require_key(m_data, "BASE_SIZE"),
                        _ish_local,
                        f"datasheet {model_unit_type} "
                        f"(figurine {idx} de l'unité {unit_data.get('id')})",
                    )
                    m_spec.update({
                        "unit_type": model_unit_type,
                        "DISPLAY_NAME": require_key(m_data, "DISPLAY_NAME"),
                        "ICON": require_key(m_data, "ICON"),
                        "ICON_SCALE": require_key(m_data, "ICON_SCALE"),
                        # Ratio d'illustration propre à la figurine : l'aperçu (UnitStatusTable) doit
                        # dimensionner l'illustration du modèle exactement comme son unité autonome.
                        "ILLUSTRATION_RATIO": require_key(m_data, "ILLUSTRATION_RATIO"),
                        "BASE_SHAPE": _m_base_shape,
                        "BASE_SIZE": _m_base_size,
                        # Hauteur PROPRE de la figurine (§03.04 : l'engagement est 2" horizontal ET
                        # 5" vertical). Même raison que `BASE_SHAPE`/`BASE_SIZE` juste au-dessus :
                        # l'intervalle vertical d'un personnage attaché est le sien, pas celui de
                        # l'escouade qui l'héberge. Sans cette recopie, le socle était mesuré par
                        # figurine et la hauteur au bloc — une moitié de la règle par figurine,
                        # l'autre au bloc.
                        "MODEL_HEIGHT": float(require_key(m_data, "MODEL_HEIGHT")),
                        "HP_MAX": int(require_key(m_data, "HP_MAX")),
                        "T": int(require_key(m_data, "T")),
                        "ARMOR_SAVE": int(require_key(m_data, "ARMOR_SAVE")),
                        "INVUL_SAVE": int(require_key(m_data, "INVUL_SAVE")),
                        "OC": int(require_key(m_data, "OC")),
                        # Ld PROPRE de la figurine (01.06) : une unite attachee porte plusieurs
                        # caracteristiques de Ld et le jet retient la MEILLEURE. Sans cette
                        # recopie, un Warboss (LD 6+) replie dans des Boyz (LD 7+) laissait
                        # l'unite tester a 7+ — la datasheet du character n'etait lue nulle part.
                        "LD": int(require_key(m_data, "LD")),
                        "VALUE": int(require_key(m_data, "VALUE")),
                        "UNIT_RULES": copy.deepcopy(require_key(m_data, "UNIT_RULES")),
                        # Keywords PROPRES de la figurine (19.03) : l'unité porte l'UNION des
                        # keywords de ses composants, mais les règles qui parlent de « each
                        # model » (06.03 hazard : 3 MW si CHAQUE figurine est MONSTER/VEHICLE)
                        # doivent interroger la figurine, pas l'union — sinon un character
                        # attaché contaminerait toute l'escouade.
                        "UNIT_KEYWORDS": copy.deepcopy(require_key(m_data, "UNIT_KEYWORDS")),
                        # Faction PROPRE de la figurine — même raison que les keywords ci-dessus :
                        # l'unité porte l'union (19.03), la figurine porte sa datasheet.
                        "FACTION_KEYWORDS": copy.deepcopy(require_key(m_data, "FACTION_KEYWORDS")),
                        "RNG_WEAPONS": m_rng,
                        "CC_WEAPONS": m_cc,
                        "selectedRngWeaponIndex": 0 if m_rng else None,
                        "selectedCcWeaponIndex": 0 if m_cc else None,
                    })
                    total_hp_cur += int(require_key(m_data, "HP_MAX"))
                    total_value += int(require_key(m_data, "VALUE"))
                else:
                    # Figurine sans override : elle vaut ce que vaut une figurine de
                    # l'unit_type de l'escouade. VALUE est posé sur TOUTE figurine (pas
                    # seulement les override) car les consommateurs par-figurine — dont
                    # l'affichage UnitStatusTable — lisent models[i].VALUE et ne doivent
                    # jamais retomber sur unit["VALUE"], qui porte la valeur de l'ESCOUADE.
                    m_spec["VALUE"] = int(full_unit_data["VALUE"])
                    # Keywords propres = ceux de l'unit_type de l'escouade, capturés AVANT
                    # l'union 19.03 appliquée plus bas à enhanced_unit["UNIT_KEYWORDS"].
                    m_spec["UNIT_KEYWORDS"] = copy.deepcopy(require_key(full_unit_data, "UNIT_KEYWORDS"))
                    m_spec["FACTION_KEYWORDS"] = copy.deepcopy(
                        require_key(full_unit_data, "FACTION_KEYWORDS")
                    )
                    # Règles propres — jumeau des keywords ci-dessus, capturées AVANT l'union
                    # 19.04. Une figurine sans override est de l'unit_type de l'escouade : ses
                    # règles sont celles de SA datasheet, pas l'union de l'escouade. C'est ce que
                    # lisent les règles « if every model in this unit has this ability » (24.09).
                    m_spec["UNIT_RULES"] = copy.deepcopy(require_key(full_unit_data, "UNIT_RULES"))
                    total_hp_cur += int(full_unit_data["HP_MAX"])
                    total_value += int(full_unit_data["VALUE"])
                normalized_models.append(m_spec)
            enhanced_unit["models"] = normalized_models
            # Règle 19.03 (Keywords in attached units) : « an attached unit has the keywords of
            # all its component units ». Un squad contenant des figurines d'un autre unit_type
            # (leader/support replié par _fold_attached_characters, ou squad hétérogène) porte
            # donc l'UNION de leurs keywords. Sans ça, [ANTI-X] et les gates keyword (couvert
            # 13.08, étages 13.06) ne voyaient que les keywords du bodyguard.
            # Union ordonnée et dédupliquée sur keywordId (l'ordre reste stable et reproductible).
            seen_keywords = {
                str(require_key(kw, "keywordId")).strip().lower()
                for kw in enhanced_unit["UNIT_KEYWORDS"]
            }
            for spec in normalized_models:
                for kw in require_key(spec, "UNIT_KEYWORDS"):
                    kw_id = str(require_key(kw, "keywordId")).strip().lower()
                    if kw_id in seen_keywords:
                        continue
                    seen_keywords.add(kw_id)
                    enhanced_unit["UNIT_KEYWORDS"].append(copy.deepcopy(kw))
            # Même union 19.03 sur les mots-clés de FACTION. Elle n'est pas décorative : un
            # character d'une sous-faction (BLOOD ANGELS…) attaché à une escouade générique fait
            # entrer ce mot-clé dans l'armée, et c'est exactement ce que la clause d'exclusion du
            # +1 Wound d'Oath interroge.
            seen_factions = {
                _normalize_keyword(kw) for kw in enhanced_unit["FACTION_KEYWORDS"]
            }
            for spec in normalized_models:
                for kw in require_key(spec, "FACTION_KEYWORDS"):
                    kw_id = _normalize_keyword(kw)
                    if kw_id in seen_factions:
                        continue
                    seen_factions.add(kw_id)
                    enhanced_unit["FACTION_KEYWORDS"].append(copy.deepcopy(kw))
            # Les dérivés de keywords se recalculent sur l'union (même autorité, une seule fois).
            enhanced_unit["hideable"] = compute_hideable(enhanced_unit["UNIT_KEYWORDS"])
            # Règle 19.04 (Abilities in attached units) : « abilities/rules that affect a unit
            # (or models in it) apply to every model in an attached unit ». Jumeau exact de
            # l'union 19.03 ci-dessus, mais sur les RÈGLES et avec une extinction par source
            # (cf. `compute_unit_rules_in_effect`). Deux sources sont séparées ici une fois
            # pour toutes : le bloc bodyguard (datasheet de l'escouade + règles propres de ses
            # figurines natives — sergent, arme spéciale) et un groupe par character replié.
            # Les marqueurs de rôle sont retirés des règles de FIGURINE : ils qualifient la
            # figurine (ordre d'allocation 05.04, T bodyguard 19.02), pas l'escouade.
            own_rules: List[Dict[str, Any]] = copy.deepcopy(
                require_key(full_unit_data, "UNIT_RULES")
            )
            own_seen = {str(require_key(r, "ruleId")) for r in own_rules}
            attached_groups: Dict[str, List[Dict[str, Any]]] = {}
            for spec in normalized_models:
                spec_rules = strip_role_rules(spec["UNIT_RULES"]) if "UNIT_RULES" in spec else []
                if "attached_from" in spec:
                    attached_groups.setdefault(str(spec["attached_from"]), []).extend(
                        copy.deepcopy(spec_rules)
                    )
                    continue
                for rule in spec_rules:
                    rule_id = str(require_key(rule, "ruleId"))
                    if rule_id in own_seen:
                        continue
                    own_seen.add(rule_id)
                    own_rules.append(copy.deepcopy(rule))
            enhanced_unit["_UNIT_RULES_OWN"] = own_rules
            enhanced_unit["_ATTACHED_RULE_GROUPS"] = attached_groups
            enhanced_unit["UNIT_RULES"] = compute_unit_rules_in_effect(
                own_rules, attached_groups,
                native_alive=any("attached_from" not in s for s in normalized_models),
                alive_attached_sources=set(attached_groups),
            )
            # Invariant §2.5 : le niveau ancre de l'unité = niveau de models[0] (cf. commentaire
            # create_unit). Sans ça, une unité dont la 1ère figurine est déclarée en hauteur garde
            # une ancre au sol (0) et désynchronise units_cache de l'empreinte réelle.
            enhanced_unit["level"] = normalized_models[0]["level"]
            enhanced_unit["HP_CUR"] = total_hp_cur
            # VALUE d'une unité = valeur de l'ESCOUADE (somme des figurines), homogène
            # comme hétérogène. C'est la sémantique attendue par tous les agrégats :
            # condition de victoire (get_winner_by_value), métriques d'attrition,
            # avantage matériel de l'observation, et les usages par-figurine qui
            # divisent déjà par model_count_at_start (points_per_hp, reward par fig
            # tuée). Neutre pour une unité mono-figurine (total_value == VALUE).
            # La valeur d'UNE figurine reste portée par models[i]["VALUE"].
            enhanced_unit["VALUE"] = total_value

        return enhanced_unit

    def _load_units_from_roster_refs(
        self,
        scenario_data: Dict[str, Any],
        scenario_file: str
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Load agent/opponent units from compact roster references."""
        scale = require_key(scenario_data, "scale")
        if not isinstance(scale, str) or not scale.strip():
            raise ValueError(f"Scenario '{scenario_file}' has invalid 'scale': {scale!r}")
        scale_name = scale.strip()

        scenario_path = Path(scenario_file).resolve()
        path_parts = scenario_path.parts
        try:
            agents_idx = path_parts.index("agents")
            scenario_agent_key = path_parts[agents_idx + 1]
        except Exception as e:
            raise ValueError(
                f"Cannot resolve agent key from scenario path '{scenario_file}': {e}"
            )
        if scenario_agent_key in {"_p2_rosters", "p2_rosters"}:
            raise ValueError(
                f"Scenario path '{scenario_file}' points to shared roster directory, not an agent scenario"
            )

        split: Optional[str] = None
        if "/scenarios/training/" in scenario_file:
            split = "training"
        elif "/scenarios/holdout_regular/" in scenario_file or "/scenarios/holdout_hard/" in scenario_file:
            split = "holdout"
        else:
            raise ValueError(
                f"Scenario '{scenario_file}' must be located under scenarios/training, "
                f"scenarios/holdout_regular, or scenarios/holdout_hard"
            )
        holdout_split_for_p1: Optional[str] = None
        holdout_split_for_p2: Optional[str] = None
        if split == "holdout":
            if "/scenarios/holdout_regular/" in scenario_file:
                holdout_split_for_p1 = "holdout_regular"
                holdout_split_for_p2 = "holdout_regular"
            elif "/scenarios/holdout_hard/" in scenario_file:
                holdout_split_for_p1 = "holdout_hard"
                holdout_split_for_p2 = "holdout_hard"
            else:
                raise ValueError(
                    f"Holdout scenario '{scenario_file}' must be in holdout_regular/ or holdout_hard/"
                )

        agent_ref_value = require_key(scenario_data, "agent_roster_ref")
        opponent_ref_value = require_key(scenario_data, "opponent_roster_ref")
        agent_roster_seed = scenario_data.get("agent_roster_seed")
        if agent_roster_seed is not None:
            if not isinstance(agent_roster_seed, int) or isinstance(agent_roster_seed, bool) or agent_roster_seed < 0:
                raise ValueError(
                    f"Scenario '{scenario_file}' has invalid 'agent_roster_seed': {agent_roster_seed!r} "
                    f"(expected non-negative integer)"
                )

        agent_ref, agent_ref_randomized = self._resolve_roster_ref(
            agent_ref_value,
            expected_split=(split if split == "training" else str(holdout_split_for_p1)),
            scenario_file=scenario_file,
            field_name="agent_roster_ref",
            allow_random=(split in {"training", "holdout"}),
            scenario_agent_key=scenario_agent_key,
            scale_name=scale_name,
            roster_kind="agent",
            random_seed=agent_roster_seed
        )
        opponent_ref, _ = self._resolve_roster_ref(
            opponent_ref_value,
            expected_split=(split if split == "training" else str(holdout_split_for_p2)),
            scenario_file=scenario_file,
            field_name="opponent_roster_ref",
            allow_random=(split in {"training", "holdout"}),
            scenario_agent_key=scenario_agent_key,
            scale_name=scale_name,
            roster_kind="opponent",
            random_seed=None
        )

        project_root = Path(__file__).resolve().parent.parent
        agent_roster_path = (
            project_root / "config" / "agents" / scenario_agent_key / "rosters" / scale_name / agent_ref
        )
        opponent_roster_path = (
            project_root / "config" / "agents" / "_p2_rosters" / scale_name / opponent_ref
        )

        agent_roster_data = self._load_compact_roster_file(agent_roster_path, "AGENT")
        opponent_roster_data = self._load_compact_roster_file(opponent_roster_path, "OPPONENT")

        controlled_player = int(require_key(self.config, "controlled_player"))
        if controlled_player not in {1, 2}:
            raise ValueError(
                f"config['controlled_player'] must be 1 or 2 for roster scenario loading "
                f"(got {controlled_player})"
            )
        opponent_player = 2 if controlled_player == 1 else 1

        # Keep historical id ranges by player to avoid downstream assumptions:
        # - player 1 units in [1..]
        # - player 2 units in [101..]
        agent_id_start = 1 if controlled_player == 1 else 101
        opponent_id_start = 101 if opponent_player == 2 else 1

        roster_deployment_types = self._resolve_deployment_type_by_player(scenario_data)

        agent_units = self._expand_compact_roster_to_basic_units(
            roster_data=agent_roster_data,
            player=controlled_player,
            id_start=agent_id_start,
            roster_path=str(agent_roster_path),
            deployment_type=require_key(roster_deployment_types, controlled_player)
        )
        opponent_units = self._expand_compact_roster_to_basic_units(
            roster_data=opponent_roster_data,
            player=opponent_player,
            id_start=opponent_id_start,
            roster_path=str(opponent_roster_path),
            deployment_type=require_key(roster_deployment_types, opponent_player)
        )

        roster_info = {
            "scale": scale_name,
            "agent_roster_ref": agent_ref,
            "opponent_roster_ref": opponent_ref,
            "agent_roster_id": str(require_key(agent_roster_data, "roster_id")),
            "opponent_roster_id": str(require_key(opponent_roster_data, "roster_id")),
            "agent_ref_randomized": agent_ref_randomized,
            "agent_player": controlled_player,
            "opponent_player": opponent_player,
            # Faction d'Armée de chaque camp, telle que déclarée par la liste effectivement
            # chargée pour CET épisode — c'est ce que 08.04 lira (`config['army_faction']`).
            "agent_army_faction": str(require_key(agent_roster_data, "army_faction")),
            "opponent_army_faction": str(require_key(opponent_roster_data, "army_faction")),
        }
        return agent_units + opponent_units, roster_info

    def _resolve_roster_ref(
        self,
        raw_ref: Any,
        expected_split: str,
        scenario_file: str,
        field_name: str,
        allow_random: bool,
        scenario_agent_key: str,
        scale_name: str,
        roster_kind: str,
        random_seed: Optional[int]
    ) -> Tuple[str, bool]:
        """Resolve roster reference to '<expected_split>/file.json'."""
        import random

        if roster_kind not in {"agent", "opponent"}:
            raise ValueError(f"Invalid roster_kind: {roster_kind!r}")

        rng = random.Random(random_seed) if random_seed is not None else random

        ref_value = raw_ref
        was_randomized = False
        if isinstance(raw_ref, str) and allow_random:
            normalized_ref = raw_ref.strip().replace("\\", "/")
            random_token = f"{expected_split}_random"
            if normalized_ref == random_token:
                project_root = Path(__file__).resolve().parent.parent
                if roster_kind == "agent":
                    base_dir = (
                        project_root
                        / "config"
                        / "agents"
                        / scenario_agent_key
                        / "rosters"
                        / scale_name
                        / expected_split
                    )
                    pattern = f"agent_{expected_split}_roster*.json"
                else:
                    base_dir = (
                        project_root
                        / "config"
                        / "agents"
                        / "_p2_rosters"
                        / scale_name
                        / expected_split
                    )
                    pattern = f"opponent_{expected_split}_roster*.json"
                if not base_dir.exists():
                    raise FileNotFoundError(
                        f"Scenario '{scenario_file}' {field_name}={random_token!r} but directory does not exist: {base_dir}"
                    )
                candidates = [
                    p for p in sorted(base_dir.glob(pattern), key=lambda p: p.name)
                    if "_kpis" not in p.name and "_matchups" not in p.name
                ]
                if expected_split == "training":
                    candidates = self._filter_training_roster_candidates(candidates)
                if not candidates:
                    raise FileNotFoundError(
                        f"Scenario '{scenario_file}' {field_name}={random_token!r} but no files matching "
                        f"{pattern} in {base_dir}"
                    )
                chosen = rng.choice(candidates)
                ref_value = f"{expected_split}/{chosen.name}"
                was_randomized = True

        if isinstance(raw_ref, list):
            if not allow_random:
                raise ValueError(
                    f"Scenario '{scenario_file}' field '{field_name}' cannot be a list outside training split"
                )
            if not raw_ref:
                raise ValueError(
                    f"Scenario '{scenario_file}' field '{field_name}' list cannot be empty"
                )
            ref_value = rng.choice(raw_ref)
            was_randomized = True

        if not isinstance(ref_value, str) or not ref_value.strip():
            raise ValueError(
                f"Scenario '{scenario_file}' has invalid '{field_name}': {ref_value!r}"
            )

        normalized = ref_value.strip().replace("\\", "/")
        if normalized.startswith("../") or "/../" in normalized or normalized.startswith("/"):
            raise ValueError(
                f"Scenario '{scenario_file}' has unsafe roster ref in '{field_name}': {normalized}"
            )

        if "/" not in normalized:
            raise ValueError(
                f"Scenario '{scenario_file}' field '{field_name}' must be explicit '<split>/file.json', got '{normalized}'"
            )
        if not normalized.endswith(".json"):
            normalized = f"{normalized}.json"

        ref_split, _, ref_filename = normalized.partition("/")
        VALID_AGENT_SPLITS = {"training", "holdout_regular", "holdout_hard"}
        VALID_OPPONENT_SPLITS = {"training", "holdout", "holdout_regular", "holdout_hard"}
        valid_splits = VALID_AGENT_SPLITS if roster_kind == "agent" else VALID_OPPONENT_SPLITS
        project_root = Path(__file__).resolve().parent.parent

        # Allow explicit split in ref (e.g. holdout_regular/... when scenario is in training/)
        # Enables cross-split evaluation (P1 holdout vs P2 training)
        if ref_split in valid_splits:
            if roster_kind == "agent":
                explicit_base = (
                    project_root
                    / "config"
                    / "agents"
                    / scenario_agent_key
                    / "rosters"
                    / scale_name
                    / ref_split
                )
            else:
                explicit_base = (
                    project_root
                    / "config"
                    / "agents"
                    / "_p2_rosters"
                    / scale_name
                    / ref_split
                )
            explicit_path = explicit_base / ref_filename
            if explicit_path.exists():
                return normalized, was_randomized
            # Try roster_id match in explicit split (e.g. holdout_regular_p1_roster-01)
            if explicit_base.exists():
                requested_id = Path(ref_filename).stem
                for candidate_path in sorted(explicit_base.glob("*.json"), key=lambda p: p.name):
                    try:
                        with open(candidate_path, "r", encoding="utf-8-sig") as f:
                            data = json.load(f)
                        if require_key(data, "roster_id") == requested_id:
                            return f"{ref_split}/{candidate_path.name}", was_randomized
                    except (json.JSONDecodeError, KeyError, ConfigurationError):
                        continue

        # Strict split validation: ref must match expected_split (scenario path context)
        prefix = f"{expected_split}/"
        if not normalized.startswith(prefix):
            raise ValueError(
                f"Scenario '{scenario_file}' field '{field_name}' must target '{expected_split}/...' "
                f"(or explicit valid split) but got '{normalized}'"
            )
        filename = ref_filename
        if roster_kind == "agent":
            base_dir = (
                project_root
                / "config"
                / "agents"
                / scenario_agent_key
                / "rosters"
                / scale_name
                / expected_split
            )
        else:
            base_dir = (
                project_root
                / "config"
                / "agents"
                / "_p2_rosters"
                / scale_name
                / expected_split
            )
        direct_path = base_dir / filename
        if direct_path.exists():
            return normalized, was_randomized

        requested_roster_id = Path(filename).stem
        if not requested_roster_id.startswith(f"{roster_kind}_") or "roster-" not in requested_roster_id:
            raise FileNotFoundError(
                f"Scenario '{scenario_file}' references missing roster file '{normalized}' "
                f"and roster id inference is not supported for '{requested_roster_id}'"
            )

        if not base_dir.exists():
            raise FileNotFoundError(
                f"Scenario '{scenario_file}' references missing roster file '{normalized}' "
                f"and roster directory does not exist: {base_dir}"
            )

        matching_files: List[Path] = []
        for candidate_path in sorted(base_dir.glob("*.json"), key=lambda p: p.name):
            try:
                with open(candidate_path, "r", encoding="utf-8-sig") as candidate_file:
                    candidate_data = json.load(candidate_file)
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid JSON in roster file {candidate_path}: {e}")
            candidate_roster_id = require_key(candidate_data, "roster_id")
            if not isinstance(candidate_roster_id, str):
                raise TypeError(
                    f"Roster file {candidate_path} has non-string roster_id: "
                    f"{type(candidate_roster_id).__name__}"
                )
            if candidate_roster_id == requested_roster_id:
                matching_files.append(candidate_path)

        if len(matching_files) == 1:
            resolved_filename = matching_files[0].name
            return f"{expected_split}/{resolved_filename}", was_randomized
        if len(matching_files) > 1:
            raise ValueError(
                f"Scenario '{scenario_file}' roster ref '{normalized}' is ambiguous by roster_id "
                f"'{requested_roster_id}': {[str(path) for path in matching_files]}"
            )
        raise FileNotFoundError(
            f"Scenario '{scenario_file}' references missing roster file '{normalized}' "
            f"and no roster with roster_id '{requested_roster_id}' exists in {base_dir}"
        )

    def _filter_training_roster_candidates(self, candidates: List[Path]) -> List[Path]:
        """Apply optional progressive roster schedule for training random roster selection."""
        if len(candidates) == 0:
            return candidates

        training_cfg_raw = self.config.get("training_config")
        if training_cfg_raw is None:
            return candidates
        if not isinstance(training_cfg_raw, dict):
            raise TypeError(
                f"config['training_config'] must be dict when present (got {type(training_cfg_raw).__name__})"
            )

        schedule_raw = training_cfg_raw.get("roster_pool_schedule")
        if schedule_raw is None:
            return candidates
        if not isinstance(schedule_raw, dict):
            raise TypeError(
                f"training_config.roster_pool_schedule must be dict (got {type(schedule_raw).__name__})"
            )

        enabled = schedule_raw.get("enabled")
        if not isinstance(enabled, bool):
            raise TypeError("training_config.roster_pool_schedule.enabled must be bool")
        if not enabled:
            return candidates

        training_schedule = schedule_raw.get("training")
        if not isinstance(training_schedule, dict):
            raise TypeError(
                "training_config.roster_pool_schedule.training must be dict when schedule is enabled"
            )
        start_counts_raw = training_schedule.get("start_counts")
        end_counts_raw = training_schedule.get("end_counts")
        if not isinstance(start_counts_raw, dict) or not isinstance(end_counts_raw, dict):
            raise TypeError(
                "training_config.roster_pool_schedule.training.start_counts and end_counts must be dict"
            )

        classes = ("swarm", "troop", "elite")
        start_counts: Dict[str, int] = {}
        end_counts: Dict[str, int] = {}
        for cls in classes:
            start_value = start_counts_raw.get(cls)
            end_value = end_counts_raw.get(cls)
            if not isinstance(start_value, int) or isinstance(start_value, bool):
                raise TypeError(f"start_counts.{cls} must be integer")
            if not isinstance(end_value, int) or isinstance(end_value, bool):
                raise TypeError(f"end_counts.{cls} must be integer")
            if start_value <= 0 or end_value <= 0:
                raise ValueError(f"start_counts/end_counts.{cls} must be > 0")
            if end_value < start_value:
                raise ValueError(
                    f"end_counts.{cls} must be >= start_counts.{cls} ({end_value} < {start_value})"
                )
            start_counts[cls] = int(start_value)
            end_counts[cls] = int(end_value)

        total_episodes = training_cfg_raw.get("total_episodes")
        n_envs = training_cfg_raw.get("n_envs")

        episode_number = require_key(self.config, "_training_episode_index")
        if not isinstance(episode_number, int) or isinstance(episode_number, bool):
            raise TypeError("config._training_episode_index must be integer when roster_pool_schedule is enabled")

        progress = ramp_progress(max(0, int(episode_number)), total_episodes, n_envs)

        active_limits: Dict[str, int] = {}
        for cls in classes:
            start_value = start_counts[cls]
            end_value = end_counts[cls]
            interpolated = start_value + int(math.floor((end_value - start_value) * progress))
            active_limits[cls] = max(start_value, min(end_value, interpolated))

        filtered: List[Path] = []
        for candidate in candidates:
            match = re.search(r"(elite|swarm|troop)_(\d+)$", candidate.stem.lower())
            if match is None:
                continue
            roster_class = str(match.group(1))
            roster_idx = int(match.group(2))
            if roster_idx <= active_limits[roster_class]:
                filtered.append(candidate)

        if len(filtered) == 0:
            raise ValueError(
                "roster_pool_schedule produced zero eligible training rosters "
                f"(active_limits={active_limits}, candidates={len(candidates)})"
            )
        return filtered

    def _load_shared_walls_from_ref(
        self, wall_ref: Any, scenario_file: str, only_type: Optional[str] = None,
        board_ref: Optional[str] = None,
    ) -> List[List[int]]:
        """Load shared wall_hexes file referenced by scenario wall_ref.

        ``only_type`` (ex: "dense") restreint aux groupes de murs typés — set Solid/dense (rule
        13.5). La forme brute ``wall_hexes`` (hexes pré-rasterisés, sans ``type``) n'est pas
        classifiable → renvoie [] quand only_type est demandé (pas de repli)."""
        if isinstance(wall_ref, str) and wall_ref.strip() == "random":
            walls_dir = self._resolve_board_dir(scenario_file, board_ref, "random wall_ref") / "walls"
            candidates = sorted(p for p in walls_dir.glob("walls-*.json") if p.stem != "walls-none")
            if not candidates:
                raise FileNotFoundError(f"No walls-*.json files found in {walls_dir} for random wall_ref in scenario {scenario_file}")
            import random as _random
            wall_ref = _random.choice(candidates).stem
        wall_path = self._resolve_shared_config_path("_walls", wall_ref, scenario_file, "wall_ref", board_ref=board_ref)
        # Le rapport fait partie de la CLÉ de cache : `W40K_BOARD_PATH` change en cours de
        # processus (l'API PvP le fait par requête), donc un même fichier peut être servi à deux
        # résolutions. Sans le rapport dans la clé, la seconde recevrait les hexes de la première.
        ratio = self._board_ref_downscale_ratio(scenario_file, board_ref)
        cache_key = f"{wall_path}::x{ratio}" if only_type is None else f"{wall_path}::{only_type}::x{ratio}"
        if cache_key in _walls_json_cache and cache_key in _walls_json_mtime_ns:
            if wall_path.exists():
                try:
                    cur_mtime = wall_path.stat().st_mtime_ns
                except OSError:
                    cur_mtime = None
                if cur_mtime is not None and _walls_json_mtime_ns[cache_key] == cur_mtime:
                    return copy.deepcopy(_walls_json_cache[cache_key])
        if not wall_path.exists():
            raise FileNotFoundError(f"Shared walls file not found for scenario {scenario_file}: {wall_path}")
        try:
            with open(wall_path, "r", encoding="utf-8-sig") as f:
                wall_data = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in shared walls file {wall_path}: {e}")
        if not isinstance(wall_data, dict):
            raise ValueError(f"Shared walls file {wall_path} must be JSON object")
        if "walls" in wall_data:
            walls = require_key(wall_data, "walls")
            if not isinstance(walls, list):
                raise ValueError(f"Shared walls file {wall_path} field 'walls' must be list")
            # Conversion AVANT rasterisation : `hex_line` trace alors la ligne dans la grille
            # cible. Réduire des hexes déjà rasterisés donnerait une ligne à trous.
            walls = self._downscale_terrain_data({"walls": walls}, ratio)["walls"]
            result: List[List[int]] = []
            for gi, g in enumerate(walls):
                if not isinstance(g, dict):
                    raise ValueError(f"Shared walls file {wall_path}: wall group must be dict")
                if only_type is not None and g.get("type") != only_type:
                    continue
                hint = f"Shared walls file {wall_path} group[{gi}]"
                expanded = expand_wall_group_to_hex_list(g, path_hint=hint)
                result.extend(expanded)
            _walls_json_cache[cache_key] = copy.deepcopy(result)
            _walls_json_mtime_ns[cache_key] = wall_path.stat().st_mtime_ns
            return result
        # Forme brute wall_hexes : hexes déjà rasterisés, sans champ 'type' → non classifiable.
        if only_type is not None:
            _walls_json_cache[cache_key] = []
            _walls_json_mtime_ns[cache_key] = wall_path.stat().st_mtime_ns
            return []
        wall_hexes = require_key(wall_data, "wall_hexes")
        if not isinstance(wall_hexes, list):
            raise ValueError(f"Shared walls file {wall_path} field 'wall_hexes' must be list")
        if ratio != 1:
            wall_hexes = self._downscale_terrain_data(
                {"walls": [{"hexes": wall_hexes}]}, ratio
            )["walls"][0]["hexes"]
        _walls_json_cache[cache_key] = copy.deepcopy(wall_hexes)
        _walls_json_mtime_ns[cache_key] = wall_path.stat().st_mtime_ns
        return wall_hexes

    def _downscale_fixed_unit(
        self,
        unit_data: Dict[str, Any],
        ratio: int,
        is_valid_hex: Any,
        wall_hex_set: Any,
        used_hexes: Any,
        max_displacement: int,
        max_spread: int,
        floor_hexes_by_level: Dict[int, Any],
    ) -> Dict[str, Any]:
        """Convertit les positions d'une unité en placement FIXE vers un plateau plus grossier.

        Renvoie une COPIE — `unit_data` peut venir d'un scénario mémoïsé, le muter ferait
        convertir deux fois au chargement suivant.

        Réduire chaque figurine séparément ne suffit pas : cinq subhex d'écart deviennent zéro
        hex, donc les figurines d'une même escouade s'écrasent sur la même case. Chaque figurine
        garde donc sa case réduite si elle est libre, sinon prend la case libre la plus proche,
        dans un rayon borné par `max_displacement` (la portée de cohérence d'escouade : au-delà,
        la figurine ne serait plus dans sa propre unité). Aucune case libre dans ce rayon =
        erreur explicite, jamais un placement silencieusement faux.

        ⚠️ COHERENCY 03.03 PAR CONSTRUCTION : borner le déplacement de CHAQUE figurine par
        `max_displacement` ne suffit pas à rendre la FORMATION cohérente — deux figurines peuvent
        s'écarter de 2 hexes en sens opposés et finir à 4 ou 5 l'une de l'autre. C'est ce qui
        arrivait : l'escouade sortait du chargement déjà incohérente (mesuré : une figurine à 3
        hexes de toutes ses sœurs), et la phase de move refusait ensuite de la déplacer —
        `execute_squad_move` levait « coherency du plan invalide (formation actuelle DEJA
        incoherente) » et le worker de training mourait. C'était le SEUL chemin de placement sans
        contrôle de cohérence (déploiement, move, charge, pile-in et consolidation valident tous).
        Chaque figurine après la première doit donc atterrir à `max_displacement` (= la portée de la
        1re puce) d'une figurine DÉJÀ posée de son escouade : la formation est connexe par
        construction, ce que la FAQ exige (une seule chaîne). La 2e puce (écart max 9") est
        vérifiée en sortie — un roster que la réduction étale au-delà est une donnée à corriger,
        pas un état à livrer en silence.

        L'invariant ancre == models[0] est préservé.

        Les cases retenues sont ajoutées à `used_hexes` : à résolution native rien ne réserve les
        cases PAR FIGURINE (seule l'empreinte de l'ancre l'est), ce qui est sans conséquence là
        où les figurines sont espacées, mais deux escouades voisines se superposeraient ici.
        """
        from engine.hex_utils import downscale_cell, hex_distance

        converted = copy.deepcopy(unit_data)
        unit_id = converted.get("id")

        def _place(
            source_col: int, source_row: int, taken: set, level: int,
            attach_to: Optional[set] = None,
        ) -> Tuple[int, int]:
            """Case réduite pour une figurine. ``attach_to`` (cases déjà posées de l'escouade,
            ``None`` pour la 1re) impose la connexité : la case retenue est à <=
            ``max_displacement`` de l'une d'elles."""
            target_col, target_row = downscale_cell(source_col, source_row, ratio)
            # Une figurine à l'étage doit rester sur un plancher de SON niveau : les sommets des
            # planchers et les positions sont réduits séparément, donc une case tout juste
            # intérieure à x5 peut tomber juste dehors une fois réduite (`floor_height_at` lève).
            allowed_cells = floor_hexes_by_level.get(int(level)) if int(level) > 0 else None
            if int(level) > 0 and not allowed_cells:
                raise ValueError(
                    f"Unit {unit_id}: figurine déclarée au niveau {level} alors qu'aucun plancher "
                    f"de ce niveau n'existe après réduction x{ratio}"
                )
            # Le rayon de recherche s'élargit tant qu'aucune case ne satisfait TOUTES les
            # contraintes (libre + connexe à l'escouade). Élargir déplace une figurine ; ne pas
            # élargir livrerait une formation illégale — le premier est réparable, le second non.
            best: Optional[Tuple[int, int, int, int]] = None
            radius = max_displacement
            while best is None and radius <= max_displacement * 4:
                for col in range(target_col - radius, target_col + radius + 1):
                    for row in range(target_row - radius, target_row + radius + 1):
                        distance = hex_distance(target_col, target_row, col, row)
                        if distance > radius:
                            continue
                        if allowed_cells is not None and (col, row) not in allowed_cells:
                            continue
                        if not is_valid_hex(col, row):
                            continue
                        if wall_hex_set and (col, row) in wall_hex_set:
                            continue
                        if (col, row) in taken or (col, row) in used_hexes:
                            continue
                        # Connexité 03.03 (1re puce) : rattachement à une sœur déjà posée.
                        if attach_to is not None and not any(
                            hex_distance(col, row, ac, ar) <= max_displacement
                            for ac, ar in attach_to
                        ):
                            continue
                        # Tri déterministe : distance, puis colonne, puis ligne.
                        candidate = (distance, col, row, 0)
                        if best is None or candidate[:3] < best[:3]:
                            best = candidate
                radius += max_displacement
            if best is None:
                raise ValueError(
                    f"Unit {unit_id}: figurine en ({source_col},{source_row}) niveau {level} sans "
                    f"case libre ET cohérente (<= {max_displacement} hex d'une sœur déjà posée) "
                    f"autour de ({target_col},{target_row}) après réduction x{ratio} — plateau trop "
                    f"dense ou positions de roster à revoir"
                )
            return best[1], best[2]

        taken: set = set()
        anchor_cell: Optional[Tuple[int, int]] = None
        models = converted.get("models")  # get allowed (escouade mono-figurine : champ absent)
        if isinstance(models, list) and models:
            for index, model in enumerate(models):
                col, row = _place(
                    int(require_key(model, "col")), int(require_key(model, "row")), taken,
                    int(model.get("level", 0)),  # get allowed (champ optionnel : absent = sol)
                    attach_to=(taken if index > 0 else None),
                )
                model["col"], model["row"] = col, row
                taken.add((col, row))
                if index == 0:
                    converted["col"], converted["row"] = col, row
                    anchor_cell = (col, row)
        else:
            col, row = _place(
                int(require_key(converted, "col")), int(require_key(converted, "row")), taken,
                int(converted.get("level", 0)),  # get allowed (champ optionnel : absent = sol)
            )
            converted["col"], converted["row"] = col, row
            taken.add((col, row))
            anchor_cell = (col, row)

        # 2e puce de 03.03 (« à 9" de CHAQUE autre modèle ») : la connexité posée ci-dessus ne la
        # garantit pas — une chaîne de 2 hexes par maillon peut s'étirer au-delà. Un roster que la
        # réduction étale autant est une donnée à corriger, donc erreur explicite et nommée.
        if len(taken) > 1:
            cells = sorted(taken)
            for i, (c1, r1) in enumerate(cells):
                for c2, r2 in cells[i + 1:]:
                    if hex_distance(c1, r1, c2, r2) > max_spread:
                        raise ValueError(
                            f"Unit {unit_id}: après réduction x{ratio}, les figurines ({c1},{r1}) et "
                            f"({c2},{r2}) sont à plus de {max_spread} hex — 2e puce de la coherency "
                            f"03.03 violée. Positions de roster à revoir."
                        )
        # L'ANCRE est laissée à l'appelant : c'est son empreinte (`_compute_deploy_footprint`)
        # qu'il valide puis réserve. La réserver ici la ferait entrer en collision avec elle-même.
        used_hexes.update(taken - {anchor_cell})
        return converted

    def _board_ref_downscale_ratio(self, scenario_file: str, board_ref: Optional[str]) -> int:
        """Rapport d'échelle entre le plateau qui PORTE les données et le plateau ACTIF.

        `board_ref` déclare la résolution native des fichiers partagés (murs, terrain) : ils sont
        écrits en subhex de CE plateau. Le plateau actif (``W40K_BOARD_PATH``) peut être le même
        plateau physique à une résolution plus grossière — c'est le cas d'un bench x1. Le rapport
        est alors `ish_source / ish_actif`, et les coordonnées sont converties au chargement.

        Une seule source de vérité : les fichiers de données restent écrits une fois, à leur
        résolution native. Dupliquer un jeu de terrain par résolution ferait diverger les deux
        copies au premier changement.

        Retourne 1 quand les deux plateaux ont la même résolution (cas PvP/x5 : aucun effet).
        Toute incohérence est une erreur explicite, jamais une conversion approximative.
        """
        from config_loader import get_config_loader

        loader = get_config_loader()
        active_board = loader.get_board_config()
        active_spec = active_board.get("default", active_board)
        active_ish = int(require_key(active_spec, "inches_to_subhex"))
        active_cols, active_rows = loader.get_board_size()

        board_dir = self._resolve_board_dir(scenario_file, board_ref, "board scale")
        source_config_path = board_dir / "board_config.json"
        if not source_config_path.exists():
            raise FileNotFoundError(
                f"Scenario '{scenario_file}' board_ref '{board_ref}' has no board_config.json "
                f"({source_config_path}) — impossible de connaître la résolution native de ses données"
            )
        # Mémoïsé sur (fichier, mtime) : appelé 4 fois par reset (murs, murs denses, aires,
        # zones), soit autant de relectures + parses JSON par épisode sans ce cache. Même
        # invalidation par mtime que le cache de murs, pour rester éditable à chaud.
        source_mtime = source_config_path.stat().st_mtime_ns
        source_cache_key = (str(source_config_path), source_mtime)
        source_board = _board_config_cache.get(source_cache_key)
        if source_board is None:
            with open(source_config_path, "r", encoding="utf-8-sig") as f:
                source_board = json.load(f)
            _board_config_cache[source_cache_key] = source_board
        source_spec = source_board.get("default", source_board)
        source_ish = int(require_key(source_spec, "inches_to_subhex"))
        source_cols = int(require_key(source_spec, "cols"))
        source_rows = int(require_key(source_spec, "rows"))

        if source_ish == active_ish:
            if (source_cols, source_rows) != (active_cols, active_rows):
                raise ValueError(
                    f"Scenario '{scenario_file}': board_ref '{board_ref}' fait "
                    f"{source_cols}x{source_rows} alors que le plateau actif fait "
                    f"{active_cols}x{active_rows} à résolution identique — les données partagées "
                    f"seraient hors plateau"
                )
            return 1

        if active_ish <= 0 or source_ish % active_ish != 0:
            raise ValueError(
                f"Scenario '{scenario_file}': board_ref '{board_ref}' est en subhex x{source_ish}, "
                f"le plateau actif en x{active_ish} — rapport non entier, conversion impossible"
            )
        ratio = source_ish // active_ish
        if (source_cols // ratio, source_rows // ratio) != (active_cols, active_rows):
            raise ValueError(
                f"Scenario '{scenario_file}': board_ref '{board_ref}' ({source_cols}x{source_rows} "
                f"en x{source_ish}) ne se réduit pas au plateau actif ({active_cols}x{active_rows} "
                f"en x{active_ish}) — ce n'est pas le même plateau physique"
            )
        return ratio

    @staticmethod
    def _downscale_terrain_data(terrain_data: Dict[str, Any], ratio: int) -> Dict[str, Any]:
        """Convertit les coordonnées d'un fichier terrain vers un plateau `ratio` fois plus grossier.

        Champs convertis, et EUX SEULS : `terrain[].vertices`, `terrain[].floors[].vertices`,
        `walls[].segments`, `walls[].hexes`, `deployment_zones[].vertices`, `icons[].center`.
        `height_inches` reste en pouces (jamais en subhex). `icons[].size` NON PLUS : c'est une
        taille écran en PIXELS, et un plateau occupe la même surface écran à toutes ses
        résolutions — `hex_radius` et `margin` sont multipliés par le rapport exactement là où
        `cols`/`rows` sont divisés (x5 : 220 cases à 2.78 px ; x1 : 44 à 13.9 px, ~917 px dans les
        deux cas). Le rayon d'hex COMPENSE déjà le changement de résolution, il ne s'y ajoute pas :
        multiplier `size` rendait les icônes du plateau x1 cinq fois trop grandes. C'est la même
        invariance qui rend l'habillage des murs correct sans conversion — il se dimensionne sur
        `HEX_HEIGHT` (`BoardDisplay.tsx`, `halfW`), pas sur une valeur du fichier terrain.

        Un segment dont les deux extrémités se rejoignent après conversion reste un segment :
        `hex_line` le rend en une case, donc le mur devient un hex au lieu de disparaître.

        Toutes ces coordonnées sont des INDICES DE CELLULE — la rasterisation des polygones
        projette elle aussi ses sommets avec `_hex_projected`. La conversion passe donc par
        `downscale_cell`, qui tient compte du décalage des colonnes impaires ; diviser col et row
        séparément déplacerait un point sur quatre d'une case.
        """
        if ratio == 1:
            return terrain_data

        from engine.hex_utils import downscale_cell

        def _pt(p: Any) -> List[int]:
            col, row = downscale_cell(int(p[0]), int(p[1]), ratio)
            return [col, row]

        scaled = copy.deepcopy(terrain_data)
        for area in scaled.get("terrain", []):  # get allowed
            if not isinstance(area, dict):
                continue
            if isinstance(area.get("vertices"), list):
                area["vertices"] = [_pt(v) for v in area["vertices"]]
            # get allowed : section OPTIONNELLE du terrain (mesure 2026-07-27 : aucune aire sur
            # 15 n'en porte dans terrain-train-01/02/03, 5 sur 15 dans mc1). Absence = terrain
            # sans etage, pas une donnee manquante — meme lecture qu'a la L659.
            for floor in area.get("floors", []) or []:  # get allowed
                if isinstance(floor, dict) and isinstance(floor.get("vertices"), list):
                    floor["vertices"] = [_pt(v) for v in floor["vertices"]]
        for group in scaled.get("walls", []):  # get allowed
            if not isinstance(group, dict):
                continue
            if isinstance(group.get("segments"), list):
                group["segments"] = [[_pt(seg[0]), _pt(seg[1])] for seg in group["segments"]]
            if isinstance(group.get("hexes"), list):
                group["hexes"] = [_pt(h) for h in group["hexes"]]
        # get allowed : section OPTIONNELLE (absente de terrain_obscuring_fixture.json).
        for zone in scaled.get("deployment_zones", []) or []:  # get allowed
            if isinstance(zone, dict) and isinstance(zone.get("vertices"), list):
                zone["vertices"] = [_pt(v) for v in zone["vertices"]]
        # get allowed : section OPTIONNELLE, purement decorative.
        for icon in scaled.get("icons", []) or []:  # get allowed
            if not isinstance(icon, dict):
                continue
            if isinstance(icon.get("center"), list):
                icon["center"] = _pt(icon["center"])
        return scaled

    def _read_terrain_file(
        self, terrain_ref: str, scenario_file: str, board_ref: Optional[str] = None
    ) -> Tuple[Dict[str, Any], Path]:
        """Resolve and parse the terrain JSON file referenced by terrain_ref. Returns (data, path).

        Les coordonnées sont converties vers la résolution du plateau ACTIF si celui-ci est plus
        grossier que le plateau qui porte le fichier (cf. `_board_ref_downscale_ratio`). Point de
        passage unique des trois lecteurs de terrain (murs, zones de déploiement, aires).
        """
        terrain_path = self._resolve_board_dir(scenario_file, board_ref, "terrain_ref") / "terrain" / terrain_ref
        if not terrain_path.exists():
            raise FileNotFoundError(f"Terrain file not found for scenario {scenario_file}: {terrain_path}")
        try:
            with open(terrain_path, "r", encoding="utf-8-sig") as f:
                terrain_data = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in terrain file {terrain_path}: {e}")
        ratio = self._board_ref_downscale_ratio(scenario_file, board_ref)
        return self._downscale_terrain_data(terrain_data, ratio), terrain_path

    def _load_terrain_walls_from_ref(
        self, terrain_ref: str, scenario_file: str, only_type: Optional[str] = None,
        board_ref: Optional[str] = None,
    ) -> List[List[int]]:
        """Load wall hexes from the 'walls' section of a terrain file referenced by terrain_ref.

        ``only_type`` (ex: "dense") restreint aux groupes de murs de ce type (champ ``type`` du
        groupe) — sert à construire le set Solid/dense de la règle 13.5. None = tous les murs."""
        terrain_data, terrain_path = self._read_terrain_file(terrain_ref, scenario_file, board_ref)
        result: List[List[int]] = []
        for gi, g in enumerate(terrain_data.get("walls", [])):  # get allowed
            if not isinstance(g, dict):
                continue
            if only_type is not None and g.get("type") != only_type:
                continue
            hint = f"Terrain file {terrain_path} walls[{gi}]"
            result.extend(expand_wall_group_to_hex_list(g, path_hint=hint))
        return result

    def _load_deployment_zones_from_ref(
        self, terrain_ref: str, scenario_file: str, board_ref: Optional[str] = None
    ) -> Optional[List[Dict[str, Any]]]:
        """Load the 'deployment_zones' section of a terrain file, or None if absent.

        Returns the raw list of zone dicts ({id, name, shape:"polygon", vertices, ...}). The geometry
        is rasterized to per-player deploy pools later (needs board cols/rows). Returns None when the
        terrain has no 'deployment_zones' key — those scenarios fall back to config/deployment/ (legacy).
        """
        terrain_data, terrain_path = self._read_terrain_file(terrain_ref, scenario_file, board_ref)
        if "deployment_zones" not in terrain_data:
            return None
        zones = terrain_data["deployment_zones"]
        if not isinstance(zones, list) or not zones:
            raise ValueError(f"Terrain file {terrain_path}: 'deployment_zones' must be a non-empty list")
        return zones

    def _load_terrain_areas_from_ref(
        self, terrain_ref: str, scenario_file: str, board_ref: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Load polygon terrain areas from the 'terrain' section of a terrain file referenced by terrain_ref.

        Only 'polygon' shapes are kept (lines like deployment markers are excluded). Each area is
        {id, obscuring, polygon_vertices, hexes}; vertices stay in col/row sub-hex space and `hexes`
        is the rasterized set of occupied board hexes (same odd-q projection as objectives/renderer).
        """
        from config_loader import get_config_loader
        cols, rows = get_config_loader().get_board_size()
        terrain_data, terrain_path = self._read_terrain_file(terrain_ref, scenario_file, board_ref)
        areas: List[Dict[str, Any]] = []
        for ai, area in enumerate(terrain_data.get("terrain", [])):  # get allowed
            if not isinstance(area, dict):
                continue
            if area.get("shape") != "polygon":
                continue
            hint = f"Terrain file {terrain_path} terrain[{ai}]"
            area_id = require_key(area, "id")
            vertices = require_key(area, "vertices")
            if not isinstance(vertices, list) or len(vertices) < 3:
                raise ValueError(f"{hint}: polygon 'vertices' must be a list of >= 3 points, got {vertices!r}")
            poly = [[int(v[0]), int(v[1])] for v in vertices]
            areas.append({
                "id": area_id,
                "name": area.get("name", area_id),
                "obscuring": bool(area.get("obscuring", False)),
                "objective": bool(area.get("objective", False)),
                "polygon_vertices": poly,
                "hexes": polygon_to_hex_list(poly, cols, rows),
                "floors": self._parse_terrain_floors(area, area_id, hint, cols, rows),
            })
        return areas

    def _parse_terrain_floors(
        self, area: Dict[str, Any], area_id: Any, hint: str, cols: int, rows: int
    ) -> List[Dict[str, Any]]:
        """Parse the optional 'floors' sub-list of a terrain area (multi-level ruins, format B).

        Absence of 'floors' = ground-level-only terrain (valid business case, not an error) -> [].
        When present, each floor is strictly validated and rasterized:
          {level:int>=1, height_inches:float>0, polygon_vertices:[[col,row]], hexes:[[col,row]]}.
        `level`/`height_inches` back the rules thresholds (3" Solid/Plunging, 5" vertical).
        """
        raw_floors = area.get("floors")
        if raw_floors is None:
            return []
        if not isinstance(raw_floors, list):
            raise ValueError(f"{hint} ('{area_id}'): 'floors' must be a list, got {raw_floors!r}")
        floors: List[Dict[str, Any]] = []
        for fi, floor in enumerate(raw_floors):
            fhint = f"{hint} ('{area_id}') floors[{fi}]"
            if not isinstance(floor, dict):
                raise ValueError(f"{fhint}: must be an object, got {type(floor).__name__}")
            level = require_key(floor, "level")
            if not isinstance(level, int) or isinstance(level, bool) or level < 1:
                raise ValueError(f"{fhint}: 'level' must be an int >= 1 (0 = ground), got {level!r}")
            height = require_key(floor, "height_inches")
            if not isinstance(height, (int, float)) or isinstance(height, bool) or height <= 0:
                raise ValueError(f"{fhint}: 'height_inches' must be a number > 0, got {height!r}")
            fvertices = require_key(floor, "vertices")
            if not isinstance(fvertices, list) or len(fvertices) < 3:
                raise ValueError(f"{fhint}: 'vertices' must be a list of >= 3 points, got {fvertices!r}")
            fpoly = [[int(v[0]), int(v[1])] for v in fvertices]
            floors.append({
                "level": level,
                "height_inches": float(height),
                "polygon_vertices": fpoly,
                "hexes": polygon_to_hex_list(fpoly, cols, rows),
            })
        floors.sort(key=lambda f: f["level"])
        return floors

    @staticmethod
    def _has_declared_source_board(scenario_file: str, board_ref: Optional[str]) -> bool:
        """Le scénario déclare-t-il le plateau dans lequel ses coordonnées sont écrites ?

        Deux déclarations équivalentes, les mêmes que celles de `_resolve_board_dir` :
        la clé `board_ref`, ou l'appartenance à `config/board/<board>/scenario/`. Sans l'une des
        deux, il n'y a pas d'échelle d'origine connue — donc rien à convertir.

        Prédicat séparé pour que la règle vive à UN endroit : `_resolve_board_dir` lève quand
        aucune déclaration n'existe, ce qui ne convient pas pour un simple test d'applicabilité.
        """
        if board_ref is not None:
            return True
        return Path(scenario_file).parent.name == "scenario"

    def _resolve_board_dir(
        self, scenario_file: str, board_ref: Optional[str], purpose: str
    ) -> Path:
        """Resolve the board directory backing a scenario's shared config refs (walls/terrain).

        Deux formes acceptées (V11 T4, décision de design n°4), sans repli implicite :
          - le scénario est dans 'config/board/<board>/scenario/' → dossier board parent (PvP, inchangé) ;
          - le scénario déclare 'board_ref' → 'config/board/<board_ref>/' (banque par-agent).
        Absence des deux OU board_ref pointant un dossier absent = erreur explicite."""
        project_root = Path(__file__).resolve().parent.parent
        if board_ref is not None:
            if not isinstance(board_ref, str) or not board_ref.strip():
                raise ValueError(
                    f"Scenario '{scenario_file}' has invalid 'board_ref': {board_ref!r}"
                )
            normalized = board_ref.strip().replace("\\", "/")
            if (
                normalized.startswith("/")
                or ".." in normalized.split("/")
                or "/" in normalized
            ):
                raise ValueError(
                    f"Scenario '{scenario_file}' has unsafe 'board_ref' (board name only): {board_ref!r}"
                )
            board_dir = project_root / "config" / "board" / normalized
            if not board_dir.is_dir():
                raise FileNotFoundError(
                    f"Scenario '{scenario_file}' board_ref '{normalized}' -> board directory not found: "
                    f"{board_dir} (needed to resolve {purpose})"
                )
            return board_dir
        scenario_parent = Path(scenario_file).parent
        if scenario_parent.name == "scenario":
            return project_root / scenario_parent.parent
        raise ValueError(
            f"Scenario '{scenario_file}' must either be located in a 'config/board/<board>/scenario/' "
            f"directory OR declare a 'board_ref' key to resolve {purpose}, got parent: '{scenario_parent}'"
        )

    def _resolve_shared_config_path(
        self,
        shared_dir_name: str,
        raw_ref: Any,
        scenario_file: str,
        field_name: str,
        board_ref: Optional[str] = None,
    ) -> Path:
        """Resolve shared config path. _walls -> config/board/<board>/walls/, _objectives -> .../objectives/, else config/agents/<shared_dir_name>/. Board dir via _resolve_board_dir (scenario/ parent OU board_ref)."""
        if not isinstance(raw_ref, str) or not raw_ref.strip():
            raise ValueError(
                f"Scenario '{scenario_file}' has invalid '{field_name}': {raw_ref!r}"
            )
        normalized = raw_ref.strip().replace("\\", "/")
        if normalized.startswith("/") or normalized.startswith("../") or "/../" in normalized:
            raise ValueError(
                f"Scenario '{scenario_file}' has unsafe '{field_name}': {normalized}"
            )
        if "/" in normalized:
            raise ValueError(
                f"Scenario '{scenario_file}' field '{field_name}' must be filename only under {shared_dir_name}, got: {normalized}"
            )
        if not normalized.endswith(".json"):
            normalized = f"{normalized}.json"

        project_root = Path(__file__).resolve().parent.parent
        if shared_dir_name == "_walls":
            return self._resolve_board_dir(scenario_file, board_ref, "wall_ref") / "walls" / normalized
        if shared_dir_name == "_objectives":
            return self._resolve_board_dir(scenario_file, board_ref, "objectives") / "objectives" / normalized
        return project_root / "config" / "agents" / shared_dir_name / normalized

    def _resolve_deployment_type_by_player(self, scenario_data: Dict[str, Any]) -> Dict[int, str]:
        """Résout le type de déploiement effectif de chaque joueur.

        'deployment_type' est le défaut du scénario ('fixed' si absent) ; les clés
        'deployment_type_P1'/'deployment_type_P2' le surchargent par joueur. Source
        unique partagée par le chargement de scénario et l'expansion des rosters
        compacts (qui doit connaître le mode AVANT de construire les figurines).
        """
        base_type = (
            require_key(scenario_data, "deployment_type")
            if "deployment_type" in scenario_data
            else "fixed"
        )
        return {
            1: (
                require_key(scenario_data, "deployment_type_P1")
                if "deployment_type_P1" in scenario_data
                else base_type
            ),
            2: (
                require_key(scenario_data, "deployment_type_P2")
                if "deployment_type_P2" in scenario_data
                else base_type
            ),
        }

    def _load_compact_roster_file(self, roster_path: Path, roster_label: str) -> Dict[str, Any]:
        """Load and validate compact roster JSON file."""
        if not roster_path.exists():
            raise FileNotFoundError(f"{roster_label} roster file not found: {roster_path}")
        _abs_rp = str(roster_path.resolve())
        if _abs_rp in _roster_json_cache:
            return copy.deepcopy(_roster_json_cache[_abs_rp])
        try:
            with open(roster_path, "r", encoding="utf-8-sig") as f:
                roster_data = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in {roster_label} roster file {roster_path}: {e}")
        if not isinstance(roster_data, dict):
            raise ValueError(
                f"{roster_label} roster file {roster_path} must be JSON object, got {type(roster_data).__name__}"
            )
        require_key(roster_data, "roster_id")
        # Faction d'Armée (08.04) : elle appartient à la LISTE, pas au scénario. Un scénario
        # d'entraînement tire ses rosters au sort à chaque épisode (`agent_roster_ref:
        # "training_random"`) : une déclaration au niveau du scénario décrirait donc l'armée
        # d'un autre épisode. Exigée ici, à la lecture du fichier qui la porte.
        army_faction_declared = require_key(roster_data, "army_faction")
        if not isinstance(army_faction_declared, str) or not army_faction_declared.strip():
            raise ValueError(
                f"{roster_label} roster {roster_path} must define 'army_faction' as a non-empty "
                f"faction keyword (e.g. \"ORKS\"), got {army_faction_declared!r}"
            )
        composition = require_key(roster_data, "composition")
        if not isinstance(composition, list) or not composition:
            raise ValueError(f"{roster_label} roster {roster_path} must define non-empty 'composition' list")
        _roster_json_cache[_abs_rp] = copy.deepcopy(roster_data)
        return roster_data

    def _expand_compact_roster_to_basic_units(
        self,
        roster_data: Dict[str, Any],
        player: int,
        id_start: int,
        roster_path: str,
        deployment_type: str
    ) -> List[Dict[str, Any]]:
        """Expand compact composition format to basic unit entries.

        Une entrée de composition décrit ``count`` escouades identiques. Le nombre de
        figurines par escouade se déclare par l'un des deux champs OPTIONNELS et
        MUTUELLEMENT EXCLUSIFS suivants (aucun des deux = escouade mono-figurine) :
          - ``models_per_unit`` (int >= 1) : escouade homogène ;
          - ``models`` (liste de unit_type) : escouade hétérogène, une entrée par
            figurine (sergent, arme spéciale, personnage attaché — règle 19.01).
        Les deux exigent un déploiement 'active' : un roster compact ne porte aucune
        coordonnée, or hors 'active' _build_enhanced_unit exige col/row par figurine.
        """
        composition = require_key(roster_data, "composition")
        if not isinstance(composition, list):
            raise ValueError(f"Roster {roster_path} field 'composition' must be list")

        next_id = id_start
        expanded_units: List[Dict[str, Any]] = []
        for idx, comp_entry in enumerate(composition):
            if not isinstance(comp_entry, dict):
                raise ValueError(
                    f"Roster {roster_path} composition[{idx}] must be object, got {type(comp_entry).__name__}"
                )
            unit_type = require_key(comp_entry, "unit_type")
            count = require_key(comp_entry, "count")
            # 20.01 — mise en réserve DÉCLARÉE par la liste. Optionnel (absent = déployée
            # normalement) ; c'est le seul champ de roster de ce chantier. Le choix DYNAMIQUE
            # (l'agent décide au déploiement) passe, lui, par `place_unit_in_strategic_reserves`.
            in_reserves = comp_entry.get("strategic_reserves", False)  # get allowed (champ optionnel)
            if not isinstance(in_reserves, bool):
                raise ValueError(
                    f"Roster {roster_path} composition[{idx}].strategic_reserves must be bool, "
                    f"got {in_reserves!r}"
                )
            if not isinstance(unit_type, str) or not unit_type.strip():
                raise ValueError(
                    f"Roster {roster_path} composition[{idx}].unit_type must be non-empty string"
                )
            if not isinstance(count, int) or isinstance(count, bool) or count <= 0:
                raise ValueError(
                    f"Roster {roster_path} composition[{idx}].count must be positive int, got {count!r}"
                )

            has_models_per_unit = "models_per_unit" in comp_entry
            has_models = "models" in comp_entry
            if has_models_per_unit and has_models:
                raise ValueError(
                    f"Roster {roster_path} composition[{idx}] cannot define both "
                    f"'models_per_unit' and 'models' (mutually exclusive)"
                )

            model_specs: Optional[List[Dict[str, Any]]] = None
            # Positions par figurine (mode 'fixed'/strict) : parallèle à model_specs, chaque entrée
            # = {'top': (col,row,level), 'bottom': (col,row,level)} ou None. Une escouade positionnée
            # porte les DEUX côtés (top=joueur 1, bottom=joueur 2) car le siège est aléatoire.
            model_positions: Optional[List[Optional[Dict[str, Tuple[int, int, int]]]]] = None
            # Même liste que ``model_positions``, mais renseignée UNIQUEMENT quand TOUTES les
            # figurines portent leurs deux côtés : c'est la seule forme consommée par le placement
            # ci-dessous (plus aucune entrée None à retester).
            declared_model_positions: Optional[List[Dict[str, Tuple[int, int, int]]]] = None
            if has_models_per_unit:
                models_per_unit = comp_entry["models_per_unit"]
                if (
                    not isinstance(models_per_unit, int)
                    or isinstance(models_per_unit, bool)
                    or models_per_unit <= 0
                ):
                    raise ValueError(
                        f"Roster {roster_path} composition[{idx}].models_per_unit must be "
                        f"positive int, got {models_per_unit!r}"
                    )
                # Escouade homogène : pas d'override par figurine, les figurines
                # héritent des stats de l'unit_type de l'escouade. Pas de positions (active seul).
                model_specs = [{} for _ in range(models_per_unit)]
            elif has_models:
                raw_models = comp_entry["models"]
                if not isinstance(raw_models, list) or not raw_models:
                    raise ValueError(
                        f"Roster {roster_path} composition[{idx}].models must be a non-empty list "
                        f"of unit_type strings or per-model objects"
                    )
                model_specs = []
                model_positions = []
                for m_idx, spec in enumerate(raw_models):
                    if isinstance(spec, str):
                        # Forme historique : type seul, aucune position (déploiement 'active' requis).
                        if not spec.strip():
                            raise ValueError(
                                f"Roster {roster_path} composition[{idx}].models[{m_idx}] must be "
                                f"non-empty string, got {spec!r}"
                            )
                        model_specs.append({"unit_type": spec.strip()})
                        model_positions.append(None)
                    elif isinstance(spec, dict):
                        # Forme positionnée : {unit_type, top:{col,row[,level]}, bottom:{...}}.
                        mt = require_key(spec, "unit_type")
                        if not isinstance(mt, str) or not mt.strip():
                            raise ValueError(
                                f"Roster {roster_path} composition[{idx}].models[{m_idx}].unit_type "
                                f"must be non-empty string, got {mt!r}"
                            )
                        model_specs.append({"unit_type": mt.strip()})
                        has_top = "top" in spec
                        has_bottom = "bottom" in spec
                        if not has_top and not has_bottom:
                            model_positions.append(None)
                        elif has_top and has_bottom:
                            model_positions.append({
                                "top": self._parse_roster_model_side(
                                    spec["top"], roster_path, idx, m_idx, "top"
                                ),
                                "bottom": self._parse_roster_model_side(
                                    spec["bottom"], roster_path, idx, m_idx, "bottom"
                                ),
                            })
                        else:
                            raise ValueError(
                                f"Roster {roster_path} composition[{idx}].models[{m_idx}] must "
                                f"declare BOTH 'top' and 'bottom' positions (or neither)"
                            )
                    else:
                        raise ValueError(
                            f"Roster {roster_path} composition[{idx}].models[{m_idx}] must be a "
                            f"unit_type string or an object {{unit_type, top, bottom}}, "
                            f"got {type(spec).__name__}"
                        )
                pos_flags = [p is not None for p in model_positions]
                if any(pos_flags) and not all(pos_flags):
                    raise ValueError(
                        f"Roster {roster_path} composition[{idx}].models mixes positioned and "
                        f"unpositioned figurines — declare top/bottom on ALL figurines or NONE"
                    )
                if pos_flags and all(pos_flags):
                    declared_model_positions = [p for p in model_positions if p is not None]

            if model_specs is not None and deployment_type != "active":
                # Hors 'active', une escouade multi-figurines DOIT porter des positions par figurine
                # (top/bottom) — sinon _build_enhanced_unit exigerait col/row absents. Pas de fallback.
                if declared_model_positions is None:
                    raise ValueError(
                        f"Roster {roster_path} composition[{idx}] declares a multi-model squad but "
                        f"player {player} deployment type is '{deployment_type}': déclare des positions "
                        f"par figurine (top/bottom) ou utilise le déploiement 'active'"
                    )
                if count != 1:
                    raise ValueError(
                        f"Roster {roster_path} composition[{idx}]: une escouade positionnée exige "
                        f"count == 1 (got {count})"
                    )
                # Sélection du côté selon le joueur assigné (convention : P1=top, P2=bottom).
                side = "top" if int(player) == 1 else "bottom"
                placed_models: List[Dict[str, Any]] = []
                for base_spec, pos in zip(model_specs, declared_model_positions):
                    p_col, p_row, p_level = pos[side]
                    placed = {"unit_type": base_spec["unit_type"], "col": p_col, "row": p_row}
                    if p_level:
                        placed["level"] = p_level
                    placed_models.append(placed)
                unit_entry = {
                    "id": next_id,
                    "player": player,
                    "unit_type": unit_type.strip(),
                    "col": placed_models[0]["col"],
                    "row": placed_models[0]["row"],
                    "models": placed_models,
                }
                if in_reserves:
                    unit_entry["strategic_reserves"] = True
                expanded_units.append(unit_entry)
                next_id += 1
                continue

            # Déploiement 'active' (positions ignorées : roster à double usage) ou mono-figurine.
            emit_models: Optional[List[Dict[str, Any]]] = None
            if model_specs is not None:
                emit_models = [
                    {"unit_type": s["unit_type"]} if "unit_type" in s else {}
                    for s in model_specs
                ]
            # Unité mono-figurine (ni 'models' ni 'models_per_unit') en mode 'fixed' : elle porte
            # ses positions au NIVEAU DE L'ENTRÉE (top/bottom), pour ne pas la transformer en
            # escouade (comportement 'active' des véhicules/persos préservé à l'identique).
            mono_pos: Optional[Tuple[int, int, int]] = None
            if model_specs is None and deployment_type != "active":
                has_top = "top" in comp_entry
                has_bottom = "bottom" in comp_entry
                if not (has_top and has_bottom):
                    raise ValueError(
                        f"Roster {roster_path} composition[{idx}] (unité mono '{unit_type}') en "
                        f"déploiement '{deployment_type}' exige des positions 'top' ET 'bottom' au "
                        f"niveau de l'entrée, ou le déploiement 'active'"
                    )
                if count != 1:
                    raise ValueError(
                        f"Roster {roster_path} composition[{idx}]: une unité positionnée exige "
                        f"count == 1 (got {count})"
                    )
                side = "top" if int(player) == 1 else "bottom"
                mono_pos = self._parse_roster_model_side(
                    comp_entry[side], roster_path, idx, 0, side
                )
            for _ in range(count):
                unit_entry = {
                    "id": next_id,
                    "player": player,
                    "unit_type": unit_type.strip(),
                }
                if in_reserves:
                    unit_entry["strategic_reserves"] = True
                if emit_models is not None:
                    unit_entry["models"] = copy.deepcopy(emit_models)
                if mono_pos is not None:
                    unit_entry["col"] = mono_pos[0]
                    unit_entry["row"] = mono_pos[1]
                    if mono_pos[2]:
                        unit_entry["level"] = mono_pos[2]
                expanded_units.append(unit_entry)
                next_id += 1
        return expanded_units

    def _parse_roster_model_side(
        self, side_spec: Any, roster_path: str, comp_idx: int, model_idx: int, side_name: str
    ) -> Tuple[int, int, int]:
        """Valide et normalise une position de côté ``{col, row[, level]}`` d'un modèle de roster.

        Retourne ``(col, row, level)``. ``level`` optionnel (défaut 0). Aucun fallback : toute
        clé manquante/invalide est une erreur explicite.
        """
        hint = f"Roster {roster_path} composition[{comp_idx}].models[{model_idx}].{side_name}"
        if not isinstance(side_spec, dict):
            raise ValueError(f"{hint} must be an object {{col, row[, level]}}, got {type(side_spec).__name__}")
        col = require_key(side_spec, "col")
        row = require_key(side_spec, "row")
        if not isinstance(col, int) or isinstance(col, bool):
            raise ValueError(f"{hint}.col must be int, got {col!r}")
        if not isinstance(row, int) or isinstance(row, bool):
            raise ValueError(f"{hint}.row must be int, got {row!r}")
        level = side_spec.get("level", 0)  # get allowed (champ optionnel : sol par défaut)
        if not isinstance(level, int) or isinstance(level, bool) or level < 0:
            raise ValueError(f"{hint}.level must be a non-negative int, got {level!r}")
        return int(col), int(row), int(level)
    
    # ============================================================================
    # UTILITIES
    # ============================================================================

    def get_unit_by_id(self, unit_id: str, game_state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Get unit by ID from game state.

        CRITICAL: Compare both sides as strings to handle int/string ID mismatches.
        """
        for unit in game_state["units"]:
            if str(unit["id"]) == str(unit_id):
                return unit
        return None

    # ============================================================================
    # OBJECTIVE CONTROL SYSTEM
    # ============================================================================

    def _sum_objective_control_oc(
        self, game_state: Dict[str, Any], hex_set: Set[Tuple[int, int]]
    ) -> Tuple[int, int]:
        """Rule 14.02 (voir ``sum_objective_control_oc``, source unique module-level)."""
        return sum_objective_control_oc(game_state, hex_set)

    def calculate_objective_control(self, game_state: Dict[str, Any]) -> Dict[int, Dict[str, Any]]:
        """
        Calculate objective control for each objective with configured control method.

        Win condition: Control more objectives than opponent at end of turn 5.
        Control rules:
        - To CAPTURE an objective: Your OC sum must be > opponent's OC sum
        - control_method == "secured" (Rule 14.03): keep control until opponent captures
        - control_method == "default" (Rule 14.02): control only while holding strictly greater OC
        - Equal OC = current controller keeps control (secured) or stays neutral (default)

        Returns:
            Dict[objective_id, {
                'player_1_oc': int,  # Total OC for player 1
                'player_2_oc': int,  # Total OC for player 2
                'controller': int|None  # 1, 2, or None (contested/uncontrolled)
            }]
        """
        objectives = require_key(game_state, "objectives")
        if not objectives:
            return {}

        primary_objective = require_key(game_state, "primary_objective")
        if primary_objective is None:
            raise ValueError("primary_objective is required to calculate objective control")
        if isinstance(primary_objective, list):
            if not primary_objective:
                raise ValueError("primary_objective list cannot be empty for objective control")
            primary_configs = primary_objective
        else:
            primary_configs = [primary_objective]

        control_method: Optional[str] = None
        for objective_cfg in primary_configs:
            if not isinstance(objective_cfg, dict):
                raise TypeError("primary_objective entry must be a dict for objective control")
            control_cfg = require_key(objective_cfg, "control")
            method = require_key(control_cfg, "method")
            if method != "oc_sum_greater":
                raise ValueError(f"Unsupported primary objective control method: {method}")
            current_control_method = require_key(control_cfg, "control_method")
            if current_control_method not in ("secured", "default"):
                raise ValueError(f"Unsupported control_method: {current_control_method}")
            tie_behavior = require_key(control_cfg, "tie_behavior")
            if tie_behavior != "no_control":
                raise ValueError(f"Unsupported primary objective tie_behavior: {tie_behavior}")
            if control_method is None:
                control_method = current_control_method
            elif control_method != current_control_method:
                raise ValueError("primary_objective control_method must be consistent across configs")

        if control_method is None:
            raise ValueError("control_method is required to calculate objective control")

        # Get persistent control state (initialize if not present)
        if "objective_controllers" not in game_state:
            game_state["objective_controllers"] = {}

        result = {}

        # UNE passe d'empreintes pour TOUS les objectifs (au lieu d'une par objectif) : le scan
        # de socle est le poste dominant de ce calcul, et il est identique d'une zone à l'autre.
        # Parseur commun : ce site indexait `h[0]/h[1]` en dur, donc il REJETAIT la forme
        # {"col","row"} que le reste du moteur accepte — une meme donnee etait lisible par la
        # regle 14.02 et par les bots, et levait ici, dans le scoring des VP.
        hex_sets = objective_hex_sets(game_state)
        oc_sums = sum_objective_control_oc_multi(game_state, hex_sets)

        for obj_index, objective in enumerate(objectives):
            obj_id = objective["id"]
            obj_id_key = str(obj_id)

            # Rule 14.02 : somme des OC des figurines dont l'empreinte de socle RECOUVRE la
            # zone (un hexe commun suffit — ce n'est PAS un test sur le centre du socle),
            # figurines mortes exclues. Les unites battle-shocked n'y contribuent rien :
            # 01.07 met l'OC de toutes leurs figurines a '-' (02.02). Detail dans
            # ``sum_objective_control_oc``, seule implementation.
            player_1_oc, player_2_oc = oc_sums[obj_index]

            # Get current controller from persistent state; explicit init when first seeing this objective
            if obj_id_key not in game_state["objective_controllers"]:
                game_state["objective_controllers"][obj_id_key] = None
            current_controller = game_state["objective_controllers"][obj_id_key]

            # Primitive E (chantier 06) : un objectif peut être sécurisé par une unité
            # portant `secure_objective_on_control` (Get da Good Bitz / Objective Secured),
            # indépendamment du control_method global. Si l'objectif est sécurisé pour le
            # contrôleur courant, l'adversaire doit avoir STRICTEMENT plus d'OC pour le reprendre.
            obj_secured_by = game_state.get("secured_objectives", {}).get(obj_id_key)
            new_controller, _should_clear = _resolve_objective_controller(
                player_1_oc, player_2_oc, current_controller, obj_secured_by, control_method
            )
            # Cleared when captured by the opponent (la capacité de sécurisation de l'adversaire
            # sera réévaluée à sa prochaine fin de phase de commandement).
            if _should_clear:
                game_state["secured_objectives"].pop(obj_id_key, None)

            # Update persistent state
            game_state["objective_controllers"][obj_id_key] = new_controller

            result[obj_id] = {
                "player_1_oc": player_1_oc,
                "player_2_oc": player_2_oc,
                "controller": new_controller,
                # Contrôleur AVANT ce checkpoint : c'est lui qui distingue « capturé maintenant »
                # de « déjà tenu », et en méthode `secured` il explique une égalité d'OC qui ne
                # change rien (14.03). Le journal de partie s'appuie dessus.
                "previous_controller": current_controller,
            }

        # Détail du DERNIER checkpoint, gardé pour le journal de partie (14.02) : sans lui,
        # `objective_controllers` ne dit QUE le vainqueur, jamais pourquoi — un joueur posé sur un
        # objectif qu'il ne prend pas n'a aucun moyen de savoir s'il est contesté, battle-shocked
        # (01.07 : OC à '-') ou hors zone. Écriture O(nb_objectifs), sans coût en entraînement.
        game_state["_objective_control_detail"] = result

        return result

    def run_objective_control_checkpoint(
        self,
        game_state: Dict[str, Any],
        old_phase: Optional[str],
        new_phase: Optional[str],
        turn_changed: bool,
    ) -> bool:
        """
        Rule 14.02: objective control is determined at the END of each phase and turn.

        A phase boundary ``old_phase`` -> ``new_phase`` is simultaneously the END of
        ``old_phase`` and the START of ``new_phase`` (no game state changes in between).
        ``game_config.json['objective_control_check']['points']`` lists the (phase, moment)
        points at which control must be (re)evaluated; when one matches this boundary we
        call ``calculate_objective_control``, which refreshes the persistent
        ``objective_controllers`` used for both display and scoring.

        No-op when no listed point matches this boundary.

        Retourne True SI la détermination a réellement eu lieu. C'est ce que lit
        ``refresh_objective_control_on_boundary`` pour s'arrêter à la PREMIÈRE frontière qui
        tire : rejouer la détermination sur un état identique écraserait le
        ``previous_controller`` du détail par le contrôleur qu'on vient d'écrire.

        La section est OBLIGATOIRE (`require_key`, cf.
        `config_loader.GAME_CONFIG_SECTIONS_REQUIRED_BY_ENGINE`) : elle etait auparavant lue en
        `.get()`, si bien qu'un constructeur de config qui l'oubliait eteignait la regle 14.02
        sans lever — ce qui est arrive au chemin d'entrainement. Meme regime d'erreur que la
        section `move` (`movement_handlers._get_move_traversal_rules`).
        """
        check_cfg = require_key(self.config, "objective_control_check")
        points = require_key(check_cfg, "points")

        def _match(phase: Optional[str], moment: str) -> bool:
            return any(p.get("phase") == phase and p.get("moment") == moment for p in points)

        fire = _match(old_phase, "end") or _match(new_phase, "start")
        if turn_changed:
            fire = fire or _match("turn", "end")
        if not fire:
            return False
        if not (
            game_state.get("objectives")
            and game_state.get("primary_objective") is not None
            and game_state.get("units_cache")
        ):
            return False
        self.calculate_objective_control(game_state)
        return True

    def refresh_objective_control_on_boundary(self, game_state: Dict[str, Any]) -> bool:
        """Réévalue le contrôle d'objectif SI une frontière de phase/tour vient d'être franchie.

        Règle 14.02 : le contrôle est déterminé à la FIN de chaque phase et de chaque tour, pas
        en continu. Cette méthode est le point d'entrée unique de ce rafraîchissement.

        Partagée par les DEUX chemins : le moteur gym (``W40KEngine.step``/``reset``) et l'API
        PvP (sérialisation d'état). Avant, seul le PvP déclenchait le checkpoint : en
        entraînement ``objective_controllers`` n'était jamais rafraîchi, donc le contrôle
        d'objectif restait figé sur son état initial.

        ⚠️ CHAQUE FRONTIÈRE FRANCHIE EST SOLDÉE, PAS SEULEMENT LES DEUX EXTRÉMITÉS. Cette
        méthode n'observe l'état que par intermittence (une fois par step moteur, une fois par
        sérialisation d'API), alors que ``execute_semantic_action`` enchaîne plusieurs phases
        DANS LA MÊME action. Ne comparer que « phase d'avant » et « phase de maintenant »
        perdait tout point situé entre les deux : MESURÉ le 2026-08-12, la dernière pose de
        déploiement enchaînait ``deployment → command → move`` et la seule frontière vue,
        ``deployment → move``, ne correspondait à AUCUN point configuré — le checkpoint de fin
        de phase de commandement du tour 1 n'existait pas, et un objectif occupé restait neutre
        en silence pendant toute la phase de mouvement. La suite réelle des phases est donc
        enregistrée par ``enter_phase`` (écrivain unique) et drainée ici.

        ⚠️ UNE SEULE DÉTERMINATION, à la PREMIÈRE frontière qui tire. Les frontières d'une
        cascade sont instantanées et séparent des états IDENTIQUES : les rejouer ne produit
        aucune séquence, ça écrase ``previous_controller`` par le contrôleur qu'on vient
        d'écrire. Le journal de partie dirait alors « held by Px » sur une CAPTURE — mesuré le
        2026-08-12 en jeu (`tri_2 Centre` n'a jamais eu sa ligne « captured by P1 »), et sur
        une cascade ``move → shoot → charge`` : détail `(1, 1)` au lieu de `(1, None)`.
        La boucle sert donc à trouver QUELLE frontière tire, pas à tirer plusieurs fois.

        Retourne True si le checkpoint a été exécuté.
        """
        from engine.game_utils import PHASES_TRAVERSED_KEY

        phase = game_state.get("phase")  # get allowed (pré-reset)
        turn = game_state.get("turn")  # get allowed (pré-reset)
        # DRAINE avant tout retour anticipé : une file conservée serait rejouée à la frontière
        # suivante, sur un état qui n'est plus le sien.
        traversed = game_state.pop(PHASES_TRAVERSED_KEY, [])  # pop allowed (absence = 1er passage)
        last = game_state.get("_objective_control_last_boundary")  # get allowed (1er passage)
        game_state["_objective_control_last_boundary"] = (phase, turn)
        if last is None:
            # Début de bataille : aucune frontière franchie → aucun objectif contrôlé (14.02).
            return False
        last_phase, last_turn = last
        turn_changed = turn != last_turn
        # Chaîne des phases réellement traversées, de la dernière vue jusqu'à la courante. Elle
        # se termine TOUJOURS sur `phase` : les états reconstruits hors `enter_phase` (fixtures
        # de test, restauration d'une sauvegarde) n'ont pas de file, et retombent alors sur les
        # deux extrémités — le comportement d'avant, jamais faux, seulement moins fin.
        chain = [last_phase] + [p for p in traversed]
        if chain[-1] != phase:
            chain.append(phase)
        boundaries = list(zip(chain, chain[1:]))
        if not boundaries:
            if not turn_changed:
                return False
            # Même phase, tour différent : c'est la fin de TOUR (14.02) qu'il faut solder.
            boundaries = [(last_phase, phase)]
        for old_phase, new_phase in boundaries:
            if self.run_objective_control_checkpoint(
                game_state, old_phase, new_phase, turn_changed=turn_changed
            ):
                return True
        return False

    def _calculate_primary_objective_control_counts(
        self,
        game_state: Dict[str, Any],
        primary_objective: Dict[str, Any]
    ) -> Dict[int, int]:
        """
        Calculate objective control counts for primary objective scoring.

        Uses primary objective control rules (method + tie behavior) to count
        objectives controlled by each player for scoring purposes.
        """
        objectives = require_key(game_state, "objectives")
        if not objectives:
            return {1: 0, 2: 0}

        objective_controllers = require_key(game_state, "objective_controllers")

        control_cfg = require_key(primary_objective, "control")
        method = require_key(control_cfg, "method")
        control_method = require_key(control_cfg, "control_method")
        tie_behavior = require_key(control_cfg, "tie_behavior")

        if method != "oc_sum_greater":
            raise ValueError(f"Unsupported primary objective control method: {method}")
        if control_method not in ("secured", "default"):
            raise ValueError(f"Unsupported control_method: {control_method}")
        if tie_behavior != "no_control":
            raise ValueError(f"Unsupported primary objective tie_behavior: {tie_behavior}")

        counts = {1: 0, 2: 0}

        # Parseur commun : ce site indexait `h[0]/h[1]` en dur, comme `_calculate_objective_control`
        # — la forme {"col","row"}, acceptee partout ailleurs, levait donc dans le comptage qui
        # decide des VP.
        for obj_id, hex_set in objective_hex_zones(game_state):
            obj_id_key = str(obj_id)
            # Rule 14.02 : somme des OC des figurines dont l'empreinte de socle RECOUVRE la
            # zone (un hexe commun suffit — ce n'est PAS un test sur le centre du socle),
            # figurines mortes exclues. Les unites battle-shocked n'y contribuent rien :
            # 01.07 met l'OC de toutes leurs figurines a '-' (02.02). Detail dans
            # ``sum_objective_control_oc``, seule implementation.
            player_1_oc, player_2_oc = self._sum_objective_control_oc(game_state, hex_set)

            if obj_id_key not in objective_controllers:
                objective_controllers[obj_id_key] = None
            current_controller = objective_controllers[obj_id_key]
            obj_secured_by = game_state.get("secured_objectives", {}).get(obj_id_key)
            new_controller, _should_clear = _resolve_objective_controller(
                player_1_oc, player_2_oc, current_controller, obj_secured_by, control_method
            )
            if _should_clear:
                game_state["secured_objectives"].pop(obj_id_key, None)

            objective_controllers[obj_id_key] = new_controller
            if new_controller is not None:
                counts[new_controller] += 1

        return counts

    def apply_primary_objective_scoring(self, game_state: Dict[str, Any], scoring_phase: str) -> None:
        """
        Apply primary objective scoring for the current turn and player.
        
        scoring_phase: "command" or "fight"
        """
        primary_objective = game_state.get("primary_objective")
        if primary_objective is None:
            return
        if isinstance(primary_objective, list):
            for objective in primary_objective:
                if not isinstance(objective, dict):
                    raise TypeError(f"primary_objective list entry is {type(objective).__name__}, expected dict")
                self._apply_primary_objective_scoring_single(game_state, scoring_phase, objective)
            return
        if not isinstance(primary_objective, dict):
            raise TypeError(f"primary_objective is {type(primary_objective).__name__}, expected dict")
        self._apply_primary_objective_scoring_single(game_state, scoring_phase, primary_objective)

    def _apply_primary_objective_scoring_single(
        self,
        game_state: Dict[str, Any],
        scoring_phase: str,
        primary_objective: Dict[str, Any]
    ) -> None:
        """
        Apply primary objective scoring for a single objective config.
        """

        scoring_cfg = require_key(primary_objective, "scoring")
        timing_cfg = require_key(primary_objective, "timing")
        start_turn = require_key(scoring_cfg, "start_turn")
        # `rules` / `max_points_per_turn` sont exiges ICI, avant les quatre sorties anticipees,
        # bien que `primary_objective_points` les relise : une mission malformee doit echouer au
        # PREMIER appel, pas au premier tour marquant — soit plusieurs minutes de run plus tard,
        # sur un chemin qu'un scenario court peut ne jamais atteindre.
        require_key(scoring_cfg, "rules")
        require_key(scoring_cfg, "max_points_per_turn")
        default_phase = require_key(timing_cfg, "default_phase")
        round5_second_player_phase = require_key(timing_cfg, "round5_second_player_phase")

        current_turn = require_key(game_state, "turn")
        current_player = require_key(game_state, "current_player")
        current_player_int = int(current_player)

        if current_turn < start_turn:
            return

        if current_turn == 5 and current_player_int == 2:
            expected_phase = round5_second_player_phase
        else:
            expected_phase = default_phase

        if scoring_phase != expected_phase:
            return

        from engine.game_utils import once_claim, once_claimed

        objective_id = require_key(primary_objective, "id")
        score_key = (objective_id, current_turn, current_player_int)
        if once_claimed(game_state, "primary_objective_scored_turns", score_key):
            return

        counts = self._calculate_primary_objective_control_counts(game_state, primary_objective)
        opponent_player = 1 if current_player_int == 2 else 2

        total_points = primary_objective_points(
            scoring_cfg, counts[current_player_int], counts[opponent_player]
        )

        victory_points = require_key(game_state, "victory_points")
        if current_player_int not in victory_points:
            raise KeyError(f"victory_points missing player {current_player_int}")
        victory_points[current_player_int] += total_points
        once_claim(game_state, "primary_objective_scored_turns", score_key)
        self._sample_objectives_held(game_state, counts, current_player_int, opponent_player)

    def _sample_objectives_held(
        self,
        game_state: Dict[str, Any],
        counts: Dict[int, int],
        current_player_int: int,
        opponent_player: int,
    ) -> None:
        """Echantillonne, UNE fois par tour marque, les objectifs tenus de part et d'autre.

        Alimente 01_VP/e_objectives_held et 01_VP/d_objectives_held_diff. Site choisi : l'instant
        exact ou les VP sont attribues au joueur controle. `counts` est celui qui vient de
        decider les points (regles de controle 14.02 du primaire, tie_behavior inclus) — la
        mesure et le score partent donc de la MEME source, sans second comptage.

        L'echantillonnage vivait auparavant dans RewardCalculator._calculate_objective_reward_per_turn
        (voir la trace laissee la-bas) : branche sur un calcul de recompense, il heritait de ses
        gardes de sortie et n'a jamais produit un seul point en 50 000 episodes.

        Un seul echantillon par tour : celui du joueur controle. La fonction est appelee pour
        les deux joueurs a chaque tour, mais `f_objectives_held_diff` compare mon controle a
        celui de l'adversaire AU MEME INSTANT — prendre aussi le passage adverse melangerait
        deux instants dans une meme moyenne.
        """
        controlled_player = int(require_key(self.config, "controlled_player"))
        if current_player_int != controlled_player:
            return
        controlled_samples = require_key(game_state, "controlled_objective_samples_scoring_turns")
        opponent_samples = require_key(game_state, "opponent_objective_samples_scoring_turns")
        controlled_samples.append(float(require_key(counts, current_player_int)))
        opponent_samples.append(float(require_key(counts, opponent_player)))

    def check_game_over(self, game_state: Dict[str, Any]) -> bool:
        """
        Check if game is over.

        Game ends when:
        1. Turn limit reached (training config override)
        """
        # Duree de bataille : game_rules.max_turns (source unique, cf. game_utils).
        from engine.game_utils import turn_limit_reached
        if turn_limit_reached(game_state):
            return True

        if require_key(game_state, "turn_limit_reached"):
            return True

        return False
    
    def determine_winner(self, game_state: Dict[str, Any]) -> Optional[int]:
        """
        Determine winner based on primary objective victory points.

        Victory conditions:
        1. More victory points at end of game
        2. Tiebreaker: More total VALUE of living units
        3. Draw if still tied

        Returns:
            1 = Player 1 wins
            2 = Player 2 wins
            -1 = Draw
            None = Game still ongoing
        """
        if not require_key(game_state, "turn_limit_reached"):
            return None

        victory_points = require_key(game_state, "victory_points")
        p1_points = require_key(victory_points, 1)
        p2_points = require_key(victory_points, 2)

        if p1_points > p2_points:
            return 1
        if p2_points > p1_points:
            return 2

        army_value = army_value_by_player(game_state)
        if army_value[1] > army_value[2]:
            return 1
        if army_value[2] > army_value[1]:
            return 2
        return DRAW_WINNER

    def determine_winner_with_method(self, game_state: Dict[str, Any]) -> Tuple[Optional[int], Optional[str]]:
        """
        Determine winner AND the method of victory.

        Returns:
            Tuple of (winner, win_method):
            - winner: 1, 2, -1 (draw), or None (ongoing)
            - win_method: "objectives", "value_tiebreaker", "draw", or None
        """
        if not require_key(game_state, "turn_limit_reached"):
            return None, None

        victory_points = require_key(game_state, "victory_points")
        p1_points = require_key(victory_points, 1)
        p2_points = require_key(victory_points, 2)

        if p1_points > p2_points:
            return 1, "objectives"
        if p2_points > p1_points:
            return 2, "objectives"

        army_value = army_value_by_player(game_state)
        if army_value[1] > army_value[2]:
            return 1, "value_tiebreaker"
        if army_value[2] > army_value[1]:
            return 2, "value_tiebreaker"
        return DRAW_WINNER, "draw"



def army_value_by_player(game_state: Dict[str, Any]) -> Dict[int, int]:
    """Valeur d'armee ENCORE EN JEU, par joueur — le critere de DEPARTAGE de la bataille.

    SOURCE UNIQUE de ce calcul : il decide la victoire a egalite de points de mission
    (« value_tiebreaker »). `determine_winner` et `determine_winner_with_method` en portaient
    chacune une copie ECRITE A LA MAIN, identiques au caractere pres — deux implementations d'une
    meme regle divergent au premier ajustement, et c'est le mode d'echec n°1 de ce depot.

    ⚠️ C'est du TOUT-OU-RIEN, et c'est la regle : une escouade rend sa VALUE entiere a sa mort,
    jamais au prorata des figurines tombees. `units_cache` ne contient que les escouades vivantes,
    et la VALUE est celle de l'ESCOUADE. Tout consommateur qui voudrait un signal continu (une
    heuristique de bot, par exemple) mesurerait alors autre chose que la condition de victoire :
    c'est un autre calcul, pas un raffinement de celui-ci.
    """
    units_cache = require_key(game_state, "units_cache")
    unit_by_id = {str(u["id"]): u for u in require_key(game_state, "units")}
    value_by_player: Dict[int, int] = {1: 0, 2: 0}
    for unit_id, entry in units_cache.items():
        unit = unit_by_id.get(str(unit_id))
        if not unit:
            raise KeyError(f"Unit {unit_id} missing from game_state['units']")
        player = int(require_key(entry, "player"))
        if player not in value_by_player:
            raise ValueError(f"Unexpected unit player id: {player}")
        value_by_player[player] += int(require_key(unit, "VALUE"))
    return value_by_player


def primary_objective_points(
    scoring_cfg: Dict[str, Any], own_objectives: int, opponent_objectives: int
) -> int:
    """VP marques par UN joueur sur UN tour de scoring du primaire, plafond compris.

    SOURCE UNIQUE de la forme du primaire : `_apply_primary_objective_scoring_single` (qui
    attribue les VP) et `RewardCalculator._calculate_objective_reward_per_turn` (qui paie
    l'agent pour la meme chose) l'appellent tous les deux. Les deux repondaient auparavant a
    leur facon : le moteur en ESCALIER (5 si >=1, 5 si >=2, 5 si j'en tiens plus, plafond 15),
    la recompense en LINEAIRE (`reward_per_objective * mes_objectifs`, sans plafond). Au-dela
    de 2 objectifs le jeu ne payait plus rien et la recompense continuait de monter : l'agent
    etait paye pour s'etaler sur des zones que la mission ne compte pas.

    Les montants et les conditions viennent de `scoring.rules` du primaire — le seul endroit ou
    la mission est definie. Une condition inconnue leve : un scoring silencieusement ignore
    ferait diverger les VP et la recompense sans que rien ne le signale.
    """
    total_points = 0
    for rule in require_key(scoring_cfg, "rules"):
        condition = require_key(rule, "condition")
        points = require_key(rule, "points")
        if condition == "control_at_least_one":
            if own_objectives >= 1:
                total_points += points
        elif condition == "control_at_least_two":
            if own_objectives >= 2:
                total_points += points
        elif condition == "control_more_than_opponent":
            if own_objectives > opponent_objectives:
                total_points += points
        else:
            raise ValueError(f"Unsupported primary objective condition: {condition}")
    return min(total_points, require_key(scoring_cfg, "max_points_per_turn"))


def sum_objective_control_oc(
    game_state: Dict[str, Any], hex_set: Set[Tuple[int, int]]
) -> Tuple[int, int]:
    """Rule 14.02 : ``(player_1_oc, player_2_oc)`` sommes sur toute FIGURINE dans la zone.

    Une figurine compte des qu UNE case de son empreinte de socle recouvre ``hex_set`` ; elle
    apporte alors la caracteristique OC de son unite (l OC est par figurine). Les figurines
    mortes (absentes de models_cache), les unites a OC 0 et les unites battle-shocked
    (01.07 : OC de toutes leurs figurines modifie a '-') sont ignorees.

    Fonction module-level : SOURCE UNIQUE du controle d objectif du moteur
    (``StateManager._sum_objective_control_oc`` / ``calculate_objective_control``).
    L observation de l agent ne l appelle PAS : ``ObservationBuilder._squad_objective_control``
    relit ``objective_controllers``, l etat persistant qu ecrit ``calculate_objective_control``
    (14.02 : le controle est fige a la fin de chaque phase et de chaque tour, pas recalcule en
    continu). La source reste donc unique, par lecture d etat et non par appel partage.

    Lecture pure : aucun etat n est mute (contrairement a ``calculate_objective_control``, qui
    met a jour ``objective_controllers``).
    """
    return sum_objective_control_oc_multi(game_state, [hex_set])[0]


def iter_living_model_footprints(
    game_state: Dict[str, Any], unit_id: Any
) -> Iterator[Set[Tuple[int, int]]]:
    """Empreintes de socle des figurines VIVANTES de ``unit_id`` (lecture PAR FIGURINE, 14.02).

    Source unique de la question « ou est reellement posee cette escouade » : ``models_cache``
    (position par figurine) + ``compute_occupied_hexes`` (empreinte du socle), et NON l ancre
    d escouade de ``units_cache``. Une figurine dont le socle recouvre une zone y est presente
    meme si l ancre de son escouade est ailleurs — c est exactement ce que teste
    ``sum_objective_control_oc_multi``, qui consomme ce generateur.

    Les figurines mortes (absentes de ``models_cache`` ou HP_CUR <= 0) sont ignorees.
    """
    from engine.hex_utils import compute_occupied_hexes, socle_is_single_hex

    units_cache = require_key(game_state, "units_cache")
    models_cache = require_key(game_state, "models_cache")
    squad_models = require_key(game_state, "squad_models")
    # Escouade éliminée : retirée de units_cache par update_units_cache_hp quand HP=0.
    # Aucune figurine vivante → aucun footprint.
    entry = units_cache.get(str(unit_id))
    if entry is None:
        return
    squad_orientation = int(require_key(entry, "orientation"))
    for mid in require_key(squad_models, str(unit_id)):
        model = models_cache.get(mid)
        if model is None:
            continue
        if int(require_key(model, "HP_CUR")) <= 0:
            continue
        # HORS TABLE (sentinelle (-1,-1)) : figurine en réserves (20.01) ou en attente de
        # déploiement. Elle n'occupe AUCUNE case, donc ne contrôle aucun objectif (14.02) —
        # jumeau de la garde de `_compute_unit_occupied_hexes`, ici sur le chemin par-figurine
        # qui appelle `compute_occupied_hexes` directement.
        col = int(model["col"])
        row = int(model["row"])
        if col < 0 or row < 0:
            continue
        # ORIENTATION PAR FIGURINE, defaut = celle de l escouade. Meme lecture que
        # `shared_utils._recompute_squad_occupied_hexes`, qui ecrit les empreintes de reference
        # (`occupied_hexes_by_model`). Cette fonction ne lisait QUE l orientation d escouade :
        # `update_model_position` pose une orientation propre a la figurine lors d un pivot a la
        # molette et ne synchronise PAS l entree d escouade — un socle ovale ou carre pivote
        # rendait donc une empreinte differente selon le lecteur, dans le meme etat de jeu. Sans
        # effet sur un socle rond (l orientation n y change rien), d ou l absence de symptome
        # jusqu ici. `get` et non `require_key` : les etats anterieurs au pivot par figurine
        # n ont pas la cle, et l orientation d escouade EST leur valeur.
        base_shape = model["BASE_SHAPE"]
        base_size = model["BASE_SIZE"]
        # CHEMIN RAPIDE MONO-HEXE (2026-08-12). A `inches_to_subhex == 1` — le plateau
        # d'entrainement — `_scale_socle` normalise TOUS les socles en `round` de taille 1, et
        # l'empreinte y vaut toujours l'ancre. Mesure ENTRELACEE (round-robin, min sur 25 tours ;
        # une mesure sequentielle avant/apres derive de ±40 % sur cette machine et rend un
        # classement faux) : **-35 % a -39 %** sur ce generateur, a toutes les echelles testees.
        # Le gain porte aussi sur `calculate_objective_control` et `unit_is_within_objective`.
        #
        # ⚠️ QUATRIEME COPIE DU RACCOURCI, pas du predicat. Le predicat, lui, a une source unique
        # (`socle_is_single_hex`, corrige le meme jour pour pouvoir servir ici) ; le raccourci
        # « empreinte = ancre » est ecrit aussi a `movement_handlers.py:4074` et `:4317`, et sous
        # une forme volontairement differente a `deployment_handlers.py:240`. Toute 5e occurrence
        # doit etre relue avec ces quatre-la sous les yeux.
        if socle_is_single_hex(base_shape, base_size):
            yield {(col, row)}
            continue
        orientation = int(model.get("orientation", squad_orientation))
        yield compute_occupied_hexes(col, row, base_shape, base_size, orientation)


#: Cle du cache des zones d'objectif (cf. `objective_hex_zones`). Valeur : le TRIPLET
#: `(objectifs, zones, union)`, ou le premier element est la liste SOURCE, comparee par identite —
#: remplacer `objectives` invalide donc le cache sans aucun code d'invalidation. Le troisieme est
#: l'union de toutes les zones (`objective_hexes_union`), memoisee AVEC elles parce que la
#: reconstruire par appel coute six fois ce qu'elle fait gagner.
_OBJECTIVE_ZONES_CACHE_KEY = "_objective_hex_zones_cache"


def objective_hex_zones(game_state: Dict[str, Any]) -> List[Tuple[Any, Set[Tuple[int, int]]]]:
    """`(id, zone)` par objectif, DANS L ORDRE de ``game_state["objectives"]`` (14.01).

    PARSEUR DES ZONES pour tout ce qui juge une PRESENCE ou un CONTROLE : controle d objectif
    (`_calculate_objective_control`, `_calculate_primary_objective_control_counts`), regle 14.02
    (`unit_is_within_objective`), consolidation 12.08 (`fight_handlers`), recompense d objectif,
    bots d evaluation.

    `fight_handlers._fight_v11_objective_hex_sets` en etait une SECONDE implementation, tolerante
    la ou celle-ci est stricte : objectif non-dict ignore, `hexes` absent ou mal type reduit a un
    ensemble vide puis ECARTE de la liste, entree `[col]` acceptee par un `len >= 2`. Sur des
    donnees propres les deux coincidaient (mesure sur le scenario d entrainement : 5 zones, memes
    tailles) ; sur une entree abimee elles rendaient des listes de LONGUEURS DIFFERENTES dans le
    meme etat de jeu — l observation et la recompense voyant N objectifs pendant que la
    consolidation 12.08 en voyait N-1, sans un mot. Les deux sites de scoring des VP indexaient
    `h[0]/h[1]` en dur : ils REJETAIENT la forme {"col","row"} que cette fonction accepte, donc
    une meme donnee etait lisible par la regle et levait dans le calcul des VP.

    ⚠️ DEUX lectures subsistent, volontairement : `observation_builder` (~581) et `action_decoder`
    (~1005) parsent `hexes` pour en tirer des DISTANCES, pas des zones — ils ont besoin des hexes
    un par un, pas d un ensemble, et acceptent deja les deux formes. Ils ne divergent donc pas de
    celle-ci sur ce qu ils acceptent ; les mutualiser est une simplification, pas une correction.

    Le loader de scenario ecrit `hexes` en paires [col, row] (`polygon_to_hex_list` sur les
    terrains "objective": true). La forme {"col","row"} est acceptee parce que la lecture
    historique du moteur l acceptait ; toute autre forme est une erreur explicite.

    Une zone VIDE leve, et l erreur nomme l objectif fautif. Un objectif sans hexe n est
    controlable par personne : il fausse `control_at_least_one` / `control_at_least_two` et le
    depart « j en tiens plus que lui », donc les VP. Le moteur le traite DEJA comme une erreur
    ailleurs — `objective_distance.distances_to_zone` leve sur une aire sans segment, et le
    scoring de deploiement comme les bots d evaluation passent par la. Lever ici ne cree
    donc pas un mode d echec, il l avance a un endroit qui dit lequel des objectifs est en cause.
    Les deux lectures precedentes en donnaient DEUX interpretations muettes : ensemble vide
    conserve cote moteur, objectif ecarte cote combat. Aucune occurrence en production (zones de
    1730 a 3000 hexes sur le scenario d entrainement), c est un garde-fou de scenario abime —
    typiquement une forme rasterisee entierement hors plateau.

    `.get` sur `objectives` est ASSUME : cette fonction est de la GEOMETRIE, partagee avec les
    bots d evaluation, qui tournent sur des etats ou l absence d objectif est legitime. La
    severite de la REGLE 14.02 est portee par `unit_is_within_objective`, pas ici.
    """
    objectives = game_state.get("objectives")  # get allowed : scenario sans objectif
    if not objectives:
        return []
    if not isinstance(objectives, list):
        raise TypeError(
            f"game_state['objectives'] must be a list, got {type(objectives).__name__}"
        )
    # CACHE PAR IDENTITE de la liste source. Les zones sont IMMUABLES sur toute la bataille : le
    # loader de scenario construit des dicts NEUFS (`hex_utils`, `objective_out = dict(objective)`)
    # et rien ne mute ensuite ni la liste ni les `hexes` (verifie par grep). Reconstruire a chaque
    # appel coutait 10 538 hexes reparses et normalises — MESURE : 2,7 ms par appel, 42 appels par
    # episode, 155 ms soit 3,3 % du temps d'un episode d'entrainement.
    #
    # POURQUOI L'IDENTITE ET PAS UNE INVALIDATION EXPLICITE : les trois sites qui posent
    # `objectives` (construction, reset, rotation de roster) y affectent une NOUVELLE liste, donc
    # `is` suffit et il n'y a aucun site d'invalidation a ne pas oublier — c'est precisement le
    # mode de defaillance qu'un cache invalide a la main introduit.
    #
    # ⚠️ Les ensembles rendus sont PARTAGES entre appelants : les muter empoisonnerait le cache.
    # Tous les consommateurs les lisent (`isdisjoint`, `in`) ; aucun n'y ecrit (verifie par grep).
    #
    # ⚠️ DEPUIS LE 2026-08-12, MUTER UNE ZONE COUTE PLUS CHER QU'AVANT. L'union memoisee (3e
    # element du triplet) en est DERIVEE, sans lien d'invalidation : une zone mutee laisserait
    # l'union en arriere, et le pre-filtre de `objective_control_contributions` ecarterait alors
    # des figurines REELLEMENT dans la zone — du controle perdu en silence, exactement la faute
    # pour laquelle le pre-filtre par union d'escouade a ete refuse. Avant, une telle mutation
    # restait au moins auto-coherente.
    # LE GEL EN `frozenset`, qui rendrait l'invariant STRUCTUREL, a ete tente puis ECARTE le meme
    # jour : le type se propage a `objective_distance` et `fight_handlers`, deux modules etrangers
    # a ce chantier (7 erreurs de typage). L'invariant reste donc porte par ce commentaire — mais
    # il n'est plus une precaution de style, et toute future mutation de zone doit reconstruire
    # l'union dans le meme geste.
    cached = game_state.get(_OBJECTIVE_ZONES_CACHE_KEY)  # get allowed : absence = 1er appel
    if cached is not None and cached[0] is objectives:
        return cached[1]
    zones: List[Tuple[Any, Set[Tuple[int, int]]]] = []
    for objective in objectives:
        hexes = require_key(objective, "hexes")
        if not isinstance(hexes, list):
            raise TypeError(f"objective['hexes'] must be a list, got {type(hexes).__name__}")
        zone: Set[Tuple[int, int]] = set()
        for objective_hex in hexes:
            if isinstance(objective_hex, dict):
                zone.add(normalize_coordinates(
                    require_key(objective_hex, "col"), require_key(objective_hex, "row")
                ))
            elif isinstance(objective_hex, (list, tuple)) and len(objective_hex) == 2:
                zone.add(normalize_coordinates(objective_hex[0], objective_hex[1]))
            else:
                raise TypeError(
                    "objective hex entry must be {'col','row'} or [col,row]/(col,row), "
                    f"got {objective_hex!r}"
                )
        if not zone:
            raise ValueError(
                f"Objective {require_key(objective, 'id')!r} has an empty control zone: "
                f"an objective with no hex cannot be controlled by anyone."
            )
        zones.append((require_key(objective, "id"), zone))
    game_state[_OBJECTIVE_ZONES_CACHE_KEY] = (
        objectives, zones, frozenset().union(*(z for _id, z in zones)),
    )
    return zones


def objective_hexes_union(game_state: Dict[str, Any]) -> "frozenset[Tuple[int, int]]":
    """Union de TOUTES les zones d objectif — memoisee avec elles, jamais reconstruite.

    Sert de PRE-FILTRE exact : une empreinte disjointe de l union est disjointe de chaque zone,
    donc l ecarter ne peut rien perdre. Reconstruire l union a chaque appel, en revanche, coute
    beaucoup plus que le filtre ne rapporte — mesure entrelacee sur des zones de la taille REELLE
    du scenario d entrainement (1730 a 3000 hexes chacune, cf. `objective_hex_zones`) :

        zones de 2000 hexes, 12 escouades x 6 figurines
          sans filtre                  0,042 ms
          filtre, union par appel      0,303 ms   (+625 %)
          filtre, union memoisee       0,028 ms   (-32 %)

    ⚠️ MESURER CE FILTRE SUR DES ZONES JOUETS DONNE LE VERDICT INVERSE : a 9 hexes par zone, la
    reconstruction par appel semble gagner 29 %. C est l erreur qui a ete commise le 2026-08-12 et
    rattrapee en review. Toute mesure de ce poste se fait aux tailles de zone du scenario reel.

    ``frozenset`` et non ``set`` : l union est partagee entre appelants comme les zones elles-memes
    (cf. l avertissement de `objective_hex_zones`), et le type interdit ici la mutation qui
    empoisonnerait le cache.
    """
    if not game_state.get("objectives"):  # get allowed : scenario sans objectif
        return frozenset()
    objective_hex_zones(game_state)  # peuple le cache si besoin
    return game_state[_OBJECTIVE_ZONES_CACHE_KEY][2]


#: Gain de Core CP de l'étape 08.02, en dur : « Both players gain 1 Command Point ». Ce n'est
#: pas un réglage — le PDF 08 ne laisse aucune latitude — d'où une constante et non une clé de
#: config, qui laisserait croire qu'un scénario peut en changer.
CORE_CP_GAIN_PER_COMMAND_PHASE = 1


def initial_command_points(config: Dict[str, Any]) -> Dict[int, int]:
    """Stock de CP des deux joueurs au début de la bataille.

    Lu dans ``game_rules.starting_command_points`` — SANS valeur par défaut : la dotation de
    départ dépend de la taille de partie (Incursion/Strike Force…), c'est donc une donnée de
    scénario, et son absence est une config incomplète, pas un « zéro raisonnable ».
    """
    game_rules = require_key(config, "game_rules")
    starting = int(require_key(game_rules, "starting_command_points"))
    if starting < 0:
        raise ValueError(
            f"game_rules.starting_command_points = {starting} : un stock de CP negatif n'a "
            f"aucun sens (aucune regle ne fait descendre un joueur sous 0)."
        )
    return {1: starting, 2: starting}


def gain_command_points(
    game_state: Dict[str, Any], player: int, amount: int, reason: str
) -> int:
    """Ajoute ``amount`` CP au joueur et journalise le gain. Retourne le nouveau stock.

    ÉCRIVAIN UNIQUE de ``game_state["command_points"]`` : 08.02 et les capacités qui accordent
    du CP (``cp_gain_on_objective``) passent toutes par ici, donc le log et le plafond éventuel
    n'ont qu'une implémentation. Aucune dépense ne transite ici tant qu'aucun consommateur
    n'existe (pas de stratagèmes) : ``amount`` est exigé strictement positif.
    """
    if amount <= 0:
        raise ValueError(f"gain_command_points: amount = {amount}, attendu strictement positif")
    player_int = int(player)
    if player_int not in (1, 2):
        raise ValueError(f"gain_command_points: joueur inconnu {player!r}")
    command_points = require_key(game_state, "command_points")
    if player_int not in command_points:
        raise KeyError(
            f"game_state['command_points'] n'a pas d'entree pour le joueur {player_int} : "
            f"{command_points!r}"
        )
    command_points[player_int] += amount
    from engine.game_utils import add_console_log

    add_console_log(
        game_state,
        f"P{player_int} gains {amount}CP ({reason}) - total {command_points[player_int]}CP",
    )
    return command_points[player_int]


def objective_hex_sets(game_state: Dict[str, Any]) -> List[Set[Tuple[int, int]]]:
    """Zones des objectifs, SANS leur id, dans l ordre de ``game_state["objectives"]``.

    L ordre est un contrat : `get_objective_control(zone_idx, ...)` indexe la meme liste, donc
    aucune entree ne peut etre omise — c est pourquoi une zone vide leve dans le parseur au lieu
    d etre ecartee.
    """
    return [zone for _objective_id, zone in objective_hex_zones(game_state)]


def unit_is_within_objective(
    game_state: Dict[str, Any],
    unit_or_id: Any,
    zones: Optional[List[Set[Tuple[int, int]]]] = None,
) -> bool:
    """Regle 14.02 : l unite est-elle A PORTEE d un objectif ? Lecture PAR FIGURINE.

    « A model is within range of a terrain objective while it is within that terrain area »
    (14.02, PDF 14 Objectives) — la portee se juge donc FIGURINE par FIGURINE, sur l aire de
    terrain, et l unite y est des qu UNE de ses figurines vivantes y est (l illustration du
    meme paragraphe compte « six of its models are within the terrain area »).

    ⚠️ ROOT CAUSE CORRIGEE — la lecture historique comparait l ANCRE D ESCOUADE a un hexe
    d objectif, par egalite stricte de coordonnees. Deux erreurs cumulees : l ancre n est pas
    une figurine (une escouade etalee a des figurines dans la zone sans que son ancre y soit,
    et l inverse), et l egalite de centre ignore l EMPREINTE DE SOCLE, alors que le controle
    d objectif du meme moteur (`sum_objective_control_oc_multi`) compte une figurine des qu une
    case de son socle recouvre la zone. Les deux questions n avaient donc pas la meme reponse
    dans le meme etat de jeu. Meme generateur d empreintes ici : une seule implementation.

    `zones` : zones deja calculees par l appelant (evite de reconstruire les ensembles a
    chaque candidate d une boucle de decision) ; None = les lire ici.

    ⚠️ Quand cette fonction construit elle-meme les zones, elle EXIGE la cle `objectives` : elle
    repond alors a une question de REGLE pour le moteur (relance de blessure sur objectif, bonus
    « sur un objectif »), et la cle est posee inconditionnellement a la construction du
    game_state — son absence est un etat corrompu, jamais « pas d objectif sur la table », qui
    est une LISTE VIDE. La lecture historique (`is_unit_on_objective`) exigeait cette cle ;
    l unification l avait relachee en `.get`, ce qui aurait desarme la regle EN SILENCE. Un
    appelant qui FOURNIT `zones` (les bots d evaluation, sur des etats ou l absence d objectif
    est legitime) ne subit pas cette exigence : il a deja repondu a la question pour lui-meme.
    """
    if zones is None:
        require_key(game_state, "objectives")
    zones = objective_hex_sets(game_state) if zones is None else zones
    if not zones:
        return False
    unit_id = str(unit_or_id["id"]) if isinstance(unit_or_id, dict) else str(unit_or_id)
    for footprint in iter_living_model_footprints(game_state, unit_id):
        if any(not footprint.isdisjoint(zone) for zone in zones):
            return True
    return False


def _resolve_objective_controller(
    player_1_oc: int,
    player_2_oc: int,
    current_controller: Optional[int],
    obj_secured_by: Optional[int],
    control_method: str,
) -> Tuple[Optional[int], bool]:
    """Résout le contrôleur d'un objectif et indique si le statut sécurisé doit être effacé.

    Retourne (new_controller, should_clear_secured).
    """
    use_secured = (
        control_method == "secured"
        or (obj_secured_by is not None and obj_secured_by == current_controller)
    )
    if use_secured:
        new_controller: Optional[int] = current_controller
        if player_1_oc > player_2_oc:
            new_controller = 1
        elif player_2_oc > player_1_oc:
            new_controller = 2
    elif control_method == "default":
        new_controller = None
        if player_1_oc > player_2_oc:
            new_controller = 1
        elif player_2_oc > player_1_oc:
            new_controller = 2
    else:
        raise ValueError(f"Unsupported control_method: {control_method}")
    should_clear = (
        obj_secured_by is not None
        and new_controller is not None
        and new_controller != obj_secured_by
    )
    return new_controller, should_clear


def unit_effective_oc(unit: Dict[str, Any]) -> int:
    """OC effectif de l'unite, incluant oc_bonus (Relic Banner, Primitive E chantier 06).

    Regle 14.02 : chaque figurine de l'unite apporte sa caracteristique OC. La regle `oc_bonus`
    ajoute un bonus fixe a cet OC par figurine. Somme sur toutes les entrees `oc_bonus` de
    UNIT_RULES (une seule declaree en pratique ; la somme generalise sans casse supplementaire).

    Source unique du OC effectif : `objective_control_contributions` l'appelle en lieu et place
    de `require_key(unit, "OC")`. Aucun autre site ne lit l'OC pour le controle : la modifier
    ici couvre tout le systeme d'objectif.
    """
    base_oc = int(require_key(unit, "OC"))
    for rule_entry in unit.get("UNIT_RULES", []):
        if rule_entry.get("ruleId") == "oc_bonus":
            rule_args = rule_entry.get("rule_args")
            if not isinstance(rule_args, dict) or "oc_bonus" not in rule_args:
                raise ValueError(
                    f"Rule 'oc_bonus' on unit {unit.get('id')} "
                    "must define rule_args.oc_bonus"
                )
            base_oc += int(rule_args["oc_bonus"])
    return base_oc


def apply_secure_objective_on_control(game_state: Dict[str, Any]) -> List[int]:
    """Primitive E — fin de phase de commandement, marque les objectifs securises.

    Regle : si l'unite active portant `secure_objective_on_control` controle un objectif en fin
    de phase de commandement, cet objectif est securise pour ce joueur (14.03) — l'adversaire
    doit avoir STRICTEMENT plus d'OC pour le reprendre. `calculate_objective_control` lit
    `secured_objectives` pour appliquer la logique securisee par objectif.

    Retourne la liste des obj_id securises lors de cet appel (0 = rien de nouveau).
    Prerequis : `objective_controllers` doit etre a jour (appeler apres le checkpoint 14.02).
    """
    from engine.phase_handlers.shared_utils import is_unit_alive, unit_has_rule_effect

    current_player = int(require_key(game_state, "current_player"))
    units = require_key(game_state, "units")

    # Porteurs vivants, non battle-shocked, du joueur actif ayant la capacite.
    carriers = [
        unit for unit in units
        if int(require_key(unit, "player")) == current_player
        and unit_has_rule_effect(unit, "secure_objective_on_control")
        and not require_key(unit, "battle_shocked")
        and is_unit_alive(str(require_key(unit, "id")), game_state)
    ]
    if not carriers:
        return []

    # S'assure que `objective_controllers` reflète l'OC ACTUEL (après le battle-shock 08.03).
    # Sans cet appel, l'état peut être périmé : au tour 1 le dict est encore vide (aucun
    # checkpoint antérieur), et au tour 2+ `_calculate_primary_objective_control_counts` peut
    # avoir été ignoré si le scoring était déjà résolu pour ce tour-ci. Même motif que
    # `movement_step_cp_gain_on_objective` (cp_gain_on_objective).
    GameStateManager(require_key(game_state, "config")).calculate_objective_control(game_state)

    if "secured_objectives" not in game_state:
        game_state["secured_objectives"] = {}

    from engine.action_log_utils import append_action_log
    controllers = require_key(game_state, "objective_controllers")
    newly_secured: List[int] = []
    for objective_id, zone in objective_hex_zones(game_state):
        obj_key = str(objective_id)
        if controllers.get(obj_key) != current_player:
            continue
        zone_list = [zone]
        securing_units = [
            u for u in carriers
            if unit_is_within_objective(game_state, u, zones=zone_list)
        ]
        if not securing_units:
            continue
        game_state["secured_objectives"][obj_key] = current_player
        newly_secured.append(objective_id)

        for unit in securing_units:
            append_action_log(game_state, {
                "type": "secure_objective",
                "unitId": str(require_key(unit, "id")),
                "player": current_player,
                "phase": "command",
                "turn": game_state.get("turn", 0),
                "objectiveId": objective_id,
            })

    from engine.game_utils import add_debug_file_log
    if newly_secured:
        add_debug_file_log(
            game_state,
            f"[SECURE OBJECTIVE] E{game_state.get('episode_number', '?')} "
            f"T{game_state.get('turn', '?')} player={current_player} "
            f"secured={newly_secured}"
        )
    return newly_secured


def objective_control_contributions(
    game_state: Dict[str, Any], hex_sets: List[Set[Tuple[int, int]]]
) -> Dict[str, Tuple[int, List[int]]]:
    """Ce que CHAQUE escouade apporte au controle : ``{unit_id: (joueur, [OC par zone])}``.

    SOURCE UNIQUE du comptage de controle (14.02). ``sum_objective_control_oc_multi`` n en est
    plus que l addition, et tout appelant qui a besoin d une variante — « sans telle escouade »,
    « qui apporte quoi » — la compose ICI, par arithmetique, sans recompter une presence.

    ⚠️ POURQUOI CETTE FORME, et non un parametre d exclusion sur la somme (arbitrage tranche le
    2026-08-12). Le surplus d encombrement des bots doit repondre « qu est-ce que mes ALLIES
    tiennent deja, SANS moi ? » — une escouade qui se compte elle-meme se voit comme un
    encombrement et quitte la zone qu elle tient. La premiere version reimplementait la question a
    cote (hexe-centre au lieu de l empreinte de socle, sans la regle 01.07) et divergeait du
    controle reel dans les deux sens ; la deuxieme a ajoute un ``exclude_unit_id`` a la fonction
    qui enonce la REGLE, ce qui lui faisait porter une question HYPOTHETIQUE de l IA. Le prochain
    contrefactuel (« sans mes escouades condamnees », « si je me posais la ») aurait ajoute son
    parametre a son tour. Exposer les contributions ferme la serie : le moteur dit qui apporte
    quoi, l appelant compose ce qu il veut, et il n y a toujours qu un seul comptage.

    Une escouade qui n apporte rien (battle-shocked 01.07, OC nul, aucune figurine dans aucune
    zone) est ABSENTE du dictionnaire : « ne rien apporter » et « ne pas figurer » sont la meme
    chose pour tous les appelants, et l addition comme la soustraction s en accommodent.

    Chaque empreinte de figurine est calculee une seule fois puis testee contre les N zones, au
    lieu d etre recalculee par zone. ``compute_occupied_hexes`` ne balaie rien : il translate des
    offsets memoises par ``precompute_footprint_offsets``. Le poste dominant MESURE est le
    generateur d empreintes lui-meme.

    DEUX pre-filtres, l un pris et l autre ECARTE, et la difference tient a l exactitude :
      - PRIS : l union des zones (``objective_hexes_union``, MEMOISEE — la construire par appel
        coute six fois ce qu elle rapporte, cf. son docstring). Une empreinte disjointe de l union
        est disjointe de chaque zone, donc ce filtre ne peut rien perdre. Mesure : -32 a -37 %,
        stable de 9 a 2000 hexes par zone.
      - ECARTE : l union d escouade (``units_cache[uid]["occupied_hexes"]``). Sur un plateau
        ``engagement_zone <= 1``, ``_compute_unit_occupied_hexes`` reduit l occupation a UNE case
        par figurine alors que le controle teste l empreinte complete — cette union-la n est pas un
        sur-ensemble et le filtre perdrait du controle EN SILENCE.

    ⚠️ ``hex_sets`` est ARBITRAIRE : rien n oblige un appelant a passer les zones de l etat, et le
    wrapper mono-zone ne le fait pas. Le pre-filtre n est donc applique QUE si les ensembles recus
    sont exactement ceux du cache (comparaison par identite, 5 tests) ; sinon il est desactive,
    parce que l union memoisee ne decrirait pas ces zones-la. Filtrer sur la mauvaise union
    perdrait du controle en silence — le defaut meme que le second pre-filtre s est vu refuser.
    """
    units_cache = require_key(game_state, "units_cache")
    unit_by_id = {str(u["id"]): u for u in game_state["units"]}
    cached_zones = game_state.get(_OBJECTIVE_ZONES_CACHE_KEY)  # get allowed : absence = 1er appel
    zones_union: Optional[FrozenSet[Tuple[int, int]]] = None
    if (
        cached_zones is not None
        and len(hex_sets) == len(cached_zones[1])
        and all(recu is connu for recu, (_id, connu) in zip(hex_sets, cached_zones[1]))
    ):
        zones_union = cached_zones[2]

    contributions: Dict[str, Tuple[int, List[int]]] = {}
    for unit_id in units_cache:
        uid = str(unit_id)
        unit = unit_by_id.get(uid)
        if not unit:
            raise KeyError(f"Unit {unit_id} missing from game_state['units']")
        # Regle 01.07 : tant qu une unite est battle-shocked, la caracteristique OC de TOUTES
        # ses figurines est modifiee a '-' (02.02) — « unable to control objectives at all ».
        # Le drapeau est porte par l unite (roll_battle_shock, etape 08.03), donc l escouade
        # entiere n apporte AUCUN controle (14.02). Cle exigee : elle est posee a la
        # construction de chaque unite ; son absence est un etat corrompu, pas un defaut.
        if bool(require_key(unit, "battle_shocked")):
            continue
        oc = unit_effective_oc(unit)
        if oc <= 0:
            continue
        unit_player = int(require_key(unit, "player"))
        if unit_player not in (1, 2):
            raise ValueError(f"Unexpected unit player id: {unit_player}")
        models_in_area = [0] * len(hex_sets)
        for footprint in iter_living_model_footprints(game_state, unit_id):
            if zones_union is not None and footprint.isdisjoint(zones_union):
                continue
            for i, zone in enumerate(hex_sets):
                if not footprint.isdisjoint(zone):
                    models_in_area[i] += 1
        if any(models_in_area):
            contributions[uid] = (unit_player, [oc * n for n in models_in_area])
    return contributions


def fold_control_contributions(
    contributions: Iterable[Tuple[int, List[int]]], n_zones: int
) -> List[Tuple[int, int]]:
    """Replie des contributions en ``(OC joueur 1, OC joueur 2)`` par zone.

    Le pli est ICI et nulle part ailleurs : ``objective_control_contributions`` rend une
    decomposition, et chaque appelant qui la compose — la somme totale, le surplus d encombrement
    des bots qui saute une escouade, le prochain contrefactuel — la replie avec cette fonction. Le
    parametre est un ITERABLE de contributions et non le dictionnaire : selectionner QUI entre dans
    le pli est l affaire de l appelant, et ca reste une comprehension d une ligne chez lui.
    """
    sums: List[List[int]] = [[0, 0] for _ in range(n_zones)]
    for unit_player, par_zone in contributions:
        camp = 0 if unit_player == 1 else 1
        for i, oc in enumerate(par_zone):
            sums[i][camp] += oc
    return [(p1, p2) for p1, p2 in sums]


def sum_objective_control_oc_multi(
    game_state: Dict[str, Any], hex_sets: List[Set[Tuple[int, int]]]
) -> List[Tuple[int, int]]:
    """``(OC joueur 1, OC joueur 2)`` par zone — l addition des contributions par escouade.

    Toute la regle est dans ``objective_control_contributions``, tout le pli dans
    ``fold_control_contributions`` : il ne reste ici que leur composition.
    """
    return fold_control_contributions(
        objective_control_contributions(game_state, hex_sets).values(), len(hex_sets)
    )


# ===========================================================================================
# CAPACITÉS DE FACTION — Waaagh! (ORKS) et Oath of Moment (ADEPTUS ASTARTES), chantier 03
# ===========================================================================================
#
# SOURCES : `Documentation/40k_rules/Armageddon/Waaagh!.txt` et `.../OathOfMoment.txt`. En cas de
# divergence entre ce module et ces fichiers, les fichiers font foi.
#
# POURQUOI ICI et pas dans un module dédié : c'est de l'ÉTAT DE PARTIE par joueur, exactement
# comme `command_points` juste au-dessus — même forme (`Dict[int, ...]` à clés 1/2), même
# écrivain unique par mutation, même journalisation. Un module séparé aurait créé un second
# endroit où chercher « où vit l'état du joueur ».
#
# Les EFFETS, eux, vivent chez ceux qui les appliquent (seuils de sauvegarde, jets de touche,
# éligibilité de charge) : ce bloc ne fait que dire QUI a quoi, et à partir de quand.

#: Mot-clé de faction qui porte Waaagh! (« If your Army Faction is ORKS »).
WAAAGH_FACTION_KEYWORD = "ORKS"
#: Mot-clé de faction qui porte Oath of Moment (« If your Army Faction is ADEPTUS ASTARTES »).
OATH_FACTION_KEYWORD = "ADEPTUS_ASTARTES"
#: Capacités de FACTION (08.04) : id de règle de `config/unit_rules.json` → mot-clé de faction
#: qui la porte. Ces capacités ne figurent dans AUCUN `UNIT_RULES` de datasheet — c'est le
#: keyword qui les donne (`unit_has_waaagh_ability`, `unit_has_oath_ability`). Tout lecteur qui
#: valide un usage de règle contre les règles de datasheet (analyzer §1.7, `rule_to_units`) doit
#: les retrouver ici, sinon il compte comme faute un usage parfaitement légal.
FACTION_ABILITY_KEYWORD_BY_RULE_ID = {
    "waaagh": WAAAGH_FACTION_KEYWORD,
    "oath_of_moment": OATH_FACTION_KEYWORD,
}
#: Sauvegarde invulnérable accordée par un Waaagh! actif (« have a 5+ invulnerable save »).
WAAAGH_INVUL_SAVE = 5
#: « Add 1 to the Strength and Attacks characteristics of melee weapons » — un seul et même
#: bonus, d'où une seule constante : les désolidariser laisserait croire qu'ils peuvent différer.
WAAAGH_MELEE_BONUS = 1
#: +1 au jet de BLESSURE contre la cible d'Oath, quand la clause de détachement est remplie.
OATH_WOUND_ROLL_BONUS = 1
#: Nom d'affichage de la capacité, tel qu'il apparaît dans `step.log` et dans le log de partie.
#: Écrit ICI et pas dans le formateur : c'est le MÊME nom que le frontend et l'analyzer
#: cherchent, et deux copies dériveraient. Une capacité de FACTION n'a pas de `displayName` de
#: datasheet à interroger — elle n'appartient à aucune règle d'unité.
OATH_ABILITY_DISPLAY_NAME = "Oath of Moment"
#: JUMEAU du nom ci-dessus, pour Waaagh!. Même raison d'être ici : c'est la clé que le frontend
#: normalise pour retrouver la description de la règle (`config/unit_rules.json`, entrée
#: `waaagh`), et l'orthographe — le `!` compris — doit être unique. Elle était écrite en dur
#: dans le log de charge, hors de portée des autres sites d'effet.
WAAAGH_ABILITY_DISPLAY_NAME = "Waaagh!"

#: Sous-factions qui ANNULENT le +1 Wound d'Oath of Moment (« your army does not include one or
#: more units with the BLOOD ANGELS, DARK ANGELS, DEATHWATCH or SPACE WOLVES keywords, or one or
#: more units from those factions' Munitorum Field Manual sections »). Les deux moitiés de la
#: phrase désignent le même ensemble d'unités dans ce moteur : une unité d'une de ces sections
#: porte le keyword correspondant. Balayage réel de l'armée, pas une option de config.
#:
#: ⚠️ Écrits dans la forme NORMALISÉE (`_normalize_keyword`), pas dans l'orthographe des
#: datasheets : c'est à cette forme que les mots-clés lus sont comparés.
OATH_EXCLUDING_KEYWORDS = frozenset({
    "BLOOD_ANGELS", "DARK_ANGELS", "DEATHWATCH", "SPACE_WOLVES",
})


def _normalize_keyword(raw: Any) -> str:
    """Un keyword sous sa forme comparable : MAJUSCULES, espaces et tirets en `_`.

    Les datasheets écrivent « ADEPTUS ASTARTES » et « adeptus astartes » indifféremment, et les
    entrées sont tantôt des dicts `{"keywordId": ...}` (UNIT_KEYWORDS / FACTION_KEYWORDS après
    `ai/unit_registry`), tantôt des chaînes nues (fixtures de test).

    ⚠️ La forme rendue est EXACTEMENT celle d'`attack_sequence.unit_keywords_upper` — jusqu'au
    remplacement des tirets. Ce n'est pas un détail : les deux lecteurs interrogent le MÊME
    champ (`FACTION_KEYWORDS`), l'un pour [ANTI-X] 24.03, l'autre pour les capacités de faction.
    Deux normalisations concurrentes donnaient deux jeux de jetons non comparables — une
    datasheet écrivant « BLOOD-ANGELS » aurait déclenché [ANTI] et pas la clause d'Oath, sans
    que rien ne lève. Toute constante de mot-clé s'écrit donc dans CETTE forme.
    """
    if isinstance(raw, dict):
        raw = require_key(raw, "keywordId")
    return "_".join(str(raw).strip().upper().replace("-", " ").split())


def unit_faction_keywords(unit: Dict[str, Any]) -> frozenset:
    """Mots-clés de FACTION d'une unité (19.03 : union des composants d'une unité attachée).

    Aucune valeur par défaut masquante : « pas de mot-clé de faction déclaré » et « ensemble
    vide » sont le MÊME fait métier — l'unité n'appartient à aucune faction connue, donc aucune
    capacité de faction ne la vise. C'est mot pour mot la convention déjà portée par
    `attack_sequence.unit_keywords_upper` pour [ANTI-X], et elle est sûre pour la même raison :
    la clé est posée par les DEUX constructeurs du moteur (`create_unit`,
    `_build_enhanced_unit`), donc une unité de production l'a toujours. Ce qui garantit qu'une
    unité de ROSTER ne perd pas sa faction en silence est le `require_key` de
    `_build_enhanced_unit`, en amont — pas une exception ici.
    """
    return frozenset(
        _normalize_keyword(entry)
        for entry in unit.get("FACTION_KEYWORDS", ())  # get allowed : absence == aucune faction
    )


def unit_has_waaagh_ability(game_state: Dict[str, Any], unit: Dict[str, Any]) -> bool:
    """« Units from your army WITH THIS ABILITY » — Waaagh! est porté par le keyword ORKS.

    DEUX conditions, et la première est la Faction d'Armée. La capacité est écrite « If your Army
    Faction is ORKS » : elle n'existe pas du tout dans une armée qui n'est pas orke, donc une
    unité ORKS invitée dans une armée d'une autre faction ne la porte pas non plus. Le prédicat
    reste ensuite par UNITÉ : dans une armée orke, une unité non-ORKS (alliée, invitée) ne gagne
    ni la charge après Advance, ni le +1 S/A, ni l'invulnérable.
    """
    if WAAAGH_FACTION_KEYWORD not in unit_faction_keywords(unit):
        return False
    return army_faction(game_state, int(require_key(unit, "player"))) == WAAAGH_FACTION_KEYWORD


def unit_has_oath_ability(game_state: Dict[str, Any], unit: Dict[str, Any]) -> bool:
    """« Each time A MODEL WITH THIS ABILITY makes an attack » — porté par ADEPTUS ASTARTES.

    Jumeau exact de `unit_has_waaagh_ability` : même nature de prédicat, même granularité, même
    subordination à la Faction d'Armée. C'est ce qui empêche le `WolfGuardTerminator` invité dans
    une armée TYRANIDS de relancer ses jets de touche — son armée n'a pas d'Oath of Moment.
    """
    if OATH_FACTION_KEYWORD not in unit_faction_keywords(unit):
        return False
    return army_faction(game_state, int(require_key(unit, "player"))) == OATH_FACTION_KEYWORD


def army_has_oath_ability(game_state: Dict[str, Any], player: int) -> bool:
    """L'armée de ce joueur a-t-elle l'Oath of Moment — « If your Army Faction is ADEPTUS ASTARTES ».

    La Faction d'ARMÉE déclarée, jamais la présence du mot-clé quelque part dans le roster
    (cf. `army_faction`). Extrait en fonction parce qu'il a désormais DEUX appelants — l'armement
    de la désignation (`command_handlers.arm_oath_selection`) et l'observation — et que les deux
    doivent répondre la même chose : un bit d'obs qui dirait « pas d'Oath » là où le moteur
    arrête la phase pour en demander un serait une observation fausse.

    C'est aussi la GARDE d'appel d'`oath_wound_bonus_applies`, qui LÈVE si
    `uses_codex_detachment` manque — champ légitimement absent d'une partie sans Astartes.
    """
    return army_faction(game_state, int(player)) == OATH_FACTION_KEYWORD


def army_keywords(game_state: Dict[str, Any], player: int) -> frozenset:
    """TOUS les mots-clés présents dans l'armée d'un joueur — faction ET unité, morts compris.

    LES DEUX TABLES, et ce n'est pas une précaution. La règle écrit « units with the BLOOD
    ANGELS, DARK ANGELS, DEATHWATCH or SPACE WOLVES KEYWORDS » sans dire dans quelle catégorie
    ils vivent — et ce dépôt les répartit entre `FACTION_KEYWORDS` (la faction) et
    `UNIT_KEYWORDS` (le reste). N'interroger que la première rendait la clause d'exclusion
    d'Oath structurellement MORTE : aucune datasheet ne pouvait la déclencher, quel que soit le
    roster (`/code-review` du 2026-08-05, finding 1). Un mot-clé déclaré du « mauvais » côté ne
    doit pas décider silencieusement d'un +1 au jet de blessure.

    Union et non intersection : la question posée est « mon armée contient-elle X ? », jamais
    « toutes mes unités sont-elles X ? ».

    Les unités détruites comptent : « your army does not INCLUDE one or more units with the
    BLOOD ANGELS […] keywords » décrit la LISTE D'ARMÉE, pas ce qui reste sur la table. Faire
    dépendre le +1 Wound de la survie d'un détachement le rendrait intermittent en cours de
    partie, ce que la règle ne dit nulle part.
    """
    player_int = int(player)
    keywords: set = set()
    for unit in require_key(game_state, "units"):
        if int(require_key(unit, "player")) != player_int:
            continue
        keywords |= unit_faction_keywords(unit)
        keywords |= {
            _normalize_keyword(entry)
            for entry in unit.get("UNIT_KEYWORDS", ())  # get allowed : absence == aucun keyword
        }
    return frozenset(keywords)


def army_faction(game_state: Dict[str, Any], player: int) -> str:
    """Faction d'ARMÉE DÉCLARÉE de ce joueur — « If your Army Faction is ORKS / ADEPTUS ASTARTES ».

    La Faction d'Armée est UNE déclaration de la liste (« Army Faction: Tyranids » en tête de
    roster), pas un mot-clé présent quelque part dans l'armée. Cette fonction lisait auparavant
    l'UNION des `FACTION_KEYWORDS` de toutes les unités du joueur, ce qui est un test différent
    et FAUX dès qu'une figurine invitée est présente : le roster tyranide de
    `scenario_pvp_test.json` contient deux `WolfGuardTerminator` (ADEPTUS ASTARTES), et son
    joueur se voyait donc demander une désignation d'Oath of Moment à chaque tour — mesuré sur
    4 tours avant correction. Le jumeau valait pour Waaagh! : une unité ORKS invitée aurait fait
    appeler le Waaagh! par une armée qui n'est pas orke.

    Déclarée et jamais devinée, pour la même raison qu'`uses_codex_detachment` juste en dessous :
    la valeur n'est pas dérivable de ce qui est sur la table (une armée peut inviter des unités
    d'une autre faction sans changer de Faction d'Armée), et la deviner ferait apparaître ou
    disparaître une capacité d'armée entière sans que personne ne l'ait décidé.

    Rendue NORMALISÉE (`_normalize_keyword`) : la config écrit « ADEPTUS ASTARTES » comme les
    datasheets, les constantes du module s'écrivent `ADEPTUS_ASTARTES`, et une seule des deux
    formes doit exister au moment de la comparaison.
    """
    player_int = int(player)
    config = require_key(game_state, "config")
    by_player = config.get("army_faction")  # get allowed : absence = clé à exiger ci-dessous
    if by_player is None:
        raise KeyError(
            "config['army_faction'] est absent : les capacites de faction (Waaagh!, Oath of "
            "Moment) demandent la Faction d'Armee DECLAREE de chaque joueur (« If your Army "
            "Faction is … »). Declarer le champ dans la config d'armee / de scenario, par ex. "
            "{\"1\": \"ADEPTUS ASTARTES\", \"2\": \"TYRANIDS\"} — aucune valeur par defaut n'est "
            "admise, et la deduire des unites presentes est ce qui a produit le defaut corrige ici."
        )
    # UNE seule forme acceptée — le dict par joueur — exactement comme `uses_codex_detachment` :
    # un scénario décrit DEUX armées, et une forme scalaire ferait jouer les deux camps sous la
    # même Faction d'Armée. Les clés JSON sont des chaînes, d'où la lecture par `str`.
    if not isinstance(by_player, dict):
        raise TypeError(
            f"config['army_faction'] doit etre un dict par joueur "
            f"(ex. {{\"1\": \"ADEPTUS ASTARTES\", \"2\": \"TYRANIDS\"}}), "
            f"recu {type(by_player).__name__}"
        )
    if str(player_int) not in by_player:
        raise KeyError(
            f"config['army_faction'] n'a pas d'entree pour le joueur {player_int} : {by_player!r}"
        )
    declared = by_player[str(player_int)]
    if not isinstance(declared, str) or not declared.strip():
        raise TypeError(
            f"config['army_faction'][{str(player_int)!r}] doit etre un mot-cle de faction non "
            f"vide, recu {declared!r} ({type(declared).__name__})"
        )
    normalized = _normalize_keyword(declared)
    # GARDE ANTI-COQUILLE. Une faction déclarée que PERSONNE ne porte ne peut pas être la Faction
    # d'Armée de ce joueur : c'est une faute de frappe ou un fichier d'armée mal recopié. Sans
    # cette garde, « ADPETUS ASTARTES » éteindrait l'Oath of Moment de toute une partie en
    # silence — l'échec exactement inverse de celui qu'on corrige, et tout aussi invisible.
    #
    # Elle ne se prononce QUE si le joueur a des unités. Une armée VIDE n'infirme rien : c'est
    # l'état normal d'un camp anéanti, et celui du camp adverse d'Endless Duty entre deux vagues
    # (les unités sont créées à la volée). Lever là serait une panne inventée, pas une coquille.
    player_units = [
        unit for unit in require_key(game_state, "units")
        if int(require_key(unit, "player")) == player_int
    ]
    if player_units and not any(
        normalized in unit_faction_keywords(unit) for unit in player_units
    ):
        raise ValueError(
            f"config['army_faction'][{str(player_int)!r}] declare {declared!r}, mais aucune unite "
            f"du joueur {player_int} ne porte ce mot-cle de faction."
        )
    return normalized


def initial_faction_ability_state() -> Dict[str, Any]:
    """État de départ des deux capacités de faction, pour les deux joueurs.

    Renvoie les quatre clés d'un coup pour qu'aucun point d'entrée du moteur (reset gym, chargement
    de scénario, construction PvP) ne puisse en poser trois sur quatre — c'est le mode de
    défaillance que des initialisations dispersées produisent.

      - `waaagh_called`  : « ONCE PER BATTLE » — verrou 1×/partie, jamais remis à False ;
      - `waaagh_active`  : Waaagh! en vigueur, jusqu'au début de MA prochaine phase de commandement ;
      - `oath_target`    : id de l'unité ennemie désignée, ou None ;
      - `pending_oath_selection` : joueur qui DOIT désigner sa cible (la désignation n'est pas
        optionnelle), ou None.
    """
    return {
        "waaagh_called": {1: False, 2: False},
        "waaagh_active": {1: False, 2: False},
        "oath_target": {1: None, 2: None},
        "pending_oath_selection": None,
    }


def _player_flag_map(game_state: Dict[str, Any], key: str) -> Dict[int, Any]:
    """Accès strict à une des tables par joueur ci-dessus. Absence = état non initialisé."""
    table = require_key(game_state, key)
    if not isinstance(table, dict):
        raise TypeError(f"game_state[{key!r}] doit etre un dict par joueur, recu {type(table).__name__}")
    return table


def waaagh_is_available(game_state: Dict[str, Any], player: int) -> bool:
    """True si ce joueur peut ENCORE appeler son Waaagh! (once per battle, non encore appelé).

    Ne dit rien de la faction ni de la phase : c'est le seul verrou d'usage. L'appelant (08.04)
    ajoute « mon armée est ORKS » et « c'est le début de MA phase de commandement ».
    """
    return not bool(_player_flag_map(game_state, "waaagh_called")[int(player)])


def waaagh_is_active(game_state: Dict[str, Any], player: int) -> bool:
    """True si le Waaagh! de ce joueur est EN VIGUEUR à cet instant.

    Il l'est aussi pendant le tour ADVERSE : « until the start of your next Command phase »
    enjambe le tour de l'adversaire. Ne jamais remplacer cette lecture par « c'est mon tour et
    j'ai appelé » — c'est exactement l'erreur que le verrou de durée existe pour attraper.
    """
    return bool(_player_flag_map(game_state, "waaagh_active")[int(player)])


def call_waaagh(game_state: Dict[str, Any], player: int) -> None:
    """ÉCRIVAIN UNIQUE de l'appel du Waaagh!. Un second appel LÈVE.

    Le masque ferme l'action après le premier appel ; si elle arrivait quand même, c'est que le
    masque et l'état ont divergé — un état incohérent, jamais un cas à absorber en silence.
    """
    player_int = int(player)
    called = _player_flag_map(game_state, "waaagh_called")
    if called[player_int]:
        raise RuntimeError(
            f"call_waaagh: le joueur {player_int} a deja appele son Waaagh! (once per battle). "
            f"Le masque n'aurait pas du rouvrir cette action."
        )
    called[player_int] = True
    _player_flag_map(game_state, "waaagh_active")[player_int] = True
    from engine.game_utils import add_console_log

    add_console_log(game_state, f"P{player_int} calls a WAAAGH! (active until their next command phase)")


def oath_target_id(game_state: Dict[str, Any], player: int) -> Optional[str]:
    """Id de l'unité ennemie désignée par l'Oath of Moment de ce joueur, ou None."""
    target = _player_flag_map(game_state, "oath_target")[int(player)]
    return None if target is None else str(target)


def set_oath_target(game_state: Dict[str, Any], player: int, unit_id: str) -> None:
    """ÉCRIVAIN UNIQUE de la cible d'Oath. Exige une unité ENNEMIE VIVANTE — sinon LÈVE.

    « select one unit from your opponent's army » : désigner une unité à soi, ou une unité morte,
    n'est pas un choix légal. Le masque ne les ouvre pas ; la garde est là pour que le PvP et les
    fixtures ne puissent pas produire un état que le gym ne produirait jamais.
    """
    player_int = int(player)
    target_id = str(unit_id)
    from engine.game_utils import get_unit_by_id
    from engine.phase_handlers.shared_utils import is_unit_alive

    # `get_unit_by_id` et pas une boucle : l'index `unit_by_id` est la convention du dépôt pour
    # « id -> unité » (O(1), même normalisation `str`). Le jour où sa clé change, ce site suit.
    target_unit = get_unit_by_id(game_state, target_id)
    if target_unit is None:
        raise KeyError(f"set_oath_target: unite {target_id!r} introuvable")
    if int(require_key(target_unit, "player")) == player_int:
        raise ValueError(
            f"set_oath_target: l'unite {target_id!r} appartient au joueur {player_int} — "
            f"Oath of Moment designe « one unit from your OPPONENT's army »."
        )
    if not is_unit_alive(target_id, game_state):
        raise ValueError(f"set_oath_target: l'unite {target_id!r} est detruite")
    _player_flag_map(game_state, "oath_target")[player_int] = target_id
    game_state["pending_oath_selection"] = None
    from engine.game_utils import add_console_log

    add_console_log(game_state, f"P{player_int} declares Oath of Moment target: unit {target_id}")


def expire_faction_abilities_for_player(game_state: Dict[str, Any], player: int) -> None:
    """« Until the START OF YOUR NEXT COMMAND PHASE » — la seule extinction des deux capacités.

    Appelée à l'OUVERTURE de la phase de commandement du joueur concerné, avant que la nouvelle
    décision ne soit posée. PAS en fin de tour : les deux effets doivent survivre au tour adverse
    (un Waaagh! appelé au tour N protège encore contre le tir adverse du tour N, et la cible
    d'Oath reste désignée pendant que l'adversaire joue).

    `waaagh_called` n'est PAS remis à False : il porte le « once per battle », pas la durée.

    Purge AUSSI les décisions de 08.04 restées en attente pour ce joueur — LES DEUX, et c'est
    le point important. Elles ne devraient pas exister (08.04 les repose juste après), mais si
    un tour précédent s'est terminé sans qu'elles soient jouées (siège sans décideur, partie
    rechargée), les laisser vivre est fatal de deux façons distinctes :

      - `pending_oath_selection` : la nouvelle désignation se poserait par-dessus l'ancienne,
        et la phase resterait arrêtée sur un choix dont personne ne sait de quel tour il date ;
      - `pending_agent_decision` de type `waaagh_call` : `set_pending_agent_decision` LÈVE quand
        une décision est déjà en attente. La phase de commandement ne se contenterait pas de
        rester bloquée, elle CRASHERAIT — et c'est le jumeau que la première version de cette
        purge avait oublié (`/code-review` du 2026-08-05, finding 3).

    Une décision d'un AUTRE type (`rule_choice`) n'est pas touchée : elle n'appartient pas à
    08.04, elle a son propre cycle de vie (`pending_rule_choice_queue`).
    """
    from engine.agent_decision import clear_pending_agent_decision, read_pending_agent_decision
    from engine.phase_handlers.command_handlers import COMMAND_PHASE_DECISION_TYPES

    player_int = int(player)
    _player_flag_map(game_state, "waaagh_active")[player_int] = False
    _player_flag_map(game_state, "oath_target")[player_int] = None
    pending_oath = game_state.get("pending_oath_selection")  # get allowed : None = aucune
    if pending_oath is not None and int(pending_oath) == player_int:
        game_state["pending_oath_selection"] = None
    pending_decision = read_pending_agent_decision(game_state)
    if (
        pending_decision is not None
        and str(require_key(pending_decision, "type")) in COMMAND_PHASE_DECISION_TYPES
        and int(require_key(pending_decision, "player")) == player_int
    ):
        clear_pending_agent_decision(game_state)


def oath_wound_bonus_applies(game_state: Dict[str, Any], player: int) -> bool:
    """Clause conditionnelle du +1 Wound d'Oath of Moment — ses DEUX moitiés.

    1. « If you are using a Codex: Space Marines Detachment » → aucun système de détachement
       n'existe dans le moteur ; la valeur est déclarée par la config d'armée
       (`uses_codex_detachment`), donnée métier que l'utilisateur possède et que le moteur ne peut
       pas déduire. ABSENTE = ERREUR EXPLICITE, jamais un défaut. Le jour où les détachements
       existent, le champ devient calculé et ce code ne bouge pas.
    2. « and your army does not include one or more units with the BLOOD ANGELS, DARK ANGELS,
       DEATHWATCH or SPACE WOLVES keywords » → balayage RÉEL de l'armée, ici et maintenant.

    La relance de touche, elle, ne dépend d'AUCUNE des deux : elle s'applique toujours.

    ORDRE DES DEUX MOITIÉS : le détachement d'abord. C'est un lookup de config (~0,3 µs) là où
    le balayage de l'armée en coûte ~24 (toutes les unités, tous leurs mots-clés) — et ce
    prédicat est évalué par INTENT D'ATTAQUE contre la cible d'Oath. Dès que le détachement est
    à False, le balayage n'a pas lieu.
    """
    if not uses_codex_detachment(game_state, int(player)):
        return False
    return not (OATH_EXCLUDING_KEYWORDS & army_keywords(game_state, player))


def uses_codex_detachment(game_state: Dict[str, Any], player: int) -> bool:
    """Moitié « Codex: Space Marines Detachment » de la clause, lue dans la config d'armée.

    Champ OBLIGATOIRE dès qu'un joueur a une armée ADEPTUS ASTARTES : son absence lève. La
    valeur n'est pas devinable, et la deviner ferait apparaître ou disparaître un +1 au jet de
    blessure sans que personne ne l'ait décidé.
    """
    player_int = int(player)
    config = require_key(game_state, "config")
    by_player = config.get("uses_codex_detachment")  # get allowed : absence = clé à exiger ci-dessous
    if by_player is None:
        raise KeyError(
            "config['uses_codex_detachment'] est absent alors qu'une armee ADEPTUS ASTARTES est "
            "en jeu : le +1 au jet de blessure d'Oath of Moment en depend (« If you are using a "
            "Codex: Space Marines Detachment »). Declarer le champ dans la config d'armee / de "
            "scenario — aucune valeur par defaut n'est admise, elle changerait les jets."
        )
    # UNE seule forme acceptée : le dict par joueur. Une forme scalaire avait été prévue « au
    # cas où » — aucun des 24 fichiers qui déclarent la clé ne la produit, et accepter deux
    # formats pour une donnée qui décide d'un +1 au jet de blessure double les chemins à tester
    # sans rien couvrir. Les clés JSON sont des chaînes, d'où la lecture par `str`.
    if not isinstance(by_player, dict):
        raise TypeError(
            f"config['uses_codex_detachment'] doit etre un dict par joueur "
            f"(ex. {{\"1\": true, \"2\": true}}), recu {type(by_player).__name__}"
        )
    if str(player_int) not in by_player:
        raise KeyError(
            f"config['uses_codex_detachment'] n'a pas d'entree pour le joueur {player_int} : "
            f"{by_player!r}"
        )
    declared = by_player[str(player_int)]
    # BOOLEEN STRICT, pas `bool(...)` : `bool("false")` vaut True. Une config qui ecrit la chaine
    # "false" — au clavier, ou par un export qui stringifie — rendrait le +1 au jet de blessure
    # que son auteur venait explicitement de couper, sans que rien ne le signale.
    if not isinstance(declared, bool):
        raise TypeError(
            f"config['uses_codex_detachment'][{str(player_int)!r}] doit etre un booleen, recu "
            f"{declared!r} ({type(declared).__name__})"
        )
    return declared


# --- Application des effets : QUI est concerné par quoi, à cet instant -----------------------
#
# Ces prédicats sont la SEULE porte d'entrée des effets de faction dans la résolution. Les
# consommateurs (seuil de sauvegarde, jets de touche/blessure, éligibilité de charge) ne lisent
# jamais `waaagh_active` ni `oath_target` directement : ils poseraient chacun leur version de
# « et cette unité porte-t-elle la capacité ? », et c'est exactement là que les jumeaux
# divergent.


def waaagh_applies_to_unit(game_state: Dict[str, Any], unit: Dict[str, Any]) -> bool:
    """True si le Waaagh! de son contrôleur est actif ET que cette unité porte la capacité.

    Les DEUX conditions, toujours : « the Waaagh! is active for your army AND units from your
    army WITH THIS ABILITY ». Une unité non-ORKS d'une armée orke ne gagne rien.

    SORTIE ANTICIPÉE « aucun Waaagh! nulle part ». Ce prédicat est évalué par BLESSURE
    (`_resolve_one_manual_wound`), par figurine de la cible (`_build_alloc_groups`) et par entité
    observée à CHAQUE step gym ; `unit_has_waaagh_ability` y CONSTRUIT un frozenset normalisé,
    alors que dans toute partie sans Orks — et dans tous les tours d'une partie orke avant
    l'appel — la réponse est « non ». Mesuré : 0,85 µs sans la sortie, 0,33 µs avec.
    Le test porte sur la table ENTIÈRE et non sur le camp de l'unité : il répond donc sans lire
    `unit["player"]`, ce qui garde le prédicat utilisable là où le camp n'est pas la question.
    """
    active = _player_flag_map(game_state, "waaagh_active")
    if not any(active.values()):
        return False
    return unit_has_waaagh_ability(game_state, unit) and bool(
        active[int(require_key(unit, "player"))]
    )


def effective_invul_save(
    game_state: Dict[str, Any], unit: Dict[str, Any], base_invul_save: int
) -> int:
    """Sauvegarde invulnérable EFFECTIVE d'une figurine de `unit`, Waaagh! compris.

    « Models from your army with this ability have a 5+ invulnerable save. » C'est un OCTROI,
    pas un plafond : une figurine qui a déjà une 4+ (Warboss, BannerNob) la GARDE — d'où le
    `min`. Une figurine sans invulnérable (sentinelle 7) passe à 5+, ce qui est tout l'effet.

    `base_invul_save` est passé par l'appelant plutôt que relu ici : la valeur vit sur la
    FIGURINE (`models_cache`), pas sur l'unité, et c'est la figurine qui encaisse.
    """
    if not waaagh_applies_to_unit(game_state, unit):
        return int(base_invul_save)
    return min(int(base_invul_save), WAAAGH_INVUL_SAVE)


def waaagh_melee_bonus(game_state: Dict[str, Any], unit: Dict[str, Any]) -> int:
    """+1 aux caractéristiques de Force ET d'Attaques des armes de mêlée, ou 0.

    Un seul prédicat pour les deux caractéristiques : la règle les accorde d'un seul tenant, et
    en faire deux fonctions laisserait croire qu'un site peut appliquer l'une sans l'autre —
    c'est précisément ce genre d'asymétrie que le jumeau tir/mêlée produit.
    """
    return WAAAGH_MELEE_BONUS if waaagh_applies_to_unit(game_state, unit) else 0


def unit_is_oath_target_of(
    game_state: Dict[str, Any], attacker_unit: Dict[str, Any], target_unit_id: str
) -> bool:
    """True si `target_unit_id` est la cible d'Oath désignée par le contrôleur de l'attaquant,
    ET si l'attaquant porte la capacité.

    « Each time A MODEL WITH THIS ABILITY makes an attack that TARGETS YOUR Oath of Moment
    target » : les deux moitiés. Tester la seule désignation ferait bénéficier de la relance une
    unité alliée d'une autre faction ; tester la seule capacité la ferait s'appliquer à toutes
    les cibles.

    MÊME SORTIE ANTICIPÉE que `waaagh_applies_to_unit`, et pour la même raison : sans aucune
    désignation en cours — toute partie sans Adeptus Astartes, et chaque tour avant 08.04 — la
    construction du frozenset de l'attaquant serait perdue, par INTENT D'ATTAQUE.
    """
    targets = _player_flag_map(game_state, "oath_target")
    if not any(target is not None for target in targets.values()):
        return False
    attacker_player = int(require_key(attacker_unit, "player"))
    if oath_target_id(game_state, attacker_player) != str(target_unit_id):
        return False
    return unit_has_oath_ability(game_state, attacker_unit)


def oath_wound_roll_bonus(
    game_state: Dict[str, Any], attacker_unit: Dict[str, Any], target_unit_id: str
) -> int:
    """+1 au jet de blessure contre la cible d'Oath, ou 0 — clause de détachement comprise."""
    if not unit_is_oath_target_of(game_state, attacker_unit, target_unit_id):
        return 0
    if not oath_wound_bonus_applies(game_state, int(require_key(attacker_unit, "player"))):
        return 0
    return OATH_WOUND_ROLL_BONUS


def unit_can_charge_after_advance(game_state: Dict[str, Any], unit: Dict[str, Any]) -> bool:
    """11.02 « eligible to declare a charge in a turn in which they Advanced ».

    DEUX sources, et c'est un OU : la capacité de datasheet `charge_after_advance` (Assault,
    Vanguard…) et le Waaagh! actif. Un seul point de lecture pour les deux, sinon la moitié des
    sites d'appel connaîtrait une source et pas l'autre.
    """
    from engine.phase_handlers.shared_utils import _unit_has_rule_effect

    if _unit_has_rule_effect(unit, "charge_after_advance"):
        return True
    return waaagh_applies_to_unit(game_state, unit)
