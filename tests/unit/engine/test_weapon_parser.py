from pathlib import Path

import pytest

from engine.weapons.parser import ArmoryParser


def test_get_armory_path_supports_canonical_and_exact_case(tmp_path: Path) -> None:
    parser = ArmoryParser()
    parser._project_root = tmp_path

    canonical = tmp_path / "frontend" / "src" / "roster" / "spaceMarine" / "armory.ts"
    canonical.parent.mkdir(parents=True, exist_ok=True)
    canonical.write_text("export const SPACE_MARINE_ARMORY: Record<string, Weapon> = {\n};", encoding="utf-8")
    assert parser._get_armory_path("SpaceMarine") == canonical

    canonical.unlink()
    exact = tmp_path / "frontend" / "src" / "roster" / "SpaceMarine" / "armory.ts"
    exact.parent.mkdir(parents=True, exist_ok=True)
    exact.write_text("export const SPACE_MARINE_ARMORY: Record<string, Weapon> = {\n};", encoding="utf-8")
    assert parser._get_armory_path("SpaceMarine") == exact


@pytest.mark.anomaly
def test_parse_armory_file_extracts_weapon_and_resolves_dice_constant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parser = ArmoryParser()
    armory_path = tmp_path / "armory.ts"
    armory_path.write_text(
        """
const TWO_D6: DiceValue = "2D6";
export const TEST_ARMORY: Record<string, Weapon> = {
  plasma: {
    code_name: "plasma",
    display_name: "Plasma Gun",
    RNG: 24,
    NB: TWO_D6,
    ATK: 3,
    STR: 8,
    AP: 2,
    DMG: D6+1,
    WEAPON_RULES: ["ASSAULT"]
  }
};
""",
        encoding="utf-8",
    )

    monkeypatch.setattr("engine.weapons.parser.get_weapon_rules_registry", lambda: object())
    validated: list[dict] = []

    def _spy_validate(weapon, registry):
        validated.append(weapon)
        return ["parsed-rule"]

    monkeypatch.setattr("engine.weapons.parser.validate_weapon_rules_field", _spy_validate)

    weapons = parser._parse_armory_file(armory_path)
    assert "plasma" in weapons
    assert weapons["plasma"]["NB"] == "2D6"
    assert weapons["plasma"]["DMG"] == "D6+1"

    # Le fail-fast est l'APPEL de validation : il doit rester, sur chaque arme.
    assert [w["display_name"] for w in validated] == ["Plasma Gun"]
    # ...mais son retour ne doit PAS etre re-stocke sur l'arme. `_parsed_rules` etait le canal
    # d'entree du defunt WeaponRulesApplier ; la clé n'a aucun lecteur et ne doit pas revenir
    # (elle forcerait api_server a l'exclure de nouveau pour ne pas la faire fuiter). Ce test
    # rougit si quelqu'un remet un cache sur le dict d'arme.
    assert "_parsed_rules" not in weapons["plasma"]
    assert not [k for k in weapons["plasma"] if k.startswith("_parsed")]


def test_parse_armory_file_requires_weapon_rules(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    parser = ArmoryParser()
    armory_path = tmp_path / "armory.ts"
    armory_path.write_text(
        """
export const TEST_ARMORY: Record<string, Weapon> = {
  bolter: {
    code_name: "bolter",
    display_name: "Bolter",
    RNG: 24,
    NB: 2,
    ATK: 3,
    STR: 4,
    AP: 1,
    DMG: 1
  }
};
""",
        encoding="utf-8",
    )
    monkeypatch.setattr("engine.weapons.parser.get_weapon_rules_registry", lambda: object())
    monkeypatch.setattr("engine.weapons.parser.validate_weapon_rules_field", lambda weapon, registry: [])
    with pytest.raises(ValueError, match=r"missing required WEAPON_RULES"):
        parser._parse_armory_file(armory_path)


def test_get_weapons_raises_when_weapon_missing(tmp_path: Path) -> None:
    parser = ArmoryParser()
    parser._cache["FactionX"] = {"known": {"display_name": "Known"}}
    with pytest.raises(KeyError, match=r"Weapon 'missing' not found"):
        parser.get_weapons("FactionX", ["known", "missing"])


def test_parsed_weapon_rule_never_survives_into_weapon_dicts() -> None:
    """Invariant de PROVENANCE : aucun `ParsedWeaponRule` ne peut exister hors du parseur.

    Ce type n'est construit qu'en `engine/weapons/rules.py` (`parse_weapon_rule`). Son unique
    chemin de production, `ArmoryParser`, jette le retour de `validate_weapon_rules_field`
    (la validation fail-fast est l'appel, pas son resultat). Aucune instance ne survit donc
    dans le processus, ce qui rend inatteignables les branches `isinstance(..., ParsedWeaponRule)`
    retirees le 2026-07-29 de `_orjson_default`, `make_json_serializable` et
    `_serialize_weapon_for_json`, ainsi que les tests de forme `hasattr(entry, "rule")` de
    `engine/utils/weapon_helpers`.

    Ce test rougit si quelqu'un remet un objet regle dans un dict d'arme : ce serait une
    regression SILENCIEUSE (la charge API porterait un dict `{rule, parameter, definition}`
    la ou le front attend une chaine), pas un plantage.

    Note : l'inatteignabilite a aussi ete verifiee par balayage du tas (`gc.get_objects()`,
    zero instance vivante apres parsing des 153 armes des deux factions). Ce balayage n'est PAS
    commite : il est global, couteux, et declenche un FutureWarning de torch en parcourant le
    tas. L'assertion utile en regression est celle sur le contenu des dicts d'armes, ci-dessous.
    """
    from engine.weapons import get_armory_parser
    from engine.weapons.rules import ParsedWeaponRule

    parser = get_armory_parser()
    armory = parser.get_armory("spaceMarine")
    assert armory, "armurerie spaceMarine vide : le test ne prouverait rien"

    for code, weapon in armory.items():
        rules = weapon["WEAPON_RULES"]
        assert isinstance(rules, list), f"{code}: WEAPON_RULES doit etre une liste"
        for entry in rules:
            assert isinstance(entry, str), (
                f"{code}: entree WEAPON_RULES de type {type(entry).__name__}, attendu str"
            )
        assert not any(isinstance(v, ParsedWeaponRule) for v in weapon.values())


def test_aucune_armurerie_ne_declare_un_seuil_anti_illegal() -> None:
    """BALAYAGE DE CORPUS : tout `[ANTI-X Y+]` des armureries a un Y+ jouable (>= 2, 05.02).

    Le garde de `attack_sequence.anti_threshold_of` ne se declenche que sur l'arme REELLEMENT
    resolue pendant une partie : une coquille dans une faction peu jouee attendrait le combat
    qui la fait sortir. Ce balayage la trouve au commit.

    Ce n'est pas theorique — `urty_syringe` (PainBoy ork) declarait `ANTI_INFANTRY:1`, ce qui
    donnait `crit_wound_on = min(6, 1) = 1` : CHAQUE jet de blessure, 1 naturel compris, etait
    une blessure critique reussie contre de l'infanterie, et la ligne d'attaque disparaissait
    du `step.log` (le formateur levait, `log_action` avalait). Corrige a 2+ dans la meme
    livraison.

    Les factions sont ENUMEREES depuis le disque, jamais listees en dur : une faction ajoutee
    sans etre inscrite dans le test serait un trou muet, exactement le mode d'echec vise.
    """
    from engine.phase_handlers.attack_sequence import ANTI_RULE_IDS, anti_threshold_of
    from engine.utils.weapon_helpers import _iter_weapon_rules, weapon_has_rule
    from engine.weapons import get_armory_parser

    roster_dir = Path(__file__).resolve().parents[3] / "frontend" / "src" / "roster"
    factions = sorted(path.parent.name for path in roster_dir.glob("*/armory.ts"))
    assert factions, f"aucune armurerie trouvee sous {roster_dir} : le test ne prouverait rien"

    parser = get_armory_parser()
    declarations = 0
    parametres = 0
    for faction in factions:
        armory = parser.get_armory(faction)
        assert armory, f"armurerie {faction} vide : le balayage ne prouverait rien"
        for code, weapon in armory.items():
            for rule_id in ANTI_RULE_IDS:
                if not weapon_has_rule(weapon, rule_id):
                    continue
                declarations += 1
                anti_threshold_of(weapon, rule_id)
            # MEME CLASSE DE DEFAUT, meme balayage : [RAPID FIRE:X], [SUSTAINED HITS:X],
            # [MELTA:X], [BLAST:X], [CLEAVE:X] sont refuses a <= 0 par le formateur de journal
            # (`step_logger._additive_rule_tokens`) — donc, la aussi, dans le `except` de
            # `log_action`. Un `BLAST:0` mangerait les lignes en silence exactement comme
            # `ANTI_INFANTRY:1` le faisait. Le corpus est la seule barriere avant le run.
            for name, param in _iter_weapon_rules(weapon):
                if not param:
                    continue  # forme NUE ([BLAST]), legale : 24.05
                parametres += 1
                assert param.lstrip("-").isdigit() and int(param) > 0, (
                    f"{faction}/{code} : parametre non entier ou <= 0 sur {name}:{param}"
                )

    # VERT VACANT : un balayage qui ne rencontre aucune declaration [ANTI] passe au vert sans
    # rien avoir regarde. Le corpus en porte plusieurs, dans plusieurs factions.
    assert declarations >= 5 and parametres >= 15, (
        f"seulement {declarations} declaration(s) [ANTI] et {parametres} parametre(s) "
        f"balayes sur {len(factions)} factions — le corpus ou l'enumeration a change"
    )
