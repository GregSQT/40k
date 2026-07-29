"""V11 T-A — [CLOSE-QUARTERS] 24.07 remplace [PISTOL] partout : verrou anti-réapparition.

**PDF 24.27** : « [PISTOL] and [CLOSE-QUARTERS] are identical for all rules purposes. See
[CLOSE-QUARTERS]. *Designer's Note*: [PISTOL] is a pre-existing ability that will be superseded
by [CLOSE-QUARTERS] as this edition of Warhammer 40,000 progresses. »

Le renommage est donc du **vocabulaire**, pas une règle : les deux termes sont fonctionnellement
identiques. Il est fait pour supprimer l'ambiguïté (décision utilisateur, 2026-07-26), et ce
fichier existe pour qu'il ne se défasse pas — un identifiant `PISTOL` réintroduit dans une
armory ou dans un prédicat moteur ferait diverger silencieusement la donnée et le code.

Ce qui est verrouillé :
- la règle est déclarée sous la clé `CLOSE_QUARTERS` dans `config/weapon_rules.json` ;
- aucune arme d'aucune armory ne déclare encore `PISTOL` ;
- aucun identifiant `PISTOL` ne subsiste dans `engine/` ni `ai/` ;
- le NOM d'arme `pistol` (bolt pistol, plasma pistol…) reste intact — c'est un nom, pas une
  règle, et le renommage ne doit pas y toucher (piège rencontré pendant la migration).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import List

PROJECT_ROOT = Path(__file__).resolve().parents[3]

# Mentions HISTORIQUES autorisées : elles citent 24.27 (« anciennement [PISTOL] »), elles ne
# déclarent rien. Toute autre occurrence est un identifiant oublié.
_ALLOWED_HISTORICAL = re.compile(r"24\.27|Formerly named|anciennement", re.IGNORECASE)


def _python_sources() -> List[Path]:
    files: List[Path] = []
    for sub in ("engine", "ai"):
        files.extend(p for p in (PROJECT_ROOT / sub).rglob("*.py") if "__pycache__" not in p.parts)
    return files


def test_weapon_rules_config_declares_close_quarters() -> None:
    """La règle vit sous la clé `CLOSE_QUARTERS`, et `PISTOL` a disparu du registre."""
    raw = json.loads((PROJECT_ROOT / "config" / "weapon_rules.json").read_text(encoding="utf-8"))
    rules = raw.get("weapon_rules", raw)
    assert "CLOSE_QUARTERS" in rules, "la regle CLOSE_QUARTERS est absente du registre"
    assert "PISTOL" not in rules, "l'ancienne cle PISTOL subsiste dans weapon_rules.json"
    entry = rules["CLOSE_QUARTERS"]
    assert entry["name"] == "Close-quarters"
    # Le registre est la source du tooltip frontend (GameLog lit les cles ET les noms).
    assert "10.06" in entry["description"], "la description doit ancrer le type de tir 10.06"


def test_no_armory_weapon_declares_the_old_identifier() -> None:
    """Aucune arme des 6 armories ne déclare encore `PISTOL` dans ses WEAPON_RULES."""
    offenders: List[str] = []
    for armory in (PROJECT_ROOT / "frontend" / "src" / "roster").glob("*/armory.ts"):
        for rules_block in re.findall(r"WEAPON_RULES:\s*\[([^\]]*)\]", armory.read_text(encoding="utf-8")):
            if re.search(r'"PISTOL"', rules_block):
                offenders.append(f"{armory.relative_to(PROJECT_ROOT)}: {rules_block.strip()}")
    assert not offenders, "armes declarant encore PISTOL :\n" + "\n".join(offenders)


# La RÈGLE s'écrit en MAJUSCULES (`PISTOL`), les NOMS d'armes en minuscules (« bolt pistol »,
# `plasma_pistol_supercharge`). C'est cette frontière qui rend le verrou précis : interdire
# `pistol` en minuscules rendrait le test faux (il condamnerait des noms d'armes légitimes),
# et n'interdire que la majuscule laisserait passer les anciens identifiants Python. On liste
# donc explicitement les seconds — ils sont connus, c'est la migration qui les a produits.
_FORMER_IDENTIFIERS = (
    "_weapon_has_pistol_rule",
    "_shooting_with_pistol",
    "current_weapon_is_pistol",
    "weapon_is_pistol",
    "declared_pistol",
    "declared_nonpistol",
    "is_pistol",
    "has_pistol",
    "pistol_free",
    "pistol_weapons",
    "pistol_shots",
    "pistol_applied",
    "adjacent_non_pistol",
)


def test_no_pistol_rule_identifier_left_in_engine_or_ai() -> None:
    """Plus aucun identifiant de RÈGLE `PISTOL` dans le code moteur ou IA.

    Distingue volontairement la règle (majuscules) des NOMS d'armes (« bolt pistol ») : le
    renommage porte sur la première, jamais sur les seconds — piège réel de la migration, où
    un remplacement en minuscules avait corrompu un nom d'arme et un mot français.
    """
    offenders: List[str] = []
    for path in _python_sources():
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            hit = re.search(r"\bPISTOL\b", line) or any(idf in line for idf in _FORMER_IDENTIFIERS)
            if not hit or _ALLOWED_HISTORICAL.search(line):
                continue
            offenders.append(f"{path.relative_to(PROJECT_ROOT)}:{lineno}: {line.strip()}")
    assert not offenders, "identifiants de regle PISTOL restants :\n" + "\n".join(offenders)


def test_weapon_display_names_are_untouched() -> None:
    """Le NOM d'arme « pistol » survit : on renomme une RÈGLE, pas des armes.

    Piège réel de la migration : un remplacement en minuscules avait transformé
    `'bolt pistol'` en `'bolt close_quarters'` et le mot français « pistolet » en
    « close_quarterset ».
    """
    armory = (PROJECT_ROOT / "frontend" / "src" / "roster" / "spaceMarine" / "armory.ts").read_text(
        encoding="utf-8"
    )
    assert "Bolt Pistol" in armory, "les display_name d'armes ne doivent PAS etre renommes"
    for path in _python_sources():
        text = path.read_text(encoding="utf-8")
        assert "close_quarterset" not in text, f"mot francais corrompu par le renommage : {path}"
        assert "bolt close_quarters" not in text, f"nom d'arme corrompu par le renommage : {path}"


def test_engine_predicate_is_renamed_and_live() -> None:
    """Le prédicat moteur reconnaît la règle renommée.

    2026-07-29 — le prédicat visé n'est plus `_weapon_has_close_quarters_rule` (doublon laxiste
    supprimé) mais `weapon_has_rule(weapon, "CLOSE_QUARTERS")`, auquel le tir délègue désormais.
    L'assertion de fond est inchangée : c'est le nouvel identifiant qui déclenche, pas l'ancien.
    """
    from engine.utils.weapon_helpers import weapon_has_rule

    assert weapon_has_rule({"WEAPON_RULES": ["CLOSE_QUARTERS"]}, "CLOSE_QUARTERS") is True
    assert weapon_has_rule({"WEAPON_RULES": ["ASSAULT"]}, "CLOSE_QUARTERS") is False
    # L'ancien identifiant ne doit plus rien déclencher : sinon une armory non migrée
    # continuerait de « marcher » et la migration se déferait en silence.
    assert weapon_has_rule({"WEAPON_RULES": ["PISTOL"]}, "CLOSE_QUARTERS") is False
