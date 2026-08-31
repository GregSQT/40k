"""Substitution de noms d'affichage pour les démos (DEMO_MODE=1).

Activé uniquement si la variable d'environnement DEMO_MODE vaut "1", "true" ou "yes".
Les mappings sont lus dans config/demo_overrides.json au démarrage du process.

Substitution par sous-chaîne : la clé "Intercessor" → "Soldier" renomme
"Assault Intercessor", "Heavy Intercessor", etc. sans entrées supplémentaires.
Correspondance exacte prioritaire sur la substitution partielle.

Attention : les remplacements s'appliquent séquentiellement. Si le résultat d'un
remplacement contient la clé d'un autre, ce second remplacement s'applique aussi.
Garder les clés disjointes pour éviter cet effet de cascade.
"""

import json
import os
from pathlib import Path
from typing import Any

_ACTIVE = os.environ.get("DEMO_MODE", "").strip() in ("1", "true", "yes")

_unit_names: dict[str, str] = {}
_weapon_names: dict[str, str] = {}
_ability_names: dict[str, str] = {}


def _load() -> None:
    overrides_path = Path(__file__).parent.parent / "config" / "demo_overrides.json"
    try:
        data: dict[str, Any] = json.loads(overrides_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise FileNotFoundError(
            f"DEMO_MODE=1 est activé mais config/demo_overrides.json est introuvable : {exc}"
        ) from exc
    _unit_names.update(data.get("unit_names", {}))
    _weapon_names.update(data.get("weapon_names", {}))
    _ability_names.update(data.get("ability_names", {}))


if _ACTIVE:
    _load()


def _sub(name: str, mapping: dict[str, str]) -> str:
    if name in mapping:
        return mapping[name]
    result = name
    for original, replacement in mapping.items():
        result = result.replace(original, replacement)
    return result


def _patch_weapons(weapons: Any) -> None:
    if not isinstance(weapons, list):
        return
    for w in weapons:
        if isinstance(w, dict) and "display_name" in w:
            w["display_name"] = _sub(w["display_name"], _weapon_names)


def _patch_obj_weapons(obj: dict[str, Any]) -> None:
    for wkey in ("RNG_WEAPONS", "CC_WEAPONS"):
        _patch_weapons(obj.get(wkey))


def apply_to_unit(unit: dict[str, Any]) -> None:
    """Patche les noms d'affichage d'un dict unité en place. No-op si DEMO_MODE non actif.

    Ne mute jamais les objets rule de UNIT_RULES : chaque règle dont displayName
    change est remplacée par un nouveau dict pour ne pas toucher l'état moteur partagé.
    """
    if not _ACTIVE:
        return
    if "DISPLAY_NAME" in unit:
        unit["DISPLAY_NAME"] = _sub(unit["DISPLAY_NAME"], _unit_names)
    _patch_obj_weapons(unit)
    for m in unit.get("models") or []:
        if isinstance(m, dict):
            if "DISPLAY_NAME" in m:
                m["DISPLAY_NAME"] = _sub(m["DISPLAY_NAME"], _unit_names)
            _patch_obj_weapons(m)
    rules = unit.get("UNIT_RULES")
    if isinstance(rules, list):
        new_rules = []
        for rule in rules:
            if isinstance(rule, dict) and "displayName" in rule:
                patched = _sub(rule["displayName"], _ability_names)
                if patched != rule["displayName"]:
                    rule = {**rule, "displayName": patched}
            new_rules.append(rule)
        unit["UNIT_RULES"] = new_rules
