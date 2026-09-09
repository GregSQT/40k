#!/usr/bin/env python3
"""Les 5 bits de mots-clés de CATÉGORIE de l'observation d'entité ↔ `UNIT_KEYWORDS`.

`kw_infantry`, `kw_vehicle`, `kw_monster`, `kw_fly`, `kw_psyker` sont émis par
`observation_builder._encode_unit_entity` depuis `unit_keywords_upper` — la source
qu'exécute la résolution de [ANTI-X] 24.03, et non `compute_hideable`.

Avant eux, l'observation décrivait le keyword ciblé par [ANTI-X] côté ARME (`wpn_rule_ids`,
vocabulaire `WEAPON_RULE_BITS + ANTI_RULE_IDS`) sans jamais dire si la CIBLE le portait : la
règle était structurellement inapprenable. Même trou pour le volet MONSTER/VEHICLE de 10.06 et
pour les gates de terrain 13.06/13.08/13.09.

Trois défauts sont verrouillés ici :

1. **Permutation du mapping** — chaque mot-clé doit allumer SON bit et lui seul. Sans le « lui
   seul », deux bits lisant le même mot-clé resteraient indétectables.
2. **Entités ennemies muettes** — le bit doit être émis pour TOUTE entité, pas seulement pour
   l'unité active : c'est la cible d'un tir qui décide de [ANTI-X], jamais le tireur.
3. **Absence silencieuse de `UNIT_KEYWORDS`** — `unit_keywords_upper` rend sciemment un ensemble
   vide sur une unité sans la clé ; ici cela écrirait « aucune catégorie » sans rien lever.
"""

from __future__ import annotations

import ast
import json
import pathlib
from typing import Any, Dict, List, Set, Tuple
from unittest.mock import patch

import pytest

from ai.unit_registry import UnitRegistry
from engine.game_state import _FLOOR_CAPABLE_KEYWORDS, _HIDEABLE_KEYWORDS
from engine.observation_builder import ObservationBuilder
from engine.observation_entities import UNIT_BIN_FIELDS, unit_bin_index
from engine.phase_handlers.attack_sequence import ANTI_RULE_IDS, ANTI_RULE_PREFIX
from engine.phase_handlers.shared_utils import _MONSTER_OR_VEHICLE_KEYWORDS
from engine.w40k_core import W40KEngine
from shared.data_validation import ConfigurationError
from tests.unit.engine._config_helpers import build_engine_config

ROOT = pathlib.Path(__file__).resolve().parents[3]

#: bit d'observation → mot-clé de datasheet qui doit l'allumer.
BIT_TO_KEYWORD = {
    "kw_infantry": "INFANTRY",
    "kw_vehicle": "VEHICLE",
    "kw_monster": "MONSTER",
    "kw_fly": "FLY",
    "kw_psyker": "PSYKER",
}

#: Mots-clés que le moteur consomme SANS bit d'observation — exclusions ACTÉES, pas oubliées.
#:
#: `BEASTS` et `SWARM` ouvrent les mêmes portes que `INFANTRY` (13.06 via
#: `_FLOOR_CAPABLE_KEYWORDS`, 13.08/13.09 via `_HIDEABLE_KEYWORDS`) mais aucune datasheet JOUÉE
#: n'en porte : MESURÉ le 2026-09-09 sur les 42 unités résolues depuis
#: `config/agents/*/rosters/**` ET `config/agents/_p2_rosters/**` (agents et adversaires), zéro
#: porteur, et zéro écart entre « peut se cacher » et `INFANTRY` sur ces 42. Sur ce périmètre un
#: bit dédié vaudrait colonne pour colonne la copie de `kw_infantry` : 32 scalaires de plus
#: (K_ALLY_SLOTS + K_ENEMY_SLOTS) et un retrain `--new` pour zéro information apprenable.
#:
#: Ce n'est PAS une dette reportée : c'est `test_no_played_roster_unit_carries_an_excluded_keyword`
#: qui tient l'exclusion. Le jour où un roster joué porte l'un de ces mots-clés, il tombe — et ce
#: roster étant lui-même nouveau, le bit se paie alors dans un retrain que ce changement rend de
#: toute façon nécessaire.
KEYWORDS_WITHOUT_BIT = frozenset({"BEASTS", "SWARM"})


def _keywords_passed_to_unit_has_keyword() -> Set[str]:
    """Littéraux passés à `movement_handlers._unit_has_keyword` dans tout `engine/`.

    CINQUIÈME source, et la plus peuplée : six sites (`movement_handlers` ×4,
    `charge_handlers` ×2) demandent `fly` par cette fonction, en MINUSCULES et sans passer par
    aucune constante. Une constante ne peut pas les représenter — l'argument est écrit sur place
    à chaque appel — donc on lit les appels eux-mêmes, par AST et non par expression régulière :
    un `grep` ne distingue pas un argument d'une mention en commentaire.

    Portée assumée : seuls les littéraux DIRECTS sont vus. Un appel construisant son argument
    (`_unit_has_keyword(u, kw)`) échapperait, comme les comparaisons de chaînes écrites hors de
    cette fonction (`shared_utils.py:5805` et `:11137`, `fight_handlers.py:4706`, qui lisent
    `monster`/`vehicle`, tous deux munis de leur bit). Ce test ne prétend donc pas à
    l'exhaustivité sur le moteur entier : il couvre les sources NOMMÉES et cet appelant unique.
    """
    keywords: Set[str] = set()
    seen_call = False
    for path in sorted((ROOT / "engine").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if name != "_unit_has_keyword" or len(node.args) < 2:
                continue
            seen_call = True
            argument = node.args[1]
            if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                keywords.add(argument.value.strip().upper())
    # VERT VACANT : une fonction renommée ferait rendre un ensemble vide, donc un test qui passe
    # en ne regardant plus rien. C'est l'appel qu'on exige de trouver, pas seulement un mot-clé.
    assert seen_call, "aucun appel à _unit_has_keyword trouvé — la source a été renommée ?"
    return keywords


def _engine_category_keywords() -> Set[str]:
    """Les mots-clés de catégorie que le MOTEUR consomme, dérivés de ses sources déclarées.

    Dérivés et non recopiés : `BIT_TO_KEYWORD` est une table de test, donc un mot-clé ajouté
    côté moteur ne s'y inscrirait jamais tout seul. Une source n'est vue ici que si elle est une
    constante NOMMÉE ou l'argument littéral d'un appelant unique — c'est pourquoi
    `_MONSTER_OR_VEHICLE_KEYWORDS` a été extraite du littéral qu'elle était.
    """
    keywords = {kw.strip().upper() for kw in _HIDEABLE_KEYWORDS}          # 13.08 / 13.09
    keywords |= {kw.strip().upper() for kw in _FLOOR_CAPABLE_KEYWORDS}    # 13.06
    keywords |= {kw.strip().upper() for kw in _MONSTER_OR_VEHICLE_KEYWORDS}  # 10.06
    keywords |= _keywords_passed_to_unit_has_keyword()                    # 21.03 et move/charge
    # [ANTI-X] 24.03 : découpe INCONDITIONNELLE, la même qu'`attack_sequence.py:203`. Filtrer sur
    # `startswith` sauterait en silence une entrée mal orthographiée que le moteur, lui,
    # découperait quand même — la dérivation serait lâche là où elle doit être exhaustive.
    for rule_id in ANTI_RULE_IDS:
        assert rule_id.startswith(ANTI_RULE_PREFIX), (
            f"{rule_id!r} ne porte pas le préfixe {ANTI_RULE_PREFIX!r} : "
            f"attack_sequence.py:203 le tronquerait quand même"
        )
        keywords.add(rule_id[len(ANTI_RULE_PREFIX):].strip().upper())
    return keywords


def _roster_unit_names() -> Set[str]:
    """Datasheets citées par les rosters JOUÉS — ceux des agents ET ceux des adversaires.

    `config/agents/_p2_rosters/**` en fait partie et n'a pas de segment `rosters` dans son
    chemin (`ai/train.py:748`) : un glob `*/rosters/**` le manquerait entièrement, alors que les
    bits de catégorie sont écrits pour les 20 slots ENNEMIS autant que pour les alliés — une
    unité adverse au mot-clé exclu laisserait l'agent aveugle, verrou au vert.

    Une entrée de `models` est soit un nom, soit un objet de placement portant son `unit_type`
    (112 des 404 entrées) : `str()` sur le second rendrait la repr d'un dict, jamais résolue
    dans le registre, donc silencieusement ignorée.
    """
    names: Set[str] = set()
    paths = sorted((ROOT / "config" / "agents").glob("*/rosters/**/*.json"))
    paths += sorted((ROOT / "config" / "agents" / "_p2_rosters").glob("**/*.json"))
    for path in paths:
        composition = json.loads(path.read_text(encoding="utf-8")).get("composition", [])
        for entry in composition:
            unit_type = entry.get("unit_type")
            if unit_type is not None:
                names.add(str(unit_type))
            for model in entry.get("models", []):
                if isinstance(model, dict):
                    nested = model.get("unit_type")
                    if nested is not None:
                        names.add(str(nested))
                else:
                    names.add(str(model))
    return names


def _weapon_cfg() -> Dict[str, Any]:
    return {
        "ATK": 2, "STR": 4, "AP": 0, "DMG": 1, "NB": 1, "RNG": 24,
        "WEAPON_RULES": [], "code": "test_weapon", "display_name": "Test Bolter",
    }


def _unit_cfg(
    uid: int, player: int, positions: List[Tuple[int, int]], keywords: List[Dict[str, str]]
) -> Dict[str, Any]:
    specs = [{"col": c, "row": r, "HP_CUR": 1, "HP_MAX": 1, "VALUE": 10} for c, r in positions]
    return {
        "id": uid, "player": player, "col": positions[0][0], "row": positions[0][1],
        "unitType": "TestUnit", "DISPLAY_NAME": f"Unit {uid}",
        "HP_CUR": len(specs), "HP_MAX": 1, "MOVE": 6, "T": 4,
        "ARMOR_SAVE": 4, "INVUL_SAVE": 0,
        "RNG_WEAPONS": [_weapon_cfg()], "CC_WEAPONS": [_weapon_cfg()],
        "UNIT_RULES": [], "UNIT_KEYWORDS": keywords,
        "LD": 7, "OC": 2, "VALUE": 10 * len(specs),
        "ICON": "test", "ICON_SCALE": 1.0, "ILLUSTRATION_RATIO": 1.0,
        "BASE_SHAPE": "round", "BASE_SIZE": 1, "MODEL_HEIGHT": 2.5,
        "models": specs,
    }


def _config(ally_keywords, enemy_keywords) -> Dict[str, Any]:
    obs_params = {"obs_size": ObservationBuilder.SQUAD_OBS_SIZE_TARGET}
    return {
        "board": {
            "default": {
                "cols": 120, "rows": 80, "hex_radius": 1.0, "margin": 0.0,
                "wall_hexes": [], "inches_to_subhex": 1,
            }
        },
        "game_rules": {
            "engagement_zone": 1, "engagement_zone_vertical": 5, "max_base_size_hex": 35,
            "unit_model_cohesion_range": 2, "unit_global_cohesion_range": 9,
            "squad_min_neighbors": 1, "cohesion_distance_mode": "euclidean",
        },
        "charge": {"charge_max_distance": 12},
        "move": {
            "can_move_through_enemy_engagement_zone": True,
            "can_move_through_enemy_model": False,
            "can_move_through_friendly_model": True,
        },
        "pve_mode": False,
        "scenario_objectives": [],
        "observation_params": obs_params,
        "training_config": {"observation_params": obs_params, "max_turns_per_episode": 3},
        "units": [
            _unit_cfg(1, 1, [(30, 20), (32, 20)], ally_keywords),
            _unit_cfg(2, 2, [(80, 20)], enemy_keywords),
        ],
    }


def _engine(ally_keywords, enemy_keywords) -> W40KEngine:
    with patch("engine.w40k_core.load_weapon_damage_table", return_value={}), \
         patch.object(W40KEngine, "_build_reward_configs_for_current_units", return_value={}):
        eng = W40KEngine(config=build_engine_config(_config(ally_keywords, enemy_keywords)))
    eng.reset()
    return eng


def _bits(engine: W40KEngine, family: str, row: int) -> Dict[str, float]:
    obs = engine.obs_builder.build_squad_observation(engine.game_state, "1")
    binv = obs[family][row]
    return {bit: float(binv[unit_bin_index(bit)]) for bit in BIT_TO_KEYWORD}


@pytest.mark.parametrize("bit,keyword", sorted(BIT_TO_KEYWORD.items()))
def test_each_keyword_lights_only_its_own_bit(bit: str, keyword: str) -> None:
    """Un mot-clé allume SON bit, et lui seul — c'est la permutation qui est verrouillée."""
    engine = _engine([{"keywordId": keyword}], [{"keywordId": "INFANTRY"}])

    bits = _bits(engine, "allies_bin", 0)

    assert bits[bit] == 1.0, f"{keyword} déclaré mais le bit '{bit}' est éteint"
    allumes_a_tort = sorted(b for b, v in bits.items() if v == 1.0 and b != bit)
    assert allumes_a_tort == [], f"{keyword} allume aussi {allumes_a_tort}"


@pytest.mark.parametrize("bit,keyword", sorted(BIT_TO_KEYWORD.items()))
def test_keywords_are_emitted_for_enemy_entities(bit: str, keyword: str) -> None:
    """Le bit est porté par la CIBLE : sans lui côté ennemi, [ANTI-X] reste inapprenable."""
    engine = _engine([{"keywordId": "INFANTRY"}], [{"keywordId": keyword}])

    bits = _bits(engine, "enemies_bin", 0)

    assert bits[bit] == 1.0, f"entité ennemie {keyword} : bit '{bit}' éteint"


@pytest.mark.parametrize("written", ["vehicle", "VEHICLE", " Vehicle "])
def test_keyword_reading_is_case_and_space_insensitive(written: str) -> None:
    """Le corpus de rosters mélange les casses ; la normalisation est celle de [ANTI-X]."""
    engine = _engine([{"keywordId": written}], [{"keywordId": "INFANTRY"}])

    assert _bits(engine, "allies_bin", 0)["kw_vehicle"] == 1.0


def test_unit_without_any_category_keyword_lights_nothing() -> None:
    """Une datasheet sans mot-clé de catégorie n'allume rien — 0 n'est pas une valeur par défaut."""
    engine = _engine([{"keywordId": "ADEPTUS ASTARTES"}], [{"keywordId": "INFANTRY"}])

    assert _bits(engine, "allies_bin", 0) == {bit: 0.0 for bit in BIT_TO_KEYWORD}


def test_missing_unit_keywords_raises() -> None:
    """T1 : la clé absente lève, au lieu d'écrire « aucune catégorie » en silence."""
    engine = _engine([{"keywordId": "INFANTRY"}], [{"keywordId": "INFANTRY"}])
    unit = next(u for u in engine.game_state["units"] if str(u["id"]) == "1")
    del unit["UNIT_KEYWORDS"]

    with pytest.raises(ConfigurationError, match="UNIT_KEYWORDS"):
        engine.obs_builder.build_squad_observation(engine.game_state, "1")


@pytest.mark.parametrize("bit,keyword", sorted(BIT_TO_KEYWORD.items()))
def test_registry_datasheets_light_their_bit(bit: str, keyword: str) -> None:
    """Contrat sur le registre RÉEL : une datasheet portant le mot-clé allume bien son bit."""
    units = UnitRegistry().units
    carriers = {
        name: unit["UNIT_KEYWORDS"]
        for name, unit in units.items()
        if any(
            str(entry["keywordId"]).strip().upper() == keyword
            for entry in unit["UNIT_KEYWORDS"]
        )
    }
    # Énumération non vide : sans porteur réel, l'assertion suivante serait verte à vide.
    assert carriers, f"aucune datasheet du registre ne porte {keyword} — le contrat ne teste rien"

    name, keywords = sorted(carriers.items())[0]
    engine = _engine(keywords, [{"keywordId": "INFANTRY"}])

    assert _bits(engine, "allies_bin", 0)[bit] == 1.0, f"{name} porte {keyword}, bit '{bit}' éteint"


def test_present_stays_the_last_field() -> None:
    """Convention §0.37 : `present` est le DERNIER champ, les bits insérés ne l'ont pas bougé."""
    assert UNIT_BIN_FIELDS[-1] == "present"


# ---------------------------------------------------------------------------
# Contrat MOTEUR → OBSERVATION (2026-09-09)
# ---------------------------------------------------------------------------
#
# Les tests ci-dessus parcourent tous `BIT_TO_KEYWORD`, une table RECOPIÉE dans ce fichier : ils
# prouvent que chaque bit DÉCLARÉ s'allume, jamais que chaque mot-clé CONSOMMÉ par le moteur
# possède un bit. Un mot-clé ajouté côté moteur n'aurait donc fait échouer aucun test, et l'agent
# aurait subi une catégorie qu'il ne perçoit pas — le motif exact fermé côté règles d'unité par
# `test_every_registered_obs_id_is_in_the_vocabulary` (`test_squad_obs_unit_rules.py`).
#
# Les deux tests suivants ferment les deux moitiés : (a) tout mot-clé consommé a un bit ou une
# exclusion actée, (b) aucune unité réellement jouée ne porte un mot-clé exclu.


def test_every_engine_category_keyword_has_a_bit_or_an_acknowledged_exclusion() -> None:
    """(a) Sens MOTEUR → OBSERVATION : rien de consommé ne reste invisible par accident."""
    consommes = _engine_category_keywords()
    # VERT VACANT : une dérivation qui rendrait un ensemble vide passerait sans rien vérifier.
    assert len(consommes) >= 5, f"dérivation suspecte, seulement {sorted(consommes)}"

    avec_bit = set(BIT_TO_KEYWORD.values())
    orphelins = sorted(consommes - avec_bit - KEYWORDS_WITHOUT_BIT)

    assert orphelins == [], (
        f"mots-clés lus par le moteur sans bit d'observation ni exclusion actée : {orphelins}. "
        f"Soit leur ajouter un bit dans UNIT_BIN_FIELDS (coût : 32 scalaires chacun et un "
        f"retrain --new), soit les inscrire dans KEYWORDS_WITHOUT_BIT en disant POURQUOI."
    )

    # Contre-épreuve : une exclusion ne survit que tant que le moteur lit vraiment le mot-clé.
    # Sans elle, une exclusion resterait après le retrait de sa source et masquerait un bit mort.
    obsoletes = sorted(KEYWORDS_WITHOUT_BIT - consommes)
    assert obsoletes == [], (
        f"exclusions devenues sans objet — le moteur ne lit plus {obsoletes}, "
        f"les retirer de KEYWORDS_WITHOUT_BIT"
    )


def test_no_played_roster_unit_carries_an_excluded_keyword() -> None:
    """(b) Ce qui DATE l'exclusion : elle ne vaut que tant qu'aucune unité jouée n'est concernée.

    Périmètre : les rosters JOUÉS — agents et adversaires —, pas `UnitRegistry` entier. Le
    catalogue compte trois porteurs (`FenrisianWolf`, `Mucolid`, `RipperSwarm`) qu'aucun roster
    ne convoque ; les confondre rendrait ce test rouge sans que rien ne soit cassé.
    """
    registry = UnitRegistry().units
    joues = {name: registry[name] for name in _roster_unit_names() if name in registry}
    # VERT VACANT : une lecture de roster qui ne résoudrait aucune datasheet passerait à vide.
    assert len(joues) >= 20, f"seulement {len(joues)} datasheets résolues depuis les rosters"

    porteurs = {
        name: sorted(
            str(entry["keywordId"]).strip().upper()
            for entry in unit["UNIT_KEYWORDS"]
            if str(entry["keywordId"]).strip().upper() in KEYWORDS_WITHOUT_BIT
        )
        for name, unit in joues.items()
        if any(
            str(entry["keywordId"]).strip().upper() in KEYWORDS_WITHOUT_BIT
            for entry in unit["UNIT_KEYWORDS"]
        )
    }

    assert porteurs == {}, (
        f"un roster joué porte désormais un mot-clé exclu : {porteurs}. L'exclusion de "
        f"KEYWORDS_WITHOUT_BIT ne tient plus — soit lui ajouter son bit dans UNIT_BIN_FIELDS "
        f"(32 scalaires, retrain --new, à payer dans celui que ce roster impose déjà), soit "
        f"retirer du roster l'unité qui l'a fait entrer. Le choix est à faire, pas à deviner."
    )
